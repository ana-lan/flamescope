"""Pull publication abstracts from OpenAlex for every PSI investigation.

Usage (from backend/):
    uv run python ingest/abstracts.py [--retry-missing]

Optional env: OPENALEX_API_KEY (sent as api_key) if OpenAlex rate-limits you.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import time
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from urllib.parse import quote

import httpx

from psi import ALL_IDS, INV_DIR, RAW, get, make_client

from dotenv import load_dotenv
load_dotenv(RAW.parents[1] / ".env")

OUT = RAW / "abstracts.jsonl"
OA = "https://api.openalex.org"
TITLE_MATCH = 0.90
PAUSE = 0.12  # stay well under OpenAlex's 10 req/s


def clean_doi(doi: str | None) -> str | None:
    if not doi:
        return None
    d = doi.strip().lower()
    d = re.sub(r"^(https?://(dx\.)?doi\.org/|doi:\s*)", "", d)
    return d if d.startswith("10.") else None


def norm_title(t: str | None) -> str:
    return " ".join(re.sub(r"[^a-z0-9 ]+", " ", (t or "").lower()).split())


def similar(a: str, b: str) -> float:
    return SequenceMatcher(None, norm_title(a), norm_title(b)).ratio()


def rebuild_abstract(inv: dict | None) -> str | None:
    if not inv:
        return None
    pos = [(i, w) for w, idxs in inv.items() for i in idxs]
    return " ".join(w for _, w in sorted(pos)) or None


def oa_params() -> dict:
    key = os.getenv("OPENALEX_API_KEY")
    return {"api_key": key} if key else {}


def by_doi(client: httpx.Client, doi: str) -> dict | None:
    try:
        r = get(client, f"{OA}/works/https://doi.org/{quote(doi, safe='/:')}")
        return r.json()
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return None
        raise


def by_title(client: httpx.Client, title: str) -> dict | None:
    q = re.sub(r"[^\w\s-]", " ", title)[:250]
    r = get(client, f"{OA}/works", params={"search": q, "per-page": 5, **oa_params()})
    best, score = None, 0.0
    for w in r.json().get("results", []):
        s = similar(title, w.get("display_name") or w.get("title") or "")
        if s > score:
            best, score = w, s
    return best if score >= TITLE_MATCH else None


def record(psi: str, pub: dict, work: dict | None, how: str) -> dict:
    loc = (work or {}).get("primary_location") or {}
    src = loc.get("source") or {}
    return {
        "key": key_of(psi, pub),
        "psi_id": psi,
        "title": pub.get("title"),
        "authors": pub.get("authorList"),
        "doi": clean_doi(pub.get("doi")) or clean_doi((work or {}).get("doi")),
        "match": how,  # doi | title | none
        "openalex_id": (work or {}).get("id"),
        "year": (work or {}).get("publication_year"),
        "venue": src.get("display_name"),
        "abstract": rebuild_abstract((work or {}).get("abstract_inverted_index")),
    }


def key_of(psi: str, pub: dict) -> str:
    return f"{psi}|{clean_doi(pub.get('doi')) or norm_title(pub.get('title'))}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--retry-missing", action="store_true",
                    help="re-query rows that previously found no match")
    args = ap.parse_args()

    existing: dict[str, dict] = {}
    if OUT.exists():
        for line in OUT.read_text().splitlines():
            if line.strip():
                row = json.loads(line)
                existing[row["key"]] = row

    if args.retry_missing:
        existing = {k: v for k, v in existing.items() if v["match"] != "none"}
        OUT.write_text("".join(json.dumps(v, ensure_ascii=False) + "\n" for v in existing.values()))

    cache: dict[str, tuple[dict | None, str]] = {}
    new = 0
    with make_client() as client, OUT.open("a") as fh:
        client.params = oa_params()
        for psi in ALL_IDS:
            pubs = json.loads((INV_DIR / f"{psi}.json").read_text()).get("publications") or []
            for pub in pubs:
                if not (pub.get("title") or pub.get("doi")):
                    continue
                k = key_of(psi, pub)
                if k in existing:
                    continue
                doi = clean_doi(pub.get("doi"))
                ck = doi or norm_title(pub.get("title"))
                if ck not in cache:
                    work, how = None, "none"
                    try:
                        if doi:
                            work = by_doi(client, doi)
                            how = "doi" if work else how
                            time.sleep(PAUSE)
                        if not work and pub.get("title"):
                            work = by_title(client, pub["title"])
                            how = "title" if work else how
                            time.sleep(PAUSE)
                    except Exception as e:
                        print(f"{psi} ERROR {type(e).__name__}: {e} :: {pub.get('title', '')[:60]}")
                        continue  # not written, so a re-run retries it
                    cache[ck] = (work, how)
                work, how = cache[ck]
                row = record(psi, pub, work, how)
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                fh.flush()
                existing[k] = row
                new += 1

    rows = list(existing.values())
    per = defaultdict(Counter)
    for r in rows:
        c = per[r["psi_id"]]
        c["pubs"] += 1
        c[r["match"]] += 1
        c["abstract"] += bool(r["abstract"])
    print(f"\n{'id':<9} {'pubs':>5} {'doi':>5} {'title':>6} {'none':>5} {'abstr':>6}")
    for psi in ALL_IDS:
        c = per.get(psi, Counter())
        print(f"{psi:<9} {c['pubs']:>5} {c['doi']:>5} {c['title']:>6} {c['none']:>5} {c['abstract']:>6}")
    tot = Counter(r["match"] for r in rows)
    n_abs = sum(bool(r["abstract"]) for r in rows)
    print(f"\n{new} new rows this run, {len(rows)} total in {OUT.name}")
    print(f"matched by doi={tot['doi']} title={tot['title']} none={tot['none']}, abstracts={n_abs}")


if __name__ == "__main__":
    main()