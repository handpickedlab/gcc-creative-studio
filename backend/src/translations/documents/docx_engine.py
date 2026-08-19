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
"""Parse a .docx into a section tree and write translations back in place.

Layout preservation strategy: we never create, move or delete document
elements. Translations are written into the *existing* ``<w:t>`` text nodes
of each paragraph (all text into the first node, remaining nodes emptied),
so styles, tables, images, fields and section properties are untouched.
Known trade-off: mixed inline formatting inside one paragraph (e.g. a bold
word mid-sentence) collapses to the first run's formatting.
"""

from __future__ import annotations

import logging
import re

from docx import Document as open_docx
from docx.document import Document
from docx.table import Table
from docx.text.paragraph import Paragraph

from src.translations.documents.model import (
    DocumentTree,
    Section,
    Segment,
    SegmentKind,
    classify_text,
    make_section_id,
)

logger = logging.getLogger(__name__)

_HEADING_STYLE = re.compile(r"^heading\s+(\d+)$", re.IGNORECASE)
_TOC_STYLE = re.compile(r"^toc\b", re.IGNORECASE)
_W_NS = (
    "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
)


def _heading_level(paragraph: Paragraph) -> int | None:
    style = paragraph.style.name if paragraph.style is not None else ""
    match = _HEADING_STYLE.match(style or "")
    return int(match.group(1)) if match else None


def _is_toc(paragraph: Paragraph) -> bool:
    style = paragraph.style.name if paragraph.style is not None else ""
    return bool(_TOC_STYLE.match(style or ""))


def _is_bold(paragraph: Paragraph) -> bool:
    """True when every run carrying text is bold (totals rows, headers)."""
    runs = [r for r in paragraph.runs if r.text.strip()]
    return bool(runs) and all(r.bold for r in runs)


def _own_text_nodes(p_element) -> list:
    """The ``<w:t>`` nodes this paragraph owns.

    A paragraph can *host* a text box, whose own paragraphs live nested
    inside it. Those belong to their own segments, so a recursive search
    would let one paragraph's translation overwrite a text box's content.
    """
    nodes = []
    for node in p_element.findall(f".//{_W_NS}t"):
        parent = node.getparent()
        while parent is not None and parent is not p_element:
            if parent.tag == f"{_W_NS}txbxContent":
                break
            parent = parent.getparent()
        else:
            nodes.append(node)
    return nodes


class DocxTranslationEngine:
    """Owns one open document: parse -> (translate) -> apply -> save."""

    def __init__(self, path_or_stream):
        self.document: Document = open_docx(path_or_stream)
        self.tree = self._parse()

    # --- parsing ----------------------------------------------------------

    def _parse(self) -> DocumentTree:
        root = Section(id="", title="(document)", level=0)
        segments: list[Segment] = []
        # Stack of sections; a new heading pops back to its parent level.
        stack: list[Section] = [root]
        taken_ids: set[str] = set()

        def current() -> Section:
            return stack[-1]

        def review_section() -> Section:
            """The level-1 or level-2 node segments are filed under."""
            for node in reversed(stack):
                if 0 < node.level <= 2:
                    return node
            return root

        table_counter = [0]

        def add_segment(
            paragraph: Paragraph,
            *,
            in_table: bool,
            is_heading: bool,
            table_index: int | None = None,
            row_index: int | None = None,
        ) -> None:
            kind = classify_text(
                paragraph.text, in_table=in_table, is_heading=is_heading
            )
            if kind == SegmentKind.SKIP and not paragraph.text.strip():
                return
            path = tuple(
                s.title for s in stack if s.level > 0
            )
            seg = Segment(
                id=len(segments),
                text=paragraph.text,
                kind=kind,
                paragraph=paragraph,
                section_path=path,
                section_id=review_section().id,
                table_index=table_index,
                row_index=row_index,
                heading_level=(
                    current().level if kind == SegmentKind.HEADING else None
                ),
                bold=_is_bold(paragraph),
            )
            segments.append(seg)
            current().segments.append(seg)

        for item in self.document.iter_inner_content():
            if isinstance(item, Paragraph):
                if _is_toc(item):
                    continue
                level = _heading_level(item)
                if level is not None and item.text.strip():
                    while stack[-1].level >= level:
                        stack.pop()
                    title = item.text.strip()
                    parent = stack[-1]
                    positional = ".".join(
                        [p for p in (parent.id, str(len(parent.children) + 1))
                         if p]
                    )
                    section = Section(
                        id=make_section_id(title, positional, taken_ids),
                        title=title,
                        level=level,
                    )
                    parent.children.append(section)
                    stack.append(section)
                    add_segment(item, in_table=False, is_heading=True)
                else:
                    add_segment(item, in_table=False, is_heading=False)
                self._parse_text_boxes(item, add_segment)
            elif isinstance(item, Table):
                self._parse_table(item, add_segment, table_counter)

        return DocumentTree(root=root, segments=segments)

    def _parse_text_boxes(self, host: Paragraph, add_segment) -> None:
        """Parses paragraphs inside text boxes anchored on this paragraph.

        Text boxes are reached through the drawing markup rather than the
        body flow, so `iter_inner_content` never yields them. Their content
        is real copy (callouts, pull quotes) and must be translated too.
        Any table inside a text box is flattened to its paragraphs — rare
        enough that row/column context isn't worth reconstructing.
        """
        for box in host._p.findall(f".//{_W_NS}txbxContent"):
            for p_element in box.findall(f".//{_W_NS}p"):
                add_segment(
                    Paragraph(p_element, host._parent),
                    in_table=False,
                    is_heading=False,
                )

    def _parse_table(
        self, table: Table, add_segment, table_counter: list[int]
    ) -> None:
        table_index = table_counter[0]
        table_counter[0] += 1
        # A merged cell is yielded once per grid position it spans, all
        # sharing one <w:tc>. Hold the elements themselves: lxml recreates
        # proxies on demand, so id() values get recycled and would collide
        # across unrelated cells — silently dropping them from the parse.
        seen_cells: set = set()
        for row_index, row in enumerate(table.rows):
            for cell in row.cells:
                element = cell._tc
                if element in seen_cells:
                    continue
                seen_cells.add(element)
                for paragraph in cell.paragraphs:
                    add_segment(
                        paragraph,
                        in_table=True,
                        is_heading=False,
                        table_index=table_index,
                        row_index=row_index,
                    )
                for nested in cell.tables:
                    self._parse_table(nested, add_segment, table_counter)

    # --- applying translations ---------------------------------------------

    def apply(self) -> int:
        """Writes every segment's ``translation`` into its paragraph.

        Returns the number of segments applied. Segments without a
        translation (untranslated, numeric, skipped) are left untouched.
        """
        applied = 0
        for seg in self.tree.segments:
            if seg.translation is None or seg.translation == seg.text:
                continue
            texts = _own_text_nodes(seg.paragraph._p)
            if not texts:
                logger.warning(
                    "Segment %s has no text nodes; skipping", seg.id
                )
                continue
            texts[0].text = seg.translation
            # Word drops leading/trailing spaces unless told to preserve.
            texts[0].set(
                "{http://www.w3.org/XML/1998/namespace}space", "preserve"
            )
            for extra in texts[1:]:
                extra.text = ""
            applied += 1
        return applied

    def save(self, path_or_stream) -> None:
        self.document.save(path_or_stream)

    # --- preflight ---------------------------------------------------------

    def tracked_changes(self) -> int:
        """Paragraphs carrying unresolved insertions or deletions.

        Word keeps both versions of revised text in the same paragraph, so
        its plain text reads as a garbled mix — the model would translate
        the duplication. The user must accept or reject changes first, which
        only helps if we tell them.
        """
        body = self.document.element.body
        return len(
            [
                p
                for p in body.iter(f"{_W_NS}p")
                if p.find(f".//{_W_NS}ins") is not None
                or p.find(f".//{_W_NS}del") is not None
            ]
        )
