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
"""Persistence models for document translation jobs and their segments."""

import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from src.common.base_repository import BaseDocument, BaseStringDocument
from src.database import Base

_JsonType = JSONB().with_variant(JSON(), "sqlite")


class DocumentTranslationJob(Base):
    __tablename__ = "document_translation_jobs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    filename: Mapped[str] = mapped_column(String, nullable=False)
    # uploaded -> translating -> review -> completed | failed
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="uploaded"
    )
    target_market: Mapped[str | None] = mapped_column(String, nullable=True)
    model_id: Mapped[str | None] = mapped_column(String, nullable=True)
    source_gcs_uri: Mapped[str | None] = mapped_column(String, nullable=True)
    output_gcs_uri: Mapped[str | None] = mapped_column(String, nullable=True)
    stats: Mapped[dict | None] = mapped_column(_JsonType, nullable=True)
    progress: Mapped[dict | None] = mapped_column(_JsonType, nullable=True)
    qa_findings: Mapped[list | None] = mapped_column(_JsonType, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        insert_default=func.now(),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        insert_default=func.now(),
        server_default=func.now(),
        onupdate=func.now(),
    )


class DocumentTranslationSegment(Base):
    __tablename__ = "document_translation_segments"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    job_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("document_translation_jobs.id", ondelete="CASCADE"),
        nullable=False,
    )
    # The engine's deterministic parse-order id; reinjection key at export.
    seg_index: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    section_id: Mapped[str | None] = mapped_column(String, nullable=True)
    table_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    row_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    heading_level: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bold: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    section_path: Mapped[list | None] = mapped_column(_JsonType, nullable=True)
    source_text: Mapped[str] = mapped_column(Text, nullable=False)
    translation: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Review state: pending -> translated -> approved; failed when the model
    # gave up, locked for numeric cells that are never translated.
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="pending"
    )
    # Where the text came from — orthogonal to review state.
    # ai (model) | tm (reused from memory) | edited (human)
    provenance: Mapped[str | None] = mapped_column(String, nullable=True)
    # The QA finding attached to this segment, if any, so the review
    # workspace needs one call.
    finding: Mapped[dict | None] = mapped_column(_JsonType, nullable=True)

    __table_args__ = (
        Index(
            "ix_document_translation_segments_job",
            "job_id",
            "seg_index",
            unique=True,
        ),
    )


class DocumentTranslationMemory(Base):
    """Approved translations, keyed by normalised source text per market."""

    __tablename__ = "document_translation_memory"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    source_hash: Mapped[str] = mapped_column(String, nullable=False)
    target_market: Mapped[str] = mapped_column(String, nullable=False)
    source_text: Mapped[str] = mapped_column(Text, nullable=False)
    translation: Mapped[str] = mapped_column(Text, nullable=False)
    # Where this translation was approved, for provenance in the UI.
    origin_job_id: Mapped[str | None] = mapped_column(String, nullable=True)
    origin_filename: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        insert_default=func.now(),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        insert_default=func.now(),
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        Index(
            "ix_document_translation_memory_key",
            "source_hash",
            "target_market",
            unique=True,
        ),
    )


class DocumentTranslationMemoryModel(BaseDocument):
    source_hash: str
    target_market: str
    source_text: str
    translation: str
    origin_job_id: str | None = None
    origin_filename: str | None = None


class DocumentTranslationJobModel(BaseStringDocument):
    filename: str
    status: str = "uploaded"
    target_market: str | None = None
    model_id: str | None = None
    source_gcs_uri: str | None = None
    output_gcs_uri: str | None = None
    stats: dict | None = None
    progress: dict | None = None
    qa_findings: list | None = None
    error_message: str | None = None
    created_by: str | None = None
    # Computed, never stored: a "translating" job whose worker died with its
    # instance. The review UI offers Resume on it.
    stalled: bool = False


class DocumentTranslationSegmentModel(BaseDocument):
    job_id: str
    seg_index: int
    kind: str
    section_id: str | None = None
    table_index: int | None = None
    row_index: int | None = None
    heading_level: int | None = None
    bold: bool = False
    section_path: list | None = None
    source_text: str
    translation: str | None = None
    status: str = "pending"
    provenance: str | None = None
    finding: dict | None = None
