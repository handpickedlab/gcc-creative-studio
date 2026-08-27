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

"""Can a poll watch the agent work, or only read the result afterwards?

The UI's live view is a poll of ``GET /ask/{id}``, so "watch it work" is real
only if the background worker writes each step to the run row as it happens —
including the marker that says the model itself is mid-turn, which is where a
deep retrieval spends most of its time.
"""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.data_query import data_query_service as svc
from src.data_query.repository.data_query_run_repository import (
    DataQueryRunRepository,
)
from src.data_query.schema.data_query_run_model import DataQueryRun


def _slow_agent(*_args, **_kwargs):
    """One tool call around a long model turn — the shape of a real run."""
    yield {"t": "step", "n": 1}
    time.sleep(0.6)
    yield {"t": "tool", "name": "run_sql", "input": {"sql": "SELECT 1"}}
    yield {"t": "tool_result", "name": "run_sql", "summary": "1 row", "ms": 12}
    yield {"t": "step", "n": 2}
    time.sleep(0.6)
    yield {"t": "text", "v": "42"}
    yield {"t": "done"}


async def _watch(sm, run_id, seconds=6.0):
    """Poll like the client does; return every distinct state we could see."""
    seen: list[tuple[str, list]] = []
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        async with sm() as db:
            row = await DataQueryRunRepository(db).get_by_id(run_id)
        if row and (not seen or seen[-1] != (row.status, row.steps)):
            seen.append((row.status, row.steps))
        if row and row.status != "processing":
            break
        await asyncio.sleep(0.05)
    return seen


@pytest.mark.anyio
async def test_a_poll_can_watch_the_agent_work(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/runs.db")
    async with engine.begin() as conn:
        await conn.run_sync(DataQueryRun.__table__.create)
    sm = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(svc, "async_session_local", sm)
    monkeypatch.setattr(svc.agent, "stream_answer", _slow_agent)
    # Flush faster than production's 1.5s so the test stays quick; the
    # behaviour under test is that a flush happens at all, mid-run.
    monkeypatch.setattr(svc, "_PROGRESS_FLUSH_S", 0.15)

    try:
        async with sm() as db:
            service = svc.DataQueryService(
                gemini_service=MagicMock(),
                sheet_repo=MagicMock(),
                run_repo=DataQueryRunRepository(db),
                gcs_service=MagicMock(),
            )
            monkeypatch.setattr(service, "ensure_loaded", AsyncMock())
            run = await service.start_ask("how many?")

        seen = await _watch(sm, run.id)
    finally:
        await engine.dispose()

    assert seen, "the run row was never readable"
    assert seen[-1][0] == "completed"

    mid = [steps for status, steps in seen if status == "processing"]
    # The model's own turn is announced, so the wait is never a blank spinner.
    assert any(
        steps and steps[-1].get("kind") == "model" for steps in mid
    ), "no 'the model is thinking' marker was ever visible"
    # And the tool call shows up before the answer does.
    assert any(
        any(s.get("kind") == "tool" for s in steps) for steps in mid
    ), "the tool call only became visible after the run finished"

    final = seen[-1][1]
    assert [s["kind"] for s in final] == ["tool", "text"], final
    assert final[0]["ms"] == 12
