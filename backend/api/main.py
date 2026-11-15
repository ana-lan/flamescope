"""FlameScope HTTP API.

GET endpoints for data and coverage, POST /ask for the agent (SSE or JSON).
Response shapes are pydantic models in api/schemas.py; docs/api.md describes them.

Run (from backend/):
    uv run uvicorn api.main:app --reload --port 8000
    open http://localhost:8000/docs
"""
from __future__ import annotations

import asyncio
import functools
import json
import logging
import os
import re
import time
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse
from starlette.concurrency import iterate_in_threadpool, run_in_threadpool

from api.schemas import (AskFinal, Coverage, Facets, Habitat, HabitatSlug, Health, Insight,
                         InvestigationDetail, InvestigationSummary, Suggested, TestsPage)
from flamescope import agent, conditions, rag, tools
from flamescope.db import connect
from flamescope.tools import _val

VERSION = "0.3.1"
log = logging.getLogger("flamescope.api")

CORE_COLS = ["test_pk", "psi_id", "experiment", "test_id", "fuel", "material", "pressure_kpa", "o2_frac",
             "diluent", "diluent_frac", "flow_cm_s", "outcome", "burn_time_s", "spread_rate_mm_s"]
MAX_LIMIT = 1000
STATE: dict = {"started_at": None, "warm": {}, "warm_s": None}


# ---------------------------------------------------------------- helpers

def _rows(sql: str, params: list | None = None) -> list[dict]:
    """Run a read-only query; rows as JSON-safe dicts (lists, Decimal, NaN handled)."""
    con = connect()
    try:
        cur = con.execute(sql, params or [])
        cols = [d[0] for d in cur.description]
        return [{c: _val(v) for c, v in zip(cols, row)} for row in cur.fetchall()]
    finally:
        con.close()


def _doi_url(doi: str | None) -> str | None:
    return f"https://doi.org/{doi}" if doi else None


@functools.lru_cache(maxsize=1)
def _inv_index() -> dict:
    return {r["psi_id"]: {"acronym": r["acronym"], "title": r["title"], "doi": r["doi"] or None,
                          "doi_url": _doi_url(r["doi"])}
            for r in _rows("select psi_id, acronym, title, doi from investigations")}


# ---------------------------------------------------------------- app

@asynccontextmanager
async def lifespan(app: FastAPI):
    t0, warm = time.time(), {}
    for name, fn in [("tests", conditions._tested), ("index", rag.load_index),
                     ("embedder", rag._model), ("tool_specs", tools.tool_specs)]:
        try:
            fn()
            warm[name] = "ok"
        except Exception as e:  # report in /health instead of crashing the server
            warm[name] = f"error: {type(e).__name__}: {e}"
            log.error("warm-up %s failed: %s", name, e)
    STATE.update(started_at=time.time(), warm=warm, warm_s=round(time.time() - t0, 2))
    yield


app = FastAPI(
    title="FlameScope API",
    version=VERSION,
    description="ISS combustion test data, habitat coverage and a cited fire safety agent. "
                "Data: NASA Physical Sciences Informatics (CC0). Cite investigations by PSI id and DOI.",
    lifespan=lifespan,
)

_origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",")
            if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_origin_regex=os.getenv("CORS_ORIGIN_REGEX", r"https://flamescope[\w-]*\.vercel\.app"),
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


class SelectiveGZip:
    """Gzip everything except /ask: compression buffers output and would stall the SSE stream."""

    def __init__(self, app, minimum_size: int = 1000):
        self.app = app
        self.gzip = GZipMiddleware(app, minimum_size=minimum_size)

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["path"].startswith("/ask"):
            return await self.app(scope, receive, send)
        return await self.gzip(scope, receive, send)


app.add_middleware(SelectiveGZip, minimum_size=1000)


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/docs")


@app.get("/health", tags=["meta"], response_model=Health)
def health():
    counts = _rows("""select (select count(*) from tests) as tests,
                             (select count(*) from investigations) as investigations,
                             (select count(*) from insights) as insights,
                             (select count(*) from habitats) as habitats""")[0]
    try:
        _, chunks, meta = rag.load_index()
        index = {"chunks": len(chunks), "model": meta["model"]}
    except Exception as e:
        index = {"error": str(e)}
    try:
        chain = [f"{p}:{m}" for p, m in agent.parse_chain()]  # names only, never keys
    except Exception:
        chain = []
    ok = all(v == "ok" for v in STATE["warm"].values()) and "error" not in index
    return {
        "status": "ok" if ok else "degraded",
        "version": VERSION,
        "db": counts,
        "index": index,
        "llm_chain": chain,
        "warm": STATE["warm"],
        "warm_s": STATE["warm_s"],
        "uptime_s": round(time.time() - STATE["started_at"], 1) if STATE["started_at"] else None,
    }


@app.get("/habitats", tags=["habitats"], response_model=list[Habitat])
def habitats():
    """Atmosphere presets (NASA-sourced). Apollo 1 is a historical reference, not a design target."""
    return conditions.list_habitats()


@functools.lru_cache(maxsize=1)
def _insights_all() -> list[dict]:
    inv = _inv_index()
    out = []
    for r in _rows("select * from insights order by rank"):
        if isinstance(r.get("detail"), str):
            try:
                r["detail"] = json.loads(r["detail"])
            except json.JSONDecodeError:
                pass
        r["sources"] = [{"psi_id": p, **inv.get(p, {})} for p in (r.get("source_psi_ids") or [])]
        out.append(r)
    return out


@app.get("/insights", tags=["insights"], response_model=list[Insight])
def insights(habitat: HabitatSlug | None = None):
    """Ranked, precomputed findings. With ?habitat=, only those tagged for it (or 'all')."""
    rows = _insights_all()
    if habitat:
        rows = [r for r in rows if not r.get("habitats") or habitat in r["habitats"] or "all" in r["habitats"]]
    return rows


@app.get("/tests", tags=["tests"], response_model=TestsPage)
def list_tests(
    experiment: Annotated[list[str] | None, Query(description="repeatable, exact name e.g. FLEX")] = None,
    psi_id: Annotated[list[str] | None, Query(description="repeatable, e.g. PSI-69")] = None,
    outcome: Annotated[list[str] | None, Query(description="repeatable, e.g. extinction")] = None,
    fuel: Annotated[str | None, Query(description="substring match on fuel or material")] = None,
    p_min: Annotated[float | None, Query(ge=0, description="kPa")] = None,
    p_max: Annotated[float | None, Query(ge=0, description="kPa")] = None,
    o2_min: Annotated[float | None, Query(ge=0, le=1, description="fraction, 0.21 = 21%")] = None,
    o2_max: Annotated[float | None, Query(ge=0, le=1, description="fraction")] = None,
    single_only: bool = False,
    include_duplicates: bool = False,
    include_raw: bool = False,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = 200,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    """Filterable test rows. Defaults: duplicates excluded, summary rows included, raw CSV row omitted."""
    where, params = [], []

    def in_list(col: str, values: list[str]):
        where.append(f"{col} in ({', '.join('?' * len(values))})")
        params.extend(values)

    if experiment:
        in_list("experiment", experiment)
    if psi_id:
        in_list("psi_id", [p.strip().upper() for p in psi_id])
    if outcome:
        in_list("outcome", outcome)
    if fuel:
        where.append("(fuel ilike ? or material ilike ?)")
        params += [f"%{fuel}%", f"%{fuel}%"]
    for col, op, v in (("pressure_kpa", ">=", p_min), ("pressure_kpa", "<=", p_max),
                       ("o2_frac", ">=", o2_min), ("o2_frac", "<=", o2_max)):
        if v is not None:
            where.append(f"{col} {op} ?")
            params.append(v)
    if single_only:
        where.append("extra->>'row_kind' is null")
    if not include_duplicates:
        where.append("coalesce(extra->>'is_duplicate', 'false') <> 'true'")
    w = ("where " + " and ".join(where)) if where else ""

    total = _rows(f"select count(*) as n from tests {w}", params)[0]["n"]
    rows = _rows(f"select {', '.join(CORE_COLS)}, extra from tests {w} "
                 f"order by experiment, test_pk limit ? offset ?", params + [limit, offset])
    for r in rows:
        extra = json.loads(r["extra"]) if isinstance(r["extra"], str) else (r["extra"] or {})
        if not include_raw:
            extra.pop("raw", None)
        r["extra"] = extra
    return {"total": total, "limit": limit, "offset": offset, "rows": rows}


@functools.lru_cache(maxsize=1)
def _facets() -> dict:
    return {
        "experiments": _rows("""
            select experiment, psi_id, count(*) as n,
                   count(*) filter (where outcome is not null) as n_outcome,
                   count(*) filter (where pressure_kpa is not null and o2_frac is not null) as n_conditions,
                   count(*) filter (where extra->>'row_kind' = 'summary') as n_summary
            from tests group by 1, 2 order by n desc"""),
        "outcomes": _rows("select outcome, count(*) as n from tests where outcome is not null "
                          "group by 1 order by n desc"),
        "fuels": _rows("select coalesce(fuel, material) as fuel, count(*) as n from tests "
                       "where coalesce(fuel, material) is not null group by 1 order by n desc limit 60"),
        "ranges": _rows("select min(pressure_kpa) as p_min, max(pressure_kpa) as p_max, "
                        "min(o2_frac) as o2_min, max(o2_frac) as o2_max from tests")[0],
    }


@app.get("/tests/facets", tags=["tests"], response_model=Facets)
def tests_facets():
    """Filter options with counts for the experiment explorer."""
    return _facets()


@functools.lru_cache(maxsize=1)
def _investigations_list() -> list[dict]:
    rows = _rows("""
        select i.psi_id, i.acronym, i.title, i.project_type, i.mission_name, i.doi, i.n_publications,
               coalesce(t.n, 0) as n_tests
        from investigations i
        left join (select psi_id, count(*) as n from tests group by 1) t using (psi_id)
        order by cast(split_part(i.psi_id, '-', 2) as integer)""")
    for r in rows:
        r["doi_url"] = _doi_url(r["doi"])
    return rows


@app.get("/investigations", tags=["investigations"], response_model=list[InvestigationSummary])
def investigations():
    return _investigations_list()


@app.get("/investigations/{psi_id}", tags=["investigations"], response_model=InvestigationDetail)
def investigation(psi_id: str):
    """Full metadata, text fields, test stats and publications for one investigation."""
    pid = psi_id.strip().upper()
    rows = _rows("select * from investigations where psi_id = ?", [pid])
    if not rows:
        raise HTTPException(status_code=404, detail=f"unknown psi_id {pid}")
    inv = {**rows[0], "doi_url": _doi_url(rows[0].get("doi"))}
    pubs = _rows("""
        select pub_id, title, authors, doi, (abstract is not null and trim(abstract) <> '') as has_abstract
        from publications where psi_id = ? order by has_abstract desc, title""", [pid])
    for p in pubs:
        p["doi_url"] = _doi_url(p["doi"])
    stats = tools.get_investigation(pid)
    return {"investigation": inv, "cite_as": stats["cite_as"], "tests": stats["tests"], "publications": pubs}


@app.get("/coverage", tags=["habitats"], response_model=Coverage)
def coverage(habitat: HabitatSlug, per_experiment: Annotated[int, Query(ge=1, le=10)] = 3):
    """Nearest tested conditions for a habitat, verdict, per-experiment rollup, and all tested points."""
    return conditions.coverage(habitat, per_experiment)


# ---------------------------------------------------------------- /ask

ASK_SLOTS = asyncio.Semaphore(int(os.getenv("ASK_CONCURRENCY", "2")))
CACHE_PATH = rag.PROCESSED / "demo_cache.json"
_CACHE: dict = {"mtime": None, "data": {}}
BUSY = "FlameScope is answering other questions right now. Try a suggested question, or ask again in a minute."
ALL_FAILED = "All language models are busy or rate-limited right now. Try a suggested question, or ask again in a minute."


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=500)
    habitat: HabitatSlug | None = None
    stream: bool = True
    fresh: bool = False  # skip the demo cache


def _norm_q(q: str) -> str:
    q = re.sub(r"\s+", " ", q.strip().lower())
    return re.sub(r"[\s?.!]+$", "", q)


def cache_key(question: str, habitat: str | None) -> str:
    """Case, whitespace and trailing punctuation are ignored; everything else must match."""
    return f"{habitat or '-'}|{_norm_q(question)}"


def _cache_load() -> dict:
    try:
        mtime = CACHE_PATH.stat().st_mtime
    except FileNotFoundError:
        _CACHE.update(mtime=None, data={})
        return _CACHE["data"]
    if mtime != _CACHE["mtime"]:  # reload when the check script rewrites the file
        _CACHE.update(mtime=mtime, data=json.loads(CACHE_PATH.read_text()))
    return _CACHE["data"]


def _cache_get(question: str, habitat: str | None) -> dict | None:
    return _cache_load().get(cache_key(question, habitat))


def _sse(ev: dict) -> dict:
    return {"event": ev["type"], "data": json.dumps({k: v for k, v in ev.items() if k != "type"}, default=str)}


async def _tokens(text: str):
    """The answer is final when it arrives; send it a few words at a time. The concatenated
    token texts equal final.answer exactly."""
    words = re.findall(r"\s*\S+\s*", text) if text[:1].isspace() else re.findall(r"\S+\s*", text)
    for i in range(0, len(words), 3):
        yield {"event": "token", "data": json.dumps({"text": "".join(words[i:i + 3])})}
        await asyncio.sleep(0.015)


async def _live(req: AskRequest):
    async with ASK_SLOTS:
        try:
            async for ev in iterate_in_threadpool(agent.run(req.question, req.habitat)):
                if ev["type"] == "answer":
                    async for t in _tokens(ev["text"]):
                        yield t
                    continue
                if ev["type"] == "final":
                    ev = {**ev, "cached": False}
                yield _sse(ev)
        except agent.AllModelsFailed:
            yield {"event": "error", "data": json.dumps({"message": ALL_FAILED})}
        except Exception as e:  # never leak a traceback to the browser
            log.exception("ask failed")
            yield {"event": "error", "data": json.dumps({"message": f"Something went wrong ({type(e).__name__})."})}


async def _replay(final: dict):
    """Replay a recorded, checked run in exactly the live event format:
    start, (status, tool_call, tool_result) per step, status, tokens, final."""
    steps = final.get("steps", [])
    yield _sse({"type": "start", "question": final["question"], "habitat": final.get("habitat")})
    for i, s in enumerate(steps):
        yield _sse({"type": "status", "stage": "thinking", "turn": i})
        await asyncio.sleep(0.15)
        yield _sse({"type": "tool_call", "tool": s["tool"], "args": s["args"], "model": final.get("model")})
        await asyncio.sleep(0.25)
        yield _sse({"type": "tool_result", "tool": s["tool"], "summary": s["summary"]})
    yield _sse({"type": "status", "stage": "thinking", "turn": len(steps)})
    await asyncio.sleep(0.15)
    async for t in _tokens(final["answer"]):
        yield t
    yield _sse({"type": "final", **final, "cached": True})


@app.post("/ask", tags=["agent"], response_model=AskFinal)
async def ask(req: AskRequest):
    """Ask FlameScope. stream=true (default): SSE events start, status, tool_call, tool_result,
    token, final (or error). stream=false: one JSON object, the same as the final event."""
    cached = None if req.fresh else _cache_get(req.question, req.habitat)

    if not req.stream:
        if cached:
            return {**cached, "cached": True}
        if ASK_SLOTS.locked():
            raise HTTPException(status_code=429, detail=BUSY)
        async with ASK_SLOTS:
            try:
                final = await run_in_threadpool(agent.ask, req.question, req.habitat)
            except agent.AllModelsFailed:
                raise HTTPException(status_code=503, detail=ALL_FAILED)
        return {**final, "cached": False}

    if cached:
        return EventSourceResponse(_replay(cached), ping=10)
    if ASK_SLOTS.locked():
        raise HTTPException(status_code=429, detail=BUSY)
    return EventSourceResponse(_live(req), ping=10)


@app.get("/ask/suggested", tags=["agent"], response_model=list[Suggested])
def suggested(habitat: HabitatSlug | None = None):
    """Questions with a recorded, checked answer. Asking one replays it in the live stream format."""
    out = [{"question": v["question"], "habitat": v.get("habitat"), "model": v.get("model"),
            "cached_at": v.get("cached_at")} for v in _cache_load().values()]
    if habitat:
        out = [s for s in out if s["habitat"] in (None, habitat)]
    return out