"""Save mission-context pages and the 2015 Researcher's Guide as plain text.

Usage (from backend/):
    uv run python ingest/context.py [--force]

If a PDF download fails, drop the file at data/raw/context/<name>.pdf and re-run.
"""
from __future__ import annotations

import argparse
import io
import json
import re
from datetime import date

import httpx
from bs4 import BeautifulSoup
from pypdf import PdfReader

from psi import RAW, get, write_atomic

CTX = RAW / "context"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")

SOURCES = {
    "apollo_1": {
        "kind": "html", "title": "Apollo 1",
        "urls": ["https://www.nasa.gov/mission/apollo-1/"],
    },
    "apollo_13": {
        "kind": "html", "title": "Apollo 13",
        "urls": ["https://www.nasa.gov/mission/apollo-13/"],
    },
    "mir_1997": {
        "kind": "html", "title": "25 Years Ago: Fire Aboard Space Station Mir",
        "urls": [
            "https://www.nasa.gov/?p=96281",
            "https://www.nasa.gov/history/25-years-ago-fire-aboard-space-station-mir/",
        ],
    },
    "researchers_guide_combustion_2015": {
        "kind": "pdf", "title": "A Researcher's Guide to: Combustion Science (ISS, 2015)",
        "urls": [
            "https://www.nasa.gov/sites/default/files/atoms/files/"
            "np-2015-10-034-jsc_combustion_in_reduced_gravity-iss-mini-book-011116-508.pdf",
        ],
    },
}
MIN_CHARS = {"html": 1500, "pdf": 20000}


def html_to_text(html: str) -> tuple[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    title = (soup.title.string or "").strip() if soup.title else ""
    for tag in soup(["script", "style", "noscript", "nav", "header", "footer",
                     "aside", "form", "svg", "button"]):
        tag.decompose()
    root = soup.find("main") or soup.find("article") or soup.body or soup
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in root.get_text("\n").splitlines()]
    text = "\n".join(ln for ln in lines if len(ln) > 2)
    return title, re.sub(r"\n{3,}", "\n\n", text)


def pdf_to_text(data: bytes) -> str:
    reader = PdfReader(io.BytesIO(data))
    pages = []
    for i, page in enumerate(reader.pages, 1):
        t = re.sub(r"[ \t]+", " ", page.extract_text() or "").strip()
        if t:
            pages.append(f"[page {i}]\n{t}")
    return "\n\n".join(pages)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    CTX.mkdir(parents=True, exist_ok=True)

    index = []
    failures = 0
    print(f"{'name':<36} {'status':<8} {'chars':>7}  source")
    with httpx.Client(timeout=90, follow_redirects=True, headers={"User-Agent": UA}) as client:
        for name, src in SOURCES.items():
            out = CTX / f"{name}.txt"
            status, used = "cached", None
            if args.force or not out.exists():
                text, page_title, err = None, src["title"], None
                local_pdf = CTX / f"{name}.pdf"
                if src["kind"] == "pdf" and local_pdf.exists():
                    text, used = pdf_to_text(local_pdf.read_bytes()), str(local_pdf.name)
                for url in ([] if text else src["urls"]):
                    try:
                        r = get(client, url)
                        if src["kind"] == "pdf":
                            write_atomic(local_pdf, r.content)
                            text = pdf_to_text(r.content)
                        else:
                            t, text = html_to_text(r.text)
                            page_title = t or page_title
                        used = str(r.url)
                        break
                    except Exception as e:
                        err = f"{type(e).__name__}: {e}"
                if not text:
                    failures += 1
                    print(f"{name:<36} {'FAILED':<8} {'':>7}  {err}")
                    continue
                header = (f"title: {page_title}\nsource: {used}\n"
                          f"fetched: {date.today().isoformat()}\n\n")
                write_atomic(out, (header + text).encode())
                status = "fetched"
            body = out.read_text()
            m = re.search(r"^source: (.*)$", body, re.M)
            used = m.group(1) if m else used
            n = len(body)
            if n < MIN_CHARS[src["kind"]]:
                status = "SHORT"
            index.append({"name": name, "title": src["title"], "kind": src["kind"],
                          "source": used, "chars": n})
            print(f"{name:<36} {status:<8} {n:>7}  {used}")

    write_atomic(CTX / "index.json", json.dumps(index, indent=2).encode())
    print(f"\n{len(index)}/{len(SOURCES)} context docs in {CTX.relative_to(RAW.parents[1])}")
    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()