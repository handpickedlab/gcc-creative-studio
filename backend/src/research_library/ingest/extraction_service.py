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

"""Per-page multimodal claim extraction.

Each rendered page image is sent to Gemini once (single image per call: this
keeps provenance exact, retries cheap, and avoids the documented multi-image
attention degradation). The response is forced into a flat JSON schema — no
``additionalProperties``, shallow nesting — because complex schemas can 400,
and it is validated with Pydantic regardless of the server-side guarantee.

The corpus is largely chart-dense infographic slides whose PDFs often have no
text layer at all, so everything the model reports comes from *looking at*
the page. Claim statements stay in the page's source language (cross-language
retrieval is the embedding model's job); metric names and tags are English.
"""

import json
import logging
import time
from typing import Literal

from google.genai import types
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

_RETRY_DELAY_SECONDS = 2.0


class ExtractionError(Exception):
    """Raised when a page could not be extracted after retries."""


class ExtractedClaim(BaseModel):
    """One atomic, self-contained insight read off a page."""

    statement: str = Field(
        description=(
            "A single self-contained factual sentence in the page's own "
            "language, understandable without seeing the page."
        ),
    )
    metric: str | None = Field(
        default=None,
        description=(
            "Generic English metric name WITHOUT dimensions, e.g. 'online "
            "share of spending' — never 'online share Health & Beauty 2030'."
        ),
    )
    value: str | None = Field(
        default=None,
        description="The value as printed, e.g. '46%', '9.3 billion EUR'.",
    )
    unit: str | None = None
    segment: str | None = Field(
        default=None,
        description="Population or product segment, e.g. 'online buyers 15+'.",
    )
    geography: str | None = Field(
        default=None,
        description="Geographic scope, e.g. 'NL', 'Germany', 'global'.",
    )
    period: str | None = Field(
        default=None,
        description="Time period the claim is about, e.g. '2024', 'Q1 2025'.",
    )
    claim_type: Literal["measurement", "forecast"] | None = None
    source_citation: str | None = Field(
        default=None,
        description=(
            "The on-page source footnote, e.g. 'Thuiswinkel Markt Monitor "
            "2024, vraag A03'."
        ),
    )
    sample: str | None = Field(
        default=None,
        description="Sample size if stated, e.g. 'n=1,006'.",
    )
    tags: list[str] = Field(
        default_factory=list,
        description="1-4 lowercase English topic tags.",
    )


class PageExtraction(BaseModel):
    """Everything extracted from one page image."""

    takeaway: str | None = Field(
        default=None,
        description=(
            "The page's single main message, usually its title, in the "
            "page's own language. Null for covers/dividers/agendas."
        ),
    )
    language: str | None = Field(
        default=None,
        description="ISO 639-1 code of the page's dominant language.",
    )
    claims: list[ExtractedClaim] = Field(default_factory=list)


_PROMPT = """\
You are extracting insights from one page of a market research document
(trend report, market monitor or slide deck) for a searchable fact library.

Read the page image carefully — titles, chart bars and labels, legends,
callout numbers and source footnotes — and extract EVERY hard insight as an
atomic claim:

- One claim per fact. A chart comparing 18 categories yields many claims;
  prefer the ones the page itself emphasizes (title, callouts) plus every
  clearly labeled data point you can read with confidence.
- Each statement must stand alone: include the metric, value, segment,
  geography and period IN the sentence, in the page's own language.
- Never invent numbers. If a bar's value is not printed or legible, skip it.
- metric names and tags are generic English; dimensions (segment, period,
  geography) go in their own fields, NEVER inside the metric name.
- claim_type: 'forecast' for expectations/projections (e.g. 2030 targets),
  'measurement' for measured/reported figures.
- Copy source footnotes (Bron/Source/Quelle...) into source_citation and the
  sample size (n=...) into sample when present.
- Cover pages, agendas, dividers and pure photo pages: return takeaway=null
  and an empty claims list.
"""

_VOCABULARY_TEMPLATE = """
Prefer these existing tags where they apply (propose a new lowercase English
tag ONLY if none fits): {vocabulary}
"""


def extract_page(
    client,
    model: str,
    image_gcs_uri: str,
    vocabulary: list[str] | None = None,
    attempts: int = 2,
) -> PageExtraction:
    """Extracts claims from one page image stored in GCS.

    Retries once on any failure (transient API errors, malformed JSON); a
    page that still fails is the caller's problem to record and skip — one
    bad page must never sink a 100-page document.
    """
    prompt = _PROMPT
    if vocabulary:
        prompt += _VOCABULARY_TEMPLATE.format(
            vocabulary=", ".join(sorted(vocabulary)),
        )

    image_part = types.Part.from_uri(
        file_uri=image_gcs_uri,
        mime_type="image/png",
    )

    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            response = client.models.generate_content(
                model=model,
                contents=[image_part, prompt],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=PageExtraction,
                    temperature=0,
                ),
            )
            return PageExtraction.model_validate(
                json.loads(response.text or "{}"),
            )
        except Exception as e:
            last_error = e
            logger.warning(
                "Extraction attempt %s failed for %s: %s",
                attempt + 1,
                image_gcs_uri,
                e,
            )
            if attempt + 1 < attempts:
                time.sleep(_RETRY_DELAY_SECONDS * (attempt + 1))

    raise ExtractionError(
        f"extraction failed after {attempts} attempts: {last_error}"
    )
