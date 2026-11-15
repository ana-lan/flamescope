"""IgnitIQ eval: the questions in eval/questions.yaml, scored against the live API.

Expected numbers are computed from the DuckDB file at run time (truth_sql /
truth_nearest), never typed in by hand. Results are saved after every question.

From backend/:
  uv run python -m eval.run_eval --truth                 print the answer key (no API calls)
  uv run python -m eval.run_eval [--only 1 7] [--gap 60] [--api URL]
  uv run python -m eval.run_eval --report                rebuild eval/results.md from saved results
"""
from __future__ import annotations

import argparse
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
import yaml

from ignitiq import conditions
from ignitiq.db import connect

HERE = Path(__file__).resolve().parent
QUESTIONS = HERE / "questions.yaml"
RESULTS = HERE / "results.json"
REPORT = HERE / "results.md"
DEFAULT_API = os.getenv("EVAL_API_URL", "https://ignit-iq.onrender.com")

NOT_COVERED = [
    "not cover", "doesn't cover", "does not cover", "no data", "no test", "not tested", "untested",
    "outside", "extrapolat", "not recorded", "no recorded", "isn't recorded", "not in the",
    "does not include", "doesn't include", "no measurement", "not measured", "none of the",
]
CATS = ["numbers", "citations", "facts", "sql", "grounding"]
NUM_RE = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?")
SUBSCRIPTS = str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789")
NUMBER_WORDS = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen "
    "sixteen seventeen eighteen nineteen twenty".split())}
# "No ISS tests ...", "do not directly cover", "does not contain any recorded ..."
NOT_COVERED_RE = re.compile(
    r"\b(no|not|never|none|without)\b[^.]{0,40}?\b(cover\w*|tested|tests?|data|recorded|measure\w*|match\w*)\b")


# ---------------------------------------------------------------- answer key

def load_questions() -> list[dict]:
    qs = yaml.safe_load(QUESTIONS.read_text())
    ids = [q["id"] for q in qs]
    assert len(ids) == len(set(ids)), "duplicate question ids"
    return qs


def truth(q: dict, con) -> dict:
    if "truth_sql" in q:
        rows = con.execute(q["truth_sql"]).fetchall()
        if q.get("truth_kind") == "text":
            return {"text": [str(r[0]) for r in rows if r[0] is not None]}
        return {"numbers": [None if v is None else float(v) for v in rows[0]]}
    if "truth_nearest" in q:
        res = conditions.nearest_for_habitat(q["truth_nearest"])
        return {"numbers": [float(res["summary"]["n_in_box"])]}
    return {}


# ---------------------------------------------------------------- scoring

def answer_numbers(text: str) -> list[str]:
    text = re.sub(r"\[[^\]]*\]", " ", text)  # drop [PSI-69] style citations
    return [m.group().replace(",", "") for m in NUM_RE.finditer(text)]


def matches(v: float, nums: list[str]) -> bool:
    """True if some number in the answer is v, rounded to the shown precision, or v as a percent."""
    cands = [v] + ([v * 100] if 0 < abs(v) <= 1 else [])
    for s in nums:
        a = float(s)
        d = len(s.split(".")[1]) if "." in s else 0
        for c in cands:
            if round(c, d) == a or (abs(c) > 10 and abs(a - c) / abs(c) < 0.01):
                return True
    return False


def _alts(items) -> list[str]:
    out = []
    for a in items:
        out += NOT_COVERED if a == "not_covered" else [str(a)]
    return out


def score(q: dict, res: dict, key: dict) -> list[dict]:
    ans = res.get("answer", "").replace("\u2019", "'").translate(SUBSCRIPTS)  # CO₂ -> CO2
    low = ans.lower()
    checks: list[dict] = []

    def add(cat, label, ok, detail=""):
        checks.append({"cat": cat, "label": label, "ok": bool(ok), "detail": str(detail)[:240]})

    if res.get("cached"):
        add("run", "live answer, not a cached replay", False, "cached")

    nums = answer_numbers(ans) + [str(n) for w, n in NUMBER_WORDS.items() if re.search(rf"\b{w}\b", low)]
    for v in key.get("numbers", []):
        if v is None:
            add("numbers", "answer key has a value", False, "truth query returned NULL")
        else:
            add("numbers", f"number {v:g}", matches(v, nums), f"answer has {nums[:15]}")
    for t in key.get("text", []):
        words = [w for w in re.findall(r"[a-z]+", t.lower()) if len(w) >= 4] or [t.lower()]
        add("facts", f"mentions {t}", any(w in low for w in words))

    verified = {c["id"] for c in res.get("citations", []) if c.get("verified")}
    for cid in q.get("cites", []):
        add("citations", f"cites {cid}", cid in verified, sorted(verified))
    if q.get("cites_any"):
        add("citations", f"cites one of {q['cites_any']}", verified & set(q["cites_any"]), sorted(verified))
    if q.get("min_citations"):
        add("citations", f"at least {q['min_citations']} verified citation(s)",
            len(verified) >= q["min_citations"], sorted(verified))

    for item in q.get("must_include", []):
        alts = item if isinstance(item, list) else [item]
        add("facts", f"says {alts[0]!r}", any(str(a).lower() in low for a in alts))
    for bad in q.get("must_not_include", []):
        add("facts", f"avoids {bad!r}", bad.lower() not in low)
    if q.get("mentions_any"):
        alts = _alts(q["mentions_any"])
        label = "says the data does not cover it" if "not_covered" in q["mentions_any"] else f"mentions one of {alts[:4]}"
        hit = any(a.lower() in low for a in alts)
        if "not_covered" in q["mentions_any"]:
            hit = hit or bool(NOT_COVERED_RE.search(low))
        add("facts", label, hit)

    sql_text = json.dumps(res.get("sql_run", [])).lower()
    for s in q.get("sql_contains", []):
        add("sql", f"SQL uses {s}", s.lower() in sql_text)

    if q.get("grounding", True):
        g = res.get("grounding") or {}
        add("grounding", "grounding ok", g.get("ok") is True, json.dumps(g)[:240])
    return checks


# ---------------------------------------------------------------- running

def load_results() -> dict:
    return json.loads(RESULTS.read_text()) if RESULTS.exists() else {}


def save(results: dict) -> None:
    tmp = RESULTS.with_suffix(".tmp")
    tmp.write_text(json.dumps(results, indent=2, ensure_ascii=False))
    tmp.replace(RESULTS)


def ask(client: httpx.Client, api: str, q: dict) -> tuple[dict | None, str | None, float]:
    body = {"question": q["question"], "habitat": q.get("habitat"), "stream": False, "fresh": True}
    t0 = time.perf_counter()
    r = client.post(f"{api}/ask", json=body)
    if r.status_code == 429:  # another question still running: wait once
        time.sleep(30)
        t0 = time.perf_counter()
        r = client.post(f"{api}/ask", json=body)
    wall = time.perf_counter() - t0
    if r.status_code != 200:
        return None, f"HTTP {r.status_code}: {r.text[:200]}", wall
    return r.json(), None, wall


def run(api: str, only: list[int] | None, gap: float) -> None:
    qs = load_questions()
    results = load_results()
    con = connect()
    todo = [q for q in qs if not only or q["id"] in only]
    with httpx.Client(timeout=180) as client:
        t0 = time.perf_counter()
        h = client.get(f"{api}/health")
        print(f"health {h.status_code} in {time.perf_counter() - t0:.1f}s ({api})")
        for i, q in enumerate(todo):
            if i:
                time.sleep(gap)
            key = truth(q, con)
            res, err, wall = ask(client, api, q)
            if err:
                checks = [{"cat": "run", "label": "HTTP 200", "ok": False, "detail": err}]
                res = {}
            else:
                checks = score(q, res, key)
            passed = all(c["ok"] for c in checks)
            results[str(q["id"])] = {
                "id": q["id"], "type": q.get("type", ""), "question": q["question"],
                "habitat": q.get("habitat"), "truth": key, "passed": passed, "checks": checks,
                "answer": res.get("answer", ""), "model": res.get("model"),
                "failover": bool(res.get("models_failed")), "usage": res.get("usage", {}),
                "elapsed_s": round(wall, 2), "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "api": api, "response" : res,
            }
            save(results)
            fails = [c["label"] for c in checks if not c["ok"]]
            print(f"{q['id']:>2} {'PASS' if passed else 'FAIL'} {wall:5.1f}s {res.get('model') or '-':<28} "
                  f"{'; '.join(fails)}")
    write_report(results)


def rescore() -> None:
    """Re-score saved responses with the current rules. No API calls."""
    qs = {q["id"]: q for q in load_questions()}
    results = load_results()
    con = connect()
    for k, r in results.items():
        if not r.get("response"):
            print(f"{k:>2} skipped: no saved response (rerun with --only {k})")
            continue
        q = qs[int(k)]
        r["checks"] = score(q, r["response"], truth(q, con))
        r["passed"] = all(c["ok"] for c in r["checks"])
    save(results)
    write_report(results)


def print_truth() -> None:
    con = connect()
    for q in load_questions():
        key = truth(q, con)
        shown = key.get("numbers") or key.get("text") or "(no numeric key)"
        print(f"{q['id']:>2} [{q.get('type', '')}] {q['question'][:70]}\n     -> {shown}")


# ---------------------------------------------------------------- report

def _pct(vals: list[float], p: float) -> float | None:
    if not vals:
        return None
    s = sorted(vals)
    return s[round(p * (len(s) - 1))]


def write_report(results: dict) -> None:
    done = sorted(results.values(), key=lambda r: r["id"])
    passed = sum(r["passed"] for r in done)
    lat = [r["elapsed_s"] for r in done if r.get("elapsed_s")]
    tokens = sum(sum(r.get("usage", {}).values()) for r in done)
    per_cat = {c: [0, 0] for c in CATS}
    for r in done:
        for c in r["checks"]:
            if c["cat"] in per_cat:
                per_cat[c["cat"]][0] += c["ok"]
                per_cat[c["cat"]][1] += 1

    def cell(r, cat):
        cs = [c for c in r["checks"] if c["cat"] == cat]
        return "-" if not cs else ("ok" if all(c["ok"] for c in cs) else "FAIL")

    out = [
        "# IgnitIQ eval results", "",
        f"Live API: `{done[0]['api'] if done else ''}`. Each question asked once with `fresh: true` "
        "(no cached answers). Expected numbers are computed from the database at run time.", "",
        f"**{passed} of {len(done)} questions pass.** "
        + " | ".join(f"{c} {ok}/{n}" for c, (ok, n) in per_cat.items() if n)
        + f" | failovers {sum(r['failover'] for r in done)}"
        + (f" | p50 {_pct(lat, 0.5):.1f} s, p95 {_pct(lat, 0.95):.1f} s" if lat else "")
        + f" | tokens {tokens:,}", "",
        "| # | Type | Question | Result | Numbers | Citations | Facts | SQL | Grounding | Time | Model |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in done:
        out.append(f"| {r['id']} | {r['type']} | {r['question']} | {'PASS' if r['passed'] else 'FAIL'} | "
                   + " | ".join(cell(r, c) for c in CATS)
                   + f" | {r['elapsed_s']:.1f} s | {r.get('model') or '-'} |")
    fails = [r for r in done if not r["passed"]]
    if fails:
        out += ["", "## Failures", ""]
        for r in fails:
            out.append(f"### Q{r['id']}: {r['question']}")
            for c in r["checks"]:
                if not c["ok"]:
                    out.append(f"- {c['label']}: {c['detail']}")
            out.append(f"\n> {r['answer'][:400].replace(chr(10), ' ')}\n")
    REPORT.write_text("\n".join(out) + "\n")
    print(f"report: {REPORT}  ({passed}/{len(done)} pass)")


def main(argv=None) -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--truth", action="store_true", help="print the answer key, no API calls")
    p.add_argument("--report", action="store_true", help="rebuild results.md from results.json")
    p.add_argument("--rescore", action="store_true", help="re-score saved responses, no API calls")
    p.add_argument("--only", type=int, nargs="+", help="question ids to run")
    p.add_argument("--gap", type=float, default=60.0, help="seconds between questions (Groq TPM)")
    p.add_argument("--api", default=DEFAULT_API)
    a = p.parse_args(argv)
    if a.truth:
        print_truth()
    elif a.rescore:
        rescore()
    elif a.report:
        write_report(load_results())
    else:
        run(a.api.rstrip("/"), a.only, a.gap)


if __name__ == "__main__":
    main()