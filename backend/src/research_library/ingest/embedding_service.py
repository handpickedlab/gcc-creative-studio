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

"""Claim/query embeddings via gemini-embedding-001.

gemini-embedding-001 is the one current Vertex embedding model that is
explicitly multilingual (the corpus mixes EN, NL and DE and users ask Dutch
questions about English decks). Two API realities shape this module:

- The model returns ONE embedding per request: passing several ``contents``
  silently collapses them into a single vector, so ``embed_texts`` loops and
  makes one call per text. At <$0.50 for the whole corpus this is fine.
- Vectors are MRL-truncated to 768 dimensions via ``output_dimensionality``,
  and truncated vectors are NOT unit-length, so they are re-normalized here
  before storage/search (cosine math assumes unit vectors).
"""

import logging
import math
import time

from google.genai import types

from src.research_library import config

logger = logging.getLogger(__name__)

# Asymmetric retrieval task types: documents are embedded with one, queries
# with the other. Using the wrong pairing measurably hurts recall.
TASK_DOCUMENT = "RETRIEVAL_DOCUMENT"
TASK_QUERY = "RETRIEVAL_QUERY"

_ATTEMPTS = 3
_RETRY_DELAY_SECONDS = 1.5


class EmbeddingError(Exception):
    """Raised when a text could not be embedded after retries."""


def _normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [value / norm for value in vector]


def embed_text(
    client,
    text: str,
    task_type: str = TASK_DOCUMENT,
) -> list[float]:
    """Embeds a single text into a unit-length 768-dim vector."""
    last_error: Exception | None = None
    for attempt in range(_ATTEMPTS):
        try:
            response = client.models.embed_content(
                model=config.EMBED_MODEL,
                contents=text,
                config=types.EmbedContentConfig(
                    task_type=task_type,
                    output_dimensionality=config.EMBED_DIMENSIONS,
                ),
            )
            values = list(response.embeddings[0].values)
            return _normalize(values)
        except Exception as e:
            last_error = e
            logger.warning(
                "Embedding attempt %s failed: %s", attempt + 1, e
            )
            if attempt + 1 < _ATTEMPTS:
                time.sleep(_RETRY_DELAY_SECONDS * (attempt + 1))

    raise EmbeddingError(
        f"embedding failed after {_ATTEMPTS} attempts: {last_error}"
    )


def embed_texts(
    client,
    texts: list[str],
    task_type: str = TASK_DOCUMENT,
) -> list[list[float]]:
    """Embeds each text with its own API call (see module docstring)."""
    return [embed_text(client, text, task_type) for text in texts]
