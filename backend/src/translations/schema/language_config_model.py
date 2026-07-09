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

"""Per-language localization profile for translation.

One row per target market/language, holding the persistent steering the
language owner configures: formality register, whether ALL-CAPS is preserved,
and free-text tone/style guidance. Injected into the translation prompt so
output is localized per language instead of a single shared prompt for all
markets.
"""

import datetime
import enum

from pydantic import Field
from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from src.common.base_repository import BaseDocument
from src.database import Base


class FormalityEnum(str, enum.Enum):
    """Form of address to instruct per language.

    `default` = let the language's natural register stand (used for languages
    without a clean formal/informal split, e.g. English/Scandinavian).
    """

    FORMAL = "formal"
    INFORMAL = "informal"
    DEFAULT = "default"


class TranslationLanguageConfig(Base):
    """SQLAlchemy model for the 'translation_language_configs' table."""

    __tablename__ = "translation_language_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Market code (e.g. FR, DE) — matches translations.markets. Unique: one
    # profile per language.
    language: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    formality: Mapped[str] = mapped_column(
        String, nullable=False, default=FormalityEnum.DEFAULT.value
    )
    preserve_casing: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    guidance: Mapped[str | None] = mapped_column(Text, nullable=True)

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


class TranslationLanguageConfigModel(BaseDocument):
    """Pydantic model for a per-language localization profile."""

    id: int | None = None
    language: str = Field(description="Target market/language code, e.g. 'FR'.")
    formality: FormalityEnum = Field(
        default=FormalityEnum.DEFAULT,
        description="Form of address to instruct for this language.",
    )
    preserve_casing: bool = Field(
        default=True,
        description="Keep fully-uppercase source segments (CTAs) uppercase.",
    )
    guidance: str | None = Field(
        default=None,
        description="Free-text tone/style guidance injected into the prompt.",
    )
