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

from pydantic import BaseModel, Field


class AskRequestDto(BaseModel):
    """A natural-language question over the uploaded sheets."""

    question: str = Field(description="The question to answer over the data.")
    allowed_tables: list[str] | None = Field(
        default=None,
        description="Optional whitelist of table names the agent may use. "
        "None = all uploaded tables.",
    )
