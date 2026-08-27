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

"""Tests for the claim search service's ranking and result shaping."""

from unittest.mock import MagicMock, patch

from src.research_library.search.claim_search_service import (
    _normalize_min_period,
    _SEARCH_SQL,
    rank_candidates,
    search_claims_sync,
)


def _row(claim_id, similarity, tier, **extra):
    row = {
        "claim_id": claim_id,
        "document_id": 1,
        "page_no": 3,
        "statement": f"claim {claim_id}",
        "similarity": similarity,
        "priority_tier": tier,
        "filename": "deck.pdf",
        "document_period": "2025",
    }
    row.update(extra)
    return row


_WEIGHTS = {"primary": 1.0, "supporting": 0.85, "background": 0.7}


class TestRankCandidates:
    def test_tier_multiplier_reorders_close_matches(self):
        rows = [
            _row(1, 0.80, "background"),
            _row(2, 0.72, "primary"),
        ]

        ranked = rank_candidates(rows, _WEIGHTS)

        # 0.72 * 1.0 beats 0.80 * 0.7 — the primary source wins.
        assert [r["claim_id"] for r in ranked] == [2, 1]

    def test_background_still_wins_on_much_better_match(self):
        rows = [
            _row(1, 0.95, "background"),
            _row(2, 0.55, "primary"),
        ]

        ranked = rank_candidates(rows, _WEIGHTS)

        assert ranked[0]["claim_id"] == 1

    def test_unknown_tier_falls_back_to_primary_weight(self):
        rows = [_row(1, 0.5, None), _row(2, 0.5, "supporting")]

        ranked = rank_candidates(rows, _WEIGHTS)

        assert ranked[0]["claim_id"] == 1


class TestRecencyRanking:
    """Recency must follow the content's date, never the upload's."""

    def test_the_newer_period_wins_between_equal_matches(self):
        rows = [
            _row(1, 0.80, "primary", period_key="2023-03"),
            _row(2, 0.80, "primary", period_key="2026-01"),
        ]

        ranked = rank_candidates(rows, _WEIGHTS)

        assert [r["claim_id"] for r in ranked] == [2, 1]

    def test_upload_time_no_longer_influences_the_score(self):
        """The 2023-vs-2026 bug: a late upload used to win on 'recency'.

        document_created_at is deliberately ignored now, so an old claim in a
        recently uploaded file cannot outrank a genuinely newer one.
        """
        import datetime

        recent_upload = datetime.datetime(2026, 7, 23, tzinfo=datetime.UTC)
        old_upload = datetime.datetime(2026, 7, 6, tzinfo=datetime.UTC)
        rows = [
            _row(
                1,
                0.80,
                "primary",
                period_key="2023-03",
                document_created_at=recent_upload,
            ),
            _row(
                2,
                0.80,
                "primary",
                period_key="2026-01",
                document_created_at=old_upload,
            ),
        ]

        ranked = rank_candidates(rows, _WEIGHTS)

        assert ranked[0]["claim_id"] == 2

    def test_falls_back_to_the_document_edition_date(self):
        rows = [
            _row(1, 0.80, "primary", document_vintage_key="2022-00"),
            _row(2, 0.80, "primary", document_vintage_key="2025-00"),
        ]

        ranked = rank_candidates(rows, _WEIGHTS)

        assert ranked[0]["claim_id"] == 2

    def test_a_claim_period_outweighs_its_document_edition(self):
        """A 2019 figure quoted in a 2025 deck is still a 2019 figure."""
        rows = [
            _row(
                1,
                0.80,
                "primary",
                period_key="2019-00",
                document_vintage_key="2025-00",
            ),
            _row(
                2,
                0.80,
                "primary",
                period_key="2024-00",
                document_vintage_key="2024-00",
            ),
        ]

        ranked = rank_candidates(rows, _WEIGHTS)

        assert ranked[0]["claim_id"] == 2

    def test_undated_claims_are_scored_neutrally(self):
        """"past 12 months" must neither win nor be buried."""
        rows = [
            _row(1, 0.90, "primary", period_key=None),
            _row(2, 0.80, "primary", period_key="2026-01"),
        ]

        ranked = rank_candidates(rows, _WEIGHTS)

        assert ranked[0]["claim_id"] == 1
        assert ranked[0]["score"] == 0.90


class TestSearchClaimsSync:
    @patch(
        "src.research_library.search.claim_search_service._fetch_candidates"
    )
    @patch(
        "src.research_library.search.claim_search_service"
        ".embedding_service.embed_text"
    )
    def test_returns_formatted_ranked_results(self, mock_embed, mock_fetch):
        mock_embed.return_value = [1.0] + [0.0] * 767
        mock_fetch.return_value = [
            _row(1, 0.9, "primary", value="46%", period="2030"),
            _row(2, 0.8, "background"),
        ]

        out = search_claims_sync(MagicMock(), "smartphone aandeel 2030")

        assert out["count"] == 2
        first = out["results"][0]
        assert first["claim_id"] == 1
        assert first["document"] == "deck.pdf"
        assert first["page"] == 3
        assert first["value"] == "46%"
        assert "score" in first

    @patch(
        "src.research_library.search.claim_search_service._fetch_candidates"
    )
    @patch(
        "src.research_library.search.claim_search_service"
        ".embedding_service.embed_text"
    )
    def test_max_results_is_clamped(self, mock_embed, mock_fetch):
        mock_embed.return_value = [1.0] + [0.0] * 767
        mock_fetch.return_value = [
            _row(i, 0.9 - i * 0.01, "primary") for i in range(40)
        ]

        out = search_claims_sync(MagicMock(), "trends", max_results=99)

        assert out["count"] == 25

    @patch(
        "src.research_library.search.claim_search_service._fetch_candidates"
    )
    @patch(
        "src.research_library.search.claim_search_service"
        ".embedding_service.embed_text"
    )
    def test_min_period_is_normalized_and_passed_to_sql(
        self, mock_embed, mock_fetch
    ):
        mock_embed.return_value = [1.0] + [0.0] * 767
        mock_fetch.return_value = []

        search_claims_sync(MagicMock(), "NPS", min_period="2024")

        assert mock_fetch.call_args.kwargs["min_period"] == "2024-00"


    @patch(
        "src.research_library.search.claim_search_service"
        ".embedding_service.embed_text"
    )
    def test_failure_returns_error_payload(self, mock_embed):
        mock_embed.side_effect = RuntimeError("embedding down")

        out = search_claims_sync(MagicMock(), "trends")

        assert "claim search failed" in out["error"]

    @patch(
        "src.research_library.search.claim_search_service._fetch_candidates"
    )
    @patch(
        "src.research_library.search.claim_search_service"
        ".embedding_service.embed_text"
    )
    def test_undated_results_are_counted_under_a_cutoff(
        self, mock_embed, mock_fetch
    ):
        """A cutoff cannot vouch for a source with no date, so say how many."""
        mock_embed.return_value = [1.0] + [0.0] * 767
        mock_fetch.return_value = [
            _row(
                1,
                0.90,
                "primary",
                period_key=None,
                document_vintage_key=None,
            ),
            _row(2, 0.80, "primary", period_key="2026-01"),
        ]

        out = search_claims_sync(MagicMock(), "NPS", min_period="2025")

        assert out["undated"] == 1

    @patch(
        "src.research_library.search.claim_search_service._fetch_candidates"
    )
    @patch(
        "src.research_library.search.claim_search_service"
        ".embedding_service.embed_text"
    )
    def test_no_undated_count_without_a_cutoff(self, mock_embed, mock_fetch):
        mock_embed.return_value = [1.0] + [0.0] * 767
        mock_fetch.return_value = [
            _row(
                1,
                0.90,
                "primary",
                period_key=None,
                document_vintage_key=None,
            ),
        ]

        out = search_claims_sync(MagicMock(), "NPS")

        assert "undated" not in out


class TestCutoffSql:
    """The cutoff runs in SQL (it must precede the candidate LIMIT), so these
    guard the two clauses that keep it from silently deleting sources."""

    def test_undated_sources_survive_the_cutoff(self):
        assert "OR COALESCE(c.period_key, d.vintage_key) IS NULL" in _SEARCH_SQL

    def test_year_only_keys_are_judged_at_the_end_of_their_year(self):
        assert "'-00'" in _SEARCH_SQL
        assert "|| '-12'" in _SEARCH_SQL


class TestNormalizeMinPeriod:
    def test_passthrough_yyyy_mm(self):
        assert _normalize_min_period("2025-08") == "2025-08"

    def test_bare_year_becomes_year_key(self):
        assert _normalize_min_period("2024") == "2024-00"

    def test_blank_is_none(self):
        assert _normalize_min_period("  ") is None
        assert _normalize_min_period(None) is None
