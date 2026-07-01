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

"""Configuration for the deep research agent.

The base model defaults to the app-wide ``GEMINI_MODEL_ID`` (see
``src.config.config_service``). Each role and depth limit can be overridden via
``DR_*`` environment variables to tune cost vs. depth without touching code.
"""

import os

from src.config.config_service import config_service

# Default model for the reasoning-heavy roles (planning, reflection, writing,
# verification). Falls back to the app-wide Gemini model.
DEFAULT_MODEL = os.getenv("DR_MODEL", config_service.GEMINI_MODEL_ID)

# Per-role models. The search worker uses Flash for speed and cost; the
# reasoning roles default to the base model (Pro).
PLANNER_MODEL = os.getenv("DR_PLANNER_MODEL", DEFAULT_MODEL)
SEARCH_MODEL = os.getenv("DR_SEARCH_MODEL", "gemini-2.5-flash")
REFLECT_MODEL = os.getenv("DR_REFLECT_MODEL", DEFAULT_MODEL)
COMPOSE_MODEL = os.getenv("DR_COMPOSE_MODEL", DEFAULT_MODEL)
# The fact-checker that re-reads cited sources to verify claims. Reasoning-heavy,
# so it defaults to the base model.
VERIFY_MODEL = os.getenv("DR_VERIFY_MODEL", DEFAULT_MODEL)

# Safety bound on the search/reflect loop. Each iteration is one round of
# searching followed by one reflection. The loop also exits early as soon as
# the reflector decides coverage is sufficient.
MAX_RESEARCH_ITERATIONS = int(os.getenv("DR_MAX_ITERATIONS", "3"))

# Number of web researchers that run concurrently each round. The plan's
# sub-questions (or the reflector's gap queries on later rounds) are distributed
# round-robin across these slots, so coverage never drops a sub-question even
# when there are more of them than slots. Higher = broader/faster but more
# concurrent search calls (cost).
RESEARCH_SLOTS = int(os.getenv("DR_RESEARCH_SLOTS", "4"))
