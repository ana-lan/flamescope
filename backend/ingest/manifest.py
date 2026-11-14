"""Write data/raw/MANIFEST.md and check Phase 1's done-when.

Usage (from backend/):
    uv run python ingest/manifest.py
"""
from __future__ import annotations

import csv
import io
import json
from collections import Counter, defaultdict
from datetime import datetime

from psi import ALL_IDS, FLIGHT, INV_DIR, RAW, TABLE_DIR, write_atomic

OUT = RAW / "MANIFEST.md"
CTX = RAW / "context"


def read_csv(path) -> tuple[int, int, str]:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    rows = list(csv.reader(io.StringIO(text)))
    header = rows[0] if rows else []
    body = [r for r in rows[1:] if any(c.strip() for c in r)]
    return len(body), len(header), enc


def main() -> None:
    abstracts = defaultdict(Counter)
    abs_path = RAW / "abstracts.jsonl"
    if abs_path.exists():
        for line in abs_path.read_text().splitlines():
            r = json.loads(line)
            c = abstracts[r["psi_id"]]
            c["looked_up"] += 1
            c["matched"] += r["match"] != "none"
            c["with_abstract"] += bool(r["abstract"])

    lines = [
        "# Phase 1 data manifest",
        "",
        f"Generated {datetime.now():%Y-%m-%d %H:%M} by `backend/ingest/manifest.py`. "
        "Raw files are gitignored; re-create them with the ingest scripts.",
        "",
        "## Investigations",
        "",
        "| PSI id | Name | Type | DOI | Pubs | Matched | Abstracts | Table files | Rows | Cols |",
        "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    table_lines = ["", "## Experimental tables", "",
                   "| PSI id | File | Rows | Cols | Encoding |",
                   "| --- | --- | ---: | ---: | --- |"]
    totals = Counter()
    problems = []

    for psi in ALL_IDS:
        jp = INV_DIR / f"{psi}.json"
        if not jp.exists():
            problems.append(f"{psi}: investigation JSON missing")
            continue
        rec = json.loads(jp.read_text())
        name = rec.get("investigationAcronym") or rec.get("title", "")
        kind = "flight" if psi in FLIGHT else "ground"
        files = [e["file_name"] for e in (rec.get("experimentalTable") or []) if e.get("file_name")]
        rows = cols = 0
        on_disk = 0
        for f in files:
            p = TABLE_DIR / f
            if not p.exists():
                problems.append(f"{psi}: table missing on disk: {f}")
                continue
            on_disk += 1
            n, k, enc = read_csv(p)
            rows += n
            cols = max(cols, k)
            table_lines.append(f"| {psi} | {f} | {n} | {k} | {enc} |")
            totals["rows_" + kind] += n
        if kind == "flight" and on_disk == 0:
            problems.append(f"{psi}: flight investigation has no CSV on disk")
        a = abstracts.get(psi, Counter())
        pubs = len(rec.get("publications") or [])
        totals["pubs"] += pubs
        totals["tables"] += on_disk
        lines.append(f"| {psi} | {name} | {kind} | {rec.get('doi') or ''} | {pubs} | "
                     f"{a['matched']} | {a['with_abstract']} | {on_disk} | {rows} | {cols} |")

    lines += table_lines

    lines += ["", "## Context documents", "", "| Name | Chars | Source |", "| --- | ---: | --- |"]
    idx = CTX / "index.json"
    for d in (json.loads(idx.read_text()) if idx.exists() else []):
        lines.append(f"| {d['name']} | {d['chars']} | {d['source']} |")

    ab = Counter()
    for c in abstracts.values():
        ab.update(c)
    lines += [
        "",
        "## Totals",
        "",
        f"- Investigations on disk: {len(list(INV_DIR.glob('PSI-*.json')))} "
        f"({len(FLIGHT)} flight, {len(ALL_IDS) - len(FLIGHT)} ground)",
        f"- Table files: {totals['tables']}",
        f"- Table rows: {totals['rows_flight']} flight, {totals['rows_ground']} ground "
        "(non-empty rows after the header)",
        f"- Publications listed: {totals['pubs']}; looked up {ab['looked_up']}, "
        f"matched in OpenAlex {ab['matched']}, with abstract {ab['with_abstract']}",
        "",
        "## Known gaps",
        "",
        "- Some publications have no DOI in PSI and no title match in OpenAlex, so no abstract.",
        "- Several tables are summaries, not one row per test (FLEX-2 ranges, SLICE, "
        "ACME BRE/CLD/E-Field/s-Flame, SAME, PSI-142 figure index). Phase 2 decides how to load them.",
        "- Pressure units vary by table (mmHg, atm, bar, text like `1 atm`).",
    ]
    if problems:
        lines += ["", "## Problems", ""] + [f"- {p}" for p in problems]

    write_atomic(OUT, ("\n".join(lines) + "\n").encode())
    print(OUT.read_text())
    print("DONE-WHEN:", "PASS" if not problems else "FAIL")
    for p in problems:
        print("  -", p)


if __name__ == "__main__":
    main()