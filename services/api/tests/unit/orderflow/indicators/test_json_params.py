"""`catalogue.json_params` (E13-T03): `validate_params`' output as the JSON a preset stores."""

from __future__ import annotations

from decimal import Decimal

from candleviewer.orderflow.indicators.catalogue import (
    default_catalogue,
    json_params,
    validate_params,
)


def test_json_params_keeps_integers_and_enums_and_writes_fractions_as_floats() -> None:
    assert json_params({"n": 14, "anchor": "session", "mult": Decimal("2.5")}) == {
        "n": 14,
        "anchor": "session",
        "mult": 2.5,
    }


def test_json_params_writes_an_integral_fraction_as_an_integer() -> None:
    got = json_params({"mult": Decimal("3.0")})
    assert got == {"mult": 3} and type(got["mult"]) is int


def test_json_params_round_trips_through_validate_params_exactly() -> None:
    """Every default of every catalogue indicator, and a step value that binary64 division
    would refuse (0.3 for a step of 0.1), reads back to the same canonical parameters."""
    for definition in default_catalogue():
        canonical = validate_params(definition, {})
        assert validate_params(definition, json_params(canonical)) == canonical, definition.id
    bollinger = default_catalogue().get("bollinger")
    assert bollinger is not None
    canonical = validate_params(bollinger, {"mult": 0.3})
    assert validate_params(bollinger, json_params(canonical)) == canonical
