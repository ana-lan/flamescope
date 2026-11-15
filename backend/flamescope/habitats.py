"""Habitat atmosphere presets, each traced to a NASA source.

Loaded into the `habitats` table by db.py. Coverage preview from backend/:
    uv run python -m flamescope.habitats
"""
from __future__ import annotations

import pandas as pd

PSI_KPA = 6.894757

# (slug, name, kind, psia, o2_frac, source, url, note)
_PRESETS = [
    ("iss", "ISS", "current", 14.7, 0.21,
     "NASA NTRS 20240003211, Moon to Mars: Exploration Atmosphere",
     "https://ntrs.nasa.gov/citations/20240003211",
     "Sea-level atmosphere used on the ISS."),
    ("gateway", "Gateway / staged", "current", 10.2, 0.265,
     "NASA MSFC, ECLS System Options for Mars Transit and Mars Surface Missions (NTRS 20230009095)",
     "https://ntrs.nasa.gov/citations/20230009095",
     "Shuttle EVA staging atmosphere; planned for Gateway docked ops."),
    ("lunar", "Lunar / Mars surface habitat", "proposed", 8.2, 0.34,
     "NASA Exploration Atmosphere (NTRS 20240003211); MSFC Mars surface habitat (NTRS 20230009095)",
     "https://ntrs.nasa.gov/citations/20240003211",
     "Exploration Atmosphere: chosen as a compromise between flammability, hypoxia, DCS risk and prebreathe time."),
    ("apollo1", "Apollo 1 (historical)", "historical", 16.7, 1.0,
     "NASA Moon to Mars: Exploration Atmosphere, Trilateral S&MA Conference 2024",
     "https://ntrs.nasa.gov/citations/20240003211",
     "Pure-O2 pad test atmosphere of the 1967 Apollo 1 fire. Reference only, not a design target."),
]

COLUMNS = ["slug", "name", "kind", "pressure_psia", "pressure_kpa", "o2_frac", "pp_o2_kpa",
           "source", "source_url", "note"]


def habitats_df() -> pd.DataFrame:
    rows = []
    for slug, name, kind, psia, o2, src, url, note in _PRESETS:
        kpa = round(psia * PSI_KPA, 3)
        rows.append((slug, name, kind, psia, kpa, o2, round(kpa * o2, 2), src, url, note))
    return pd.DataFrame(rows, columns=COLUMNS)


COVERAGE_SQL = """
SELECT h.slug, t.experiment, count(*) AS n,
       round(min(t.pressure_kpa), 1) AS p_min, round(max(t.pressure_kpa), 1) AS p_max,
       round(min(t.o2_frac), 3) AS o2_min, round(max(t.o2_frac), 3) AS o2_max
FROM habitats h JOIN tests t
  ON abs(t.pressure_kpa - h.pressure_kpa) <= ? * h.pressure_kpa
 AND abs(t.o2_frac - h.o2_frac) <= ?
WHERE h.slug = ?
GROUP BY h.slug, t.experiment
ORDER BY n DESC
"""


def coverage_preview(con, p_tol: float = 0.15, o2_tol: float = 0.03) -> None:
    for slug, name, kpa, o2, pp in con.execute(
            "SELECT slug, name, pressure_kpa, o2_frac, pp_o2_kpa FROM habitats").fetchall():
        rows = con.execute(COVERAGE_SQL, [p_tol, o2_tol, slug]).fetchall()
        total = sum(r[2] for r in rows)
        print(f"\n{name} ({kpa:.1f} kPa, {o2:.1%} O2, ppO2 {pp} kPa): {total} tests within "
              f"±{p_tol:.0%} pressure, ±{o2_tol * 100:.0f} pts O2")
        for _, exp, n, p0, p1, a, b in rows:
            print(f"  {exp:<14} {n:>4}   p {p0}-{p1} kPa   O2 {a}-{b}")


if __name__ == "__main__":
    from flamescope.db import connect
    print(habitats_df()[["slug", "name", "kind", "pressure_kpa", "o2_frac", "pp_o2_kpa"]].to_string(index=False))
    coverage_preview(connect())
