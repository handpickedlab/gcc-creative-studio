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
from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column
from src.common.base_repository import BaseDocument
from src.database import Base


class GlossaryTerm(Base):
    """SQLAlchemy model for the 'glossary_terms' table.

    A glossary term is a global override: whenever `source` appears in the
    text to translate, the model is instructed to render it as `target`,
    regardless of the target language.
    """

    __tablename__ = "glossary_terms"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String, nullable=False, unique=True)
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
    source: str = Field(description="The source word/term to match in the text.")
    target: str = Field(
        description="The fixed translation to always use for the source term."
    )
