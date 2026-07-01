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

"""Tests for sub-question extraction, slot assignment, and findings merging."""

from src.deep_research.agent import prompts
from src.deep_research.agent.agent import (
    _extract_list_items_under,
    _extract_targets,
    _finalize_report,
    _make_merge_callback,
    _make_slot_instruction,
    merge_findings,
)

PLAN = """\
## Research question
What is X?

## Sub-questions
1. First sub-question?
2. Second sub-question?
3. Third sub-question?

## Initial search queries
- a query
- another query
"""

GAP = """\
## Remaining gaps
Something is missing.

## Next search queries
- gap query one
- gap query two
"""


# --- parsing ----------------------------------------------------------------


def test_extract_items_under_heading():
    items = _extract_list_items_under(PLAN, "sub-question")
    assert items == [
        "First sub-question?",
        "Second sub-question?",
        "Third sub-question?",
    ]


def test_extract_stops_at_next_heading():
    # The "Initial search queries" items must not leak into the sub-questions.
    items = _extract_list_items_under(PLAN, "sub-question")
    assert "a query" not in items


def test_extract_targets_prefers_gaps_when_present():
    targets, focus = _extract_targets(
        {"research_plan": PLAN, "gap_analysis": GAP}
    )
    assert targets == ["gap query one", "gap query two"]
    assert focus == "open gaps"


def test_extract_targets_falls_back_to_plan():
    targets, focus = _extract_targets({"research_plan": PLAN})
    assert targets == [
        "First sub-question?",
        "Second sub-question?",
        "Third sub-question?",
    ]
    assert focus == "sub-questions"


def test_extract_targets_empty_when_nothing_parseable():
    targets, focus = _extract_targets({})
    assert targets == []


# --- slot assignment (round-robin) ------------------------------------------


class _Ctx:
    def __init__(self, state):
        self.state = state


def test_slots_partition_targets_round_robin_without_loss():
    state = {"research_plan": PLAN}
    num_slots = 2
    assigned = []
    for i in range(num_slots):
        instr = _make_slot_instruction(i, num_slots, "2026-06-30")(_Ctx(state))
        # Pull the assigned bullet lines out of the rendered instruction.
        assigned += [
            line[2:]
            for line in instr.splitlines()
            if line.startswith("- ") and line[2:].endswith("?")
        ]
    # Every sub-question is covered exactly once across the slots.
    assert sorted(assigned) == [
        "First sub-question?",
        "Second sub-question?",
        "Third sub-question?",
    ]


def test_unassigned_slot_returns_skip():
    # 3 targets, slot index 5 -> nothing assigned.
    instr = _make_slot_instruction(5, 6, "2026-06-30")(
        _Ctx({"research_plan": PLAN})
    )
    assert instr == prompts.SLOT_SKIP_INSTRUCTION


def test_fallback_slot_zero_researches_whole_plan():
    instr = _make_slot_instruction(0, 4, "2026-06-30")(_Ctx({}))
    assert "overall research question" in instr
    # Other slots skip when there is nothing to parse.
    assert (
        _make_slot_instruction(1, 4, "2026-06-30")(_Ctx({}))
        == prompts.SLOT_SKIP_INSTRUCTION
    )


# --- findings merge ----------------------------------------------------------


def test_merge_into_empty_prior():
    out = merge_findings("", "Fact A", 1)
    assert out == "## Research round 1\n\nFact A"


def test_merge_appends_with_round_header():
    out = merge_findings("## Research round 1\n\nFact A", "Fact B", 2)
    assert "## Research round 1" in out and "## Research round 2" in out
    assert out.index("Fact A") < out.index("Fact B")


def test_merge_callback_combines_slots_and_clears_them():
    state = {
        "slot_findings_0": "Evidence from slot 0",
        "slot_findings_1": prompts.SLOT_SKIP_TOKEN,  # filtered out
        "slot_findings_2": "Evidence from slot 2",
    }
    _make_merge_callback(3)(_Ctx(state))

    assert state["research_round"] == 1
    findings = state["research_findings"]
    assert "Evidence from slot 0" in findings
    assert "Evidence from slot 2" in findings
    assert prompts.SLOT_SKIP_TOKEN not in findings
    # Slot keys are cleared for the next round.
    assert all(state[f"slot_findings_{i}"] == "" for i in range(3))


def test_merge_callback_no_op_when_all_slots_empty():
    state = {"slot_findings_0": "", "slot_findings_1": prompts.SLOT_SKIP_TOKEN}
    _make_merge_callback(2)(_Ctx(state))
    assert "research_round" not in state
    assert "research_findings" not in state


# --- report finalization (draft + verification) -----------------------------


def test_finalize_appends_verification_section():
    state = {
        "draft_report": "# Report\n\nBody.",
        "verification_section": (
            "## Verification & confidence\n\nOverall confidence: High."
        ),
    }
    _finalize_report(_Ctx(state))
    final = state["final_report"]
    assert final.startswith("# Report")
    assert "## Verification & confidence" in final
    # The draft body is preserved verbatim ahead of the separator.
    assert final.index("Body.") < final.index("## Verification & confidence")


def test_finalize_falls_back_to_draft_when_no_verification():
    state = {"draft_report": "# Report\n\nBody.", "verification_section": ""}
    _finalize_report(_Ctx(state))
    assert state["final_report"] == "# Report\n\nBody."
