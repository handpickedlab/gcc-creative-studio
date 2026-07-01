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

"""Tests for the Hunkemöller brief / initial-state assembly (pure functions)."""

from datetime import date

from src.deep_research.agent.brief import (
    NOT_SPECIFIED,
    build_brief,
    build_initial_state,
)
from src.deep_research.agent.intake import INTAKE_FIELDS


def _full_values():
    return {
        "research_topic": "Comfort bras",
        "market": "Germany",
        "customer_lens": "18 to 29 years",
        "gender": ["Women", "Other"],
        "research_goal": "Product development",
        "category_focus": ["Bras", "Comfort bras"],
        "consumer_angle": ["Comfort", "Fit"],
        "time_horizon": "Last 12 months",
        "source_preference": ["Public reviews", "Forums"],
        "competitor_context": "Compare with Triumph",
        "output_usage": "Product implications",
    }


def test_build_brief_injects_today():
    brief = build_brief({"research_topic": "x"}, today=date(2026, 1, 2))
    assert "2026-01-02" in brief


def test_build_brief_defaults_today_to_real_date():
    # Should not raise and should contain an ISO date for "today".
    brief = build_brief({"research_topic": "x"})
    assert date.today().isoformat() in brief


def test_build_brief_includes_all_supplied_values():
    values = _full_values()
    brief = build_brief(values, today=date(2026, 1, 2))
    assert "Comfort bras" in brief
    assert "Germany" in brief
    # Lists render comma-joined.
    assert "Women, Other" in brief


def test_missing_and_blank_fields_render_not_specified():
    brief = build_brief({"research_topic": "x"}, today=date(2026, 1, 2))
    # Every unsupplied field falls back to the sentinel.
    assert NOT_SPECIFIED in brief


def test_empty_list_renders_not_specified():
    brief = build_brief(
        {"research_topic": "x", "gender": []}, today=date(2026, 1, 2)
    )
    assert NOT_SPECIFIED in brief


def test_build_initial_state_has_every_field_as_string():
    state = build_initial_state(_full_values())
    assert set(state) == {f.key for f in INTAKE_FIELDS}
    assert all(isinstance(v, str) for v in state.values())
    assert state["gender"] == "Women, Other"


def test_build_brief_does_not_leave_unresolved_placeholders():
    # A successful str.format leaves no stray "{token}" behind.
    brief = build_brief(_full_values(), today=date(2026, 1, 2))
    assert "{" not in brief and "}" not in brief
