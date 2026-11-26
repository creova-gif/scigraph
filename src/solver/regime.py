import re
from collections.abc import Callable

from pydantic import BaseModel, ConfigDict


class RegimeParameter(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    dimension: str
    value: float
    unit: str
    canonical_value: float
    canonical_unit: str
    raw_token: str


_TEMP_CONTEXT_PATTERN = re.compile(
    r"(?:(?<=at\s)|(?<=to\s))(?P<val>-?\d+(?:\.\d+)?)\s*(?P<unit>C|K)\b"
    r"|(?P<val2>-?\d+(?:\.\d+)?)\s*(?P<unit2>degrees\s+Celsius|K)\b"
    r"|(?P<val3>-?\d+(?:\.\d+)?)\s*(?P<unit3>C)(?=\s+(?:oxidative|steam|damp|larval|thermal|heatwave|regeneration|annealing)\b)"
)
_HUMIDITY_PATTERN = re.compile(r"(?P<val>\d+(?:\.\d+)?)\s*%\s*(?:relative\s+humidity|RH)?")
_CURRENT_DENSITY_PATTERN = re.compile(r"(?P<val>\d+(?:\.\d+)?)\s*(?P<unit>mA/cm2)\b")
_CRATE_PATTERN = re.compile(
    r"(?P<val>\d+(?:\.\d+)?)\s*(?P<unit>C)(?:\s+(?:charge|discharge|rate|cycling))?\b"
)
_MOLARITY_PATTERN = re.compile(r"(?P<val>\d+(?:\.\d+)?)\s*(?P<unit>mM|M)\b")
_MASS_CONC_PATTERN = re.compile(r"(?P<val>\d+(?:\.\d+)?)\s*(?P<unit>ng/mL)\b")
_FREQ_PATTERN = re.compile(r"(?P<val>\d+(?:\.\d+)?)\s*(?P<unit>Hz)\b")


def _normalize_temperature(value: float, unit: str) -> tuple[float, str]:
    if unit == "K":
        return (value - 273.15, "C")
    return (value, "C")


def _normalize_molarity(value: float, unit: str) -> tuple[float, str]:
    if unit == "mM":
        return (value / 1000.0, "M")
    return (value, "M")


_PATTERN_SPECS: tuple[
    tuple[str, re.Pattern[str], str, Callable[[float, str], tuple[float, str]] | None],
    ...,
] = (
    ("humidity", _HUMIDITY_PATTERN, "%", None),
    ("current_density", _CURRENT_DENSITY_PATTERN, "mA/cm2", None),
    ("c_rate", _CRATE_PATTERN, "C", None),
    ("molarity", _MOLARITY_PATTERN, "M", _normalize_molarity),
    ("mass_concentration", _MASS_CONC_PATTERN, "ng/mL", None),
    ("frequency", _FREQ_PATTERN, "Hz", None),
)


def extract_regime_parameters(condition: str) -> tuple[RegimeParameter, ...]:
    params: list[RegimeParameter] = []
    occupied_spans: list[tuple[int, int]] = []

    for match in _TEMP_CONTEXT_PATTERN.finditer(condition):
        val_raw = match.group("val") or match.group("val2") or match.group("val3")
        unit_raw = match.group("unit") or match.group("unit2") or match.group("unit3")
        val = float(val_raw)
        canon_val, canon_unit = _normalize_temperature(val, unit_raw)
        params.append(
            RegimeParameter(
                dimension="temperature",
                value=val,
                unit=unit_raw,
                canonical_value=canon_val,
                canonical_unit=canon_unit,
                raw_token=match.group(0).strip(),
            )
        )
        occupied_spans.append(match.span())

    for dimension, pattern, default_unit, normalizer in _PATTERN_SPECS:
        for match in pattern.finditer(condition):
            start, end = match.span()
            if any(not (end <= s or start >= e) for s, e in occupied_spans):
                continue
            val = float(match.group("val"))
            unit = (
                match.group("unit")
                if "unit" in pattern.groupindex and match.group("unit")
                else default_unit
            )
            canon_val, canon_unit = normalizer(val, unit) if normalizer else (val, default_unit)
            params.append(
                RegimeParameter(
                    dimension=dimension,
                    value=val,
                    unit=unit,
                    canonical_value=canon_val,
                    canonical_unit=canon_unit,
                    raw_token=match.group(0).strip(),
                )
            )
            occupied_spans.append((start, end))

    return tuple(params)


def compute_regime_delta(cond_a: str, cond_b: str) -> str | None:
    params_a = extract_regime_parameters(cond_a)
    params_b = extract_regime_parameters(cond_b)
    if not params_a and not params_b:
        return None

    map_a: dict[str, RegimeParameter] = {}
    for p in params_a:
        map_a.setdefault(p.dimension, p)
    map_b: dict[str, RegimeParameter] = {}
    for p in params_b:
        map_b.setdefault(p.dimension, p)

    shared_deltas: list[str] = []
    for dim in sorted(set(map_a) & set(map_b)):
        pa = map_a[dim]
        pb = map_b[dim]
        diff = pb.canonical_value - pa.canonical_value
        if abs(diff) > 1e-9:
            shared_deltas.append(
                f"Quantitative {dim} delta: {diff:+.4g} {pa.canonical_unit} "
                f"({pa.raw_token} -> {pb.raw_token})"
            )

    if shared_deltas:
        return "; ".join(shared_deltas)

    if params_a and params_b and (set(map_a) != set(map_b)):
        a_summary = ", ".join(f"{p.dimension}={p.raw_token}" for p in params_a)
        b_summary = ", ".join(f"{p.dimension}={p.raw_token}" for p in params_b)
        return f"Cross-dimension regime shift: {a_summary} vs {b_summary}"

    return None
