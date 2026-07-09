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
"""Unit 1: per-language localization profile repository (mocked session)."""

import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.translations.repository.language_config_repository import (
    LanguageConfigRepository,
)
from src.translations.schema.language_config_model import (
    TranslationLanguageConfig,
)


def _row(**overrides):
    now = datetime.datetime.now(datetime.UTC)
    defaults = dict(
        id=1,
        language="FR",
        formality="formal",
        preserve_casing=True,
        guidance="Elegant tone",
        created_at=now,
        updated_at=now,
    )
    defaults.update(overrides)
    return TranslationLanguageConfig(**defaults)


@pytest.mark.anyio
async def test_upsert_creates_when_absent():
    mock_db = AsyncMock()
    mock_db.add = MagicMock()  # Session.add is synchronous
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_db.execute.return_value = mock_result

    async def refresh(obj):
        obj.id = 5
        obj.created_at = datetime.datetime.now(datetime.UTC)
        obj.updated_at = obj.created_at

    mock_db.refresh.side_effect = refresh

    repo = LanguageConfigRepository(db=mock_db)
    model = await repo.upsert(
        "FR",
        {"formality": "formal", "preserve_casing": True, "guidance": "Elegant"},
    )

    mock_db.add.assert_called_once()
    mock_db.commit.assert_awaited_once()
    assert model.language == "FR"
    assert model.formality == "formal"
    assert model.guidance == "Elegant"


@pytest.mark.anyio
async def test_upsert_updates_existing_without_insert():
    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    existing = _row(formality="default", guidance="old")
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = existing
    mock_db.execute.return_value = mock_result

    repo = LanguageConfigRepository(db=mock_db)
    model = await repo.upsert("FR", {"formality": "formal", "guidance": "new"})

    mock_db.add.assert_not_called()  # updates existing, not a new insert
    assert model.formality == "formal"
    assert model.guidance == "new"
    # `language` in the payload must never overwrite the row key.
    assert model.language == "FR"


@pytest.mark.anyio
async def test_get_by_languages_returns_keyed_map():
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [
        _row(id=1, language="FR"),
        _row(id=2, language="DE", formality="informal"),
    ]
    mock_db.execute.return_value = mock_result

    repo = LanguageConfigRepository(db=mock_db)
    profiles = await repo.get_by_languages(["FR", "DE"])

    assert set(profiles) == {"FR", "DE"}
    assert profiles["DE"].formality == "informal"


@pytest.mark.anyio
async def test_get_by_languages_empty_input_short_circuits():
    mock_db = AsyncMock()
    repo = LanguageConfigRepository(db=mock_db)
    assert await repo.get_by_languages([]) == {}
    mock_db.execute.assert_not_called()


@pytest.mark.anyio
async def test_get_by_language_returns_none_when_missing():
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_db.execute.return_value = mock_result

    repo = LanguageConfigRepository(db=mock_db)
    assert await repo.get_by_language("ZZ") is None
