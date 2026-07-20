"""add data_query_runs table

Durable record of background data-query ``/ask`` runs. Additive only — a brand
new table, so its ``CREATE TABLE`` holds no lock on any table with live
readers (unlike an ``ALTER`` on an existing table). ``/ask`` now runs the agent
in the background and writes progress here so the client can poll instead of
holding a long streaming response open (which the hosting rewrite times out at
~60s).

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-07-20
"""

from typing import Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, None] = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "data_query_runs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column(
            "status",
            sa.String(),
            server_default=sa.text("'processing'"),
            nullable=False,
        ),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("steps", postgresql.JSONB(), nullable=True),
        sa.Column("answer_sources", postgresql.JSONB(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("data_query_runs")
