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

"""Re-queues research documents whose ingest died with its instance.

Ingest runs on an in-process ThreadPoolExecutor, so anything that ends the
process takes the pending queue with it: a Cloud Run scale-down (as soon as
request traffic stops, and on every deploy) or an OOM kill. The 23 July 2026
bulk upload hit both within ten minutes and left 120 documents in PROCESSING
forever — no worker owned them, nothing retried them, and ``/reprocess``
refused to touch a document that still claimed to be processing.

This sweeper makes the database the queue of record. Every few minutes it
looks for PROCESSING documents that have not made progress for
``config.STALE_AFTER_SECONDS``, claims each one atomically under a fresh
ingest run, and resubmits it — never more than this process has free
capacity for, so the in-memory queue stays shallow enough that losing it
costs at most a few minutes of work. A document that keeps dying is retried
``config.MAX_INGEST_ATTEMPTS`` times and then failed, so a file too heavy for
the instance can't take it down on a loop.

Every instance runs its own sweeper; the atomic claim in
``ResearchDocumentRepository.claim_stalled`` decides who gets what.
"""

import asyncio
import datetime
import logging
import uuid
from concurrent.futures import ThreadPoolExecutor

from src.research_library import config
from src.research_library.ingest import ingest_queue
from src.research_library.ingest.ingest_worker import run_ingest
from src.research_library.repository.research_document_repository import (
    ResearchDocumentRepository,
)
from src.research_library.schema.research_document_model import (
    ResearchDocStatus,
)

logger = logging.getLogger(__name__)


async def sweep_once(executor: ThreadPoolExecutor) -> int:
    """Claims and resubmits stalled documents; returns how many were queued."""
    from src.database import async_session_local

    slots = ingest_queue.free_slots()
    if slots <= 0:
        return 0

    cutoff = datetime.datetime.now(datetime.UTC) - datetime.timedelta(
        seconds=config.STALE_AFTER_SECONDS,
    )
    reserved = ingest_queue.reserved_ids()
    requeued = 0

    async with async_session_local() as session:
        repo = ResearchDocumentRepository(session)
        # Ask for enough rows that documents already in flight here can be
        # skipped without eating into the free slots.
        candidates = await repo.find_stalled(cutoff, slots + len(reserved))

        for document in candidates:
            if requeued >= slots:
                break
            if document.id is None or document.id in reserved:
                continue
            if document.ingest_attempts >= config.MAX_INGEST_ATTEMPTS:
                await _give_up(repo, document)
                continue
            if not ingest_queue.try_reserve(document.id):
                continue

            run_id = str(uuid.uuid4())
            try:
                claimed = await repo.claim_stalled(document.id, run_id, cutoff)
            except Exception:
                ingest_queue.release(document.id)
                raise
            if not claimed:
                # Another instance got there first.
                ingest_queue.release(document.id)
                continue

            try:
                executor.submit(run_ingest, document_id=document.id)
            except Exception:
                ingest_queue.release(document.id)
                raise

            requeued += 1
            logger.info(
                "Re-queued stalled research document %s (%s) as run %s.",
                document.id,
                document.filename,
                run_id,
            )

    return requeued


async def _give_up(
    repo: ResearchDocumentRepository,
    document,
) -> None:
    """Marks a document FAILED after too many restarts.

    Leaving it in PROCESSING would keep it in the sweep forever; FAILED puts
    it in front of a human, who can still hit reprocess (which resets the
    attempt counter) once the cause — usually a file large enough to OOM the
    instance — has been dealt with.
    """
    logger.error(
        "Research document %s (%s) stalled %s times without completing;"
        " marking it failed.",
        document.id,
        document.filename,
        document.ingest_attempts,
    )
    await repo.update(
        document.id,
        {
            "status": ResearchDocStatus.FAILED.value,
            "error_message": (
                f"Ingest stopped after {document.ingest_attempts} attempts:"
                " the worker died before finishing every time. Large files"
                " can exhaust the instance's memory. Retry to try again."
            ),
        },
    )


async def run_sweeper_loop(executor: ThreadPoolExecutor) -> None:
    """Sweeps for stalled ingests forever; cancelled at app shutdown."""
    await asyncio.sleep(config.SWEEP_INITIAL_DELAY_SECONDS)
    while True:
        try:
            requeued = await sweep_once(executor)
            if requeued:
                logger.info(
                    "Stalled-ingest sweep re-queued %s document(s).",
                    requeued,
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.error("Stalled-ingest sweep failed.", exc_info=True)
        await asyncio.sleep(config.SWEEP_INTERVAL_SECONDS)
