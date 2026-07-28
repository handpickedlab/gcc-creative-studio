"""add sortable period keys to research claims and documents

Claim periods are stored exactly as the slide phrased them — 2,749 distinct
spellings across the corpus ("Q2 2025", "P10 2024", "2025 P1", "OCT 2025",
"January-February 2025", "past 12 months"). Nothing could be ordered, so
"the most recent NPS" returned 2023 figures. ``period_key`` holds the
normalized ``YYYY-MM`` form alongside the original text.

``research_documents.vintage_key`` is the document's own edition date, read
from its filename. Until now the only per-document date was ``created_at``,
the upload timestamp, and ranking weighted recency on it — so a 2023 figure
outranked a 2026 one purely because its file was dragged in later.

Additive: two nullable columns and one index, no rewrite and no backfill in
the migration itself (a separate pass fills them, so a slow parse can't hold
up startup).

Revision ID: b6c7d8e9f0a1
Revises: a5b6c7d8e9f0
Create Date: 2026-07-28
"""

from typing import Union

import sqlalchemy as sa

from alembic import op

revision: str = "b6c7d8e9f0a1"
down_revision: Union[str, None] = "a5b6c7d8e9f0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "research_claims",
        sa.Column("period_key", sa.String(), nullable=True),
    )
    op.add_column(
        "research_documents",
        sa.Column("vintage_key", sa.String(), nullable=True),
    )
    # Ranking reads period_key for every candidate and the agent filters on
    # it, so it earns an index.
    op.create_index(
        "ix_research_claims_period_key",
        "research_claims",
        ["period_key"],
    )


def downgrade() -> None:
    op.drop_index("ix_research_claims_period_key", table_name="research_claims")
    op.drop_column("research_documents", "vintage_key")
    op.drop_column("research_claims", "period_key")
