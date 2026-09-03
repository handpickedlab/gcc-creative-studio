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
"""Deterministic QA checks over translated segments.

These are the trust layer of document translation: numbers must survive
translation exactly, protected names must survive verbatim, and suspicious
length blow-ups get flagged for human review.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from enum import Enum

from src.translations.documents import locale_format
from src.translations.documents.locale_format import LocaleFormat
from src.translations.documents.model import Segment, SegmentKind
from src.translations.documents.translator import GlossaryEntry


class Severity(str, Enum):
    ERROR = "error"  # blocks export
    WARNING = "warning"  # needs a human look


@dataclass
class Finding:
    segment_id: int
    check: str
    severity: Severity
    detail: str
    # Structured context so the UI can show a term-level diff instead of
    # parsing prose out of `detail`.
    term: str | None = None
    expected: str | None = None
    found: str | None = None


# Number tokens: digit groups incl. thousands/decimal separators ("319,915",
# "4.6", "2:403"); single digits count too.
_NUMBER = re.compile(r"\d+(?:[.,:]\d+)*")

_LENGTH_RATIO = 1.8
_LENGTH_MIN_SOURCE = 40


def _numbers(text: str) -> Counter:
    return Counter(_NUMBER.findall(text))


def _pair_up(
    source: Counter, target: Counter, variants: dict[str, str]
) -> tuple[Counter, Counter]:
    """Matches source figures against the target's, accepting each figure's
    localised spelling as the same figure. Returns (missing, added)."""
    remaining = Counter(target)
    missing: Counter = Counter()
    for token, count in source.items():
        for _ in range(count):
            for form in (token, variants.get(token)):
                if form and remaining[form] > 0:
                    remaining[form] -= 1
                    break
            else:
                missing[token] += 1
    return missing, +remaining


def check_numbers(
    segments: list[Segment], fmt: LocaleFormat | None = None
) -> list[Finding]:
    """Every number in the source must appear in the translation, and no
    new numbers may be introduced.

    Exact-match by default. When the export will renotate figures (`fmt`),
    a figure already carrying the target market's spelling counts as
    reproduced: the model is told to copy figures verbatim, but one that
    localised a figure anyway did not change its value.
    """
    findings = []
    for seg in segments:
        if seg.translation is None:
            continue
        source, target = _numbers(seg.text), _numbers(seg.translation)
        if source == target:
            continue
        variants = (
            locale_format.number_plan(
                seg.text, fmt, conservative=seg.kind == SegmentKind.HEADING
            )
            if fmt
            else {}
        )
        missing, added = _pair_up(source, target, variants)
        if not missing and not added:
            continue
        parts = []
        if missing:
            parts.append("missing: " + ", ".join(sorted(missing)))
        if added:
            parts.append("added: " + ", ".join(sorted(added)))
        findings.append(
            Finding(
                segment_id=seg.id,
                check="number",
                severity=Severity.ERROR,
                detail="; ".join(parts),
                expected=", ".join(sorted(missing)) or None,
                found=", ".join(sorted(added)) or None,
            )
        )
    return findings


def check_do_not_translate(
    segments: list[Segment], terms: list[str]
) -> list[Finding]:
    findings = []
    for seg in segments:
        if seg.translation is None:
            continue
        for term in terms:
            if seg.text.count(term) > seg.translation.count(term):
                findings.append(
                    Finding(
                        segment_id=seg.id,
                        check="dnt",
                        severity=Severity.ERROR,
                        detail=f'"{term}" not reproduced verbatim',
                        term=term,
                        expected=term,
                    )
                )
    return findings


def check_glossary(
    segments: list[Segment], glossary: list[GlossaryEntry]
) -> list[Finding]:
    """Soft check: if a glossary source term occurs, its target term should
    appear. Inflection makes this fuzzy, hence WARNING, never ERROR."""
    findings = []
    for seg in segments:
        if seg.translation is None:
            continue
        source_lower = seg.text.lower()
        target_lower = seg.translation.lower()
        for entry in glossary:
            pattern = r"\b" + re.escape(entry.source.lower()) + r"\b"
            if re.search(pattern, source_lower) and (
                entry.target.lower() not in target_lower
            ):
                findings.append(
                    Finding(
                        segment_id=seg.id,
                        check="glossary",
                        severity=Severity.WARNING,
                        detail=(
                            f'"{entry.source}" translated without '
                            f'"{entry.target}"'
                        ),
                        term=entry.source,
                        expected=entry.target,
                    )
                )
    return findings


def check_length(segments: list[Segment]) -> list[Finding]:
    findings = []
    for seg in segments:
        if seg.translation is None:
            continue
        if (
            len(seg.text) >= _LENGTH_MIN_SOURCE
            and len(seg.translation) > _LENGTH_RATIO * len(seg.text)
        ):
            findings.append(
                Finding(
                    segment_id=seg.id,
                    check="length",
                    severity=Severity.WARNING,
                    detail=(
                        f"translation {len(seg.translation)} chars vs "
                        f"source {len(seg.text)}"
                    ),
                )
            )
    return findings


def run_all(
    segments: list[Segment],
    glossary: list[GlossaryEntry] | None = None,
    do_not_translate: list[str] | None = None,
    fmt: LocaleFormat | None = None,
) -> list[Finding]:
    findings = check_numbers(segments, fmt)
    if do_not_translate:
        findings += check_do_not_translate(segments, do_not_translate)
    if glossary:
        findings += check_glossary(segments, glossary)
    findings += check_length(segments)
    return findings
