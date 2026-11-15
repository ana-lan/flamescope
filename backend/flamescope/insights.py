"""Precomputed, citable insights. Each is a SQL recipe + a sentence template.

Every query returns one row with a `value` column and a `psi_ids` list (the sources it used);
all other columns are kept as `detail` and can be used in the template.
Written into the `insights` table by db.py. Inspect or verify from backend/:
    uv run python -m flamescope.insights            # list stored insights
    uv run python -m flamescope.insights --verify   # rerun every stored SQL, compare values
"""
from __future__ import annotations

import argparse
import json
import math
import string
from dataclasses import dataclass


@dataclass
class Insight:
    id: str
    rank: int
    title: str
    unit: str
    habitats: list[str]       # habitat slugs, or ["all"]
    sql: str
    template: str


_PSI = "list_sort(list_distinct(list(psi_id) FILTER (WHERE psi_id IS NOT NULL))) AS psi_ids"
_SHARE = "round(avg(CASE WHEN outcome = '{o}' THEN 1.0 ELSE 0.0 END) FILTER (WHERE {w}), 3)"

INSIGHTS = [
    Insight(
        "coverage_gap", 1, "Where crews will live next has the least fire data", "x fewer tests",
        ["iss", "gateway", "lunar"],
        f"""
WITH near AS (
  SELECT h.slug, t.psi_id
  FROM habitats h JOIN tests t
    ON abs(t.pressure_kpa - h.pressure_kpa) <= 0.15 * h.pressure_kpa
   AND abs(t.o2_frac - h.o2_frac) <= 0.03
  WHERE h.slug IN ('iss', 'gateway', 'lunar'))
SELECT count(*) FILTER (WHERE slug = 'iss') AS iss_n,
       count(*) FILTER (WHERE slug = 'gateway') AS gateway_n,
       count(*) FILTER (WHERE slug = 'lunar') AS lunar_n,
       round(count(*) FILTER (WHERE slug = 'iss')
             / nullif(count(*) FILTER (WHERE slug = 'lunar'), 0), 1) AS value,
       {_PSI}
FROM near""",
        "Only {lunar_n} microgravity tests ran near NASA's proposed 8.2 psia / 34% O2 lunar and Mars "
        "habitat atmosphere, versus {iss_n} near ISS conditions ({value:.0f}x fewer) and {gateway_n} "
        "near the 10.2 psia / 26.5% Gateway atmosphere.",
    ),
    Insight(
        "cfig_high_o2_persistence", 2, "At high O2, gas flames burn until the fuel is cut", "share of tests",
        ["lunar"],
        f"""
SELECT {_SHARE.format(o='flow_terminated', w='o2_frac >= 0.30')} AS value,
       {_SHARE.format(o='flow_terminated', w='o2_frac < 0.25')} AS low_o2_share,
       round(median(burn_time_s) FILTER (WHERE o2_frac >= 0.30), 0) AS high_o2_burn_s,
       round(median(burn_time_s) FILTER (WHERE o2_frac < 0.25), 0) AS low_o2_burn_s,
       count(*) FILTER (WHERE o2_frac >= 0.30) AS n_high,
       count(*) FILTER (WHERE o2_frac < 0.25) AS n_low,
       {_PSI}
FROM tests
WHERE experiment = 'CFI-G' AND o2_frac IS NOT NULL
  AND outcome IN ('self_extinguished', 'flow_terminated')""",
        "In CFI-G gas-jet tests at 30% O2 or more, {value:.0%} of flames kept burning until the fuel "
        "flow was stopped, versus {low_o2_share:.0%} below 25% O2 (median burn {high_o2_burn_s:.0f} s vs "
        "{low_o2_burn_s:.0f} s; n = {n_high} and {n_low}).",
    ),
    Insight(
        "flex_limiting_o2", 3, "How little oxygen a fuel droplet needs", "O2 fraction",
        ["all"],
        f"""
SELECT min(o2_frac) FILTER (WHERE fuel = 'heptane' AND outcome = 'completion') AS value,
       round(arg_min(pressure_kpa, o2_frac) FILTER (WHERE fuel = 'heptane' AND outcome = 'completion'), 0)
           AS low_o2_complete_kpa,
       max(o2_frac) FILTER (WHERE fuel = 'heptane' AND outcome = 'extinction') AS heptane_max_ext_o2,
       round(arg_max(pressure_kpa, o2_frac) FILTER (WHERE fuel = 'heptane' AND outcome = 'extinction'), 0)
           AS high_o2_ext_kpa,
       min(o2_frac) FILTER (WHERE fuel = 'methanol' AND outcome = 'completion') AS methanol_min_complete_o2,
       count(*) FILTER (WHERE fuel = 'heptane') AS n_heptane,
       count(*) FILTER (WHERE fuel = 'methanol') AS n_methanol,
       {_PSI}
FROM tests WHERE experiment = 'FLEX' AND outcome IS NOT NULL""",
        "In FLEX, a heptane droplet burned to completion at just {value:.0%} O2 (at {low_o2_complete_kpa:.0f} kPa), "
        "while another went out at {heptane_max_ext_o2:.0%} O2 (at {high_o2_ext_kpa:.0f} kPa): oxygen fraction "
        "alone does not predict whether a droplet fire survives ({n_heptane} heptane tests).",
    ),
    Insight(
        "flex_diluent_extinction", 4, "Which inert gas puts droplet flames out", "share of tests",
        ["all"],
        f"""
SELECT {_SHARE.format(o='extinction', w="diluent = 'CO2'")} AS value,
       {_SHARE.format(o='extinction', w="diluent = 'N2'")} AS n2_share,
       {_SHARE.format(o='extinction', w="diluent = 'He'")} AS he_share,
       round(avg(o2_frac) FILTER (WHERE diluent = 'CO2'), 3) AS co2_mean_o2,
       round(avg(o2_frac) FILTER (WHERE diluent = 'N2'), 3) AS n2_mean_o2,
       count(*) FILTER (WHERE diluent = 'CO2') AS n_co2,
       count(*) FILTER (WHERE diluent = 'N2') AS n_n2,
       count(*) FILTER (WHERE diluent = 'He') AS n_he,
       {_PSI}
FROM tests WHERE experiment = 'FLEX' AND outcome IS NOT NULL""",
        "{value:.0%} of FLEX droplet tests with CO2 as the main diluent ended in flame extinction, versus "
        "{n2_share:.0%} with N2 and {he_share:.0%} with He (n = {n_co2}, {n_n2}, {n_he}; mean O2 "
        "{co2_mean_o2:.0%} in the CO2 tests vs {n2_mean_o2:.0%} in the N2 tests).",
    ),
    Insight(
        "saffire_flow_direction", 5, "Flow direction changes how long a large fire lasts", "ratio",
        ["iss"],
        f"""
WITH b AS (
  SELECT max(burn_time_s) FILTER (WHERE extra->>'flow_direction' = 'concurrent') AS concurrent_s,
         max(burn_time_s) FILTER (WHERE extra->>'flow_direction' = 'opposed') AS opposed_s,
         any_value(material) AS material,
         {_PSI}
  FROM tests WHERE experiment = 'SAFFIRE-I' AND burn_time_s IS NOT NULL)
SELECT concurrent_s, opposed_s, round(concurrent_s / nullif(opposed_s, 0), 1) AS value, material, psi_ids
FROM b""",
        "In SAFFIRE-I's large {material} burns aboard a Cygnus, the sample with air flowing along the "
        "flame burned for {concurrent_s:.0f} s versus {opposed_s:.0f} s against the flow ({value}x; one burn each).",
    ),
]


# ---------------------------------------------------------------- running

class _SafeFormatter(string.Formatter):
    """Missing or null values print as 'n/a' instead of crashing the template."""

    def format_field(self, value, spec):
        if value is None or (isinstance(value, float) and math.isnan(value)):
            return "n/a"
        return super().format_field(value, spec)


def run_one(con, ins: Insight) -> dict | None:
    cur = con.execute(ins.sql)
    cols = [d[0] for d in cur.description]
    row = cur.fetchone()
    r = dict(zip(cols, row)) if row else {}
    if r.get("value") is None:
        return None
    detail = {k: v for k, v in r.items() if k not in ("value", "psi_ids")}
    return {
        "id": ins.id, "rank": ins.rank, "title": ins.title,
        "value": float(r["value"]), "unit": ins.unit,
        "explanation": _SafeFormatter().format(ins.template, **r),
        "sql": ins.sql.strip(), "source_psi_ids": list(r.get("psi_ids") or []),
        "habitats": ins.habitats, "detail": json.dumps(detail, default=str),
    }


DDL = """
CREATE TABLE insights (
    id VARCHAR PRIMARY KEY, rank INTEGER, title VARCHAR, value DOUBLE, unit VARCHAR,
    explanation VARCHAR, sql VARCHAR, source_psi_ids VARCHAR[], habitats VARCHAR[], detail JSON
)"""


def write_insights(con) -> None:
    """Compute every insight against the open (being-built) database and store the ones with data."""
    con.execute(DDL)
    for ins in INSIGHTS:
        r = run_one(con, ins)
        if r is None:
            print(f"  insight {ins.id}: SKIPPED (no data for value)")
            continue
        con.execute("INSERT INTO insights VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", list(r.values()))
    n = con.execute("SELECT count(*) FROM insights").fetchone()[0]
    print(f"insights={n} of {len(INSIGHTS)}")


def show(con) -> None:
    for rank, iid, title, value, unit, expl, psis, habs in con.execute(
            "SELECT rank, id, title, value, unit, explanation, source_psi_ids, habitats "
            "FROM insights ORDER BY rank").fetchall():
        print(f"\n[{rank}] {title}  ({iid})")
        print(f"    value: {value} {unit}   sources: {psis}   habitats: {habs}")
        print(f"    {expl}")


def verify(con) -> bool:
    ok = True
    for iid, sql, stored in con.execute("SELECT id, sql, value FROM insights ORDER BY rank").fetchall():
        cur = con.execute(sql)
        cols = [d[0] for d in cur.description]
        again = dict(zip(cols, cur.fetchone()))["value"]
        same = again is not None and math.isclose(float(again), stored, rel_tol=1e-9, abs_tol=1e-12)
        ok &= same
        print(f"  {iid:<28} stored={stored:<10} rerun={again:<10} {'PASS' if same else 'FAIL'}")
    print("VERIFY:", "PASS" if ok else "FAIL")
    return ok


if __name__ == "__main__":
    from flamescope.db import connect
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify", action="store_true")
    a = ap.parse_args()
    con = connect()
    if a.verify:
        raise SystemExit(0 if verify(con) else 1)
    show(con)
