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

from src.translations.documents.model import Segment
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


# Number tokens: digit groups incl. thousands/decimal separators ("319,915",
# "4.6", "2:403"); single digits count too.
_NUMBER = re.compile(r"\d+(?:[.,:]\d+)*")

_LENGTH_RATIO = 1.8
_LENGTH_MIN_SOURCE = 40


def _numbers(text: str) -> Counter:
    return Counter(_NUMBER.findall(text))


def check_numbers(segments: list[Segment]) -> list[Finding]:
    """Every number in the source must appear in the translation, and no
    new numbers may be introduced. Exact-match: number localisation, when
    we add it, happens deterministically *after* this check."""
    findings = []
    for seg in segments:
        if seg.translation is None:
            continue
        source, target = _numbers(seg.text), _numbers(seg.translation)
        if source != target:
            missing = source - target
            added = target - source
            parts = []
            if missing:
                parts.append("missing: " + ", ".join(sorted(missing)))
            if added:
                parts.append("added: " + ", ".join(sorted(added)))
            findings.append(
                Finding(
                    segment_id=seg.id,
                    check="numbers",
                    severity=Severity.ERROR,
                    detail="; ".join(parts),
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
                        check="do_not_translate",
                        severity=Severity.ERROR,
                        detail=f'"{term}" not reproduced verbatim',
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
) -> list[Finding]:
    findings = check_numbers(segments)
    if do_not_translate:
        findings += check_do_not_translate(segments, do_not_translate)
    if glossary:
        findings += check_glossary(segments, glossary)
    findings += check_length(segments)
    return findings
