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

"""glossary_terms per language

Adds a `language` column so each target language has its own dictionary,
and replaces the unique(source) constraint with unique(language, source).

Revision ID: c2d3e4f5a6b7
Revises: b1c2d3e4f5a6
Create Date: 2026-06-15 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c2d3e4f5a6b7"
down_revision: Union[str, None] = "b1c2d3e4f5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add language column. server_default backfills any pre-existing rows
    # (the feature was previously global); new rows always set it explicitly.
    op.add_column(
        "glossary_terms",
        sa.Column(
            "language",
            sa.String(),
            nullable=False,
            server_default="English",
        ),
    )
    op.drop_constraint(
        "uq_glossary_terms_source", "glossary_terms", type_="unique"
    )
    op.create_unique_constraint(
        "uq_glossary_terms_lang_source",
        "glossary_terms",
        ["language", "source"],
    )
    # Drop the temporary server_default so the application must supply it.
    op.alter_column("glossary_terms", "language", server_default=None)


def downgrade() -> None:
    op.drop_constraint(
        "uq_glossary_terms_lang_source", "glossary_terms", type_="unique"
    )
    op.create_unique_constraint(
        "uq_glossary_terms_source", "glossary_terms", ["source"]
    )
    op.drop_column("glossary_terms", "language")
