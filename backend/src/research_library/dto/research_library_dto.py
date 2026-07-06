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

"""Request/response DTOs for the research library API."""

from pydantic import Field

from src.common.base_dto import BaseDto
from src.research_library.schema.research_document_model import (
    PriorityTierEnum,
    TagAliasKindEnum,
)


class GenerateUploadUrlDto(BaseDto):
    """Request body to generate a signed URL for an upload."""

    filename: str = Field(description="The name of the file to be uploaded.")
    mime_type: str = Field(
        description="The MIME type of the file (e.g., 'application/pdf').",
    )
    size_bytes: int = Field(
        gt=0, description="The size of the file in bytes."
    )


class GenerateUploadUrlResponseDto(BaseDto):
    """Response containing the signed URL and the final GCS URI."""

    upload_url: str = Field(
        description="The GCS v4 signed URL for the PUT request.",
    )
    gcs_uri: str = Field(
        description="The gs:// path where the file will be stored.",
    )


class FinalizeUploadDto(BaseDto):
    """Request body to finalize an upload and start (or skip) processing."""

    gcs_uri: str = Field(
        description="The GCS URI of the successfully uploaded file.",
    )
    filename: str = Field(
        description="The original name of the uploaded file.",
    )
    mime_type: str = Field(
        description="The MIME type of the uploaded file.",
    )


class UpdateDocumentDto(BaseDto):
    """Request body to update a document's mutable fields."""

    priority_tier: PriorityTierEnum = Field(
        description="The new ranking tier for this document's claims.",
    )


class BootstrapCanonicalizationDto(BaseDto):
    """Request body for the tag canonicalization bootstrap."""

    threshold: float | None = Field(
        default=None,
        gt=0,
        le=1,
        description="Cosine similarity above which two tags merge. "
        "Omit for the default.",
    )


class UpsertTagAliasDto(BaseDto):
    """Manual correction of one raw -> canonical alias."""

    raw: str = Field(description="The raw tag or metric string.")
    canonical: str = Field(description="Its canonical (English) form.")
    kind: TagAliasKindEnum = Field(default=TagAliasKindEnum.TAG)
    resolve: bool = Field(
        default=True,
        description="Whether to re-resolve all claims' canonical tags "
        "immediately after this change.",
    )
