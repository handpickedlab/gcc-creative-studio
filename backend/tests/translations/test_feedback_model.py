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
"""Tests for the feedback ORM + response models."""

import datetime
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from src.translations.schema.feedback_model import (
    BriefingFeedbackRequest,
    BriefingFeedbackTicket,
    FeedbackRequestModel,
    FeedbackTicketModel,
)


def test_ticket_model_serializes_camel_case():
    """Response fields serialize as camelCase for the frontend."""
    model = FeedbackTicketModel(
        id=1,
        briefing_id=10,
        market="NL",
        segment_index=2,
        field_snapshot="Header",
        source_snapshot="Shop now",
        author_name="Sanne",
        author_role="translator",
        body="Deze CTA is te lang.",
        status="open",
    )
    dumped = model.model_dump(by_alias=True)

    assert dumped["segmentIndex"] == 2
    assert dumped["authorName"] == "Sanne"
    assert dumped["authorRole"] == "translator"
    assert dumped["briefingId"] == 10


def test_ticket_model_rejects_unknown_status():
    """Status is constrained to the known vocabulary."""
    with pytest.raises(ValidationError):
        FeedbackTicketModel(
            id=1,
            briefing_id=10,
            market="NL",
            segment_index=0,
            author_name="Sanne",
            author_role="translator",
            body="x",
            status="totally-not-a-status",
        )


def test_ticket_model_rejects_unknown_author_role():
    with pytest.raises(ValidationError):
        FeedbackTicketModel(
            id=1,
            briefing_id=10,
            market="NL",
            segment_index=0,
            author_name="Sanne",
            author_role="ceo",
            body="x",
        )


def test_request_model_never_exposes_token_hash():
    """Even when validated from an object that carries token_hash, the
    response model must not surface it."""
    now = datetime.datetime.now(datetime.UTC)
    row = SimpleNamespace(
        id=1,
        briefing_id=10,
        market="NL",
        review_state="in_review",
        requested_at=now,
        token_hash="deadbeef" * 8,
        expires_at=now,
        revoked_at=None,
        created_at=now,
        updated_at=now,
    )
    model = FeedbackRequestModel.model_validate(row)
    dumped = model.model_dump(by_alias=True)

    assert model.review_state == "in_review"
    assert "tokenHash" not in dumped
    assert "token_hash" not in dumped
    assert not any("token" in key.lower() for key in dumped)


def test_orm_tables_and_columns_defined():
    """ORM tables exist with the security/integrity-relevant columns."""
    assert BriefingFeedbackRequest.__tablename__ == "briefing_feedback_requests"
    assert BriefingFeedbackTicket.__tablename__ == "briefing_feedback_tickets"

    req_cols = BriefingFeedbackRequest.__table__.columns
    assert "token_hash" in req_cols
    assert "review_state" in req_cols
    # token_hash must be uniquely constrained (one active link per token).
    unique_cols = {
        tuple(c.name for c in con.columns)
        for con in BriefingFeedbackRequest.__table__.constraints
        if con.__class__.__name__ == "UniqueConstraint"
    }
    assert ("token_hash",) in unique_cols
    assert ("briefing_id", "market") in unique_cols

    ticket_cols = BriefingFeedbackTicket.__table__.columns
    for col in (
        "segment_index",
        "author_role",
        "body",
        "status",
        "content_hash",
        "resolution_note",
    ):
        assert col in ticket_cols
