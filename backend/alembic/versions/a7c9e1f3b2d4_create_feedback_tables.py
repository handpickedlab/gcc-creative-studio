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

"""create feedback request + ticket tables

Revision ID: a7c9e1f3b2d4
Revises: e4f5a6b7c8d9
Create Date: 2026-06-19 09:00:00.000000

Additive only (two new tables) so older application revisions remain
forward-compatible against the shared database.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a7c9e1f3b2d4"
down_revision: Union[str, None] = "e4f5a6b7c8d9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "briefing_feedback_requests",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("briefing_id", sa.Integer(), nullable=False),
        sa.Column("market", sa.String(), nullable=False),
        sa.Column(
            "review_state",
            sa.String(),
            nullable=False,
            server_default="draft",
        ),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("token_hash", sa.String(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["briefing_id"], ["briefings.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint(
            "briefing_id", "market", name="uq_feedback_request_market"
        ),
        sa.UniqueConstraint(
            "token_hash", name="uq_feedback_request_token_hash"
        ),
    )
    op.create_table(
        "briefing_feedback_tickets",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("briefing_id", sa.Integer(), nullable=False),
        sa.Column("market", sa.String(), nullable=False),
        sa.Column("segment_index", sa.Integer(), nullable=False),
        sa.Column("field_snapshot", sa.String(), nullable=True),
        sa.Column("source_snapshot", sa.Text(), nullable=True),
        sa.Column("content_hash", sa.String(), nullable=True),
        sa.Column("author_name", sa.String(), nullable=False),
        sa.Column("author_role", sa.String(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="open"),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "status_changed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["briefing_id"], ["briefings.id"], ondelete="CASCADE"
        ),
        sa.CheckConstraint(
            "segment_index >= 0", name="ck_feedback_ticket_segment_index"
        ),
        sa.CheckConstraint(
            "length(btrim(body)) > 0", name="ck_feedback_ticket_body_nonempty"
        ),
    )
    op.create_index(
        "ix_feedback_ticket_briefing_market",
        "briefing_feedback_tickets",
        ["briefing_id", "market"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_feedback_ticket_briefing_market",
        table_name="briefing_feedback_tickets",
    )
    op.drop_table("briefing_feedback_tickets")
    op.drop_table("briefing_feedback_requests")
