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

from datetime import date
from unittest.mock import MagicMock

from src.data_query.agent import stream_answer, system_instruction


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
        # 'step' announces each model turn for the live view (TestLiveProgress).
        assert kinds == [
            "step", "tool", "tool_result", "step", "text", "sources",
        ]
        # The search tool result is streamed to the frontend.
        assert events[2]["result"]["count"] == 1
        # Sources carry document + page for the citation viewer.
        source = events[5]["v"][0]
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

        assert [e["t"] for e in events] == ["step", "text"]

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


class TestSystemInstruction:
    """The prompt must carry the real date.

    Without it the model reasoned from its training cutoff and told a tester
    that Q4 2025 and Q1 2026 "lie in the future", offering to look for
    forecasts instead of searching two quarters the library covers.
    """

    def test_today_is_substituted(self):
        out = system_instruction(date(2026, 8, 25))

        assert "Today's date is 2026-08-25" in out
        assert "{today}" not in out

    def test_defaults_to_the_real_today(self):
        assert date.today().isoformat() in system_instruction()

    def test_forbids_calling_a_past_period_the_future(self):
        out = system_instruction(date(2026, 8, 25))

        assert "has already happened" in out
        assert "forecasts" in out

    def test_the_date_is_not_frozen_at_import_time(self):
        """A warm instance must not keep answering from its boot date."""
        first = system_instruction(date(2026, 1, 1))
        second = system_instruction(date(2026, 8, 25))

        assert "2026-01-01" in first
        assert "2026-08-25" in second


class TestLiveProgress:
    """The client can only render "watch it work" from what the loop emits.

    The model's own turn is the longest silence in a run, so it is announced
    before the call rather than only after it produces something.
    """

    def _run(self):
        client = MagicMock()
        client.models.generate_content.side_effect = [
            _tool_response("search_claims", {"query": "smartphone 2030"}),
            _text_response("46%."),
        ]
        return list(
            stream_answer(
                client,
                "gemini-test",
                "Hoeveel via smartphone in 2030?",
                claim_search=MagicMock(return_value=_search_result()),
            )
        )

    def test_every_model_turn_is_announced_before_it_starts(self):
        events = self._run()

        assert events[0] == {"t": "step", "n": 1}
        steps = [e["n"] for e in events if e["t"] == "step"]
        assert steps == [1, 2]
        # The announcement precedes the tool call it leads to.
        assert events.index({"t": "step", "n": 1}) < next(
            i for i, e in enumerate(events) if e["t"] == "tool"
        )

    def test_a_tool_result_carries_how_long_the_call_took(self):
        result = next(e for e in self._run() if e["t"] == "tool_result")

        assert isinstance(result["ms"], int)
        assert result["ms"] >= 0
