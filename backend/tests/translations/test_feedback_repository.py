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
"""Tests for FeedbackRepository (mocked AsyncSession)."""

import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.translations.repository.feedback_repository import FeedbackRepository
from src.translations.schema.feedback_model import (
    BriefingFeedbackRequest,
    BriefingFeedbackTicket,
)


def _ticket_row(**overrides):
    now = datetime.datetime.now(datetime.UTC)
    defaults = dict(
        id=1,
        briefing_id=10,
        market="NL",
        segment_index=0,
        author_name="Sanne",
        author_role="translator",
        body="te lang",
        status="open",
        created_at=now,
        status_changed_at=now,
    )
    defaults.update(overrides)
    return BriefingFeedbackTicket(**defaults)


@pytest.mark.anyio
async def test_get_request_returns_row():
    mock_db = AsyncMock()
    mock_result = MagicMock()
    row = BriefingFeedbackRequest(id=1, briefing_id=10, market="NL")
    mock_result.scalar_one_or_none.return_value = row
    mock_db.execute.return_value = mock_result

    repo = FeedbackRepository(db=mock_db)
    assert await repo.get_request(10, "NL") is row


@pytest.mark.anyio
async def test_upsert_request_creates_when_absent():
    mock_db = AsyncMock()
    mock_db.add = MagicMock()  # Session.add is synchronous
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None  # no existing row
    mock_db.execute.return_value = mock_result

    repo = FeedbackRepository(db=mock_db)
    row = await repo.upsert_request(
        10, "NL", {"review_state": "in_review", "token_hash": "abc"}
    )

    mock_db.add.assert_called_once()
    mock_db.commit.assert_awaited_once()
    assert row.review_state == "in_review"
    assert row.token_hash == "abc"
    assert row.briefing_id == 10 and row.market == "NL"


@pytest.mark.anyio
async def test_upsert_request_updates_existing():
    mock_db = AsyncMock()
    mock_result = MagicMock()
    existing = BriefingFeedbackRequest(
        id=1, briefing_id=10, market="NL", review_state="draft"
    )
    mock_result.scalar_one_or_none.return_value = existing
    mock_db.execute.return_value = mock_result

    repo = FeedbackRepository(db=mock_db)
    row = await repo.upsert_request(10, "NL", {"review_state": "done"})

    mock_db.add.assert_not_called()  # existing row, not a new insert
    assert row is existing
    assert row.review_state == "done"


@pytest.mark.anyio
async def test_create_ticket_returns_model():
    mock_db = AsyncMock()
    mock_db.add = MagicMock()  # Session.add is synchronous

    async def refresh(obj):
        obj.id = 7
        obj.created_at = datetime.datetime.now(datetime.UTC)
        obj.status_changed_at = obj.created_at

    mock_db.refresh.side_effect = refresh

    repo = FeedbackRepository(db=mock_db)
    model = await repo.create_ticket(
        {
            "briefing_id": 10,
            "market": "NL",
            "segment_index": 1,
            "author_name": "CM",
            "author_role": "content_manager",
            "body": "shorter please",
            "status": "open",
        }
    )

    mock_db.add.assert_called_once()
    mock_db.commit.assert_awaited_once()
    assert model.id == 7
    assert model.author_role == "content_manager"
    assert model.segment_index == 1


@pytest.mark.anyio
async def test_list_tickets_filters_by_market():
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [_ticket_row()]
    mock_db.execute.return_value = mock_result

    repo = FeedbackRepository(db=mock_db)
    tickets = await repo.list_tickets(10, "NL")

    assert len(tickets) == 1
    assert tickets[0].market == "NL"


@pytest.mark.anyio
async def test_update_ticket_returns_none_when_missing():
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_db.execute.return_value = mock_result

    repo = FeedbackRepository(db=mock_db)
    assert await repo.update_ticket(999, {"status": "resolved"}) is None
    mock_db.commit.assert_not_awaited()
