# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Segment translators: Gemini-backed (batch per section) and a
deterministic pseudo-translator for dry runs and tests."""

from __future__ import annotations

import json
import logging
import time
from typing import Iterable, Protocol

from pydantic import BaseModel

from src.translations.documents.model import Segment

logger = logging.getLogger(__name__)

# Batch bounds: one API call per section chunk. Small enough that one bad
# generation is cheap to retry, large enough for in-call term consistency.
MAX_BATCH_SEGMENTS = 40
MAX_BATCH_CHARS = 8000

_RETRY_DELAY_SECONDS = 3.0


class GlossaryEntry(BaseModel):
    source: str
    target: str


class _TranslatedSegment(BaseModel):
    id: int
    translation: str


class _TranslationBatch(BaseModel):
    segments: list[_TranslatedSegment]


class SegmentTranslator(Protocol):
    def translate_batch(self, segments: list[Segment]) -> dict[int, str]:
        """Returns translations keyed by segment id (may miss ids)."""


def iter_batches(
    segments: Iterable[Segment],
    max_segments: int = MAX_BATCH_SEGMENTS,
    max_chars: int = MAX_BATCH_CHARS,
) -> Iterable[list[Segment]]:
    """Chunks segments, keeping section boundaries intact.

    Segments of the same section stay together until a size bound is hit,
    so each API call carries one coherent context.
    """
    batch: list[Segment] = []
    chars = 0
    section: tuple[str, ...] | None = None
    for seg in segments:
        boundary = section is not None and seg.section_path != section
        full = len(batch) >= max_segments or chars + len(seg.text) > max_chars
        if batch and (boundary or full):
            yield batch
            batch, chars = [], 0
        section = seg.section_path
        batch.append(seg)
        chars += len(seg.text)
    if batch:
        yield batch


class PseudoTranslator:
    """Deterministic no-API translator: proves the reinjection pipeline.

    Wraps every segment in guillemets so the output is visibly 'translated'
    while numbers and terms stay byte-identical for the QA checks.
    """

    def translate_batch(self, segments: list[Segment]) -> dict[int, str]:
        return {seg.id: f"«{seg.text}»" for seg in segments}


class GeminiSegmentTranslator:
    """Translates section batches with Gemini structured output."""

    def __init__(
        self,
        client,
        model_id: str,
        target_language: str,
        glossary: list[GlossaryEntry] | None = None,
        do_not_translate: list[str] | None = None,
        attempts: int = 3,
        instruction: str | None = None,
    ):
        self.client = client
        self.model_id = model_id
        self.target_language = target_language
        self.glossary = glossary or []
        self.do_not_translate = do_not_translate or []
        self.attempts = attempts
        # Reviewer steering for single-segment re-translation
        # (e.g. "more formal", "use 'reële waarde'").
        self.instruction = instruction

    def _build_prompt(self, segments: list[Segment]) -> str:
        path = " > ".join(segments[0].section_path) or "(front matter)"
        lines = [
            "You are translating segments of an audited corporate annual "
            f"report (IFRS financial statements) into {self.target_language}.",
            f"Current section: {path}",
            "",
            "Rules:",
            "- Formal financial/legal register; use the established "
            f"{self.target_language} terminology for IFRS and statutory terms.",
            "- Translate each segment on its own; segments are paragraphs, "
            "headings or table labels from the section above.",
            "- Reproduce every number, date, currency amount and note "
            "reference (e.g. '2.19') exactly as written.",
            "- Keep heading numbering prefixes (e.g. '2.19') in place.",
            "- Do not add, merge, drop or reorder segments: return exactly "
            "one translation per input id.",
        ]
        if self.do_not_translate:
            lines.append(
                "- Never translate these names; reproduce them verbatim: "
                + ", ".join(f'"{t}"' for t in self.do_not_translate)
            )
        if self.glossary:
            lines.append(
                "- Apply this glossary strictly (inflect to fit naturally):"
            )
            lines.extend(
                f'    "{e.source}" -> "{e.target}"' for e in self.glossary
            )
        if self.instruction:
            lines.append(
                f"- Reviewer instruction for this translation: "
                f"{self.instruction}"
            )
        lines.append("")
        lines.append("Segments (JSON):")
        lines.append(
            json.dumps(
                [{"id": s.id, "text": s.text} for s in segments],
                ensure_ascii=False,
            )
        )
        return "\n".join(lines)

    def translate_batch(self, segments: list[Segment]) -> dict[int, str]:
        from google.genai import types  # deferred: heavy import

        prompt = self._build_prompt(segments)
        wanted = {s.id for s in segments}
        last_error: Exception | None = None
        for attempt in range(self.attempts):
            try:
                response = self.client.models.generate_content(
                    model=self.model_id,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=_TranslationBatch,
                        temperature=0,
                    ),
                )
                batch = _TranslationBatch.model_validate(
                    json.loads(response.text or "{}")
                )
                results = {
                    s.id: s.translation
                    for s in batch.segments
                    if s.id in wanted
                }
                missing = wanted - results.keys()
                if missing:
                    logger.warning(
                        "Batch returned %s/%s segments; missing %s",
                        len(results),
                        len(wanted),
                        sorted(missing),
                    )
                return results
            except Exception as e:  # transient API errors, malformed JSON
                last_error = e
                logger.warning(
                    "Translation batch attempt %s failed: %s", attempt + 1, e
                )
                if attempt + 1 < self.attempts:
                    time.sleep(_RETRY_DELAY_SECONDS * (attempt + 1))
        raise RuntimeError(
            f"translation batch failed after {self.attempts} attempts: "
            f"{last_error}"
        )


def translate_tree(
    segments: list[Segment], translator: SegmentTranslator
) -> list[int]:
    """Translates all given segments in section batches, in place.

    Segments the translator failed to return are retried once individually;
    ids that still fail are returned to the caller (recorded, not fatal —
    one bad paragraph must never sink a 100-page document).
    """
    failed: list[int] = []
    for batch in iter_batches(segments):
        results = translator.translate_batch(batch)
        for seg in batch:
            if seg.id in results:
                seg.translation = results[seg.id]
        missing = [s for s in batch if s.id not in results]
        for seg in missing:
            try:
                retry = translator.translate_batch([seg])
                if seg.id in retry:
                    seg.translation = retry[seg.id]
                else:
                    failed.append(seg.id)
            except Exception as e:
                logger.error("Segment %s failed to translate: %s", seg.id, e)
                failed.append(seg.id)
    return failed
