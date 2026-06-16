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

import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel
from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column
from src.common.base_repository import BaseDocument
from src.database import Base


# --- Plain Pydantic value objects (stored inside JSON columns) -------------


class _CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class BriefingSegment(_CamelModel):
    """A single copy snippet within a briefing (e.g. B1 / Header)."""

    block: str | None = Field(default=None, description="Block label, e.g. 'B1'.")
    field: str = Field(description="Field name, e.g. 'Header', 'Body', 'CTA'.")
    label: str = Field(description="Full label as shown, incl. limit hints.")
    char_limit: int | None = Field(
        default=None, description="Maximum character count, if any."
    )
    text: str = Field(default="", description="The copy text (source or translated).")


class BriefingMeta(_CamelModel):
    """Free-form briefing metadata (request header fields)."""

    request_label: str | None = None
    email: str | None = None
    requestor: str | None = None
    date_email: str | None = None
    due: str | None = None
    notes: str | None = None


# --- ORM models ------------------------------------------------------------


class Briefing(Base):
    """A campaign briefing: structured copy in the source market (EN)."""

    __tablename__ = "briefings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    source_market: Mapped[str] = mapped_column(
        String, nullable=False, server_default="EN"
    )
    # Column is NOT named "metadata" (reserved by SQLAlchemy Declarative).
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    segments: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), insert_default=func.now(), server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        insert_default=func.now(),
        onupdate=func.now(),
        server_default=func.now(),
    )


class BriefingTranslation(Base):
    """A translated version of a briefing for one target market."""

    __tablename__ = "briefing_translations"
    __table_args__ = (
        UniqueConstraint(
            "briefing_id", "market", name="uq_briefing_translation_market"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    briefing_id: Mapped[int] = mapped_column(
        ForeignKey("briefings.id", ondelete="CASCADE"), nullable=False
    )
    market: Mapped[str] = mapped_column(String, nullable=False)
    segments: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    status: Mapped[str] = mapped_column(
        String, nullable=False, server_default="draft"
    )
    comment: Mapped[str | None] = mapped_column(String, nullable=True)

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), insert_default=func.now(), server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        insert_default=func.now(),
        onupdate=func.now(),
        server_default=func.now(),
    )


# --- Pydantic response models ---------------------------------------------


class BriefingTranslationModel(BaseDocument):
    id: int
    briefing_id: int
    market: str
    segments: list[BriefingSegment]
    status: str = "draft"
    comment: str | None = None


class BriefingModel(BaseDocument):
    id: int
    name: str
    source_market: str = "EN"
    meta: BriefingMeta = Field(default_factory=BriefingMeta)
    segments: list[BriefingSegment] = Field(default_factory=list)
