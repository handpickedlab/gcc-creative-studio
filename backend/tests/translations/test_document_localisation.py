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
"""Tests for figure/date renotation and the QA check that tolerates it."""

import pytest

from src.translations.documents import locale_format, qa
from src.translations.documents.locale_format import NBSP
from src.translations.documents.model import Segment, SegmentKind

NL = locale_format.for_market("NL")
DE = locale_format.for_market("DE")
FR = locale_format.for_market("FR")


def _segment(
    text: str,
    translation: str | None = None,
    kind: SegmentKind = SegmentKind.PROSE,
) -> Segment:
    return Segment(
        id=1,
        text=text,
        kind=kind,
        paragraph=None,
        section_path=("2.19 Right-of-use assets",),
        translation=translation,
    )


def _prose(source: str, fmt=NL) -> str:
    """Renotates a translation that reproduced the source's figures."""
    return locale_format.localise_translation(source, source, fmt)


# --- figures ------------------------------------------------------------


def test_english_targets_need_no_renotation():
    assert locale_format.for_market("EN") is None
    assert locale_format.for_market("UK") is None
    assert locale_format.for_market(None) is None


@pytest.mark.parametrize(
    "market, expected",
    [
        ("NL", "1.234.567,89"),
        ("BENL", "1.234.567,89"),
        ("DE", "1.234.567,89"),
        ("DK", "1.234.567,89"),
        ("ES", "1.234.567,89"),
        ("FR", f"1{NBSP}234{NBSP}567,89"),
        ("SE", f"1{NBSP}234{NBSP}567,89"),
        ("CHDE", "1'234'567.89"),
    ],
)
def test_grouped_figures_follow_the_market(market, expected):
    fmt = locale_format.for_market(market)
    assert _prose("1,234,567.89", fmt) == expected


def test_thousands_separator_in_a_sentence():
    assert _prose("an impairment of EUR 20,913 thousand") == (
        "an impairment of EUR 20.913 thousand"
    )


def test_a_year_is_left_alone():
    assert _prose("the year ended 2026 and note 16") == (
        "the year ended 2026 and note 16"
    )


def test_a_decimal_in_prose_is_renotated():
    assert _prose("a ratio of 4.6 times") == "a ratio of 4,6 times"


@pytest.mark.parametrize(
    "source",
    [
        "as set out in note 2.19",
        "See Note 2.19 for details",
        "Notes 2.19, 2.20 and 2.21 disclose this",
        "in accordance with IFRS 16.35",
        "refer to section 4.2",
    ],
)
def test_cross_references_are_never_renotated(source):
    assert _prose(source) == source


def test_a_heading_keeps_its_section_number():
    assert (
        locale_format.localise_translation(
            "2.19 Right-of-use assets",
            "2.19 Gebruiksrechten",
            NL,
            conservative=True,
        )
        == "2.19 Gebruiksrechten"
    )


def test_a_heading_still_renotates_a_grouped_figure():
    assert (
        locale_format.localise_translation(
            "1. Revenue of 20,913",
            "1. Omzet van 20,913",
            NL,
            conservative=True,
        )
        == "1. Omzet van 20.913"
    )


def test_a_numbered_label_keeps_its_number():
    """Word renders most section numbers from list numbering, so a labelled
    paragraph reaches us as prose rather than as a heading."""
    assert _prose("2.19 Right-of-use assets") == "2.19 Right-of-use assets"


def test_a_bracketed_reference_is_left_alone():
    assert _prose("Right-of-use assets (2.19)") == (
        "Right-of-use assets (2.19)"
    )


def test_a_bracketed_percentage_is_still_a_figure():
    assert _prose("margin (4.6%)") == "margin (4,6%)"


def test_an_introduced_amount_is_still_a_figure():
    assert _prose("an amount of 4.6 million") == "an amount of 4,6 million"


def test_a_multi_level_reference_is_not_a_figure():
    assert _prose("see 2.19.1 below") == "see 2.19.1 below"


def test_a_figure_already_in_continental_notation_is_left_alone():
    """"12,34" is not English grouping — rewriting it would guess."""
    assert _prose("a margin of 12,34") == "a margin of 12,34"


def test_a_figure_inside_an_identifier_is_left_alone():
    assert _prose("FY2025.26 and IFRS16.2") == "FY2025.26 and IFRS16.2"


def test_negative_table_figures_keep_their_brackets():
    assert _prose("(141,764)") == "(141.764)"


# --- locked numeric cells ----------------------------------------------


def test_a_locked_cell_is_renotated():
    assert locale_format.localise_locked("319,915", NL) == "319.915"


def test_a_locked_cell_keeps_a_bare_decimal():
    """In a numeric cell "2.19" is as likely a note reference as a ratio."""
    assert locale_format.localise_locked("2.19", NL) == "2.19"


def test_a_locked_cell_keeps_a_dash():
    assert locale_format.localise_locked("-", NL) == "-"


# --- percent -----------------------------------------------------------


def test_french_spaces_the_percent_sign():
    assert _prose("19%", FR) == f"19{NBSP}%"


def test_dutch_does_not_space_the_percent_sign():
    assert _prose("19%") == "19%"


def test_percent_spacing_is_idempotent():
    once = locale_format.localise_locked("19%", FR)
    assert locale_format.localise_locked(once, FR) == once


# --- dates -------------------------------------------------------------


@pytest.mark.parametrize(
    "market, expected",
    [
        ("NL", "31 januari 2026"),
        ("DE", "31. Januar 2026"),
        ("FR", "31 janvier 2026"),
        ("ES", "31 de enero de 2026"),
        ("DK", "31. januar 2026"),
        ("SE", "31 januari 2026"),
        ("NO", "31. januar 2026"),
    ],
)
def test_a_month_name_date_follows_the_market(market, expected):
    fmt = locale_format.for_market(market)
    assert _prose("January 31, 2026", fmt) == expected


def test_a_day_first_date_is_recognised():
    assert _prose("31 January 2026") == "31 januari 2026"


def test_an_abbreviated_month_is_recognised():
    assert _prose("Jan. 31, 2026") == "31 januari 2026"


def test_an_ordinal_day_is_recognised():
    assert _prose("January 1st, 2026") == "1 januari 2026"


def test_french_writes_the_first_of_the_month_as_an_ordinal():
    assert _prose("January 1, 2026", FR) == "1er janvier 2026"


def test_a_month_and_year_without_a_day():
    assert _prose("in January 2026 the Group") == "in januari 2026 the Group"
    assert _prose("in January 2026", locale_format.for_market("ES")) == (
        "in enero de 2026"
    )


def test_a_date_in_a_table_label_is_renotated():
    assert _prose("As at January 31, 2026") == "As at 31 januari 2026"


def test_date_renotation_is_idempotent():
    once = _prose("January 31, 2026")
    assert locale_format.localise_translation(
        "January 31, 2026", once, NL
    ) == once


def test_all_numeric_dates_are_left_alone():
    """31/01/2026 and 2026-01-31 read correctly in every target market."""
    assert _prose("31/01/2026 and 2026-01-31") == "31/01/2026 and 2026-01-31"


# --- interaction with the model and the reviewer -----------------------


def test_a_figure_the_model_already_localised_is_not_flipped_back():
    assert (
        locale_format.localise_translation(
            "Total assets of 319,915", "Totale activa van 319.915", NL
        )
        == "Totale activa van 319.915"
    )


def test_a_reviewers_own_notation_survives():
    assert (
        locale_format.localise_translation(
            "a ratio of 4.6 times", "een ratio van 4,6 keer", NL
        )
        == "een ratio van 4,6 keer"
    )


def test_renotation_never_changes_a_value():
    fmt = NL
    for source in ("319,915", "1,234.56", "20,913", "4.6", "1,000,000"):
        localised = locale_format.apply_plan(
            source, locale_format.number_plan(source, fmt)
        )
        digits = "".join(c for c in localised if c.isdigit())
        assert digits == "".join(c for c in source if c.isdigit())


# --- QA ----------------------------------------------------------------


def test_qa_flags_a_changed_figure_regardless_of_localisation():
    findings = qa.check_numbers(
        [_segment("Total assets of 319,915", "Totale activa van 319.916")],
        NL,
    )
    assert [f.check for f in findings] == ["number"]
    assert "319,915" in findings[0].detail


def test_qa_accepts_a_figure_the_model_localised_itself():
    findings = qa.check_numbers(
        [_segment("Total assets of 319,915", "Totale activa van 319.915")],
        NL,
    )
    assert findings == []


def test_qa_still_demands_exact_figures_without_localisation():
    findings = qa.check_numbers(
        [_segment("Total assets of 319,915", "Totale activa van 319.915")]
    )
    assert [f.check for f in findings] == ["number"]


def test_qa_flags_a_localised_section_number_in_a_heading():
    """A heading's "2.19" is a reference; renotating it is a real error."""
    findings = qa.check_numbers(
        [
            _segment(
                "2.19 Right-of-use assets",
                "2,19 Gebruiksrechten",
                kind=SegmentKind.HEADING,
            )
        ],
        NL,
    )
    assert [f.check for f in findings] == ["number"]


def test_qa_accepts_a_localised_decimal_in_prose():
    findings = qa.check_numbers(
        [_segment("a ratio of 4.6 times", "een ratio van 4,6 keer")], NL
    )
    assert findings == []


def test_qa_counts_repeated_figures():
    findings = qa.check_numbers(
        [_segment("20,913 and 20,913", "20.913 en 20913")], NL
    )
    assert [f.check for f in findings] == ["number"]
    assert "20,913" in findings[0].expected


def test_qa_dates_survive_localisation():
    findings = qa.check_numbers(
        [_segment("As at January 31, 2026", "Per 31 januari 2026")], NL
    )
    assert findings == []
