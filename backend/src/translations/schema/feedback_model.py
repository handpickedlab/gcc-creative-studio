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
"""Persistence for the translator feedback loop.

Two tables, both keyed on the briefing + target market (never on the
``briefing_translations`` row, which is delete+inserted on every save):

* ``briefing_feedback_requests`` — one row per (briefing, market) carrying the
  durable per-market review state AND the current share-link credential. The
  review state survives link expiry (the link is only an access credential).
* ``briefing_feedback_tickets`` — standalone per-item feedback notes.
"""

import datetime
from typing import Literal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column
from src.common.base_repository import BaseDocument
from src.database import Base

# --- Constrained value vocabularies -------------------------------------

ReviewState = Literal["draft", "in_review", "done"]
TicketStatus = Literal["open", "in_progress", "resolved"]
AuthorRole = Literal["content_manager", "translator"]


# --- ORM models ----------------------------------------------------------


class BriefingFeedbackRequest(Base):
    """Per-market review state + the current share-link credential.

    One row per (briefing_id, market). ``review_state`` is durable and is NOT
    derived from the link, so a market stays ``in_review`` even after its link
    expires. ``token_hash`` holds the sha256 of the *current* active token (or
    NULL when none/revoked); Postgres allows multiple NULLs under the unique
    constraint, so revoked/absent links don't collide.
    """

    __tablename__ = "briefing_feedback_requests"
    __table_args__ = (
        UniqueConstraint(
            "briefing_id", "market", name="uq_feedback_request_market"
        ),
        UniqueConstraint("token_hash", name="uq_feedback_request_token_hash"),
    )

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    briefing_id: Mapped[int] = mapped_column(
        ForeignKey("briefings.id", ondelete="CASCADE"), nullable=False
    )
    market: Mapped[str] = mapped_column(String, nullable=False)
    review_state: Mapped[str] = mapped_column(
        String, nullable=False, server_default="draft"
    )
    requested_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    token_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    expires_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        insert_default=func.now(),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        insert_default=func.now(),
        onupdate=func.now(),
        server_default=func.now(),
    )


class BriefingFeedbackTicket(Base):
    """A standalone feedback note on one item (segment) of one market.

    Bound by ``segment_index`` (positional, matching how segments align across
    briefing/translation/export). ``content_hash`` lets the read path flag a
    ticket as stale (``itemChanged``) when the underlying segment has since been
    re-translated. ``resolution_note`` is a content-manager-only field and is
    never exposed on the public translator view.
    """

    __tablename__ = "briefing_feedback_tickets"
    __table_args__ = (
        CheckConstraint(
            "segment_index >= 0", name="ck_feedback_ticket_segment_index"
        ),
        CheckConstraint(
            "length(btrim(body)) > 0", name="ck_feedback_ticket_body_nonempty"
        ),
    )

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    briefing_id: Mapped[int] = mapped_column(
        ForeignKey("briefings.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    market: Mapped[str] = mapped_column(String, nullable=False, index=True)
    segment_index: Mapped[int] = mapped_column(Integer, nullable=False)
    field_snapshot: Mapped[str | None] = mapped_column(String, nullable=True)
    source_snapshot: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    author_name: Mapped[str] = mapped_column(String, nullable=False)
    author_role: Mapped[str] = mapped_column(String, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String, nullable=False, server_default="open"
    )
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        insert_default=func.now(),
        server_default=func.now(),
    )
    status_changed_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        insert_default=func.now(),
        server_default=func.now(),
    )


# --- Pydantic response models -------------------------------------------


class FeedbackTicketModel(BaseDocument):
    """A ticket as returned to the content manager (includes resolution_note)."""

    briefing_id: int
    market: str
    segment_index: int
    field_snapshot: str | None = None
    source_snapshot: str | None = None
    author_name: str
    author_role: AuthorRole
    body: str
    status: TicketStatus = "open"
    resolution_note: str | None = None
    status_changed_at: datetime.datetime | None = None


class FeedbackRequestModel(BaseDocument):
    """Per-market review state for the content manager.

    Deliberately omits ``token_hash`` — the raw token is returned only once at
    creation and the hash is never exposed.
    """

    briefing_id: int
    market: str
    review_state: ReviewState = "draft"
    requested_at: datetime.datetime | None = None
    expires_at: datetime.datetime | None = None
    revoked_at: datetime.datetime | None = None
