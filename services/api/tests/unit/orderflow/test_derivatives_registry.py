"""E24-T04 Registry completeness: the ten 24 §7.2 Derivatives descriptors are registered with
their unit, params and estimated flag, and the registry agrees with the engine's read path."""

from __future__ import annotations

import pytest

from candleviewer.orderflow.derivatives import DESCRIPTORS
from candleviewer.rules.vocabulary.build import build_vocabulary
from candleviewer.rules.vocabulary.metrics import default_registry

#: 24 §7.2 Derivatives: name -> (unit, params with defaults, enum values).
EXPECTED: dict[str, tuple[str, dict[str, str], tuple[str, ...]]] = {
    "open_interest": ("qty", {}, ()),
    "open_interest_value": ("notional", {}, ()),
    "open_interest_delta": ("qty", {}, ()),
    "oi_price_quadrant": (
        "enum",
        {},
        ("long_buildup", "short_covering", "short_buildup", "long_unwind"),
    ),
    "funding_rate": ("pct", {}, ()),
    "funding_annualized": ("pct", {}, ()),
    "time_to_funding_ms": ("ms", {}, ()),
    "basis": ("price", {"source": "last"}, ()),
    "premium_pct": ("pct", {"source": "last"}, ()),
    "liquidation_notional": ("notional", {"side": "both"}, ()),
}


def test_registry_has_all_ten_derivatives_descriptors() -> None:
    reg = default_registry()
    missing = [n for n in EXPECTED if reg.get(n) is None]
    assert not missing, f"derivatives descriptors missing from the registry: {missing}"
    assert set(DESCRIPTORS) == set(EXPECTED)


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_descriptor_unit_params_enum_and_exact_confidence(name: str) -> None:
    d = default_registry().get(name)
    assert d is not None
    unit, params, enums = EXPECTED[name]
    assert (d.unit, d.params, d.enum_values) == (unit, params, enums)
    assert d.confidence == "exact"  # estimated: false is a property of the descriptor


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_registry_param_defaults_are_the_engine_defaults(name: str) -> None:
    d = default_registry().get(name)
    assert d is not None
    assert d.params == {k: v[0] for k, v in DESCRIPTORS[name].items()}


_PER_BAR = ("open_interest_delta", "oi_price_quadrant", "liquidation_notional")


@pytest.mark.parametrize("name", _PER_BAR)
def test_per_bar_descriptors_are_bar_scoped_with_their_none_case(name: str) -> None:
    d = default_registry().get(name)
    assert d is not None and d.cadence == "on_bar_close" and d.nullable_when


def test_vocabulary_reports_derivatives_as_not_estimated() -> None:
    by = {s["id"]: s for s in build_vocabulary(default_registry())["signals"]}
    for name in EXPECTED:
        assert by[name]["estimated"] is False
    assert by["oi_price_quadrant"]["enum_values"] == list(EXPECTED["oi_price_quadrant"][2])
