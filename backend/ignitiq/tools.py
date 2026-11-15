"""Agent tools for FlameScope (Phase 3.4).

Four tools, their Anthropic tool schemas, and one dispatcher. No LLM calls here,
so everything is testable from the CLI without an API key.

    search_docs(query, psi_ids?, source_types?, k?)    -> passages (rag.search)
    query_tests(sql)                                    -> rows (read-only DuckDB SELECT)
    get_investigation(psi_id)                           -> metadata, text, pubs, test stats
    nearest_conditions(habitat? | pressure_kpa + o2_frac, per_experiment?)

CLI (from backend/):
    uv run python -m ignitiq.tools               # self-test
    uv run python -m ignitiq.tools --specs       # print the tool descriptions
"""
from __future__ import annotations

import argparse
import datetime as dt
import decimal
import functools
import json
import math
import re
import threading

import duckdb

from ignitiq import conditions, rag
from ignitiq.conditions import _records
from ignitiq.db import connect

MAX_ROWS = 200
MAX_SQL_CHARS = 8000
QUERY_TIMEOUT_S = 10.0
MAX_PASSAGE_CHARS = 2200
MAX_FIELD_CHARS = 1200
MAX_RESULT_CHARS = 20000

TEXT_FIELDS = ["objective", "approach", "hypothesis", "research_impacts", "hardware", "description"]
LINEAGE_KEYS = {"raw", "source_file", "source_row"}
# Left out of the query_tests description to save tokens: ids, dates and free text.
HIDDEN_KEYS = LINEAGE_KEYS | {
    "date", "day", "gmt_day", "source_test_id", "identifier", "notes", "note", "comments",
    "description", "color", "sample_label", "planned_test_num", "sample_num", "cir_id",
    "record_type", "length_raw", "one_g_burn_length_raw", "fuel_text", "same_as",
}


# ---------------------------------------------------------------- value cleaning

def _val(v):
    """DuckDB values -> compact JSON-safe Python."""
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, float):
        return None if math.isnan(v) or math.isinf(v) else round(v, 6)
    if isinstance(v, decimal.Decimal):
        return round(float(v), 6)
    if isinstance(v, (dt.date, dt.datetime, dt.time)):
        return v.isoformat()
    if isinstance(v, (list, tuple)):
        return [_val(x) for x in v]
    if isinstance(v, dict):
        return {k: _val(x) for k, x in v.items()}
    if isinstance(v, (bytes, bytearray)):
        return f"<{len(v)} bytes>"
    return v


def to_text(result: dict, max_chars: int = MAX_RESULT_CHARS) -> str:
    """Serialize a tool result for the model, capped so one result can't flood the context."""
    s = json.dumps(result, ensure_ascii=False, default=str)
    if len(s) > max_chars:
        s = s[:max_chars] + f' ... [truncated {len(s) - max_chars} chars; narrow the request]'
    return s


# ---------------------------------------------------------------- SQL guard

def check_sql(sql: str) -> str | None:
    """Return an error message if sql is not exactly one SELECT, else None."""
    if not isinstance(sql, str) or not sql.strip():
        return "empty SQL"
    if len(sql) > MAX_SQL_CHARS:
        return f"SQL longer than {MAX_SQL_CHARS} chars"
    try:
        stmts = duckdb.extract_statements(sql)
    except duckdb.Error as e:
        return f"parse error: {e}"
    if len(stmts) != 1:
        return f"exactly one statement allowed, got {len(stmts)}"
    if stmts[0].type != duckdb.StatementType.SELECT:
        return f"only SELECT is allowed, got {stmts[0].type.name}"
    return None


@functools.lru_cache(maxsize=1)
def _key_types() -> dict:
    """Every extra key -> True if its values are numeric. Used by the column auto-fix."""
    con = connect()
    try:
        rows = con.execute("""
            select k, bool_and(json_type(extra -> k) in ('BIGINT', 'UBIGINT', 'DOUBLE'))
            from (select extra, unnest(json_keys(extra)) as k from tests)
            where json_type(extra -> k) <> 'NULL'
            group by k
        """).fetchall()
    finally:
        con.close()
    return {k: bool(n) for k, n in rows}


_MISSING_COL = re.compile(r'Referenced column "([A-Za-z_][A-Za-z0-9_]*)" not found')


def _rewrite_extra_key(sql: str, key: str, numeric: bool) -> str:
    """Bare key -> JSON access. Skips quoted text, qualified names (t.key) and aliases (AS key)."""
    expr = f"TRY_CAST(extra->>'{key}' AS DOUBLE)" if numeric else f"(extra->>'{key}')"
    return re.sub(rf"(?<![\w'\".>])(?<!AS )(?<!as ){re.escape(key)}(?![\w'\"])", expr, sql)


def _run_select(sql: str) -> dict:
    err = check_sql(sql)
    if err:
        return {"error": err, "sql": sql}
    con = connect()
    timer = threading.Timer(QUERY_TIMEOUT_S, con.interrupt)
    try:
        # Layer 3: block file and network access (read_csv, COPY TO, ATTACH, INSTALL).
        # Fail closed: if this SET fails, no query runs.
        con.execute("SET enable_external_access = false")
        timer.start()
        cur = con.execute(sql)
        cols = [d[0] for d in cur.description]
        rows = cur.fetchmany(MAX_ROWS + 1)
    except duckdb.InterruptException:
        return {"error": f"query exceeded {QUERY_TIMEOUT_S:.0f}s; simplify or aggregate", "sql": sql}
    except duckdb.BinderException as e:  # unknown column or table: hand back the real schema
        return {"error": f"BinderException: {e}", "hint": _schema_hint(), "sql": sql, "_binder": True}
    except duckdb.Error as e:
        return {"error": f"{type(e).__name__}: {e}", "sql": sql}
    finally:
        timer.cancel()
        con.close()
    truncated = len(rows) > MAX_ROWS
    rows = rows[:MAX_ROWS]
    return {"sql": sql, "columns": cols, "rows": [[_val(v) for v in r] for r in rows],
            "row_count": len(rows), "truncated": truncated}


_FROM_TESTS = re.compile(
    r"\bfrom\s+tests\b(?:\s+(?:as\s+)?(?P<alias>(?!where\b|group\b|order\b|limit\b|having\b)[A-Za-z_]\w*))?"
    r"(?:\s+(?P<where>where\s+.+?))?\s*(?=\bgroup\s+by\b|\border\s+by\b|\blimit\b|\bhaving\b|;|$)",
    re.I | re.S)


def _provenance(sql: str) -> list | None:
    """Which experiments a simple single-table query's rows came from (same WHERE, grouped).
    Skips joins, unions, subqueries and CTEs rather than guessing."""
    s = sql.strip()
    if re.match(r"with\b", s, re.I) or re.search(r"\b(join|union)\b|\(\s*select\b", s, re.I):
        return None
    m = _FROM_TESTS.search(s)
    if not m:
        return None
    alias, where = m.group("alias") or "", m.group("where") or ""
    r = _run_select(f"select experiment, psi_id, count(*) as n from tests {alias} {where} "
                    f"group by 1, 2 order by n desc limit 20")
    return r.get("rows") if "rows" in r else None


def query_tests(sql: str) -> dict:
    """Run a guarded SELECT. If it fails only because an extra JSON key was used as a column,
    rewrite that key to extra->>'key' and retry (up to 3 keys), instead of costing a model round trip."""
    original, fixes = sql, []
    res = _run_select(sql)
    types = _key_types()
    for _ in range(3):
        m = _MISSING_COL.search(res.get("error", "")) if res.get("_binder") else None
        if not m or m.group(1) not in types:
            break
        key = m.group(1)
        fixed = _rewrite_extra_key(sql, key, types[key])
        if fixed == sql or check_sql(fixed):
            break
        fixes.append(f"{key} -> extra->>'{key}'")
        sql = fixed
        res = _run_select(sql)
    res.pop("_binder", None)
    if fixes:
        res["auto_fixed"] = fixes
        res["original_sql"] = original
    # Rows without experiment/psi_id can't be cited: attach which experiments they came from.
    if "rows" in res and not ({"experiment", "psi_id"} & {c.lower() for c in res["columns"]}):
        prov = _provenance(sql)
        if prov:
            res["provenance"] = {"columns": ["experiment", "psi_id", "n"], "rows": prov}
    return res


# ---------------------------------------------------------------- other tools

# A query that names an incident always gets that incident's best passage. Dense search on a
# short query can rank long experiment write-ups above the one page that is actually about it.
INCIDENT_DOCS = {
    "apollo_13": re.compile(r"apollo[\s-]*13", re.I),
    "apollo_1": re.compile(r"apollo[\s-]*(?:1|one)(?!\d)|as-?204", re.I),
    "mir_1997": re.compile(r"\bmir\b", re.I),
}
# Historical habitat presets ARE incidents: nearest_conditions attaches the incident's page.
HABITAT_CONTEXT = {"apollo1": ("apollo_1", "Apollo 1 cabin fire pure oxygen")}


def _passage(h: dict) -> dict:
    text = h["text"]
    if len(text) > MAX_PASSAGE_CHARS:
        text = text[:MAX_PASSAGE_CHARS] + " ..."
    pages = f"{h['page_start']}-{h['page_end']}" if h.get("page_start") else None
    return {"chunk_id": h["chunk_id"], "source_type": h["source_type"], "psi_id": h["psi_id"],
            "experiment": h["experiment"], "field": h["field"], "title": h["title"],
            "doi": h["doi"], "psi_doi": h["psi_doi"], "url": h["url"], "pages": pages,
            "score": h["score"], "text": text}


def _best_context(slug: str, query: str) -> dict | None:
    return next((h for h in rag.search(query, k=20, source_types=["context"]) if h["field"] == slug), None)


def search_docs(query: str, psi_ids: list[str] | None = None,
                source_types: list[str] | None = None, k: int = 5) -> dict:
    k = max(1, min(int(k), 10))
    hits = rag.search(query, k=k, psi_ids=psi_ids, source_types=source_types)
    if not psi_ids:
        for slug, pat in INCIDENT_DOCS.items():
            if pat.search(query) and not any(h["field"] == slug for h in hits):
                best = _best_context(slug, query)
                if best:
                    hits = hits[:k - 1] + [best]
    return {"query": query, "passages": [_passage(h) for h in hits]}


_PSI_RE = re.compile(r"^PSI-\d+$")


def get_investigation(psi_id: str) -> dict:
    pid = str(psi_id).strip().upper()
    if not _PSI_RE.match(pid):
        return {"error": f"psi_id must look like PSI-69, got {psi_id!r}"}
    con = connect()
    try:
        inv = con.execute("select * from investigations where psi_id = ?", [pid]).df()
        if inv.empty:
            ids = [r[0] for r in con.execute("select psi_id from investigations order by psi_id").fetchall()]
            return {"error": f"unknown psi_id {pid}; known: {ids}"}
        pubs = con.execute("""
            select title, doi, (abstract is not null and trim(abstract) <> '') as has_abstract
            from publications where psi_id = ? order by has_abstract desc, title limit 25
        """, [pid]).df()
        stats = con.execute("""
            select count(*) as n_rows,
                   count(*) filter (where extra->>'row_kind' is null) as n_single_tests,
                   min(pressure_kpa) as p_min_kpa, max(pressure_kpa) as p_max_kpa,
                   min(o2_frac) as o2_min, max(o2_frac) as o2_max
            from tests where psi_id = ?
        """, [pid]).df()
        fuels = con.execute("""
            select coalesce(fuel, material) as fuel, count(*) as n from tests
            where psi_id = ? and coalesce(fuel, material) is not null
            group by 1 order by n desc limit 15
        """, [pid]).fetchall()
        outcomes = con.execute("""
            select outcome, count(*) from tests
            where psi_id = ? and outcome is not null group by 1 order by 2 desc
        """, [pid]).fetchall()
    finally:
        con.close()

    rec = _records(inv)[0]
    for f in TEXT_FIELDS:
        v = rec.get(f)
        if isinstance(v, str) and len(v) > MAX_FIELD_CHARS:
            rec[f] = v[:MAX_FIELD_CHARS] + " ..."
    return {
        "investigation": rec,
        "cite_as": f"[{pid}] doi:{rec.get('doi')}" if rec.get("doi") else f"[{pid}]",
        "tests": {**_records(stats)[0],
                  "top_fuels": [{"fuel": f, "n": int(n)} for f, n in fuels],
                  "outcomes": {o: int(n) for o, n in outcomes}},
        "publications": _records(pubs),
    }


def nearest_conditions(habitat: str | None = None, pressure_kpa: float | None = None,
                       o2_frac: float | None = None, per_experiment: int = 2) -> dict:
    per_experiment = max(1, min(int(per_experiment), 5))
    if habitat:
        res = conditions.nearest_for_habitat(habitat, per_experiment)
    elif pressure_kpa is not None and o2_frac is not None:
        if o2_frac > 1:  # model sent percent
            return {"error": "o2_frac is a fraction (0.21 for 21%), not a percent"}
        res = conditions.nearest(float(pressure_kpa), float(o2_frac), per_experiment)
    else:
        return {"error": "give either habitat, or both pressure_kpa and o2_frac"}
    keep = ["test_id", "fuel", "material", "pressure_kpa", "o2_frac", "outcome",
            "burn_time_s", "row_kind", "distance"]
    for e in res["experiments"]:
        e["nearest"] = [{k: r[k] for k in keep} for r in e["nearest"]]
    if habitat in HABITAT_CONTEXT:
        slug, q = HABITAT_CONTEXT[habitat]
        best = _best_context(slug, q)
        if best:
            res["context"] = [_passage(best)]
    return res


# ---------------------------------------------------------------- tool specs

@functools.lru_cache(maxsize=1)
def _extra_keys() -> dict:
    """experiment -> sorted useful extra keys (ids, dates and free text hidden)."""
    con = connect()
    try:
        rows = con.execute("""
            select experiment, list_sort(list(distinct k))
            from (select experiment, unnest(json_keys(extra)) as k from tests)
            group by 1
        """).fetchall()
    finally:
        con.close()
    return {exp: [k for k in ks if k not in HIDDEN_KEYS] for exp, ks in rows}


@functools.lru_cache(maxsize=1)
def _query_tests_description() -> str:
    """Generated from the live schema. Holds NO data numbers (no row counts), so the model
    can't quote numbers from here: every data number must come from a query result."""
    con = connect()
    try:
        exps = con.execute("select experiment, psi_id from tests group by 1, 2 order by 2").fetchall()
        diluents = [d for (d,) in con.execute(
            "select distinct diluent from tests where diluent is not null order by 1").fetchall()]
        with_outcome = [e for (e,) in con.execute(
            "select distinct experiment from tests where outcome is not null order by 1").fetchall()]
    finally:
        con.close()
    keys = _extra_keys()
    exp_lines = "\n".join(f"- {exp} ({psi})" + (": " + ", ".join(keys[exp]) if keys.get(exp) else "")
                          for exp, psi in exps)
    return f"""Run one read-only DuckDB SELECT (WITH allowed) on ISS combustion tests. Results are capped at {MAX_ROWS} rows, so aggregate in SQL. On an error, read it and fix the query.

tests columns: test_pk, psi_id, experiment, test_id, fuel, material, pressure_kpa (kPa), o2_frac (ambient O2 as a fraction, 0.21 = 21%), diluent, diluent_frac, flow_cm_s, outcome, burn_time_s, spread_rate_mm_s, extra (JSON).

Rules:
- ppO2 in kPa = pressure_kpa * o2_frac. Inverse flames have o2_frac NULL; burner O2 is (extra->>'oxidizer_o2_frac')::DOUBLE.
- outcome is recorded only for {', '.join(with_outcome)}. FLEX droplets: extinction (went out before the fuel was used up), completion (droplet burned away), disruption (droplet broke apart). CFI-G gas jets: self_extinguished (went out on its own), flow_terminated (still burning when the fuel flow was stopped). no_ignition: never lit. NULL = not recorded, never "did not burn". For a share of flame behavior the denominator is outcome IS NOT NULL AND outcome <> 'no_ignition'. For a share per group (e.g. high vs low O2), each group's denominator is that group's rows: GROUP BY the group, or put the group condition in both the numerator and the denominator.
- Single tests only: extra->>'row_kind' IS NULL. Drop duplicates: coalesce(extra->>'is_duplicate', 'false') <> 'true'.
- When rows come from specific experiments, include experiment in the SELECT (and GROUP BY it) so every result can be cited to its investigation.
- diluent is the suppressant gas ({', '.join(repr(d) for d in diluents)}). Compare suppressants with GROUP BY diluent, never with the *_frac keys.
- extra keys are JSON fields, not columns: extra->>'key' for text, (extra->>'key')::DOUBLE for numbers.
- experiment names are exact and case-sensitive.

Experiments (psi_id) and their JSON fields in extra (read as extra->>'name', never as columns):
{exp_lines}

Other tables: investigations(psi_id, acronym, title, doi), publications(psi_id, title, doi), habitats(slug, name, pressure_kpa, o2_frac, pp_o2_kpa), insights(id, title, value, unit)."""


@functools.lru_cache(maxsize=1)
def _schema_hint() -> dict:
    """Returned with an unknown-column error so the model can fix the query in one retry."""
    con = connect()
    try:
        cols = {t: [c[0] for c in con.execute(f"describe {t}").fetchall()]
                for t in ("tests", "investigations", "publications", "habitats", "insights")}
    finally:
        con.close()
    return {"columns": cols, "extra_keys_by_experiment": _extra_keys(),
            "note": "extra keys are JSON fields, not columns: use extra->>'key' or (extra->>'key')::DOUBLE"}


@functools.lru_cache(maxsize=1)
def tool_specs() -> list[dict]:
    """Tool definitions (JSON Schema). Kept short: they are resent on every model call."""
    habitat_slugs = [h["slug"] for h in conditions.list_habitats()]
    return [
        {
            "name": "search_docs",
            "description": ("Search ISS combustion write-ups, paper abstracts, the Researcher's Guide to "
                            "ISS Combustion Science, and NASA pages on Apollo 1, Apollo 13 and the Mir fire. "
                            "For mechanisms and history, not test numbers. Passages carry cite_as."),
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "psi_ids": {"type": ["array", "null"], "items": {"type": "string"},
                                "description": "optional filter, e.g. [\"PSI-69\"]"},
                },
                "required": ["query"],
            },
        },
        {
            "name": "query_tests",
            "description": _query_tests_description(),
            "input_schema": {
                "type": "object",
                "properties": {"sql": {"type": "string"}},
                "required": ["sql"],
            },
        },
        {
            "name": "get_investigation",
            "description": "One investigation: title, DOI, objective, approach, test counts and ranges, outcomes, publications.",
            "input_schema": {
                "type": "object",
                "properties": {"psi_id": {"type": "string", "description": "e.g. PSI-69"}},
                "required": ["psi_id"],
            },
        },
        {
            "name": "nearest_conditions",
            "description": ("Tested conditions closest to a cabin atmosphere: give habitat, or pressure_kpa and "
                            "o2_frac. Returns a verdict (well_covered, sparse, near_only, untested) and the "
                            "nearest tests per experiment. Call it first for any habitat or atmosphere question. "
                            "Quote distances as given; never compute gaps or ratios from them."),
            "input_schema": {
                "type": "object",
                "properties": {
                    # nullable: some models send null for the arguments they don't use
                    "habitat": {"type": ["string", "null"], "enum": habitat_slugs + [None]},
                    "pressure_kpa": {"type": ["number", "null"]},
                    "o2_frac": {"type": ["number", "null"], "description": "fraction, 0.21 for 21%"},
                },
            },
        },
    ]


_DISPATCH = {
    "search_docs": search_docs,
    "query_tests": query_tests,
    "get_investigation": get_investigation,
    "nearest_conditions": nearest_conditions,
}


def run_tool(name: str, args: dict | None) -> dict:
    """Never raises: any failure comes back as {"error": ...} so the model can recover."""
    fn = _DISPATCH.get(name)
    if fn is None:
        return {"error": f"unknown tool {name!r}; tools: {list(_DISPATCH)}"}
    try:
        return fn(**(args or {}))
    except TypeError as e:
        return {"error": f"bad arguments for {name}: {e}"}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


# ---------------------------------------------------------------- self-test

def _selftest() -> bool:
    ok = True

    def check(label, cond, detail=""):
        nonlocal ok
        ok &= bool(cond)
        print(f"  {'PASS' if cond else 'FAIL'}  {label}{'  -> ' + detail if detail else ''}")

    print("allowed queries")
    r = run_tool("query_tests", {"sql": "select count(*) as n from tests"})
    check("count(*) = 1999", r.get("rows") == [[1999]], str(r.get("rows") or r.get("error")))
    r = run_tool("query_tests", {"sql": "with t as (select experiment, count(*) n from tests group by 1) "
                                        "select * from t order by n desc;"})
    check("CTE + trailing semicolon", "rows" in r and r["row_count"] > 5, str(r.get("error", r.get("row_count"))))
    r = run_tool("query_tests", {"sql": "select * from tests"})
    check("row cap 200 + truncated flag", r.get("row_count") == 200 and r.get("truncated") is True,
          f"{r.get('row_count')} rows, truncated={r.get('truncated')}")
    r = run_tool("query_tests", {"sql": "select extra->>'row_kind' as k, count(*) from tests group by 1"})
    check("JSON operator works", "rows" in r, str(r.get("error", r.get("rows"))))
    r = run_tool("query_tests", {"sql": "select flow_direction, burn_time_s from tests "
                                        "where experiment = 'SAFFIRE-I' and flow_direction is not null"})
    check("auto-fix text key used as column", r.get("row_count") == 2 and r.get("auto_fixed"),
          f"{r.get('auto_fixed')} rows={r.get('rows') or r.get('error')}")
    r = run_tool("query_tests", {"sql": "select avg(thickness_cm) as t from tests where experiment = 'SAFFIRE-I'"})
    check("auto-fix numeric key (TRY_CAST)", "rows" in r and r.get("auto_fixed"),
          f"{r.get('auto_fixed')} rows={r.get('rows') or r.get('error')}")
    r = run_tool("query_tests", {"sql": "select no_such_thing from tests"})
    check("unknown non-key column still errors with hint", "error" in r and "hint" in r)
    r = run_tool("query_tests", {"sql": "SELECT COUNT(*) AS cnt FROM tests WHERE material='Kapton'"})
    check("provenance attached to an untagged count", "provenance" in r
          and {row[1] for row in r["provenance"]["rows"]} == {"PSI-101", "PSI-102"},
          str(r.get("provenance")))
    r = run_tool("query_tests", {"sql": "select experiment, count(*) from tests group by 1"})
    check("no provenance when experiment is already a column", "provenance" not in r)

    print("rejected queries (each must return an error)")
    bad = [
        "delete from tests",
        "drop table tests",
        "insert into tests (psi_id) values ('x')",
        "create table x as select 1",
        "update tests set fuel = 'x'",
        "select 1; select 2",
        "select 1; drop table tests",
        "copy (select 1) to '/tmp/flamescope_leak.csv'",
        "select * from read_csv('/etc/hosts')",
        "select * from read_text('/etc/hosts')",
        "attach '/tmp/x.duckdb' as x",
        "install httpfs",
        "set threads = 1",
        "pragma version",
        "select * from tests where",
        "",
    ]
    for sql in bad:
        r = run_tool("query_tests", {"sql": sql})
        check(f"{sql[:55]!r}", "error" in r, (r.get("error") or "NO ERROR")[:90])

    print("other tools")
    r = run_tool("search_docs", {"query": "cool flames of heptane droplets", "k": 3})
    check("search_docs returns 3 passages", len(r.get("passages", [])) == 3,
          ", ".join(f"{p['psi_id'] or p['field']}:{p['score']}" for p in r.get("passages", [])))
    r = run_tool("search_docs", {"query": "smoke", "psi_ids": ["psi-101"], "k": 2})
    check("search_docs psi filter (lowercase id)", all(p["psi_id"] == "PSI-101" for p in r.get("passages", [])) and r.get("passages"),
          str([p["psi_id"] for p in r.get("passages", [])]))
    r = run_tool("get_investigation", {"psi_id": "psi-69"})
    inv = r.get("investigation", {})
    check("get_investigation PSI-69", inv.get("doi") == "10.60555/mbq8-0451",
          f"{inv.get('acronym')} doi={inv.get('doi')} tests={r.get('tests', {}).get('n_rows')} "
          f"outcomes={r.get('tests', {}).get('outcomes')} pubs={len(r.get('publications', []))}")
    r = run_tool("get_investigation", {"psi_id": "PSI-999"})
    check("get_investigation unknown id -> error", "error" in r)
    r = run_tool("nearest_conditions", {"habitat": "lunar"})
    check("nearest_conditions lunar -> sparse, 11", r.get("summary", {}).get("verdict") == "sparse"
          and r["summary"]["n_in_box"] == 11, str(r.get("summary", r.get("error"))))
    r = run_tool("nearest_conditions", {"pressure_kpa": 70, "o2_frac": 30})
    check("nearest_conditions percent -> error", "error" in r)
    r = run_tool("no_such_tool", {})
    check("unknown tool -> error", "error" in r)
    r = run_tool("query_tests", {"sqll": "select 1"})
    check("bad argument name -> error", "error" in r, r.get("error", "")[:80])

    print("specs")
    specs = tool_specs()
    check("4 tool specs", [s["name"] for s in specs] ==
          ["search_docs", "query_tests", "get_investigation", "nearest_conditions"])
    desc = specs[1]["description"]
    check("query_tests description lists experiments", "FLEX" in desc and "PSI-69" in desc,
          f"{len(desc)} chars")
    check("to_text caps size", len(to_text({"x": "a" * 50000})) < MAX_RESULT_CHARS + 100)
    return ok


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="ignitiq.tools")
    ap.add_argument("--specs", action="store_true", help="print the tool descriptions")
    args = ap.parse_args(argv)
    if args.specs:
        for s in tool_specs():
            print(f"\n=== {s['name']} ===\n{s['description']}")
        return
    print("TOOLS: PASS" if _selftest() else "TOOLS: FAIL")


if __name__ == "__main__":
    main()