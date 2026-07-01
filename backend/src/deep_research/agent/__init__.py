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

"""Deep research engine: an ADK + Vertex AI (Gemini) multi-agent pipeline.

Bridges the app-wide Vertex config (``src.config.config_service``) to the
environment variables ADK / google-genai expect, then re-exports the pipeline
builder and runner. Grounding (``google_search`` + ``url_context``) generally
needs a regional endpoint; override with ``DR_LOCATION`` if the app-wide
``LOCATION`` is ``global``.
"""

import os

from src.config.config_service import config_service

os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "TRUE")
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", config_service.PROJECT_ID)
os.environ.setdefault(
    "GOOGLE_CLOUD_LOCATION",
    os.getenv("DR_LOCATION", config_service.LOCATION),
)

from .agent import build_root_agent  # noqa: E402
from .pipeline import run_pipeline  # noqa: E402

__all__ = ["build_root_agent", "run_pipeline"]
