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

MAX_STEPS = 12

# Citations the frontend can render; capped so a rambling session can't
# produce an unbounded sources event.
MAX_SOURCES = 20

SYSTEM = """You are a market research analyst with two data sources:

A. A DuckDB warehouse of spreadsheets the user uploaded. For exact numbers
   and computations you run REAL SQL — you never guess a number.
B. A research library of claims extracted from slide decks and trend reports
   (Euromonitor, Kantar, McKinsey, Thuiswinkel, ...), searchable
   semantically via `search_claims`. Sources are in English, Dutch and
   German; search works across languages, so query in the user's wording.

Choosing tools:
- Facts, trends, forecasts, "what do the reports say about X" -> `search_claims`.
- Computations, aggregations, exact figures from the uploaded sheets ->
  `list_tables` / `describe_table` / `run_sql` (single read-only SELECT/WITH,
  slugged column names).
- Many questions need both; combine them freely. If one source returns
  nothing useful, try the other before concluding the data doesn't exist.

Using search_claims results:
- Results are ranked by relevance times the document's priority tier;
  prefer higher-tier (primary) sources when they disagree.
- Cite EVERY research-library fact inline as (document, p. page), e.g.
  "(Thuiswinkel Markt Monitor Q1 2025, p. 3)".
- When sources conflict on the same metric and segment, name BOTH values
  with their periods and prefer the most recent period — never silently
  pick one.
- A claim's period matters: a 2024 measurement and a 2030 forecast are
  different facts. Say which one you are quoting.

Answer in the user's language (default Dutch), concise and concrete: lead
with the answer/number, then a short explanation. If data is missing from
both sources, say so honestly instead of inventing it."""

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
]


def _dispatch(name, args, allowed, claim_search=None,
              allowed_documents=None):
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
            # allowed_documents is enforced server-side from the request DTO,
            # never trusted from the model's own arguments.
            allowed_documents=allowed_documents,
            max_results=int(args.get("max_results") or 8),
        )
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
                  claim_search=None, allowed_documents=None):
    """Run the function-calling loop, yielding event dicts:
    {t:'tool',name,input}, {t:'tool_result',name,summary,result}, {t:'text',v},
    {t:'sources',v} (citations for search_claims facts), {t:'done'}.
    """
    tool = types.Tool(function_declarations=[types.FunctionDeclaration(**d) for d in _TOOLS])
    config = types.GenerateContentConfig(
        tools=[tool], system_instruction=SYSTEM, temperature=0
    )
    contents = [types.Content(role="user", parts=[types.Part.from_text(text=question)])]
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
                            allowed_documents=allowed_documents)
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
