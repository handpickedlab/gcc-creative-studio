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

from pydantic import Field

from src.common.base_dto import BaseDto

# The intake field keys, in the order the brief expects them. Kept in sync with
# ``src.deep_research.agent.intake.INTAKE_FIELDS``; a test asserts they match.
INTAKE_KEYS: tuple[str, ...] = (
    "research_topic",
    "market",
    "customer_lens",
    "gender",
    "research_goal",
    "category_focus",
    "consumer_angle",
    "time_horizon",
    "source_preference",
    "competitor_context",
    "output_usage",
)


class StartDeepResearchDto(BaseDto):
    """Request body to kick off a Consumer Sentiment Scan.

    Mirrors the intake fields. Only ``research_topic`` is required; every other
    field is optional and renders as "(not specified)" in the brief, which tells
    the agent to make (and state) a sensible assumption.
    """

    research_topic: str = Field(min_length=1, description="The central topic.")
    market: str | None = None
    customer_lens: str | None = None
    gender: list[str] = Field(default_factory=list)
    research_goal: str | None = None
    category_focus: list[str] = Field(default_factory=list)
    consumer_angle: list[str] = Field(default_factory=list)
    time_horizon: str | None = None
    source_preference: list[str] = Field(default_factory=list)
    competitor_context: str | None = None
    output_usage: str | None = None

    max_iterations: int | None = Field(
        default=None,
        ge=1,
        le=6,
        description="Override the number of search/reflect rounds (1-6).",
    )

    def intake_values(self) -> dict:
        """Return only the intake selections, keyed as the brief builder expects.

        Excludes ``max_iterations`` (a run parameter, not an intake field).
        """
        return {key: getattr(self, key) for key in INTAKE_KEYS}
