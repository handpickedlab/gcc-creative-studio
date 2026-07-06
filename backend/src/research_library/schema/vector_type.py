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

"""Dialect-aware embedding column type.

Claim embeddings live in Postgres/pgvector in every real environment, but the
backend test suite exercises SQLAlchemy models against an in-memory SQLite
database (via aiosqlite) that has no ``vector`` extension. ``EmbeddingVector``
renders as pgvector's ``Vector`` on the ``postgresql`` dialect and falls back
to a plain JSON float list everywhere else, so ``Base.metadata.create_all()``
keeps working for tests without special-casing this column.
"""

from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON
from sqlalchemy.engine.interfaces import Dialect
from sqlalchemy.types import TypeDecorator, TypeEngine


class EmbeddingVector(TypeDecorator):
    """A fixed-dimension embedding column: pgvector on Postgres, JSON elsewhere."""

    impl = JSON
    cache_ok = True

    def __init__(self, dimensions: int, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.dimensions = dimensions

    def load_dialect_impl(self, dialect: Dialect) -> TypeEngine:
        if dialect.name == "postgresql":
            return dialect.type_descriptor(Vector(self.dimensions))
        return dialect.type_descriptor(JSON())

    def process_bind_param(
        self,
        value: list[float] | None,
        dialect: Dialect,
    ) -> list[float] | None:
        if value is None:
            return None
        return list(value)

    def process_result_value(
        self,
        value: list[float] | None,
        dialect: Dialect,
    ) -> list[float] | None:
        if value is None:
            return None
        return list(value)
