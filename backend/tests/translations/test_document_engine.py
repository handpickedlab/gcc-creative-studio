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
"""Tests for the docx document-translation engine (parse/apply/QA)."""

import io

import pytest
from docx import Document

from src.translations.documents import qa
from src.translations.documents.docx_engine import DocxTranslationEngine
from src.translations.documents.model import SegmentKind, classify_text
from src.translations.documents.translator import (
    GlossaryEntry,
    PseudoTranslator,
    iter_batches,
    translate_tree,
)


def _fixture_docx() -> io.BytesIO:
    """A miniature annual report: headings, styled prose, a financial table."""
    doc = Document()
    doc.add_heading("1. Management Board Report", level=1)
    p = doc.add_paragraph("We operate ")
    p.add_run("700 stores").bold = True
    p.add_run(" across 11 countries.")
    doc.add_heading("2.19 Right-of-use assets", level=2)
    doc.add_paragraph(
        "The Group recognised an impairment of EUR 1,234 thousand."
    )
    table = doc.add_table(rows=3, cols=3)
    rows = [
        ["€ in thousands", "January 31, 2026", "January 31, 2025"],
        ["Intangible assets", "20,913", "22,210"],
        ["Total assets", "319,915", "-"],
    ]
    for r, values in enumerate(rows):
        for c, value in enumerate(values):
            table.rows[r].cells[c].paragraphs[0].add_run(value)
    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer


class TestClassify:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("319,915", SegmentKind.NUMERIC),
            ("(141,764)", SegmentKind.NUMERIC),
            ("19%", SegmentKind.NUMERIC),
            ("2.18", SegmentKind.NUMERIC),
            ("-", SegmentKind.SKIP),
            ("", SegmentKind.SKIP),
            ("Intangible assets", SegmentKind.TABLE_LABEL),
        ],
    )
    def test_table_cells(self, text, expected):
        assert classify_text(text, in_table=True, is_heading=False) == expected

    def test_prose_and_heading(self):
        assert (
            classify_text("We operate.", in_table=False, is_heading=False)
            == SegmentKind.PROSE
        )
        assert (
            classify_text("2.19 Right-of-use", in_table=False, is_heading=True)
            == SegmentKind.HEADING
        )

    def test_date_with_digits_is_translatable(self):
        assert (
            classify_text("January 31, 2026", in_table=True, is_heading=False)
            == SegmentKind.TABLE_LABEL
        )


class TestParse:
    def test_tree_structure_and_classification(self):
        engine = DocxTranslationEngine(_fixture_docx())
        tree = engine.tree

        top = tree.root.children
        assert [s.title for s in top] == ["1. Management Board Report"]
        assert [c.title for c in top[0].children] == [
            "2.19 Right-of-use assets"
        ]

        stats = tree.stats()
        # 2 headings + 2 prose + 5 table labels (incl. the date columns)
        # are translatable; 3 numeric cells and the "-" cell are not.
        assert stats["heading"] == 2
        assert stats["prose"] == 2
        assert stats["table_label"] == 5
        assert stats["numeric"] == 3
        assert stats["translatable"] == 9

    def test_section_path_inherited(self):
        engine = DocxTranslationEngine(_fixture_docx())
        prose = [
            s for s in engine.tree.segments if s.kind == SegmentKind.PROSE
        ]
        assert prose[1].section_path == (
            "1. Management Board Report",
            "2.19 Right-of-use assets",
        )


class TestApplyRoundTrip:
    def test_translation_lands_and_numbers_survive(self):
        engine = DocxTranslationEngine(_fixture_docx())
        failed = translate_tree(engine.tree.translatable, PseudoTranslator())
        assert failed == []
        applied = engine.apply()
        assert applied == 9

        out = io.BytesIO()
        engine.save(out)
        out.seek(0)
        reopened = DocxTranslationEngine(out)

        texts = [s.text for s in reopened.tree.segments]
        assert "«We operate 700 stores across 11 countries.»" in texts
        assert "«Intangible assets»" in texts
        # Numeric cells were never touched.
        assert "319,915" in texts
        assert "20,913" in texts
        # Same shape: no elements created or destroyed.
        assert len(reopened.tree.segments) == len(engine.tree.segments)
        assert len(reopened.document.tables) == 1

    def test_multi_run_paragraph_keeps_run_count(self):
        engine = DocxTranslationEngine(_fixture_docx())
        seg = next(
            s for s in engine.tree.segments if "700 stores" in s.text
        )
        seg.translation = "Wij exploiteren 700 winkels in 11 landen."
        engine.apply()
        # 3 runs still exist; text is consolidated into the first.
        runs = seg.paragraph.runs
        assert len(runs) == 3
        assert runs[0].text == "Wij exploiteren 700 winkels in 11 landen."
        assert runs[1].text == "" and runs[2].text == ""


class TestBatching:
    def test_batches_respect_section_boundaries(self):
        engine = DocxTranslationEngine(_fixture_docx())
        batches = list(iter_batches(engine.tree.translatable))
        for batch in batches:
            assert len({s.section_path for s in batch}) == 1

    def test_batches_respect_size_bounds(self):
        engine = DocxTranslationEngine(_fixture_docx())
        batches = list(
            iter_batches(engine.tree.translatable, max_segments=2)
        )
        assert all(len(b) <= 2 for b in batches)


class TestQa:
    def _translated_fixture(self):
        engine = DocxTranslationEngine(_fixture_docx())
        translate_tree(engine.tree.translatable, PseudoTranslator())
        return engine.tree.translatable

    def test_clean_translation_passes(self):
        segments = self._translated_fixture()
        assert qa.run_all(segments) == []

    def test_dropped_number_is_an_error(self):
        segments = self._translated_fixture()
        seg = next(s for s in segments if "1,234" in s.text)
        seg.translation = "De Groep heeft een waardevermindering geboekt."
        findings = qa.check_numbers(segments)
        assert [f.check for f in findings] == ["numbers"]
        assert findings[0].severity == qa.Severity.ERROR
        assert "1,234" in findings[0].detail

    def test_invented_number_is_an_error(self):
        segments = self._translated_fixture()
        seg = next(s for s in segments if "700 stores" in s.text)
        seg.translation = "«We operate 800 stores across 11 countries.»"
        findings = qa.check_numbers(segments)
        assert any("800" in f.detail for f in findings)

    def test_translated_brand_name_is_an_error(self):
        segments = self._translated_fixture()
        seg = next(s for s in segments if "impairment" in s.text)
        seg.translation = seg.translation.replace("EUR", "euro")
        findings = qa.check_do_not_translate(segments, ["EUR"])
        assert findings and findings[0].check == "do_not_translate"

    def test_glossary_miss_is_a_warning(self):
        segments = self._translated_fixture()
        glossary = [
            GlossaryEntry(
                source="impairment", target="bijzondere waardevermindering"
            )
        ]
        findings = qa.check_glossary(segments, glossary)
        assert findings and findings[0].severity == qa.Severity.WARNING

    def test_length_blowup_is_a_warning(self):
        segments = self._translated_fixture()
        seg = next(s for s in segments if "1,234" in s.text)
        seg.translation = seg.text + " lorem ipsum" * 20
        findings = qa.check_length(segments)
        assert findings and findings[0].check == "length"
