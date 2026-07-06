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

"""Tests for extraction_service and embedding_service."""

import json
import math
from unittest.mock import MagicMock, patch

import pytest

from src.research_library.ingest.embedding_service import (
    EmbeddingError,
    embed_text,
    embed_texts,
)
from src.research_library.ingest.extraction_service import (
    ExtractionError,
    extract_page,
)

_VALID_EXTRACTION = {
    "takeaway": (
        "Online kopers verwachten in 2030 bijna de helft van hun aankopen "
        "via een smartphone te doen"
    ),
    "language": "nl",
    "claims": [
        {
            "statement": (
                "In 2030 verwachten online kopers gemiddeld 46% van al hun "
                "online aankopen via een smartphone te doen"
            ),
            "metric": "share of online purchases via smartphone",
            "value": "46%",
            "segment": "online kopers 15+",
            "geography": "NL",
            "period": "2030",
            "claim_type": "forecast",
            "source_citation": "Thuiswinkel Markt Monitor Q1 2025",
            "sample": "n=916",
            "tags": ["mobile commerce", "online shopping"],
        },
    ],
}


def _response(payload) -> MagicMock:
    response = MagicMock()
    response.text = json.dumps(payload) if isinstance(payload, dict) else payload
    return response


@patch("src.research_library.ingest.extraction_service.time.sleep")
class TestExtractPage:
    def test_parses_valid_extraction(self, _sleep):
        client = MagicMock()
        client.models.generate_content.return_value = _response(
            _VALID_EXTRACTION
        )

        extraction = extract_page(
            client, "gemini-test", "gs://bucket/pages/0001.png"
        )

        assert extraction.language == "nl"
        assert len(extraction.claims) == 1
        claim = extraction.claims[0]
        assert claim.value == "46%"
        assert claim.claim_type == "forecast"
        assert claim.tags == ["mobile commerce", "online shopping"]

    def test_retries_once_on_malformed_json(self, _sleep):
        client = MagicMock()
        client.models.generate_content.side_effect = [
            _response("{not json"),
            _response(_VALID_EXTRACTION),
        ]

        extraction = extract_page(
            client, "gemini-test", "gs://bucket/pages/0001.png"
        )

        assert client.models.generate_content.call_count == 2
        assert len(extraction.claims) == 1

    def test_raises_extraction_error_after_retries(self, _sleep):
        client = MagicMock()
        client.models.generate_content.side_effect = RuntimeError("quota")

        with pytest.raises(ExtractionError, match="quota"):
            extract_page(
                client, "gemini-test", "gs://bucket/pages/0001.png"
            )
        assert client.models.generate_content.call_count == 2

    def test_vocabulary_lands_in_prompt(self, _sleep):
        client = MagicMock()
        client.models.generate_content.return_value = _response(
            _VALID_EXTRACTION
        )

        extract_page(
            client,
            "gemini-test",
            "gs://bucket/pages/0001.png",
            vocabulary=["mobile-commerce", "sustainability"],
        )

        contents = client.models.generate_content.call_args.kwargs["contents"]
        prompt = contents[1]
        assert "mobile-commerce" in prompt
        assert "sustainability" in prompt

    def test_empty_page_yields_no_claims(self, _sleep):
        client = MagicMock()
        client.models.generate_content.return_value = _response(
            {"takeaway": None, "language": None, "claims": []}
        )

        extraction = extract_page(
            client, "gemini-test", "gs://bucket/pages/0001.png"
        )

        assert extraction.claims == []


@patch("src.research_library.ingest.embedding_service.time.sleep")
class TestEmbedding:
    def _client_returning(self, values):
        client = MagicMock()
        embedding = MagicMock()
        embedding.values = values
        response = MagicMock()
        response.embeddings = [embedding]
        client.models.embed_content.return_value = response
        return client

    def test_embedding_is_renormalized_to_unit_length(self, _sleep):
        client = self._client_returning([3.0, 4.0, 0.0])

        vector = embed_text(client, "hello")

        norm = math.sqrt(sum(v * v for v in vector))
        assert norm == pytest.approx(1.0)
        assert vector == pytest.approx([0.6, 0.8, 0.0])

    def test_one_api_call_per_text(self, _sleep):
        client = self._client_returning([1.0, 0.0])

        vectors = embed_texts(client, ["een", "twee", "drie"])

        assert len(vectors) == 3
        assert client.models.embed_content.call_count == 3

    def test_raises_embedding_error_after_retries(self, _sleep):
        client = MagicMock()
        client.models.embed_content.side_effect = RuntimeError("429")

        with pytest.raises(EmbeddingError, match="429"):
            embed_text(client, "hello")
        assert client.models.embed_content.call_count == 3
