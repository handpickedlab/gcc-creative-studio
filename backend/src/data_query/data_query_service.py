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
import time
import uuid
from collections.abc import Iterator
from functools import partial

from fastapi import Depends

from src.common.storage_service import GcsService
from src.data_query import agent
from src.data_query import duckdb_store as store
from src.data_query.repository.data_query_run_repository import (
    DataQueryRunRepository,
)
from src.data_query.repository.data_query_sheet_repository import (
    DataQuerySheetRepository,
)
from src.data_query.schema.data_query_run_model import DataQueryRunModel
from src.data_query.schema.data_query_sheet_model import DataQuerySheetModel
from src.database import async_session_local
from src.multimodal.gemini_service import GeminiService
from src.research_library.search import claim_search_service

logger = logging.getLogger(__name__)

_SHEET_PREFIX = "data-query-sheets/global"

# How often the background worker flushes the accumulating trace to the DB so
# the client's poll (GET /ask/{id}) shows live progress. The hosting rewrite
# buffers and times out long streaming responses (~60s), and deep retrieval can
# run well past that, so polling — not SSE — is the reliable path in prod.
_PROGRESS_FLUSH_S = 1.5
# Hold references to in-flight background tasks so they aren't garbage-collected
# if the launching request returns first. CPU stays allocated (cpu-throttling is
# disabled), but the service runs min-instances=0 since 2026-08-11, so what keeps
# the instance alive mid-run is the client's own polling — a run whose client
# walks away can lose its instance before it finishes.
_ASK_TASKS: set[asyncio.Task] = set()


def _set_thinking(steps: list[dict], n: int | None) -> None:
    """Keep exactly one trailing "the model is thinking" marker.

    It is a live-progress artefact, not part of the answer trace: the next tool
    call or text chunk drops it again, so a finished run stores only its real
    steps and the collapsible trace stays clean.
    """
    _clear_thinking(steps)
    steps.append({"kind": "model", "n": n})


def _clear_thinking(steps: list[dict]) -> None:
    if steps and steps[-1].get("kind") == "model":
        steps.pop()


class DataQueryService:
    """Ingests uploaded spreadsheets (durably) and answers questions over
    them — and over the research document library — with a Gemini agent."""

    def __init__(
        self,
        gemini_service: GeminiService = Depends(),
        sheet_repo: DataQuerySheetRepository = Depends(),
        run_repo: DataQueryRunRepository = Depends(),
        gcs_service: GcsService = Depends(),
    ):
        self.gemini = gemini_service
        self.sheet_repo = sheet_repo
        self.run_repo = run_repo
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

    async def ensure_loaded(
        self, sheet_repo: DataQuerySheetRepository | None = None
    ) -> None:
        """Rehydrate this instance's DuckDB from GCS for any cataloged table
        it is missing (self-healing after a restart or on a fresh instance).

        Accepts an explicit ``sheet_repo`` so a background task can pass a repo
        bound to its own DB session (the request-scoped ``self.sheet_repo`` is
        closed once the launching request returns)."""
        repo = sheet_repo or self.sheet_repo
        sheets = await repo.list_active()
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
        history: list[dict] | None = None,
        min_period: str | None = None,
    ) -> Iterator[dict]:
        """Yield the agent's streaming events. Callers must `await
        ensure_loaded()` before iterating so the DuckDB warehouse is current.

        ``history`` seeds prior question/answer turns for follow-up context."""
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
            history=history,
            list_tags=claim_search_service.list_tags_sync,
            list_facets=claim_search_service.list_facets_sync,
            min_period=min_period,
        )

    # ── background ask (poll model) ─────────────────────────────────
    async def start_ask(
        self,
        question: str,
        allowed_tables: list[str] | None = None,
        allowed_documents: list[int] | None = None,
        history: list[dict] | None = None,
        min_period: str | None = None,
    ) -> DataQueryRunModel:
        """Create a run row and kick the agent off in the background.

        Returns immediately with the run (status ``processing``); the client
        polls :meth:`get_run` until it is ``completed`` or ``failed``. Deep
        retrieval can outlast the hosting rewrite's ~60s buffered-response
        timeout, so we never hold the request open for the whole answer."""
        run = await self.run_repo.create(
            DataQueryRunModel(id=uuid.uuid4().hex, question=question)
        )
        task = asyncio.create_task(
            self._run_ask(
                run.id,
                question,
                allowed_tables,
                allowed_documents,
                history,
                min_period,
            )
        )
        _ASK_TASKS.add(task)
        task.add_done_callback(_ASK_TASKS.discard)
        logger.info("Data-query ask queued: %s", run.id)
        return run

    async def get_run(self, run_id: str) -> DataQueryRunModel | None:
        """Fetch a run's current state (for polling)."""
        return await self.run_repo.get_by_id(run_id)

    async def _run_ask(
        self,
        run_id: str,
        question: str,
        allowed_tables: list[str] | None,
        allowed_documents: list[int] | None,
        history: list[dict] | None,
        min_period: str | None,
    ) -> None:
        """Background worker: run the agent, assemble the trace, and persist it.

        Uses its own short-lived DB sessions (the launching request's session is
        already closed) and runs the synchronous agent generator in a thread so
        the event loop stays free to flush progress and serve poll requests."""
        steps: list[dict] = []
        sources: list[list] = [[]]  # 1-slot holder written by the worker thread

        def _consume() -> None:
            cur_text: dict | None = None
            cur_tool: dict | None = None
            client = self.gemini.client
            model = self.gemini.cfg.GEMINI_MODEL_ID
            allowed = set(allowed_tables) if allowed_tables else None
            claim_search = partial(
                claim_search_service.search_claims_sync, client
            )
            for ev in agent.stream_answer(
                client,
                model,
                question,
                allowed,
                claim_search=claim_search,
                allowed_documents=allowed_documents,
                history=history,
                list_tags=claim_search_service.list_tags_sync,
                list_facets=claim_search_service.list_facets_sync,
                min_period=min_period,
            ):
                t = ev.get("t")
                if t == "step":
                    # A model turn is starting: show it, drop it again as soon
                    # as the turn produces something real.
                    _set_thinking(steps, ev.get("n"))
                    continue
                if t in ("tool", "text", "error"):
                    _clear_thinking(steps)
                if t == "tool":
                    cur_text = None
                    cur_tool = {
                        "kind": "tool",
                        "name": ev.get("name"),
                        "input": ev.get("input"),
                        "summary": "…",
                    }
                    steps.append(cur_tool)
                elif t == "tool_result":
                    if cur_tool is not None:
                        cur_tool["summary"] = ev.get("summary") or ""
                        cur_tool["result"] = ev.get("result")
                        cur_tool["ms"] = ev.get("ms")
                elif t == "text":
                    if cur_text is None:
                        cur_text = {"kind": "text", "text": ""}
                        steps.append(cur_text)
                    cur_text["text"] = (cur_text.get("text") or "") + (
                        ev.get("v") or ""
                    )
                elif t == "sources":
                    sources[0] = ev.get("v") or []
                elif t == "error":
                    steps.append(
                        {
                            "kind": "text",
                            "text": "⚠️ " + (ev.get("message") or "error"),
                        }
                    )

        async def _flush() -> None:
            while True:
                await asyncio.sleep(_PROGRESS_FLUSH_S)
                try:
                    async with async_session_local() as db:
                        await DataQueryRunRepository(db).update(
                            run_id, {"steps": list(steps)}
                        )
                except Exception:
                    pass  # progress is best-effort

        # Rehydrate DuckDB with a fresh session before answering.
        try:
            async with async_session_local() as db:
                await self.ensure_loaded(DataQuerySheetRepository(db))
        except Exception as e:
            logger.error("Rehydrate before ask failed for %s: %s", run_id, e)

        flusher = asyncio.create_task(_flush())
        started = time.monotonic()
        try:
            await asyncio.to_thread(_consume)
            flusher.cancel()
            _clear_thinking(steps)
            logger.info(
                "Data-query ask %s done in %.1fs: %s steps",
                run_id,
                time.monotonic() - started,
                len(steps),
            )
            async with async_session_local() as db:
                await DataQueryRunRepository(db).update(
                    run_id,
                    {
                        "status": "completed",
                        "steps": list(steps),
                        "answer_sources": sources[0],
                    },
                )
        except Exception as e:
            flusher.cancel()
            _clear_thinking(steps)
            logger.error(
                "Data-query ask %s failed: %s", run_id, e, exc_info=True
            )
            try:
                async with async_session_local() as db:
                    await DataQueryRunRepository(db).update(
                        run_id,
                        {
                            "status": "failed",
                            "steps": list(steps),
                            "error_message": f"{type(e).__name__}: {e}",
                        },
                    )
            except Exception:
                pass
