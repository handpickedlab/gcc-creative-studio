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


class GenerateUploadUrlDto(BaseDto):
    filename: str = Field(description="Name of the .docx to be uploaded.")
    size_bytes: int = Field(gt=0, description="File size in bytes.")


class GenerateUploadUrlResponseDto(BaseDto):
    upload_url: str = Field(description="Signed URL to PUT the file to.")
    gcs_uri: str = Field(description="Where the file will land.")


class FinalizeUploadDto(BaseDto):
    gcs_uri: str = Field(
        description="The gcs_uri returned when the upload URL was minted."
    )
    filename: str = Field(description="Original filename, shown in the UI.")


class StartTranslationDto(BaseDto):
    target_market: str = Field(
        description="Target market code from the translations markets list, "
        "e.g. 'NL' or 'DE'."
    )
    model_id: str | None = Field(
        default=None,
        description="Optional Gemini model override; defaults to app config.",
    )
    localise_numbers: bool = Field(
        default=False,
        description="Write figures and dates the way the target market does "
        "when the document is exported (319,915 -> 319.915, "
        "'January 31, 2026' -> '31 januari 2026').",
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
