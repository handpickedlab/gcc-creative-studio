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


_NUMBER_PREFIX = re.compile(r"^(\d+(?:\.\d+)*)\.?\s")


def make_section_id(
    title: str, positional: str, taken: set[str]
) -> str:
    """A readable id for a heading: its section number.

    Reviewers cite annual-report sections by number ("2.19"), so an explicit
    number in the heading text wins. Word usually renders that number from
    automatic list numbering instead, leaving it out of the text — then the
    heading's position in the outline supplies the same shape.
    """
    match = _NUMBER_PREFIX.match(title.strip())
    base = match.group(1) if match else positional
    candidate = base
    suffix = 2
    while candidate in taken:
        candidate = f"{base}-{suffix}"
        suffix += 1
    taken.add(candidate)
    return candidate


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
    # Review sections are the outline's top two levels; every segment belongs
    # to exactly one, so the UI can key its tree on this.
    section_id: str = ""
    translation: str | None = None
    # Table-cell segments carry their table/row position so the UI can
    # regroup cells into rendered rows; None for body paragraphs.
    table_index: int | None = None
    row_index: int | None = None
    # Outline depth for headings (1 = chapter, 2+ = section); None otherwise.
    heading_level: int | None = None
    # Fully bold paragraphs mark totals rows and table headers.
    bold: bool = False


@dataclass
class Section:
    """A node in the document outline (from heading styles)."""

    id: str
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

    def outline(self) -> list[dict]:
        """The review tree: chapters (level 1) with their sections (level 2).

        Deeper headings fold into their level-2 parent — the review workspace
        navigates two levels, not the document's full nesting. Counts are per
        section, including everything folded into it.
        """
        by_section: dict[str, list[Segment]] = {}
        for seg in self.segments:
            by_section.setdefault(seg.section_id, []).append(seg)

        def summarise(node: Section) -> dict:
            segs = by_section.get(node.id, [])
            tables = {
                s.table_index for s in segs if s.table_index is not None
            }
            return {
                "id": node.id,
                "title": node.title,
                "segments": len(segs),
                "translatable": len(
                    [s for s in segs if s.kind.translatable]
                ),
                "tables": len(tables),
            }

        chapters = []
        for chapter in self.root.children:
            sections = [summarise(child) for child in chapter.children]
            own = summarise(chapter)
            chapters.append(
                {
                    **own,
                    "sections": sections,
                }
            )
        return chapters
