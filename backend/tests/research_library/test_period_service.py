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

"""Tests for period normalization.

Every input below is a spelling that actually occurs in the corpus.
"""

import pytest

from src.research_library.period_service import (
    label_for_key,
    normalize_period,
    parse_filename_vintage,
)


class TestNormalizePeriod:
    """Tests for normalize_period."""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("2024", "2024-00"),
            ("2030", "2030-00"),
            ("Q2 2025", "2025-04"),
            ("Q1 2024", "2024-01"),
            ("H2 2022", "2022-07"),
            ("H1 2024", "2024-01"),
            ("HY1 2024", "2024-01"),
            ("P10 2024", "2024-10"),
            ("P1 2024", "2024-01"),
            ("2025 P1", "2025-01"),
            ("October 2025", "2025-10"),
            ("OCT 2025", "2025-10"),
            ("Oct 2025", "2025-10"),
            ("Feb 2025", "2025-02"),
            ("mei 2026", "2026-05"),
            ("18-10-2024", "2024-10"),
            ("9-1-2025", "2025-01"),
            ("20241114", "2024-11"),
        ],
    )
    def test_resolves_the_spellings_used_in_the_corpus(self, raw, expected):
        assert normalize_period(raw) == expected

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [("Q1'24", "2024-01"), ("Q3'24", "2024-07"), ("P4-24", "2024-04")],
    )
    def test_accepts_shortened_years(self, raw, expected):
        assert normalize_period(raw) == expected

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("January-February 2025", "2025-01"),
            ("April-May 2025", "2025-04"),
            ("24 January and 7 February 2025", "2025-01"),
            ("August 22 - September 5, 2025", "2025-08"),
            ("01 September 2024 - 30 November 2024", "2024-09"),
            ("March 21 - April 4, 2025", "2025-03"),
        ],
    )
    def test_a_range_collapses_to_its_start(self, raw, expected):
        assert normalize_period(raw) == expected

    @pytest.mark.parametrize(
        "raw",
        [
            "next five years",
            "the next five years",
            "in the next five years",
            "past 2 years",
            "past 12 months",
            "last 2 years",
            "afgelopen 12 maanden",
            "over 5 jaar",
            "recently",
            "current",
            "LTM",
            "post wave",
            "April 2-21",
            "",
            None,
        ],
    )
    def test_refuses_to_invent_a_date(self, raw):
        """Naming no point in time must stay unresolved, not be guessed."""
        assert normalize_period(raw) is None

    def test_an_anchored_window_files_under_its_anchor(self):
        assert (
            normalize_period("Last 12 months ending 28 September 2025")
            == "2025-09"
        )

    @pytest.mark.parametrize(
        ("raw", "year", "expected"),
        [("P5", 2025, "2025-05"), ("P10", 2024, "2024-10"), ("Q3", 2024, "2024-07")],
    )
    def test_a_bare_period_is_dated_by_its_document(self, raw, year, expected):
        """Satisfaction slides write "P10"; the year is the deck's."""
        assert normalize_period(raw, year) == expected

    @pytest.mark.parametrize("raw", ["P5", "Q3"])
    def test_a_bare_period_without_a_document_year_stays_unresolved(self, raw):
        assert normalize_period(raw) is None

    def test_a_year_in_the_text_beats_the_document_year(self):
        assert normalize_period("P5 2023", 2025) == "2023-05"

    def test_a_retrospective_dates_as_the_later_year(self):
        """"1975 versus 2025" is a 2025 document about 1975."""
        assert normalize_period("1975 versus 2025") == "2025-00"

    def test_keys_sort_chronologically_as_plain_strings(self):
        keys = [
            normalize_period(p)
            for p in ("Q2 2025", "2024", "P10 2024", "Q1 2024", "January 2026")
        ]
        assert sorted(keys) == [
            "2024-00",
            "2024-01",
            "2024-10",
            "2025-04",
            "2026-01",
        ]


class TestParseFilenameVintage:
    """Tests for reading a document's own edition date off its filename."""

    @pytest.mark.parametrize(
        ("filename", "expected"),
        [
            ("Customer Satisfaction Survey - P10 2024.pptx", "2024-10"),
            ("Beauty market - Desk research 9-1-2025.pptx", "2025-01"),
            ("Euromonitor - Consumer types may 2026.ppt", "2026-05"),
            ("The_State_of_Fashion_2024.pdf", "2024-00"),
            ("Gartner - CMO_Journal_4Q_2025.pdf", "2025-10"),
            ("Webinar_Fashion V2 23-2-24 .pdf", "2024-02"),
            ("Statista - 20241114_Webinar_Consumertrends2025.pdf", "2024-11"),
            ("Thuiswinkel-markt-monitor-fy-2024-basisversie.pdf", "2024-00"),
        ],
    )
    def test_reads_the_edition_date(self, filename, expected):
        assert parse_filename_vintage(filename) == expected

    def test_an_explicit_date_beats_a_trailing_topic_year(self):
        """"20241114_...Consumertrends2025" is a 2024 file about 2025."""
        assert (
            parse_filename_vintage("Statista - 20241114_Trends2025.pdf")
            == "2024-11"
        )

    @pytest.mark.parametrize(
        "filename",
        [
            "HKM Promise Insights Report Qualitative Research NL and GER.pptx",
            "FashionUnited - Trendrapport.pdf",
            "",
        ],
    )
    def test_undated_filenames_stay_unresolved(self, filename):
        assert parse_filename_vintage(filename) is None


class TestLabelForKey:
    """Tests for the human-readable label."""

    @pytest.mark.parametrize(
        ("key", "expected"),
        [
            ("2024-10", "October 2024"),
            ("2024-00", "2024"),
            ("2026-01", "January 2026"),
            (None, None),
            ("rubbish", None),
        ],
    )
    def test_renders_a_readable_label(self, key, expected):
        assert label_for_key(key) == expected
