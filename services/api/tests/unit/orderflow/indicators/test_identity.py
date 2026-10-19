"""Indicator identity: canonical form and `spec_hash` (E13-T02 plan §3.3; TS-mirror vectors)."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from decimal import Decimal
from typing import Any, cast

import pytest

from candleviewer.orderflow.errors import IndicatorParamError
from candleviewer.orderflow.indicators import (
    INDICATOR_SPEC_VERSION,
    IndicatorSpec,
    canonical_json,
    compute_spec_hash,
)
from candleviewer.orderflow.indicators.identity import canonical_number, canonical_value
from candleviewer.orderflow.indicators.types import ParamValue
from tests.unit.orderflow.indicators._golden import (
    FIVE_MINUTES,
    GOLDEN,
    ONE_MINUTE,
    render_spec_hash_vectors,
)

BAR = ONE_MINUTE.spec_hash


def _hash(
    params: Mapping[str, ParamValue],
    *,
    indicator: str = "ema",
    bar_spec_hash: str = BAR,
    source: str | None = "close",
) -> str:
    return compute_spec_hash(indicator, params, bar_spec_hash=bar_spec_hash, source=source)


def test_spec_hash_vectors_file_is_current() -> None:
    stored = (GOLDEN / "spec_hash_vectors.json").read_text(encoding="utf-8")
    assert stored == render_spec_hash_vectors()


def test_spec_hash_vectors_hash_their_canonical_json() -> None:
    doc = json.loads((GOLDEN / "spec_hash_vectors.json").read_text(encoding="utf-8"))
    assert doc["indicator_spec_version"] == INDICATOR_SPEC_VERSION
    for v in doc["vectors"]:
        assert hashlib.sha256(v["canonical_json"].encode()).hexdigest() == v["spec_hash"]
        kw = {"bar_spec_hash": v["bar_spec_hash"], "source": v["source"]}
        assert canonical_json(v["indicator"], v["params"], **kw) == v["canonical_json"]


def test_ema_21_int_float_and_decimal_share_one_identity() -> None:
    assert _hash({"n": 21}) == _hash({"n": 21.0}) == _hash({"n": Decimal("21.00")})
    assert _hash({"n": 21}) != _hash({"n": 22})


def test_key_order_does_not_change_the_identity() -> None:
    a = _hash({"depth": 5, "deviation_pct": 0.1}, indicator="zigzag", source=None)
    assert a == _hash({"deviation_pct": 0.1, "depth": 5}, indicator="zigzag", source=None)


def test_an_omitted_default_is_another_identity() -> None:
    """Callers write defaults out (plan §3.3): `{}` and `{"anchor": "session"}` differ."""
    full = _hash({"anchor": "session"}, indicator="cvd", source=None)
    assert _hash({}, indicator="cvd", source=None) != full


def test_source_and_bar_spec_are_part_of_the_identity() -> None:
    assert _hash({"n": 21}) != _hash({"n": 21}, source="hlc3")
    assert _hash({"n": 21}) != _hash({"n": 21}, bar_spec_hash=FIVE_MINUTES.spec_hash)
    assert _hash({"n": 21}) != _hash({"n": 21}, source=None)


def test_canonical_json_pins_the_version_and_layout() -> None:
    text = canonical_json("ema", {"n": 21.0}, bar_spec_hash=BAR, source="close")
    assert INDICATOR_SPEC_VERSION == 1
    assert text == (
        f'{{"bar_spec_hash":"{BAR}","indicator":"ema","params":{{"n":"21"}},'
        '"source":"close","v":1}'
    )


@pytest.mark.parametrize(
    ("value", "text"),
    [
        (21, "21"),
        (21.0, "21"),
        (Decimal("21.00"), "21"),
        (0.1, "0.1"),
        (1e-07, "0.0000001"),
        (-0.0, "0"),
        (Decimal("-0.000"), "0"),
        (Decimal("1E+3"), "1000"),
        (10**30, "1000000000000000000000000000000"),
        (-2.5, "-2.5"),
    ],
)
def test_canonical_number_is_a_plain_decimal_string(
    value: int | float | Decimal, text: str
) -> None:
    assert canonical_number(value) == text


NOT_NUMBERS = (float("nan"), float("inf"), Decimal("NaN"), Decimal("-Infinity"), True)
OUT_OF_RANGE = (Decimal("1e999999999"), Decimal("1e-65"), 1e65, 10**65)


@pytest.mark.parametrize("value", NOT_NUMBERS + OUT_OF_RANGE)
def test_canonical_number_refuses_non_finite_huge_tiny_and_booleans(value: float | Decimal) -> None:
    with pytest.raises(IndicatorParamError):
        canonical_number(value)


def test_canonical_values_keep_booleans_and_tokens() -> None:
    assert canonical_value("flag", True) is True
    assert canonical_value("anchor", "utc_day") == "utc_day"


@pytest.mark.parametrize("value", ["Session", "a b", "", "x" * 33, ["n"]])
def test_canonical_value_refuses_non_tokens_without_echoing_them(value: object) -> None:
    with pytest.raises(IndicatorParamError) as err:
        canonical_value("anchor", cast(Any, value))
    assert "anchor" in str(err.value)
    assert repr(value) not in str(err.value)


@pytest.mark.parametrize(
    ("indicator", "params", "bar_spec_hash", "source"),
    [
        ("EMA", {"n": 21}, BAR, "close"),
        ("e" * 33, {"n": 21}, BAR, "close"),
        ("ema", {"N": 21}, BAR, "close"),
        ("ema", {"n": 21}, BAR.upper(), "close"),
        ("ema", {"n": 21}, BAR[:63], "close"),
        ("ema", {"n": 21}, BAR, "Close"),
        ("ema", {"n": float("nan")}, BAR, "close"),
    ],
)
def test_identity_fields_are_validated(
    indicator: str, params: dict[str, ParamValue], bar_spec_hash: str, source: str
) -> None:
    with pytest.raises(IndicatorParamError):
        _hash(params, indicator=indicator, bar_spec_hash=bar_spec_hash, source=source)


def test_indicator_spec_is_canonical_on_construction() -> None:
    a = IndicatorSpec.of("ema", {"n": 21}, bar_spec_hash=BAR, source="close")
    b = IndicatorSpec.of("ema", {"n": 21.0}, bar_spec_hash=BAR, source="close")
    assert a == b
    assert hash(a) == hash(b)
    assert a.params == (("n", "21"),)
    assert a.spec_hash == compute_spec_hash("ema", {"n": 21}, bar_spec_hash=BAR, source="close")


def test_indicator_spec_refuses_a_repeated_parameter() -> None:
    with pytest.raises(IndicatorParamError, match="more than once"):
        IndicatorSpec("ema", (("n", 21), ("n", 22)), BAR, "close")
