"""add research_documents.ingest_attempts

Counts how often the stalled-ingest sweeper has re-queued a document. Ingest
runs in-process, so a Cloud Run scale-down or an OOM kill (both happened
during the 23 July 2026 bulk upload) leaves documents in PROCESSING with no
worker; the sweeper retries those. Without a counter a file that reliably
exhausts the instance's memory would be retried forever, killing the
instance -- and paying Gemini -- on every round.

Additive: one nullable-with-default integer column, backfilled to 0 by the
server default, so the ALTER takes no table rewrite and old revisions keep
working against the same database.

Revision ID: a5b6c7d8e9f0
Revises: d4e5f6a7b8c9
Create Date: 2026-07-27
"""

from typing import Union

import sqlalchemy as sa

from alembic import op

revision: str = "a5b6c7d8e9f0"
down_revision: Union[str, None] = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "research_documents",
        sa.Column(
            "ingest_attempts",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("research_documents", "ingest_attempts")
