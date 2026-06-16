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

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from src.translations.schema.briefing_model import BriefingMeta, BriefingSegment


class _CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class MarketInfo(_CamelModel):
    code: str
    label: str


class ParsedRequestInfo(_CamelModel):
    """One 'Request nr. X' discovered in an uploaded sheet."""

    index: int
    label: str
    filled: int = 0  # number of source fields that actually contain copy


class GlossarySample(_CamelModel):
    source: str
    target: str


class GlossaryMarketSummary(_CamelModel):
    market: str
    count: int
    samples: list[GlossarySample] = Field(default_factory=list)


class GlossarySummaryDto(_CamelModel):
    total: int
    per_market: list[GlossaryMarketSummary] = Field(default_factory=list)


class ParseResultDto(_CamelModel):
    """Result of parsing an uploaded workbook.

    When no specific request is selected, `requests` lists what was found
    (discovery). When a request is selected, `briefing` is populated.
    """

    sheets: list[str] = Field(default_factory=list)
    selected_sheet: str | None = None
    requests: list[ParsedRequestInfo] = Field(default_factory=list)
    briefing_name: str | None = None
    meta: BriefingMeta | None = None
    segments: list[BriefingSegment] = Field(default_factory=list)


class BriefingInputDto(_CamelModel):
    """A briefing payload coming from the client (not yet persisted)."""

    name: str
    source_market: str = "EN"
    meta: BriefingMeta = Field(default_factory=BriefingMeta)
    segments: list[BriefingSegment] = Field(default_factory=list)


class MarketTranslationDto(_CamelModel):
    market: str
    segments: list[BriefingSegment]


class TranslateBriefingRequestDto(_CamelModel):
    briefing: BriefingInputDto
    markets: list[str] = Field(min_length=1)
    tone: str | None = None


class RenameBriefingDto(_CamelModel):
    name: str


class TranslateBriefingResponseDto(_CamelModel):
    translations: list[MarketTranslationDto]


class SaveBriefingRequestDto(_CamelModel):
    briefing: BriefingInputDto
    translations: list[MarketTranslationDto] = Field(default_factory=list)


class TmImportResultDto(_CamelModel):
    imported: int
    markets: list[str]


class GlossaryTermInputDto(_CamelModel):
    market: str
    source: str
    target: str


class GlossaryTermUpdateDto(_CamelModel):
    market: str | None = None
    source: str | None = None
    target: str | None = None
