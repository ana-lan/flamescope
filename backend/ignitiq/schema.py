"""Core `tests` schema and shared parsing helpers.

Every mapper (2.3, 2.4) builds TestRow objects using these helpers.
Helpers return None, never NaN, so DuckDB stores real NULLs and `extra` stays valid JSON.

Self-test from backend/:  uv run python -m ignitiq.schema
"""
from __future__ import annotations

import math
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ---------------------------------------------------------------- model

Outcome = Literal[
    "extinction", "completion", "disruption",
    "self_extinguished", "flow_terminated", "no_ignition",
]

CORE_COLUMNS = [
    "psi_id", "experiment", "test_id", "fuel", "material", "pressure_kpa",
    "o2_frac", "diluent", "diluent_frac", "flow_cm_s", "outcome",
    "burn_time_s", "spread_rate_mm_s",
]


class TestRow(BaseModel):
    """One row of the long `tests` table. Fails loudly on bad values."""

    model_config = ConfigDict(extra="forbid")

    psi_id: str = Field(pattern=r"^PSI-\d+$")
    experiment: str
    test_id: str
    fuel: str | None = None
    material: str | None = None
    pressure_kpa: float | None = Field(default=None, gt=0, lt=1000)
    o2_frac: float | None = Field(default=None, ge=0, le=1)
    diluent: Literal["N2", "CO2", "He"] | None = None
    diluent_frac: float | None = Field(default=None, ge=0, le=1)
    flow_cm_s: float | None = None
    outcome: Outcome | None = None
    burn_time_s: float | None = Field(default=None, ge=0)
    spread_rate_mm_s: float | None = Field(default=None, ge=0)
    extra: dict[str, Any] = Field(default_factory=dict)

    @field_validator("extra")
    @classmethod
    def _json_safe(cls, v: dict) -> dict:
        return {k: _nan_to_none(x) for k, x in v.items()}

    def record(self) -> dict:
        """Flat dict for building a DataFrame (extra stays a dict until db.py dumps it)."""
        return self.model_dump()


def _nan_to_none(x: Any) -> Any:
    if isinstance(x, float) and math.isnan(x):
        return None
    if isinstance(x, list):
        return [_nan_to_none(i) for i in x]
    if isinstance(x, dict):
        return {k: _nan_to_none(i) for k, i in x.items()}
    return x


# ---------------------------------------------------------------- text and numbers

NULLS = {"", "-", "n/a", "na", "none", "nan", "null", "insignificant"}
_NUM = r"[-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][-+]?\d+)?"


def clean(v: Any) -> str | None:
    """Strip whitespace; map empty and placeholder strings to None."""
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    s = str(v).replace("\r", " ").strip()
    return None if s.lower() in NULLS else s


def num(v: Any) -> float | None:
    """First number in a string: '.33 cm' -> 0.33, '~ 21.5' -> 21.5, '1,234' -> 1234."""
    s = clean(v)
    if s is None:
        return None
    m = re.search(_NUM, s.replace(",", ""))
    return float(m.group(0)) if m else None


def num_or_mid(v: Any) -> float | None:
    """A number, or the midpoint of a range: '21.5 - 21.7' -> 21.6, '22.1 to 22.0' -> 22.05."""
    s = clean(v)
    if s is None:
        return None
    m = re.fullmatch(rf"\s*~?\s*({_NUM})\s*(?:-|to|–)\s*({_NUM})\s*\D*", s)
    if m:
        a, b = float(m.group(1)), float(m.group(2))
        return round((a + b) / 2, 6)
    return num(s)


def num_list(v: Any) -> list[float]:
    """All numbers in a string: '0.5; 1.0; 1.5; 2.0; or 3.0' -> [0.5, 1.0, 1.5, 2.0, 3.0]."""
    s = clean(v)
    return [float(x) for x in re.findall(_NUM, s)] if s else []


def is_numeric(v: Any) -> bool:
    s = clean(v)
    return s is not None and re.fullmatch(rf"\s*{_NUM}\s*", s.replace(",", "")) is not None


def strict_num(v: Any) -> float | None:
    """Number only if the whole cell is numeric; 'RAMPED' or '3 5 approaching 10' -> None."""
    return float(clean(v).replace(",", "")) if is_numeric(v) else None


def pct(v: Any) -> float | None:
    """Percent to fraction, range-aware: '22.2' -> 0.222, '21.5 - 21.7' -> 0.216."""
    x = num_or_mid(v)
    return None if x is None else round(x / 100, 6)


# ---------------------------------------------------------------- units

KPA_PER = {"kpa": 1.0, "atm": 101.325, "bar": 100.0, "mmhg": 0.133322, "torr": 0.133322, "psi": 6.894757}


def to_kpa(value: Any, unit: str | None = None) -> float | None:
    """Pressure to kPa. Unit given, or read from text ('1.25 atm'). Zero or negative -> None."""
    x = num(value)
    if x is None:
        return None
    if unit is None:
        m = re.search(r"(kpa|atm|bar|mmhg|torr|psi)", str(value).lower())
        if not m:
            raise ValueError(f"no pressure unit in {value!r}")
        unit = m.group(1)
    kpa = x * KPA_PER[unit.lower()]
    return round(kpa, 3) if kpa > 0 else None


# ---------------------------------------------------------------- time

def hms_to_s(v: Any) -> float | None:
    """'14:37:08' -> seconds since midnight. Anything else -> None."""
    s = clean(v)
    if s is None:
        return None
    m = re.fullmatch(r"(\d{1,2})[:.](\d{2})[:.](\d{2}(?:\.\d+)?)", s)
    if not m:
        return None
    h, mi, sec = int(m.group(1)), int(m.group(2)), float(m.group(3))
    return h * 3600 + mi * 60 + sec


def duration_s(start: Any, end: Any) -> float | None:
    """end - start for HH:MM:SS clock times, wrapping past midnight."""
    a, b = hms_to_s(start), hms_to_s(end)
    if a is None or b is None:
        return None
    d = b - a
    return d + 86400 if d < 0 else d


# ---------------------------------------------------------------- gases and fuels

_AUTOFILL = [(re.compile(r"\bCH[5-9]\b"), "CH4"), (re.compile(r"\bN[3-9]\b"), "N2")]


def fix_autofill(v: Any) -> tuple[str | None, bool]:
    """Undo Excel drag-fill typos: CH5..CH9 -> CH4, N3..N9 -> N2. Returns (text, changed)."""
    s = clean(v)
    if s is None:
        return None, False
    out = s
    for pat, rep in _AUTOFILL:
        out = pat.sub(rep, out)
    return out, out != s


_FORMULA = r"(C\d*H\d+|CH4|H2|O2|N2|He|CO2)"


def parse_fuel_bottle(v: Any) -> tuple[str | None, float | None, str | None]:
    """'40% CH4 (balance N2)' -> ('CH4', 0.4, 'N2'); '100%C2H4' -> ('C2H4', 1.0, None)."""
    s, _ = fix_autofill(v)
    if s is None:
        return None, None, None
    m = re.search(rf"({_NUM})\s*%\s*{_FORMULA}", s)
    if not m:
        f = re.search(_FORMULA, s)
        return (f.group(1) if f else s), None, None
    frac = round(float(m.group(1)) / 100, 6)
    fuel = m.group(2)
    dil = re.search(r"(?:balance|with)\s+(N2|He|CO2)", s)
    return fuel, frac, (dil.group(1) if dil else None)


def dominant_diluent(fracs: dict[str, float | None]) -> tuple[str | None, float | None]:
    """Largest non-zero diluent: {'N2': .09, 'CO2': .7, 'He': 0} -> ('CO2', 0.7)."""
    present = {k: v for k, v in fracs.items() if v is not None and v > 0}
    if not present:
        return None, None
    k = max(present, key=present.get)
    return k, present[k]


# ---------------------------------------------------------------- outcomes and keys

_OUTCOMES = {
    "extinction": "extinction", "completion": "completion", "disruption": "disruption",
    "se": "self_extinguished", "self-extinguished": "self_extinguished",
    "ft": "flow_terminated", "flow terminated": "flow_terminated",
    "no ignition": "no_ignition", "not ignited": "no_ignition", "failed to ignite": "no_ignition",
}


# Plain-English meaning of each outcome code. Tool results send these next to
# the codes so the model never has to guess (e.g. flow_terminated = still burning).
OUTCOME_MEANINGS = {
    "extinction": "went out before the fuel was used up",
    "completion": "burned until the droplet was used up",
    "disruption": "broke apart while burning",
    "self_extinguished": "went out on its own while fuel was still flowing",
    "flow_terminated": "still burning when the fuel flow was stopped",
    "no_ignition": "did not ignite",
}


def outcome(v: Any) -> str | None:
    """Map a raw outcome to the shared vocabulary; unknown values -> None."""
    s = clean(v)
    return _OUTCOMES.get(s.lower()) if s else None


def snake(col: str) -> str:
    """Source header to an `extra` key: 'Burn Time (s)' -> 'burn_time_s', '?-g Burn Length' -> 'ug_burn_length'."""
    s = col.strip().replace("?-g", "ug").replace("%", "pct").replace("#", "num")
    s = re.sub(r"[^0-9a-zA-Z]+", "_", s).strip("_").lower()
    return s or "col"


def raw_extra(row: dict, skip: set[str] = frozenset()) -> dict:
    """All source columns not in `skip`, snake-cased, cleaned (None for blanks)."""
    return {snake(k): clean(v) for k, v in row.items() if k not in skip}


# ---------------------------------------------------------------- self-test

def _selftest() -> None:
    checks = [
        (clean("  n/a "), None), (clean("-"), None), (clean(" Insignificant"), None),
        (num(".33 cm"), 0.33), (num("~ 21.5"), 21.5), (num("145 s"), 145.0), (num("1,234.5"), 1234.5),
        (num("-5.92"), -5.92), (num("RAMPED"), None),
        (num_or_mid("21.5 - 21.7"), 21.6), (num_or_mid("22.1 to 22.0"), 22.05), (num_or_mid("~ 22.1"), 22.1),
        (num_list("0.5; 1.0; 1.5; 2.0; or 3.0"), [0.5, 1.0, 1.5, 2.0, 3.0]),
        (num_list("0.17; 0.21;0.25; 0.3"), [0.17, 0.21, 0.25, 0.3]),
        (strict_num("3   5   approaching 10"), None), (strict_num("0.212"), 0.212),
        (pct("22.2"), 0.222), (pct("21.5 - 21.7"), 0.216),
        (to_kpa(760, "mmHg"), 101.325), (to_kpa("1.25 atm"), 126.656), (to_kpa(1.1, "bar"), 110.0),
        (to_kpa(0, "mmHg"), None), (to_kpa("", "atm"), None),
        (duration_s("14:37:08", "14:48:03"), 655.0), (duration_s("23:59:50", "00:00:10"), 20.0),
        (duration_s("1744", "14:48:03"), None), (duration_s("14.43.58", "14.44.16"), 18.0),
        (fix_autofill("40% CH6"), ("40% CH4", True)), (fix_autofill("~21% O2 with N3"), ("~21% O2 with N2", True)),
        (fix_autofill("100% C2H4"), ("100% C2H4", False)), (fix_autofill("C12H26"), ("C12H26", False)),
        (parse_fuel_bottle("40% CH4 (balance N2) including 2 pyro"), ("CH4", 0.4, "N2")),
        (parse_fuel_bottle("100%C2H4"), ("C2H4", 1.0, None)),
        (parse_fuel_bottle("50% C2H4 with N2"), ("C2H4", 0.5, "N2")),
        (parse_fuel_bottle("40% CH7"), ("CH4", 0.4, None)),
        (dominant_diluent({"N2": 0.09, "CO2": 0.7, "He": 0.0}), ("CO2", 0.7)),
        (dominant_diluent({"N2": 0.0, "He": None}), (None, None)),
        (outcome("Extinction"), "extinction"), (outcome("SE"), "self_extinguished"),
        (outcome("FT"), "flow_terminated"), (outcome("-"), None), (outcome("weird"), None),
        (snake("Burn Time (s)"), "burn_time_s"), (snake("?-g Burn Length"), "ug_burn_length"),
        (snake("Calibrated  initial O2 % by vol "), "calibrated_initial_o2_pct_by_vol"),
        (snake("Test #"), "test_num"),
    ]
    failed = [(i, got, want) for i, (got, want) in enumerate(checks) if got != want]

    ok = TestRow(psi_id="PSI-69", experiment="FLEX", test_id="1", pressure_kpa=101.3,
                 o2_frac=0.21, outcome="extinction", extra={"x": float("nan")})
    assert ok.extra["x"] is None
    for bad in ({"o2_frac": 21.5}, {"outcome": "Extinguished"}, {"psi_id": "69"},
                {"pressure_kpa": 0}, {"diluent": "Ar"}, {"nope": 1}):
        try:
            TestRow(**{"psi_id": "PSI-69", "experiment": "FLEX", "test_id": "1", **bad})
            failed.append(("model accepted", bad, "error"))
        except Exception:
            pass

    for f in failed:
        print("FAIL", f)
    total = len(checks) + 7
    print(f"schema self-test: {total - len(failed)}/{total} passed")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    _selftest()