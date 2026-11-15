# IgnitIQ

AI fire safety analyst for space habitats, built for NASA Space Apps 2026 (Flame in Freefall).

Pick a habitat atmosphere, ask a fire safety question, and get an answer computed from real ISS combustion test rows and cited to the NASA PSI investigation behind it.

- Numbers come from SQL over 1,999 test rows from 18 ISS combustion investigations
- Explanations come from retrieval over investigation write-ups, publication abstracts and NASA incident reports
- Every number in an answer is traced to a tool result and checked against its citation

Repo layout: `backend/` (FastAPI, DuckDB, agent) and `web/` (Next.js). The full README with setup, architecture and data credits comes in Phase 5.