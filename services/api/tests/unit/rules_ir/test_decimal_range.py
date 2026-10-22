"""A number outside the decimal range is a typed refusal, never a ``decimal`` signal (#4185).

A ``Decimal`` field (``tolerance``, a limit) reads a numeric string; a ``Decimal`` const or metric
param comes from ``parse_ir_json`` or code. ``dec_str`` normalises under the context, whose
exponents run from ``Etiny`` to ``Emax``: past the top ``normalize`` signalled ``Overflow`` (a 500
on the routes), and below the bottom a number silently read as ``0``. Both are now an
``IrValueError`` naming the path, which the routes answer as ``422 rule_ir_invalid``; a number at
either end of the range hashes as it did. Every number is built from the context's own limits.
"""

from __future__ import annotations

import copy
import decimal
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from candleviewer.rules.ir import Rule, canonical, canonicalize, ir_hash, parse_ir_json

FIXTURES = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "rule_ir"
_BASE: dict[str, Any] = json.loads((FIXTURES / "form_simple_0.json").read_text(encoding="utf-8"))
CTX = decimal.getcontext()
OVER_EMAX = CTX.Emax + 1  # one past the largest exponent the context holds
UNDER_ETINY = CTX.Etiny() - 1  # one below the smallest
REASON = "Number is outside the range a rule can hold"
PATH = {
    "tolerance": ("conditions", "tolerance"),
    "limit": ("limits", "max_notional_per_fire"),
    "const": ("conditions", "right", "const"),
    "metric param": ("conditions", "left", "params", "k"),
}


def _num(exp: int, *, sign: int = 0, digits: tuple[int, ...] = (1,)) -> Decimal:
    return Decimal((sign, digits, exp))  # exact: no context rounds it


OUT = {  # a number the context cannot hold
    "above": _num(OVER_EMAX), "negative above": _num(OVER_EMAX, sign=1),
    "rounds above": _num(CTX.Emax - 28, digits=(9,) * 29),  # 29 digits: rounding carries past Emax
    "below": _num(UNDER_ETINY), "negative below": _num(UNDER_ETINY, sign=1),
}  # fmt: skip
EDGE = {"largest": _num(CTX.Emax), "smallest": _num(CTX.Etiny())}
#: ``ir_hash(_doc("tolerance", EDGE[x]))`` on the base commit: an edge number hashes alike.
EDGE_HASH = {
    "largest": "32944fd85ed2467e09fc9d325c66a1e5b83d192901db1aa81be6fc9dfafbca6c",
    "smallest": "dfb03bc05b02fe52c0ded59b34b452bea6eb47146068a0eb413277c5279ccbad",
}


def _doc(where: str, value: Any) -> dict[str, Any]:
    """``form_simple_0`` with ``value`` at ``where``."""
    doc = copy.deepcopy(_BASE)
    node = doc["conditions"]
    if where == "tolerance":
        node["tolerance"] = value
    elif where == "limit":
        doc["limits"] = {"max_notional_per_fire": value}
    elif where == "const":
        node["right"]["const"] = value
    else:
        node["left"]["params"] = {"k": value}
    return doc


@pytest.mark.parametrize("label", OUT)
@pytest.mark.parametrize("where", PATH)
def test_canonicalize_number_outside_the_decimal_range_is_a_refusal_naming_its_path(
    where: str, label: str
) -> None:
    rule = Rule.model_validate(_doc(where, OUT[label]))  # the models take it: the hash refuses
    for hashing in (canonicalize, ir_hash):
        with pytest.raises(canonical.IrValueError) as caught:
            hashing(rule)
        assert (caught.value.loc, caught.value.reason) == (PATH[where], REASON)


@pytest.mark.parametrize("label", OUT)
def test_condition_hash_number_outside_the_decimal_range_is_a_refusal_naming_its_path(
    label: str,
) -> None:
    rule = Rule.model_validate(_doc("tolerance", OUT[label]))
    with pytest.raises(canonical.IrValueError) as caught:
        canonical.condition_hash(rule.model_dump())  # the alert view of the same condition
    assert (caught.value.loc, caught.value.reason) == (PATH["tolerance"], REASON)


@pytest.mark.parametrize("label", OUT)
def test_dec_str_number_outside_the_decimal_range_is_a_refusal_with_no_path_yet(
    label: str,
) -> None:
    with pytest.raises(canonical.IrValueError) as caught:
        canonical.dec_str(OUT[label])
    assert (caught.value.loc, caught.value.reason) == ((), REASON)


def test_dec_str_signalling_nan_is_a_refusal_not_an_invalid_operation() -> None:
    with pytest.raises(canonical.IrValueError) as caught:
        canonical.dec_str(Decimal("sNaN"))
    assert (caught.value.loc, caught.value.reason) == ((), "Input should be a finite number")


@pytest.mark.parametrize("edge", EDGE)
def test_ir_hash_number_at_either_end_of_the_range_hashes_to_its_pinned_value(edge: str) -> None:
    assert ir_hash(Rule.model_validate(_doc("tolerance", EDGE[edge]))) == EDGE_HASH[edge]


@pytest.mark.parametrize("edge", EDGE)
@pytest.mark.parametrize("where", PATH)
def test_canonicalize_number_at_either_end_of_the_range_is_not_refused(
    where: str, edge: str
) -> None:
    assert canonicalize(Rule.model_validate(_doc(where, EDGE[edge])))


@pytest.mark.parametrize(
    ("exponent", "loc"), [(OVER_EMAX, PATH["tolerance"]), (decimal.MAX_EMAX + 1, ())]
)
def test_parse_ir_json_number_outside_the_decimal_range_is_a_refusal(
    exponent: int, loc: tuple[str, ...]
) -> None:
    """Up to ``MAX_EMAX`` ``Decimal`` reads the literal exactly and the hash refuses it, naming
    the path; past that the parse itself is the refusal (it was an ``InvalidOperation``)."""
    text = json.dumps(_doc("tolerance", "__slot__")).replace('"__slot__"', f"1e{exponent}")
    with pytest.raises(canonical.IrValueError) as caught:
        ir_hash(parse_ir_json(text))
    assert (caught.value.loc, caught.value.reason) == (loc, REASON)


_NUMBER = st.builds(
    _num,
    st.integers(CTX.Etiny() - 3, CTX.Emax + 3),
    sign=st.integers(0, 1),
    digits=st.lists(st.integers(0, 9), min_size=1, max_size=30).map(tuple),
)


@settings(max_examples=200, deadline=None, database=None)
@given(_NUMBER, st.sampled_from(["tolerance", "limit", "metric param"]))
def test_canonicalize_any_drawn_number_hashes_or_is_refused_never_a_decimal_signal(
    number: Decimal, where: str
) -> None:
    """Exponents drawn around both ends of the range: a number strictly inside it always hashes."""
    try:
        canonicalize(Rule.model_validate(_doc(where, number)))
    except canonical.IrValueError as exc:
        assert exc.reason == REASON and not CTX.Etiny() <= number.adjusted() < CTX.Emax, exc
