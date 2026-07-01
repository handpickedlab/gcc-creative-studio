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

"""Tests for pipeline wiring and the {today} date substitution."""

from datetime import date

from src.deep_research.agent.agent import build_root_agent


def _instruction(agent, name):
    (sub,) = [a for a in _iter_agents(agent) if a.name == name]
    return sub.instruction


def _iter_agents(agent):
    yield agent
    for sub in getattr(agent, "sub_agents", []) or []:
        yield from _iter_agents(sub)


def test_pipeline_structure():
    root = build_root_agent()
    assert [a.name for a in root.sub_agents] == [
        "plan_generator",
        "research_loop",
        "report_composer",
        "claim_verifier",
    ]
    loop = root.sub_agents[1]
    assert [a.name for a in loop.sub_agents] == [
        "parallel_research",
        "reflector",
    ]


def test_composer_drafts_and_verifier_finalizes():
    root = build_root_agent()
    composer = root.sub_agents[2]
    verifier = root.sub_agents[3]
    assert composer.output_key == "draft_report"
    assert verifier.name == "claim_verifier"
    assert verifier.output_key == "verification_section"
    tool_names = {
        getattr(t, "name", getattr(t, "__name__", "")) for t in verifier.tools
    }
    assert "url_context" in tool_names


def test_parallel_research_has_requested_slots():
    root = build_root_agent(num_slots=3)
    parallel = root.sub_agents[1].sub_agents[0]
    assert parallel.name == "parallel_research"
    assert [a.name for a in parallel.sub_agents] == [
        "web_researcher_1",
        "web_researcher_2",
        "web_researcher_3",
    ]


def test_research_slots_have_search_and_url_context_tools():
    root = build_root_agent(num_slots=2)
    parallel = root.sub_agents[1].sub_agents[0]
    for slot in parallel.sub_agents:
        tool_names = {
            getattr(t, "name", getattr(t, "__name__", "")) for t in slot.tools
        }
        assert "google_search" in tool_names
        assert "url_context" in tool_names


def test_today_token_is_substituted_in_planner():
    root = build_root_agent(today=date(2026, 1, 2))
    planner = _instruction(root, "plan_generator")
    assert "2026-01-02" in planner
    # The literal token must not survive into the rendered instruction.
    assert "{today}" not in planner


def test_max_iterations_override():
    root = build_root_agent(max_iterations=5)
    assert root.sub_agents[1].max_iterations == 5
