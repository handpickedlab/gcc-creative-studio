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
"""Seeds the default glossary from the bundled glossary-of-terms workbook.

Runs once (guarded by a system_settings flag). End users can edit the seeded
terms afterwards via the glossary management endpoints.
"""

import logging
import os

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.system_settings.schema.system_setting_model import SystemSetting
from src.translations import briefing_parser as parser
from src.translations.repository.glossary_repository import GlossaryRepository

logger = logging.getLogger(__name__)

_SEED_FLAG = "default_glossary_v1_seeded"
_SEED_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "seed", "glossary_of_terms.xlsx"
)


async def seed_default_glossary(db: AsyncSession) -> None:
    try:
        existing = await db.execute(
            select(SystemSetting).where(SystemSetting.id == _SEED_FLAG)
        )
        if existing.scalar_one_or_none():
            return  # already seeded

        if not os.path.exists(_SEED_PATH):
            logger.warning("Default glossary file not found at %s", _SEED_PATH)
            return

        with open(_SEED_PATH, "rb") as f:
            entries = parser.parse_glossary_workbook(f.read())

        rows = [
            {"language": e["market"], "source": e["source"], "target": e["target"]}
            for e in entries
        ]
        repo = GlossaryRepository(db)
        inserted = await repo.bulk_upsert(rows)

        db.add(
            SystemSetting(
                id=_SEED_FLAG,
                value="true",
                description="Default glossary-of-terms has been seeded.",
            )
        )
        await db.commit()
        logger.info(
            "Seeded default glossary: %s terms inserted (%s parsed).",
            inserted,
            len(rows),
        )
    except Exception as e:
        logger.error("Default glossary seeding failed: %s", e)
        await db.rollback()
