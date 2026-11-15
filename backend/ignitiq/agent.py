"""IgnitIQ agent: an LLM tool loop over the 4 tools in tools.py.

Provider-agnostic: any OpenAI-compatible endpoint. LLM_CHAIN (backend/.env) lists
provider:model entries in priority order. On a rate limit the agent waits for the
provider's reset when it is short; otherwise it moves to the next entry and stays
there for the rest of the question. Every attempt is logged in llm_trace.

Every answer is verified: each citation against what the tools returned, and each
number against a tagged tool source (and the citation of its sentence).

CLI (from backend/):
    uv run python -m ignitiq.agent --ping
    uv run python -m ignitiq.agent --budget
    uv run python -m ignitiq.agent "question" [--habitat lunar] [--model groq:openai/gpt-oss-120b] [--json]
"""
from __future__ import annotations

import argparse
import functools
import json
import logging
import math
import os
import re
import time
from dataclasses import dataclass, field
from typing import Iterator

import openai
from dotenv import load_dotenv
from openai import OpenAI

from ignitiq import conditions, rag
from ignitiq.db import connect
from ignitiq.tools import run_tool, to_text, tool_specs

log = logging.getLogger("ignitiq.agent")
load_dotenv(rag.BACKEND / ".env")

PROVIDERS = {
    "groq": {"base_url": "https://api.groq.com/openai/v1", "key_env": "GROQ_API_KEY", "timeout": 60},
    "openrouter": {"base_url": "https://openrouter.ai/api/v1", "key_env": "OPENROUTER_API_KEY", "timeout": 90},
    "ollama": {"base_url": os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1"), "key_env": None,
               "timeout": 300},
}
DEFAULT_CHAIN = (
    "groq:openai/gpt-oss-120b,"
    "groq:qwen/qwen3.8-27b,"
    "openrouter:nvidia/nemotron-3-ultra-550b-a55b:free,"
    "openrouter:google/gemma-4-31b-it:free,"
    "ollama:qwen3:8b"
)

MAX_TURNS = 6
REPAIR_ROUNDS = 1               # one rewrite when the number check fails (eval Q3, Q10, Q14)
MAX_OUTPUT_TOKENS = 1500        # Groq reserves requested output tokens against the per-minute limit
TEMPERATURE = 0.1
TOOL_RESULT_CHARS = 3500        # what the model sees per tool result
PASSAGE_CHARS_FOR_MODEL = 600
MAX_K = 4
MAX_PER_EXPERIMENT = 2
MODEL_TEXT_CHARS = 500
MODEL_PUBS = 6
NEAREST_EXPS_FOR_MODEL = 3
TRACE_ROWS = 20
MAX_RATE_WAIT_S = 30.0
MAX_WAITS = 4
MODEL_MAX_TOKENS = {"groq:qwen/qwen3.8-27b": 900}            # Groq OTPM limit is 1000 for qwen
MODEL_EXTRA = {"groq:openai/gpt-oss-120b": {"reasoning_effort": "low"}}  # fewer hidden tokens, faster
FORCE_FAIL_ENV = "FLAMESCOPE_FORCE_LLM_FAIL"                   # tests only: every model call fails

CONTEXT_REFS = {
    "apollo_1": "apollo_1",
    "apollo_13": "apollo_13",
    "mir_1997": "mir_1997",
    "guide_2015": "researchers_guide_combustion_2015",
}
SLUG_TO_REF = {v: k for k, v in CONTEXT_REFS.items()}

SYSTEM_PROMPT = """You are IgnitIQ, a fire safety analyst for spacecraft and habitats. You answer from NASA PSI records of ISS combustion experiments, using your tools.

- Every number about tests must come from a query_tests or nearest_conditions result. Compute totals, ratios and percentages in SQL. Never estimate or do arithmetic yourself.
- Write the one query that answers the question. Skip exploratory queries.
- For a habitat or atmosphere question, call nearest_conditions first and state its verdict. If it is sparse, near_only or untested, say the data does not directly cover those conditions.
- Use search_docs for mechanisms and history. For a past incident (Apollo 1, Apollo 13, Mir), search it and cite its NASA document. If the question names a material or fuel, first check with query_tests whether it was tested. If the tools cannot answer, say what is missing.
- After each factual sentence cite its source: [PSI-69] for an investigation, or [NASA:apollo_1], [NASA:apollo_13], [NASA:mir_1997], [NASA:guide_2015]. Cite only sources your tools returned. Never put a tool name or raw values inside brackets. Habitat values need no citation.
- O2 fraction and O2 partial pressure differ. Apollo 1 is history, never a design target. NULL outcome means not recorded. These are microgravity results; lunar and Martian gravity add buoyant flow.

Answer first, then the evidence. Under 150 words, no tables, no em dashes."""


# ---------------------------------------------------------------- providers

def parse_chain(spec: str | None = None) -> list[tuple[str, str]]:
    spec = spec or os.getenv("LLM_CHAIN") or DEFAULT_CHAIN
    chain = []
    for item in spec.split(","):
        item = item.strip()
        if not item:
            continue
        prov, sep, model = item.partition(":")  # first colon only: "ollama:qwen3:8b" works
        if not sep or prov not in PROVIDERS or not model:
            raise ValueError(f"bad LLM_CHAIN entry {item!r}; use provider:model, provider in {list(PROVIDERS)}")
        key_env = PROVIDERS[prov]["key_env"]
        if key_env and not os.getenv(key_env):
            log.warning("skipping %s: %s not set", item, key_env)
            continue
        chain.append((prov, model))
    if not chain:
        raise RuntimeError("no usable model in LLM_CHAIN (check API keys in backend/.env)")
    return chain


@functools.lru_cache(maxsize=None)
def _client(provider: str) -> OpenAI:
    cfg = PROVIDERS[provider]
    key = os.getenv(cfg["key_env"]) if cfg["key_env"] else "ollama"
    headers = ({"HTTP-Referer": "https://github.com/ana-lan/ignit-iq", "X-Title": "IgnitIQ"}
               if provider == "openrouter" else None)
    # max_retries=0: failure is handled by waiting or moving down the chain, not by SDK retries.
    return OpenAI(base_url=cfg["base_url"], api_key=key, timeout=cfg["timeout"],
                  max_retries=0, default_headers=headers)


@functools.lru_cache(maxsize=1)
def openai_tools() -> list[dict]:
    """tools.py specs are JSON Schema; wrap them in the OpenAI function format."""
    return [{"type": "function",
             "function": {"name": s["name"], "description": s["description"], "parameters": s["input_schema"]}}
            for s in tool_specs()]


@functools.lru_cache(maxsize=1)
def _tools_chars() -> int:
    return len(json.dumps(openai_tools()))


class AllModelsFailed(RuntimeError):
    pass


class _Empty(Exception):
    pass


@dataclass
class _Run:
    chain: list
    idx: int = 0
    waits: int = 0
    calls: int = 0
    usage: dict = field(default_factory=lambda: {"prompt_tokens": 0, "completion_tokens": 0})
    last_model: str | None = None
    last_finish: str | None = None
    failed: list = field(default_factory=list)
    notes: list = field(default_factory=list)      # status events for the UI, flushed by run()
    llm_trace: list = field(default_factory=list)  # every attempt: model, ok/error, tokens, limits


def _code(e: Exception) -> str:
    """Error class + status only: safe to show publicly (provider messages contain org ids)."""
    code = getattr(e, "status_code", None)
    return f"{type(e).__name__}{f' {code}' if code else ''}"


def _short(e: Exception) -> str:
    msg = str(getattr(e, "message", None) or e).replace("\n", " ")
    return f"{_code(e)}: {msg[:200]}"


_LIMIT_RE = re.compile(r"\((?P<kind>[A-Z]{2,5})\): Limit (?P<limit>\d+)"
                       r"(?:, Used (?P<used>\d+))?(?:, Requested (?P<requested>\d+))?")


def _limit_info(e: Exception) -> dict:
    """Parse e.g. '(TPM): Limit 8000, Used 7036, Requested 1500' from a provider error."""
    m = _LIMIT_RE.search(str(e))
    if not m:
        return {}
    return {k: (int(v) if v and v.isdigit() else v) for k, v in m.groupdict().items() if v}


def _retry_after(e: Exception) -> float | None:
    """Seconds until the provider's rate limit resets, if it says so."""
    headers = getattr(getattr(e, "response", None), "headers", None) or {}
    for key in ("retry-after", "x-ratelimit-reset-tokens"):
        v = headers.get(key)
        m = re.fullmatch(r"\s*([\d.]+)\s*(ms|s)?\s*", v or "")
        if m:
            x = float(m.group(1))
            return x / 1000 if m.group(2) == "ms" else x
    m = re.search(r"try again in ([\d.]+)(ms|s)", str(e))
    if m:
        x = float(m.group(1))
        return x / 1000 if m.group(2) == "ms" else x
    return None


def _adapt(prov: str, model: str, messages: list[dict]) -> list[dict]:
    """Per-model tweaks. Qwen3 on Ollama: /no_think stops it spending the budget on reasoning."""
    if prov == "ollama" and model.startswith("qwen3"):
        return [{**messages[0], "content": messages[0]["content"] + "\n/no_think"}] + messages[1:]
    return messages


def _est_tokens(messages: list[dict]) -> int:
    """Rough prompt size (chars / 4) for attempts that fail before the provider reports usage."""
    return (len(json.dumps(messages, default=str)) + _tools_chars()) // 4


_THINK = re.compile(r"<think>.*?</think>", re.S)


def _strip_think(s: str | None) -> str:
    s = _THINK.sub("", s or "")
    if "</think>" in s:  # unclosed opening tag earlier in the text
        s = s.split("</think>", 1)[1]
    return s.strip()


def _fail(run: _Run, name: str, e: Exception, info: dict) -> None:
    run.failed.append({"model": name, "error": _code(e), **info})
    log.warning("%s failed, trying next: %s", name, _short(e))
    run.notes.append({"type": "status", "stage": "model_switch", "from": name, "reason": _code(e)})
    run.idx += 1


def _complete(run: _Run, messages: list[dict], tool_choice: str = "auto"):
    """One chat completion: wait out short rate limits, else fall down the chain."""
    if os.getenv(FORCE_FAIL_ENV) == "1":
        raise AllModelsFailed(f"forced by {FORCE_FAIL_ENV}")
    est = _est_tokens(messages)
    while run.idx < len(run.chain):
        prov, model = run.chain[run.idx]
        name = f"{prov}:{model}"
        t0 = time.time()
        try:
            resp = _client(prov).chat.completions.create(
                model=model, messages=_adapt(prov, model, messages), tools=openai_tools(),
                tool_choice=tool_choice, temperature=TEMPERATURE,
                max_tokens=MODEL_MAX_TOKENS.get(name, MAX_OUTPUT_TOKENS), **MODEL_EXTRA.get(name, {}),
            )
            msg = resp.choices[0].message
            if not msg.tool_calls and not _strip_think(msg.content):
                raise _Empty("empty response")
            pt = resp.usage.prompt_tokens if resp.usage else None
            ct = resp.usage.completion_tokens if resp.usage else None
            run.calls += 1
            run.last_model = name
            run.last_finish = resp.choices[0].finish_reason
            run.usage["prompt_tokens"] += pt or 0
            run.usage["completion_tokens"] += ct or 0
            run.llm_trace.append({"model": name, "ok": True, "prompt_tokens": pt, "completion_tokens": ct,
                                  "est_prompt_tokens": est, "latency_s": round(time.time() - t0, 2),
                                  "finish": run.last_finish})
            return prov, model, msg
        except openai.RateLimitError as e:
            info = _limit_info(e)
            run.llm_trace.append({"model": name, "ok": False, "error": _code(e), **info,
                                  "est_prompt_tokens": est, "latency_s": round(time.time() - t0, 2)})
            wait = _retry_after(e)
            if wait is not None and wait <= MAX_RATE_WAIT_S and run.waits < MAX_WAITS:
                run.waits += 1
                log.warning("%s rate limited (%s), waiting %.1fs", name, info.get("kind", "?"), wait)
                run.notes.append({"type": "status", "stage": "rate_limited", "model": name,
                                  "wait_s": round(wait, 1)})
                time.sleep(wait + 0.25)
                continue
            _fail(run, name, e, info)
        except (openai.APIError, _Empty, IndexError, AttributeError) as e:
            info = _limit_info(e)
            run.llm_trace.append({"model": name, "ok": False, "error": _code(e), **info,
                                  "est_prompt_tokens": est, "latency_s": round(time.time() - t0, 2)})
            _fail(run, name, e, info)
    raise AllModelsFailed("all models failed: " + "; ".join(f"{f['model']} ({f['error']})" for f in run.failed))


# ---------------------------------------------------------------- trace helpers

@functools.lru_cache(maxsize=1)
def _investigations() -> dict:
    con = connect()
    try:
        rows = con.execute("select psi_id, acronym, title, doi from investigations").fetchall()
    finally:
        con.close()
    return {p: {"acronym": a, "title": t, "doi": d or None} for p, a, t, d in rows}


@functools.lru_cache(maxsize=1)
def _experiment_psi() -> dict:
    con = connect()
    try:
        return dict(con.execute("select distinct experiment, psi_id from tests").fetchall())
    finally:
        con.close()


def _cite_key(p: dict) -> str:
    if p.get("psi_id"):
        return f"[{p['psi_id']}]"
    return f"[NASA:{SLUG_TO_REF.get(p.get('field'), p.get('field'))}]"


def _for_model(name: str, result: dict) -> str:
    """Compact view of a tool result for the model (free-tier token budget).
    The full result stays in the trace for the UI and the verifier."""
    if "error" in result:
        return to_text(result, TOOL_RESULT_CHARS)
    r = result
    if name == "query_tests":
        r = {k: result[k] for k in ("columns", "rows", "row_count", "truncated")}
        if result.get("provenance"):
            r["provenance"] = result["provenance"]  # which experiments these rows came from
        if result.get("note"):
            r["note"] = result["note"]  # warnings: empty result, MIN/MAX from different tests
        tags = _psi_tags((result.get("sql") or "") + " "
                         + to_text({"rows": result.get("rows"), "provenance": result.get("provenance")}, 50000))
        if tags:  # the citation for these rows, so the model never has to recall a PSI id
            r["cite_as"] = " ".join(f"[{t}]" for t in sorted(tags))
    elif name == "search_docs":
        r = {"passages": [{"cite_as": _cite_key(p), "pages": p["pages"], "score": round(p["score"], 2),
                           "text": p["text"][:PASSAGE_CHARS_FOR_MODEL]} for p in result["passages"]]}
    elif name == "nearest_conditions":
        exps = result["experiments"]
        r = {
            "habitat": (result.get("habitat") or {}).get("name"),
            "target": result["target"],
            "summary": {**{k: result["summary"][k] for k in ("n_in_box", "nearest_distance", "verdict", "note")},
                        # a real citation for coverage statements, so the model never cites the tool name
                        "cite_as": " ".join(f"[{e['psi_id']}]" for e in
                                            ([e for e in exps if e["n_in_box"]] or exps[:1]))},
            "experiments": [{
                "cite_as": f"[{e['psi_id']}]", "experiment": e["experiment"],
                "n_in_box": e["n_in_box"], "n_tested": e["n_tested"],
                "nearest_distance": e["nearest_distance"], "outcomes_in_box": e["outcomes_in_box"],
                "tested_range": e["tested_range"],
                "nearest": [{"fuel": row.get("fuel") or row.get("material"),
                             "pressure_kpa": row.get("pressure_kpa"), "o2_frac": row.get("o2_frac"),
                             "outcome": row.get("outcome"), "distance": row.get("distance")}
                            for row in e["nearest"][:MAX_PER_EXPERIMENT]],
            } for e in exps[:NEAREST_EXPS_FOR_MODEL]],
            "other_experiments": [f"{e['experiment']} [{e['psi_id']}] nearest {e['nearest_distance']}"
                                  for e in exps[NEAREST_EXPS_FOR_MODEL:]],
        }
        if result.get("context"):
            r["context"] = [{"cite_as": _cite_key(p), "text": p["text"][:PASSAGE_CHARS_FOR_MODEL]}
                            for p in result["context"]]
    elif name == "get_investigation":
        keep = ("psi_id", "acronym", "title", "doi", "project_type", "mission_name", "objective", "approach")
        inv = result["investigation"]
        r = {"cite_as": result["cite_as"],
             "investigation": {k: (inv[k][:MODEL_TEXT_CHARS] if isinstance(inv.get(k), str) else inv.get(k))
                               for k in keep},
             "tests": result["tests"],
             "publications": [p["title"] for p in result["publications"][:MODEL_PUBS]]}
    return to_text(r, TOOL_RESULT_CHARS)


def _summary(name: str, result: dict) -> str:
    if "error" in result:
        return f"error: {str(result['error'])[:150]}"
    if name == "query_tests":
        return (f"{result['row_count']} rows" + (" (truncated)" if result.get("truncated") else "")
                + (f" (auto-fixed {', '.join(result['auto_fixed'])})" if result.get("auto_fixed") else ""))
    if name == "search_docs":
        return ", ".join(f"{p['psi_id'] or p['field']} {p['score']:.2f}" for p in result["passages"])
    if name == "get_investigation":
        inv = result["investigation"]
        return f"{inv.get('acronym') or inv.get('title')} {result['cite_as']}"
    if name == "nearest_conditions":
        s = result["summary"]
        return f"{s['verdict']}, {s['n_in_box']} in box, nearest {s['nearest_distance']}"
    return "ok"


def _clamp_args(name: str, args: dict) -> dict:
    """Keep tool results small enough for free-tier token limits."""
    try:
        if name == "search_docs":
            args["k"] = max(1, min(int(args.get("k") or MAX_K), MAX_K))
        elif name == "nearest_conditions":
            args["per_experiment"] = max(1, min(int(args.get("per_experiment") or 2), MAX_PER_EXPERIMENT))
    except (TypeError, ValueError):
        args.pop("k", None)
        args.pop("per_experiment", None)
    return args


# ---------------------------------------------------------------- text normalization

_DASHES = str.maketrans({c: "-" for c in "\u2010\u2011\u2012\u2013\u2014\u2212"})  # parsing: all dashes
_HYPHENS = str.maketrans({c: "-" for c in "\u2010\u2011\u2012\u2013\u2212"})       # prose: not em dash
_BRACKETS = str.maketrans({"\u3010": "[", "\u3011": "]", "\uff3b": "[", "\uff3d": "]"})  # 【】［］
_BRACKET = re.compile(r"\[([^\[\]]{2,120})\]")
CITATION_RE = re.compile(r"\[([^\[\]]{2,120})\]")  # documented in docs/api.md
CITATION_ID_RE = re.compile(r"^(PSI-\d+|NASA:[a-z0-9_]+)$")
_PAREN_IDS = re.compile(r"\(((?:PSI-\d+|NASA:[a-z0-9_]+)(?:\s*[,;]\s*(?:PSI-\d+|NASA:[a-z0-9_]+))*)\)")


def _norm_answer(s: str) -> str:
    """Answer text as the UI receives it: standard brackets (also for '(PSI-69)'), ASCII dashes
    in ids and prose, no em dashes (inside citations they become '-', in prose ', ')."""
    s = s.translate(_BRACKETS)
    s = _BRACKET.sub(lambda m: "[" + m.group(1).translate(_DASHES) + "]", s)
    s = s.translate(_HYPHENS)
    s = _PAREN_IDS.sub(lambda m: "[" + m.group(1) + "]", s)
    s = re.sub(r"\s*\u2014\s*", ", ", s)
    return _merge_trailing_cites(s)


_TRAILING_CITES = re.compile(r"\n\s*\n\s*((?:\[[^\]\n]+\]\s*)+)$")


def _merge_trailing_cites(s: str) -> str:
    """A last paragraph that is only citations joins the paragraph before it; ids already
    cited earlier are dropped, so the UI never shows a lone chip on its own line."""
    s = s.rstrip()
    m = _TRAILING_CITES.search(s)
    if not m:
        return s
    body = s[:m.start()].rstrip()
    extra = [c for c in re.findall(r"\[[^\]\n]+\]", m.group(1)) if c not in body]
    return body + (" " + " ".join(extra) if extra else "")


# ---------------------------------------------------------------- citations

_PSI = re.compile(r"^PSI-?\s*(\d+)\b", re.I)   # prefix match: "[PSI-100 query]" still parses as PSI-100
_REF = re.compile(r"^NASA:\s*([a-z0-9_]+)", re.I)   # prefix match: drops ":22-24" page suffixes


def _cited_ids(text: str) -> list[str]:
    ids = []
    for grp in _BRACKET.findall(text.translate(_BRACKETS).translate(_DASHES)):
        for part in re.split(r"[,;]\s*", grp):
            part = part.strip()
            m = _PSI.match(part)
            if m:
                cid = f"PSI-{m.group(1)}"
            else:
                m = _REF.match(part)
                if not m:
                    continue
                cid = "NASA:" + m.group(1).lower()
            if cid not in ids:
                ids.append(cid)
    return ids


def _touched(trace: dict) -> set[str]:
    """Sources that actually appeared in tool results or SQL this run."""
    blob = "\n".join(trace["tool_texts"] + [s["sql"] or "" for s in trace["sql_run"]])
    ids = set(re.findall(r"PSI-\d+", blob))
    for exp, psi in _experiment_psi().items():
        if f'"{exp}"' in blob or f"'{exp}'" in blob:
            ids.add(psi)
    for p in trace["passages"].values():
        if p["source_type"] == "context":
            ids.add("NASA:" + SLUG_TO_REF.get(p["field"], p["field"]))
    return ids


def _citations(answer: str, trace: dict) -> list[dict]:
    touched, invs, out = _touched(trace), _investigations(), []
    for cid in _cited_ids(answer):
        if cid.startswith("PSI-"):
            inv = invs.get(cid)
            doi = inv["doi"] if inv else None
            out.append({"id": cid, "kind": "investigation",
                        "label": (inv["acronym"] or inv["title"]) if inv else cid,
                        "title": inv["title"] if inv else None, "doi": doi,
                        "url": f"https://doi.org/{doi}" if doi else None,
                        "known": inv is not None, "verified": inv is not None and cid in touched})
        else:
            ref = cid.split(":", 1)[1]
            slug = CONTEXT_REFS.get(ref)
            url = next((p["url"] for p in trace["passages"].values()
                        if p["field"] == slug and p.get("url")), None)
            out.append({"id": cid, "kind": "context", "label": rag.CONTEXT_DOCS.get(slug, ref),
                        "title": rag.CONTEXT_DOCS.get(slug), "doi": None, "url": url,
                        "known": slug is not None, "verified": slug is not None and cid in touched})
    return out


# ---------------------------------------------------------------- number verification

# Commas only as thousands separators (1,999); "2009," and "420,70" are not one number.
_NUM = re.compile(r"(?<![A-Za-z0-9_.,])(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?")
_DOI = re.compile(r"\b10\.\d{4,9}/[^\s\"'\]\)]+")
_URL = re.compile(r"https?://\S+")
_LIST_MARK = re.compile(r"(?m)^\s*\d+[.)]\s+")
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z*_(])")


def _strip_ids(s: str, citations: bool = False) -> str:
    """Remove digits that are not claims: DOIs, URLs, PSI ids, and (answers only) citation brackets.
    Never strip brackets from tool results: their JSON rows are [...] arrays."""
    s = s.translate(_BRACKETS).translate(_DASHES)
    s = _DOI.sub(" ", s)
    s = _URL.sub(" ", s)
    if citations:
        s = _BRACKET.sub(" ", s)
    return re.sub(r"PSI-\s*\d+", " ", s, flags=re.I)


def _values(text: str) -> set[float]:
    out = set()
    for m in _NUM.findall(_strip_ids(text)):
        try:
            out.add(float(m.replace(",", "")))
        except ValueError:
            pass
    return out


def _values(text: str) -> set[float]:
    out = set()
    for m in _NUM.findall(_strip_ids(text)):
        try:
            out.add(float(m.replace(",", "")))
        except ValueError:
            pass
    return out


def _round_half_up(v: float, d: int) -> float:
    q = 10 ** d
    return math.floor(v * q + 0.5) / q


def _matches(a: float, d: int, values) -> bool:
    """Allowed transforms only: round to the answer's precision; fraction (0, 1] -> percent."""
    for v in values:
        for cand in ((v, v * 100) if 0 < v <= 1 else (v,)):
            if abs(round(cand, d) - a) < 1e-9 or abs(_round_half_up(cand, d) - a) < 1e-9:
                return True
    return False


def _psi_tags(text: str) -> set[str]:
    tags = set(re.findall(r"PSI-\d+", text))
    for exp, psi in _experiment_psi().items():
        if f"'{exp}'" in text or f'"{exp}"' in text:
            tags.add(psi)
    return tags


def _add_source(trace: dict, kind: str, tags: set, obj) -> None:
    text = obj if isinstance(obj, str) else to_text(obj, 200000)
    trace["sources"].append({"kind": kind, "tags": set(tags), "values": _values(text)})


def _record(trace: dict, name: str, args: dict | None, result: dict) -> None:
    trace["tool_texts"].append(to_text(result, 200000))
    trace["steps"].append({"tool": name, "args": args, "summary": _summary(name, result)})
    if name == "query_tests":
        trace["sql_run"].append({
            "sql": result.get("sql") or (args or {}).get("sql"),  # the query that actually ran
            "original_sql": result.get("original_sql"), "auto_fixed": result.get("auto_fixed"),
            "error": result.get("error"),
            "columns": result.get("columns"), "rows": (result.get("rows") or [])[:TRACE_ROWS],
            "row_count": result.get("row_count"), "truncated": result.get("truncated"),
        })
    if "error" in result:
        return
    if name == "query_tests":
        rows = {"columns": result.get("columns"), "rows": result.get("rows"), "provenance": result.get("provenance")}
        _add_source(trace, "sql", _psi_tags((args or {}).get("sql", "") + " " + to_text(rows, 50000)), rows)
    elif name == "nearest_conditions":
        for e in result["experiments"]:
            _add_source(trace, f"nearest_conditions:{e['psi_id']}", {e["psi_id"]}, e)
        _add_source(trace, "nearest_conditions", set(),
                    {"target": result["target"], "summary": result["summary"], "habitat": result.get("habitat")})
        for p in result.get("context", []):  # e.g. the Apollo 1 page for the apollo1 preset
            trace["passages"].setdefault(p["chunk_id"], {**p, "text": p["text"][:600]})
            tag = "NASA:" + SLUG_TO_REF.get(p["field"], p["field"])
            _add_source(trace, f"passage:{tag}", {tag}, p["text"])
    elif name == "search_docs":
        for p in result.get("passages", []):
            trace["passages"].setdefault(p["chunk_id"], {**p, "text": p["text"][:600]})
            tag = p["psi_id"] or "NASA:" + SLUG_TO_REF.get(p["field"], p["field"])
            _add_source(trace, f"passage:{tag}", {tag}, p["text"])
    elif name == "get_investigation":
        pid = result["investigation"]["psi_id"]
        _add_source(trace, f"get_investigation:{pid}", {pid}, result)


def _units(answer: str) -> list[str]:
    """Answer split into lines, then sentences: the scope a citation applies to."""
    out = []
    for line in answer.translate(_BRACKETS).translate(_DASHES).splitlines():
        line = _LIST_MARK.sub("", line)  # "1. " before sentence splitting, or "1." becomes its own unit
        if line.strip():
            out += [u for u in _SENT_SPLIT.split(line) if u.strip()]
    return out


def _find_source(a: float, d: int, cited: set, trace: dict, user_text: str) -> tuple[str | None, bool]:
    """(source kind, attributed). attributed=False with a kind = found, but not in a cited source."""
    if d == 0 and 1900 <= a <= 2100:
        return "year", True
    qv = _values(user_text)
    if _matches(a, d, qv) or _matches(a, d, {v / 100 for v in qv if 1 < v <= 100}):  # "5%" -> 0.05
        return "question", True
    found_elsewhere = None
    # Prefer sources the sentence cites, then neutral ones (habitat target, notes), then the rest,
    # so provenance labels name the most relevant source.
    ranked = sorted(trace["sources"],
                    key=lambda s: 0 if (cited and s["tags"] & cited) else (1 if not s["tags"] else 2))
    for s in ranked:
        if _matches(a, d, s["values"]):
            # Untagged sources (habitat target, habitats query) support any sentence.
            if not cited or not s["tags"] or (s["tags"] & cited):
                return s["kind"], True
            found_elsewhere = found_elsewhere or s["kind"]
    return found_elsewhere, False


def _grounding(answer: str, trace: dict, user_text: str) -> dict:
    """Every number in the answer, where it came from, and whether its sentence's citation matches."""
    numbers = []
    for unit in _units(answer):
        cited = set(_cited_ids(unit))
        body = _LIST_MARK.sub(" ", _strip_ids(unit, citations=True))
        for s in _NUM.findall(body):
            raw = s.replace(",", "").rstrip(".")
            try:
                a = float(raw)
            except ValueError:
                continue
            d = len(raw.split(".")[1]) if "." in raw else 0
            src, attributed = _find_source(a, d, cited, trace, user_text)
            numbers.append({"value": s, "cited": sorted(cited), "source": src, "ok": src is not None and attributed})
    unverified = [n["value"] for n in numbers if n["source"] is None]
    misattributed = [n["value"] for n in numbers if n["source"] is not None and not n["ok"]]
    return {"numbers_checked": len(numbers), "numbers": numbers, "unverified": unverified,
            "misattributed": misattributed, "ok": not unverified and not misattributed}


def _backfill_citations(answer: str, trace: dict, user_text: str) -> tuple[str, list]:
    """If a sentence has numbers, cites nothing, and every number traces to sources tagged with
    exactly one investigation, append that citation. Never replaces a citation the model wrote."""
    added, out_lines = [], []
    for line in answer.splitlines():
        if not line.strip() or line.lstrip().startswith("|"):  # leave tables and blank lines alone
            out_lines.append(line)
            continue
        sents = _SENT_SPLIT.split(line)
        for i, sent in enumerate(sents):
            if _cited_ids(sent):
                continue
            body = _LIST_MARK.sub(" ", _strip_ids(sent, citations=True))
            tags_per_number = []
            for s in _NUM.findall(body):
                raw = s.replace(",", "").rstrip(".")
                d = len(raw.split(".")[1]) if "." in raw else 0
                a = float(raw)
                if (d == 0 and 1900 <= a <= 2100) or _matches(a, d, _values(user_text)):
                    continue  # years and the question's own numbers need no citation
                tags = set().union(*[s_["tags"] for s_ in trace["sources"] if s_["tags"] and _matches(a, d, s_["values"])])
                tags_per_number.append(tags)
            if tags_per_number and all(tags_per_number):
                common = set.intersection(*tags_per_number)
                if len(common) == 1:
                    cid = next(iter(common))
                    sents[i] = re.sub(r"(\s*[.!?]?)\s*$", f" [{cid}]\\1", sent, count=1)
                    added.append({"id": cid, "sentence": sent.strip()[:120]})
        out_lines.append(" ".join(sents))
    return "\n".join(out_lines), added


def _new_trace() -> dict:
    return {"sql_run": [], "passages": {}, "tool_texts": [], "steps": [], "sources": []}


# ---------------------------------------------------------------- the loop

def _repair_prompt(g: dict) -> str:
    """Tell the model exactly which numbers failed verification and why."""
    lines = []
    for n in g["numbers"]:
        if n["ok"]:
            continue
        if n["source"] is None:
            lines.append(f"- {n['value']}: not in any tool result above")
        else:
            lines.append(f"- {n['value']}: comes from {n['source']}, but its sentence cites "
                         f"{', '.join(n['cited']) or 'nothing'}")
    return ("Automatic check before your answer is shown. These numbers failed:\n" + "\n".join(lines)
            + "\nRewrite the whole answer. Keep every number that passed. For each failed number: use the "
              "exact value from a tool result above (rounded normally), cite the investigation it came "
              "from, or remove it. Never estimate: if the data has no value, say the data does not "
              "record it. Follow the same citation rules.")


def run(question: str, habitat: str | None = None, chain: list | None = None) -> Iterator[dict]:
    """Yield events: start, status, tool_call, tool_result, answer, final."""
    t0 = time.time()
    state = _Run(chain=chain or parse_chain())
    user = question.strip()
    if habitat:
        h = conditions.get_habitat(habitat)
        user = (f"[Selected habitat: {h['name']} ({h['slug']}): {h['pressure_kpa']:.1f} kPa, "
                f"{h['o2_frac'] * 100:.1f}% O2]\n{user}")
    messages = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}]
    trace = _new_trace()
    yield {"type": "start", "question": question, "habitat": habitat}

    answer = None
    for turn in range(MAX_TURNS):
        yield {"type": "status", "stage": "thinking", "turn": turn}
        prov, model, msg = _complete(state, messages)
        while state.notes:
            yield state.notes.pop(0)
        if not msg.tool_calls:
            answer = _strip_think(msg.content)
            break
        ids = [tc.id or f"call_{turn}_{i}" for i, tc in enumerate(msg.tool_calls)]
        messages.append({
            "role": "assistant", "content": _strip_think(msg.content) or None,
            "tool_calls": [{"id": cid, "type": "function",
                            "function": {"name": tc.function.name, "arguments": tc.function.arguments or "{}"}}
                           for cid, tc in zip(ids, msg.tool_calls)],
        })
        for cid, tc in zip(ids, msg.tool_calls):
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments or "{}")
                if not isinstance(args, dict):
                    raise ValueError("arguments must be a JSON object")
            except (json.JSONDecodeError, ValueError) as e:
                args, result = None, {"error": f"tool arguments were not a valid JSON object: {e}"}
            if args is not None:
                args = _clamp_args(name, args)
            yield {"type": "tool_call", "tool": name, "args": args, "model": f"{prov}:{model}"}
            if args is not None:
                result = run_tool(name, args)
            _record(trace, name, args, result)
            yield {"type": "tool_result", "tool": name, "summary": _summary(name, result)}
            messages.append({"role": "tool", "tool_call_id": cid, "content": _for_model(name, result)})

    if answer is None:  # turn budget spent: force a final answer without more tools
        messages.append({"role": "user", "content": "Tool budget used up. Answer now from the tool "
                                                    "results above, following the citation rules."})
        yield {"type": "status", "stage": "thinking", "turn": MAX_TURNS}
        _, _, msg = _complete(state, messages, tool_choice="none")
        while state.notes:
            yield state.notes.pop(0)
        answer = _strip_think(msg.content) or "I could not finish this question within the tool budget."

    answer = _norm_answer(answer)
    answer, citations_added = _backfill_citations(answer, trace, user)
    grounding = _grounding(answer, trace, user)
    repaired = False
    if not grounding["ok"] and REPAIR_ROUNDS:
        yield {"type": "status", "stage": "thinking", "turn": MAX_TURNS + 1}
        try:
            messages += [{"role": "assistant", "content": answer},
                         {"role": "user", "content": _repair_prompt(grounding)}]
            _, _, msg = _complete(state, messages, tool_choice="none")
            fixed = _strip_think(msg.content)
        except Exception:  # repair is best effort: keep the checked original
            fixed = None
        while state.notes:
            yield state.notes.pop(0)
        if fixed:
            fixed = _norm_answer(fixed)
            fixed, added2 = _backfill_citations(fixed, trace, user)
            g2 = _grounding(fixed, trace, user)
            bad = lambda g: len(g["unverified"]) + len(g["misattributed"])
            if bad(g2) < bad(grounding):
                answer, citations_added, grounding, repaired = fixed, added2, g2, True
    yield {"type": "answer", "text": answer}
    yield {
        "type": "final",
        "question": question,
        "habitat": habitat,
        "answer": answer,
        "citations": _citations(answer, trace),
        "citations_added": citations_added,  # added by the system from tool provenance, never replacing the model's
        "sql_run": trace["sql_run"],
        "passages": list(trace["passages"].values()),
        "steps": trace["steps"],
        "grounding": grounding,
        "repaired": repaired,  # True when the answer was rewritten after a failed number check
        "answer_truncated": state.last_finish == "length",
        "model": state.last_model,
        "models_failed": state.failed,
        "llm_calls": state.calls,
        "usage": state.usage,
        "llm_trace": state.llm_trace,
        "elapsed_s": round(time.time() - t0, 2),
    }


def ask(question: str, habitat: str | None = None, chain: list | None = None) -> dict:
    """Run the agent to completion; returns the final payload."""
    final = None
    for ev in run(question, habitat, chain):
        if ev["type"] == "final":
            final = {k: v for k, v in ev.items() if k != "type"}
    return final


# ---------------------------------------------------------------- CLI

def ping(chain: list) -> None:
    """Check each chain entry answers and emits a proper tool call."""
    for prov, model in chain:
        t = time.time()
        try:
            r = _client(prov).chat.completions.create(
                model=model, temperature=0, max_tokens=1000, tools=openai_tools(), tool_choice="auto",
                messages=_adapt(prov, model, [{"role": "system", "content": "You call tools."},
                                              {"role": "user", "content": "Call the nearest_conditions tool for habitat iss."}]),
                **MODEL_EXTRA.get(f"{prov}:{model}", {}))
            m = r.choices[0].message
            calls = [tc.function.name for tc in (m.tool_calls or [])]
            ok = calls[:1] == ["nearest_conditions"]
            print(f"  {'OK  ' if ok else 'NO  '} {prov}:{model}  {time.time() - t:.1f}s  tool_calls={calls}"
                  + ("" if ok else f"  text={_strip_think(m.content)[:80]!r}"))
        except openai.APIError as e:
            print(f"  FAIL {prov}:{model}  {time.time() - t:.1f}s  {_code(e)} {_limit_info(e)}")


def budget(chain: list) -> None:
    """Measure the fixed cost of every call: system prompt + tool schemas, in real provider tokens."""
    print(f"system prompt: {len(SYSTEM_PROMPT)} chars")
    for s in openai_tools():
        print(f"tool {s['function']['name']}: {len(json.dumps(s))} chars")
    print(f"total fixed: {len(SYSTEM_PROMPT) + _tools_chars()} chars (~{(len(SYSTEM_PROMPT) + _tools_chars()) // 4} tokens est.)")
    prov, model = chain[0]
    try:
        r = _client(prov).chat.completions.create(
            model=model, temperature=0, max_tokens=50, tools=openai_tools(),
            messages=[{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": "Reply OK."}],
            **MODEL_EXTRA.get(f"{prov}:{model}", {}))
        print(f"measured baseline on {prov}:{model}: {r.usage.prompt_tokens} prompt tokens per call")
    except openai.APIError as e:
        print(f"measurement call failed: {_code(e)} {_limit_info(e)}")


def main(argv=None) -> None:
    logging.basicConfig(level=logging.WARNING, format="  [%(name)s] %(message)s")
    ap = argparse.ArgumentParser(prog="ignitiq.agent")
    ap.add_argument("question", nargs="?")
    ap.add_argument("--habitat", choices=["iss", "gateway", "lunar", "apollo1"])
    ap.add_argument("--model", help="force one entry, e.g. groq:openai/gpt-oss-120b or ollama:qwen3:8b")
    ap.add_argument("--ping", action="store_true", help="check every model in the chain")
    ap.add_argument("--budget", action="store_true", help="measure the fixed prompt cost per call")
    ap.add_argument("--json", action="store_true", help="print only the final JSON")
    args = ap.parse_args(argv)

    chain = parse_chain(args.model) if args.model else parse_chain()
    if args.ping:
        ping(chain)
        return
    if args.budget:
        budget(chain)
        return
    if not args.question:
        ap.error("give a question, --ping or --budget")

    try:
        for ev in run(args.question, args.habitat, chain):
            if args.json:
                if ev["type"] == "final":
                    print(json.dumps({k: v for k, v in ev.items() if k != "type"}, indent=2, default=str))
                continue
            if ev["type"] == "tool_call":
                print(f"-> {ev['tool']} {json.dumps(ev['args'])[:220]}  [{ev['model']}]")
            elif ev["type"] == "tool_result":
                print(f"   <- {ev['summary']}")
            elif ev["type"] == "answer":
                print("\n" + ev["text"] + "\n")
            elif ev["type"] == "final":
                if ev["answer_truncated"]:
                    print("WARNING: answer was cut off by the output token limit")
                print("citations: " + (", ".join(
                    f"{c['id']}{'' if c['verified'] else ' (UNVERIFIED)'}" for c in ev["citations"]) or "none"))
                g = ev["grounding"]
                print(f"numbers: {g['numbers_checked']} checked | unverified: {g['unverified'] or 'none'} | "
                      f"misattributed: {g['misattributed'] or 'none'}")
                for n in g["numbers"]:
                    print(f"   {n['value']:>8}  cited={','.join(n['cited']) or '-':<24} <- "
                          f"{n['source'] or 'NO SOURCE'}{'' if n['ok'] else '   FAIL'}")
                for c in ev["llm_trace"]:
                    lim = (f"  {c['kind']} used {c.get('used')}/{c.get('limit')} requested {c.get('requested')}"
                           if c.get("kind") else "")
                    print(f"   llm {c['model']}: {'ok' if c['ok'] else c.get('error')} "
                          f"prompt={c.get('prompt_tokens')} est={c.get('est_prompt_tokens')} {c['latency_s']}s{lim}")
                print(f"model: {ev['model']} | llm calls: {ev['llm_calls']} | tokens: {ev['usage']} | "
                      f"{ev['elapsed_s']}s" + (f" | failed: {[f['model'] for f in ev['models_failed']]}"
                                               if ev["models_failed"] else ""))
    except AllModelsFailed as e:
        raise SystemExit(f"AGENT: FAIL\n  {e}")


if __name__ == "__main__":
    main()