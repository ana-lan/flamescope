"""Retrieval layer for FlameScope.

Part 1 (3.1): turn every text source into chunks with citation metadata.
Part 2 (3.2): embed chunks, write the on-disk index, search() it.

CLI (from backend/):
    uv run python -m flamescope.rag chunks [--show N]
    uv run python -m flamescope.rag index
    uv run python -m flamescope.rag search "query" [-k 5] [--psi PSI-69 ...] [--source abstract ...]
"""

from __future__ import annotations

import argparse
import functools
import hashlib
import json
import math
import os
import re
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

from flamescope.db import connect

BACKEND = Path(__file__).resolve().parents[1]
RAW = BACKEND / "data" / "raw"
CONTEXT_DIR = RAW / "context"
TABLE_DIR = RAW / "tables"
PROCESSED = BACKEND / "data" / "processed"

# bge-small reads at most 512 tokens and silently drops the rest.
# Scientific English runs ~1.3 to 1.5 tokens per word; 280 words (max ~320 after
# folding a short tail) stays under. 3.2 checks real token counts.
CHUNK_WORDS = 280
OVERLAP_WORDS = 40
MIN_WORDS = 5  # shorter than this is a placeholder ("N/A", "TBD"), not content

INV_FIELDS = ["objective", "approach", "hypothesis", "research_impacts", "hardware", "description"]

CONTEXT_DOCS = {
    "apollo_1": "Apollo 1 fire (1967)",
    "apollo_13": "Apollo 13 oxygen tank failure (1970)",
    "mir_1997": "Mir oxygen generator fire (1997)",
    "researchers_guide_combustion_2015": "Researcher's Guide to ISS Combustion Science (2015)",
}

FIGURE_INDEX_PSI = "PSI-142"

MODEL_NAME = "BAAI/bge-small-en-v1.5"
EMB_DIM = 384
MAX_TOKENS = 512
TOKEN_TARGET = 480  # slice size when a chunk overflows; leaves headroom under MAX_TOKENS
# bge v1.5 was trained with this instruction on the query side only.
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
EMB_PATH = PROCESSED / "embeddings.npy"
CHUNKS_PATH = PROCESSED / "chunks.parquet"
INDEX_META_PATH = PROCESSED / "index_meta.json"
MODEL_CACHE = BACKEND / ".cache" / "fastembed"
SOURCE_TYPES = ["investigation", "abstract", "context", "figure_index"]
RESULT_COLUMNS = [
    "chunk_id", "source_type", "psi_id", "experiment", "field", "title",
    "doi", "psi_doi", "url", "page_start", "page_end", "text",
]

COLUMNS = [
    "chunk_id", "source_type", "psi_id", "experiment", "field", "title",
    "doi", "psi_doi", "url", "page_start", "page_end", "n_words", "text_hash", "text",
]

_PAGE = re.compile(r"\[page (\d+)\]")
_WS = re.compile(r"\s+")


def clean(s) -> str:
    """Collapse whitespace; treat None/NaN as empty."""
    if s is None or (isinstance(s, float) and pd.isna(s)):
        return ""
    return _WS.sub(" ", str(s)).strip()


def blank_to_none(s):
    s = clean(s)
    return s or None


def text_hash(s: str) -> str:
    return hashlib.sha1(clean(s).lower().encode()).hexdigest()[:16]


def windows(words: list, size: int = CHUNK_WORDS, overlap: int = OVERLAP_WORDS):
    """Yield (start, end) word spans. The last window is never a tiny stub:
    if the tail would be under the overlap, the previous window absorbs it."""
    n = len(words)
    if n <= size:
        yield 0, n
        return
    step = size - overlap
    start = 0
    while start < n:
        end = min(start + size, n)
        if n - end < overlap:  # fold a tiny tail into this window
            end = n
        yield start, end
        if end == n:
            break
        start += step


def make_chunk(*, source_type, key, part, body, header, psi_id=None, experiment=None,
               field=None, title=None, doi=None, psi_doi=None, url=None,
               page_start=None, page_end=None) -> dict:
    # The header goes into the embedded text so a passage about "the burner"
    # still carries which experiment it belongs to.
    text = f"{header}\n{body}"
    return {
        "chunk_id": f"{source_type}:{key}:{part}",
        "source_type": source_type,
        "psi_id": psi_id,
        "experiment": experiment,
        "field": field,
        "title": title,
        "doi": doi,
        "psi_doi": psi_doi,
        "url": url,
        "page_start": page_start,
        "page_end": page_end,
        "n_words": len(body.split()),
        "text_hash": text_hash(body),
        "text": text,
    }


def split_body(body: str, **kw) -> list[dict]:
    words = body.split()
    return [make_chunk(part=i, body=" ".join(words[s:e]), **kw)
            for i, (s, e) in enumerate(windows(words))]


# ---------------------------------------------------------------- sources

def investigation_chunks(con) -> tuple[list[dict], dict]:
    df = con.execute(
        f"select psi_id, acronym, title, doi, {', '.join(INV_FIELDS)} from investigations order by psi_id"
    ).df()
    out, skipped_short, skipped_dup = [], 0, 0
    for r in df.itertuples(index=False):
        label = clean(r.acronym) or clean(r.title)  # ground studies have no acronym
        head = f"{label} ({r.psi_id})" + (f" | {clean(r.title)}" if clean(r.acronym) else "")
        seen = set()
        for field in INV_FIELDS:
            body = clean(getattr(r, field))
            if len(body.split()) < MIN_WORDS:
                skipped_short += 1
                continue
            h = text_hash(body)
            if h in seen:  # e.g. description copied from objective
                skipped_dup += 1
                continue
            seen.add(h)
            out += split_body(
                body, source_type="investigation", key=f"{r.psi_id}:{field}",
                header=f"{head} | {field.replace('_', ' ')}",
                psi_id=r.psi_id, experiment=label, field=field, title=clean(r.title),
                doi=blank_to_none(r.doi), psi_doi=blank_to_none(r.doi),
            )
    return out, {"skipped_short": skipped_short, "skipped_dup_in_psi": skipped_dup}


def abstract_chunks(con) -> tuple[list[dict], dict]:
    df = con.execute("""
        select p.pub_id, p.psi_id, p.title, p.authors, p.doi, p.abstract,
               coalesce(i.acronym, i.title) as label, i.doi as psi_doi
        from publications p join investigations i using (psi_id)
        where p.abstract is not null and trim(p.abstract) <> ''
        order by p.psi_id, p.pub_id
    """).df()
    out = []
    for r in df.itertuples(index=False):
        body = clean(r.abstract)
        if len(body.split()) < MIN_WORDS:
            continue
        out += split_body(
            body, source_type="abstract", key=f"{r.psi_id}:{r.pub_id}",
            header=f"{clean(r.label)} ({r.psi_id}) | paper: {clean(r.title)}",
            psi_id=r.psi_id, experiment=clean(r.label), field="abstract",
            title=clean(r.title), doi=blank_to_none(r.doi), psi_doi=blank_to_none(r.psi_doi),
        )
    return out, {"papers_with_abstract": len(df)}


def _context_meta() -> dict:
    """Read titles/urls from context/index.json if its shape allows; never fail on it."""
    path = CONTEXT_DIR / "index.json"
    meta = {}
    try:
        data = json.loads(path.read_text())
    except Exception:
        return meta
    entries = data if isinstance(data, list) else (
        [dict(v, slug=k) if isinstance(v, dict) else {"slug": k} for k, v in data.items()]
        if isinstance(data, dict) else [])
    for e in entries:
        if not isinstance(e, dict):
            continue
        blob = " ".join(str(v) for v in e.values())
        for slug in CONTEXT_DOCS:
            if slug in blob:
                meta.setdefault(slug, {})
                for k in ("url", "source_url", "source", "href"):
                    if isinstance(e.get(k), str) and e[k].startswith("http"):
                        meta[slug]["url"] = e[k]
                        break
    return meta


def _paged_words(raw: str) -> list[tuple[str, int | None]]:
    """Split text into (word, page) pairs using the [page N] markers from pypdf."""
    pairs, page = [], None
    for piece in _PAGE.split(raw):
        if piece.isdigit():
            page = int(piece)
        else:
            pairs += [(w, page) for w in piece.split()]
    return pairs


def context_chunks() -> tuple[list[dict], dict]:
    meta = _context_meta()
    out, per_doc = [], {}
    for slug, title in CONTEXT_DOCS.items():
        path = CONTEXT_DIR / f"{slug}.txt"
        if not path.exists():
            per_doc[slug] = "MISSING"
            continue
        raw = path.read_text(encoding="utf-8", errors="replace")
        # NASA pages left JSON escapes without the backslash: "u0022Gusu0022" -> "\"Gus\""
        raw = re.sub(r"u00([2-7][0-9a-fA-F])", lambda m: chr(int(m.group(1), 16)), raw)
        pairs = _paged_words(raw)
        if len(pairs) < MIN_WORDS:
            per_doc[slug] = "EMPTY"
            continue
        words = [w for w, _ in pairs]
        n0 = len(out)
        for i, (s, e) in enumerate(windows(words)):
            pages = [p for _, p in pairs[s:e] if p is not None]
            out.append(make_chunk(
                source_type="context", key=slug, part=i, body=" ".join(words[s:e]),
                header=f"{title}" + (f" | page {pages[0]}" if pages else ""),
                experiment=None, field=slug, title=title,
                url=meta.get(slug, {}).get("url"),
                page_start=min(pages) if pages else None,
                page_end=max(pages) if pages else None,
            ))
        per_doc[slug] = len(out) - n0
    return out, per_doc


def _read_csv(path: Path) -> pd.DataFrame:
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return pd.read_csv(path, dtype=str, keep_default_na=False, encoding=enc)
        except UnicodeDecodeError:
            continue
    raise RuntimeError(f"cannot decode {path}")


def figure_index_chunks(con) -> tuple[list[dict], dict]:
    files = sorted(TABLE_DIR.glob(f"{FIGURE_INDEX_PSI}_*.csv"))
    if not files:
        return [], {"files": 0}
    inv = con.execute("select title, doi from investigations where psi_id = ?", [FIGURE_INDEX_PSI]).fetchone()
    title, doi = (clean(inv[0]), blank_to_none(inv[1])) if inv else (FIGURE_INDEX_PSI, None)
    out, n_rows = [], 0
    for f in files:
        df = _read_csv(f)
        # One line per row, "column: value; ..." so the text reads like a sentence.
        lines = []
        for _, row in df.iterrows():
            cells = [f"{clean(c)}: {clean(v)}" for c, v in row.items() if clean(v)]
            if cells:
                lines.append("; ".join(cells))
        n_rows += len(lines)
        # Pack whole rows into chunks so no row is split mid-way.
        buf, part = [], 0
        def flush():
            nonlocal buf, part
            if buf:
                out.append(make_chunk(
                    source_type="figure_index", key=f"{FIGURE_INDEX_PSI}:{f.stem}", part=part,
                    body=" | ".join(buf), header=f"{title} ({FIGURE_INDEX_PSI}) | figure index",
                    psi_id=FIGURE_INDEX_PSI, experiment=title, field="figure_index",
                    title=title, doi=doi, psi_doi=doi,
                ))
                part += 1
                buf = []
        size = 0
        for line in lines:
            words = line.split()
            if len(words) > CHUNK_WORDS:  # one giant row: split it on its own
                flush()
                size = 0
                for s, e in windows(words):
                    buf.append(" ".join(words[s:e]))
                    flush()
                continue
            w = len(words) + 1  # +1 for the " | " separator
            if buf and size + w > CHUNK_WORDS:
                flush()
                size = 0
            buf.append(line)
            size += w
        flush()
    return out, {"files": len(files), "rows": n_rows}


# ---------------------------------------------------------------- build

def build_chunks(verbose: bool = False) -> pd.DataFrame:
    """All chunks as one DataFrame. Fails closed if a core source is empty."""
    con = connect()
    try:
        inv, inv_stats = investigation_chunks(con)
        abs_, abs_stats = abstract_chunks(con)
        fig, fig_stats = figure_index_chunks(con)
    finally:
        con.close()
    ctx, ctx_stats = context_chunks()

    rows, n_split = _fit_tokens(inv + abs_ + ctx + fig)
    df = pd.DataFrame(rows, columns=COLUMNS)
    for c in ("page_start", "page_end"):
        df[c] = df[c].astype("Int64")

    problems = []
    for st, rows in (("investigation", inv), ("abstract", abs_), ("context", ctx)):
        if not rows:
            problems.append(f"no {st} chunks")
    if df["chunk_id"].duplicated().any():
        problems.append(f"duplicate chunk_id: {df.loc[df.chunk_id.duplicated(), 'chunk_id'].tolist()[:5]}")
    over = df[df.n_words > CHUNK_WORDS + OVERLAP_WORDS]
    if len(over):
        problems.append(f"{len(over)} chunks over the word limit")
    if (df.n_words < 1).any():
        problems.append("empty chunk")
    if df.loc[df.source_type != "context", "psi_id"].isna().any():
        problems.append("non-context chunk without psi_id")

    if verbose:
        stats = {"investigation": inv_stats, "abstract": abs_stats,
                 "context": ctx_stats, "figure_index": fig_stats,
                 "token_split": {"chunks_split": n_split}}
        _report(df, stats)
    if problems:
        raise SystemExit("CHUNKS: FAIL\n  " + "\n  ".join(problems))
    return df


def _report(df: pd.DataFrame, stats: dict) -> None:
    print(f"total chunks: {len(df)}")
    g = df.groupby("source_type").agg(
        chunks=("chunk_id", "size"), words_min=("n_words", "min"),
        words_median=("n_words", "median"), words_max=("n_words", "max"))
    print(g.to_string())
    print("\nsource stats:")
    for k, v in stats.items():
        print(f"  {k}: {v}")
    inv = df[df.source_type == "investigation"]
    print(f"\ninvestigation chunks by field:\n{inv.field.value_counts().to_string()}")
    print(f"\npsi_ids covered (non-context): {df.psi_id.nunique()}")
    dup = df[df.source_type == "abstract"].text_hash.duplicated().sum()
    print(f"abstract chunks sharing text with another psi_id: {dup}")
    print(f"chunks with a doi: {df.doi.notna().sum()}, with psi_doi: {df.psi_doi.notna().sum()}")
    ctx = df[df.source_type == "context"]
    if len(ctx):
        print(f"context chunks with page numbers: {ctx.page_start.notna().sum()}")


# ---------------------------------------------------------------- index (3.2)

@functools.lru_cache(maxsize=1)
def _model():
    from fastembed import TextEmbedding  # lazy: the `chunks` CLI should not load ONNX
    MODEL_CACHE.mkdir(parents=True, exist_ok=True)
    return TextEmbedding(model_name=MODEL_NAME, cache_dir=str(MODEL_CACHE))


def _normalize(m) -> np.ndarray:
    m = np.asarray(m, dtype=np.float32)
    norms = np.linalg.norm(m, axis=-1, keepdims=True)
    return m / np.clip(norms, 1e-12, None)


def embed_passages(texts: list[str], batch_size: int = 32) -> np.ndarray:
    return _normalize(np.vstack(list(_model().embed(texts, batch_size=batch_size))))


def embed_query(query: str) -> np.ndarray:
    return _normalize(next(iter(_model().embed([QUERY_PREFIX + clean(query)]))))


@functools.lru_cache(maxsize=1)
def _tokenizer():
    from tokenizers import Tokenizer
    tok = Tokenizer.from_pretrained(MODEL_NAME)
    tok.no_truncation()
    tok.no_padding()
    return tok


def token_counts(texts: list[str]):
    """Real bge token counts with truncation off, or None if the tokenizer can't load."""
    try:
        tok = _tokenizer()
    except Exception as e:
        print(f"  token check skipped: {type(e).__name__}: {e}")
        return None
    return [len(enc.ids) for enc in tok.encode_batch(texts)]


def _fit_tokens(rows: list[dict]) -> tuple[list[dict], int]:
    """Split any chunk over MAX_TOKENS into equal word slices of ~TOKEN_TARGET tokens.
    Chunks that fit keep their id; split ones become <id>.0, <id>.1, ..."""
    counts = token_counts([r["text"] for r in rows])
    if counts is None:
        return rows, 0
    out, n_split = [], 0
    for r, n_tok in zip(rows, counts):
        if n_tok <= MAX_TOKENS:
            out.append(r)
            continue
        n_split += 1
        header, body = r["text"].split("\n", 1)
        words = body.split()
        pieces = math.ceil(n_tok / TOKEN_TARGET)
        size = math.ceil(len(words) / pieces)
        for j in range(pieces):
            part = words[j * size:(j + 1) * size]
            if not part:
                continue
            b = " ".join(part)
            out.append({**r, "chunk_id": f"{r['chunk_id']}.{j}", "text": f"{header}\n{b}",
                        "n_words": len(part), "text_hash": text_hash(b)})
    return out, n_split


def _chunks_sha(df: pd.DataFrame) -> str:
    """Fingerprint of row order + text: ties embeddings.npy to chunks.parquet."""
    h = hashlib.sha1()
    for cid, text in zip(df["chunk_id"], df["text"]):
        h.update(cid.encode())
        h.update(b"\0")
        h.update(text.encode())
        h.update(b"\0")
    return h.hexdigest()[:16]


def _write_atomic(path: Path, write) -> None:
    tmp = path.with_name(path.name + ".tmp")
    write(tmp)
    os.replace(tmp, path)


def build_index() -> None:
    t0 = time.time()
    df = build_chunks(verbose=False)
    texts = df["text"].tolist()

    toks = token_counts(texts)
    if toks is not None:
        df["n_tokens"] = pd.array(toks, dtype="Int64")
        over = df[df["n_tokens"] > MAX_TOKENS]
        print(f"tokens: max {max(toks)}, median {int(np.median(toks))}, over {MAX_TOKENS}: {len(over)}")
        for r in over.itertuples():
            print(f"  will be truncated: {r.chunk_id} ({r.n_tokens} tokens)")
    else:
        df["n_tokens"] = pd.array([None] * len(df), dtype="Int64")

    print(f"embedding {len(texts)} chunks with {MODEL_NAME} (first run downloads the model) ...")
    emb = embed_passages(texts)
    t1 = time.time()

    problems = []
    if emb.shape != (len(df), EMB_DIM):
        problems.append(f"shape {emb.shape}, expected {(len(df), EMB_DIM)}")
    if not np.isfinite(emb).all():
        problems.append("non-finite values in embeddings")
    elif not np.allclose(np.linalg.norm(emb, axis=1), 1.0, atol=1e-3):
        problems.append("vectors are not unit length")
    if problems:
        raise SystemExit("INDEX: FAIL\n  " + "\n  ".join(problems))

    meta = {
        "model": MODEL_NAME,
        "dim": EMB_DIM,
        "n_chunks": int(len(df)),
        "chunks_sha": _chunks_sha(df),
        "query_prefix": QUERY_PREFIX,
        "by_source": {k: int(v) for k, v in df["source_type"].value_counts().items()},
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }

    PROCESSED.mkdir(parents=True, exist_ok=True)

    def save_npy(p):
        with open(p, "wb") as f:  # file handle: np.save(path) would append ".npy" to the tmp name
            np.save(f, emb)

    _write_atomic(EMB_PATH, save_npy)
    _write_atomic(CHUNKS_PATH, lambda p: df.to_parquet(p, index=False))
    _write_atomic(INDEX_META_PATH, lambda p: p.write_text(json.dumps(meta, indent=2)))  # meta last
    load_index.cache_clear()

    # Self-check: each chunk's nearest neighbour should be itself.
    sims = emb @ emb.T
    self_top1 = float((sims.argmax(axis=1) == np.arange(len(df))).mean())
    print(f"embedded in {t1 - t0:.1f}s; self top-1 = {self_top1:.3f}")
    for p in (EMB_PATH, CHUNKS_PATH, INDEX_META_PATH):
        print(f"  {p.relative_to(BACKEND)}  {p.stat().st_size:,} bytes")
    print(f"meta: n_chunks={meta['n_chunks']} sha={meta['chunks_sha']} by_source={meta['by_source']}")
    print("INDEX: PASS")


@functools.lru_cache(maxsize=1)
def load_index():
    """(embeddings, chunks, meta). Refuses files that don't belong together."""
    missing = [p.name for p in (EMB_PATH, CHUNKS_PATH, INDEX_META_PATH) if not p.exists()]
    if missing:
        raise RuntimeError(f"index missing {missing}: run `uv run python -m flamescope.rag index`")
    emb = np.load(EMB_PATH)
    df = pd.read_parquet(CHUNKS_PATH)
    meta = json.loads(INDEX_META_PATH.read_text())
    if (meta.get("model") != MODEL_NAME
            or emb.shape != (len(df), meta.get("dim"))
            or len(df) != meta.get("n_chunks")
            or _chunks_sha(df) != meta.get("chunks_sha")):
        raise RuntimeError("index files out of sync: run `uv run python -m flamescope.rag index`")
    return emb, df, meta


def _py(v):
    """numpy/pandas scalars -> plain Python (JSON-safe for the API)."""
    if v is None:
        return None
    if not isinstance(v, str) and pd.isna(v):
        return None
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, np.floating):
        return float(v)
    return v


def search(query: str, k: int = 5, psi_ids=None, source_types=None, dedupe: bool = True) -> list[dict]:
    """Cosine top-k. Filters are applied before ranking, so you always get k hits if k exist."""
    emb, df, _ = load_index()
    scores = emb @ embed_query(query)

    mask = np.ones(len(df), dtype=bool)
    if psi_ids:
        mask &= df["psi_id"].isin([p.strip().upper() for p in psi_ids]).to_numpy()
    if source_types:
        mask &= df["source_type"].isin(source_types).to_numpy()

    idx = np.flatnonzero(mask)
    order = idx[np.argsort(-scores[idx], kind="stable")]

    out, seen = [], set()
    for i in order:
        row = df.iloc[i]
        if dedupe:
            if row["text_hash"] in seen:  # same abstract filed under two investigations
                continue
            seen.add(row["text_hash"])
        hit = {c: _py(row[c]) for c in RESULT_COLUMNS}
        hit["score"] = round(float(scores[i]), 4)
        out.append(hit)
        if len(out) >= k:
            break
    return out


# ---------------------------------------------------------------- CLI

def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="flamescope.rag")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("chunks", help="build chunks and print a report")
    c.add_argument("--show", type=int, default=0, help="print N sample chunks per source type")
    sub.add_parser("index", help="embed chunks; write embeddings.npy, chunks.parquet, index_meta.json")
    s = sub.add_parser("search", help="query the index")
    s.add_argument("query")
    s.add_argument("-k", type=int, default=5)
    s.add_argument("--psi", nargs="*", default=None, help="restrict to these PSI ids")
    s.add_argument("--source", nargs="*", default=None, choices=SOURCE_TYPES)
    args = ap.parse_args(argv)

    if args.cmd == "chunks":
        df = build_chunks(verbose=True)
        if args.show:
            for st, g in df.groupby("source_type"):
                print(f"\n=== {st} samples ===")
                for r in g.head(args.show).itertuples():
                    print(f"[{r.chunk_id}] words={r.n_words} doi={r.doi} pages={r.page_start}-{r.page_end}")
                    print("  " + r.text[:300].replace("\n", "\n  ") + ("..." if len(r.text) > 300 else ""))
        print("\nCHUNKS: PASS")

    elif args.cmd == "index":
        build_index()

    elif args.cmd == "search":
        t = time.time()
        hits = search(args.query, k=args.k, psi_ids=args.psi, source_types=args.source)
        print(f'query: "{args.query}"  ({(time.time() - t) * 1000:.0f} ms incl. model load)')
        for rank, h in enumerate(hits, 1):
            where = h["psi_id"] or h["field"]
            pages = f" p.{h['page_start']}-{h['page_end']}" if h["page_start"] else ""
            print(f"{rank}. {h['score']:.3f}  [{where}] {h['source_type']}/{h['field']}{pages}")
            print("   " + h["text"].split("\n", 1)[-1][:160])


if __name__ == "__main__":
    main()
