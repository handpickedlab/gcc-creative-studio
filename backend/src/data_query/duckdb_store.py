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

"""Local DuckDB store for the data-query tool.

Spreadsheets (.csv/.xlsx) uploaded by the user are loaded into a local DuckDB
file as clean tables; the Gemini agent then introspects them and runs read-only
SQL. No vector index — the agent comprehends the tables at query time and lets
DuckDB compute exact numbers.

`duckdb` is imported lazily inside the functions so this module (and the FastAPI
app) still imports before `uv sync` installs the dependency.
"""
import io
import os
import re

import pandas as pd

DB_PATH = os.environ.get(
    "DATA_QUERY_DB_PATH",
    os.path.join(os.path.dirname(__file__), "..", "..", "data_query.duckdb"),
)

# read-only guard for run_sql: one statement, SELECT/WITH only, no dangerous verbs
_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|create|alter|attach|copy|install|load|"
    r"pragma|export|import|call|set)\b",
    re.I,
)


def _connect(read_only=False):
    import duckdb

    os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)
    # Read-only connections run the agent's arbitrary SQL, so lock down all
    # filesystem/network access: this stops a SELECT from exfiltrating local
    # files via DuckDB table functions like read_text()/read_csv()/glob().
    # Ingest (read_only=False) only runs our own controlled SQL and needs full
    # access for the in-memory pandas register step.
    config = {"enable_external_access": False} if read_only else {}
    return duckdb.connect(DB_PATH, read_only=read_only, config=config)


# --- spreadsheet cleaning -------------------------------------------------
def _slug(s):
    s = re.sub(r"[^0-9a-zA-Z]+", "_", str(s).strip().lower()).strip("_")
    if not s:
        s = "col"
    if s[0].isdigit():
        s = "c_" + s
    return s[:48]


def _dedupe(names):
    seen, out = {}, []
    for n in names:
        if n in seen:
            seen[n] += 1
            out.append(f"{n}_{seen[n]}")
        else:
            seen[n] = 1
            out.append(n)
    return out


def _detect_header(raw):
    best, best_n = 0, -1
    for i in range(min(8, len(raw))):
        n = int(raw.iloc[i].notna().sum())
        if n > best_n:
            best_n, best = n, i
    return best


def _frame(raw):
    """Raw (header-less) frame -> clean DataFrame with detected header + types."""
    raw = raw.dropna(axis=1, how="all").dropna(axis=0, how="all").reset_index(drop=True)
    if raw.empty:
        return None
    h = _detect_header(raw)
    header = _dedupe([_slug(c) for c in raw.iloc[h].tolist()])
    df = raw.iloc[h + 1:].reset_index(drop=True)
    df.columns = header
    df = df.dropna(axis=0, how="all")
    if df.empty:
        return None
    for c in df.columns:
        coerced = pd.to_numeric(df[c], errors="coerce")
        if df[c].notna().any() and coerced.notna().mean() >= 0.8:
            df[c] = coerced
    return df


def _ensure_catalog(con):
    con.execute(
        "CREATE TABLE IF NOT EXISTS uploads_catalog("
        "table_name VARCHAR PRIMARY KEY, source_file VARCHAR, sheet VARCHAR, "
        "n_rows BIGINT, n_cols INT, columns VARCHAR)"
    )


def ingest_bytes(filename: str, data: bytes) -> list[dict]:
    """Load a .csv/.xlsx file into DuckDB. Returns a summary per created table."""
    ext = filename.lower().rsplit(".", 1)[-1]
    stem = _slug(os.path.splitext(os.path.basename(filename))[0])
    frames: dict[str, pd.DataFrame] = {}

    if ext in ("xlsx", "xlsm", "xls"):
        sheets = pd.read_excel(io.BytesIO(data), sheet_name=None, header=None, dtype=object)
        for name, raw in sheets.items():
            f = _frame(raw)
            if f is not None and len(f):
                frames[name] = f
    elif ext == "csv":
        try:
            raw = pd.read_csv(io.BytesIO(data), header=None, dtype=object,
                              skip_blank_lines=True, on_bad_lines="skip")
        except Exception:
            raw = pd.read_csv(io.BytesIO(data), header=None, dtype=object,
                              skip_blank_lines=True, engine="python", on_bad_lines="skip")
        f = _frame(raw)
        if f is not None and len(f):
            frames["data"] = f
    else:
        raise ValueError(f"unsupported file type: .{ext} (only csv/xlsx)")

    if not frames:
        raise ValueError("no usable data found in the file")

    multi = len(frames) > 1
    out = []
    con = _connect(read_only=False)
    try:
        _ensure_catalog(con)
        for sheet, df in frames.items():
            tbl = (f"up_{stem}" + (f"_{_slug(sheet)}" if multi else ""))[:60]
            con.register("df_in", df)
            con.execute(f'CREATE OR REPLACE TABLE "{tbl}" AS SELECT * FROM df_in')
            con.unregister("df_in")
            n = con.execute(f'SELECT count(*) FROM "{tbl}"').fetchone()[0]
            cols = list(df.columns)
            con.execute("DELETE FROM uploads_catalog WHERE table_name = ?", [tbl])
            con.execute(
                "INSERT INTO uploads_catalog VALUES (?,?,?,?,?,?)",
                [tbl, os.path.basename(filename), sheet, n, len(cols), ",".join(cols)],
            )
            out.append({"table": tbl, "sheet": sheet, "n_rows": n, "columns": cols,
                        "source_file": os.path.basename(filename)})
    finally:
        con.close()
    return out


# --- introspection + query (read-only) ------------------------------------
def list_tables() -> list[dict]:
    if not os.path.exists(DB_PATH):
        return []
    con = _connect(read_only=True)
    try:
        tabs = [r[0] for r in con.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema='main' ORDER BY table_name").fetchall()]
        out = []
        for t in tabs:
            if t == "uploads_catalog":
                continue
            try:
                n = con.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0]
            except Exception:
                n = None
            out.append({"table": t, "n_rows": n})
    finally:
        con.close()
    return out


def describe_table(name: str) -> dict:
    if not os.path.exists(DB_PATH):
        return {"error": "no data loaded yet"}
    con = _connect(read_only=True)
    try:
        names = {r[0] for r in con.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema='main'").fetchall()}
        if name not in names:
            return {"error": f"unknown table {name!r}. Use list_tables()."}
        columns = [{"name": d[0], "type": d[1]}
                   for d in con.execute(f'DESCRIBE "{name}"').fetchall()]
        cur = con.execute(f'SELECT * FROM "{name}" LIMIT 5')
        cnames = [c[0] for c in cur.description]
        sample = [dict(zip(cnames, r)) for r in cur.fetchall()]
        n = con.execute(f'SELECT count(*) FROM "{name}"').fetchone()[0]
    finally:
        con.close()
    return {"table": name, "n_rows": n, "columns": columns, "sample": sample}


def _referenced_blocked_tables(con, sql: str, allowed: set[str]) -> list[str]:
    """Existing tables referenced by the SQL that are NOT in `allowed`.

    Table names are slugged ([a-z0-9_]), so a word-boundary match reliably
    isolates a whole identifier. Defense-in-depth: list_tables/describe_table
    already hide disabled tables, but the agent could still name one directly
    in a run_sql query, which would otherwise bypass the session whitelist.
    """
    existing = {r[0] for r in con.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema='main'").fetchall()}
    blocked = []
    for t in sorted(existing):
        if t == "uploads_catalog" or t in allowed:
            continue
        if re.search(rf"\b{re.escape(t)}\b", sql, re.I):
            blocked.append(t)
    return blocked


def run_sql(sql: str, max_rows: int = 500, allowed: set[str] | None = None) -> dict:
    stripped = (sql or "").strip().rstrip(";").strip()
    if ";" in stripped:
        return {"error": "only a single statement is allowed (no ';')."}
    if not re.match(r"^(select|with)\b", stripped, re.I):
        return {"error": "only SELECT/WITH queries are allowed."}
    if _FORBIDDEN.search(stripped):
        return {"error": "query contains a forbidden keyword (read-only access)."}
    if not os.path.exists(DB_PATH):
        return {"error": "no data loaded yet — upload a sheet first."}
    try:
        con = _connect(read_only=True)
        try:
            if allowed is not None:
                blocked = _referenced_blocked_tables(con, stripped, allowed)
                if blocked:
                    return {"error": "query references tables disabled in this "
                            f"session: {', '.join(blocked)}"}
            cur = con.execute(stripped)
            cols = [d[0] for d in cur.description]
            data = cur.fetchmany(max_rows + 1)
        finally:
            con.close()
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}
    truncated = len(data) > max_rows
    data = data[:max_rows]
    return {"columns": cols, "rows": [dict(zip(cols, r)) for r in data],
            "row_count": len(data), "truncated": truncated}
