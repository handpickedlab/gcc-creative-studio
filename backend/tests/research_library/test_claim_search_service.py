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
        "src.research_library.search.claim_search_service"
        ".embedding_service.embed_text"
    )
    def test_failure_returns_error_payload(self, mock_embed):
        mock_embed.side_effect = RuntimeError("embedding down")

        out = search_claims_sync(MagicMock(), "trends")

        assert "claim search failed" in out["error"]
