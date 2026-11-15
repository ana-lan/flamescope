"""Phase 3 check v2: the evidence suite behind docs/phase3_check.md.

Parts (results saved per part in eval/phase3_results.json; report + demo cache rebuilt from them):
    offline    verifier negative tests + SQL safety      (in-process, no LLM, no server)
    api        API contract against api/schemas.py      (server on :8000)
    questions  6 questions x --runs, fresh, plus the out-of-scope question  (server; LLM)
    sse        SSE contract: live, cached, forced failure (server; 1 LLM run)
    report     rebuild docs/phase3_check.md and data/processed/demo_cache.json only

Run from backend/ with the server up:
    uv run python -m api.check --part offline api
    uv run python -m api.check --part questions sse          # ~22 min: runs spaced for Groq's per-minute limit
    uv run python -m api.check --part questions --only 5     # rerun one question, results merge
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import re
import statistics
import time

import httpx
from pydantic import TypeAdapter, ValidationError

from api.main import CACHE_PATH, app, cache_key
from api.schemas import AskFinal, Coverage, Habitat, Health, Insight, InvestigationDetail, TestsPage
from flamescope import agent, tools
from flamescope.rag import BACKEND

API = os.getenv("API_URL", "http://localhost:8000")
RESULTS = BACKEND / "eval" / "phase3_results.json"
REPORT = BACKEND.parent / "docs" / "phase3_check.md"
P95_TARGET_S = 15.0
STEP_EVENTS = {"start", "status", "tool_call", "tool_result"}

NOT_COVERED = ["not cover", "doesn't cover", "does not cover", "no data", "no test", "not tested", "untested",
               "outside", "not in the data", "no kapton", "lowest", "below the", "cannot", "can't",
               "not available", "no record", "not include"]

QUESTIONS = [
    {"id": 1, "habitat": None,
     "question": "How many FLEX tests ended in extinction, and over what O2 range?",
     "numbers": ["186", ("12", "0.12"), ("30", "0.30", "0.3")], "cites": ["PSI-69"],
     "source": "tests table: FLEX outcome = extinction (186), o2_frac 0.12 to 0.30"},
    {"id": 2, "habitat": None,
     "question": "In FLEX, what percentage of droplet tests ended in extinction with each suppressant gas: "
                 "CO2, nitrogen and helium?",
     "numbers": ["90", "75", "66"], "cites": ["PSI-69"],
     "source": "insight flex_diluent_extinction"},
    {"id": 3, "habitat": None,
     "question": "How long did the concurrent and opposed flow fires burn in SAFFIRE-I?",
     "numbers": ["420", "70"], "cites": ["PSI-98"],
     "source": "insight saffire_flow_direction"},
    {"id": 4, "habitat": "lunar",
     "question": "How much test data covers this habitat, and what happened to the flames there?",
     "numbers": [("11", "eleven")], "cites": ["PSI-159"], "mentions_any": ["sparse"],
     "source": "insight coverage_gap and /coverage?habitat=lunar"},
    {"id": 5, "habitat": None,  # no habitat: lunar's 34% O2 must not satisfy the "34" check by accident
     "question": "In CFI-G, what share of flames kept burning until the fuel flow was stopped at 30% O2 "
                 "or more, compared with below 25%?",
     "numbers": [("34", "33.7", "0.337")], "cites": ["PSI-159"], "sql_contains": ["flow_terminated"],
     "source": "insight cfig_high_o2_persistence (31 of 92 ignited flames)"},
    {"id": 6, "habitat": "apollo1",
     "question": "Could the test data tell us how the Apollo 1 cabin fire would have behaved?",
     "numbers": [], "cites": [], "cites_any": ["NASA:apollo_1"], "mentions_any": NOT_COVERED,
     "source": "/coverage?habitat=apollo1 (untested, nearest 20 box widths) and the Apollo 1 NASA page"},
    {"id": 7, "habitat": None, "out_of_scope": True,
     "question": "How flammable is Kapton at 5% O2 on Mars?",
     "numbers": [], "cites": [], "mentions_any": NOT_COVERED,
     # Kapton IS in the data: heated in the SAME / SAME-R smoke tests, never burned for flammability.
     # The agent must look it up (SQL) and say so, not claim it was never tested.
     "sql_contains": ["kapton"], "cites_any": ["PSI-101", "PSI-102"],
     "source": "Kapton only in SAME-R (29) and SAME (1) smoke tests; nothing near 5% O2; no Martian gravity tests"},
]
STABILITY_IDS = [1, 2, 3, 4, 5, 6]


# ---------------------------------------------------------------- results file

def write_atomic(path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


def load_results() -> dict:
    data = json.loads(RESULTS.read_text()) if RESULTS.exists() else {}
    if "runs" not in data:  # v1 format: start fresh
        data = {}
    data.setdefault("runs", {})
    data.setdefault("meta", {})
    return data


def save(results: dict) -> None:
    write_atomic(RESULTS, json.dumps(results, indent=1, default=str))


def _add(out: list, label: str, ok, detail="") -> None:
    out.append({"label": label, "ok": bool(ok), "detail": detail if isinstance(detail, str) else json.dumps(detail, default=str)[:400]})


def _print(title: str, items: list) -> None:
    print(f"\n{title}")
    for c in items:
        print(f"  {'PASS' if c['ok'] else 'FAIL'}  {c['label']}{'  -> ' + c['detail'] if c['detail'] else ''}")


# ---------------------------------------------------------------- offline: verifier

def verifier_tests() -> list:
    tr = agent._new_trace()
    agent._add_source(tr, "sql", {"PSI-98"},
                      {"columns": ["flow_dir", "burn_s"], "rows": [["concurrent", 420.0], ["opposed", 70.0]]})
    agent._add_source(tr, "sql", {"PSI-159"}, {"columns": ["share_pct"], "rows": [[33.7]]})
    agent._add_source(tr, "nearest_conditions", set(), {"target": {"o2_frac": 0.21, "pressure_kpa": 3.5}})
    tr["tool_texts"].append("'SAFFIRE-I' PSI-98 'CFI-G' PSI-159")
    question = "How did the flames behave?"

    def g(ans: str) -> dict:
        return agent._grounding(agent._norm_answer(ans), tr, question)

    def cit(ans: str) -> list:
        return agent._citations(agent._norm_answer(ans), tr)

    out = []
    r = g("The concurrent fire burned for 812 s [PSI-98].")
    _add(out, "NEGATIVE: invented '812 s' is flagged unverified", "812" in r["unverified"] and not r["ok"],
         {"unverified": r["unverified"]})
    r = g("The concurrent fire burned for 420 s [PSI-98].")
    _add(out, "control: real '420 s' cited to PSI-98 passes", r["ok"],
         [(n["value"], n["source"]) for n in r["numbers"]])
    c = cit("It burned for 420 s [PSI-999].")
    _add(out, "NEGATIVE: [PSI-999] is not a verified citation",
         len(c) == 1 and not c[0]["verified"] and not c[0]["known"], c)
    c = cit("It burned for 420 s [PSI-98].")
    _add(out, "control: [PSI-98] is a verified citation", len(c) == 1 and c[0]["verified"], c)
    r = g("34% of CFI-G flames kept burning until the flow stopped [PSI-69].")
    _add(out, "NEGATIVE: a CFI-G number cited to [PSI-69] is misattributed",
         "34" in r["misattributed"] and not r["ok"], {"misattributed": r["misattributed"]})
    r = g("34% of CFI-G flames kept burning until the flow stopped [PSI-159].")
    _add(out, "control: same number cited to PSI-159 passes (33.7 rounds to 34)", r["ok"],
         [(n["value"], n["source"]) for n in r["numbers"]])
    r = g("The cabin air was 21% O2.")
    _add(out, "control: fraction 0.21 verifies '21%'", r["ok"], [(n["value"], n["source"]) for n in r["numbers"]])
    r = g("The chamber was at 350 kPa.")
    _add(out, "NEGATIVE: x100 of a non-fraction (3.5 -> 350) is not allowed", "350" in r["unverified"],
         {"unverified": r["unverified"]})
    r = g("Public since 2009, doi:10.60555/mbq8-0451 [PSI-69].")
    _add(out, "years, DOIs and PSI ids are not checked as claims",
         r["ok"] and [n["value"] for n in r["numbers"]] == ["2009"], [(n["value"], n["source"]) for n in r["numbers"]])
    r = g("Burned for 420 s [PSI\u201198].")
    c = cit("Burned for 420 s [PSI\u201198].")
    _add(out, "non-breaking hyphen citation [PSI\u201198] parses and verifies",
         r["ok"] and len(c) == 1 and c[0]["id"] == "PSI-98" and c[0]["verified"], c)
    r = g("1. First point\n2. Burned for 420 s [PSI-98].")
    _add(out, "list markers '1.' '2.' are not checked as numbers", r["ok"] and r["numbers_checked"] == 1,
         [n["value"] for n in r["numbers"]])
    return out


# ---------------------------------------------------------------- offline: SQL safety

def sql_safety_tests() -> list:
    out = []
    bad = [
        ("DROP", "drop table tests"),
        ("DELETE", "delete from tests"),
        ("UPDATE", "update tests set fuel = 'x'"),
        ("INSERT", "insert into tests (psi_id) values ('x')"),
        ("ATTACH", "attach '/tmp/flamescope_x.duckdb' as x"),
        ("COPY", "copy (select 1) to '/tmp/flamescope_leak.csv'"),
        ("PRAGMA", "pragma version"),
        ("second statement after ;", "select 1; drop table tests"),
        ("file read inside a SELECT", "select * from read_csv('/etc/hosts')"),
    ]
    for label, sql in bad:
        r = tools.query_tests(sql)
        _add(out, f"rejected: {label}", "error" in r, (r.get("error") or "NO ERROR")[:110])
    r = tools.query_tests("select * from tests")
    _add(out, "SELECT * FROM tests returns at most 200 rows and says it was capped",
         r.get("row_count") == 200 and r.get("truncated") is True,
         f"row_count={r.get('row_count')} truncated={r.get('truncated')}")
    _add(out, "query timeout is 10 s", tools.QUERY_TIMEOUT_S == 10, f"QUERY_TIMEOUT_S={tools.QUERY_TIMEOUT_S}")
    t0 = time.time()
    r = tools.query_tests("select sum(a.range * b.range) as s from range(200000) a, range(200000) b")
    dt = time.time() - t0
    _add(out, "a runaway query (4e10-row cross join) is interrupted at the timeout",
         "exceeded" in (r.get("error") or "") and dt < tools.QUERY_TIMEOUT_S + 5,
         f"{dt:.1f}s: {(r.get('error') or 'NO ERROR')[:60]}")
    r = tools.query_tests("select count(*) from tests")
    _add(out, "data unchanged afterwards (1999 rows)", r.get("rows") == [[1999]], str(r.get("rows")))
    return out


# ---------------------------------------------------------------- api contract

def api_contract(client: httpx.Client) -> list:
    out = []
    cases = [
        ("GET /health", "/health", None, Health),
        ("GET /habitats", "/habitats", None, list[Habitat]),
        ("GET /insights?habitat=lunar", "/insights", {"habitat": "lunar"}, list[Insight]),
        ("GET /tests?experiment=FLEX", "/tests", {"experiment": "FLEX"}, TestsPage),
        ("GET /investigations/PSI-69", "/investigations/PSI-69", None, InvestigationDetail),
        ("GET /coverage?habitat=lunar", "/coverage", {"habitat": "lunar"}, Coverage),
    ]
    for label, path, params, model in cases:
        r = client.get(f"{API}{path}", params=params, timeout=60)
        try:
            TypeAdapter(model).validate_python(r.json())
            _add(out, f"{label}: 200 and matches its schema", r.status_code == 200, f"HTTP {r.status_code}")
        except (ValidationError, ValueError) as e:
            _add(out, f"{label}: 200 and matches its schema", False, str(e)[:300])
    r = client.get(f"{API}/investigations/PSI-999", timeout=30)
    _add(out, "unknown psi_id -> 404", r.status_code == 404, f"HTTP {r.status_code}")
    r = client.get(f"{API}/coverage", params={"habitat": "mars"}, timeout=30)
    _add(out, "unknown habitat -> 422", r.status_code == 422, f"HTTP {r.status_code}")
    r = client.options(f"{API}/habitats", timeout=30,
                       headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET"})
    _add(out, "CORS preflight allows http://localhost:3000",
         r.headers.get("access-control-allow-origin") == "http://localhost:3000",
         f"allow-origin={r.headers.get('access-control-allow-origin')}")
    r = client.get(f"{API}/habitats", headers={"Origin": "http://localhost:3000"}, timeout=30)
    _add(out, "CORS header present on a real GET from http://localhost:3000",
         r.headers.get("access-control-allow-origin") == "http://localhost:3000",
         f"allow-origin={r.headers.get('access-control-allow-origin')}")
    return out


# ---------------------------------------------------------------- sse contract

def parse_sse(lines: list[str]) -> list[tuple[str, dict | None]]:
    events, cur = [], {}
    for line in lines:
        if line.startswith(":"):  # ping comment
            continue
        if not line.strip():
            if cur:
                events.append(cur)
                cur = {}
            continue
        field, _, value = line.partition(":")
        value = value[1:] if value.startswith(" ") else value
        if field == "event":
            cur["event"] = value
        elif field == "data":
            cur["data"] = cur.get("data", "") + value
    if cur:
        events.append(cur)
    return [(e.get("event", "message"), json.loads(e["data"]) if e.get("data") else None) for e in events]


def _order(names: list[str]) -> str:
    out = []
    for n in names:
        if out and out[-1][0] == n:
            out[-1][1] += 1
        else:
            out.append([n, 1])
    return " > ".join(f"{n}x{k}" if k > 1 else n for n, k in out)


def sse_checks(events: list, expect: str, label: str) -> list:
    out, names = [], [n for n, _ in events]
    _add(out, f"{label}: first event is start", names[:1] == ["start"], _order(names))
    if expect == "error":
        _add(out, f"{label}: exactly one error event", names.count("error") == 1)
        _add(out, f"{label}: error is the last event (stream closed cleanly)", names[-1:] == ["error"])
        _add(out, f"{label}: no token or final events", "token" not in names and "final" not in names)
        err = next((d for n, d in events if n == "error"), {}) or {}
        _add(out, f"{label}: error carries a user-facing message", bool(err.get("message")), err.get("message", ""))
        return out
    _add(out, f"{label}: exactly one final event", names.count("final") == 1, f"{names.count('final')} final")
    _add(out, f"{label}: final is the last event, no error", names[-1:] == ["final"] and "error" not in names)
    tok = [i for i, n in enumerate(names) if n == "token"]
    steps = [i for i, n in enumerate(names) if n in STEP_EVENTS]
    fin = names.index("final") if "final" in names else -1
    _add(out, f"{label}: order is step events, then tokens, then final",
         bool(tok) and bool(steps) and max(steps) < min(tok) and max(tok) < fin
         and set(names) <= STEP_EVENTS | {"token", "final"}, _order(names))
    final = events[fin][1] if fin >= 0 else {}
    joined = "".join(d["text"] for n, d in events if n == "token")
    _add(out, f"{label}: concatenated tokens == final.answer", joined == final.get("answer"),
         f"{len(joined)} vs {len(final.get('answer') or '')} chars")
    try:
        AskFinal.model_validate(final)
        _add(out, f"{label}: final matches the AskFinal schema", True)
    except ValidationError as e:
        _add(out, f"{label}: final matches the AskFinal schema", False, str(e)[:300])
    _add(out, f"{label}: final has answer, citations, sql_run, passages",
         all(k in final for k in ("answer", "citations", "sql_run", "passages")))
    _add(out, f"{label}: final.cached is {expect == 'cached'}", final.get("cached") is (expect == "cached"),
         f"cached={final.get('cached')}")
    return out


def stream_lines(client: httpx.Client, body: dict) -> tuple[int, list[str]]:
    with client.stream("POST", f"{API}/ask", json=body, timeout=300) as r:
        return r.status_code, list(r.iter_lines())


async def _forced_failure_lines() -> tuple[int, list[str]]:
    """In-process (ASGITransport): the env switch never has to exist on the real server."""
    os.environ[agent.FORCE_FAIL_ENV] = "1"
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://in-process") as c:
            async with c.stream("POST", "/ask", timeout=60,
                                json={"question": "How many FLEX tests ended in extinction?", "fresh": True}) as r:
                return r.status_code, [line async for line in r.aiter_lines()]
    finally:
        os.environ.pop(agent.FORCE_FAIL_ENV, None)


def sse_contract(client: httpx.Client, gap: float) -> list:
    out = []
    q = next(q for q in QUESTIONS if q["id"] == 3)
    print(f"  live stream (fresh) after a {gap:.0f}s gap ...")
    time.sleep(gap)
    status, lines = stream_lines(client, {"question": q["question"], "habitat": q["habitat"], "fresh": True})
    _add(out, "live: HTTP 200", status == 200, f"HTTP {status}")
    out += sse_checks(parse_sse(lines), "live", "live")

    cache = json.loads(CACHE_PATH.read_text()) if CACHE_PATH.exists() else {}
    entry = cache.get(cache_key(q["question"], q["habitat"])) or next(iter(cache.values()), None)
    if entry:
        status, lines = stream_lines(client, {"question": entry["question"], "habitat": entry.get("habitat")})
        _add(out, "cached: HTTP 200", status == 200, f"HTTP {status}")
        out += sse_checks(parse_sse(lines), "cached", "cached")
    else:
        _add(out, "cached: a cache entry exists to replay", False, "run --part questions first")

    status, lines = asyncio.run(_forced_failure_lines())
    _add(out, "forced failure: HTTP 200 stream", status == 200, f"HTTP {status}")
    out += sse_checks(parse_sse(lines), "error", "forced failure")
    return out


# ---------------------------------------------------------------- questions

def score(q: dict, res: dict) -> list:
    """Correctness checks (failover is tracked separately)."""
    out = []
    if "error" in res:
        _add(out, "request succeeded", False, res["error"])
        return out
    ans = (res.get("answer") or "").translate(agent._DASHES)
    low = ans.lower()
    cits = res.get("citations") or []
    verified = {c["id"] for c in cits if c.get("verified")}
    g = res.get("grounding") or {}
    for n in q.get("numbers", []):
        forms = n if isinstance(n, (tuple, list)) else (n,)  # e.g. percent or fraction form
        _add(out, f"mentions {' or '.join(forms)}",
             any(re.search(rf"(?<![\d.\w]){re.escape(f)}(?![\d\w])", ans, re.I) for f in forms))
    for c in q.get("cites", []):
        _add(out, f"cites {c} (verified)", c in verified)
    sqls = " ".join((s.get("sql") or "") for s in res.get("sql_run") or []).lower()
    for frag in q.get("sql_contains", []):
        _add(out, f"SQL uses {frag}", frag.lower() in sqls)
    if q.get("cites_any"):
        _add(out, f"cites one of {q['cites_any']}", verified & set(q["cites_any"]))
    if q.get("mentions_any"):
        _add(out, "says the data does not cover it" if q["mentions_any"] is NOT_COVERED else
             f"says one of {q['mentions_any']}", any(m in low for m in q["mentions_any"]))
    if not q.get("out_of_scope"):
        _add(out, "has a verified citation", verified)
    _add(out, "every citation verified", all(c.get("verified") for c in cits),
         [c["id"] for c in cits if not c.get("verified")] or "")
    _add(out, "no unverified numbers", not g.get("unverified"), g.get("unverified") or "")
    _add(out, "numbers match their citations", not g.get("misattributed"), g.get("misattributed") or "")
    _add(out, "answer not cut off", not res.get("answer_truncated"))
    return out


def ask_json(client: httpx.Client, q: dict) -> tuple[dict, float]:
    t0 = time.time()
    r = client.post(f"{API}/ask", timeout=300, json={
        "question": q["question"], "habitat": q["habitat"], "stream": False, "fresh": True})
    wall = round(time.time() - t0, 2)
    if r.status_code != 200:
        return {"error": f"HTTP {r.status_code}: {r.text[:200]}"}, wall
    return r.json(), wall


def run_questions(client: httpx.Client, results: dict, only: list | None, runs: int, gap: float) -> None:
    qs = [q for q in QUESTIONS if not only or q["id"] in only]
    for q in qs:
        results["runs"][str(q["id"])] = []
    plan = [(rnd, q) for rnd in range(runs) for q in qs if not (q.get("out_of_scope") and rnd > 0)]
    print(f"\n{len(plan)} runs, {gap:.0f}s apart: about {len(plan) * (gap + 3) / 60:.0f} min")
    for k, (rnd, q) in enumerate(plan):
        if k:
            time.sleep(gap)
        res, wall = ask_json(client, q)
        checks = score(q, res)
        rec = {"ran_at": time.strftime("%Y-%m-%d %H:%M:%S"), "round": rnd + 1, "wall_s": wall,
               "passed": all(c["ok"] for c in checks), "failover": bool(res.get("models_failed")),
               "checks": checks, "result": res}
        results["runs"][str(q["id"])].append(rec)
        save(results)
        fails = [c["label"] for c in checks if not c["ok"]]
        print(f"  [{k + 1}/{len(plan)}] Q{q['id']} round {rnd + 1}: {'PASS' if rec['passed'] else 'FAIL'} "
              f"{wall}s model={res.get('model')} failover={rec['failover']}"
              + (f"  failed: {fails}" if fails else ""))


# ---------------------------------------------------------------- cache + report

def build_cache(results: dict) -> int:
    cache = {}
    for q in QUESTIONS:
        good = [r for r in results["runs"].get(str(q["id"]), []) if r["passed"] and not r["failover"]]
        if good:
            final = {k: v for k, v in good[-1]["result"].items() if k != "cached"}
            cache[cache_key(q["question"], q["habitat"])] = {**final, "cached_at": good[-1]["ran_at"]}
    write_atomic(CACHE_PATH, json.dumps(cache, indent=1, default=str))
    return len(cache)


def pct(vals: list[float], p: float) -> float | None:
    if not vals:
        return None
    s = sorted(vals)
    return s[max(0, math.ceil(p / 100 * len(s)) - 1)]


def stability(results: dict) -> dict:
    runs = [r for i in STABILITY_IDS for r in results["runs"].get(str(i), [])]
    walls = [r["wall_s"] for r in runs]
    return {"n": len(runs), "passed": sum(r["passed"] for r in runs),
            "failovers": sum(r["failover"] for r in runs),
            "p50": pct(walls, 50), "p95": pct(walls, 95)}


def _count(items: list) -> str:
    return f"{sum(c['ok'] for c in items)}/{len(items)}" if items else "not run"


def _table(items: list) -> list[str]:
    rows = ["| Check | Result | Detail |", "| --- | --- | --- |"]
    for c in items:
        detail = (c["detail"] or "").replace("|", "\\|").replace("\n", " ")
        rows.append(f"| {c['label']} | {'PASS' if c['ok'] else 'FAIL'} | {detail} |")
    return rows


KNOWN_LIMITATIONS = [
    "Adversarial out-of-scope question (Q7, Kapton at 5% O2 on Mars) failed 3 of 3 attempts. The agent "
    "correctly says the data does not cover the conditions, but adds unsupported detail: an invented pressure "
    "range, a computed 'gap' figure, or a citation to CFI instead of the SAME/SAME-R smoke tests where Kapton "
    "actually appears. Every attempt was flagged by the verifier (unverified or misattributed numbers) or by the "
    "fact-level check. Mitigations in place: provenance on untagged SQL, cite_as on every result. The UI shows "
    "grounding.ok = false as a warning.",
    "Number verification matches by value, so a small round number can coincide with an unrelated value in a "
    "source carrying the same citation (e.g. '30 Kapton tests' vs '30% ethane'). Fact-level eval checks catch "
    "these; the verifier alone cannot.",
    "Groq free tier: 8,000 tokens per minute and 200,000 per day on gpt-oss-120b (about 40 questions a day). "
    "Latency here was measured with runs spaced 65 s apart; questions asked within the same minute can wait "
    "for capacity or fail over. Suggested questions replay from the checked demo cache at zero token cost.",
]


def write_report(results: dict) -> None:
    meta = results["meta"]
    st = stability(results)
    oos = results["runs"].get("7", [])
    oos_ok = bool(oos) and all(r["passed"] for r in oos)
    p95_ok = st["p95"] is not None and st["p95"] < P95_TARGET_S
    L = ["# Phase 3 check", "",
         f"Generated {time.strftime('%Y-%m-%d %H:%M')} against `{API}`. LLM runs used `fresh: true` (no cache) "
         f"and were spaced {meta.get('gap', '?')} s apart: Groq's free tier allows 8,000 tokens per minute and one "
         "question uses about 4,000 to 5,000. Latency is wall-clock time per question as the client sees it, "
         "excluding the gaps.", "",
         "## Done-when", "",
         "| Requirement | Result |", "| --- | --- |",
         f"| Verifier negative tests (with controls) | {_count(results.get('verifier', []))} |",
         f"| SQL safety | {_count(results.get('sql_safety', []))} |",
         f"| API contract | {_count(results.get('api', []))} |",
         f"| SSE contract: live, cached, forced failure | {_count(results.get('sse', []))} |",
         f"| Stability: {st['n']} runs correct | {st['passed']}/{st['n']} |",
         f"| No failover on the 6 questions | {st['failovers']} failovers |",
         f"| p95 latency under {P95_TARGET_S:.0f} s | p95 {st['p95']} s, p50 {st['p50']} s "
         f"{'(PASS)' if p95_ok else '(FAIL)'} |",
         f"| Out-of-scope question | {'PASS' if oos_ok else ('FAIL' if oos else 'not run')} |", ""]

    L += ["## Known limitations", ""] + [f"- {x}" for x in KNOWN_LIMITATIONS] + [""]
    for key, title in (("verifier", "Verifier negative tests"), ("sql_safety", "SQL safety"),                       ("api", "API contract"), ("sse", "SSE contract")):
        L += [f"## {title}", ""] + (_table(results[key]) if results.get(key) else ["Not run."]) + [""]

    L += ["## Stability", "", "| # | Question | Correct | Failovers | p50 s | max s |",
          "| --- | --- | --- | --- | --- | --- |"]
    for q in QUESTIONS:
        rs = results["runs"].get(str(q["id"]), [])
        if not rs:
            continue
        walls = [r["wall_s"] for r in rs]
        L.append(f"| {q['id']} | {q['question']} | {sum(r['passed'] for r in rs)}/{len(rs)} | "
                 f"{sum(r['failover'] for r in rs)} | {statistics.median(walls):.2f} | {max(walls):.2f} |")
    L += ["", "### Every run", "", "| Q | Round | Result | Wall s | Model | LLM calls | Prompt tokens | Failover | Failed checks |",
          "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for q in QUESTIONS:
        for r in results["runs"].get(str(q["id"]), []):
            res = r["result"]
            fails = "; ".join(c["label"] for c in r["checks"] if not c["ok"])
            L.append(f"| {q['id']} | {r['round']} | {'PASS' if r['passed'] else 'FAIL'} | {r['wall_s']} | "
                     f"`{res.get('model')}` | {res.get('llm_calls')} | {(res.get('usage') or {}).get('prompt_tokens')} | "
                     f"{', '.join(f['model'] + ' ' + f['error'] + (' ' + str(f.get('kind')) if f.get('kind') else '') for f in res.get('models_failed') or []) or 'none'} | "
                     f"{fails} |")

    L += ["", "## Latest answer per question", ""]
    for q in QUESTIONS:
        rs = results["runs"].get(str(q["id"]), [])
        if not rs:
            continue
        r = rs[-1]
        res = r["result"]
        L += [f"### {q['id']}. {q['question']}", "",
              f"Habitat: {q['habitat'] or 'none'}. Expected source: {q['source']}.", ""]
        if "error" in res:
            L += [f"Error: {res['error']}", ""]
            continue
        L += [f"> {ln}" if ln else ">" for ln in res["answer"].splitlines()] + [""]
        L += ["| Number | Cited | Source | OK |", "| --- | --- | --- | --- |"]
        for n in (res.get("grounding") or {}).get("numbers", []):
            L.append(f"| {n['value']} | {', '.join(n['cited']) or '-'} | {n['source'] or 'NO SOURCE'} | "
                     f"{'yes' if n['ok'] else 'NO'} |")
        L += ["", "Citations: " + (", ".join(f"{c['id']} ({c['label']}{', doi:' + c['doi'] if c.get('doi') else ''})"
                                             f"{'' if c['verified'] else ' UNVERIFIED'}" for c in res["citations"]) or "none"), ""]
        for i, s in enumerate(res.get("sql_run") or [], 1):
            L += [f"SQL {i}: {s.get('row_count')} rows"
                  + (f", auto-fixed {s['auto_fixed']}" if s.get("auto_fixed") else "")
                  + (f", error: {s['error'][:120]}" if s.get("error") else ""), "", "```sql", s.get("sql") or "", "```", ""]
        L += ["LLM calls:", ""]
        for c in res.get("llm_trace") or []:
            lim = f" {c['kind']} used {c.get('used')}/{c.get('limit')} requested {c.get('requested')}" if c.get("kind") else ""
            L.append(f"- `{c['model']}`: {'ok' if c['ok'] else c.get('error')}, prompt {c.get('prompt_tokens')} "
                     f"(est {c.get('est_prompt_tokens')}), {c.get('latency_s')} s{lim}")
        L.append("")
    write_atomic(REPORT, "\n".join(L) + "\n")


def summary(results: dict) -> bool:
    st = stability(results)
    parts_ok = all(results.get(k) and all(c["ok"] for c in results[k])
                   for k in ("verifier", "sql_safety", "api", "sse"))
    oos = results["runs"].get("7", [])
    done = (parts_ok and st["n"] >= 18 and st["passed"] == st["n"] and st["failovers"] == 0
            and st["p95"] is not None and st["p95"] < P95_TARGET_S and oos and all(r["passed"] for r in oos))
    print(f"\nverifier {_count(results.get('verifier', []))} | sql {_count(results.get('sql_safety', []))} | "
          f"api {_count(results.get('api', []))} | sse {_count(results.get('sse', []))} | "
          f"stability {st['passed']}/{st['n']} | failovers {st['failovers']} | p50 {st['p50']} s | p95 {st['p95']} s | "
          f"out-of-scope {'PASS' if oos and all(r['passed'] for r in oos) else 'FAIL' if oos else 'not run'}")
    print(f"PHASE 3 CHECK: {'PASS' if done else 'NOT YET'}")
    return done


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="api.check")
    ap.add_argument("--part", nargs="+", default=["offline", "api", "questions", "sse"],
                    choices=["offline", "api", "questions", "sse", "report"])
    ap.add_argument("--only", type=int, nargs="*", help="question ids (questions part)")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--gap", type=float, default=65, help="seconds between LLM runs")
    args = ap.parse_args(argv)

    results = load_results()
    results["meta"]["gap"] = args.gap
    if "offline" in args.part:
        results["verifier"] = verifier_tests()
        _print("verifier negative tests", results["verifier"])
        results["sql_safety"] = sql_safety_tests()
        _print("SQL safety", results["sql_safety"])
        save(results)
    with httpx.Client() as client:
        if {"api", "questions", "sse"} & set(args.part):
            h = client.get(f"{API}/health", timeout=30).json()
            if h.get("status") != "ok":
                raise SystemExit(f"API not healthy: {h}")
        if "api" in args.part:
            results["api"] = api_contract(client)
            _print("API contract", results["api"])
            save(results)
        if "questions" in args.part:
            run_questions(client, results, args.only, args.runs, args.gap)
            print(f"cache: {build_cache(results)} answers")
        if "sse" in args.part:
            results["sse"] = sse_contract(client, args.gap)
            _print("SSE contract", results["sse"])
            save(results)
    build_cache(results)
    write_report(results)
    print(f"report: {REPORT.relative_to(BACKEND.parent)}")
    summary(results)


if __name__ == "__main__":
    main()