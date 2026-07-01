# Copyright 2025 Google LLC
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

"""Deep research agent built on Google ADK + Vertex AI (Gemini).

Pipeline (a SequentialAgent):
    1. plan_generator    -- decompose the question into a plan + sub-questions
    2. research_loop     -- LoopAgent that alternates:
         a. parallel_research -- N web researchers run concurrently, each owning
            a slice of the plan's sub-questions (or the reflector's gap queries
            on later rounds); their findings are merged into research_findings.
         b. reflector         -- judge coverage; stop early or propose new queries
    3. report_composer   -- synthesize a final, cited Markdown report

``root_agent`` is the entry point discovered by `adk run` / `adk web` and by
the local runner in ``run.py``.
"""

from __future__ import annotations

import re
from collections.abc import AsyncGenerator
from datetime import date

from google.adk.agents import (
    BaseAgent,
    LlmAgent,
    LoopAgent,
    ParallelAgent,
    SequentialAgent,
)
from google.adk.agents.callback_context import CallbackContext
from google.adk.agents.invocation_context import InvocationContext
from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.events import Event, EventActions
from google.adk.tools import google_search, url_context

from . import config, prompts
from .tools import exit_research_loop
from .vertex_model import make_model


def _finalize_report(callback_context: CallbackContext) -> None:
    """Combine the draft report with the verifier's verification section.

    The verifier never rewrites the report body (so it cannot itself corrupt it);
    it only produces a ``## Verification & confidence`` section, which we append
    here to form the ``final_report`` returned to the caller.
    """
    state = callback_context.state
    draft = (state.get("draft_report") or "").strip()
    verification = (state.get("verification_section") or "").strip()
    state["final_report"] = f"{draft}\n\n---\n\n{verification}" if verification else draft
    return None

# --- Sub-question / gap extraction (parsing the planner & reflector output) --

_HEADING = re.compile(r"^\s*#{1,6}\s+(.*\S)\s*$")
_LIST_ITEM = re.compile(r"^\s*(?:\d+[.)]|[-*•])\s+(.*\S)\s*$")


def _extract_list_items_under(markdown: str, keyword: str) -> list[str]:
    """Return the list items under the first heading whose text contains keyword.

    Used to pull the planner's "## Sub-questions" or the reflector's "## Next
    search queries" into discrete targets. Case-insensitive; collection stops at
    the next heading.
    """
    items: list[str] = []
    in_section = False
    for line in (markdown or "").splitlines():
        heading = _HEADING.match(line)
        if heading:
            in_section = keyword.lower() in heading.group(1).lower()
            continue
        if in_section:
            item = _LIST_ITEM.match(line)
            if item:
                items.append(item.group(1).strip())
    return items


def _extract_targets(state) -> tuple[list[str], str]:
    """Pick this round's research targets and label their kind.

    Later rounds focus on the reflector's gap queries; the first round (no gap
    analysis yet) fans out over the plan's sub-questions.
    """
    gap_items = _extract_list_items_under(state.get("gap_analysis") or "", "next search")
    if gap_items:
        return gap_items, "open gaps"
    plan_items = _extract_list_items_under(state.get("research_plan") or "", "sub-question")
    if plan_items:
        return plan_items, "sub-questions"
    return [], "sub-questions"


# --- Per-slot instruction provider ------------------------------------------


def _make_slot_instruction(slot_index: int, num_slots: int, today_iso: str):
    """Build an ADK instruction provider for one parallel researcher slot.

    Resolved at run time (ADK does not state-template provider output), so each
    round it reads the current plan/gaps and claims its round-robin slice of the
    targets. A slot with no target this round returns the skip instruction.
    """

    def provider(ctx: ReadonlyContext) -> str:
        state = ctx.state
        targets, focus = _extract_targets(state)
        mine = targets[slot_index::num_slots]
        # Fallback: if nothing parsed, slot 0 researches the whole plan alone.
        if not targets and slot_index == 0:
            mine = ["Answer the overall research question using the plan above."]
        if not mine:
            return prompts.SLOT_SKIP_INSTRUCTION

        findings = (state.get("research_findings") or "").strip()
        return prompts.SLOT_RESEARCHER_TEMPLATE.format(
            today=today_iso,
            focus=focus,
            targets="\n".join(f"- {t}" for t in mine),
            plan=state.get("research_plan") or "(no plan available)",
            findings=findings or "(nothing yet -- this is the first round)",
            skip_token=prompts.SLOT_SKIP_TOKEN,
        )

    return provider


# --- Findings accumulation ---------------------------------------------------


def merge_findings(prior: str, new: str, round_no: int) -> str:
    """Append one round's findings to the cumulative document.

    Each round is wrapped in a ``## Research round N`` header so the reflector
    and composer can see how evidence accumulated.
    """
    block = f"## Research round {round_no}\n\n{new.strip()}"
    return f"{prior.rstrip()}\n\n{block}" if prior.strip() else block


def _make_merge_callback(num_slots: int):
    """After parallel_research, fold every slot's findings into research_findings.

    Findings are accumulated in code rather than asking a model to copy the whole
    document forward each round (which loses detail and burns tokens). Slot keys
    are cleared so the next round starts clean.
    """

    def callback(callback_context: CallbackContext) -> None:
        state = callback_context.state
        fragments: list[str] = []
        for i in range(num_slots):
            key = f"slot_findings_{i}"
            value = (state.get(key) or "").strip()
            if value and value != prompts.SLOT_SKIP_TOKEN:
                fragments.append(value)
            state[key] = ""  # clear for the next round
        if not fragments:
            return None
        round_no = int(state.get("research_round") or 0) + 1
        state["research_round"] = round_no
        state["research_findings"] = merge_findings(
            state.get("research_findings") or "", "\n\n".join(fragments), round_no
        )
        return None

    return callback


# --- Pipeline wiring ---------------------------------------------------------


def unresolved_claims(verification: str) -> list[str]:
    """The claims the verifier listed under its "caution" heading (empty = clean).

    The verifier writes flagged claims as a bullet list under "### Claims to
    treat with caution"; a clean report carries the literal "None -- ..." line
    there, which is not a list item.
    """
    return _extract_list_items_under(verification or "", "caution")


class _VerificationGate(BaseAgent):
    """Stops the verify/revise loop when the draft is clean or the budget is spent.

    Sits between claim_verifier and report_reviser. Escalating stops the
    LoopAgent immediately (before the reviser runs), so the loop always ends on
    a draft whose verification section was produced from that exact draft, and
    the reviser only runs when there is something to fix.
    """

    max_revisions: int

    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        state = ctx.session.state
        round_no = int(state.get("verification_round") or 0) + 1
        clean = not unresolved_claims(state.get("verification_section") or "")
        yield Event(
            invocation_id=ctx.invocation_id,
            author=self.name,
            actions=EventActions(
                state_delta={"verification_round": round_no},
                escalate=clean or round_no > self.max_revisions,
            ),
        )


def build_root_agent(
    composer_instruction: str = prompts.COMPOSER_INSTRUCTION,
    max_iterations: int | None = None,
    num_slots: int | None = None,
    max_revisions: int | None = None,
    today: date | None = None,
) -> SequentialAgent:
    """Construct the deep-research pipeline.

    The planner, web researchers and reflector are domain-agnostic and fixed.
    Only the final ``report_composer`` instruction varies: the default produces
    a generic cited report, while the Hunkemöller intake flow passes its own
    10-section composer instruction (see ``deep_research.brief``).

    ``max_iterations`` overrides the search/reflect loop bound and ``num_slots``
    the number of concurrent researchers (defaults from ``config``). ``today`` is
    substituted into the planner / researcher instructions (defaults to the
    current date) so the model is told the real date, not one frozen in source.
    """
    today_iso = (today or date.today()).isoformat()
    num_slots = num_slots or config.RESEARCH_SLOTS

    def with_date(instruction: str) -> str:
        return instruction.replace("{today}", today_iso)

    # 1. Plan the research.
    plan_generator = LlmAgent(
        name="plan_generator",
        model=make_model(config.PLANNER_MODEL),
        description="Breaks a research question into a structured plan with sub-questions.",
        instruction=with_date(prompts.PLANNER_INSTRUCTION),
        output_key="research_plan",
    )

    # 2a. Fan out: N researchers search concurrently, each owning a slice of the
    # sub-questions/gaps. The callback merges their findings into research_findings.
    research_slots = [
        LlmAgent(
            name=f"web_researcher_{i + 1}",
            model=make_model(config.SEARCH_MODEL),
            description="Researches its assigned sub-questions and reports new cited findings.",
            instruction=_make_slot_instruction(i, num_slots, today_iso),
            # google_search discovers pages; url_context reads the most relevant
            # ones in full (both are Gemini 2 built-ins, no external key needed).
            tools=[google_search, url_context],
            output_key=f"slot_findings_{i}",
        )
        for i in range(num_slots)
    ]
    parallel_research = ParallelAgent(
        name="parallel_research",
        description="Researches the plan's sub-questions concurrently.",
        sub_agents=research_slots,
        after_agent_callback=_make_merge_callback(num_slots),
    )

    # 2b. Reflect on coverage; stop the loop or request more searches.
    reflector = LlmAgent(
        name="reflector",
        model=make_model(config.REFLECT_MODEL),
        description="Judges whether coverage is sufficient; stops the loop or proposes new queries.",
        instruction=prompts.REFLECTOR_INSTRUCTION,
        tools=[exit_research_loop],
        output_key="gap_analysis",
    )

    # 2. The iterative research loop (bounded by max_iterations, exits early on completion).
    research_loop = LoopAgent(
        name="research_loop",
        description="Iteratively researches in parallel and reflects until coverage is sufficient.",
        sub_agents=[parallel_research, reflector],
        max_iterations=max_iterations or config.MAX_RESEARCH_ITERATIONS,
    )

    # 3. Compose the draft report.
    report_composer = LlmAgent(
        name="report_composer",
        model=make_model(config.COMPOSE_MODEL),
        description="Synthesizes the draft report from the findings.",
        instruction=composer_instruction,
        output_key="draft_report",
    )

    # 4. Verify the draft against its sources, fix what fails, then finalize.
    # The verifier re-reads cited pages (url_context) and lists unsupported
    # claims; while any remain (and revision budget is left) the reviser rewrites
    # the draft to correct or drop them, and the loop re-verifies the result. The
    # gate exits after a verify pass, so the final verification section always
    # describes the draft it is appended to (assembled in code by _finalize_report).
    claim_verifier = LlmAgent(
        name="claim_verifier",
        model=make_model(config.VERIFY_MODEL),
        description="Re-reads cited sources to verify the draft's claims and flags unsupported ones.",
        instruction=prompts.VERIFIER_INSTRUCTION,
        tools=[url_context],
        output_key="verification_section",
    )
    revisions = (
        max_revisions
        if max_revisions is not None
        else config.MAX_REVISION_PASSES
    )
    verification_gate = _VerificationGate(
        name="verification_gate", max_revisions=revisions
    )
    report_reviser = LlmAgent(
        name="report_reviser",
        model=make_model(config.REVISE_MODEL),
        description="Rewrites the draft report to fix or drop the claims the verifier flagged.",
        instruction=prompts.REVISER_INSTRUCTION,
        output_key="draft_report",
    )
    verify_and_fix = LoopAgent(
        name="verify_and_fix",
        description="Verifies the draft's claims and revises the report until clean, ending on a verified draft.",
        sub_agents=[claim_verifier, verification_gate, report_reviser],
        # +1: the last allowed iteration is a verify-only pass (the gate exits
        # before the reviser), so a revised draft is always re-verified.
        max_iterations=revisions + 1,
        after_agent_callback=_finalize_report,
    )

    return SequentialAgent(
        name="deep_research_agent",
        description="Deep research agent: plan, parallel web research + reflection, a cited draft, then verify-and-fix.",
        sub_agents=[plan_generator, research_loop, report_composer, verify_and_fix],
    )


# Entry point discovered by `adk run` / `adk web` and the local CLI runner.
root_agent = build_root_agent()
