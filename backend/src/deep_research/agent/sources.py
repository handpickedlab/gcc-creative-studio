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

"""Resolve Vertex grounding redirect URLs to their real destinations.

Grounding with Google Search cites pages through short-lived
``vertexaisearch.cloud.google.com/grounding-api-redirect/...`` URLs: each one
302-redirects to the real page and expires after a few days. A report that
ships them has sources nobody can open -- including the claim verifier, whose
url_context reads then fail and drag every claim down to UNVERIFIABLE.

``resolve_grounding_redirects`` swaps every redirect URL in a text fragment
for the destination in its ``Location`` header. Only that first hop is
requested -- the target site itself is never fetched, so paywalls and bot
checks cannot break resolution. URLs that fail to resolve are left as-is.
"""

from __future__ import annotations

import asyncio
import logging
import re

import httpx

logger = logging.getLogger(__name__)

GROUNDING_REDIRECT_URL = re.compile(
    r"https://vertexaisearch\.cloud\.google\.com/grounding-api-redirect/"
    r"[A-Za-z0-9_\-=%]+"
)

# Bounds for the per-round resolution work: grounded findings can cite tens of
# URLs, and one slow lookup must not stall the research loop for long.
_MAX_CONCURRENT_LOOKUPS = 8
_LOOKUP_TIMEOUT_SECONDS = 10.0


async def _resolve_one(client: httpx.AsyncClient, url: str) -> str | None:
    """The redirect target of ``url``, or None when it does not cleanly redirect."""
    try:
        response = await client.get(url)
    except httpx.HTTPError as error:
        logger.warning("Could not resolve grounding redirect %s: %s", url, error)
        return None
    location = response.headers.get("location")
    if response.is_redirect and location:
        return location
    logger.warning(
        "Grounding redirect %s did not redirect (HTTP %s).",
        url,
        response.status_code,
    )
    return None


async def resolve_grounding_redirects(
    text: str, client: httpx.AsyncClient | None = None
) -> str:
    """Replace every grounding redirect URL in ``text`` with its destination.

    Each unique URL is looked up once, concurrently. ``client`` is injectable
    for tests; the default client does not follow redirects (only the
    ``Location`` header is needed) and is closed after use.
    """
    urls = sorted(set(GROUNDING_REDIRECT_URL.findall(text or "")))
    if not urls:
        return text

    async def resolve_all(client: httpx.AsyncClient) -> list[str | None]:
        semaphore = asyncio.Semaphore(_MAX_CONCURRENT_LOOKUPS)

        async def bounded(url: str) -> str | None:
            async with semaphore:
                return await _resolve_one(client, url)

        return await asyncio.gather(*(bounded(url) for url in urls))

    if client is None:
        async with httpx.AsyncClient(
            timeout=_LOOKUP_TIMEOUT_SECONDS, follow_redirects=False
        ) as owned_client:
            targets = await resolve_all(owned_client)
    else:
        targets = await resolve_all(client)

    resolved = {url: target for url, target in zip(urls, targets) if target}
    logger.info("Resolved %d/%d grounding redirect URLs.", len(resolved), len(urls))
    return GROUNDING_REDIRECT_URL.sub(
        lambda match: resolved.get(match.group(0), match.group(0)), text
    )
