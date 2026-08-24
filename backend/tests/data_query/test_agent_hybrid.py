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

"""Tests for the hybrid (sheets + research library) agent loop."""

from unittest.mock import MagicMock

from src.data_query.agent import stream_answer


def _text_response(text: str) -> MagicMock:
    part = MagicMock()
    part.text = text
    part.function_call = None
    response = MagicMock()
    response.candidates = [MagicMock()]
    response.candidates[0].content.parts = [part]
    return response


def _tool_response(name: str, args: dict) -> MagicMock:
    call = MagicMock()
    call.name = name
    call.args = args
    part = MagicMock()
    part.text = None
    part.function_call = call
    response = MagicMock()
    response.candidates = [MagicMock()]
    response.candidates[0].content.parts = [part]
    return response


def _search_result() -> dict:
    return {
        "count": 1,
        "results": [
            {
                "claim_id": 42,
                "statement": "46% via smartphone in 2030",
                "value": "46%",
                "period": "2030",
                "source_citation": "Thuiswinkel Markt Monitor Q1 2025",
                "document_id": 7,
                "document": "thuiswinkel-q1-2025.pdf",
                "page": 3,
                "tier": "primary",
                "score": 0.91,
            },
        ],
    }


class TestHybridAgent:
    def test_search_claims_flow_emits_sources_event(self):
        client = MagicMock()
        client.models.generate_content.side_effect = [
            _tool_response("search_claims", {"query": "smartphone 2030"}),
            _text_response("46% (thuiswinkel-q1-2025.pdf, p. 3)."),
        ]
        claim_search = MagicMock(return_value=_search_result())

        events = list(
            stream_answer(
                client,
                "gemini-test",
                "Hoeveel via smartphone in 2030?",
                claim_search=claim_search,
                allowed_documents=[7, 8],
            ),
        )

        kinds = [e["t"] for e in events]
        assert kinds == ["tool", "tool_result", "text", "sources"]
        # The search tool result is streamed to the frontend.
        assert events[1]["result"]["count"] == 1
        # Sources carry document + page for the citation viewer.
        source = events[3]["v"][0]
        assert source["document_id"] == 7
        assert source["page"] == 3

    def test_allowed_documents_comes_from_server_not_model(self):
        client = MagicMock()
        client.models.generate_content.side_effect = [
            _tool_response(
                "search_claims",
                # A prompt-injected attempt to widen the scope.
                {"query": "x", "allowed_documents": [999]},
            ),
            _text_response("done"),
        ]
        claim_search = MagicMock(return_value={"count": 0, "results": []})

        list(
            stream_answer(
                client,
                "gemini-test",
                "vraag",
                claim_search=claim_search,
                allowed_documents=[7],
            ),
        )

        assert claim_search.call_args.kwargs["allowed_documents"] == [7]

    def test_min_period_comes_from_server_not_model(self):
        client = MagicMock()
        client.models.generate_content.side_effect = [
            _tool_response(
                "search_claims",
                {"query": "x", "min_period": "2019-00"},
            ),
            _text_response("done"),
        ]
        claim_search = MagicMock(return_value={"count": 0, "results": []})

        list(
            stream_answer(
                client,
                "gemini-test",
                "vraag",
                claim_search=claim_search,
                min_period="2025-00",
            ),
        )

        assert claim_search.call_args.kwargs["min_period"] == "2025-00"

    def test_sheet_only_flow_has_no_sources_event(self):
        client = MagicMock()
        client.models.generate_content.side_effect = [
            _text_response("Er staan 3 tabellen klaar."),
        ]

        events = list(
            stream_answer(client, "gemini-test", "Welke tabellen zijn er?"),
        )

        assert [e["t"] for e in events] == ["text"]

    def test_search_without_library_returns_clear_error(self):
        client = MagicMock()
        client.models.generate_content.side_effect = [
            _tool_response("search_claims", {"query": "x"}),
            _text_response("kan niet zoeken"),
        ]

        events = list(
            stream_answer(client, "gemini-test", "vraag", claim_search=None),
        )

        tool_result = next(e for e in events if e["t"] == "tool_result")
        assert "not available" in tool_result["result"]["error"]
