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
"""Market/locale definitions for briefing translation.

Markets mirror the columns of the customer's translation spreadsheet. `EN` is
the source; every other market is a translation target. Each market maps to a
human-readable language/locale descriptor used to instruct Gemini.
"""

SOURCE_MARKET = "EN"

# Ordered to match the spreadsheet columns.
MARKETS: dict[str, str] = {
    "EN": "English (source)",
    "UK": "English (United Kingdom)",
    "NL": "Dutch (Netherlands)",
    "BENL": "Dutch (Belgium / Flemish)",
    "BEFR": "French (Belgium)",
    "FR": "French (France)",
    "LU": "French (Luxembourg)",
    "CHFR": "French (Switzerland)",
    "CHDE": "German (Switzerland)",
    "DE": "German (Germany)",
    "AT": "German (Austria)",
    "DK": "Danish (Denmark)",
    "ES": "Spanish (Spain)",
    "SE": "Swedish (Sweden)",
    "NO": "Norwegian (Norway)",
}

# Markets used as translation targets (everything except the source).
TARGET_MARKETS: list[str] = [m for m in MARKETS if m != SOURCE_MARKET]


def language_for_market(market: str) -> str:
    """Returns the language/locale descriptor for a market code."""
    return MARKETS.get(market, market)


def is_valid_market(market: str) -> bool:
    return market in MARKETS
