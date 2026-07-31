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
"""Translation-memory keying.

Annual reports repeat heavily year over year — accounting policies and note
boilerplate are often word-for-word identical. Hashing the source text lets
an approved translation carry over instead of being paid for and reviewed
again.
"""

from __future__ import annotations

import hashlib
import re

_WHITESPACE = re.compile(r"\s+")


def normalize(text: str) -> str:
    """Collapses whitespace, keeping case and punctuation.

    Word scatters line breaks and non-breaking spaces through otherwise
    identical boilerplate, and casing is meaningful (ALL-CAPS headings), so
    only whitespace is folded.
    """
    return _WHITESPACE.sub(" ", text.replace("\xa0", " ")).strip()


def source_hash(text: str) -> str:
    return hashlib.sha256(normalize(text).encode("utf-8")).hexdigest()
