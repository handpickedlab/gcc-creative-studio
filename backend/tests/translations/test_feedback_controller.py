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
"""Tests for the authenticated content-manager feedback controller."""

from unittest.mock import AsyncMock

import pytest
from fastapi import status

from main import app
from src.translations.dto.feedback_dto import (
    BriefingFeedbackDto,
    MarketOverviewDto,
    ShareLinkResponseDto,
)
from src.translations.feedback_service import FeedbackService
from src.translations.schema.feedback_model import FeedbackTicketModel


@pytest.fixture(name="mock_feedback_service")
def fixture_mock_feedback_service():
    return AsyncMock()


@pytest.fixture(name="override_feedback_service", autouse=True)
def fixture_override(mock_feedback_service):
    app.dependency_overrides[FeedbackService] = lambda: mock_feedback_service
    yield
    app.dependency_overrides.pop(FeedbackService, None)


def _ticket(**kw):
    base = dict(
        id=1,
        briefing_id=10,
        market="NL",
        segment_index=0,
        author_name="Regular User",
        author_role="content_manager",
        body="shorter please",
        status="open",
    )
    base.update(kw)
    return FeedbackTicketModel(**base)


def test_get_feedback_returns_overview(api_client, mock_feedback_service):
    mock_feedback_service.get_feedback_overview.return_value = (
        BriefingFeedbackDto(
            markets=[MarketOverviewDto(market="NL", review_state="in_review")],
            tickets=[_ticket()],
        )
    )

    resp = api_client.get("/api/briefings/10/feedback")

    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["markets"][0]["market"] == "NL"
    assert data["markets"][0]["reviewState"] == "in_review"
    assert len(data["tickets"]) == 1


def test_create_ticket_uses_current_user_as_author(
    api_client, mock_feedback_service
):
    mock_feedback_service.create_ticket.return_value = _ticket()

    resp = api_client.post(
        "/api/briefings/10/markets/NL/tickets",
        json={"segmentIndex": 0, "body": "shorter please"},
    )

    assert resp.status_code == status.HTTP_201_CREATED
    # Author + role are set server-side, not from the request body.
    args = mock_feedback_service.create_ticket.call_args.args
    assert args[0] == 10 and args[1] == "NL" and args[2] == 0
    assert args[3] == "Regular User"  # current_user.name
    assert args[4] == "content_manager"


def test_update_ticket_status(api_client, mock_feedback_service):
    mock_feedback_service.update_ticket_status.return_value = _ticket(
        status="resolved"
    )

    resp = api_client.patch(
        "/api/briefings/tickets/1",
        json={"status": "resolved", "resolutionNote": "aangepast"},
    )

    assert resp.status_code == status.HTTP_200_OK
    assert resp.json()["status"] == "resolved"
    args = mock_feedback_service.update_ticket_status.call_args.args
    assert args[0] == 1 and args[1] == "resolved"


def test_create_share_link(api_client, mock_feedback_service):
    import datetime

    mock_feedback_service.request_feedback.return_value = ShareLinkResponseDto(
        token="raw-token-xyz",
        expires_at=datetime.datetime.now(datetime.UTC),
    )

    resp = api_client.post("/api/briefings/10/markets/NL/share-link")

    assert resp.status_code == status.HTTP_201_CREATED
    assert resp.json()["token"] == "raw-token-xyz"


def test_revoke_share_link(api_client, mock_feedback_service):
    mock_feedback_service.revoke_link.return_value = None

    resp = api_client.delete("/api/briefings/10/markets/NL/share-link")

    assert resp.status_code == status.HTTP_204_NO_CONTENT
    mock_feedback_service.revoke_link.assert_awaited_once_with(10, "NL")
