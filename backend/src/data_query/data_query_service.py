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

"""Business logic for the data-query tool: ingest sheets and run the agent."""
import logging
from collections.abc import Iterator
from functools import partial

from fastapi import Depends

from src.data_query import agent
from src.data_query import duckdb_store as store
from src.multimodal.gemini_service import GeminiService
from src.research_library.search import claim_search_service

logger = logging.getLogger(__name__)


class DataQueryService:
    """Ingests uploaded spreadsheets into DuckDB and answers questions over
    them — and over the research document library — with a Gemini
    function-calling agent."""

    def __init__(self, gemini_service: GeminiService = Depends()):
        self.gemini = gemini_service

    def ingest(self, filename: str, data: bytes) -> list[dict]:
        return store.ingest_bytes(filename, data)

    def list_sources(self) -> list[dict]:
        return store.list_tables()

    def stream(
        self,
        question: str,
        allowed_tables: list[str] | None = None,
        allowed_documents: list[int] | None = None,
    ) -> Iterator[dict]:
        """Yield the agent's streaming events for a question."""
        client = self.gemini.client
        model = self.gemini.cfg.GEMINI_MODEL_ID
        allowed = set(allowed_tables) if allowed_tables else None
        claim_search = partial(
            claim_search_service.search_claims_sync, client
        )
        yield from agent.stream_answer(
            client,
            model,
            question,
            allowed,
            claim_search=claim_search,
            allowed_documents=allowed_documents,
        )
