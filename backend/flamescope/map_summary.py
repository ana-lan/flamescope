"""Mappers for the summary and test-day tables (Phase 2.4).

These rows are not single tests. Core columns get a value only when the row has exactly
one; lists and ranges go to `extra`. Every row is tagged extra.row_kind = "summary".
"""
from __future__ import annotations

import re
from datetime import date, timedelta

from flamescope.schema import clean, fix_autofill, num, num_list, parse_fuel_bottle, strict_num, to_kpa
from flamescope.tables import Spec, first, fuel_name

ATM_KPA = 101.325


def _drop_none(d: dict) -> dict:
    return {k: v for k, v in d.items() if v is not None}


def yyddd(v) -> str | None:
    """'17319' -> '2017-11-15' (year 20YY, day-of-year DDD). Anything else -> None."""
    s = clean(v)
    if not s or not re.fullmatch(r"\d{5}", s):
        return None
    yy, ddd = int(s[:2]), int(s[2:])
    if not 1 <= ddd <= 366:
        return None
    return (date(2000 + yy, 1, 1) + timedelta(days=ddd - 1)).isoformat()


def _fuel(v) -> tuple[str | None, dict]:
    """Fuel bottle text -> (common fuel name, extra fields incl. fuel_frac, fuel_diluent, autofill flag)."""
    _, fixed = fix_autofill(v)
    formula, frac, dil = parse_fuel_bottle(v)
    extra = _drop_none({"fuel_frac": frac, "fuel_diluent": dil})
    if fixed:
        extra["autofill_fixed"] = True
    return fuel_name(formula), extra


def _summary(extra: dict) -> dict:
    return {"row_kind": "summary", **_drop_none(extra)}


# ---------------------------------------------------------------- FLEX-2

def flex2(r: dict, i: int) -> dict:
    name = clean(r["Sample (Fuel Type)"]) or ""
    fuel = re.sub(r"\s*\(pure\)\s*$", "", name, flags=re.I).lower() or None
    p_atm = num_list(r["Ambient Pressure (atm)"])
    return dict(
        test_id=fuel or f"row{i + 1}", fuel=fuel,
        extra=_summary({
            "sample_label": name,
            "o2_frac_values": num_list(r["Oxygen Mole Fraction"]) or None,
            "pressure_kpa_values": [round(p * ATM_KPA, 3) for p in p_atm] or None,
            "flow_cm_s_range": num_list(r["Flow Velocity (cm/s)"]) or None,
            "droplet_d0_mm_range": num_list(r["Initial Droplet Diameter (mm)"]) or None,
            "ambient_mixture": clean(r["Ambient Gas Mixture"]),
            "ambient_temp_c": strict_num(r["Ambient Temperature (C)"]),
        }),
    )


# ---------------------------------------------------------------- SLICE

def slice_(r: dict, i: int) -> dict:
    raw_date = clean(r["Test Date"]) or ""
    m = re.match(r"(\d{4})-([A-Za-z]{3})-(\d{2})", raw_date)
    day = m.group(0) if m else None
    note = raw_date[len(day):].strip() if day else raw_date
    fuel, fx = _fuel(r["Fuel Type"])
    return dict(
        test_id=day or f"row{i + 1}", fuel=fuel,
        extra=_summary({**fx, "date": day, "note": note or None,
                        "fuel_text": clean(r["Fuel Type"])}),
    )


# ---------------------------------------------------------------- SAME

def same(r: dict, i: int) -> dict:
    mat_raw = clean(first(r, "Sample Material")) or ""
    material = mat_raw.split(":")[0].strip() or None
    m = re.search(r"same conditions as\s*([\d\s-]+)", mat_raw, re.I)
    aging_min = strict_num(r["Aging Duration (minutes)"])
    return dict(
        test_id=r["Sample #"], material=material,
        flow_cm_s=strict_num(r["Air Flow (cm/s)"]),
        extra=_summary({
            "same_as": m.group(1).strip() if m else None,
            "weight_loss_mg_min": strict_num(r["Weight loss rate (mg/min)"]),
            "aging_s": aging_min * 60 if aging_min is not None else None,
        }),
    )


# ---------------------------------------------------------------- ACME test-day tables

def bre(r: dict, i: int) -> dict:
    fuel, fx = _fuel(r["Fuel Bottle"])
    vals = num_list(r["Oxygen Conc (percent)"])
    excel_fix = any(x > 100 for x in vals)               # '3400%' is 34 shown as a % cell
    o2s = [round((x / 100 if x > 100 else x) / 100, 6) for x in vals]
    return dict(
        test_id=f"{clean(r['Year'])}-{clean(r['Month'])}-{clean(r['Date'])}",
        fuel=fuel,
        o2_frac=o2s[0] if len(o2s) == 1 else None,
        extra=_summary({
            **fx, "o2_frac_values": o2s or None,
            "excel_percent_fixed": True if excel_fix else None,
            "burner_mm": strict_num(r["Burner Size (mm)"]),
            "flames_ignited": strict_num(r["Flames Ignited"]),
            "notes": clean(r.get("Notes")),
        }),
    )


def cld(r: dict, i: int) -> dict:
    fuel, fx = _fuel(r["Fuel Bottle"])
    conc = [round(x / 100, 6) for x in num_list(r["Fuel conc. Range"])]
    return dict(
        test_id=r["Test Day"], fuel=fuel,
        extra=_summary({
            **fx, "date": yyddd(r["Test Day"]), "test_type": clean(r["Test Type"]),
            "fuel_frac_range": conc or None,
            "fuel_mfc": strict_num(r["Fuel MFC"]), "n2_mfc": strict_num(r["N2 MFC"]),
            "flames_ignited": strict_num(r["Flames ignited"]),
            "notes": clean(r.get("Notes")),
        }),
    )


_EFIELD_FILL = ["Test Type", "Test Day", "Year", "Month", "Date", "Mesh Polarity", "Fuel Bottle"]


def efield_prep(rows: list[dict]) -> list[dict]:
    """Forward-fill identity columns into continuation rows (blank Test Day). Counts are not filled."""
    out, prev = [], None
    for r in rows:
        r = dict(r)
        cont = not clean(r.get("Test Day")) and prev is not None
        if cont:
            for c in _EFIELD_FILL:
                if not clean(r.get(c)):
                    r[c] = prev.get(c, "")
        r["_continuation"] = "yes" if cont else ""
        out.append(r)
        if not cont:
            prev = r
    return out


def efield(r: dict, i: int) -> dict:
    fuel, fx = _fuel(r["Fuel Bottle"])
    conc = num(r["Fuel Conc"])
    extra = {**fx, "fuel_frac": round(conc / 100, 6) if conc is not None else fx.get("fuel_frac"),
             "date": yyddd(r["Test Day"]), "test_type": clean(r["Test Type"]),
             "mesh_polarity": (clean(r["Mesh Polarity"]) or "").lower() or None,
             "flames_ignited": strict_num(r["Flames Ignited"]),
             "notes": clean(r.get("Notes"))}
    if r.get("_continuation") == "yes":
        extra["continuation"] = True
    return dict(test_id=r["Test Day"], fuel=fuel, extra=_summary(extra))


def sflame(r: dict, i: int) -> dict:
    atmos, fixed_a = fix_autofill(r["Atmosphere*"])
    m = re.search(r"([\d.]+)\s*%\s*O2\s*with\s*(N2|He|CO2)", atmos or "")
    o2 = round(float(m.group(1)) / 100, 6) if m else None
    fuel, fx = _fuel(r["Fuel Bottle"])
    extra = {**fx, "date": yyddd(r["Test Day*"]), "test_type": clean(r["Test Type"]),
             "atmosphere": atmos, "pressure_approx": True,
             "flames_ignited": strict_num(r["Flames Ignited*"]),
             "notes": clean(r.get("Notes"))}
    if fixed_a:
        extra["autofill_fixed"] = True
    return dict(
        test_id=r["Test Day*"], fuel=fuel,
        pressure_kpa=to_kpa(1, "atm"), o2_frac=o2,
        diluent=m.group(2) if m else None,
        diluent_frac=round(1 - o2, 6) if o2 is not None else None,
        extra=_summary(extra),
    )


SPECS = [
    Spec("FLEX-2", "PSI-68", "Flex2", flex2),
    Spec("SLICE", "PSI-106", "Slice", slice_),
    Spec("SAME", "PSI-102", "SAME", same),
    Spec("ACME BRE", "PSI-20", "ACME BRE", bre),
    Spec("ACME CLD", "PSI-21", "CLD Flame", cld),
    Spec("ACME E-Field", "PSI-22", "ACME E-FIELD Flames", efield, prep=efield_prep),
    Spec("ACME s-Flame", "PSI-23", "ACME s-Flame", sflame),
]
