# Copyright 2025 Google LLC
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
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.common.base_repository import BaseDocument
from src.common.schema.media_item_model import JobStatusEnum
from src.database import Base


class DeepResearchReport(Base):
    """SQLAlchemy model for the 'deep_research_reports' table.

    One row per Consumer Sentiment Scan: the intake selections, the assembled
    brief and, once the background pipeline finishes, the cited Markdown report.
    """

    __tablename__ = "deep_research_reports"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )

    topic: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[JobStatusEnum] = mapped_column(
        String,
        default=JobStatusEnum.PROCESSING.value,
    )
    error_message: Mapped[str | None] = mapped_column(String, nullable=True)

    # Number of search/reflect rounds requested for this run (None = default).
    max_iterations: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # The raw intake selections (field key -> str | list[str]).
    intake: Mapped[dict] = mapped_column(JSONB, default=dict)
    # Live progress events (author/kind/text) while the pipeline runs, so the
    # client can poll and show what the agent is doing.
    progress: Mapped[list] = mapped_column(JSONB, default=list)
    # The assembled research brief fed to the pipeline as the user message.
    brief: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The final, cited Markdown report produced by the pipeline.
    report: Mapped[str | None] = mapped_column(Text, nullable=True)

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


class DeepResearchReportModel(BaseDocument):
    """Pydantic representation (DTO) of a deep research report."""

    id: int | None = None

    user_id: int
    topic: str
    status: JobStatusEnum = JobStatusEnum.PROCESSING
    error_message: str | None = None
    max_iterations: int | None = None

    intake: dict = Field(
        default_factory=dict,
        description="The raw intake selections used to build the brief.",
    )
    progress: list = Field(
        default_factory=list,
        description="Live progress events emitted while the pipeline runs.",
    )
    brief: str | None = Field(
        default=None,
        description="The assembled research brief fed to the pipeline.",
    )
    report: str | None = Field(
        default=None,
        description="The final cited Markdown report, once completed.",
    )
