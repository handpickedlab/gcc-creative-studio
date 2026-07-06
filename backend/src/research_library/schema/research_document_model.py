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

"""SQLAlchemy + Pydantic models for the research document library.

Four tables: ``research_documents`` (one row per uploaded file),
``research_document_pages`` (one row per rendered page image),
``research_claims`` (one row per atomic insight extracted from a page, with
its embedding), and ``research_tag_aliases`` (raw -> canonical tag/metric
mapping, rebuilt by the Unit 4 canonicalization bootstrap).
"""

import datetime
import enum

from pydantic import Field
from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.common.base_repository import BaseDocument
from src.database import Base
from src.research_library.schema.vector_type import EmbeddingVector

# Claim embeddings are 768-dimensional (gemini-embedding-001,
# output_dimensionality=768). This is a schema decision, not an env-tunable
# one: widening it requires a new migration, so it is hardcoded here rather
# than read from config.EMBED_DIMENSIONS.
EMBEDDING_DIMENSIONS = 768

# JSONB on Postgres, plain JSON on every other dialect (the test suite runs
# SQLAlchemy models against SQLite/aiosqlite, which cannot compile JSONB).
_JsonListType = JSONB().with_variant(JSON(), "sqlite")


class DocKindEnum(str, enum.Enum):
    """Detected document kind, used to pick a default priority tier."""

    SLIDE_DECK = "slide-deck"
    PROSE_REPORT = "prose-report"
    INFOGRAPHIC = "infographic"
    IMAGE = "image"
    OTHER = "other"


class PriorityTierEnum(str, enum.Enum):
    """Ranking weight bucket for a document's claims."""

    PRIMARY = "primary"
    SUPPORTING = "supporting"
    BACKGROUND = "background"


class ResearchDocStatus(str, enum.Enum):
    """Lifecycle states for a research document.

    Mirrors ``src.common.schema.media_item_model.JobStatusEnum`` (PROCESSING,
    COMPLETED, FAILED, STOPPED) plus two states that enum has no room for:
    REJECTED (exact-duplicate or otherwise never queued for ingest) and
    COMPLETED_WITH_ERRORS (some pages failed after retries, the rest kept).
    Defined here instead of extending the shared enum so unrelated features
    are not exposed to states they don't handle.
    """

    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"
    REJECTED = "rejected"
    COMPLETED_WITH_ERRORS = "completed_with_errors"


class ClaimTypeEnum(str, enum.Enum):
    """Whether a claim states a measured fact or a forward-looking forecast."""

    MEASUREMENT = "measurement"
    FORECAST = "forecast"


class TagAliasKindEnum(str, enum.Enum):
    """Whether a tag alias resolves a free-text tag or a metric name."""

    TAG = "tag"
    METRIC = "metric"


class ResearchDocument(Base):
    """SQLAlchemy model for the 'research_documents' table.

    One row per uploaded source file (PDF/DOCX/PPT/PPTX/ODP/PNG/JPEG).
    """

    __tablename__ = "research_documents"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    filename: Mapped[str] = mapped_column(String, nullable=False)
    mime_type: Mapped[str] = mapped_column(String, nullable=False)
    # NULL for administrative rows (e.g. the REJECTED duplicate marker) that
    # deliberately don't carry the uploaded content's hash. See the partial
    # unique index below.
    sha256: Mapped[str | None] = mapped_column(String, nullable=True)
    gcs_uri: Mapped[str] = mapped_column(String, nullable=False)
    # Detected later in the pipeline (Unit 2/3); drives the default tier.
    doc_kind: Mapped[str | None] = mapped_column(String, nullable=True)
    language: Mapped[str | None] = mapped_column(String, nullable=True)
    period: Mapped[str | None] = mapped_column(String, nullable=True)
    priority_tier: Mapped[str] = mapped_column(
        String,
        nullable=False,
        default=PriorityTierEnum.PRIMARY.value,
    )
    status: Mapped[str] = mapped_column(
        String,
        nullable=False,
        default=ResearchDocStatus.PROCESSING.value,
    )
    error_message: Mapped[str | None] = mapped_column(String, nullable=True)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    failed_pages: Mapped[list] = mapped_column(_JsonListType, default=list)
    ingest_run_id: Mapped[str | None] = mapped_column(String, nullable=True)

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        insert_default=func.now(),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        insert_default=func.now(),
        onupdate=func.now(),
        server_default=func.now(),
    )
    deleted_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    __table_args__ = (
        # Uniqueness only applies among non-soft-deleted rows, and NULL
        # sha256 values are never compared for uniqueness by either dialect.
        # This lets: (a) the same content be re-uploaded after its original
        # document is deleted, and (b) a REJECTED duplicate-marker row
        # coexist with the original it duplicates (it stores sha256=NULL).
        Index(
            "uq_research_documents_sha256_active",
            "sha256",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
            sqlite_where=text("deleted_at IS NULL"),
        ),
        Index("ix_research_documents_status", "status"),
    )


class ResearchDocumentPage(Base):
    """SQLAlchemy model for the 'research_document_pages' table.

    One row per rendered page image (+ thumbnail) of a document.
    """

    __tablename__ = "research_document_pages"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("research_documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    page_no: Mapped[int] = mapped_column(Integer, nullable=False)
    image_gcs_uri: Mapped[str | None] = mapped_column(String, nullable=True)
    thumb_gcs_uri: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(
        String,
        nullable=False,
        default=ResearchDocStatus.PROCESSING.value,
    )
    error: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "document_id",
            "page_no",
            name="uq_research_document_pages_document_page",
        ),
    )


class ResearchClaim(Base):
    """SQLAlchemy model for the 'research_claims' table.

    One row per atomic insight extracted from a single page, with its
    embedding for semantic search.
    """

    __tablename__ = "research_claims"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("research_documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    page_no: Mapped[int] = mapped_column(Integer, nullable=False)
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    metric: Mapped[str | None] = mapped_column(String, nullable=True)
    # Values like "46%" or ranges ("30-40%") stay strings; never coerced to
    # a number so the extraction never has to choose a representation.
    value: Mapped[str | None] = mapped_column(String, nullable=True)
    unit: Mapped[str | None] = mapped_column(String, nullable=True)
    segment: Mapped[str | None] = mapped_column(String, nullable=True)
    geography: Mapped[str | None] = mapped_column(String, nullable=True)
    period: Mapped[str | None] = mapped_column(String, nullable=True)
    claim_type: Mapped[str | None] = mapped_column(String, nullable=True)
    source_citation: Mapped[str | None] = mapped_column(String, nullable=True)
    sample: Mapped[str | None] = mapped_column(String, nullable=True)
    raw_tags: Mapped[list] = mapped_column(_JsonListType, default=list)
    canonical_tags: Mapped[list] = mapped_column(_JsonListType, default=list)
    embedding: Mapped[list[float] | None] = mapped_column(
        EmbeddingVector(EMBEDDING_DIMENSIONS),
        nullable=True,
    )
    ingest_run_id: Mapped[str | None] = mapped_column(String, nullable=True)

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        insert_default=func.now(),
        server_default=func.now(),
    )

    __table_args__ = (
        Index("ix_research_claims_document_id", "document_id"),
    )


class TagAlias(Base):
    """SQLAlchemy model for the 'research_tag_aliases' table.

    Maps a raw tag or metric name to its canonical (English) form. Rebuilt by
    the Unit 4 canonicalization bootstrap; consulted at extraction time to
    seed the vocabulary and at write time to auto-alias unseen tags.
    """

    __tablename__ = "research_tag_aliases"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    raw: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    canonical: Mapped[str] = mapped_column(String, nullable=False)
    kind: Mapped[str] = mapped_column(
        String,
        nullable=False,
        default=TagAliasKindEnum.TAG.value,
    )

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        insert_default=func.now(),
        server_default=func.now(),
    )


class ResearchDocumentModel(BaseDocument):
    """COLLECTION: research_documents
    A single uploaded market research file: its storage location, detected
    kind/language/period, priority tier, and ingest lifecycle status.
    """

    id: int | None = None

    filename: str
    mime_type: str
    sha256: str | None = None
    gcs_uri: str
    doc_kind: DocKindEnum | None = Field(
        default=None,
        description="Detected during ingest; drives the default priority tier.",
    )
    language: str | None = None
    period: str | None = Field(
        default=None,
        description="Edition/vintage of the document, e.g. 'Q1 2025'.",
    )
    priority_tier: PriorityTierEnum = PriorityTierEnum.PRIMARY
    status: ResearchDocStatus = ResearchDocStatus.PROCESSING
    error_message: str | None = None
    page_count: int | None = None
    failed_pages: list[int] = Field(default_factory=list)
    ingest_run_id: str | None = None
    deleted_at: datetime.datetime | None = None


class ResearchDocumentPageModel(BaseDocument):
    """COLLECTION: research_document_pages
    A single rendered page image (+ thumbnail) belonging to a document.
    """

    id: int | None = None

    document_id: int
    page_no: int
    image_gcs_uri: str | None = None
    thumb_gcs_uri: str | None = None
    status: ResearchDocStatus = ResearchDocStatus.PROCESSING
    error: str | None = None


class ResearchClaimModel(BaseDocument):
    """COLLECTION: research_claims
    A single atomic insight extracted from one page of a document, with its
    embedding for semantic search.
    """

    id: int | None = None

    document_id: int
    page_no: int
    statement: str
    metric: str | None = None
    value: str | None = Field(
        default=None,
        description="Kept as a string (e.g. '46%', '30-40%'); never coerced.",
    )
    unit: str | None = None
    segment: str | None = None
    geography: str | None = None
    period: str | None = None
    claim_type: ClaimTypeEnum | None = None
    source_citation: str | None = None
    sample: str | None = None
    raw_tags: list[str] = Field(default_factory=list)
    canonical_tags: list[str] = Field(default_factory=list)
    embedding: list[float] | None = None
    ingest_run_id: str | None = None


class TagAliasModel(BaseDocument):
    """COLLECTION: research_tag_aliases
    Maps a raw tag/metric string to its canonical (English) form.
    """

    id: int | None = None

    raw: str
    canonical: str
    kind: TagAliasKindEnum = TagAliasKindEnum.TAG
