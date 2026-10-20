"""Indicator identity: canonical form and `spec_hash` (24-internal-schemas §7.4; TS-mirror vectors).

The identity hashes the bar source `tape` (24 §7.4, 23 §6.1), never the price a kernel reads.
"""

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
from candleviewer.orderflow.indicators.identity import (
    BAR_SOURCE,
    canonical_number,
    canonical_value,
)
from candleviewer.orderflow.indicators.types import ParamValue
from tests.unit.orderflow.indicators._golden import (
    FIVE_MINUTES,
    GOLDEN,
    ONE_MINUTE,
    render_spec_hash_vectors,
)

BAR = ONE_MINUTE.spec_hash


def _hash(
    params: Mapping[str, ParamValue], *, indicator: str = "ema", bar_spec_hash: str = BAR
) -> str:
    return compute_spec_hash(indicator, params, bar_spec_hash=bar_spec_hash)


def test_spec_hash_vectors_file_is_current() -> None:
    stored = (GOLDEN / "spec_hash_vectors.json").read_text(encoding="utf-8")
    assert stored == render_spec_hash_vectors()


def test_spec_hash_vectors_hash_their_canonical_json() -> None:
    doc = json.loads((GOLDEN / "spec_hash_vectors.json").read_text(encoding="utf-8"))
    assert doc["indicator_spec_version"] == INDICATOR_SPEC_VERSION
    assert doc["source"] == BAR_SOURCE == "tape"
    for v in doc["vectors"]:
        assert hashlib.sha256(v["canonical_json"].encode()).hexdigest() == v["spec_hash"]
        text = canonical_json(v["indicator"], v["params"], bar_spec_hash=v["bar_spec_hash"])
        assert text == v["canonical_json"]
        assert '"source":"tape"' in text, v["note"]


def test_ema_21_vector_is_the_sha256_of_the_24_7_4_canonical_form() -> None:
    """The form written out by hand from 24 §7.4 (every number a JSON string of its plain
    decimal digits, `source` the bar source `tape`) gives the committed ema(21) vector."""
    by_hand = (
        f'{{"bar_spec_hash":"{BAR}","indicator":"ema","params":{{"n":"21"}},"source":"tape","v":1}}'
    )
    doc = json.loads((GOLDEN / "spec_hash_vectors.json").read_text(encoding="utf-8"))
    vector = next(v for v in doc["vectors"] if v["note"] == "ema(21) on 1m")
    assert vector["canonical_json"] == by_hand
    assert vector["spec_hash"] == hashlib.sha256(by_hand.encode()).hexdigest()


def test_ema_21_int_float_and_decimal_share_one_identity() -> None:
    assert _hash({"n": 21}) == _hash({"n": 21.0}) == _hash({"n": Decimal("21.00")})
    assert _hash({"n": 21}) != _hash({"n": 22})


def test_key_order_does_not_change_the_identity() -> None:
    a = _hash({"depth": 5, "deviation_pct": 0.1}, indicator="zigzag")
    assert a == _hash({"deviation_pct": 0.1, "depth": 5}, indicator="zigzag")


def test_an_omitted_default_is_another_identity() -> None:
    """Callers write defaults out (24 §7.4): `{}` and `{"anchor": "session"}` differ."""
    full = _hash({"anchor": "session"}, indicator="cvd")
    assert _hash({}, indicator="cvd") != full


def test_the_bar_spec_and_the_indicator_are_part_of_the_identity() -> None:
    assert _hash({"n": 21}) != _hash({"n": 21}, bar_spec_hash=FIVE_MINUTES.spec_hash)
    assert _hash({"n": 21}) != _hash({"n": 21}, indicator="sma")


def test_canonical_json_pins_the_version_layout_and_tape_source() -> None:
    text = canonical_json("ema", {"n": 21.0}, bar_spec_hash=BAR)
    assert (INDICATOR_SPEC_VERSION, BAR_SOURCE) == (1, "tape")
    assert text == (
        f'{{"bar_spec_hash":"{BAR}","indicator":"ema","params":{{"n":"21"}},"source":"tape","v":1}}'
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
        (Decimal("1." + "0" * 100), "1"),
        (Decimal("0." + "1" * 40), "0." + "1" * 40),
    ],
)
def test_canonical_number_is_a_plain_decimal_string(
    value: int | float | Decimal, text: str
) -> None:
    assert canonical_number(value) == text


NOT_NUMBERS = (float("nan"), float("inf"), Decimal("NaN"), Decimal("-Infinity"), True)
OUT_OF_RANGE = (Decimal("1e999999999"), Decimal("1e-65"), 1e65, 10**65)
#: Inside the magnitude bounds but with more than 40 significant digits: a huge mantissa would
#: otherwise build a canonical string as long as itself.
TOO_PRECISE = (Decimal("0." + "1" * 41), 10**40 + 1, Decimal("0." + "7" * 100_000))


@pytest.mark.parametrize("value", NOT_NUMBERS + OUT_OF_RANGE + TOO_PRECISE)
def test_canonical_number_refuses_non_finite_huge_tiny_overlong_and_booleans(
    value: float | Decimal,
) -> None:
    with pytest.raises(IndicatorParamError):
        canonical_number(value)


def test_canonical_value_names_the_digit_bound_without_echoing_the_number() -> None:
    with pytest.raises(IndicatorParamError) as err:
        canonical_value("mult", Decimal("0." + "3" * 41))
    assert "40 significant digits" in str(err.value)
    assert "333" not in str(err.value)


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
    ("indicator", "params", "bar_spec_hash"),
    [
        ("EMA", {"n": 21}, BAR),
        ("e" * 33, {"n": 21}, BAR),
        ("ema", {"N": 21}, BAR),
        ("ema", {"n": 21}, BAR.upper()),
        ("ema", {"n": 21}, BAR[:63]),
        ("ema", {"n": float("nan")}, BAR),
    ],
)
def test_identity_fields_are_validated(
    indicator: str, params: dict[str, ParamValue], bar_spec_hash: str
) -> None:
    with pytest.raises(IndicatorParamError):
        _hash(params, indicator=indicator, bar_spec_hash=bar_spec_hash)
    with pytest.raises(IndicatorParamError):
        IndicatorSpec.of(indicator, params, bar_spec_hash=bar_spec_hash)


def test_indicator_spec_is_canonical_on_construction() -> None:
    a = IndicatorSpec.of("ema", {"n": 21}, bar_spec_hash=BAR)
    b = IndicatorSpec.of("ema", {"n": 21.0}, bar_spec_hash=BAR)
    assert a == b
    assert hash(a) == hash(b)
    assert a.params == (("n", "21"),)
    assert a.spec_hash == compute_spec_hash("ema", {"n": 21}, bar_spec_hash=BAR)


@pytest.mark.parametrize(
    ("indicator", "params", "canonical"),
    [
        ("zigzag", {"depth": 5, "deviation_pct": 0.5}, (("depth", "5"), ("deviation_pct", "0.5"))),
        ("bollinger", {"n": 20, "mult": Decimal("2.50")}, (("mult", "2.5"), ("n", "20"))),
        ("psar", {"step": 0.02, "max_step": 0.2}, (("max_step", "0.2"), ("step", "0.02"))),
        ("ema", {"n": 21, "offset": -2.5}, (("n", "21"), ("offset", "-2.5"))),
    ],
)
def test_indicator_spec_hashes_fractional_and_negative_numbers_as_compute_spec_hash_does(
    indicator: str, params: dict[str, ParamValue], canonical: tuple[tuple[str, str], ...]
) -> None:
    """A canonical number is a string such as "0.5"; the spec canonicalises it once, so it
    never meets the enum-token rule (which refuses ".")."""
    spec = IndicatorSpec.of(indicator, params, bar_spec_hash=BAR)
    assert spec.params == canonical
    assert spec.spec_hash == compute_spec_hash(indicator, params, bar_spec_hash=BAR)


def test_indicator_spec_refuses_a_repeated_parameter() -> None:
    with pytest.raises(IndicatorParamError, match="more than once"):
        IndicatorSpec("ema", (("n", 21), ("n", 22)), BAR)
