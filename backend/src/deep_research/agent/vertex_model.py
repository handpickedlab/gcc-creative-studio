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

"""Scoped Vertex AI model for the deep-research agents.

ADK's default ``Gemini`` builds its ``google.genai`` client from the process-wide
Application Default Credentials. This subclass instead points the client at the
app's dedicated Vertex project (``VERTEX_PROJECT_ID``) using the scoped
service-account credentials from ``src.common.vertex_credentials`` -- the same
mechanism the rest of the app uses to route GenMedia to the client project -- so
deep-research GenAI calls run in that project WITHOUT changing the host process's
global ADC (which must stay on the primary project for storage / auth / signing).

ADK documents this exact extension point: subclass ``Gemini`` and override the
``api_client`` cached property. The client is built lazily on first use, so
constructing the model (e.g. at ``build_root_agent`` import time) never touches
credentials -- only an actual model call does.
"""

from __future__ import annotations

from functools import cached_property

from google.adk.models import Gemini
from google.genai import Client

from src.common.vertex_credentials import (
    get_vertex_credentials,
    get_vertex_project,
)

from . import config


class ScopedVertexGemini(Gemini):
    """A ``Gemini`` model whose client targets the dedicated Vertex project.

    Falls back to ADK's normal ADC behaviour in local dev, where
    ``get_vertex_credentials()`` returns ``None`` and ``get_vertex_project()``
    resolves to the primary project.
    """

    @cached_property
    def api_client(self) -> Client:
        return Client(
            vertexai=True,
            project=get_vertex_project(),
            location=config.VERTEX_LOCATION,
            credentials=get_vertex_credentials(),
        )


def make_model(model_name: str) -> Gemini:
    """Build a deep-research model bound to the scoped Vertex client."""
    return ScopedVertexGemini(model=model_name)
