"""add do_not_translate flag to glossary_terms

Marks a glossary entry as a do-not-translate brand/product/collection name
that must be reproduced verbatim in the target. Additive only.

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-07-09
"""

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, None] = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "glossary_terms",
        sa.Column(
            "do_not_translate",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("glossary_terms", "do_not_translate")
