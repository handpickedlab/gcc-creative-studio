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

"""Reusable runner for the deep-research pipeline.

``run_pipeline`` seeds session state, streams progress through an optional
``on_event`` callback, and returns the final (verified) report. The backend
deep-research service drives the ADK agent through this; persistence of the
result is the service's responsibility.
"""

from __future__ import annotations

from collections.abc import Callable

from google.adk.agents import BaseAgent
from google.adk.runners import InMemoryRunner
from google.genai import types

APP_NAME = "deep_research"
USER_ID = "backend"

# on_event(author, kind, text): kind is "tool" or "text".
EventCallback = Callable[[str, str, str], None]


async def run_pipeline(
    agent: BaseAgent,
    message: str,
    initial_state: dict | None = None,
    on_event: EventCallback | None = None,
) -> str:
    """Run ``agent`` over ``message`` and return the ``final_report`` state value.

    Args:
        agent: the root agent to run (e.g. from ``build_root_agent``).
        message: the user message / research brief.
        initial_state: optional session state to seed (intake context for the
            composer).
        on_event: optional progress callback invoked per streamed event.
    """
    # Seed empty docs so instruction templates that reference these keys resolve
    # even before the agents that write them have run: research_findings is
    # accumulated by the researchers' callback; draft_report is written by the
    # composer and read by the verifier.
    state: dict = {"research_findings": "", "draft_report": ""}
    if initial_state:
        state.update(initial_state)

    runner = InMemoryRunner(agent=agent, app_name=APP_NAME)
    session = await runner.session_service.create_session(
        app_name=APP_NAME, user_id=USER_ID, state=state
    )
    content = types.Content(role="user", parts=[types.Part(text=message)])

    async for event in runner.run_async(
        user_id=USER_ID, session_id=session.id, new_message=content
    ):
        author = getattr(event, "author", "?")
        if not (event.content and event.content.parts):
            continue
        for part in event.content.parts:
            if on_event is None:
                continue
            if getattr(part, "function_call", None):
                on_event(author, "tool", part.function_call.name)
            elif getattr(part, "text", None) and part.text.strip():
                on_event(author, "text", part.text.strip())

    session = await runner.session_service.get_session(
        app_name=APP_NAME, user_id=USER_ID, session_id=session.id
    )
    return session.state.get("final_report", "")
