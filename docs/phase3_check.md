# Phase 3 check

Generated 2026-11-15 12:23 against `http://localhost:8000`. LLM runs used `fresh: true` (no cache) and were spaced 65 s apart: Groq's free tier allows 8,000 tokens per minute and one question uses about 4,000 to 5,000. Latency is wall-clock time per question as the client sees it, excluding the gaps.

## Done-when

| Requirement | Result |
| --- | --- |
| Verifier negative tests (with controls) | 11/11 |
| SQL safety | 13/13 |
| API contract | 10/10 |
| SSE contract: live, cached, forced failure | 24/24 |
| Stability: 18 runs correct | 18/18 |
| No failover on the 6 questions | 0 failovers |
| p95 latency under 15 s | p95 2.03 s, p50 1.46 s (PASS) |
| Out-of-scope question | FAIL |

## Known limitations

- Adversarial out-of-scope question (Q7, Kapton at 5% O2 on Mars) failed 3 of 3 attempts. The agent correctly says the data does not cover the conditions, but adds unsupported detail: an invented pressure range, a computed 'gap' figure, or a citation to CFI instead of the SAME/SAME-R smoke tests where Kapton actually appears. Every attempt was flagged by the verifier (unverified or misattributed numbers) or by the fact-level check. Mitigations in place: provenance on untagged SQL, cite_as on every result. The UI shows grounding.ok = false as a warning.
- Number verification matches by value, so a small round number can coincide with an unrelated value in a source carrying the same citation (e.g. '30 Kapton tests' vs '30% ethane'). Fact-level eval checks catch these; the verifier alone cannot.
- Groq free tier: 8,000 tokens per minute and 200,000 per day on gpt-oss-120b (about 40 questions a day). Latency here was measured with runs spaced 65 s apart; questions asked within the same minute can wait for capacity or fail over. Suggested questions replay from the checked demo cache at zero token cost.

## Verifier negative tests

| Check | Result | Detail |
| --- | --- | --- |
| NEGATIVE: invented '812 s' is flagged unverified | PASS | {"unverified": ["812"]} |
| control: real '420 s' cited to PSI-98 passes | PASS | [["420", "sql"]] |
| NEGATIVE: [PSI-999] is not a verified citation | PASS | [{"id": "PSI-999", "kind": "investigation", "label": "PSI-999", "title": null, "doi": null, "url": null, "known": false, "verified": false}] |
| control: [PSI-98] is a verified citation | PASS | [{"id": "PSI-98", "kind": "investigation", "label": "SAFFIRE-I", "title": "Spacecraft Fire Safety Experiment-I", "doi": "10.60555/0t15-1z43", "url": "https://doi.org/10.60555/0t15-1z43", "known": true, "verified": true}] |
| NEGATIVE: a CFI-G number cited to [PSI-69] is misattributed | PASS | {"misattributed": ["34"]} |
| control: same number cited to PSI-159 passes (33.7 rounds to 34) | PASS | [["34", "sql"]] |
| control: fraction 0.21 verifies '21%' | PASS | [["21", "nearest_conditions"]] |
| NEGATIVE: x100 of a non-fraction (3.5 -> 350) is not allowed | PASS | {"unverified": ["350"]} |
| years, DOIs and PSI ids are not checked as claims | PASS | [["2009", "year"]] |
| non-breaking hyphen citation [PSI‑98] parses and verifies | PASS | [{"id": "PSI-98", "kind": "investigation", "label": "SAFFIRE-I", "title": "Spacecraft Fire Safety Experiment-I", "doi": "10.60555/0t15-1z43", "url": "https://doi.org/10.60555/0t15-1z43", "known": true, "verified": true}] |
| list markers '1.' '2.' are not checked as numbers | PASS | ["420"] |

## SQL safety

| Check | Result | Detail |
| --- | --- | --- |
| rejected: DROP | PASS | only SELECT is allowed, got DROP |
| rejected: DELETE | PASS | only SELECT is allowed, got DELETE |
| rejected: UPDATE | PASS | only SELECT is allowed, got UPDATE |
| rejected: INSERT | PASS | only SELECT is allowed, got INSERT |
| rejected: ATTACH | PASS | only SELECT is allowed, got ATTACH |
| rejected: COPY | PASS | only SELECT is allowed, got COPY |
| rejected: PRAGMA | PASS | only SELECT is allowed, got PRAGMA |
| rejected: second statement after ; | PASS | exactly one statement allowed, got 2 |
| rejected: file read inside a SELECT | PASS | PermissionException: Permission Error: Cannot access file "/etc/hosts" - file system operations are disabled b |
| SELECT * FROM tests returns at most 200 rows and says it was capped | PASS | row_count=200 truncated=True |
| query timeout is 10 s | PASS | QUERY_TIMEOUT_S=10.0 |
| a runaway query (4e10-row cross join) is interrupted at the timeout | PASS | 10.0s: query exceeded 10s; simplify or aggregate |
| data unchanged afterwards (1999 rows) | PASS | [[1999]] |

## API contract

| Check | Result | Detail |
| --- | --- | --- |
| GET /health: 200 and matches its schema | PASS | HTTP 200 |
| GET /habitats: 200 and matches its schema | PASS | HTTP 200 |
| GET /insights?habitat=lunar: 200 and matches its schema | PASS | HTTP 200 |
| GET /tests?experiment=FLEX: 200 and matches its schema | PASS | HTTP 200 |
| GET /investigations/PSI-69: 200 and matches its schema | PASS | HTTP 200 |
| GET /coverage?habitat=lunar: 200 and matches its schema | PASS | HTTP 200 |
| unknown psi_id -> 404 | PASS | HTTP 404 |
| unknown habitat -> 422 | PASS | HTTP 422 |
| CORS preflight allows http://localhost:3000 | PASS | allow-origin=http://localhost:3000 |
| CORS header present on a real GET from http://localhost:3000 | PASS | allow-origin=http://localhost:3000 |

## SSE contract

| Check | Result | Detail |
| --- | --- | --- |
| live: HTTP 200 | PASS | HTTP 200 |
| live: first event is start | PASS | start > status > tool_call > tool_result > status > tokenx7 > final |
| live: exactly one final event | PASS | 1 final |
| live: final is the last event, no error | PASS |  |
| live: order is step events, then tokens, then final | PASS | start > status > tool_call > tool_result > status > tokenx7 > final |
| live: concatenated tokens == final.answer | PASS | 132 vs 132 chars |
| live: final matches the AskFinal schema | PASS |  |
| live: final has answer, citations, sql_run, passages | PASS |  |
| live: final.cached is False | PASS | cached=False |
| cached: HTTP 200 | PASS | HTTP 200 |
| cached: first event is start | PASS | start > status > tool_call > tool_result > status > tokenx7 > final |
| cached: exactly one final event | PASS | 1 final |
| cached: final is the last event, no error | PASS |  |
| cached: order is step events, then tokens, then final | PASS | start > status > tool_call > tool_result > status > tokenx7 > final |
| cached: concatenated tokens == final.answer | PASS | 132 vs 132 chars |
| cached: final matches the AskFinal schema | PASS |  |
| cached: final has answer, citations, sql_run, passages | PASS |  |
| cached: final.cached is True | PASS | cached=True |
| forced failure: HTTP 200 stream | PASS | HTTP 200 |
| forced failure: first event is start | PASS | start > status > error |
| forced failure: exactly one error event | PASS |  |
| forced failure: error is the last event (stream closed cleanly) | PASS |  |
| forced failure: no token or final events | PASS |  |
| forced failure: error carries a user-facing message | PASS | All language models are busy or rate-limited right now. Try a suggested question, or ask again in a minute. |

## Stability

| # | Question | Correct | Failovers | p50 s | max s |
| --- | --- | --- | --- | --- | --- |
| 1 | How many FLEX tests ended in extinction, and over what O2 range? | 3/3 | 0 | 1.57 | 1.63 |
| 2 | In FLEX, what percentage of droplet tests ended in extinction with each suppressant gas: CO2, nitrogen and helium? | 3/3 | 0 | 1.20 | 1.41 |
| 3 | How long did the concurrent and opposed flow fires burn in SAFFIRE-I? | 3/3 | 0 | 1.21 | 2.03 |
| 4 | How much test data covers this habitat, and what happened to the flames there? | 3/3 | 0 | 1.49 | 1.49 |
| 5 | In CFI-G, what share of flames kept burning until the fuel flow was stopped at 30% O2 or more, compared with below 25%? | 3/3 | 0 | 1.75 | 1.76 |
| 6 | Could the test data tell us how the Apollo 1 cabin fire would have behaved? | 3/3 | 0 | 1.65 | 1.89 |
| 7 | How flammable is Kapton at 5% O2 on Mars? | 0/1 | 0 | 2.73 | 2.73 |

### Every run

| Q | Round | Result | Wall s | Model | LLM calls | Prompt tokens | Failover | Failed checks |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 1 | PASS | 1.09 | `groq:openai/gpt-oss-120b` | 2 | 3935 | none |  |
| 1 | 2 | PASS | 1.63 | `groq:openai/gpt-oss-120b` | 2 | 3935 | none |  |
| 1 | 3 | PASS | 1.57 | `groq:openai/gpt-oss-120b` | 2 | 3935 | none |  |
| 2 | 1 | PASS | 1.2 | `groq:openai/gpt-oss-120b` | 2 | 4032 | none |  |
| 2 | 2 | PASS | 1.17 | `groq:openai/gpt-oss-120b` | 2 | 3966 | none |  |
| 2 | 3 | PASS | 1.41 | `groq:openai/gpt-oss-120b` | 2 | 4034 | none |  |
| 3 | 1 | PASS | 1.21 | `groq:openai/gpt-oss-120b` | 2 | 3915 | none |  |
| 3 | 2 | PASS | 2.03 | `groq:openai/gpt-oss-120b` | 2 | 3948 | none |  |
| 3 | 3 | PASS | 0.94 | `groq:openai/gpt-oss-120b` | 2 | 3915 | none |  |
| 4 | 1 | PASS | 1.49 | `groq:openai/gpt-oss-120b` | 2 | 4621 | none |  |
| 4 | 2 | PASS | 1.49 | `groq:openai/gpt-oss-120b` | 2 | 4621 | none |  |
| 4 | 3 | PASS | 1.43 | `groq:openai/gpt-oss-120b` | 2 | 4621 | none |  |
| 5 | 1 | PASS | 1.46 | `groq:openai/gpt-oss-120b` | 2 | 4146 | none |  |
| 5 | 2 | PASS | 1.76 | `groq:openai/gpt-oss-120b` | 2 | 4129 | none |  |
| 5 | 3 | PASS | 1.75 | `groq:openai/gpt-oss-120b` | 2 | 4129 | none |  |
| 6 | 1 | PASS | 1.32 | `groq:openai/gpt-oss-120b` | 2 | 4797 | none |  |
| 6 | 2 | PASS | 1.89 | `groq:openai/gpt-oss-120b` | 2 | 4797 | none |  |
| 6 | 3 | PASS | 1.65 | `groq:openai/gpt-oss-120b` | 3 | 6845 | none |  |
| 7 | 1 | FAIL | 2.73 | `groq:openai/gpt-oss-120b` | 3 | 6734 | none | cites one of ['PSI-101', 'PSI-102']; no unverified numbers |

## Latest answer per question

### 1. How many FLEX tests ended in extinction, and over what O2 range?

Habitat: none. Expected source: tests table: FLEX outcome = extinction (186), o2_frac 0.12 to 0.30.

> 186 FLEX tests ended in extinction, occurring across an O₂ fraction range from 0.12 to 0.30. [PSI-69]

| Number | Cited | Source | OK |
| --- | --- | --- | --- |
| 186 | PSI-69 | sql | yes |
| 0.12 | PSI-69 | sql | yes |
| 0.30 | PSI-69 | sql | yes |

Citations: PSI-69 (FLEX, doi:10.60555/mbq8-0451)

SQL 1: 1 rows

```sql
SELECT COUNT(*) AS cnt, MIN(o2_frac) AS min_o2, MAX(o2_frac) AS max_o2 FROM tests WHERE psi_id='PSI-69' AND outcome='extinction' AND (extra->>'is_duplicate' IS NULL OR extra->>'is_duplicate'!='true')
```

LLM calls:

- `groq:openai/gpt-oss-120b`: ok, prompt 1892 (est 1780), 1.19 s
- `groq:openai/gpt-oss-120b`: ok, prompt 2043 (est 1943), 0.35 s

### 2. In FLEX, what percentage of droplet tests ended in extinction with each suppressant gas: CO2, nitrogen and helium?

Habitat: none. Expected source: insight flex_diluent_extinction.

> In the FLEX droplet series, extinction occurred in 90 % of the CO₂ tests, 75 % of the helium tests, and 66 % of the nitrogen tests[PSI-69].

| Number | Cited | Source | OK |
| --- | --- | --- | --- |
| 90 | PSI-69 | sql | yes |
| 75 | PSI-69 | sql | yes |
| 66 | PSI-69 | sql | yes |

Citations: PSI-69 (FLEX, doi:10.60555/mbq8-0451)

SQL 1: 3 rows

```sql
WITH filtered AS (
  SELECT diluent, outcome
  FROM tests
  WHERE psi_id = 'PSI-69'
    AND coalesce(extra->>'is_duplicate','false') <> 'true'
    AND (outcome IS NOT NULL AND outcome <> 'no_ignition')
)
SELECT diluent,
       100.0 * SUM(CASE WHEN outcome = 'extinction' THEN 1 ELSE 0 END) / COUNT(*) AS pct_extinction
FROM filtered
WHERE diluent IN ('CO2','N2','He')
GROUP BY diluent;
```

LLM calls:

- `groq:openai/gpt-oss-120b`: ok, prompt 1901 (est 1792), 0.87 s
- `groq:openai/gpt-oss-120b`: ok, prompt 2133 (est 2019), 0.51 s

### 3. How long did the concurrent and opposed flow fires burn in SAFFIRE-I?

Habitat: none. Expected source: insight saffire_flow_direction.

> The average burn time for SAFFIRE-I tests was about **420 s for concurrent-flow fires** and **70 s for opposed-flow fires**[PSI-98].

| Number | Cited | Source | OK |
| --- | --- | --- | --- |
| 420 | PSI-98 | sql | yes |
| 70 | PSI-98 | sql | yes |

Citations: PSI-98 (SAFFIRE-I, doi:10.60555/0t15-1z43)

SQL 1: 2 rows, auto-fixed ["flow_direction -> extra->>'flow_direction'"]

```sql
SELECT (extra->>'flow_direction'), AVG(burn_time_s) AS avg_burn_s FROM tests WHERE experiment='SAFFIRE-I' AND (extra->>'flow_direction') IS NOT NULL AND burn_time_s IS NOT NULL GROUP BY (extra->>'flow_direction')
```

LLM calls:

- `groq:openai/gpt-oss-120b`: ok, prompt 1893 (est 1781), 0.68 s
- `groq:openai/gpt-oss-120b`: ok, prompt 2022 (est 1944), 0.21 s

### 4. How much test data covers this habitat, and what happened to the flames there?

Habitat: lunar. Expected source: insight coverage_gap and /coverage?habitat=lunar.

> The lunar-surface habitat (56.5 kPa, 34 % O₂) is only sparsely covered by ISS combustion data. Eleven CFI-G gas-jet tests fall within ±15 % pressure and ±3 % O₂ of those conditions. In that subset five flames stopped when the fuel flow was cut off (flow-terminated) and four extinguished on their own (self-extinguished) [PSI-159]. No FLEX droplet or other experiment tests lie this close, so the only observed behavior is that flames tend to die out rather than burn continuously under the habitat’s relatively low pressure and elevated O₂.

| Number | Cited | Source | OK |
| --- | --- | --- | --- |
| 56.5 | - | question | yes |
| 34 | - | question | yes |
| 15 | - | nearest_conditions | yes |
| 3 | - | nearest_conditions | yes |

Citations: PSI-159 (ACME CFI-G, doi:10.60555/cyt1-kh64)

LLM calls:

- `groq:openai/gpt-oss-120b`: ok, prompt 1921 (est 1803), 0.47 s
- `groq:openai/gpt-oss-120b`: ok, prompt 2700 (est 2398), 0.88 s

### 5. In CFI-G, what share of flames kept burning until the fuel flow was stopped at 30% O2 or more, compared with below 25%?

Habitat: none. Expected source: insight cfig_high_o2_persistence (31 of 92 ignited flames).

> About one-third of the CFI-G flames (33.7 %) kept burning until the fuel flow was stopped when the ambient O₂ fraction was ≥ 30 % [PSI-159]. By contrast, none of the tests with O₂ < 25 % showed that behavior. [PSI-159]

| Number | Cited | Source | OK |
| --- | --- | --- | --- |
| 33.7 | PSI-159 | sql | yes |
| 30 | PSI-159 | question | yes |
| 25 | PSI-159 | question | yes |

Citations: PSI-159 (ACME CFI-G, doi:10.60555/cyt1-kh64)

SQL 1: 1 rows

```sql
WITH filtered AS (
  SELECT o2_frac, outcome
  FROM tests
  WHERE psi_id='PSI-159'
    AND extra->>'row_kind' IS NULL
    AND coalesce(extra->>'is_duplicate','false') <> 'true'
    AND outcome IS NOT NULL
    AND outcome <> 'no_ignition'
)
SELECT
  SUM(CASE WHEN o2_frac >= 0.30 AND outcome='flow_terminated' THEN 1 ELSE 0 END)::DOUBLE / NULLIF(SUM(CASE WHEN o2_frac >= 0.30 THEN 1 ELSE 0 END),0) AS share_high,
  SUM(CASE WHEN o2_frac < 0.25 AND outcome='flow_terminated' THEN 1 ELSE 0 END)::DOUBLE / NULLIF(SUM(CASE WHEN o2_frac < 0.25 THEN 1 ELSE 0 END),0) AS share_low
FROM filtered;
```

LLM calls:

- `groq:openai/gpt-oss-120b`: ok, prompt 1910 (est 1793), 0.98 s
- `groq:openai/gpt-oss-120b`: ok, prompt 2219 (est 2072), 0.74 s

### 6. Could the test data tell us how the Apollo 1 cabin fire would have behaved?

Habitat: apollo1. Expected source: /coverage?habitat=apollo1 (untested, nearest 20 box widths) and the Apollo 1 NASA page.

> The nearest ISS combustion tests do not cover the Apollo 1 cabin atmosphere (115 kPa, 100 % O₂). The closest tested conditions are still far away, over 20 units in the combined pressure-O₂ space, and no experiment recorded outcomes at that pure-oxygen pressure. Consequently, the test database cannot directly predict flame spread, burn rate, or extinction behavior for the Apollo 1 fire; any inference would be an extrapolation beyond the measured regime. Historical investigations of the accident describe a rapid, uncontrollable fire in a pure-oxygen environment, but the ISS data alone do not provide quantitative behavior for those conditions. [PSI-159] [NASA:apollo_1]

| Number | Cited | Source | OK |
| --- | --- | --- | --- |
| 1 | - | question | yes |
| 115 | - | question | yes |
| 100 | - | question | yes |
| 20 | - | nearest_conditions | yes |
| 1 | - | question | yes |

Citations: PSI-159 (ACME CFI-G, doi:10.60555/cyt1-kh64), NASA:apollo_1 (Apollo 1 fire (1967))

LLM calls:

- `groq:openai/gpt-oss-120b`: ok, prompt 1924 (est 1801), 0.43 s
- `groq:openai/gpt-oss-120b`: ok, prompt 1986 (est 1917), 0.34 s
- `groq:openai/gpt-oss-120b`: ok, prompt 2935 (est 2678), 0.79 s

### 7. How flammable is Kapton at 5% O2 on Mars?

Habitat: none. Expected source: Kapton only in SAME-R (29) and SAME (1) smoke tests; nothing near 5% O2; no Martian gravity tests.

> No Kapton tests were recorded at a 5 % O₂ mixture, and the nearest ISS combustion data to a Mars-like habitat (≈0.6 kPa, 5 % O₂) are sparse, with only a few CFI-G runs at higher O₂ fractions and no outcomes at the target condition. Consequently the flammability of Kapton under 5 % O₂ on Mars is not directly characterized by the ISS test program.

| Number | Cited | Source | OK |
| --- | --- | --- | --- |
| 5 | - | question | yes |
| 0.6 | - | NO SOURCE | NO |
| 5 | - | question | yes |
| 5 | - | question | yes |

Citations: none

SQL 1: 1 rows

```sql
SELECT COUNT(*) AS cnt FROM tests WHERE material='Kapton' AND o2_frac=0.05 AND coalesce(extra->>'is_duplicate','false')<>'true'
```

LLM calls:

- `groq:openai/gpt-oss-120b`: ok, prompt 1921 (est 1811), 0.66 s
- `groq:openai/gpt-oss-120b`: ok, prompt 2017 (est 1940), 1.17 s
- `groq:openai/gpt-oss-120b`: ok, prompt 2796 (est 2536), 0.76 s

