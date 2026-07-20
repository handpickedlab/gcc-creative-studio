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

"""Durable record of one data-query ``/ask`` run.

The agent can iterate for well over a minute on a follow-up (deep hybrid
retrieval), which is longer than the Firebase-Hosting rewrite timeout on a
buffered streaming response. So instead of streaming, ``/ask`` kicks the run
off in the background and writes its progress here; the client polls
``GET /ask/{id}`` and renders the accumulating steps + final answer.
"""

import datetime

from sqlalchemy import JSON, DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.common.base_repository import BaseStringDocument
from src.database import Base

_JsonListType = JSONB().with_variant(JSON(), "sqlite")


class DataQueryRun(Base):
    """SQLAlchemy model for the 'data_query_runs' table (one row per ask)."""

    __tablename__ = "data_query_runs"

    # Opaque UUID so run ids aren't enumerable across users.
    id: Mapped[str] = mapped_column(String, primary_key=True)
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="processing"
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    # The assembled trace (tool calls + answer text), same shape the client
    # renders; flushed periodically while the run is in progress.
    steps: Mapped[list] = mapped_column(_JsonListType, default=list)
    # Citations behind the answer (research-library claims).
    answer_sources: Mapped[list] = mapped_column(_JsonListType, default=list)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        insert_default=func.now(),
        server_default=func.now(),
    )


class DataQueryRunModel(BaseStringDocument):
    """COLLECTION: data_query_runs
    One background ``/ask`` run: its status, the accumulating trace steps, and
    the citations behind the final answer.
    """

    status: str = "processing"
    question: str
    steps: list[dict] = []
    answer_sources: list[dict] = []
    error_message: str | None = None
