"""Nearest tested conditions for a habitat atmosphere (Phase 3.3).

For a target (pressure, ambient O2 fraction), rank every test that recorded both
by a normalized distance and summarize per experiment. Feeds /coverage and the agent.

Distance unit = one Phase 2 box width on each axis (±15% pressure, ±3 pts O2), so
in_box (both deltas <= 1) reproduces the Phase 2 coverage preview.

CLI (from backend/):
    uv run python -m flamescope.conditions                 # all habitat presets
    uv run python -m flamescope.conditions lunar -n 5
    uv run python -m flamescope.conditions --p 70 --o2 0.30
"""
from __future__ import annotations

import argparse
import functools
import math

import numpy as np
import pandas as pd

from flamescope.db import connect

P_TOL = 0.15        # ±15% of the target pressure = 1 unit
O2_TOL = 0.03       # ±3 percentage points of O2 = 1 unit
EPS = 1e-9          # 0.24 - 0.21 is 0.030000000000000002 in floating point
FAR = 2.0           # nearest test beyond 2 units = extrapolation
WELL_COVERED = 20   # tests inside the box for "well_covered"

HABITAT_ORDER = ["iss", "gateway", "lunar", "apollo1"]

ROW_COLS = [
    "test_pk", "test_id", "fuel", "material", "pressure_kpa", "o2_frac", "pp_o2_kpa",
    "diluent", "outcome", "burn_time_s", "row_kind", "distance", "d_pressure_pct", "d_o2_pts",
]

_BASE_SQL = """
select test_pk, psi_id, experiment, test_id, fuel, material,
       pressure_kpa, o2_frac, diluent, outcome, burn_time_s,
       extra->>'row_kind' as row_kind,
       coalesce(extra->>'is_duplicate', 'false') = 'true' as is_dup
from tests
where pressure_kpa is not null
  and o2_frac is not null
  and coalesce(extra->>'invalid_pressure', 'false') <> 'true'
"""


# ---------------------------------------------------------------- helpers

def _clean(v):
    """numpy/pandas scalars -> JSON-safe Python."""
    if v is None or v is pd.NA:
        return None
    if isinstance(v, (bool, np.bool_)):
        return bool(v)
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, (float, np.floating)):
        return None if math.isnan(v) else round(float(v), 4)
    return v


def _records(df: pd.DataFrame) -> list[dict]:
    return [{k: _clean(v) for k, v in rec.items()} for rec in df.to_dict("records")]


@functools.lru_cache(maxsize=1)
def _tested() -> pd.DataFrame:
    """Every test row with both pressure and ambient O2. Loaded once per process."""
    con = connect()
    try:
        df = con.execute(_BASE_SQL).df()
    finally:
        con.close()
    df["pp_o2_kpa"] = df["pressure_kpa"] * df["o2_frac"]
    return df


def _deltas(df: pd.DataFrame, p: float, o2: float) -> tuple[pd.Series, pd.Series]:
    d_p = (df["pressure_kpa"] - p).abs() / (P_TOL * p)
    d_o = (df["o2_frac"] - o2).abs() / O2_TOL
    return d_p, d_o


def _in_box(d_p: pd.Series, d_o: pd.Series) -> pd.Series:
    return (d_p <= 1 + EPS) & (d_o <= 1 + EPS)


# ---------------------------------------------------------------- habitats

def list_habitats() -> list[dict]:
    con = connect()
    try:
        df = con.execute("select * from habitats").df()
    finally:
        con.close()
    df["_order"] = df["slug"].map({s: i for i, s in enumerate(HABITAT_ORDER)}).fillna(99)
    return _records(df.sort_values("_order").drop(columns="_order"))


def get_habitat(slug: str) -> dict:
    habs = {h["slug"]: h for h in list_habitats()}
    if slug not in habs:
        raise ValueError(f"unknown habitat {slug!r}; choose from {list(habs)}")
    return habs[slug]


# ---------------------------------------------------------------- core

def nearest(pressure_kpa: float, o2_frac: float, per_experiment: int = 3,
            include_summary: bool = True) -> dict:
    """Rank tested conditions by distance to (pressure_kpa, o2_frac)."""
    if not (pressure_kpa > 0 and 0 < o2_frac <= 1):
        raise ValueError("pressure_kpa must be > 0 and o2_frac in (0, 1]")

    full = _tested()
    n_box_with_dupes = int(_in_box(*_deltas(full, pressure_kpa, o2_frac)).sum())

    df = full[~full["is_dup"]].copy()
    if not include_summary:
        df = df[df["row_kind"].isna()]

    d_p, d_o = _deltas(df, pressure_kpa, o2_frac)
    df["distance"] = np.sqrt(d_p ** 2 + d_o ** 2)
    df["in_box"] = _in_box(d_p, d_o)
    df["d_pressure_pct"] = 100 * (df["pressure_kpa"] - pressure_kpa) / pressure_kpa
    df["d_o2_pts"] = 100 * (df["o2_frac"] - o2_frac)
    df = df.sort_values(["distance", "test_pk"], kind="stable")

    experiments = []
    for (psi, exp), g in df.groupby(["psi_id", "experiment"], sort=False):
        box = g[g["in_box"]]
        nd = float(g["distance"].iloc[0])
        experiments.append({
            "psi_id": psi,
            "experiment": exp,
            "n_tested": int(len(g)),
            "n_in_box": int(len(box)),
            "nearest_distance": round(nd, 2),
            "far": nd > FAR,
            "tested_range": {
                "pressure_kpa": [_clean(g["pressure_kpa"].min()), _clean(g["pressure_kpa"].max())],
                "o2_frac": [_clean(g["o2_frac"].min()), _clean(g["o2_frac"].max())],
            },
            "outcomes_in_box": {k: int(v) for k, v in box["outcome"].value_counts().items()},
            "nearest": _records(g.head(per_experiment)[ROW_COLS]),
        })
    experiments.sort(key=lambda e: e["nearest_distance"])

    n_box = int(df["in_box"].sum())
    best = float(df["distance"].iloc[0]) if len(df) else math.inf
    if n_box >= WELL_COVERED:
        verdict = "well_covered"
    elif n_box > 0:
        verdict = "sparse"
    elif best <= FAR:
        verdict = "near_only"
    else:
        verdict = "untested"

    note = (f"{n_box} tests within ±{P_TOL:.0%} pressure and ±{O2_TOL * 100:.0f} pts O2 "
            f"across {sum(e['n_in_box'] > 0 for e in experiments)} experiments; "
            f"nearest test at distance {best:.2f}.")
    if verdict == "untested":
        note += f" No test within {FAR:.0f} box widths: any answer here is an extrapolation."

    return {
        "target": {"pressure_kpa": round(pressure_kpa, 3), "o2_frac": o2_frac,
                   "pp_o2_kpa": round(pressure_kpa * o2_frac, 2)},
        "tolerance": {"pressure_rel": P_TOL, "o2_abs": O2_TOL, "far": FAR},
        "summary": {
            "n_tested": int(len(df)),
            "n_in_box": n_box,
            "n_in_box_incl_duplicates": n_box_with_dupes,
            "nearest_distance": round(best, 2),
            "verdict": verdict,
            "note": note,
        },
        "experiments": experiments,
    }


def nearest_for_habitat(slug: str, per_experiment: int = 3, include_summary: bool = True) -> dict:
    hab = get_habitat(slug)
    out = nearest(hab["pressure_kpa"], hab["o2_frac"], per_experiment, include_summary)
    return {"habitat": hab, **out}


def coverage(slug: str, per_experiment: int = 3) -> dict:
    """Payload for GET /coverage: the nearest summary plus every tested point for the chart."""
    res = nearest_for_habitat(slug, per_experiment)
    hab = res["habitat"]
    full = _tested()
    pts = full[~full["is_dup"]].copy()
    pts["in_box"] = _in_box(*_deltas(pts, hab["pressure_kpa"], hab["o2_frac"]))
    res["points"] = _records(pts[["psi_id", "experiment", "pressure_kpa", "o2_frac",
                                  "outcome", "row_kind", "in_box"]])
    return res


# ---------------------------------------------------------------- CLI

def _print(res: dict, title: str, n: int) -> None:
    t, s = res["target"], res["summary"]
    print(f"\n== {title}: {t['pressure_kpa']:.1f} kPa, {t['o2_frac'] * 100:.1f}% O2, "
          f"ppO2 {t['pp_o2_kpa']:.1f} kPa ==")
    print(f"in box: {s['n_in_box']} (incl. duplicates: {s['n_in_box_incl_duplicates']}) | "
          f"nearest {s['nearest_distance']:.2f} | verdict {s['verdict']}")
    for e in res["experiments"]:
        pr, orr = e["tested_range"]["pressure_kpa"], e["tested_range"]["o2_frac"]
        print(f"  {e['experiment']} ({e['psi_id']})  in box {e['n_in_box']}/{e['n_tested']}  "
              f"nearest {e['nearest_distance']:.2f}{' FAR' if e['far'] else ''}  "
              f"range {pr[0]:.0f}-{pr[1]:.0f} kPa, {orr[0] * 100:.0f}-{orr[1] * 100:.0f}%  "
              f"outcomes {e['outcomes_in_box']}")
        for r in e["nearest"][:n]:
            print(f"     {r['test_id']}: {r['fuel'] or r['material']} {r['pressure_kpa']:.1f} kPa "
                  f"{r['o2_frac'] * 100:.1f}% -> {r['outcome']} (d={r['distance']:.2f})")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="flamescope.conditions")
    ap.add_argument("slug", nargs="?", help="habitat slug; omit for all presets")
    ap.add_argument("--p", type=float, help="custom pressure in kPa (with --o2)")
    ap.add_argument("--o2", type=float, help="custom O2 fraction, e.g. 0.30")
    ap.add_argument("-n", type=int, default=2, help="nearest rows to print per experiment")
    args = ap.parse_args(argv)

    if args.p is not None or args.o2 is not None:
        if args.p is None or args.o2 is None:
            raise SystemExit("give both --p and --o2")
        _print(nearest(args.p, args.o2, args.n), "custom", args.n)
        return
    slugs = [args.slug] if args.slug else [h["slug"] for h in list_habitats()]
    for slug in slugs:
        res = nearest_for_habitat(slug, args.n)
        _print(res, f"{res['habitat']['name']} ({slug})", args.n)


if __name__ == "__main__":
    main()