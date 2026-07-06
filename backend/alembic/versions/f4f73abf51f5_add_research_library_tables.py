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

"""add research library tables

Revision ID: f4f73abf51f5
Revises: e2f3a4b5c6d7
Create Date: 2026-07-06 10:00:00.000000

Additive only (four new tables, one new extension) so older application
revisions remain forward-compatible against the shared database. Enables
pgvector first since ``research_claims.embedding`` depends on it (verified
available on the target Cloud SQL Postgres 18 instance).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql


revision: str = "f4f73abf51f5"
down_revision: Union[str, None] = "e2f3a4b5c6d7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "research_documents",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("filename", sa.String(), nullable=False),
        sa.Column("mime_type", sa.String(), nullable=False),
        sa.Column("sha256", sa.String(), nullable=True),
        sa.Column("gcs_uri", sa.String(), nullable=False),
        sa.Column("doc_kind", sa.String(), nullable=True),
        sa.Column("language", sa.String(), nullable=True),
        sa.Column("period", sa.String(), nullable=True),
        sa.Column(
            "priority_tier",
            sa.String(),
            nullable=False,
            server_default="primary",
        ),
        sa.Column(
            "status",
            sa.String(),
            nullable=False,
            server_default="processing",
        ),
        sa.Column("error_message", sa.String(), nullable=True),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column(
            "failed_pages",
            postgresql.JSONB(),
            nullable=False,
            server_default="[]",
        ),
        sa.Column("ingest_run_id", sa.String(), nullable=True),
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
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Partial unique index: uniqueness only among non-soft-deleted rows, so
    # re-uploading the same content after its original document is deleted
    # is allowed, and NULL sha256 (the REJECTED duplicate-marker rows) never
    # collides with anything.
    op.create_index(
        "uq_research_documents_sha256_active",
        "research_documents",
        ["sha256"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_research_documents_status",
        "research_documents",
        ["status"],
    )

    op.create_table(
        "research_document_pages",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("page_no", sa.Integer(), nullable=False),
        sa.Column("image_gcs_uri", sa.String(), nullable=True),
        sa.Column("thumb_gcs_uri", sa.String(), nullable=True),
        sa.Column(
            "status",
            sa.String(),
            nullable=False,
            server_default="processing",
        ),
        sa.Column("error", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["research_documents.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "document_id",
            "page_no",
            name="uq_research_document_pages_document_page",
        ),
    )

    op.create_table(
        "research_claims",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("page_no", sa.Integer(), nullable=False),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("metric", sa.String(), nullable=True),
        sa.Column("value", sa.String(), nullable=True),
        sa.Column("unit", sa.String(), nullable=True),
        sa.Column("segment", sa.String(), nullable=True),
        sa.Column("geography", sa.String(), nullable=True),
        sa.Column("period", sa.String(), nullable=True),
        sa.Column("claim_type", sa.String(), nullable=True),
        sa.Column("source_citation", sa.String(), nullable=True),
        sa.Column("sample", sa.String(), nullable=True),
        sa.Column(
            "raw_tags",
            postgresql.JSONB(),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "canonical_tags",
            postgresql.JSONB(),
            nullable=False,
            server_default="[]",
        ),
        # gemini-embedding-001, output_dimensionality=768 (MRL truncation,
        # re-normalized before storage). See src.research_library.schema
        # .research_document_model.EMBEDDING_DIMENSIONS.
        sa.Column("embedding", Vector(768), nullable=True),
        sa.Column("ingest_run_id", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["research_documents.id"],
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_research_claims_document_id",
        "research_claims",
        ["document_id"],
    )

    op.create_table(
        "research_tag_aliases",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("raw", sa.String(), nullable=False),
        sa.Column("canonical", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False, server_default="tag"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("raw", name="uq_research_tag_aliases_raw"),
    )


def downgrade() -> None:
    op.drop_table("research_tag_aliases")
    op.drop_index(
        "ix_research_claims_document_id", table_name="research_claims"
    )
    op.drop_table("research_claims")
    op.drop_table("research_document_pages")
    op.drop_index(
        "ix_research_documents_status", table_name="research_documents"
    )
    op.drop_index(
        "uq_research_documents_sha256_active",
        table_name="research_documents",
    )
    op.drop_table("research_documents")
    # The `vector` extension is left installed: other objects may come to
    # depend on it, and dropping shared extensions in a downgrade is unsafe.
