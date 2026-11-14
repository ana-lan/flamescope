"""Fetch PSI investigation metadata (and, from 1.4, experimental tables).

Usage (from backend/):
    uv run python ingest/psi.py {investigations|tables|all} [--force]
"""
from __future__ import annotations

import argparse
import json
import sys
from urllib.parse import quote
from pathlib import Path

import httpx
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

BASE = "https://psi.nasa.gov/geode-py/ws"
BACKEND = Path(__file__).resolve().parents[1]
RAW = BACKEND / "data" / "raw"
INV_DIR = RAW / "investigations"
TABLE_DIR = RAW / "tables"

FLIGHT = {
    "PSI-69": "FLEX", "PSI-68": "FLEX-2", "PSI-39": "CFI",
    "PSI-26": "BASS", "PSI-25": "BASS-II",
    "PSI-98": "SAFFIRE-I", "PSI-99": "SAFFIRE-II", "PSI-100": "SAFFIRE-III",
    "PSI-102": "SAME", "PSI-101": "SAME-R",
    "PSI-107": "SPICE", "PSI-106": "SLICE",
    "PSI-10": "ACME Flame Design", "PSI-21": "ACME CLD", "PSI-23": "ACME s-Flame",
    "PSI-22": "ACME E-Field", "PSI-20": "ACME BRE", "PSI-159": "ACME CFI-G",
}
GROUND = ["PSI-117", "PSI-62", "PSI-60", "PSI-142", "PSI-115"]
ALL_IDS = list(FLIGHT) + GROUND


def _retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        return code == 429 or code >= 500
    return False


@retry(
    retry=retry_if_exception(_retryable),
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=1, max=20),
    reraise=True,
)
def get(client: httpx.Client, url: str, **kw) -> httpx.Response:
    r = client.get(url, **kw)
    r.raise_for_status()
    return r


def make_client() -> httpx.Client:
    return httpx.Client(timeout=60, follow_redirects=True,
                        headers={"User-Agent": "flamescope/0.1 (NASA Space Apps 2026)"})


def write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    tmp.write_bytes(data)
    tmp.replace(path)


def fetch_investigations(force: bool = False) -> int:
    INV_DIR.mkdir(parents=True, exist_ok=True)
    failures = 0
    print(f"{'id':<9} {'acronym':<20} {'status':<8} {'tables':>6} {'pubs':>5}")
    with make_client() as client:
        for psi in ALL_IDS:
            path = INV_DIR / f"{psi}.json"
            status = "cached"
            try:
                if force or not path.exists():
                    rec = get(client, f"{BASE}/repo/investigations/{psi}").json()
                    if not isinstance(rec, dict) or not rec.get("title"):
                        raise ValueError("response has no title")
                    write_atomic(path, json.dumps(rec, indent=2, ensure_ascii=False).encode())
                    status = "fetched"
                rec = json.loads(path.read_text())
            except Exception as e:  # keep going, report at the end
                failures += 1
                print(f"{psi:<9} {'':<20} FAILED   {type(e).__name__}: {e}")
                continue
            tables = rec.get("experimentalTable") or []
            pubs = rec.get("publications") or []
            print(f"{psi:<9} {str(rec.get('investigationAcronym'))[:20]:<20} "
                  f"{status:<8} {len(tables):>6} {len(pubs):>5}")
    print(f"\n{len(ALL_IDS) - failures}/{len(ALL_IDS)} investigations on disk in {INV_DIR.relative_to(BACKEND)}")
    return failures


def signed_url(client: httpx.Client, psi: str, file_name: str, version: int) -> str:
    url = (f"{BASE}/studies/{psi}/download"
           f"?file={quote(file_name)}&version={version}&redirect=false")
    body = get(client, url).text.strip().strip('"')
    if not body.startswith("https://"):
        raise ValueError(f"unexpected download response: {body[:120]}")
    return body


def fetch_tables(force: bool = False) -> int:
    TABLE_DIR.mkdir(parents=True, exist_ok=True)
    failures, total = 0, 0
    print(f"{'id':<9} {'status':<8} {'bytes':>9}  file")
    with make_client() as client:
        for psi in ALL_IDS:
            inv_path = INV_DIR / f"{psi}.json"
            if not inv_path.exists():
                print(f"{psi:<9} MISSING  investigation JSON, run `investigations` first")
                failures += 1
                continue
            entries = json.loads(inv_path.read_text()).get("experimentalTable") or []
            for e in entries:
                name = e.get("file_name")
                if not name or e.get("restricted") or e.get("visible") is False:
                    print(f"{psi:<9} SKIPPED  {'':>9}  {name} (restricted/hidden/unnamed)")
                    continue
                total += 1
                expected = e.get("file_size")
                path = TABLE_DIR / name
                if not force and path.exists() and (expected is None or path.stat().st_size == expected):
                    print(f"{psi:<9} {'cached':<8} {path.stat().st_size:>9}  {name}")
                    continue
                try:
                    data = get(client, signed_url(client, psi, name, e.get("version") or 1)).content
                    if data[:1] == b"<":
                        raise ValueError("got HTML/XML instead of a file")
                    if expected is not None and len(data) != expected:
                        raise ValueError(f"size {len(data)} != expected {expected}")
                    write_atomic(path, data)
                    print(f"{psi:<9} {'fetched':<8} {len(data):>9}  {name}")
                except Exception as ex:
                    failures += 1
                    print(f"{psi:<9} FAILED   {'':>9}  {name}: {type(ex).__name__}: {ex}")
    print(f"\n{total - failures}/{total} table files on disk in {TABLE_DIR.relative_to(BACKEND)}")
    return failures


def main() -> None:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("investigations", "tables", "all"):
        s = sub.add_parser(name)
        s.add_argument("--force", action="store_true", help="re-fetch even if cached")
    args = p.parse_args()

    failures = 0
    if args.cmd in ("investigations", "all"):
        failures += fetch_investigations(args.force)
    if args.cmd in ("tables", "all"):
        failures += fetch_tables(args.force)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()