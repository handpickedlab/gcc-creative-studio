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
"""Data model for the document translation tree."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class SegmentKind(str, Enum):
    HEADING = "heading"
    PROSE = "prose"
    TABLE_LABEL = "table_label"
    # Not translatable: figures, empty-ish cells, table-of-contents entries.
    NUMERIC = "numeric"
    SKIP = "skip"

    @property
    def translatable(self) -> bool:
        return self in (
            SegmentKind.HEADING,
            SegmentKind.PROSE,
            SegmentKind.TABLE_LABEL,
        )


# A cell/paragraph counts as numeric when, digits and figure punctuation
# aside, nothing remains — e.g. "319,915", "(141,764)", "19%", "-", "2.18".
_FIGURE_CHARS = re.compile(r"^[\d\s.,%()€$£±+\-–—−/:*×xX']*$")


def classify_text(text: str, *, in_table: bool, is_heading: bool) -> SegmentKind:
    stripped = text.strip()
    if not stripped:
        return SegmentKind.SKIP
    if _FIGURE_CHARS.match(stripped):
        return SegmentKind.NUMERIC if any(c.isdigit() for c in stripped) else SegmentKind.SKIP
    if is_heading:
        return SegmentKind.HEADING
    return SegmentKind.TABLE_LABEL if in_table else SegmentKind.PROSE


@dataclass
class Segment:
    """One translatable unit: a body paragraph or a table-cell paragraph.

    ``paragraph`` keeps a live reference into the python-docx tree so the
    translation can be written back in place.
    """

    id: int
    text: str
    kind: SegmentKind
    paragraph: Any
    section_path: tuple[str, ...]
    translation: str | None = None


@dataclass
class Section:
    """A node in the document outline (from heading styles)."""

    title: str
    level: int
    segments: list[Segment] = field(default_factory=list)
    children: list[Section] = field(default_factory=list)

    def walk(self):
        yield self
        for child in self.children:
            yield from child.walk()

    def all_segments(self) -> list[Segment]:
        return [s for node in self.walk() for s in node.segments]


@dataclass
class DocumentTree:
    root: Section
    segments: list[Segment]  # every segment, in document order

    @property
    def translatable(self) -> list[Segment]:
        return [s for s in self.segments if s.kind.translatable]

    def stats(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for seg in self.segments:
            counts[seg.kind.value] = counts.get(seg.kind.value, 0) + 1
        counts["total"] = len(self.segments)
        counts["translatable"] = len(self.translatable)
        return counts
