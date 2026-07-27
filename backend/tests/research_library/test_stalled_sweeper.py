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

"""Tests for the stalled-ingest sweeper and the bounded ingest queue."""

import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.research_library import config
from src.research_library.ingest import ingest_queue, stalled_sweeper
from src.research_library.schema.research_document_model import (
    ResearchDocStatus,
    ResearchDocumentModel,
)


def _document(
    document_id: int, ingest_attempts: int = 0
) -> ResearchDocumentModel:
    return ResearchDocumentModel(
        id=document_id,
        filename=f"deck-{document_id}.pptx",
        mime_type="application/vnd.ms-powerpoint",
        sha256=f"hash-{document_id}",
        gcs_uri=f"gs://test-bucket/research-library/global/u{document_id}/d.pptx",
        status=ResearchDocStatus.PROCESSING,
        ingest_run_id="dead-run",
        ingest_attempts=ingest_attempts,
    )


def _patched_repo(repo: AsyncMock):
    """Patches the session factory and the repository the sweeper builds."""
    session_cm = MagicMock()
    session_cm.__aenter__ = AsyncMock(return_value=MagicMock())
    session_cm.__aexit__ = AsyncMock(return_value=False)
    return (
        patch(
            "src.research_library.ingest.stalled_sweeper"
            ".ResearchDocumentRepository",
            MagicMock(return_value=repo),
        ),
        patch(
            "src.database.async_session_local",
            MagicMock(return_value=session_cm),
        ),
    )


class TestSweepOnce:
    """Tests for stalled_sweeper.sweep_once."""

    @pytest.mark.anyio
    async def test_requeues_stalled_documents_under_a_new_run(self):
        repo = AsyncMock()
        repo.find_stalled.return_value = [_document(11), _document(12)]
        repo.claim_stalled.return_value = True
        executor = MagicMock()
        patch_repo, patch_session = _patched_repo(repo)

        with patch_repo, patch_session:
            requeued = await stalled_sweeper.sweep_once(executor)

        assert requeued == 2
        assert executor.submit.call_count == 2
        submitted = {
            call.kwargs["document_id"]
            for call in executor.submit.call_args_list
        }
        assert submitted == {11, 12}
        # Each document is claimed under its own fresh ingest run id, and
        # never under the run the dead worker was using.
        run_ids = {call.args[1] for call in repo.claim_stalled.call_args_list}
        assert len(run_ids) == 2
        assert "dead-run" not in run_ids
        assert ingest_queue.reserved_ids() == {11, 12}

    @pytest.mark.anyio
    async def test_a_reserved_document_is_a_running_document(self):
        """The queue holds no waiting documents by default.

        A document waiting in the executor queue beats no heartbeat, so the
        sweeper would read it as abandoned and let a second process claim and
        extract it too — paying Gemini twice for one document.
        """
        assert config.MAX_QUEUED == config.INGEST_WORKERS

    @pytest.mark.anyio
    async def test_skips_documents_another_instance_claimed_first(self):
        repo = AsyncMock()
        repo.find_stalled.return_value = [_document(11)]
        repo.claim_stalled.return_value = False
        executor = MagicMock()
        patch_repo, patch_session = _patched_repo(repo)

        with patch_repo, patch_session:
            requeued = await stalled_sweeper.sweep_once(executor)

        assert requeued == 0
        executor.submit.assert_not_called()
        # The slot is handed back, so the next sweep can try other documents.
        assert ingest_queue.reserved_ids() == set()

    @pytest.mark.anyio
    async def test_never_exceeds_the_free_queue_slots(self):
        repo = AsyncMock()
        repo.find_stalled.return_value = [
            _document(i) for i in range(1, config.MAX_QUEUED + 5)
        ]
        repo.claim_stalled.return_value = True
        executor = MagicMock()
        patch_repo, patch_session = _patched_repo(repo)

        with patch_repo, patch_session:
            requeued = await stalled_sweeper.sweep_once(executor)

        assert requeued == config.MAX_QUEUED
        assert executor.submit.call_count == config.MAX_QUEUED

    @pytest.mark.anyio
    async def test_does_nothing_when_the_queue_is_full(self):
        for document_id in range(1, config.MAX_QUEUED + 1):
            assert ingest_queue.try_reserve(document_id)
        repo = AsyncMock()
        executor = MagicMock()
        patch_repo, patch_session = _patched_repo(repo)

        with patch_repo, patch_session:
            requeued = await stalled_sweeper.sweep_once(executor)

        assert requeued == 0
        repo.find_stalled.assert_not_called()
        executor.submit.assert_not_called()

    @pytest.mark.anyio
    async def test_skips_documents_this_process_is_already_running(self):
        assert ingest_queue.try_reserve(11)
        repo = AsyncMock()
        repo.find_stalled.return_value = [_document(11), _document(12)]
        repo.claim_stalled.return_value = True
        executor = MagicMock()
        patch_repo, patch_session = _patched_repo(repo)

        with patch_repo, patch_session:
            requeued = await stalled_sweeper.sweep_once(executor)

        assert requeued == 1
        executor.submit.assert_called_once_with(
            stalled_sweeper.run_ingest, document_id=12
        )
        repo.claim_stalled.assert_awaited_once()
        assert repo.claim_stalled.call_args.args[0] == 12

    @pytest.mark.anyio
    async def test_fails_a_document_that_has_used_up_its_attempts(self):
        """A file that OOM-kills its instance must not be retried forever."""
        repo = AsyncMock()
        repo.find_stalled.return_value = [
            _document(11, ingest_attempts=config.MAX_INGEST_ATTEMPTS),
        ]
        executor = MagicMock()
        patch_repo, patch_session = _patched_repo(repo)

        with patch_repo, patch_session:
            requeued = await stalled_sweeper.sweep_once(executor)

        assert requeued == 0
        executor.submit.assert_not_called()
        repo.claim_stalled.assert_not_called()
        document_id, updates = repo.update.call_args.args
        assert document_id == 11
        assert updates["status"] == ResearchDocStatus.FAILED.value
        assert "attempts" in updates["error_message"]
        # Failing it takes no queue slot, so the sweep moves on cleanly.
        assert ingest_queue.reserved_ids() == set()

    @pytest.mark.anyio
    async def test_still_retries_a_document_below_the_attempt_cap(self):
        repo = AsyncMock()
        repo.find_stalled.return_value = [
            _document(11, ingest_attempts=config.MAX_INGEST_ATTEMPTS - 1),
        ]
        repo.claim_stalled.return_value = True
        executor = MagicMock()
        patch_repo, patch_session = _patched_repo(repo)

        with patch_repo, patch_session:
            requeued = await stalled_sweeper.sweep_once(executor)

        assert requeued == 1
        repo.update.assert_not_called()
        executor.submit.assert_called_once()

    @pytest.mark.anyio
    async def test_cutoff_is_the_configured_staleness_window(self):
        repo = AsyncMock()
        repo.find_stalled.return_value = []
        executor = MagicMock()
        patch_repo, patch_session = _patched_repo(repo)

        with patch_repo, patch_session:
            await stalled_sweeper.sweep_once(executor)

        cutoff = repo.find_stalled.call_args.args[0]
        age = datetime.datetime.now(datetime.UTC) - cutoff
        assert (
            config.STALE_AFTER_SECONDS
            <= age.total_seconds()
            < config.STALE_AFTER_SECONDS + 60
        )


class TestIngestQueue:
    """Tests for the bounded, process-local ingest queue."""

    def test_refuses_a_document_it_already_holds(self):
        assert ingest_queue.try_reserve(5)
        assert not ingest_queue.try_reserve(5)

    def test_refuses_once_full_and_accepts_again_after_release(self):
        for document_id in range(1, config.MAX_QUEUED + 1):
            assert ingest_queue.try_reserve(document_id)
        assert ingest_queue.free_slots() == 0
        assert not ingest_queue.try_reserve(999)

        ingest_queue.release(1)

        assert ingest_queue.free_slots() == 1
        assert ingest_queue.try_reserve(999)

    def test_release_of_an_unknown_document_is_harmless(self):
        ingest_queue.release(424242)
        assert ingest_queue.free_slots() == config.MAX_QUEUED
