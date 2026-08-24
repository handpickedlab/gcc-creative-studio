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

"""Gemini function-calling agent over the local DuckDB store and the
research document library.

The agent has two data sources: the DuckDB warehouse of uploaded sheets
(list_tables/describe_table/run_sql — exact numbers, real SQL) and the
research claim library (search_claims — facts extracted from slide decks and
trend reports, with document + page provenance). It yields a stream of events
(tool calls, results, answer, sources) so the frontend can show the agent's
work live and render slide citations.
"""
import logging

from google.genai import Client, types

from src.data_query import duckdb_store as store

logger = logging.getLogger(__name__)

# Each step is one model turn (which may fire several tool calls). Deep hybrid
# questions legitimately need many rounds (orient → sheets → several searches
# per facet → synthesise); the poll model removed the request-timeout ceiling,
# so give the agent real room before cutting it off.
MAX_STEPS = 30

# Citations the frontend can render; capped so a rambling session can't
# produce an unbounded sources event.
MAX_SOURCES = 20

SYSTEM = """You are a market research analyst answering questions about
Hunkemöller (a lingerie / bodyfashion retailer, often abbreviated "HKM" or
"hkm" — always treat those as "Hunkemöller"). You have TWO data sources and
are expected to use them TOGETHER (hybrid), not pick just one:

A. A DuckDB warehouse of the survey / tracker spreadsheets the user uploaded
   (brand & campaign trackers, concept- and product-tests, raw respondent
   data). Use `list_tables` / `describe_table` / `run_sql` for EXACT numbers —
   you never guess a figure. The real survey figures (awareness, NPS,
   competitor mentions, price willingness, concept-test scores) live HERE, not
   only in the decks.
B. A research library of claims extracted from slide decks and trend reports
   (Euromonitor, Kantar, McKinsey, Thuiswinkel, Hunkemöller's own decks, ...),
   searchable semantically via `search_claims`. Sources are English, Dutch and
   German; search works across languages.

BE THOROUGH — search deeply, hybridly and ITERATIVELY. One `search_claims`
call returns only its ~10 closest matches: that is a keyhole, never the whole
answer. For almost every question you should make SEVERAL tool calls:
- When a question is broad or vague ("brand awareness", "competitors",
  "price image", "what do customers think"), call `list_tags` FIRST to see
  which topics the library actually covers, then search the matching tags.
  Never fire one literal query, get 8 claims from a single document, and give
  up — that is the failure mode this guidance exists to prevent.
- When a question hinges on a specific market, period or segment (Belgium?
  2023? "the 45+ segment"?), call `list_facets` to see which geographies,
  periods, segments, claim types and documents the corpus ACTUALLY contains.
  If your target isn't listed there, it is genuinely absent — say so — instead
  of concluding "not found" from a query that may simply have been phrased
  wrong. Use the listed values to aim your searches precisely.
- Call `list_tables` early to see which uploaded survey/tracker sheets exist,
  then `describe_table` + `run_sql` on the relevant ones to pull ACTUAL
  numbers. Do not answer a metric question from the decks alone if a sheet
  could hold the figure.
- Run MULTIPLE `search_claims` calls, not one: vary the wording, try BOTH
  English and Dutch, expand "hkm" → "Hunkemöller", and split a broad question
  into facets — per market (Netherlands / Germany / Belgium / ...), per
  sub-topic, per synonym (e.g. awareness / consideration / top-of-mind /
  spontaneous mention / competitors / rivals / benchmark brands).
- Combine both sources before answering. NEVER conclude "not in the data"
  after a single search — reformulate (English, full brand name, add a
  geography or period hint) AND check the sheets first. Only report something
  as missing after several genuinely different attempts came up empty.

ASK BACK WHEN TRULY AMBIGUOUS: if, after orienting (`list_tags`) and a few
searches plus the sheets, the question is still genuinely ambiguous in a way
that changes the answer — which market (NL / DE / BE / global)? aided vs
spontaneous awareness? which period? — briefly summarise what you DID find,
then ask the user ONE short clarifying question instead of guessing. This is a
multi-turn tool, so a clarifying question is a valid answer. But do NOT ask
back for clear questions: do the work first, clarify only as a last resort.

Tool guidance:
- `search_claims` results are ranked by relevance × the document's priority
  tier × recency (newer content ranks higher). A user-set recency cutoff,
  if any, is already applied server-side — older editions will not appear.
  Prefer primary and recent sources when they disagree.
- `run_sql` is a single read-only SELECT/WITH. NEVER guess or invent column
  names — call `describe_table` and use ONLY the exact columns and values it
  returns (it lists each column's distinct values under `categories`). If a
  query fails with a Binder "column not found" error, that column does NOT
  exist: do not retry a slightly different name — re-read `describe_table` and
  use the real columns.
- The survey/tracker sheets are normalized to tidy LONG tables with columns
  like `question`, `answer`, `segment`, `base_n`, `value`: the metric is in
  `question`, the row category in `answer`, the banner breakdown (market, age,
  wave, ...) in `segment`, the base count in `base_n`, and the number in
  `value`. Query them by filtering, e.g.
  `SELECT question, answer, segment, value FROM <t>
   WHERE question ILIKE '%unaided awareness%' AND segment ILIKE '%Hunkem%'
   AND segment ILIKE '%NL%'`. Use ILIKE with `%` wildcards on `question` /
  `answer` / `segment` — never assume an exact column per metric or market.
- If a tracker figure is hard to isolate this way, fall back to `search_claims`
  (the same numbers were extracted from the slide decks) rather than guessing.

Citing & grounding — this is a research tool the user must be able to trust:
- Cite EVERY research-library fact inline as (document, p. page), e.g.
  "(Thuiswinkel Markt Monitor Q1 2025, p. 3)"; for a figure from a sheet, name
  the table / source file.
- State a figure, fact, document name or page number ONLY if it appears in a
  `search_claims` result or `run_sql` output from THIS conversation. Never
  invent a source, a page number or a statistic, and never rely on your own
  prior knowledge of a report.
- Do NOT treat facts embedded in the user's question as verified — confirm via
  a tool or say you could not verify them.
- When sources conflict on the same metric and segment, name BOTH values with
  their periods and prefer the most recent; a 2024 measurement and a 2030
  forecast are different facts — say which one you quote.
- For a multi-part or multi-hop question, answer each part the tools support
  and explicitly name the parts you could NOT find rather than filling the gap
  with a plausible-sounding figure.

This can be a MULTI-TURN conversation: earlier questions and answers may appear
before the current one. Use them as context for follow-ups (e.g. "en in
Duitsland?" refers to the previous topic), but still ground every new fact with
a fresh tool call.

Answer in the user's language (default Dutch), concise and concrete: lead with
the answer/number, then a short explanation. When in doubt, under-claim:
"dit staat niet in de bronnen" is always better than a confident guess."""

_TOOLS = [
    {
        "name": "list_tables",
        "description": "List every table in the warehouse (the uploaded sheets) with row counts.",
        "parameters_json_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "describe_table",
        "description": "Columns (name + type) and 5 sample rows of a table. Use before writing SQL.",
        "parameters_json_schema": {
            "type": "object",
            "properties": {"name": {"type": "string", "description": "table name"}},
            "required": ["name"],
        },
    },
    {
        "name": "run_sql",
        "description": "Run a single read-only SELECT/WITH query and get rows back. "
                       "DuckDB SQL: avg(), median(), quantile_cont(), count(), sum(), etc.",
        "parameters_json_schema": {
            "type": "object",
            "properties": {
                "sql": {"type": "string"},
                "max_rows": {"type": "integer"},
            },
            "required": ["sql"],
        },
    },
    {
        "name": "search_claims",
        "description": "Semantic search over the research library: facts/claims "
                       "extracted from slide decks and trend reports, each with its "
                       "source document + page. Works across English/Dutch/German. "
                       "Use for trends, forecasts and 'what do the reports say' "
                       "questions.",
        "parameters_json_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "natural-language search query",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "optional topic tag filter (lowercase English)",
                },
                "period": {
                    "type": "string",
                    "description": "optional period hint, e.g. '2025' or 'Q1 2025' "
                                   "(soft relevance signal, not a hard filter)",
                },
                "geography": {
                    "type": "string",
                    "description": "optional geography hint, e.g. 'Netherlands' "
                                   "(soft relevance signal, not a hard filter)",
                },
                "max_results": {"type": "integer"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "list_tags",
        "description": "List the research library's topic vocabulary: every "
                       "canonical tag and how many claims carry it (e.g. "
                       "'brand awareness', 'competitors', 'pricing', 'nps'). "
                       "Call this to ORIENT yourself on a broad or vague "
                       "question — see what the corpus actually covers, then "
                       "search the relevant tags instead of guessing one query.",
        "parameters_json_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "list_facets",
        "description": "List the searchable LANDSCAPE of the research library: "
                       "which geographies, market segments, periods, claim "
                       "types and documents actually exist, each with a claim "
                       "count. Call this to check whether a value you want (a "
                       "market like Belgium, a period, a segment) is even "
                       "present BEFORE searching for it — so that if it isn't "
                       "listed here, 'not in the data' is a real absence and "
                       "not just a mis-phrased query. Pair with `list_tags` "
                       "(topics) to see the full space you can search.",
        "parameters_json_schema": {"type": "object", "properties": {}},
    },
]


def _dispatch(name, args, allowed, claim_search=None,
              allowed_documents=None, list_tags=None, list_facets=None,
              min_period=None):
    if name == "list_tables":
        ts = store.list_tables()
        return [t for t in ts if allowed is None or t["table"] in allowed]
    if name == "describe_table":
        nm = args.get("name", "")
        if allowed is not None and nm not in allowed:
            return {"error": f"table {nm!r} is disabled in this session"}
        return store.describe_table(nm)
    if name == "run_sql":
        return store.run_sql(args.get("sql", ""),
                             max_rows=int(args.get("max_rows") or 500),
                             allowed=allowed)
    if name == "search_claims":
        if claim_search is None:
            return {"error": "the research library is not available in this session"}
        return claim_search(
            query=args.get("query", ""),
            tags=args.get("tags"),
            period=args.get("period"),
            geography=args.get("geography"),
            # allowed_documents and min_period are enforced server-side from
            # the request DTO, never trusted from the model's own arguments.
            allowed_documents=allowed_documents,
            min_period=min_period,
            max_results=int(args.get("max_results") or 10),
        )
    if name == "list_tags":
        if list_tags is None:
            return {"error": "the research library is not available in this session"}
        return list_tags(allowed_documents=allowed_documents)
    if name == "list_facets":
        if list_facets is None:
            return {"error": "the research library is not available in this session"}
        return list_facets(allowed_documents=allowed_documents)
    return {"error": f"unknown tool {name!r}"}


def _summarize(name, out):
    try:
        if isinstance(out, dict) and out.get("error"):
            return f"error: {out['error']}"
        if name == "run_sql":
            return f"{out.get('row_count', 0)} rows" + (" (truncated)" if out.get("truncated") else "")
        if name == "list_tables":
            return f"{len(out)} tables: " + ", ".join(t["table"] for t in out[:8])
        if name == "describe_table":
            cols = ", ".join(c["name"] for c in out.get("columns", []))
            return f"{out.get('n_rows')} rows · columns: {cols[:140]}"
        if name == "search_claims":
            docs = {r["document"] for r in out.get("results", [])}
            return f"{out.get('count', 0)} claims from {len(docs)} documents"
        if name == "list_tags":
            return f"{len(out.get('tags', []))} tags"
        if name == "list_facets":
            return (
                f"{len(out.get('geographies', []))} geographies, "
                f"{len(out.get('segments', []))} segments, "
                f"{len(out.get('periods', []))} periods, "
                f"{len(out.get('documents', []))} documents"
            )
    except Exception:
        pass
    return ""


def _collect_sources(sources, out):
    """Accumulates deduped citations from search_claims results."""
    for result in out.get("results", []):
        key = result.get("claim_id")
        if key is None or key in sources:
            continue
        sources[key] = {
            "claim_id": result["claim_id"],
            "document_id": result["document_id"],
            "document": result["document"],
            "page": result["page"],
            "statement": result["statement"],
            "period": result.get("period"),
            "source_citation": result.get("source_citation"),
        }


def stream_answer(client: Client, model: str, question: str, allowed=None,
                  claim_search=None, allowed_documents=None, history=None,
                  list_tags=None, list_facets=None, min_period=None):
    """Run the function-calling loop, yielding event dicts:
    {t:'tool',name,input}, {t:'tool_result',name,summary,result}, {t:'text',v},
    {t:'sources',v} (citations for search_claims facts), {t:'done'}.

    ``history`` is an optional list of prior turns ({"question", "answer"}) that
    seed the conversation so follow-up questions have context. Only the final
    answer text of each turn is replayed (not its tool traffic), which is enough
    for the model to resolve references like "en in Duitsland?".
    """
    tool = types.Tool(function_declarations=[types.FunctionDeclaration(**d) for d in _TOOLS])
    config = types.GenerateContentConfig(
        tools=[tool], system_instruction=SYSTEM, temperature=0
    )
    contents = []
    for turn in (history or []):
        prior_q = (turn.get("question") or "").strip()
        prior_a = (turn.get("answer") or "").strip()
        if prior_q:
            contents.append(types.Content(
                role="user", parts=[types.Part.from_text(text=prior_q)]))
        if prior_a:
            contents.append(types.Content(
                role="model", parts=[types.Part.from_text(text=prior_a)]))
    contents.append(types.Content(role="user", parts=[types.Part.from_text(text=question)]))
    sources = {}

    def _finish():
        if sources:
            yield {"t": "sources",
                   "v": list(sources.values())[:MAX_SOURCES]}

    for _ in range(MAX_STEPS):
        resp = client.models.generate_content(model=model, contents=contents, config=config)
        cand = resp.candidates[0] if resp.candidates else None
        text_parts, calls = [], []
        if cand and cand.content:
            contents.append(cand.content)
            for p in (cand.content.parts or []):
                if getattr(p, "text", None):
                    text_parts.append(p.text)
                if getattr(p, "function_call", None):
                    calls.append(p.function_call)

        if not calls:
            if text_parts:
                yield {"t": "text", "v": "".join(text_parts)}
            yield from _finish()
            return

        if text_parts:
            yield {"t": "text", "v": "".join(text_parts)}

        responses = []
        for fc in calls:
            args = dict(fc.args) if fc.args else {}
            yield {"t": "tool", "name": fc.name, "input": args}
            out = _dispatch(fc.name, args, allowed,
                            claim_search=claim_search,
                            allowed_documents=allowed_documents,
                            list_tags=list_tags,
                            list_facets=list_facets,
                            min_period=min_period)
            if fc.name == "search_claims" and isinstance(out, dict):
                _collect_sources(sources, out)
            yield {"t": "tool_result", "name": fc.name,
                   "summary": _summarize(fc.name, out),
                   "result": out if fc.name in ("run_sql", "search_claims") else None}
            responses.append(types.Part.from_function_response(
                name=fc.name, response={"result": out}))
        contents.append(types.Content(role="user", parts=responses))

    yield {"t": "text", "v": "(stopped: too many steps)"}
    yield from _finish()
