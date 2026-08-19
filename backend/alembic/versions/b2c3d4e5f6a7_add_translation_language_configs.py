"""add translation_language_configs table

Per-language localization profiles (formality, casing preservation, free-text
guidance). Additive only.

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f7
Create Date: 2026-07-09
"""

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "b2c3d4e5f6a7"
# Chained after the data-query/research-library migrations (develop) so the
# integrated branch has a single linear alembic head.
down_revision: Union[str, None] = "a1b2c3d4e5f7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "translation_language_configs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("language", sa.String(), nullable=False),
        sa.Column(
            "formality",
            sa.String(),
            server_default="default",
            nullable=False,
        ),
        sa.Column(
            "preserve_casing",
            sa.Boolean(),
            server_default=sa.true(),
            nullable=False,
        ),
        sa.Column("guidance", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "language", name="uq_translation_language_configs_language"
        ),
    )


def downgrade() -> None:
    op.drop_table("translation_language_configs")
