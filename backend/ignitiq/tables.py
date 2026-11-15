"""Read experimental-table CSVs, run mappers, validate, and build the long `tests` rows.

Mappers live in map_per_test.py (2.3) and map_summary.py (2.4). Each exposes SPECS.

Check from backend/:  uv run python -m ignitiq.tables [EXPERIMENT ...] [--show N]
"""
from __future__ import annotations

import argparse
import importlib
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import pandas as pd

from ignitiq.schema import CORE_COLUMNS, TestRow, clean, raw_extra

BACKEND = Path(__file__).resolve().parents[1]
TABLE_DIR = BACKEND / "data" / "raw" / "tables"
MAPPER_MODULES = ["ignitiq.map_per_test", "ignitiq.map_summary"]


@dataclass
class Spec:
    experiment: str          # value stored in tests.experiment
    psi_id: str
    file_tag: str            # file is "<psi_id>_Experimental table_<file_tag>.csv"
    fn: Callable[[dict, int], dict]   # (row, index) -> TestRow kwargs (no psi_id/experiment)
    prep: Callable[[list[dict]], list[dict]] | None = None   # optional whole-table pass

    @property
    def key(self) -> str:
        return f"{self.experiment} [{self.file_tag}]"


# ---------------------------------------------------------------- reading

def norm_header(h: str) -> str:
    return " ".join(str(h).split())


def read_table(path: Path) -> list[dict]:
    """CSV -> list of {normalized header: whitespace-squashed string}. Blank rows dropped."""
    for enc in ("utf-8-sig", "cp1252"):
        try:
            df = pd.read_csv(path, dtype=str, keep_default_na=False, encoding=enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise RuntimeError(f"cannot decode {path}")
    df.columns = [norm_header(c) for c in df.columns]
    df = df.apply(lambda c: c.map(lambda v: " ".join(str(v).split())))
    df = df[~df.eq("").all(axis=1)]
    return df.to_dict("records")


def find_file(spec: Spec) -> Path:
    path = TABLE_DIR / f"{spec.psi_id}_Experimental table_{spec.file_tag}.csv"
    if not path.exists():
        raise FileNotFoundError(path)
    return path


def first(r: dict, *names: str):
    """Value of the first header that exists in the row (handles header variants)."""
    for n in names:
        if n in r:
            return r[n]
    return None


# ---------------------------------------------------------------- fuels

_FORMULA_NAMES = {
    "c2h4": "ethylene", "c3h8": "propane", "ch4": "methane", "c2h6": "ethane",
    "c4h10": "butane", "c3h6": "propylene", "c12h26": "n-dodecane",
}


def fuel_name(v) -> str | None:
    """Lowercase common name: 'C2H4' -> 'ethylene', '75 % Propylene' -> '75% propylene'."""
    s = clean(v)
    if s is None:
        return None
    s = " ".join(re.sub(r"\s+%", "%", s).lower().split())
    return _FORMULA_NAMES.get(s, s)


# ---------------------------------------------------------------- running

def load_specs() -> list[Spec]:
    specs = []
    for mod in MAPPER_MODULES:
        try:
            specs += importlib.import_module(mod).SPECS
        except ModuleNotFoundError as e:
            if e.name != mod:
                raise
    return specs


def run_spec(spec: Spec) -> tuple[list[TestRow], list[tuple[int, str]]]:
    path = find_file(spec)
    rows = read_table(path)
    if spec.prep:
        rows = spec.prep(rows)
    out, errors = [], []
    seen_raw, seen_ids = set(), Counter()
    for i, r in enumerate(rows):
        try:
            d = spec.fn(r, i)
            extra = d.setdefault("extra", {})
            key = tuple(r.items())
            if key in seen_raw:
                extra["is_duplicate"] = True
            seen_raw.add(key)
            tid = clean(d.get("test_id")) or f"row{i + 1}"
            seen_ids[tid] += 1
            if seen_ids[tid] > 1:
                extra["source_test_id"] = tid
                tid = f"{tid}#{seen_ids[tid]}"
            d["test_id"] = tid
            extra["source_file"] = path.name
            extra["source_row"] = i + 1
            extra["raw"] = raw_extra(r)
            out.append(TestRow(psi_id=spec.psi_id, experiment=spec.experiment, **d))
        except Exception as e:  # keep going; report every bad row
            errors.append((i + 1, f"{type(e).__name__}: {e}"[:400]))
    return out, errors


def build_tests(only: list[str] | None = None) -> tuple[pd.DataFrame, list[dict]]:
    """Run every spec (or those whose experiment is in `only`). Returns (rows df, report)."""
    records, report = [], []
    for spec in load_specs():
        if only and spec.experiment not in only:
            continue
        rows, errors = run_spec(spec)
        records += [r.record() for r in rows]
        flags = Counter(k for r in rows for k, v in r.extra.items()
                        if v is True)
        report.append({
            "key": spec.key, "rows_out": len(rows), "errors": errors,
            "fill": {c: sum(getattr(r, c) is not None for r in rows) for c in CORE_COLUMNS[3:]},
            "flags": dict(flags),
        })
    df = pd.DataFrame(records, columns=CORE_COLUMNS + ["extra"])
    return df, report


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("experiments", nargs="*")
    ap.add_argument("--show", type=int, default=0, help="sample rows per experiment")
    a = ap.parse_args()

    df, report = build_tests(a.experiments or None)
    short = {"pressure_kpa": "p", "o2_frac": "o2", "diluent": "dil", "diluent_frac": "dilf",
             "flow_cm_s": "flow", "outcome": "out", "burn_time_s": "burn", "spread_rate_mm_s": "spread"}
    for rep in report:
        fill = " ".join(f"{short.get(c, c)}={n}" for c, n in rep["fill"].items() if n)
        print(f"{rep['key']:<42} rows={rep['rows_out']:<4} err={len(rep['errors']):<3} {fill}")
        if rep["flags"]:
            print(f"{'':<42} flags {rep['flags']}")
        for row, msg in rep["errors"][:5]:
            print(f"{'':<6}ERR row {row}: {msg}")
    total_err = sum(len(r["errors"]) for r in report)
    print(f"\nTOTAL rows={len(df)} errors={total_err}")

    if a.show:
        with pd.option_context("display.max_columns", None, "display.width", 200,
                               "display.max_colwidth", 30):
            for exp, g in df.groupby("experiment", sort=False):
                print(f"\n--- {exp}")
                print(g[CORE_COLUMNS[2:]].head(a.show).to_string(index=False))


if __name__ == "__main__":
    main()
