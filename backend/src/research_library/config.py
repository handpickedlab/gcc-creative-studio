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

"""Configuration for the research library ingest pipeline and claim search.

Mirrors ``src.deep_research.agent.config``'s per-role env-var pattern
(``DR_*`` there, ``RL_*`` here) so models, concurrency and thresholds can be
tuned without touching code. The extraction model defaults to the app-wide
``GEMINI_MODEL_ID`` (see ``src.config.config_service``).
"""

import os

from src.config.config_service import config_service

# Model used for per-page multimodal claim extraction. Defaults to the
# app-wide Gemini model (chart-heavy corpus favors the more accurate tier).
EXTRACT_MODEL = os.getenv("RL_EXTRACT_MODEL", config_service.GEMINI_MODEL_ID)

# Embedding model + output dimensionality for claim vectors. gemini-embedding-001
# explicitly supports the corpus's EN/NL/DE mix; text-embedding-005 is
# English-only and is not used here.
EMBED_MODEL = os.getenv("RL_EMBED_MODEL", "gemini-embedding-001")
EMBED_DIMENSIONS = int(os.getenv("RL_EMBED_DIMENSIONS", "768"))

# Target long-edge resolution (pixels) for rendered page images and their
# thumbnails.
RENDER_LONG_EDGE = int(os.getenv("RL_RENDER_LONG_EDGE", "1800"))
THUMB_LONG_EDGE = int(os.getenv("RL_THUMB_LONG_EDGE", "400"))

# Hard cap on pages processed per document (protects against monster decks
# such as the 700-page Euromonitor Passport export).
MAX_PAGES = int(os.getenv("RL_MAX_PAGES", "250"))

# Size of the dedicated ingest ThreadPoolExecutor (kept separate from the
# shared app.state.executor so a bulk ingest run can't starve other jobs).
INGEST_WORKERS = int(os.getenv("RL_INGEST_WORKERS", "2"))

# Upper bound on how many documents one process may hold in its in-memory
# ingest queue. Everything above this stays PROCESSING in the database until
# the sweeper has capacity for it. The bound is the whole point: the executor
# queue lives inside the API process, so a Cloud Run scale-down throws away
# whatever is still in it (a July 2026 bulk upload lost 120 documents that
# way). Keeping the queue shallow keeps the database the queue of record.
MAX_QUEUED = int(os.getenv("RL_MAX_QUEUED", str(INGEST_WORKERS * 3)))

# How long a document may sit in PROCESSING without any progress before the
# sweeper concludes its worker is gone and re-queues it. Must comfortably
# exceed the slowest single step (downloading a 300MB deck plus a LibreOffice
# conversion plus one extraction batch).
STALE_AFTER_SECONDS = int(os.getenv("RL_STALE_AFTER_SECONDS", "900"))

# How often the sweeper looks for stalled documents, and how long it waits
# after boot before the first sweep (the app needs ~2 minutes to finish
# warming up, and an instance that has just started owns no work yet).
SWEEP_INTERVAL_SECONDS = int(os.getenv("RL_SWEEP_INTERVAL_SECONDS", "300"))
SWEEP_INITIAL_DELAY_SECONDS = int(
    os.getenv("RL_SWEEP_INITIAL_DELAY_SECONDS", "120"),
)

# How often the sweeper may restart one document before giving up on it.
# A file heavy enough to exhaust the instance's memory (a 4GiB OOM kill ended
# the 23 July 2026 bulk run) would otherwise be retried forever, taking the
# instance down with it every round and paying for the extraction each time.
MAX_INGEST_ATTEMPTS = int(os.getenv("RL_MAX_INGEST_ATTEMPTS", "3"))

# Bounded concurrency for per-page extraction calls within a single document.
EXTRACT_CONCURRENCY = int(os.getenv("RL_EXTRACT_CONCURRENCY", "4"))

# Maximum accepted upload size, in bytes. Defaults to 300 MiB.
MAX_UPLOAD_BYTES = int(os.getenv("RL_MAX_UPLOAD_BYTES", str(300 * 1024 * 1024)))


def _parse_tier_weights(raw: str) -> dict[str, float]:
    """Parses a ``key=value,key=value`` string into a tier -> weight map."""
    weights: dict[str, float] = {}
    for pair in raw.split(","):
        pair = pair.strip()
        if not pair:
            continue
        key, _, value = pair.partition("=")
        key = key.strip()
        if not key or not value.strip():
            continue
        weights[key] = float(value.strip())
    return weights


# Score multiplier applied to a claim's cosine similarity based on its
# document's priority tier, so primary sources outrank background ones at
# equal semantic relevance. Overridable as "primary=1.0,supporting=0.85,
# background=0.7".
TIER_WEIGHTS = _parse_tier_weights(
    os.getenv(
        "RL_TIER_WEIGHTS",
        "primary=1.0,supporting=0.85,background=0.7",
    ),
)

# Recency boost: newer documents are usually the most reliable, so a claim's
# score is multiplied by (1 + RECENCY_WEIGHT × how-recent), where how-recent is
# 0 for the oldest document in the candidate pool and 1 for the newest (by
# upload time). At the default 0.25 the newest source gets a 25% edge over the
# oldest at equal semantic relevance — enough to break ties toward fresh data
# without letting an old-but-far-more-relevant claim be buried.
RECENCY_WEIGHT = float(os.getenv("RL_RECENCY_WEIGHT", "0.25"))
