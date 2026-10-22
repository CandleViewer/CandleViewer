"""A JSON number in a rule's ``params`` hashes as its exact decimal, never as a bool (#4132).

``MetricRef.params`` values are typed like ``Literal_`` (``bool | int | Decimal | str``, and
``None`` as before) with strict members, so a JSON ``1.0`` stays a number (``Literal_``'s lax union
reads it as ``true``, #951).
The canonicaliser keeps a ``float -> Decimal(float.__repr__(x))`` arm for the untyped places
(``Action.params``) and refuses a non-finite number with a typed ``IrValueError``: the routes
answer ``422 rule_ir_invalid``, never a 500. A bad metric param is one clear refusal, and a
``Decimal`` param's JSON form is the hash's own digits, so a stored value re-hashes alike.
"""

from __future__ import annotations

import copy
import json
import pickle
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from candleviewer.rules.ir import (
    MetricRef,
    Rule,
    canonical,
    canonicalize,
    ir_hash,
    models,
    parse_ir_json,
)

FIXTURES = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "rule_ir"
_BASE: dict[str, Any] = json.loads((FIXTURES / "form_simple_0.json").read_text(encoding="utf-8"))
#: ``ir_hash(_doc(x))``, computed on the base commit (a number through its ``Decimal`` form, the
#: only form that hashed there): a JSON value must land on exactly these values.
HALF = "ca1d7339f3a1554d6620a685d1872ea2a431f05aa2e4099b55fabb3697232e9e"  # 0.5 = 0.50 = 5E-1
ONE = "503b645c9d48b1a32eb7e7a87abcfbd85471512cbf49a7f37532938244900847"  # 1 and 1.0: "1"
TRUE = "0520de66e155eb688ee163d99f72be44458e1854e5dafe1f4ab2b8d3bfe92468"  # JSON true
NULL = "3019dc201c2e965a58aefdf8ef3a87474ff8ad36bbc239f262fe25e3b1d67f46"  # JSON null, valid before
_SLOT = "__slot__"
_REF = json.dumps({"metric": "rsi", "params": {"k": _SLOT}})


def _doc(threshold: Any, **action: Any) -> dict[str, Any]:
    """``form_simple_0`` with ``threshold`` in its metric operand's params (``action``: extra
    params on its action)."""
    doc = copy.deepcopy(_BASE)
    doc["conditions"]["left"] = {"metric": "rsi", "params": {"period": 14, "threshold": threshold}}
    doc["actions"][0]["params"] = {"channel": "ui", "severity": "info", "template": "x", **action}
    return doc


def _text(spelling: str) -> str:
    """``_doc`` as JSON text with the threshold spelled exactly ``spelling``."""
    return json.dumps(_doc(_SLOT)).replace(f'"{_SLOT}"', spelling)


def _param(spelling: str) -> Any:
    """The ``k`` param of a metric ref parsed from JSON text that spells it ``spelling``."""
    raw = json.loads(_REF.replace(f'"{_SLOT}"', spelling))
    return MetricRef.model_validate(raw).params["k"]


@pytest.mark.parametrize(
    ("spelling", "expected"),
    [("true", True), ("false", False), ("1", 1), ("0", 0), ('"x"', "x"), ('"0.5"', "0.5"),
     ("null", None)],
)  # fmt: skip
def test_metric_param_json_scalar_or_null_keeps_its_type(spelling: str, expected: Any) -> None:
    value = _param(spelling)
    assert value == expected and type(value) is type(expected)


@pytest.mark.parametrize("spelling", ["1.0", "0.0", "-0.0", "0.5", "0.50", "5E-1", "1e300"])
def test_metric_param_json_float_literal_is_decimal_never_bool(spelling: str) -> None:
    value = _param(spelling)
    assert type(value) is Decimal and value == Decimal(spelling)


_FINITE = ("finite_number", "Input should be a finite number")
_PLAIN = ("plain_value", "Input should be a plain value (true/false, a number, text or null)")


@pytest.mark.parametrize(
    ("spelling", "error"),
    [('{"a": 1}', _PLAIN), ("[1]", _PLAIN), ("NaN", _FINITE), ("Infinity", _FINITE),
     ("-Infinity", _FINITE)],
)  # fmt: skip
def test_metric_param_unsupported_or_non_finite_value_is_one_clear_refusal(
    spelling: str, error: tuple[str, str]
) -> None:
    with pytest.raises(ValidationError) as caught:
        _param(spelling)
    found = [(e["type"], e["msg"], e["loc"]) for e in caught.value.errors()]
    assert found == [(*error, ("params", "k"))]


def test_ir_hash_fractional_metric_param_matches_its_decimal_form() -> None:
    """Scenario: a rule whose metric operand params hold 0.5 hashes deterministically."""
    assert ir_hash(_doc(0.5)) == ir_hash(_doc(Decimal("0.5"))) == HALF


@pytest.mark.parametrize("spelling", ["0.5", "0.50", "5E-1", "0.500000"])
def test_ir_hash_equal_decimal_spellings_hash_alike(spelling: str) -> None:
    text = _text(spelling)
    assert ir_hash(json.loads(text)) == ir_hash(parse_ir_json(text)) == HALF


@pytest.mark.parametrize("spelling", ["1", "1.0", "1.00", "1E0"])
def test_ir_hash_int_one_and_number_one_hash_alike_as_dec_str(spelling: str) -> None:
    text = _text(spelling)
    assert ir_hash(json.loads(text)) == ir_hash(parse_ir_json(text)) == ONE
    assert b'"threshold":"1"' in canonicalize(json.loads(text))


def test_ir_hash_json_true_stays_a_bool_distinct_from_one() -> None:
    assert ir_hash(json.loads(_text("true"))) == TRUE != ONE
    assert b'"threshold":true' in canonicalize(json.loads(_text("true")))


def test_ir_hash_null_metric_param_keeps_its_base_hash_and_its_stored_form_reloads() -> None:
    """A null param was valid before typing: same hash, and the jsonb form of it loads again."""
    rule = Rule.model_validate(json.loads(_text("null")))
    stored = Rule.model_validate(json.loads(rule.model_dump_json()))
    assert ir_hash(rule) == ir_hash(stored) == NULL
    assert b'"threshold":null' in canonicalize(rule)


@pytest.mark.parametrize(
    ("spelling", "stored"),
    [("0.5", "0.5"), ("3.0", "3"), ("1e-7", "0.0000001"), ("1E+21", "1000000000000000000000"),
     ("-0.0", "0"), ("2.50", "2.5")],
)  # fmt: skip
def test_ir_hash_number_param_json_form_is_its_hashed_decimal_so_it_reloads_alike(
    spelling: str, stored: str
) -> None:
    """The stored (jsonb) and returned form holds the hash's own digits: it re-hashes alike."""
    rule = Rule.model_validate(json.loads(_text(spelling)))
    dumped = json.loads(rule.model_dump_json())
    assert dumped["conditions"]["left"]["params"]["threshold"] == stored
    assert ir_hash(Rule.model_validate(dumped)) == ir_hash(rule)


@settings(max_examples=300, deadline=None, database=None)
@given(st.decimals(allow_nan=False, allow_infinity=False))
def test_plain_decimal_is_dec_str_or_the_numbers_own_text_when_it_refuses(d: Decimal) -> None:
    """``models._plain_decimal`` writes the digits ``canonical.dec_str`` hashes; a number the hash
    refuses (a form wider than its bound) keeps its own text."""
    try:
        want = canonical.dec_str(d)
    except canonical.IrValueError:
        want = str(d)
    assert models._plain_decimal(d) == want


def test_canonicalize_fractional_action_param_hashes_as_its_decimal() -> None:
    assert canonicalize(_doc(1, weight=0.1)) == canonicalize(_doc(1, weight=Decimal("0.1")))
    assert b'"weight":"0.1"' in canonicalize(_doc(1, weight=0.1))


@pytest.mark.parametrize(
    ("value", "text"),
    [(0.1, "0.1"), (1.0, "1"), (-0.0, "0"), (1e16, "10000000000000000"), (2.5e-7, "0.00000025")],
)
def test_normalise_float_is_its_repr_decimal(value: float, text: str) -> None:
    assert canonical._normalise(value) == text


class _Spelled(float):
    """A float subclass with its own repr, as numpy's ``float64`` has."""

    def __repr__(self) -> str:
        return f"_Spelled({float.__repr__(self)})"


def test_normalise_float_subclass_hashes_by_floats_own_repr() -> None:
    assert canonical._normalise(_Spelled(0.1)) == "0.1"


_DECIMALS = st.decimals(Decimal("-1e15"), Decimal("1e15"), allow_nan=False, places=12)
#: Floats and integers whose plain form is far inside the width bound (a wider one is a refusal).
_FLOATS = st.one_of(st.floats(1e-30, 1e30), st.floats(-1e30, -1e-30), st.just(0.0))
_NUMBERS = st.one_of(st.integers(-(10**30), 10**30), _FLOATS, _DECIMALS)


@settings(max_examples=300, deadline=None, database=None)
@given(_NUMBERS)
def test_canonicalize_finite_number_in_any_params_within_the_bound_never_raises(
    x: int | float | Decimal,
) -> None:
    """Metric and action params: any finite JSON number inside the width bound hashes, as its exact
    decimal."""
    exact = Decimal(repr(x)) if isinstance(x, float) else x
    doc = _doc(x, weight=x)
    assert canonicalize(doc) == canonicalize(_doc(exact, weight=exact))
    canonical.condition_hash(Rule.model_validate(doc).model_dump())  # the alert view hashes too


_NON_FINITE = [
    float("nan"), float("inf"), float("-inf"), Decimal("NaN"), Decimal("sNaN"), Decimal("-Infinity")
]  # fmt: skip


@pytest.mark.parametrize("value", _NON_FINITE, ids=repr)
def test_canonicalize_non_finite_action_param_is_a_typed_refusal_not_type_error(
    value: float | Decimal,
) -> None:
    rule = Rule.model_validate(_doc(1, weight=value))
    with pytest.raises(canonical.IrValueError) as caught:
        canonicalize(rule)
    assert not isinstance(caught.value, TypeError)
    assert caught.value.loc == ("actions", 0, "params", "weight")
    assert caught.value.reason == "Input should be a finite number"


def test_normalise_unsupported_type_is_a_typed_type_error() -> None:
    with pytest.raises(canonical.IrTypeError) as caught:
        canonical._normalise({"actions": [{"params": {"tags": {"a", "b"}}}]})
    assert issubclass(caught.type, canonical.IrValueError) and issubclass(caught.type, TypeError)
    assert caught.value.loc == ("actions", 0, "params", "tags")


@pytest.mark.parametrize(
    ("bad", "text"),
    [(float("nan"), "Input should be a finite number at /actions/0/params/w/1"),
     ({1}, "unsupported type in IR: set at /actions/0/params/w/1")],
)  # fmt: skip
def test_ir_value_error_survives_pickle_copy_and_deepcopy(bad: object, text: str) -> None:
    with pytest.raises(canonical.IrValueError) as caught:
        canonical._normalise({"actions": [{"params": {"w": [0, bad]}}]})
    err = caught.value
    assert str(err) == text
    unpickled = pickle.loads(pickle.dumps(err))  # noqa: S301 - this test's own bytes (#4132)
    for twin in (unpickled, copy.copy(err), copy.deepcopy(err)):
        assert type(twin) is type(err)
        assert (twin.loc, twin.reason, str(twin)) == (err.loc, err.reason, text)


def test_ir_value_error_built_directly_survives_pickle_copy_and_deepcopy() -> None:
    err = canonical.IrValueError(("a", 0), "r")  # never through at(): pins the constructor
    unpickled = pickle.loads(pickle.dumps(err))  # noqa: S301 - this test's own bytes (#4132)
    for twin in (unpickled, copy.copy(err), copy.deepcopy(err)):
        assert type(twin) is canonical.IrValueError
        assert (twin.loc, twin.reason, str(twin)) == (("a", 0), "r", "r at /a/0")
