# Copyright 2025 Google LLC
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

import asyncio
import json
import logging
import os
import sys
from collections.abc import AsyncGenerator
from concurrent.futures import ThreadPoolExecutor

from fastapi import Depends, HTTPException, status
from google.cloud.logging import Client as LoggerClient
from google.cloud.logging.handlers import CloudLoggingHandler

from src.common.dto.pagination_response_dto import PaginationResponseDto
from src.common.schema.media_item_model import JobStatusEnum
from src.database import async_session_local
from src.deep_research.agent import build_root_agent, run_pipeline
from src.deep_research.agent.brief import (
    HUNKEMOLLER_COMPOSER_INSTRUCTION,
    build_brief,
    build_initial_state,
)
from src.deep_research.agent.intake import INTAKE_FIELDS, STEPPER_GROUPS
from src.deep_research.dto.deep_research_search_dto import DeepResearchSearchDto
from src.deep_research.dto.intake_schema_dto import (
    IntakeFieldDto,
    IntakeSchemaDto,
    IntakeStepDto,
)
from src.deep_research.dto.start_deep_research_dto import StartDeepResearchDto
from src.deep_research.repository.deep_research_repository import (
    DeepResearchRepository,
)
from src.deep_research.schema.deep_research_model import DeepResearchReportModel
from src.users.user_model import UserModel, UserRoleEnum

logger = logging.getLogger(__name__)

# Interval (seconds) between SSE heartbeat comments while the pipeline is quiet,
# so proxies don't close an idle connection.
_SSE_HEARTBEAT_S = 15
# How often the background worker flushes accumulated progress to the DB, so the
# client can poll GET /{id} and render live progress (SSE is buffered by the
# hosting CDN for long responses, so polling is the reliable path in production).
_PROGRESS_FLUSH_S = 1.5
# Keep references to in-flight streaming tasks so they aren't garbage collected
# if the client disconnects mid-run (CPU stays allocated: cpu-throttling=false).
_STREAM_TASKS: set[asyncio.Task] = set()


def _sse(payload: dict) -> str:
    """Format a payload as a Server-Sent-Events ``data:`` frame."""
    return "data: " + json.dumps(payload, default=str) + "\n\n"


def _run_deep_research_in_background(
    report_id: int,
    brief: str,
    initial_state: dict,
    max_iterations: int | None,
) -> None:
    """Long-running worker: run the ADK pipeline and persist the result.

    Runs in a separate thread with its own event loop and database engine (see
    :class:`src.database.WorkerDatabase`). On success the report row is marked
    COMPLETED with the cited Markdown; on failure it is marked FAILED with the
    error message.
    """
    worker_logger = logging.getLogger(f"deep_research_worker.{report_id}")
    worker_logger.setLevel(logging.INFO)

    try:
        from src.database import WorkerDatabase

        # --- Hybrid logging setup for the worker thread ---
        if worker_logger.hasHandlers():
            worker_logger.handlers.clear()

        if os.getenv("ENVIRONMENT") == "production":
            log_client = LoggerClient()
            handler = CloudLoggingHandler(
                log_client, name=f"deep_research_worker.{report_id}"
            )
            worker_logger.addHandler(handler)
        else:
            handler = logging.StreamHandler(sys.stdout)
            handler.setFormatter(
                logging.Formatter(
                    "%(asctime)s - [DEEP_RESEARCH_WORKER] - %(levelname)s - %(message)s",
                )
            )
            worker_logger.addHandler(handler)

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        async def _async_worker():
            async with WorkerDatabase() as db_factory:
                async with db_factory() as db:
                    repo = DeepResearchRepository(db)

                    # Accumulate the pipeline's per-step events; a flusher task
                    # persists them so the client can poll and show progress.
                    steps: list[dict] = []

                    def on_event(author: str, kind: str, text: str) -> None:
                        steps.append(
                            {
                                "author": author,
                                "kind": kind,
                                "text": text if kind == "tool" else text[:200],
                            }
                        )

                    async def _flush_progress() -> None:
                        async with db_factory() as progress_db:
                            progress_repo = DeepResearchRepository(progress_db)
                            while True:
                                await asyncio.sleep(_PROGRESS_FLUSH_S)
                                try:
                                    await progress_repo.update(
                                        report_id, {"progress": list(steps)}
                                    )
                                except Exception:
                                    pass  # progress is best-effort

                    flusher = asyncio.create_task(_flush_progress())
                    try:
                        worker_logger.info(
                            "Starting deep research pipeline for report %s.",
                            report_id,
                        )
                        agent = build_root_agent(
                            composer_instruction=HUNKEMOLLER_COMPOSER_INSTRUCTION,
                            max_iterations=max_iterations,
                        )
                        report = await run_pipeline(
                            agent, brief, initial_state, on_event
                        )
                        if not report:
                            raise RuntimeError(
                                "The research pipeline produced an empty report."
                            )

                        flusher.cancel()
                        await repo.update(
                            report_id,
                            {
                                "status": JobStatusEnum.COMPLETED,
                                "report": report,
                                "progress": list(steps),
                            },
                        )
                        worker_logger.info(
                            "Deep research report %s completed.", report_id
                        )
                    except Exception as e:
                        flusher.cancel()
                        worker_logger.error(
                            "Deep research pipeline failed.",
                            extra={
                                "json_fields": {
                                    "report_id": report_id,
                                    "error": str(e),
                                },
                            },
                            exc_info=True,
                        )
                        await repo.update(
                            report_id,
                            {
                                "status": JobStatusEnum.FAILED,
                                "error_message": str(e),
                                "progress": list(steps),
                            },
                        )

        loop.run_until_complete(_async_worker())
        loop.close()

    except Exception as e:
        worker_logger.error(
            "Deep research worker failed to initialize.",
            extra={"json_fields": {"report_id": report_id, "error": str(e)}},
            exc_info=True,
        )


class DeepResearchService:
    """Business logic for the Hunkemöller Consumer Sentiment Scan.

    Assembles the brief from the intake, persists a placeholder report and runs
    the multi-agent pipeline in a background job that updates the report when it
    finishes.
    """

    def __init__(self, repo: DeepResearchRepository = Depends()):
        self.repo = repo

    def _authorize(
        self, report: DeepResearchReportModel, current_user: UserModel
    ) -> None:
        """Reports are private to their owner; admins may access any report."""
        is_admin = UserRoleEnum.ADMIN in current_user.roles
        if report.user_id != current_user.id and not is_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not authorized to access this report.",
            )

    def get_intake_schema(self) -> IntakeSchemaDto:
        """Return the intake field schema + stepper grouping for the UI."""
        fields = [
            IntakeFieldDto(
                key=f.key,
                label=f.label,
                type=f.type.value,
                brief_label=f.brief_label,
                options=list(f.options),
                example=f.example,
                help=f.help,
            )
            for f in INTAKE_FIELDS
        ]
        steps = [
            IntakeStepDto(title=title, field_keys=list(keys))
            for title, keys in STEPPER_GROUPS
        ]
        return IntakeSchemaDto(fields=fields, steps=steps)

    async def start_research(
        self,
        dto: StartDeepResearchDto,
        current_user: UserModel,
        executor: ThreadPoolExecutor,
    ) -> DeepResearchReportModel:
        """Create a placeholder report and queue the research pipeline."""
        intake = dto.intake_values()
        brief = build_brief(intake)
        initial_state = build_initial_state(intake)

        placeholder = DeepResearchReportModel(
            user_id=current_user.id,
            topic=dto.research_topic,
            status=JobStatusEnum.PROCESSING,
            max_iterations=dto.max_iterations,
            intake=intake,
            brief=brief,
        )
        placeholder = await self.repo.create(placeholder)

        executor.submit(
            _run_deep_research_in_background,
            report_id=placeholder.id,
            brief=brief,
            initial_state=initial_state,
            max_iterations=dto.max_iterations,
        )
        logger.info("Deep research job queued: %s", placeholder.id)

        return placeholder

    async def stream_research(
        self,
        dto: StartDeepResearchDto,
        current_user: UserModel,
    ) -> AsyncGenerator[str, None]:
        """Start a scan and stream the agent's progress as SSE frames.

        Emits ``start`` (with the report id), then a ``step`` per pipeline event
        (plan / search / reflect / compose / verify), then ``done`` or ``error``.
        The pipeline runs as a task with its own DB session so the report is
        persisted even if the client disconnects (Cloud Run keeps CPU allocated).
        """
        intake = dto.intake_values()
        brief = build_brief(intake)
        initial_state = build_initial_state(intake)

        placeholder = await self.repo.create(
            DeepResearchReportModel(
                user_id=current_user.id,
                topic=dto.research_topic,
                status=JobStatusEnum.PROCESSING,
                max_iterations=dto.max_iterations,
                intake=intake,
                brief=brief,
            )
        )
        report_id = placeholder.id
        yield _sse({"t": "start", "id": report_id, "topic": placeholder.topic})

        queue: asyncio.Queue = asyncio.Queue()

        def on_event(author: str, kind: str, text: str) -> None:
            # Called synchronously from inside the pipeline's async loop.
            try:
                queue.put_nowait(
                    {"t": "step", "author": author, "kind": kind, "text": text}
                )
            except Exception:  # never let progress reporting break the run
                pass

        async def _run() -> None:
            try:
                agent = build_root_agent(
                    composer_instruction=HUNKEMOLLER_COMPOSER_INSTRUCTION,
                    max_iterations=dto.max_iterations,
                )
                report = await run_pipeline(
                    agent, brief, initial_state, on_event
                )
                async with async_session_local() as db:
                    repo = DeepResearchRepository(db)
                    if report:
                        await repo.update(
                            report_id,
                            {"status": JobStatusEnum.COMPLETED, "report": report},
                        )
                    else:
                        await repo.update(
                            report_id,
                            {
                                "status": JobStatusEnum.FAILED,
                                "error_message": "The research pipeline produced an empty report.",
                            },
                        )
                queue.put_nowait(
                    {
                        "t": "done",
                        "id": report_id,
                        "status": "completed" if report else "failed",
                    }
                )
            except Exception as e:
                logger.error(
                    "Deep research stream failed for %s: %s",
                    report_id,
                    e,
                    exc_info=True,
                )
                try:
                    async with async_session_local() as db:
                        await DeepResearchRepository(db).update(
                            report_id,
                            {
                                "status": JobStatusEnum.FAILED,
                                "error_message": str(e),
                            },
                        )
                except Exception:
                    pass
                queue.put_nowait(
                    {"t": "error", "id": report_id, "message": str(e)}
                )
            finally:
                queue.put_nowait(None)

        task = asyncio.create_task(_run())
        _STREAM_TASKS.add(task)
        task.add_done_callback(_STREAM_TASKS.discard)

        while True:
            try:
                item = await asyncio.wait_for(
                    queue.get(), timeout=_SSE_HEARTBEAT_S
                )
            except asyncio.TimeoutError:
                yield ": ping\n\n"  # SSE comment keeps the connection alive
                continue
            if item is None:
                break
            yield _sse(item)

    async def list_reports(
        self,
        search_dto: DeepResearchSearchDto,
        current_user: UserModel,
    ) -> PaginationResponseDto[DeepResearchReportModel]:
        """List the current user's reports, newest first."""
        return await self.repo.query(search_dto, user_id=current_user.id)

    async def get_report(
        self,
        report_id: int,
        current_user: UserModel,
    ) -> DeepResearchReportModel | None:
        """Fetch a single report after an ownership check."""
        report = await self.repo.get_by_id(report_id)
        if not report:
            return None
        self._authorize(report, current_user)
        return report

    async def delete_report(
        self,
        report_id: int,
        current_user: UserModel,
    ) -> None:
        """Delete a report after an ownership check."""
        report = await self.repo.get_by_id(report_id)
        if not report:
            return
        self._authorize(report, current_user)
        await self.repo.delete(report_id)
