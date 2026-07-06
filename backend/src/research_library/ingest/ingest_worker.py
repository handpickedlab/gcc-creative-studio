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

"""Background ingest worker for the research library.

Follows the ``brand_guidelines`` worker pattern: a module-level function
submitted to a ``ThreadPoolExecutor`` (the dedicated
``app.state.research_ingest_executor``, not the shared one), which owns its
own event loop and a per-thread ``WorkerDatabase()`` engine.

This module ships as a stub for Unit 1: ``_run_ingest_pipeline`` always ends
the document in FAILED with a placeholder error. Units 2/3 replace its body
with the real convert -> render -> extract -> embed pipeline; the
``run_ingest(document_id)`` signature, the executor it is submitted to, and
the tombstone check before the terminal write all stay the same.
"""

import asyncio
import logging

from src.research_library.schema.research_document_model import (
    ResearchDocStatus,
)

logger = logging.getLogger(__name__)


def run_ingest(document_id: int) -> None:
    """Entry point submitted to the dedicated research-ingest executor.

    Runs in a worker thread with its own event loop and database engine, so
    it never shares a connection or loop with the request that queued it.
    """
    worker_logger = logging.getLogger(f"research_library_worker.{document_id}")

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(
            _run_ingest_pipeline(document_id, worker_logger),
        )
    except Exception:
        worker_logger.error(
            "Research library ingest worker crashed for document %s.",
            document_id,
            exc_info=True,
        )
    finally:
        loop.close()


async def _run_ingest_pipeline(
    document_id: int,
    worker_logger: logging.Logger,
) -> None:
    """The actual pipeline body. Unit 1: a placeholder that always fails."""
    from src.database import WorkerDatabase
    from src.research_library.repository.research_document_repository import (
        ResearchDocumentRepository,
    )

    async with WorkerDatabase() as db_factory:
        async with db_factory() as db:
            repo = ResearchDocumentRepository(db)

            # Tombstone check: if the document was deleted while this job
            # was queued, abort without resurrecting it.
            document = await repo.find_active_by_id(document_id)
            if not document:
                worker_logger.warning(
                    "Document %s no longer exists; aborting ingest.",
                    document_id,
                )
                return

            # TODO(Unit 2/3): convert -> render -> per-page extract ->
            # per-claim embed -> persist claims/pages, ending in COMPLETED or
            # COMPLETED_WITH_ERRORS. For now, fail fast and visibly.
            await repo.update(
                document_id,
                {
                    "status": ResearchDocStatus.FAILED.value,
                    "error_message": "ingest pipeline not yet implemented",
                },
            )
            worker_logger.info(
                "Document %s marked FAILED (ingest pipeline stub).",
                document_id,
            )
