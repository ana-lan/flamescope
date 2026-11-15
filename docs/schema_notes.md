# Schema notes (Phase 2)

Source: `backend/ingest/profile_tables.py` report over `backend/data/raw/tables/` (21 CSVs, 1,999 flight rows + 8 rows in PSI-142). Mappers: `backend/ignitiq/map_per_test.py` (1,871 rows) and `map_summary.py` (128 rows).

## Core `tests` columns

| Column | Type | Meaning |
| --- | --- | --- |
| psi_id | text | e.g. `PSI-69` |
| experiment | text | acronym, e.g. `FLEX`, `Flame Design` |
| test_id | text | source id; repeats get `#2`, `#3` with the original in `extra.source_test_id`; `row<n>` when none |
| fuel | text | lowercase common name (`methanol`, `heptane`, `ethylene`, `methane`); blend fraction in `extra.fuel_frac` |
| material | text | solid sample material (PMMA, SIBAL, Kapton...) |
| pressure_kpa | float | ambient pressure, kPa (1 atm = 101.325, 1 bar = 100, 1 mmHg = 0.133322) |
| o2_frac | float | **ambient** O2 mole fraction, 0 to 1. Null for inverse flames |
| diluent | text | dominant non-O2 ambient gas: `N2`, `CO2`, `He` |
| diluent_frac | float | mole fraction of that diluent |
| flow_cm_s | float | imposed flow velocity, cm/s |
| outcome | text | normalized: `extinction`, `completion`, `disruption`, `self_extinguished`, `flow_terminated`, `no_ignition`, or null |
| burn_time_s | float | seconds |
| spread_rate_mm_s | float | flame spread rate, mm/s |
| extra | JSON | parsed experiment-specific fields, flags, and the raw row (see layout below) |

Rules:
- Every source row becomes one `tests` row (count must equal 1,999). Duplicates are kept and flagged `extra.is_duplicate = true`.
- `extra` layout: parsed fields and flags at the top level, the untouched CSV row under `extra.raw`, plus `source_file` and `source_row`. Summary-table rows carry `extra.row_kind = "summary"`.
- Every row passes the pydantic `TestRow` model (`ignitiq/schema.py`): o2 and diluent fractions in [0, 1], pressure > 0, outcome in the fixed vocabulary.
- Non-numeric values in numeric columns (`RAMP`, `none`, `n/a`) become null in core; the raw string stays in `extra.raw`.
- Values with units (`.33 cm`, `30 cm/s`, `145 s`) are parsed by regex only where the column is known to carry units; pure-number columns use strict parsing.
- Ranges (`21.5 - 21.7`, `22.1 to 22.0`) become the midpoint; lists (`21; 26.5; 40`) go to `extra.*_values` and leave the core column null.
- Percent columns are divided by 100.
- `diluent` / `diluent_frac` are filled only when the source gives ambient gas fractions (FLEX, CFI, s-Flame). Fuel-stream diluents go to `extra.fuel_diluent`.

## Per experiment

### PSI-69 FLEX (274, cp1252) - per test, droplets
- test_id `FLEX Test #`; fuel `Fuel` (methanol, heptane)
- pressure_kpa `Ambient pressure; mmHg` x 0.133322; **0 is invalid (1 row), set null, flag `invalid_pressure`**
- o2_frac `O initial ...` (O2); diluents `N initial` (N2), `CO initial` (**CO2**), `He initial`; diluent = largest of the three
- outcome `Test end` (Disruption, Extinction, Completion)
- burn_time_s `Burn time; s`
- extra: identifier, date, droplet_d0_mm, extinction_d_mm, burning_rate_k_mm2_s (the `Burning rate; mm` column is the burning-rate constant K, not spread rate), all gas fractions
- 1 duplicated `FLEX Identifier` (273 unique of 274)

### PSI-39 CFI (87) - per test, droplets, cool flames
- test_id `Flex Number` (79 unique; 8 duplicate rows, flag)
- fuel `Fuel`: `n-dodecane`, `n-dodecane/iso-dodecane 75/25`, `n-dodecane/iso-dodecane 60/40`
- pressure_kpa from text `Pressure` (`1 atm`... `3 atm`) x 101.325
- o2_frac `Oxygen`; diluents `Nitrogen`, `Helium`
- extra: date, CIR id, fiber (Yes/No)
- no outcome column

### PSI-68 FLEX-2 (8) - summary, one row per fuel
- fuel from `Sample (Fuel Type)` without `(pure)`; all other values are ranges shared by every row
- core pressure/o2/flow null; extra lists: `o2_frac_values` [0.17, 0.21, 0.25, 0.3], `pressure_kpa_values` (0.5 to 3 atm), `flow_cm_s_range` [0.1, 5], `droplet_d0_mm_range` [1.5, 5], `ambient_mixture` `O2/N2 or O2/He`

### PSI-10 ACME Flame Design (207 normal + 120 inverse) - per test, gas jet
- Normal: test_id `Test`; fuel `Fuel` (ethylene, propane); o2_frac `XO2 (init)`; pressure `pinit (atm)` x 101.325
  - 60 rows have `RAMP` (57) or `RAMPED` (3) in flow columns: null in core, `extra.ramped = true`
- Inverse: no fuel column, fuel = ethylene (`XC2H4`); O2 comes from the burner: `XO2` to `extra.oxidizer_o2_frac`, **o2_frac null**; pressure `pinit (atm)`
  - 11 non-numeric values in XO2/flow columns: null + raw in extra
- extra: flame_type, day, mass flows, Zst, Tad_K, pfinal/pmean as kPa
- no outcome column; diluent null (balance gas not stated)

### PSI-159 ACME CFI-G (179 normal + 154 inverse) - per test, gas jet, cool flames
- Normal: test_id `Test`; fuel `Fuel` (ethane, propane, butane mixes); o2_frac `XO2 before test`; pressure `approx p (bar)` x 100
- Inverse: fuel `Fuel`; `Xf before test` to `extra.ambient_fuel_frac`; `XO2` to `extra.oxidizer_o2_frac`, **o2_frac null**; 861 blank rows in the file are dropped
- outcome from `Self-ext or flow term`: SE to self_extinguished, FT to flow_terminated, `-` to null; `Comments` like "Failed to ignite" / "Not ignited" to no_ignition
- burn_time_s `burn time (sec)`
- extra: flame_type, hot_ignition (yes/no/flash), cool_flame (normal only, 8 rows filled), TFP, Tad_K, Zst, peak burner T, color, comments

### PSI-26 BASS (122) - sample list only
- test_id `As Run Test #` (1 blank row: fallback `row<n>`); material `Fuel Sample Material` (SIBAL, PMMA sphere...)
- core gas/pressure/outcome null; extra: date, sample number, planned test number

### PSI-25 BASS-II (129) - per test, solid fuels
- test_id `Test #`; material `Fuel Sample Material` (e.g. `100 micron PMMA film 2 cm wide`)
- o2_frac `Calibrated initial O2 % by vol` / 100; CO2 initial / 100 to extra
- pressure not given: null
- flow: `Air display` is a fan setting with text (`3 5 approaching 10`), not cm/s: extra.raw only
- extra: PI, date, flow restrictor, final O2/CO2, CO ppm

### PSI-107 SPICE (469) - per test, smoke points
- test_id `GMT date`-`GMT ignition`; fuel `Fuel` (normalize `75 % Propylene` to `75% propylene`)
- flow_cm_s `Air Rate (cm/s)` (8 negatives down to -5.92: keep, flag `extra.negative_flow`)
- burn_time_s = `GMT Flame Off` minus `GMT ignition` (HH:MM:SS or HH.MM.SS); non-times (`Ku LOS` = Ku-band loss of signal, `no ku`, `n/a`, `1744`) stay null; 442 of 469 filled
- 34 exact duplicate rows: flag
- pressure/o2 not given: null; extra: nozzle_mm, fuel rates

### PSI-101 SAME-R (109) - per test, smoke
- test_id `SAME Test #` (has `a` suffixes); material `Sample Type` (Kapton, Silicone, Lampwick, Teflon...)
- flow_cm_s `Inlet velocity (cm/s)`
- extra: description, date, Rt/R0, duration, aging times

### PSI-102 SAME (8) - summary
- test_id `Sample #`; material = text before `:` in `Sample Material`
- rows 5 to 8 say "same conditions as 1-4": core null, `extra.same_as = "1-4"`
- flow_cm_s `Air Flow (cm/s)` where present; extra: weight_loss_mg_min, aging_s

### PSI-98 SAFFIRE-I (4) - large-scale solid fire
- rows S1, S2 are burns; rows 3 to 4 are flow-visualization records: `extra.record_type = flow_visualization`, material null
- material SIBAL Fabric; o2_frac from `Percent O2` (`21.5 - 21.7` midpoint, `~ 21.5`) / 100; flow 20 cm/s; burn_time_s; flow direction to extra
- pressure null (Cygnus cabin, not given)

### PSI-99 SAFFIRE-II (15) - units in values
- 9 rows filled, 6 sparse: keep all
- thickness: strict parse (one number + mm or cm): `037 mm` (3 rows) is a typo for 0.37 mm (flag `thickness_typo_fixed`), `1 cm` gives 10 mm, `See Fig. 5` and `0.85 and 0.37 mm` give null
- o2 from `Percent O2 (Note 1)` (ranges and `~`) / 100; flow from `20 cm/s`
- burn_time_s from `145 s` (`Insignificant` to null)
- spread_rate_mm_s from `?-g Spread Length` (`?` is micro; only values carrying `mm/s`); 1-g burn length and spread rate to extra
- material includes `PMMA & Nomex`

### PSI-100 SAFFIRE-III (2)
- material SIBAL; flow 30 cm/s; dimensions parsed from text; direction to extra; o2/pressure null
- note: SAFFIRE-I lists length 40.6 / width 94, SAFFIRE-III lists length 94 / width 40.6 (same sample size, columns swapped)

### PSI-106 SLICE (12) - summary
- fuel from `Fuel Type` (e.g. `40% CH4 (balance N2)`): fuel `methane`, extra.fuel_frac 0.4, extra.fuel_diluent N2 (fuel-stream diluent, not ambient, so core `diluent` stays null)
- `Test Date` sometimes carries note text: date to `extra.date`, rest to `extra.note`

### PSI-20 ACME BRE (18) - summary, one row per test day
- fuel from `Fuel Bottle` (`100% C2H4`, `100%C2H4`); burner size to extra
- `Oxygen Conc (percent)` is usually a list (`21; 26.5; 40`): `extra.o2_frac_values`, core o2 null
- `3400%` / `2100%` are Excel percent-format artifacts (34 and 21 shown as % cells): values over 100 are divided by 100 again, flagged `excel_percent_fixed`; these are the 2 single-value rows and fill core o2_frac
- extra: flames_ignited, notes

### PSI-21 ACME CLD (32) - summary, one row per test day
- fuel from `Fuel Bottle`: **CH5, CH6, CH7... are autofill typos for CH4** (8 rows), normalized and flagged `autofill_fixed`
- test day YYDDD to `extra.date` (ISO); conc range, MFC settings, flames_ignited to extra

### PSI-22 ACME E-Field (32) - summary, one row per test day
- 11 continuation rows hold only `Fuel Conc`: identity columns forward-filled from the row above (flames_ignited is not filled), flag `extra.continuation = true`
- 4 duplicate rows after the fill: flag
- fuel from `Fuel Bottle`, fraction from `Fuel Conc`; mesh polarity, flames_ignited to extra

### PSI-23 ACME s-Flame (18) - summary, one row per test day
- `Atmosphere*` like `~30% O2 with N2`: o2_frac 0.30, diluent N2, diluent_frac 1 - o2 (**N3, N4 are autofill typos for N2**, 7 rows flagged); `*Atmosphere is ~1 atm`: pressure_kpa 101.325, flag `pressure_approx`
- fuel from `Fuel Bottle` (`50% C2H4 with N2`)
- extra: test type (N2 vs He dilution), date, flames_ignited

### PSI-142 (8, ground) - not loaded into `tests`
- figure index pointing at publications; used as RAG text in Phase 3

## Fill counts (verified Phase 2.3 and 2.4)

- pressure_kpa: FLEX 273, CFI 87, Flame Design 327, CFI-G 333, s-Flame 18
- o2_frac: FLEX 274, CFI 87, Flame Design normal 207, CFI-G normal 179, BASS-II 129, SAFFIRE-I 2, SAFFIRE-II 9, BRE 2, s-Flame 18
- outcome: FLEX 274, CFI-G 284
- burn_time_s: FLEX 266, CFI-G 329, SPICE 442, SAFFIRE-I 2, SAFFIRE-II 5
- spread_rate_mm_s: SAFFIRE-II 2
- flow_cm_s: SPICE 444, SAME-R 109, SAME 4, SAFFIRE-I 2, SAFFIRE-II 9, SAFFIRE-III 2
