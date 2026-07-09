"""add data_query_sheets catalog table

Durable catalog for uploaded data-query spreadsheets. Additive only: the
DuckDB warehouse stays as the query engine, this table is the persistent
record of which sheets exist and where their raw files live in GCS, so any
Cloud Run instance can rehydrate its local DuckDB.

Revision ID: a1b2c3d4e5f7
Revises: f4f73abf51f5
Create Date: 2026-07-09
"""

from typing import Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "a1b2c3d4e5f7"
down_revision: Union[str, None] = "f4f73abf51f5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "data_query_sheets",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("table_name", sa.String(), nullable=False),
        sa.Column("source_file", sa.String(), nullable=False),
        sa.Column("sheet", sa.String(), nullable=True),
        sa.Column("n_rows", sa.Integer(), nullable=True),
        sa.Column("n_cols", sa.Integer(), nullable=True),
        sa.Column("columns", postgresql.JSONB(), nullable=True),
        sa.Column("gcs_uri", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_data_query_sheets_table_active",
        "data_query_sheets",
        ["table_name"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_data_query_sheets_table_active", table_name="data_query_sheets"
    )
    op.drop_table("data_query_sheets")
