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
"""add document translation jobs + segments

Revision ID: f7a8b9c0d1e2
Revises: b6c7d8e9f0a1
Create Date: 2026-07-31
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f7a8b9c0d1e2"
down_revision: Union[str, None] = "b6c7d8e9f0a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "document_translation_jobs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("filename", sa.String(), nullable=False),
        sa.Column(
            "status",
            sa.String(),
            server_default=sa.text("'uploaded'"),
            nullable=False,
        ),
        sa.Column("target_market", sa.String(), nullable=True),
        sa.Column("model_id", sa.String(), nullable=True),
        sa.Column("source_gcs_uri", sa.String(), nullable=True),
        sa.Column("output_gcs_uri", sa.String(), nullable=True),
        sa.Column("stats", postgresql.JSONB(), nullable=True),
        sa.Column("progress", postgresql.JSONB(), nullable=True),
        sa.Column("qa_findings", postgresql.JSONB(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(), nullable=True),
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
    )
    op.create_table(
        "document_translation_segments",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("job_id", sa.String(), nullable=False),
        sa.Column("seg_index", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("section_path", postgresql.JSONB(), nullable=True),
        sa.Column("source_text", sa.Text(), nullable=False),
        sa.Column("translation", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.String(),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["document_translation_jobs.id"],
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_document_translation_segments_job",
        "document_translation_segments",
        ["job_id", "seg_index"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_document_translation_segments_job",
        table_name="document_translation_segments",
    )
    op.drop_table("document_translation_segments")
    op.drop_table("document_translation_jobs")
