# FlameScope API

Base URL: `http://localhost:8000` locally, the Render URL in production (`NEXT_PUBLIC_API_URL`).
Interactive docs: `/docs`. Machine-readable schema: `/openapi.json`. Version 0.3.1.

The response shapes below are defined as pydantic models in `backend/api/schemas.py`. Every endpoint declares its model, and the contract test validates live responses against them. If this file and the models ever disagree, the models win.

## Conventions

- Pressure is in **kPa**. O2 and other gas amounts are **fractions 0 to 1** (0.21 = 21%). ppO2 in kPa = pressure × O2 fraction.
- Investigations are identified by `psi_id` (`PSI-69`). Show the DOI next to anything from an investigation (`doi`, `doi_url`).
- `outcome` is one of:
  - **FLEX droplets:** `extinction` (went out early), `completion` (burned away), `disruption` (broke apart)
  - **CFI-G gas jets:** `self_extinguished`, `flow_terminated` (still burning when the fuel flow stopped)
  - `no_ignition`
  - `null`, which means **not recorded**, never "did not burn"
- Rows with `extra.row_kind = "summary"` are test-day or fuel summaries, not single tests.
- **Habitat slugs:** `iss`, `gateway`, `lunar`, `apollo1`. Any other value returns **422**. The allowed values are published as an enum in `/openapi.json`.
- **Errors:**
  - 422 validation: `{"detail": [ {"loc", "msg", "type"} ]}`
  - 404, 429, 503: `{"detail": "message"}`
- Responses over 1 KB are gzipped, except `/ask` (streamed).
- **CORS:** `CORS_ORIGINS` (default localhost:3000) and `CORS_ORIGIN_REGEX` (default `https://ignit-?iq[\w-]*\.vercel\.app`).

## GET /health

```json
{"status": "ok", "version": "0.3.1",
 "db": {"tests": 1999, "investigations": 23, "insights": 5, "habitats": 4},
 "index": {"chunks": 316, "model": "BAAI/bge-small-en-v1.5"},
 "llm_chain": ["groq:openai/gpt-oss-120b", "..."],
 "warm": {"tests": "ok", "index": "ok", "embedder": "ok", "tool_specs": "ok"},
 "warm_s": 0.28, "uptime_s": 11.6}
```

`status` is `ok` or `degraded`. Use this to show the "waking the backend" state: Render's free tier sleeps, so the first call can take 30 to 60 s.

## GET /habitats

An array in the order iss, gateway, lunar, apollo1:

```json
{"slug": "lunar", "name": "Lunar / Mars surface habitat", "kind": "proposed",
 "pressure_psia": 8.2, "pressure_kpa": 56.537, "o2_frac": 0.34, "pp_o2_kpa": 19.22,
 "source": "...", "source_url": "...", "note": "..."}
```

`kind` is `current`, `proposed` or `historical`. Apollo 1 is a historical reference, never a design target.

## GET /insights?habitat=

Ranked, precomputed findings. `habitat` (optional) keeps only insights tagged for that slug or `all`.

```json
{"id": "flex_diluent_extinction", "rank": 4, "title": "...", "value": 90.0, "unit": "%",
 "explanation": "...", "sql": "select ...", "source_psi_ids": ["PSI-69"], "habitats": ["all"],
 "detail": {"...": "insight-specific numbers"},
 "sources": [{"psi_id": "PSI-69", "acronym": "FLEX", "title": "...", "doi": "10.60555/mbq8-0451",
              "doi_url": "https://doi.org/10.60555/mbq8-0451"}]}
```

## GET /tests

| Param | Type | Notes |
| --- | --- | --- |
| `experiment` | string, repeatable | exact name, e.g. `FLEX`, `CFI-G` |
| `psi_id` | string, repeatable | case-insensitive |
| `outcome` | string, repeatable | |
| `fuel` | string | substring match on fuel or material |
| `p_min`, `p_max` | number ≥ 0 | kPa |
| `o2_min`, `o2_max` | number 0 to 1 | fraction (30 instead of 0.30 gives 422) |
| `single_only` | bool, default false | drop summary rows |
| `include_duplicates` | bool, default false | |
| `include_raw` | bool, default false | adds `extra.raw` (the untouched CSV row) |
| `limit` | 1 to 1000, default 200 | |
| `offset` | ≥ 0, default 0 | |

```json
{"total": 186, "limit": 200, "offset": 0,
 "rows": [{"test_pk": 1, "psi_id": "PSI-69", "experiment": "FLEX", "test_id": "202",
           "fuel": "methanol", "material": null, "pressure_kpa": 101.4, "o2_frac": 0.21,
           "diluent": "N2", "diluent_frac": null, "flow_cm_s": null, "outcome": "extinction",
           "burn_time_s": null, "spread_rate_mm_s": null,
           "extra": {"droplet_d0_mm": 3.1, "source_file": "...", "source_row": 12}}]}
```

`extra` keys differ per experiment (SAFFIRE `flow_direction`, CFI-G `cool_flame`, `flame_type`, ...). Totals: 1999 with duplicates, 1953 without.

## GET /tests/facets

```json
{"experiments": [{"experiment": "SPICE", "psi_id": "PSI-107", "n": 469, "n_outcome": 0,
                  "n_conditions": 0, "n_summary": 0}],
 "outcomes": [{"outcome": "extinction", "n": 0}],
 "fuels": [{"fuel": "heptane", "n": 0}],
 "ranges": {"p_min": 43.023, "p_max": 506.625, "o2_min": 0.12, "o2_max": 0.4}}
```

`n_conditions` counts rows with both pressure and O2 (plottable on the coverage chart).

## GET /investigations

```json
[{"psi_id": "PSI-69", "acronym": "FLEX", "title": "...", "project_type": "...", "mission_name": "...",
  "doi": "10.60555/mbq8-0451", "doi_url": "https://doi.org/...", "n_publications": 51, "n_tests": 274}]
```

23 items, sorted by PSI number. Ground studies have `acronym: null`: label them by title.

## GET /investigations/{psi_id}

```json
{"investigation": {"psi_id": "PSI-69", "acronym": "FLEX", "title": "...", "doi": "...", "doi_url": "...",
                   "objective": "...", "approach": "...", "hypothesis": "...", "research_impacts": "...",
                   "hardware": "...", "description": "...", "project_type": "...", "mission_name": "..."},
 "cite_as": "[PSI-69] doi:10.60555/mbq8-0451",
 "tests": {"n_rows": 274, "n_single_tests": 274, "p_min_kpa": 70.0, "p_max_kpa": 309.0,
           "o2_min": 0.12, "o2_max": 0.34, "top_fuels": [{"fuel": "heptane", "n": 117}],
           "outcomes": {"extinction": 186, "disruption": 61, "completion": 27}},
 "publications": [{"pub_id": "...", "title": "...", "authors": "...", "doi": "...", "doi_url": "...",
                   "has_abstract": true}]}
```

An unknown id returns **404**.

## GET /coverage?habitat=&per_experiment=

`habitat` is required (422 if missing or unknown). `per_experiment` is 1 to 10, default 3.

```json
{"habitat": {"slug": "lunar", "...": "same as /habitats"},
 "target": {"pressure_kpa": 56.537, "o2_frac": 0.34, "pp_o2_kpa": 19.22},
 "tolerance": {"pressure_rel": 0.15, "o2_abs": 0.03, "far": 2.0},
 "summary": {"n_tested": 756, "n_in_box": 11, "n_in_box_incl_duplicates": 11,
             "nearest_distance": 0.69, "verdict": "sparse", "note": "11 tests within ..."},
 "experiments": [{"psi_id": "PSI-159", "experiment": "CFI-G", "n_tested": 179, "n_in_box": 11,
                  "nearest_distance": 0.69, "far": false,
                  "tested_range": {"pressure_kpa": [50.7, 304.0], "o2_frac": [0.18, 0.40]},
                  "outcomes_in_box": {"flow_terminated": 5, "self_extinguished": 4},
                  "nearest": [{"test_pk": 0, "test_id": "21153 F1", "fuel": "30% ethane",
                               "pressure_kpa": 50.7, "o2_frac": 0.341, "pp_o2_kpa": 17.29,
                               "outcome": "self_extinguished", "distance": 0.69,
                               "d_pressure_pct": -10.3, "d_o2_pts": 0.1}]}],
 "points": [{"psi_id": "PSI-69", "experiment": "FLEX", "pressure_kpa": 101.4, "o2_frac": 0.21,
             "outcome": "extinction", "row_kind": null, "in_box": false}]}
```

- **Distance** is in box widths: 1 = 15% of the target pressure or 3 points of O2.
- **`verdict`:** `well_covered` (≥ 20 in the box), `sparse` (1 to 19), `near_only` (0 in the box, nearest ≤ 2), `untested`.
- **`points`** holds every plottable test for the pressure-vs-O2 chart. Mark the `in_box` points and the habitat target.

## POST /ask

Request body:

```json
{"question": "string, 3 to 500 chars", "habitat": "iss | gateway | lunar | apollo1 | null",
 "stream": true, "fresh": false}
```

| Status | When |
| --- | --- |
| 200 | an SSE stream (`stream: true`) or the final JSON (`stream: false`) |
| 422 | the question is too short or long, or the habitat is unknown |
| 429 | `ASK_CONCURRENCY` (default 2) questions are already running. Show `detail` and point to the suggested questions |
| 503 | `stream: false` only: every model failed |

**The demo cache.** When `fresh` is false and the question matches a recorded, checked answer (case, whitespace and trailing punctuation are ignored, the habitat must match), the recorded run is replayed **in exactly the live event format**, with `final.cached = true`. `GET /ask/suggested` lists those questions.

### Stream events (`stream: true`)

Each event is `event: <name>` followed by `data: <json>`. A `: ping` comment arrives every 10 s; ignore it.

The order is always: **step events** (`start`, then any mix of `status`, `tool_call`, `tool_result`), then **`token` events**, then **exactly one `final`**. If something fails, it's step events, then **exactly one `error`**, and the stream closes.

| Event | Data |
| --- | --- |
| `start` | `{"question": str, "habitat": str \| null}` |
| `status` | one of: `{"stage": "thinking", "turn": int}`; `{"stage": "rate_limited", "model": str, "wait_s": float}`; `{"stage": "model_switch", "from": str, "reason": str}` |
| `tool_call` | `{"tool": "query_tests" \| "search_docs" \| "get_investigation" \| "nearest_conditions", "args": object \| null, "model": str}` |
| `tool_result` | `{"tool": str, "summary": str}`, e.g. `"4 rows"`, `"2 rows (auto-fixed flow_direction -> extra->>'flow_direction')"`, `"sparse, 11 in box, nearest 0.69"`, `"error: ..."` |
| `token` | `{"text": str}`. **Concatenating every `token.text` gives exactly `final.answer`.** |
| `final` | the final payload, below |
| `error` | `{"message": str}`, a user-facing message. Show it and offer the suggested questions |

Suggested UI labels:

| Event | Label |
| --- | --- |
| `thinking` | "Thinking" |
| `rate_limited` | "Waiting for model capacity (12 s)" |
| `model_switch` | "Switching model" |
| `query_tests` | "Running SQL" |
| `search_docs` | "Searching documents" |
| `nearest_conditions` | "Checking nearest tests" |
| `get_investigation` | "Reading investigation" |

### `stream: false`

One JSON object, identical to the `final` payload.

### The final payload

```json
{"question": "...", "habitat": null,
 "answer": "markdown with citations like [PSI-98] or [PSI-69, NASA:guide_2015]",
 "citations": [{"id": "PSI-98", "kind": "investigation", "label": "SAFFIRE-I",
                "title": "Spacecraft Fire Safety Experiment-I", "doi": "10.60555/0t15-1z43",
                "url": "https://doi.org/10.60555/0t15-1z43", "known": true, "verified": true}],
 "sql_run": [{"sql": "the query that actually ran", "original_sql": "the model's query if auto-fixed, else null",
              "auto_fixed": ["flow_direction -> extra->>'flow_direction'"],
              "error": null, "columns": ["flow_dir", "total_burn_s"],
              "rows": [["concurrent", 420.0], ["opposed", 70.0]], "row_count": 2, "truncated": false}],
 "passages": [{"chunk_id": "...", "source_type": "abstract", "psi_id": "PSI-69", "experiment": "FLEX",
               "field": "abstract", "title": "...", "doi": "...", "psi_doi": "...", "url": null,
               "pages": null, "score": 0.85, "text": "first 600 chars"}],
 "steps": [{"tool": "query_tests", "args": {"sql": "..."}, "summary": "2 rows"}],
 "grounding": {"numbers_checked": 2, "ok": true, "unverified": [], "misattributed": [],
               "numbers": [{"value": "420", "cited": ["PSI-98"], "source": "sql", "ok": true}]},
 "answer_truncated": false,
 "model": "groq:openai/gpt-oss-120b", "models_failed": [], "llm_calls": 2,
 "usage": {"prompt_tokens": 3715, "completion_tokens": 129},
 "llm_trace": [{"model": "groq:openai/gpt-oss-120b", "ok": true, "prompt_tokens": 1787,
                "completion_tokens": 60, "est_prompt_tokens": 1661, "latency_s": 0.58, "finish": "tool_calls"}],
 "elapsed_s": 1.43, "cached": false, "cached_at": null}
```

- **`answer`** is markdown. The backend has already normalized it: standard `[ ]` brackets, ASCII `-` in place of unicode hyphens and dashes, and no em dashes.
- **`grounding.numbers`** lists every number in the answer with its source:
  - `sql`
  - `nearest_conditions`, or `nearest_conditions:PSI-<n>`
  - `passage:PSI-<n>`, or `passage:NASA:<doc>`
  - `get_investigation:PSI-<n>`
  - `question`
  - `year`
  - `null`, if not found

  `ok: false` means unverified (no source) or misattributed (found only in a source the sentence doesn't cite). Show a small "check these numbers" note when `grounding.ok` is false.
- **`citations[].verified: false`** means the answer cites something no tool returned. Show it as a warning chip.
- **`citations_added`** lists citations the backend appended from tool provenance (`{"id", "sentence"}`), only where a sentence had numbers, no citation, and every number traced to exactly one investigation. It never replaces a citation the model wrote. Optionally style these chips differently ("added by FlameScope").
- **`llm_trace`** has one entry per model attempt. Failed attempts carry `"error": "RateLimitError 429"` plus, for rate limits, `"kind": "TPM" | "ITPM" | "OTPM"`, `"used"`, `"limit"`, `"requested"`. It's for the "how I got this" drawer and debugging. It never contains provider messages or account ids.
- **`cached: true`** comes with `cached_at`: the answer is a replay of a checked run. Label it "recorded answer".

### Citation format

The backend parses citations with exactly these patterns (`backend/ignitiq/agent.py`: `CITATION_RE`, `CITATION_ID_RE`). The frontend should use the same ones:

```
CITATION_RE    = \[([^\[\]]{2,120})\]                 one bracket group
split on       = [,;]\s*                              ids inside a group
CITATION_ID_RE = ^(PSI-\d+|NASA:[a-z0-9_]+)$          a valid id
```

Valid ids are `PSI-<n>` and `NASA:apollo_1`, `NASA:apollo_13`, `NASA:mir_1997`, `NASA:guide_2015`. Render each valid id as a chip linked to the matching `citations[].url`, and leave other bracketed text (like `[note]`) as it is.

## GET /ask/suggested?habitat=

Questions with a checked, cached answer. Asking one with the same text and habitat replays it.

```json
[{"question": "How long did the concurrent and opposed flow fires burn in SAFFIRE-I?", "habitat": null,
  "model": "groq:openai/gpt-oss-120b", "cached_at": "2026-11-14 22:10:00"}]
```

With `habitat`, you get that habitat's questions plus the general ones (`habitat: null`). An unknown habitat returns 422.