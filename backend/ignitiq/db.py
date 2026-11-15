"""Build backend/data/processed/flamescope.duckdb from the raw files.

Tables: investigations, publications, tests. Rebuilt from scratch each run, written atomically.
Fails (writes nothing) if any test row fails validation.

Run from backend/:  uv run python -m ignitiq.db
"""
from __future__ import annotations

import html
import json
import re
import sys
from pathlib import Path

import duckdb
import pandas as pd

from ignitiq.habitats import habitats_df
from ignitiq.insights import write_insights
from ignitiq.schema import CORE_COLUMNS
from ignitiq.tables import build_tests

BACKEND = Path(__file__).resolve().parents[1]
RAW = BACKEND / "data" / "raw"
INV_DIR = RAW / "investigations"
ABSTRACTS = RAW / "abstracts.jsonl"
DB_PATH = BACKEND / "data" / "processed" / "flamescope.duckdb"

TEXT_FIELDS = {
    "objective": "objective", "approach": "approach", "hypothesis": "hypothesis",
    "research_impacts": "researchImpacts", "hardware": "experimentHardware",
    "description": "description",
}


def connect(read_only: bool = True) -> duckdb.DuckDBPyConnection:
    """Open the built database (read-only by default; the agent and API use this)."""
    return duckdb.connect(str(DB_PATH), read_only=read_only)


# ---------------------------------------------------------------- text helpers

def as_text(v) -> str | None:
    """JSON field -> plain text: lists joined, dicts flattened, HTML stripped, spaces squashed."""
    if v is None:
        return None
    if isinstance(v, list):
        v = "; ".join(t for t in (as_text(x) for x in v) if t)
    elif isinstance(v, dict):
        v = "; ".join(f"{k}: {t}" for k, x in v.items() if (t := as_text(x)))
    s = html.unescape(re.sub(r"<[^>]+>", " ", str(v)))
    s = " ".join(s.split())
    return s or None


def norm_doi(v) -> str | None:
    s = (str(v or "")).strip().lower()
    s = re.sub(r"^(https?://)?(dx\.)?doi\.org/", "", s).removeprefix("doi:").strip()
    return s or None


def norm_title(v) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(v or "").lower())


# ---------------------------------------------------------------- loaders

def load_investigations() -> tuple[pd.DataFrame, list[dict]]:
    inv_rows, pub_rows = [], []
    for p in sorted(INV_DIR.glob("PSI-*.json"), key=lambda p: int(p.stem.split("-")[1])):
        d = json.loads(p.read_text())
        psi = p.stem
        row = {
            "psi_id": psi,
            "acronym": as_text(d.get("investigationAcronym")),
            "title": as_text(d.get("title")),
            "project_type": as_text(d.get("projectType")),
            "mission_name": as_text(d.get("missionName")),
            "doi": norm_doi(d.get("doi")),
            "total_file_size": d.get("totalFileSize"),
            "n_tables": len(d.get("experimentalTable") or []),
        }
        row |= {col: as_text(d.get(key)) for col, key in TEXT_FIELDS.items()}
        pubs = d.get("publications") or []
        row["n_publications"] = len(pubs)
        inv_rows.append(row)
        for pub in pubs:
            pub_rows.append({
                "psi_id": psi,
                "title": as_text(pub.get("title")),
                "authors": as_text(pub.get("authorList")),
                "doi": norm_doi(pub.get("doi")),
            })
    return pd.DataFrame(inv_rows), pub_rows


def attach_abstracts(pub_rows: list[dict]) -> pd.DataFrame:
    """Join abstracts.jsonl onto publications by (psi_id, doi), then (psi_id, normalized title)."""
    by_doi, by_title = {}, {}
    if ABSTRACTS.exists():
        for line in ABSTRACTS.read_text().splitlines():
            if not line.strip():
                continue
            a = json.loads(line)
            abstract = as_text(a.get("abstract"))
            psi, _, ident = str(a.get("key", "")).partition("|")
            psi = a.get("psi_id") or psi
            source = a.get("match") or a.get("matched_by") or a.get("source")
            rec = (abstract, source)
            for d in {norm_doi(a.get("doi")), norm_doi(ident) if ident.startswith("10.") else None} - {None}:
                by_doi[(psi, d)] = rec
            for t in {norm_title(a.get("title")), norm_title(ident)} - {""}:
                by_title[(psi, t)] = rec
    for r in pub_rows:
        hit = by_doi.get((r["psi_id"], r["doi"])) if r["doi"] else None
        hit = hit or by_title.get((r["psi_id"], norm_title(r["title"])))
        r["abstract"], r["abstract_source"] = hit if hit else (None, None)
    df = pd.DataFrame(pub_rows, columns=["psi_id", "title", "authors", "doi", "abstract", "abstract_source"])
    df.insert(0, "pub_id", range(1, len(df) + 1))
    return df


# ---------------------------------------------------------------- build

TESTS_DDL = """
CREATE TABLE tests (
    test_pk INTEGER PRIMARY KEY,
    psi_id VARCHAR NOT NULL, experiment VARCHAR NOT NULL, test_id VARCHAR NOT NULL,
    fuel VARCHAR, material VARCHAR, pressure_kpa DOUBLE, o2_frac DOUBLE,
    diluent VARCHAR, diluent_frac DOUBLE, flow_cm_s DOUBLE, outcome VARCHAR,
    burn_time_s DOUBLE, spread_rate_mm_s DOUBLE, extra JSON
)"""


def build() -> None:
    tests, report = build_tests()
    n_err = sum(len(r["errors"]) for r in report)
    if n_err:
        for r in report:
            for row, msg in r["errors"][:3]:
                print(f"ERR {r['key']} row {row}: {msg}")
        sys.exit(f"build aborted: {n_err} validation errors, nothing written")

    tests = tests.copy()
    tests.insert(0, "test_pk", range(1, len(tests) + 1))
    tests["extra"] = tests["extra"].map(lambda e: json.dumps(e, ensure_ascii=False))
    inv, pub_rows = load_investigations()
    pubs = attach_abstracts(pub_rows)

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = DB_PATH.with_suffix(".duckdb.tmp")
    tmp.unlink(missing_ok=True)
    con = duckdb.connect(str(tmp))
    try:
        con.register("inv_df", inv)
        con.execute("CREATE TABLE investigations AS SELECT * FROM inv_df")
        con.register("pub_df", pubs)
        con.execute("CREATE TABLE publications AS SELECT * FROM pub_df")
        con.execute(TESTS_DDL)
        con.register("tests_df", tests)
        cols = ", ".join(["test_pk"] + CORE_COLUMNS)
        con.execute(f"INSERT INTO tests SELECT {cols}, CAST(extra AS JSON) FROM tests_df")
        con.register("hab_df", habitats_df())
        con.execute("CREATE TABLE habitats AS SELECT * FROM hab_df")
        write_insights(con)
        checks(con)
    finally:
        con.close()
    tmp.replace(DB_PATH)
    print(f"\nwritten {DB_PATH}")


def checks(con: duckdb.DuckDBPyConnection) -> None:
    q = lambda sql: con.execute(sql).fetchall()  # noqa: E731
    n_inv, n_pub, n_test = (q(f"SELECT count(*) FROM {t}")[0][0] for t in ("investigations", "publications", "tests"))
    n_abs = q("SELECT count(*) FROM publications WHERE abstract IS NOT NULL")[0][0]
    n_hab = q("SELECT count(*) FROM habitats")[0][0]
    print(f"investigations={n_inv}  publications={n_pub} (with abstract {n_abs})  tests={n_test}  habitats={n_hab}")

    print("\ntests by investigation:")
    for psi, acr, exp, n, summ in q("""
        SELECT t.psi_id, i.acronym, t.experiment, count(*),
               count(*) FILTER (WHERE t.extra->>'row_kind' = 'summary')
        FROM tests t LEFT JOIN investigations i USING (psi_id)
        GROUP BY t.psi_id, i.acronym, t.experiment
        ORDER BY CAST(split_part(t.psi_id, '-', 2) AS INT), t.experiment"""):
        print(f"  {psi:<8} {str(acr):<20} {exp:<14} {n:>4}" + (f"  (summary {summ})" if summ else ""))

    orphans = q("SELECT DISTINCT psi_id FROM tests WHERE psi_id NOT IN (SELECT psi_id FROM investigations)")
    dup_ids = q("SELECT experiment, test_id, count(*) FROM tests GROUP BY ALL HAVING count(*) > 1 LIMIT 5")
    bad_json = q("SELECT count(*) FROM tests WHERE json_extract(extra, '$.raw') IS NULL")[0][0]
    print("\nchecks:")
    print(f"  orphan psi_ids in tests: {[o[0] for o in orphans] or 'none'}")
    print(f"  duplicate (experiment, test_id): {dup_ids or 'none'}")
    print(f"  rows missing extra.raw: {bad_json}")
    print(f"  tests row count: {n_test} {'PASS' if n_test == 1999 else 'FAIL (expect 1999)'}")
    if orphans or dup_ids or bad_json or n_test != 1999:
        raise RuntimeError("integrity checks failed")


if __name__ == "__main__":
    build()
