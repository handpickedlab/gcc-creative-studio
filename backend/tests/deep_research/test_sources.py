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

"""Tests for resolving vertexaisearch grounding redirect URLs."""

import httpx
import pytest

from src.deep_research.agent.sources import resolve_grounding_redirects

_REDIRECT = "https://vertexaisearch.cloud.google.com/grounding-api-redirect"


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.anyio
async def test_redirects_are_replaced_with_their_targets():
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        if str(request.url).endswith("/abc123"):
            return httpx.Response(
                302, headers={"location": "https://real.example.com/article"}
            )
        return httpx.Response(404)

    text = (
        f"Fact one [Source: Title - {_REDIRECT}/abc123]\n"
        f"Fact two [Source: Other - {_REDIRECT}/dead-token]\n"
        f"Fact one again, cited as {_REDIRECT}/abc123."
    )
    async with _client(handler) as client:
        out = await resolve_grounding_redirects(text, client=client)

    # Both occurrences of the resolvable URL are swapped for the real page.
    assert out.count("https://real.example.com/article") == 2
    # Trailing punctuation survives the swap.
    assert "https://real.example.com/article." in out
    # A URL that does not redirect is kept as-is rather than dropped.
    assert f"{_REDIRECT}/dead-token" in out
    # Each unique URL is looked up exactly once.
    assert len(requested) == 2


@pytest.mark.anyio
async def test_text_without_redirect_urls_is_untouched_and_makes_no_requests():
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("no lookup expected")

    text = "Plain findings citing https://example.com/report directly."
    async with _client(handler) as client:
        assert await resolve_grounding_redirects(text, client=client) == text


@pytest.mark.anyio
async def test_network_errors_keep_the_original_url():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    text = f"Fact [Source: Title - {_REDIRECT}/abc123]"
    async with _client(handler) as client:
        assert await resolve_grounding_redirects(text, client=client) == text
