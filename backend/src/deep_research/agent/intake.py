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

"""Intake schema for the Hunkemöller Consumer Sentiment Scan.

This is the single source of truth shared by the Streamlit stepper (``app.py``)
and the brief builder (``brief.py``). Each :class:`IntakeField` describes one
question from the original intake sheet: its label, how it is selected, the
suggested options and an example.

The option lists below are deliberately kept as plain module constants so they
are trivial to edit without touching UI or prompt code. In particular,
``SEGMENTS`` ships with placeholder names -- replace them with the real five
Hunkemöller segments.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class FieldType(str, Enum):
    """How a field is captured in the UI."""

    FREE_TEXT = "free_text"
    SINGLE_SELECT = "single_select"
    SINGLE_SELECT_CUSTOM = "single_select_custom"  # dropdown + free "Other…" input
    MULTI_SELECT = "multi_select"
    COMPETITOR = "competitor"  # 3-way: none / include / specific competitors + text


# --- Configurable option lists (edit freely) --------------------------------

# The five Hunkemöller segments, split by age band.
SEGMENTS: list[str] = [
    "Under 18 years",
    "18 to 29 years",
    "30 to 44 years",
    "45 to 60 years",
    "61 years or older",
]

# Gender is a second demographic axis, combinable with the age segments.
GENDERS: list[str] = [
    "Women",
    "Men",
    "Other",
]

MARKETS: list[str] = [
    "Global",
    "Germany",
    "Netherlands",
    "Belgium",
    "Spain",
    "France",
    "Scandinavia",
]

CUSTOMER_LENSES: list[str] = [
    "All consumers",
    *SEGMENTS,
    "Compare segments",
]

RESEARCH_GOALS: list[str] = [
    "Product development",
    "Campaign / messaging",
    "Pricing / value",
    "Trend inspiration",
    "Proposition validation",
    "Customer experience",
]

CATEGORIES: list[str] = [
    "Bras",
    "Comfort bras",
    "Non-wired bras",
    "Underwear",
    "Cotton basics",
    "Nightwear",
    "Loungewear",
    "Swimwear",
    "Shapewear",
    "Premium lingerie",
]

CONSUMER_ANGLES: list[str] = [
    "Comfort",
    "Fit",
    "Support",
    "Softness",
    "Style",
    "Quality",
    "Affordability",
    "Premium feel",
    "Confidence",
    "Gifting",
    "Sustainability",
    "Inclusivity",
]

TIME_HORIZONS: list[str] = [
    "Current sentiment",
    "Last 3 months",
    "Last 6 months",
    "Last 12 months",
    "Emerging trend",
    "Timeless needs",
]

SOURCE_PREFERENCES: list[str] = [
    "Public reviews",
    "Forums",
    "Social conversations",
    "Competitor websites",
    "Trend articles",
    "Search behaviour",
    "News / articles",
    "All available sources",
]

OUTPUT_USAGES: list[str] = [
    "One-page insight brief",
    "Product implications",
    "Messaging implications",
    "Risks & objections",
    "Research hypotheses",
    "Next-step questions",
]

TOPIC_EXAMPLES: list[str] = [
    "Comfort bras",
    "Casual cotton underwear",
    "Self-gifting",
    "Price perception",
    "Quality perception",
    "Body confidence",
    "Loungewear",
    "Nightwear",
    "Fit frustration",
    "Premium materials",
]


# --- Field schema -----------------------------------------------------------


@dataclass(frozen=True)
class IntakeField:
    """One intake question.

    Attributes:
        key: stable identifier, also the key in the values dict and session state.
        label: human-readable question label.
        type: how it is captured (see :class:`FieldType`).
        options: suggested choices for select fields.
        example: example custom input shown as a hint.
        help: extra guidance shown under the field.
        brief_label: label used in the assembled brief / report header.
    """

    key: str
    label: str
    type: FieldType
    brief_label: str
    options: list[str] = field(default_factory=list)
    example: str = ""
    help: str = ""


INTAKE_FIELDS: list[IntakeField] = [
    IntakeField(
        key="research_topic",
        label="Research topic",
        type=FieldType.FREE_TEXT,
        brief_label="Research topic",
        options=TOPIC_EXAMPLES,
        example="Consumer sentiment around wireless bras for everyday use",
        help="The central topic of the scan. Pick an example or type your own topic.",
    ),
    IntakeField(
        key="market",
        label="Market / geography",
        type=FieldType.SINGLE_SELECT_CUSTOM,
        brief_label="Market / geography",
        options=MARKETS,
        example="Germany and Netherlands comparison",
        help="Select one market or type your own combination via 'Other…'.",
    ),
    IntakeField(
        key="customer_lens",
        label="Customer lens",
        type=FieldType.SINGLE_SELECT_CUSTOM,
        brief_label="Customer lens",
        options=CUSTOMER_LENSES,
        example="Young segment vs older quality-focused segment",
        help="All consumers, one Hunkemöller segment, or a comparison of segments.",
    ),
    IntakeField(
        key="gender",
        label="Gender",
        type=FieldType.MULTI_SELECT,
        brief_label="Gender",
        options=GENDERS,
        example="Women and Other",
        help="Second demographic axis, combinable with the age segments. Empty = all genders.",
    ),
    IntakeField(
        key="research_goal",
        label="Research goal",
        type=FieldType.SINGLE_SELECT,
        brief_label="Research goal",
        options=RESEARCH_GOALS,
        example="Input for a new Q4 campaign territory",
        help="Determines the structure of section 7 (Implications).",
    ),
    IntakeField(
        key="category_focus",
        label="Category focus",
        type=FieldType.MULTI_SELECT,
        brief_label="Category focus",
        options=CATEGORIES,
        example="Casual cotton collection for younger women",
        help="One or more product categories.",
    ),
    IntakeField(
        key="consumer_angle",
        label="Consumer angle",
        type=FieldType.MULTI_SELECT,
        brief_label="Consumer angle",
        options=CONSUMER_ANGLES,
        example="Softness, fit and price/value",
        help="The angles you mainly want to highlight.",
    ),
    IntakeField(
        key="time_horizon",
        label="Time horizon",
        type=FieldType.SINGLE_SELECT,
        brief_label="Time horizon",
        options=TIME_HORIZONS,
        example="Current sentiment for campaign planning",
        help="Which period of signals gets priority.",
    ),
    IntakeField(
        key="source_preference",
        label="Source preference",
        type=FieldType.MULTI_SELECT,
        brief_label="Source preference",
        options=SOURCE_PREFERENCES,
        example="Forums and reviews first",
        help="Which source types are consulted first.",
    ),
    IntakeField(
        key="competitor_context",
        label="Competitor context",
        type=FieldType.COMPETITOR,
        brief_label="Competitor context",
        options=[
            "No competitor context",
            "Include competitor context",
            "Specific competitors",
        ],
        example="Compare with H&M, Intimissimi, Triumph and Skims",
        help="Optional: include competitors in the analysis.",
    ),
    IntakeField(
        key="output_usage",
        label="Output usage",
        type=FieldType.SINGLE_SELECT,
        brief_label="Output usage",
        options=OUTPUT_USAGES,
        example="Product implications and messaging angles",
        help="What the output is primarily used for.",
    ),
]

# Quick lookup by key.
FIELDS_BY_KEY: dict[str, IntakeField] = {f.key: f for f in INTAKE_FIELDS}

# Grouping for the stepper: (step title, [field keys]).
STEPPER_GROUPS: list[tuple[str, list[str]]] = [
    ("Topic & market", ["research_topic", "market", "time_horizon"]),
    ("Audience & goal", ["customer_lens", "gender", "research_goal", "output_usage"]),
    ("Focus & angle", ["category_focus", "consumer_angle"]),
    ("Sources & competition", ["source_preference", "competitor_context"]),
]
