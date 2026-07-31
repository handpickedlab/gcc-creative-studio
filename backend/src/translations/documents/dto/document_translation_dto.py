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
"""API DTOs for document translation jobs."""

from pydantic import Field

from src.common.base_dto import BaseDto


class StartTranslationDto(BaseDto):
    target_market: str = Field(
        description="Target market code from the translations markets list, "
        "e.g. 'NL' or 'DE'."
    )
    model_id: str | None = Field(
        default=None,
        description="Optional Gemini model override; defaults to app config.",
    )


class RetranslateSegmentDto(BaseDto):
    instruction: str | None = Field(
        default=None,
        description="Optional reviewer steering, e.g. \"more formal\" or "
        "\"use 'reële waarde'\".",
    )


class UpdateSegmentDto(BaseDto):
    translation: str | None = Field(
        default=None, description="Edited translation text."
    )
    status: str | None = Field(
        default=None,
        description="New review status: translated | edited | approved.",
    )
