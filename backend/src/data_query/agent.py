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

"""Gemini function-calling agent over the local DuckDB store.

The agent discovers what tables exist (list_tables/describe_table) and then runs
real SQL (run_sql) to answer a natural-language question — DuckDB computes the
numbers. It yields a stream of events (tool calls, results, answer) so the
frontend can show the agent's work live.
"""
import logging

from google.genai import Client, types

from src.data_query import duckdb_store as store

logger = logging.getLogger(__name__)

MAX_STEPS = 12

SYSTEM = """You are a data analyst working on a local DuckDB warehouse of
spreadsheets the user uploaded. You answer questions by running REAL SQL — you
never guess a number.

Workflow:
1. ALWAYS start broad: call `list_tables` to see every available table (the
   uploaded sheets) before choosing one. Don't jump to a single table if you're
   not sure it's the right one.
2. Call `describe_table` to learn a table's columns + sample rows before writing SQL.
3. Then call `run_sql` with a single read-only SELECT/WITH. Column names are
   slugged (lowercase, underscores). Filter on values that actually exist.

Answer in the user's language (default Dutch), concise and concrete: lead with
the answer/number, then a short explanation. If data is missing, say so honestly
instead of inventing it."""

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
]


def _dispatch(name, args, allowed):
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
    except Exception:
        pass
    return ""


def stream_answer(client: Client, model: str, question: str, allowed=None):
    """Run the function-calling loop, yielding event dicts:
    {t:'tool',name,input}, {t:'tool_result',name,summary,result}, {t:'text',v}, {t:'done'}.
    """
    tool = types.Tool(function_declarations=[types.FunctionDeclaration(**d) for d in _TOOLS])
    config = types.GenerateContentConfig(
        tools=[tool], system_instruction=SYSTEM, temperature=0
    )
    contents = [types.Content(role="user", parts=[types.Part.from_text(text=question)])]

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
            return

        if text_parts:
            yield {"t": "text", "v": "".join(text_parts)}

        responses = []
        for fc in calls:
            args = dict(fc.args) if fc.args else {}
            yield {"t": "tool", "name": fc.name, "input": args}
            out = _dispatch(fc.name, args, allowed)
            yield {"t": "tool_result", "name": fc.name,
                   "summary": _summarize(fc.name, out),
                   "result": out if fc.name == "run_sql" else None}
            responses.append(types.Part.from_function_response(
                name=fc.name, response={"result": out}))
        contents.append(types.Content(role="user", parts=responses))

    yield {"t": "text", "v": "(stopped: too many steps)"}
