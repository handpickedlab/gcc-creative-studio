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

"""Tests for pipeline wiring, {today} substitution and the verify/revise loop."""

from collections.abc import AsyncGenerator
from datetime import date

import pytest
from google.adk.agents import BaseAgent, LoopAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event, EventActions
from google.adk.runners import InMemoryRunner
from google.genai import types

from src.deep_research.agent.agent import (
    _finalize_report,
    _VerificationGate,
    build_root_agent,
    unresolved_claims,
)


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
        "verify_and_fix",
    ]
    research_loop = root.sub_agents[1]
    assert [a.name for a in research_loop.sub_agents] == [
        "parallel_research",
        "reflector",
    ]
    fix_loop = root.sub_agents[3]
    assert [a.name for a in fix_loop.sub_agents] == [
        "claim_verifier",
        "verification_gate",
        "report_reviser",
    ]


def test_composer_verifier_and_reviser_share_the_draft():
    root = build_root_agent()
    composer = root.sub_agents[2]
    fix_loop = root.sub_agents[3]
    verifier, _gate, reviser = fix_loop.sub_agents
    assert composer.output_key == "draft_report"
    assert verifier.output_key == "verification_section"
    # The reviser rewrites the same draft the composer produced.
    assert reviser.output_key == "draft_report"
    tool_names = {
        getattr(t, "name", getattr(t, "__name__", "")) for t in verifier.tools
    }
    assert "url_context" in tool_names


def test_revision_budget_wiring():
    fix_loop = build_root_agent(max_revisions=2).sub_agents[3]
    assert fix_loop.max_iterations == 3  # 2 revisions + the final verify pass
    assert fix_loop.sub_agents[1].max_revisions == 2
    # 0 restores flag-only behaviour: one verify pass, no revision.
    fix_loop = build_root_agent(max_revisions=0).sub_agents[3]
    assert fix_loop.max_iterations == 1
    assert fix_loop.sub_agents[1].max_revisions == 0


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


# --- The verify/revise loop ---------------------------------------------------

DIRTY_VERIFICATION = """\
## Verification & confidence
Overall confidence: Low -- several key claims lack support.
### Claims to treat with caution
- "60% of shoppers prefer wireless bras" -- source does not support it
- Q3 revenue figure -- no URL
### Source quality
Mixed; two sources lacked usable URLs."""

CLEAN_VERIFICATION = """\
## Verification & confidence
Overall confidence: High -- key claims are supported.
### Claims to treat with caution
None -- all key claims are supported by their sources.
### Source quality
Reputable industry sources, all with URLs."""


def test_unresolved_claims_parses_the_caution_list():
    assert unresolved_claims(DIRTY_VERIFICATION) == [
        '"60% of shoppers prefer wireless bras" -- source does not support it',
        "Q3 revenue figure -- no URL",
    ]
    assert unresolved_claims(CLEAN_VERIFICATION) == []
    assert unresolved_claims("") == []


class _ScriptedVerifier(BaseAgent):
    """Stub claim_verifier: emits a scripted verification section per pass."""

    sections: list[str]

    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        passes = int(ctx.session.state.get("verifier_passes") or 0) + 1
        section = self.sections[min(passes - 1, len(self.sections) - 1)]
        yield Event(
            invocation_id=ctx.invocation_id,
            author=self.name,
            actions=EventActions(
                state_delta={
                    "verifier_passes": passes,
                    "verification_section": section,
                }
            ),
        )


class _StubReviser(BaseAgent):
    """Stub report_reviser: overwrites the draft and counts its runs."""

    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        passes = int(ctx.session.state.get("revise_passes") or 0) + 1
        yield Event(
            invocation_id=ctx.invocation_id,
            author=self.name,
            actions=EventActions(
                state_delta={
                    "revise_passes": passes,
                    "draft_report": f"REVISED DRAFT v{passes}",
                }
            ),
        )


def _make_fix_loop(sections: list[str], max_revisions: int) -> LoopAgent:
    """Mirror build_root_agent's verify_and_fix wiring with stubbed LLM ends."""
    return LoopAgent(
        name="verify_and_fix",
        sub_agents=[
            _ScriptedVerifier(name="claim_verifier", sections=sections),
            _VerificationGate(name="verification_gate", max_revisions=max_revisions),
            _StubReviser(name="report_reviser"),
        ],
        max_iterations=max_revisions + 1,
        after_agent_callback=_finalize_report,
    )


async def _run_to_state(agent: BaseAgent, state: dict) -> dict:
    runner = InMemoryRunner(agent=agent, app_name="test")
    session = await runner.session_service.create_session(
        app_name="test", user_id="u", state=state
    )
    message = types.Content(role="user", parts=[types.Part(text="go")])
    async for _ in runner.run_async(
        user_id="u", session_id=session.id, new_message=message
    ):
        pass
    session = await runner.session_service.get_session(
        app_name="test", user_id="u", session_id=session.id
    )
    return session.state


@pytest.mark.anyio
async def test_flagged_claims_get_revised_and_reverified():
    loop = _make_fix_loop([DIRTY_VERIFICATION, CLEAN_VERIFICATION], max_revisions=1)
    state = await _run_to_state(loop, {"draft_report": "ORIGINAL DRAFT"})
    assert state["verifier_passes"] == 2  # dirty pass, then re-verify the fix
    assert state["revise_passes"] == 1
    assert state["draft_report"] == "REVISED DRAFT v1"
    # The final report is the revised draft plus the verification OF that draft.
    assert state["final_report"] == f"REVISED DRAFT v1\n\n---\n\n{CLEAN_VERIFICATION}"


@pytest.mark.anyio
async def test_clean_draft_skips_the_reviser():
    loop = _make_fix_loop([CLEAN_VERIFICATION], max_revisions=1)
    state = await _run_to_state(loop, {"draft_report": "ORIGINAL DRAFT"})
    assert state["verifier_passes"] == 1
    assert not state.get("revise_passes")
    assert state["final_report"] == f"ORIGINAL DRAFT\n\n---\n\n{CLEAN_VERIFICATION}"


@pytest.mark.anyio
async def test_exhausted_budget_still_ends_on_a_verified_draft():
    # The verifier never comes back clean: one revision is attempted, the
    # revised draft is re-verified, and the honest (dirty) verdict ships.
    loop = _make_fix_loop([DIRTY_VERIFICATION], max_revisions=1)
    state = await _run_to_state(loop, {"draft_report": "ORIGINAL DRAFT"})
    assert state["verifier_passes"] == 2
    assert state["revise_passes"] == 1
    assert state["final_report"] == f"REVISED DRAFT v1\n\n---\n\n{DIRTY_VERIFICATION}"


@pytest.mark.anyio
async def test_zero_revisions_restores_flag_only_behaviour():
    loop = _make_fix_loop([DIRTY_VERIFICATION], max_revisions=0)
    state = await _run_to_state(loop, {"draft_report": "ORIGINAL DRAFT"})
    assert state["verifier_passes"] == 1
    assert not state.get("revise_passes")
    assert state["final_report"] == f"ORIGINAL DRAFT\n\n---\n\n{DIRTY_VERIFICATION}"
