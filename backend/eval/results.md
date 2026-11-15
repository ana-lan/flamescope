# IgnitIQ eval results

Live API: `https://ignit-iq.onrender.com`. Each question asked once with `fresh: true` (no cached answers). Expected numbers are computed from the database at run time.

**9 of 15 questions pass.** numbers 17/19 | citations 12/12 | facts 13/16 | sql 1/1 | grounding 12/15 | failovers 0 | p50 1.6 s, p95 2.0 s | tokens 73,072

| # | Type | Question | Result | Numbers | Citations | Facts | SQL | Grounding | Time | Model |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | count | How many FLEX droplet tests ended in extinction, and what were the lowest and highest ambient O2 levels in those tests? | PASS | ok | ok | - | - | ok | 1.5 s | groq:openai/gpt-oss-120b |
| 2 | share | In CFI-G, what share of flames kept burning until the fuel flow was stopped at 30% O2 or more, compared with below 25% O2? | PASS | ok | ok | ok | ok | ok | 1.8 s | groq:openai/gpt-oss-120b |
| 3 | share | Which suppressant gas put out FLEX droplet flames most often, comparing CO2, nitrogen and helium as the diluent? | FAIL | ok | ok | ok | - | FAIL | 1.9 s | groq:openai/gpt-oss-120b |
| 4 | duration | In SAFFIRE-I, how long did the fire burn with concurrent flow compared with opposed flow? | PASS | ok | ok | - | - | ok | 1.3 s | groq:openai/gpt-oss-120b |
| 5 | minimum | What is the lowest ambient oxygen level at which a heptane droplet burned completely in FLEX, and at what pressure? | FAIL | FAIL | ok | - | - | ok | 1.4 s | groq:openai/gpt-oss-120b |
| 6 | list | Which fuels were burned in the FLEX droplet tests? | PASS | - | ok | ok | - | ok | 1.3 s | groq:openai/gpt-oss-120b |
| 7 | coverage | How much test data covers this habitat, and what happened to the flames there? | FAIL | ok | ok | FAIL | - | ok | 1.9 s | groq:openai/gpt-oss-120b |
| 8 | coverage | How well do the ISS combustion tests cover this habitat's atmosphere? | PASS | ok | ok | - | - | ok | 1.6 s | groq:openai/gpt-oss-120b |
| 9 | coverage | Were any ISS combustion tests run in an atmosphere like the Apollo 1 cabin? | PASS | - | ok | ok | - | ok | 2.2 s | groq:openai/gpt-oss-120b |
| 10 | range | What range of pressures and ambient oxygen levels did the CFI-G experiment test? | FAIL | FAIL | ok | - | - | FAIL | 1.5 s | groq:openai/gpt-oss-120b |
| 11 | text | What was the FLEX investigation trying to learn? | PASS | - | ok | ok | - | ok | 1.1 s | groq:openai/gpt-oss-120b |
| 12 | text | What happened in the 1997 fire on the Mir space station? | PASS | - | ok | ok | - | ok | 2.0 s | groq:openai/gpt-oss-120b |
| 13 | out of scope | How flammable is Kapton in microgravity according to the test data? | FAIL | - | - | FAIL | - | ok | 1.8 s | groq:openai/gpt-oss-120b |
| 14 | data gap | What flame spread rates did the BASS experiment measure? | FAIL | - | - | FAIL | - | FAIL | 1.8 s | groq:openai/gpt-oss-120b |
| 15 | maximum | What is the highest ambient oxygen level tested in any of the ISS combustion experiments? | PASS | ok | - | - | - | ok | 1.6 s | groq:openai/gpt-oss-120b |

## Failures

### Q3: Which suppressant gas put out FLEX droplet flames most often, comparing CO2, nitrogen and helium as the diluent?
- grounding ok: {"numbers_checked": 15, "numbers": [{"value": "165", "cited": [], "source": "sql", "ok": true}, {"value": "250", "cited": [], "source": "sql", "ok": true}, {"value": "66", "cited": [], "source": null, "ok": false}, {"value": "18", "cited": 

> Nitrogen (N₂) suppressed FLEX droplet flames in the highest share of tests, 165 extinctions out of 250 runs (66 %). Carbon-dioxide (CO₂) extinguished 18 of 20 droplets (90 %), and helium (He) did so in 3 of 4 cases (75 %).    **Evidence** - Query of the FLEX droplet experiment [PSI-69] shows 250 N₂ tests with 165 extinctions, 20 CO₂ tests with 18 extinctions, and 4 He tests with 3 extinctions[PSI-

### Q5: What is the lowest ambient oxygen level at which a heptane droplet burned completely in FLEX, and at what pressure?
- number 102.271: answer has ['0.14', '14', '2', '71']

> The lowest ambient oxygen fraction at which a heptane droplet burned completely in the FLEX experiment was 0.14 (14 % O₂) at an ambient pressure of ≈ 71 kPa. [PSI-69]

### Q7: How much test data covers this habitat, and what happened to the flames there?
- says 'still burning': 

> The lunar-surface habitat (56 kPa, 34 % O₂) is only sparsely covered by ISS combustion data. Eleven CFI-G gas-jet tests fall within the ±15 % pressure / ±3 % O₂ envelope; no FLEX droplet tests lie that close. In those CFI-G runs the flames either self-extinguished (4 cases) or continued until the fuel flow was stopped (5 cases)[PSI-159]. No other experiments recorded outcomes near those conditions

### Q10: What range of pressures and ambient oxygen levels did the CFI-G experiment test?
- number 50.665: answer has ['50', '304', '0.18', '18', '2', '0.40', '40', '2']
- grounding ok: {"numbers_checked": 6, "numbers": [{"value": "50", "cited": ["PSI-159"], "source": null, "ok": false}, {"value": "304", "cited": ["PSI-159"], "source": "sql", "ok": true}, {"value": "0.18", "cited": ["PSI-159"], "source": "sql", "ok": true}

> The CFI-G (Continuous Flow Ignition - Gas) experiment covered cabin-like pressures from about 50 kPa up to 304 kPa and ambient oxygen fractions from roughly 0.18 (≈18 % O₂) to 0.40 (≈40 % O₂)[PSI-159].

### Q13: How flammable is Kapton in microgravity according to the test data?
- says 'smoke': 

> Kapton was tested in 30 microgravity experiments (SAME-R and SAME), but none of those tests recorded an outcome (ignition, extinction, etc.). Consequently the ISS combustion database does not contain quantitative flammability results for Kapton in microgravity. [PSI-101] [PSI-102]

### Q14: What flame spread rates did the BASS experiment measure?
- says the data does not cover it: 
- grounding ok: {"numbers_checked": 2, "numbers": [{"value": "0.9", "cited": ["PSI-25", "PSI-26"], "source": null, "ok": false}, {"value": "30", "cited": ["PSI-25", "PSI-26"], "source": null, "ok": false}], "unverified": ["0.9", "30"], "misattributed": [],

> The BASS series recorded flame-spread rates of about **0.9 mm s⁻¹** on average (≈ 30 mm min⁻¹) across its tests[PSI-25][PSI-26].

