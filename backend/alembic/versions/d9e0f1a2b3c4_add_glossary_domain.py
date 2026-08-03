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
"""add domain to glossary terms

Existing rows are all campaign terminology, so they become 'marketing'.
The unique key widens to (language, source, domain) so a term can carry a
different fixed translation in a financial statement than in campaign copy.

Revision ID: d9e0f1a2b3c4
Revises: c8d9e0f1a2b3
Create Date: 2026-07-31
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d9e0f1a2b3c4"
down_revision: Union[str, None] = "c8d9e0f1a2b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_OLD_CONSTRAINT = "uq_glossary_terms_lang_source"
_NEW_CONSTRAINT = "uq_glossary_terms_lang_source_domain"


def upgrade() -> None:
    op.add_column(
        "glossary_terms",
        sa.Column(
            "domain",
            sa.String(),
            server_default=sa.text("'marketing'"),
            nullable=False,
        ),
    )
    op.drop_constraint(_OLD_CONSTRAINT, "glossary_terms", type_="unique")
    op.create_unique_constraint(
        _NEW_CONSTRAINT, "glossary_terms", ["language", "source", "domain"]
    )


def downgrade() -> None:
    # Financial rows would collide with their marketing namesakes on the
    # narrower key, so drop them before restoring it.
    op.execute("DELETE FROM glossary_terms WHERE domain <> 'marketing'")
    op.drop_constraint(_NEW_CONSTRAINT, "glossary_terms", type_="unique")
    op.create_unique_constraint(
        _OLD_CONSTRAINT, "glossary_terms", ["language", "source"]
    )
    op.drop_column("glossary_terms", "domain")
