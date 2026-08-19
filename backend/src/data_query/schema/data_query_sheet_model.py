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

"""Durable catalog for uploaded data-query spreadsheets.

The DuckDB warehouse itself is a local, ephemeral file on the Cloud Run
instance — it is lost on restart and not shared across instances. This
Postgres catalog is the source of truth for which sheets exist: each row is
one loaded table, points at the raw uploaded file in GCS, and lets any
instance rehydrate its local DuckDB on demand.
"""

import datetime

from sqlalchemy import JSON, DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.common.base_repository import BaseDocument
from src.database import Base

_JsonListType = JSONB().with_variant(JSON(), "sqlite")


class DataQuerySheet(Base):
    """SQLAlchemy model for the 'data_query_sheets' table (one row per table)."""

    __tablename__ = "data_query_sheets"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # DuckDB table name (slugged). Unique among non-deleted rows via a
    # partial index below.
    table_name: Mapped[str] = mapped_column(String, nullable=False)
    source_file: Mapped[str] = mapped_column(String, nullable=False)
    sheet: Mapped[str | None] = mapped_column(String, nullable=True)
    n_rows: Mapped[int | None] = mapped_column(Integer, nullable=True)
    n_cols: Mapped[int | None] = mapped_column(Integer, nullable=True)
    columns: Mapped[list] = mapped_column(_JsonListType, default=list)
    # gs:// URI of the raw uploaded file (a multi-sheet workbook is shared by
    # several rows, one per sheet/table).
    gcs_uri: Mapped[str] = mapped_column(String, nullable=False)

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        insert_default=func.now(),
        server_default=func.now(),
    )
    deleted_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class DataQuerySheetModel(BaseDocument):
    """COLLECTION: data_query_sheets
    One uploaded spreadsheet table: its DuckDB table name, source file,
    shape, and the GCS location of the raw file it was loaded from.
    """

    id: int | None = None

    table_name: str
    source_file: str
    sheet: str | None = None
    n_rows: int | None = None
    n_cols: int | None = None
    columns: list[str] = []
    gcs_uri: str
    deleted_at: datetime.datetime | None = None
