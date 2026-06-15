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


class GlossaryTermCreateDto(BaseModel):
    """Payload to create a glossary term in a language's dictionary."""

    language: str = Field(description="Target language this entry applies to.")
    source: str = Field(description="The source word/term to match.")
    target: str = Field(description="The fixed translation to always use.")


class GlossaryTermUpdateDto(BaseModel):
    """Payload to update a glossary term. Fields are optional (partial update)."""

    language: str | None = Field(default=None, description="New target language.")
    source: str | None = Field(default=None, description="New source word/term.")
    target: str | None = Field(default=None, description="New fixed translation.")


class TranslateRequestDto(BaseModel):
    """Payload to translate a text into one or more target languages."""

    text: str = Field(description="The source text to translate.")
    target_languages: list[str] = Field(
        description="Languages to translate into, e.g. ['Dutch', 'French'].",
        min_length=1,
    )
    tone: str | None = Field(
        default=None,
        description="Optional tone, e.g. 'formal' or 'informal'.",
    )


class TranslationResult(BaseModel):
    """A single translation result for one target language."""

    language: str
    translation: str


class TranslateResponseDto(BaseModel):
    """Response containing one translation per requested language."""

    results: list[TranslationResult]
