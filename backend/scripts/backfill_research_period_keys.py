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

"""Fills ``period_key`` and ``vintage_key`` for already-ingested rows.

Migration ``b6c7d8e9f0a1`` adds the columns; this fills them for documents
and claims that were ingested before period normalization existed. Purely
deterministic string parsing — no model calls, so it costs nothing and is
safe to re-run.

Three passes, in order, because each feeds the next:

1. documents: edition date from the filename,
2. claims: ``period`` -> sortable key, using the document's vintage year to
   date phrasings that omit it ("P10" on a 2024 deck's slide),
3. documents still undated: the latest period their own claims mention.

Usage (against the live database, via the Cloud SQL proxy):

    USE_CLOUD_SQL_AUTH_PROXY=true DB_HOST=127.0.0.1 DB_PORT=5433 \
    DB_USER=studio_user DB_NAME=creative_studio DB_PASS=... \
    uv run python scripts/backfill_research_period_keys.py [--dry-run]
"""

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text  # noqa: E402

from src.research_library import period_service  # noqa: E402


async def main(dry_run: bool) -> None:
    from src.database import async_session_local

    async with async_session_local() as db:
        # --- 1. document edition dates, from filenames -------------------
        documents = (
            await db.execute(
                text(
                    "SELECT id, filename FROM research_documents"
                    " WHERE deleted_at IS NULL"
                ),
            )
        ).mappings().all()

        vintages: dict[int, str] = {}
        for row in documents:
            key = period_service.parse_filename_vintage(row["filename"])
            if key:
                vintages[row["id"]] = key
        print(
            f"1. {len(vintages)}/{len(documents)} documents dated from their"
            " filename"
        )

        # --- 2. claim period keys ----------------------------------------
        pairs = (
            await db.execute(
                text(
                    "SELECT DISTINCT c.document_id, c.period"
                    " FROM research_claims c"
                    " JOIN research_documents d ON d.id = c.document_id"
                    " WHERE d.deleted_at IS NULL AND c.period IS NOT NULL",
                ),
            )
        ).mappings().all()

        updates = []
        for pair in pairs:
            vintage = vintages.get(pair["document_id"])
            year = int(vintage.split("-")[0]) if vintage else None
            key = period_service.normalize_period(pair["period"], year)
            if key:
                updates.append(
                    {
                        "doc": pair["document_id"],
                        "period": pair["period"],
                        "key": key,
                    },
                )
        print(
            f"2. {len(updates)}/{len(pairs)} distinct (document, period) pairs"
            " resolved"
        )

        if not dry_run and updates:
            await db.execute(
                text(
                    "UPDATE research_claims SET period_key = :key"
                    " WHERE document_id = :doc AND period = :period",
                ),
                updates,
            )
            await db.commit()

        # --- 3. documents dated by their own content ---------------------
        undated = [r["id"] for r in documents if r["id"] not in vintages]
        if undated and not dry_run:
            derived = (
                await db.execute(
                    text(
                        "SELECT document_id, MAX(period_key) AS key"
                        " FROM research_claims"
                        " WHERE document_id = ANY(:ids)"
                        " AND period_key IS NOT NULL"
                        " GROUP BY document_id",
                    ),
                    {"ids": undated},
                )
            ).mappings().all()
            for row in derived:
                vintages[row["document_id"]] = row["key"]
            print(
                f"3. {len(derived)}/{len(undated)} undated documents dated"
                " from their claims"
            )

        if not dry_run and vintages:
            await db.execute(
                text(
                    "UPDATE research_documents"
                    " SET vintage_key = :key, period = :label"
                    " WHERE id = :id",
                ),
                [
                    {
                        "id": doc_id,
                        "key": key,
                        "label": period_service.label_for_key(key),
                    }
                    for doc_id, key in vintages.items()
                ],
            )
            await db.commit()

        print(
            f"\n{'DRY RUN — nothing written' if dry_run else 'done'}:"
            f" {len(vintages)} documents dated,"
            f" {len(updates)} claim period groups keyed"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report what would change without writing",
    )
    asyncio.run(main(parser.parse_args().dry_run))
