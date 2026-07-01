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

"""Custom tools for the deep research agent."""

from google.adk.tools.tool_context import ToolContext


def exit_research_loop(tool_context: ToolContext) -> dict:
    """Signal that the gathered research is sufficient and stop the research loop.

    Call this ONLY when the findings fully cover every sub-question in the
    research plan with credible, sourced evidence and no material gaps remain.
    Do not call it while important sub-questions are still unanswered.
    """
    tool_context.actions.escalate = True
    return {"status": "research_complete"}
