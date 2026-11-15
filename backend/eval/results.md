# IgnitIQ eval results

Live API: `https://ignit-iq.onrender.com`. Each question asked once with `fresh: true` (no cached answers). Expected numbers are computed from the database at run time.

**14 of 15 questions pass.** numbers 18/19 | citations 12/12 | facts 19/19 | sql 1/1 | grounding 15/15 | failovers 0 | p50 1.6 s, p95 2.2 s | tokens 73,519

| # | Type | Question | Result | Numbers | Citations | Facts | SQL | Grounding | Time | Model |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | count | How many FLEX droplet tests ended in extinction, and what were the lowest and highest ambient O2 levels in those tests? | PASS | ok | ok | - | - | ok | 1.5 s | groq:openai/gpt-oss-120b |
| 2 | share | In CFI-G, what share of flames kept burning until the fuel flow was stopped at 30% O2 or more, compared with below 25% O2? | PASS | ok | ok | ok | ok | ok | 1.8 s | groq:openai/gpt-oss-120b |
| 3 | share | Which suppressant gas put out FLEX droplet flames most often, comparing CO2, nitrogen and helium as the diluent? | PASS | ok | ok | ok | - | ok | 3.0 s | groq:openai/gpt-oss-120b |
| 4 | duration | In SAFFIRE-I, how long did the fire burn with concurrent flow compared with opposed flow? | PASS | ok | ok | - | - | ok | 1.3 s | groq:openai/gpt-oss-120b |
| 5 | minimum | What is the lowest ambient oxygen level at which a heptane droplet burned completely in FLEX, and at what pressure? | FAIL | FAIL | ok | - | - | ok | 1.6 s | groq:openai/gpt-oss-120b |
| 6 | list | Which fuels were burned in the FLEX droplet tests? | PASS | - | ok | ok | - | ok | 1.3 s | groq:openai/gpt-oss-120b |
| 7 | coverage | How much test data covers this habitat, and what happened to the flames there? | PASS | ok | ok | ok | - | ok | 2.2 s | groq:openai/gpt-oss-120b |
| 8 | coverage | How well do the ISS combustion tests cover this habitat's atmosphere? | PASS | ok | ok | - | - | ok | 1.6 s | groq:openai/gpt-oss-120b |
| 9 | coverage | Were any ISS combustion tests run in an atmosphere like the Apollo 1 cabin? | PASS | - | ok | ok | - | ok | 2.2 s | groq:openai/gpt-oss-120b |
| 10 | range | What range of pressures and ambient oxygen levels did the CFI-G experiment test? | PASS | ok | ok | - | - | ok | 1.6 s | groq:openai/gpt-oss-120b |
| 11 | text | What was the FLEX investigation trying to learn? | PASS | - | ok | ok | - | ok | 1.1 s | groq:openai/gpt-oss-120b |
| 12 | text | What happened in the 1997 fire on the Mir space station? | PASS | - | ok | ok | - | ok | 2.0 s | groq:openai/gpt-oss-120b |
| 13 | out of scope | How flammable is Kapton in microgravity according to the test data? | PASS | - | - | ok | - | ok | 1.8 s | groq:openai/gpt-oss-120b |
| 14 | data gap | What flame spread rates did the BASS experiment measure? | PASS | - | - | ok | - | ok | 0.8 s | groq:openai/gpt-oss-120b |
| 15 | maximum | What is the highest ambient oxygen level tested in any of the ISS combustion experiments? | PASS | ok | - | - | - | ok | 1.6 s | groq:openai/gpt-oss-120b |

## Failures

### Q5: What is the lowest ambient oxygen level at which a heptane droplet burned completely in FLEX, and at what pressure?
- number 102.271: answer has ['0.14', '14', '2', '71']

> The lowest ambient oxygen fraction at which a heptane droplet achieved complete combustion in the FLEX experiment was 0.14 (14 % O₂) and it occurred at an ambient pressure of about 71 kPa. [PSI-69]

