"""Profile every experimental-table CSV: columns, types, units, samples, row counts.

Run from backend/:  uv run python ingest/profile_tables.py
Prints the report and writes it to data/raw/profile.txt.
"""
import json
import re
from pathlib import Path

import pandas as pd

from psi import INV_DIR, RAW, TABLE_DIR

OUT = RAW / "profile.txt"
SAMPLES = 4
MAXLEN = 40


def file_to_psi() -> dict[str, tuple[str, str]]:
    """Map each table file name to (psi_id, acronym) using the investigation JSONs."""
    m = {}
    for p in sorted(INV_DIR.glob("PSI-*.json")):
        inv = json.loads(p.read_text())
        acr = inv.get("investigationAcronym") or (inv.get("title") or "")[:30]
        for t in inv.get("experimentalTable") or []:
            m[Path(t["file_name"]).name] = (p.stem, acr)
    return m


def lookup(path: Path, m: dict) -> tuple[str, str]:
    for fname, v in m.items():
        if path.name == fname or fname in path.name:
            return v
    hit = re.search(r"PSI-\d+", path.name)
    return (hit.group(0), "?") if hit else ("?", "?")


def read_csv(path: Path) -> tuple[pd.DataFrame, str]:
    for enc in ("utf-8-sig", "cp1252"):
        try:
            df = pd.read_csv(path, dtype=str, keep_default_na=False, encoding=enc)
            return df, enc
        except UnicodeDecodeError:
            continue
    raise RuntimeError(f"cannot decode {path}")


def short(v: str) -> str:
    v = v.replace("\r", "").replace("\n", "\\n")
    return v if len(v) <= MAXLEN else v[: MAXLEN - 3] + "..."


def profile_col(s: pd.Series) -> str:
    s = s.str.strip()
    filled = s[s != ""]
    num = pd.to_numeric(filled.str.replace(",", "", regex=False), errors="coerce")
    n_num = int(num.notna().sum())
    if len(filled) and n_num == len(filled):
        kind = "num"
    elif n_num:
        kind = f"mixed({n_num} num)"
    else:
        kind = "text"
    rng = f" [{num.min():g} .. {num.max():g}]" if n_num else ""
    samples = ", ".join(repr(short(v)) for v in filled.drop_duplicates().head(SAMPLES))
    return f"{len(filled)}/{len(s)} filled, {filled.nunique()} uniq, {kind}{rng} | e.g. {samples}"


def psi_num(psi: str) -> int:
    hit = re.search(r"\d+", psi)
    return int(hit.group(0)) if hit else 10**6


def main() -> None:
    m = file_to_psi()
    paths = sorted(TABLE_DIR.glob("*.csv"), key=lambda p: (psi_num(lookup(p, m)[0]), p.name))
    out, summary = [], []

    for path in paths:
        psi, acr = lookup(path, m)
        df, enc = read_csv(path)
        blank = df.apply(lambda c: c.str.strip()).eq("").all(axis=1)
        df = df[~blank]
        dups = int(df.duplicated().sum())

        out.append(f"\n=== {psi} {acr} | {path.name} | enc={enc} | rows={len(df)} "
                   f"| cols={df.shape[1]} | dup_rows={dups} | blank_rows_dropped={int(blank.sum())}")
        for i, col in enumerate(df.columns):
            out.append(f"  [{i:02}] {col!r}: {profile_col(df[col])}")
        summary.append((psi, acr, path.name, len(df), df.shape[1], dups))

    out.append("\n=== SUMMARY")
    flight_total = 0
    for psi, acr, name, rows, cols, dups in summary:
        out.append(f"  {psi:<8} {acr:<20} rows={rows:<4} cols={cols:<3} dups={dups:<3} {name}")
        if psi != "PSI-142":
            flight_total += rows
    out.append(f"  files={len(summary)}  flight_rows={flight_total} (expect 1999)")

    report = "\n".join(out)
    OUT.write_text(report)
    print(report)
    print(f"\nwritten to {OUT}")


if __name__ == "__main__":
    main()