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
from pydantic import Field
from sqlalchemy import DateTime, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column
from src.common.base_repository import BaseDocument
from src.database import Base


class GlossaryTerm(Base):
    """SQLAlchemy model for the 'glossary_terms' table.

    Each glossary term belongs to a specific target `language`: whenever
    `source` appears in the text to translate into that language, the model
    is instructed to render it as `target`. Each language has its own
    dictionary, so the same source term may map to different targets per
    language. The pair (language, source) is unique.
    """

    __tablename__ = "glossary_terms"
    __table_args__ = (
        UniqueConstraint("language", "source", name="uq_glossary_terms_lang_source"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    language: Mapped[str] = mapped_column(String, nullable=False)
    source: Mapped[str] = mapped_column(String, nullable=False)
    target: Mapped[str] = mapped_column(String, nullable=False)

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


class GlossaryTermModel(BaseDocument):
    """Pydantic model representing a glossary term."""

    id: int = Field(description="The auto-generated ID of the glossary term.")
    language: str = Field(
        description="The target language this dictionary entry applies to."
    )
    source: str = Field(description="The source word/term to match in the text.")
    target: str = Field(
        description="The fixed translation to always use for the source term."
    )
