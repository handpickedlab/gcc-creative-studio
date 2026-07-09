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

"""Business logic for the data-query tool: ingest sheets and run the agent.

Persistence model: the DuckDB warehouse is a local, ephemeral cache on each
Cloud Run instance. The durable source of truth is a Postgres catalog
(`data_query_sheets`) plus the raw uploaded files in GCS. On upload we write
to all three; before answering a question we rehydrate the local DuckDB from
GCS for any cataloged table this instance is missing, so sheets survive
restarts and are shared across instances.
"""
import asyncio
import logging
import uuid
from collections.abc import Iterator
from functools import partial

from fastapi import Depends

from src.common.storage_service import GcsService
from src.data_query import agent
from src.data_query import duckdb_store as store
from src.data_query.repository.data_query_sheet_repository import (
    DataQuerySheetRepository,
)
from src.data_query.schema.data_query_sheet_model import DataQuerySheetModel
from src.multimodal.gemini_service import GeminiService
from src.research_library.search import claim_search_service

logger = logging.getLogger(__name__)

_SHEET_PREFIX = "data-query-sheets/global"


class DataQueryService:
    """Ingests uploaded spreadsheets (durably) and answers questions over
    them — and over the research document library — with a Gemini agent."""

    def __init__(
        self,
        gemini_service: GeminiService = Depends(),
        sheet_repo: DataQuerySheetRepository = Depends(),
        gcs_service: GcsService = Depends(),
    ):
        self.gemini = gemini_service
        self.sheet_repo = sheet_repo
        self.gcs = gcs_service

    async def ingest(self, filename: str, data: bytes) -> list[dict]:
        """Load a sheet into DuckDB, store the raw file in GCS, and record
        each resulting table in the durable catalog."""
        # 1. Load into the local DuckDB (also validates the file).
        tables = await asyncio.to_thread(store.ingest_bytes, filename, data)

        # 2. Persist the raw file so any instance can rehydrate later.
        blob = f"{_SHEET_PREFIX}/{uuid.uuid4()}/{filename}"
        gcs_uri = await asyncio.to_thread(
            self.gcs.upload_bytes_to_gcs,
            data,
            blob,
            "application/octet-stream",
        )
        if not gcs_uri:
            raise RuntimeError("could not store the uploaded file")

        # 3. Catalog each table (replacing any prior row with the same name).
        for t in tables:
            await self.sheet_repo.deactivate_table(t["table"])
            await self.sheet_repo.create(
                DataQuerySheetModel(
                    table_name=t["table"],
                    source_file=t["source_file"],
                    sheet=t.get("sheet"),
                    n_rows=t.get("n_rows"),
                    n_cols=len(t.get("columns") or []),
                    columns=t.get("columns") or [],
                    gcs_uri=gcs_uri,
                ),
            )
        return tables

    async def list_sheets(self) -> list[DataQuerySheetModel]:
        """The durable catalog of uploaded sheets (for the manage page)."""
        return await self.sheet_repo.list_active()

    async def list_sources(self) -> list[dict]:
        """Lightweight source list for the query sidebar (from the catalog)."""
        sheets = await self.sheet_repo.list_active()
        return [{"table": s.table_name, "n_rows": s.n_rows} for s in sheets]

    async def delete_sheet(self, sheet_id: int) -> bool:
        """Soft-delete a sheet: catalog row, local DuckDB table, and the raw
        GCS file when no other table still references it."""
        sheet = await self.sheet_repo.find_active_by_id(sheet_id)
        if not sheet:
            return False
        await self.sheet_repo.soft_delete(sheet_id)
        await asyncio.to_thread(store.drop_table, sheet.table_name)
        if not await self.sheet_repo.gcs_uri_still_used(sheet.gcs_uri, sheet_id):
            await asyncio.to_thread(self.gcs.delete_blob_from_uri, sheet.gcs_uri)
        return True

    async def ensure_loaded(self) -> None:
        """Rehydrate this instance's DuckDB from GCS for any cataloged table
        it is missing (self-healing after a restart or on a fresh instance)."""
        sheets = await self.sheet_repo.list_active()
        if not sheets:
            return
        present = await asyncio.to_thread(store.loaded_table_names)
        missing = [s for s in sheets if s.table_name not in present]
        if not missing:
            return
        # One raw file can back several tables; download each file once.
        for gcs_uri in {s.gcs_uri for s in missing}:
            source = next(s for s in missing if s.gcs_uri == gcs_uri)
            try:
                data = await asyncio.to_thread(
                    self.gcs.download_bytes_from_gcs, gcs_uri
                )
                if data:
                    await asyncio.to_thread(
                        store.ingest_bytes, source.source_file, data
                    )
            except Exception as e:
                logger.error("Rehydrate failed for %s: %s", gcs_uri, e)

    def stream(
        self,
        question: str,
        allowed_tables: list[str] | None = None,
        allowed_documents: list[int] | None = None,
    ) -> Iterator[dict]:
        """Yield the agent's streaming events. Callers must `await
        ensure_loaded()` before iterating so the DuckDB warehouse is current."""
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
