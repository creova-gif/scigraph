import pytest

from solver.regime import compute_regime_delta, extract_regime_parameters


@pytest.mark.parametrize(
    ("condition", "expected_val"),
    [
        ("buffer at pH 4.5", 4.5),
        ("reaction at ph 7.4", 7.4),
        ("acidic medium PH12", 12.0),
    ],
)
def test_extract_ph_case_insensitive(condition: str, expected_val: float) -> None:
    params = extract_regime_parameters(condition)
    assert len(params) == 1
    param = params[0]
    assert param.dimension == "ph"
    assert param.value == pytest.approx(expected_val)
    assert param.unit == "pH"
    assert param.canonical_value == pytest.approx(expected_val)
    assert param.canonical_unit == "pH"


@pytest.mark.parametrize(
    ("condition", "expected_val", "expected_unit", "expected_canon"),
    [
        ("autoclave at 1 MPa", 1.0, "MPa", 1000.0),
        ("chamber at 500 kPa", 500.0, "kPa", 500.0),
        ("vacuum at 2000 Pa", 2000.0, "Pa", 2.0),
        ("vessel at 1 bar", 1.0, "bar", 100.0),
        ("ambient 1 atm", 1.0, "atm", 101.325),
    ],
)
def test_extract_pressure_normalization(
    condition: str,
    expected_val: float,
    expected_unit: str,
    expected_canon: float,
) -> None:
    params = extract_regime_parameters(condition)
    assert len(params) == 1
    param = params[0]
    assert param.dimension == "pressure"
    assert param.value == pytest.approx(expected_val)
    assert param.unit == expected_unit
    assert param.canonical_value == pytest.approx(expected_canon)
    assert param.canonical_unit == "kPa"


@pytest.mark.parametrize(
    ("condition", "expected_val", "expected_unit", "expected_canon"),
    [
        ("oral 0.5 g/kg", 0.5, "g/kg", 500.0),
        ("oral 2 mg/kg", 2.0, "mg/kg", 2.0),
        ("oral 500 ug/kg", 500.0, "ug/kg", 0.5),
    ],
)
def test_extract_dosage_normalization(
    condition: str,
    expected_val: float,
    expected_unit: str,
    expected_canon: float,
) -> None:
    params = extract_regime_parameters(condition)
    assert len(params) == 1
    param = params[0]
    assert param.dimension == "dosage"
    assert param.value == pytest.approx(expected_val)
    assert param.unit == expected_unit
    assert param.canonical_value == pytest.approx(expected_canon)
    assert param.canonical_unit == "mg/kg"


def test_compute_regime_delta_equivalent_units_return_none() -> None:
    assert compute_regime_delta("at 1 bar", "at 100 kPa") is None
    assert compute_regime_delta("dose 0.5 g/kg", "dose 500 mg/kg") is None


def test_compute_regime_delta_new_dimensions() -> None:
    assert (
        compute_regime_delta("reaction at 1 MPa", "reaction at 500 kPa")
        == "Quantitative pressure delta: -500 kPa (1 MPa -> 500 kPa)"
    )
    assert (
        compute_regime_delta("dose 500 ug/kg", "dose 2 mg/kg")
        == "Quantitative dosage delta: +1.5 mg/kg (500 ug/kg -> 2 mg/kg)"
    )
    assert (
        compute_regime_delta("buffer at pH 4.5", "buffer at pH 7.4")
        == "Quantitative ph delta: +2.9 pH (pH 4.5 -> pH 7.4)"
    )


def test_compute_regime_delta_combined_with_existing_dimensions() -> None:
    delta = compute_regime_delta(
        "at 25 C, pH 4.5, 1 bar",
        "at 37 C, pH 7.4, 200 kPa",
    )
    assert delta == (
        "Quantitative ph delta: +2.9 pH (pH 4.5 -> pH 7.4); "
        "Quantitative pressure delta: +100 kPa (1 bar -> 200 kPa); "
        "Quantitative temperature delta: +12 C (25 C -> 37 C)"
    )


def test_compute_regime_delta_cross_dimension() -> None:
    delta = compute_regime_delta("buffer at pH 7.0", "chamber at 100 kPa")
    assert delta == "Cross-dimension regime shift: ph=pH 7.0 vs pressure=100 kPa"
