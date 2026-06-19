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
"""Tests for the PUBLIC token-gated feedback controller.

These use a client that does NOT override get_current_user — proving the routes
work with no authentication — and assert the fail-closed + IDOR guarantees.
"""

from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException, status
from fastapi.testclient import TestClient

from main import app
from src.translations.dto.feedback_dto import (
    PublicFeedbackItemDto,
    PublicFeedbackViewDto,
)
from src.translations.feedback_service import FeedbackService
from src.translations.schema.feedback_model import FeedbackTicketModel


@pytest.fixture(name="mock_feedback_service")
def fixture_mock_feedback_service():
    return AsyncMock()


@pytest.fixture(name="public_client")
def fixture_public_client(mock_feedback_service):
    """A client with NO authenticated user — only the service is mocked."""
    app.dependency_overrides[FeedbackService] = lambda: mock_feedback_service
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.pop(FeedbackService, None)


def _view():
    return PublicFeedbackViewDto(
        briefing_name="Q3 Campaign",
        market="NL",
        market_label="Dutch (Netherlands)",
        items=[
            PublicFeedbackItemDto(
                index=0,
                field="Header",
                label="Header",
                source="Shop",
                translation="Koop",
            )
        ],
        tickets=[],
    )


def test_public_view_works_without_auth(public_client, mock_feedback_service):
    mock_feedback_service.validate_share_token.return_value = (10, "NL")
    mock_feedback_service.get_public_view.return_value = _view()

    # No Authorization header at all.
    resp = public_client.get("/api/public/feedback/some-token")

    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["briefingName"] == "Q3 Campaign"
    assert data["market"] == "NL"
    # PII / internal fields must not be present.
    assert "meta" not in data


def test_expired_token_is_410(public_client, mock_feedback_service):
    mock_feedback_service.validate_share_token.side_effect = HTTPException(
        status_code=status.HTTP_410_GONE, detail="expired"
    )

    resp = public_client.get("/api/public/feedback/expired-token")

    assert resp.status_code == status.HTTP_410_GONE
    mock_feedback_service.get_public_view.assert_not_called()


def test_unknown_token_is_404(public_client, mock_feedback_service):
    mock_feedback_service.validate_share_token.side_effect = HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, detail="unknown"
    )

    resp = public_client.get("/api/public/feedback/bogus")

    assert resp.status_code == status.HTTP_404_NOT_FOUND


def test_create_ticket_derives_market_from_token_only(
    public_client, mock_feedback_service
):
    """IDOR: market/briefing come from the token, never the body."""
    mock_feedback_service.validate_share_token.return_value = (10, "NL")
    mock_feedback_service.create_ticket.return_value = FeedbackTicketModel(
        id=5,
        briefing_id=10,
        market="NL",
        segment_index=0,
        author_name="Sanne",
        author_role="translator",
        body="te lang",
        status="open",
    )

    # Attacker tries to smuggle a different market/briefing in the body.
    resp = public_client.post(
        "/api/public/feedback/valid-token/tickets",
        json={
            "segmentIndex": 0,
            "authorName": "Sanne",
            "body": "te lang",
            "market": "FR",
            "briefingId": 999,
        },
    )

    assert resp.status_code == status.HTTP_201_CREATED
    args = mock_feedback_service.create_ticket.call_args.args
    # briefing_id=10, market="NL" come from the token context — body ignored.
    assert args[0] == 10 and args[1] == "NL"
    assert args[4] == "translator"
    body = resp.json()
    assert "resolutionNote" not in body  # public projection excludes it
