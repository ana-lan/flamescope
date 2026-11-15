"""Mappers for the per-test experimental tables (Phase 2.3).

Each function maps one raw row (normalized headers) to TestRow kwargs.
psi_id, experiment, raw row, source file/row, duplicate flags are added by tables.run_spec.
"""
from __future__ import annotations

import re

from ignitiq.schema import (
    clean, dominant_diluent, duration_s, num, num_or_mid, outcome, pct, strict_num, to_kpa,
)
from ignitiq.tables import Spec, first, fuel_name


def _drop_none(d: dict) -> dict:
    return {k: v for k, v in d.items() if v is not None}


def _atm(v):
    x = strict_num(v)
    return to_kpa(x, "atm") if x is not None else None


def _bar(v):
    x = strict_num(v)
    return to_kpa(x, "bar") if x is not None else None


_IGNITE_FAIL = re.compile(r"fail\w* to ignite|not ignited|no ignition|did not ignite", re.I)


# ---------------------------------------------------------------- droplets

def flex(r: dict, i: int) -> dict:
    p_raw = strict_num(r["Ambient pressure; mmHg"])
    o2 = strict_num(r["O initial ambient composition; mole fraction"])
    gases = {
        "N2": strict_num(r["N initial ambient composition; mole fraction"]),
        "CO2": strict_num(r["CO initial ambient composition; mole fraction"]),
        "He": strict_num(r["He initial ambient composition; mole fraction"]),
    }
    dil, dil_frac = dominant_diluent(gases)
    extra = _drop_none({
        "identifier": clean(r["FLEX Identifier"]),
        "date": clean(r["Test Date"]),
        "n2_frac": gases["N2"], "co2_frac": gases["CO2"], "he_frac": gases["He"],
        "droplet_d0_mm": strict_num(r["Droplet initial diameter; mm"]),
        "extinction_d_mm": strict_num(r["Visible flame extinction diameter; mm"]),
        "burning_rate_k_mm2_s": strict_num(r["Burning rate; mm"]),
    })
    if p_raw == 0:
        extra["invalid_pressure"] = True
    return dict(
        test_id=r["FLEX Test #"], fuel=fuel_name(r["Fuel"]),
        pressure_kpa=to_kpa(p_raw, "mmHg") if p_raw else None,
        o2_frac=o2, diluent=dil, diluent_frac=dil_frac,
        outcome=outcome(r["Test end"]), burn_time_s=strict_num(r["Burn time; s"]),
        extra=extra,
    )


_CFI_BLEND = re.compile(r"\[(\.\d+)\]/\[(\.\d+)\]\s*c12h26/iso-dodecane")


def cfi(r: dict, i: int) -> dict:
    fuel = fuel_name(first(r, "Fuel"))
    m = _CFI_BLEND.fullmatch(fuel or "")
    if m:
        a, b = round(float(m.group(1)) * 100), round(float(m.group(2)) * 100)
        fuel = f"n-dodecane/iso-dodecane {a}/{b}"
    o2 = strict_num(r["Oxygen"])
    gases = {"N2": strict_num(r["Nitrogen"]), "He": strict_num(r["Helium"])}
    dil, dil_frac = dominant_diluent(gases)
    return dict(
        test_id=r["Flex Number"], fuel=fuel, pressure_kpa=to_kpa(r["Pressure"]),
        o2_frac=o2, diluent=dil, diluent_frac=dil_frac,
        extra=_drop_none({
            "date": clean(r["Test Date"]), "cir_id": clean(first(r, "CIR")),
            "n2_frac": gases["N2"], "he_frac": gases["He"],
            "fiber": clean(r.get("Fiber")),
        }),
    )


# ---------------------------------------------------------------- ACME gas jets

def _ramped(r: dict) -> bool:
    return any(str(v).upper().startswith("RAMP") for v in r.values())


def flame_design_normal(r: dict, i: int) -> dict:
    extra = _drop_none({
        "flame_type": "normal", "day": strict_num(r["Day"]),
        "fuel_frac": strict_num(r["Xfuel"]),
        "mfuel_mg_s": strict_num(r["mfuel (mg/s)"]), "mn2_mg_s": strict_num(r["mN2 (mg/s)"]),
        "mtot_mg_s": strict_num(r["mtot (mg/s)"]),
        "o2_frac_final": strict_num(r["XO2 (final)"]),
        "pressure_final_kpa": _atm(r["pfinal (atm)"]), "pressure_mean_kpa": _atm(r["pmean (atm)"]),
        "zst": strict_num(r["mean Zst"]), "tad_k": strict_num(r["Tad (K)"]),
    })
    if _ramped(r):
        extra["ramped"] = True
    return dict(
        test_id=r["Test"], fuel=fuel_name(r["Fuel"]),
        pressure_kpa=_atm(r["pinit (atm)"]), o2_frac=strict_num(r["XO2 (init)"]),
        extra=extra,
    )


def flame_design_inverse(r: dict, i: int) -> dict:
    # Inverse flame: O2 flows from the burner into an ethylene/N2 ambient.
    return dict(
        test_id=r["Test"], fuel="ethylene", pressure_kpa=_atm(r["pinit (atm)"]), o2_frac=None,
        extra=_drop_none({
            "flame_type": "inverse", "day": strict_num(r["Day"]),
            "oxidizer_o2_frac": strict_num(r["XO2"]),
            "ambient_fuel_frac": strict_num(r["XC2H4 initial"]),
            "ambient_fuel_frac_final": strict_num(r["XC2H4 final"]),
            "mo2_mg_s": strict_num(r["mO2 (mg/s)"]), "mn2_mg_s": strict_num(r["mN2 (mg/s)"]),
            "mtot_mg_s": strict_num(r["mtot (mg/s)"]),
            "pressure_final_kpa": _atm(r["pfinal (atm)"]), "pressure_mean_kpa": _atm(r["pmean (atm)"]),
            "zst": strict_num(r["mean Zst"]), "tad_k": strict_num(r["Tad (K)"]),
        }),
    )


def _cfig_outcome(r: dict) -> str | None:
    o = outcome(first(r, "Self-ext or flow term", "Self -ext or flow term"))
    if o is None and _IGNITE_FAIL.search(r.get("Comments") or ""):
        o = "no_ignition"
    return o


def _cfig_common(r: dict) -> dict:
    hot = clean(r.get("Hot ignition"))
    return _drop_none({
        "day": strict_num(r["Day"]), "tfp": clean(r.get("TFP")),
        "hot_ignition": hot.lower() if hot else None,
        "tad_k": strict_num(r["Tad (K)"]), "zst": strict_num(r["Zst"]),
        "peak_burner_t_c": strict_num(first(r, "Peak burner T (C )", "Peak burner Temp (C)")),
        "color": clean(r.get("Color")), "comments": clean(r.get("Comments")),
    })


def cfig_normal(r: dict, i: int) -> dict:
    extra = _cfig_common(r) | _drop_none({
        "flame_type": "normal",
        "o2_frac_final": strict_num(r["XO2 after test"]),
        "fuel_frac": strict_num(r["Xf"]), "mhc_mg_s": strict_num(r["mHC (mg/s)"]),
        "cool_flame": clean(r.get("Cool flame?")),
    })
    return dict(
        test_id=r["Test"], fuel=fuel_name(r["Fuel"]),
        pressure_kpa=_bar(r["approx p (bar)"]), o2_frac=strict_num(r["XO2 before test"]),
        outcome=_cfig_outcome(r), burn_time_s=strict_num(r["burn time (sec)"]),
        extra=extra,
    )


def cfig_inverse(r: dict, i: int) -> dict:
    extra = _cfig_common(r) | _drop_none({
        "flame_type": "inverse",
        "oxidizer_o2_frac": strict_num(r["XO2"]),
        "ambient_fuel_frac": strict_num(r["Xf before test"]),
        "ambient_fuel_frac_final": strict_num(r["Xf after test"]),
        "hc_burnrate_mg_s": strict_num(r["HC burnrate (mg/s)"]),
        "o2_flow_mg_s": strict_num(r["O2 flow rate (mg/s)"]),
    })
    return dict(
        test_id=r["Test"], fuel=fuel_name(r["Fuel"]),
        pressure_kpa=_bar(r["approx p (bar)"]), o2_frac=None,
        outcome=_cfig_outcome(r), burn_time_s=strict_num(r["burn time (sec)"]),
        extra=extra,
    )


# ---------------------------------------------------------------- solids

def bass(r: dict, i: int) -> dict:
    return dict(
        test_id=clean(r["As Run Test #"]) or f"row{i + 1}",
        material=clean(r["Fuel Sample Material"]),
        extra=_drop_none({"date": clean(r["Date"]), "sample_num": clean(r["Sample #"]),
                          "planned_test_num": clean(r["Test #"])}),
    )


def _pct_strict(v):
    x = strict_num(v)
    return round(x / 100, 6) if x is not None else None


def bass2(r: dict, i: int) -> dict:
    return dict(
        test_id=r["Test #"], material=clean(r["Fuel Sample Material"]),
        o2_frac=_pct_strict(r["Calibrated initial O2 % by vol"]),
        extra=_drop_none({
            "pi": clean(r["PI"]), "date": clean(r["Date"]),
            "o2_frac_final": _pct_strict(r["Calibrated final O2 % by vol"]),
            "co2_frac": _pct_strict(r["Initial CO2 % by vol"]),
            "co2_frac_final": _pct_strict(r["Final CO2 % by vol"]),
            "co_ppm": strict_num(r["Initial CO (ppm)"]),
            "co_ppm_final": strict_num(r["Final CO (ppm)"]),
            "flow_restrictor": strict_num(r["Flow restrictor"]),
        }),
    )


def saffire1(r: dict, i: int) -> dict:
    mat = clean(r["Material"])
    flow_vis = bool(mat and mat.lower().startswith("pre-test flow"))
    extra = _drop_none({
        "thickness_cm": strict_num(r["Sample Thickness (cm)"]),
        "length_cm": strict_num(r["Sample Length (cm)"]),
        "width_cm": strict_num(r["Sample Width (cm)"]),
        "ignition_power_w": strict_num(r["Ignition Power (W)"]),
        "ignition_time_s": strict_num(r["Ignition Time (s)"]),
        "flow_direction": (clean(r["Flow Direction"]) or "").lower() or None,
    })
    if flow_vis:
        extra["record_type"] = "flow_visualization"
        extra["note"] = mat
    return dict(
        test_id=r["Sample Number"], material=None if flow_vis else mat,
        o2_frac=pct(r["Percent O2"]), flow_cm_s=strict_num(r["Air Flow (cm/s)"]),
        burn_time_s=strict_num(r["Burn Time (s)"]), extra=extra,
    )


def _unit_num(v, unit: str):
    """Number only if the value carries the expected unit: ('2.1 mm/s', 'mm/s') -> 2.1."""
    s = clean(v)
    return num(s) if s and unit in s else None


def _thickness_mm(v) -> tuple[float | None, bool]:
    """Strict: one number + mm|cm. '1 cm' -> 10.0, '037 mm' -> 0.37 (typo), 'See Fig. 5' -> None."""
    s = clean(v)
    m = re.fullmatch(r"(\d*\.?\d+)\s*(mm|cm)", s or "")
    if not m:
        return None, False
    digits, unit = m.group(1), m.group(2)
    typo = bool(re.fullmatch(r"0\d+", digits))           # '037' means 0.37
    x = float("0." + digits[1:]) if typo else float(digits)
    return (x * 10 if unit == "cm" else x), typo


def saffire2(r: dict, i: int) -> dict:
    thick, typo = _thickness_mm(r["Samle Thickness"])
    extra = {"thickness_typo_fixed": True} if typo else {}
    ug_spread = first(r, "?-g Spread Length", "µ-g Spread Length", "μ-g Spread Length")
    ug_burn = first(r, "?-g Burn Length", "µ-g Burn Length", "μ-g Burn Length")
    extra |= _drop_none({
        "thickness_mm": thick,
        "length_raw": clean(r["Sample Length"]),
        "width_cm": num(r["Sample Width (cm)"]),
        "ignition_power_w": num(r["Ignition Power (W)"]),
        "ignition_time_s": num(r["Ignition Time (s)"]),
        "flow_direction": (clean(r["Flow Direction"]) or "").lower() or None,
        "ug_burn_length_cm": _unit_num(ug_burn, "cm"),
        "one_g_burn_length_raw": clean(r["1-g Burn Length"]),
        "one_g_spread_rate_mm_s": _unit_num(r["1-g Spread Rate"], "mm/s"),
    })
    return dict(
        test_id=r["Sample Number"], material=clean(r["Material"]),
        o2_frac=pct(r["Percent O2 (Note 1)"]), flow_cm_s=num(r["Air Flow (cm/s)"]),
        burn_time_s=num(r["Burn Time (s)"]),
        spread_rate_mm_s=_unit_num(ug_spread, "mm/s"),
        extra=extra,
    )


def saffire3(r: dict, i: int) -> dict:
    return dict(
        test_id=r["Sample Number"], material=clean(r["Material"]),
        flow_cm_s=num(r["Air Flow"]),
        extra=_drop_none({
            "thickness_cm": num(r["Sample Thickness"]),
            "length_cm": num(r["Sample Length"]), "width_cm": num(r["Sample Width"]),
            "flow_direction": (clean(r["Direction"]) or "").lower() or None,
        }),
    )


# ---------------------------------------------------------------- smoke

def spice(r: dict, i: int) -> dict:
    flow = strict_num(r["Air Rate (cm/s)"])
    extra = _drop_none({
        "gmt_day": strict_num(r["GMT date"]),
        "nozzle_mm": strict_num(r["Nozzle (mm)"]),
        "fuel_rate_sccm": strict_num(r["Fuel Rate (sccm)"]),
        "fuel_rate_mg_s": strict_num(r["Fuel Rate (mg/s)"]),
        "hc_fuel_rate_mg_s": strict_num(r["HC Fuel Rate (mg/s)"]),
    })
    if flow is not None and flow < 0:
        extra["negative_flow"] = True
    return dict(
        test_id=f"{clean(r['GMT date'])}-{clean(r['GMT ignition'])}",
        fuel=fuel_name(r["Fuel"]), flow_cm_s=flow,
        burn_time_s=duration_s(r["GMT ignition"], r["GMT Flame Off"]),
        extra=extra,
    )


def same_r(r: dict, i: int) -> dict:
    return dict(
        test_id=r["SAME Test #"], material=clean(r["Sample Type"]),
        flow_cm_s=strict_num(r["Inlet velocity (cm/s)"]),
        extra=_drop_none({
            "description": clean(r["Description"]), "date": clean(r["Date"]),
            "rt_r0": strict_num(r["Rt/R0"]),
            "duration_s": strict_num(r["Duration (sec)"]),
            "primary_aging_s": strict_num(r["Primary aging time (sec)"]),
            "primary_mixing_s": strict_num(r["Primary mixing time (sec)"]),
            "net_aging_s": strict_num(r["Net aging time (sec)"]),
        }),
    )


SPECS = [
    Spec("FLEX", "PSI-69", "FLEX", flex),
    Spec("CFI", "PSI-39", "CFI", cfi),
    Spec("Flame Design", "PSI-10", "Flame Design_Normal Flame", flame_design_normal),
    Spec("Flame Design", "PSI-10", "Flame Design_Inverse Flame", flame_design_inverse),
    Spec("CFI-G", "PSI-159", "CFI-G_Normal Flames", cfig_normal),
    Spec("CFI-G", "PSI-159", "CFI-G_Inverse Flames", cfig_inverse),
    Spec("BASS", "PSI-26", "BASS", bass),
    Spec("BASS-II", "PSI-25", "BASS-II", bass2),
    Spec("SAFFIRE-I", "PSI-98", "SAFFIRE-1", saffire1),
    Spec("SAFFIRE-II", "PSI-99", "SAFFIRE-2", saffire2),
    Spec("SAFFIRE-III", "PSI-100", "SAFFIRE-3", saffire3),
    Spec("SPICE", "PSI-107", "Spice", spice),
    Spec("SAME-R", "PSI-101", "SAME-R", same_r),
]