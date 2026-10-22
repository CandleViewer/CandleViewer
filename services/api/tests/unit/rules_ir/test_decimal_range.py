"""A Decimal whose canonical form would exceed 64 characters is a typed refusal (#4185).

A ``Decimal`` field (``tolerance``, a limit) reads a numeric string; a ``Decimal`` const or metric
param comes from ``parse_ir_json`` or code. ``dec_str`` refuses a number whose plain form (sign,
digits and decimal point) would exceed 64 characters with an ``IrValueError`` naming the path, which
the routes answer as ``422 rule_ir_invalid``. Every number outside the decimal context's range is
one, and the width is worked out from the leading exponent and digit count, before the form is
built. A number of 64 characters or fewer hashes as it always did. Every number below is built from
the bound or from the context's own limits.
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

from candleviewer.rules.ir import Rule, canonical, canonicalize, ir_hash, models, parse_ir_json

FIXTURES = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "rule_ir"
_BASE: dict[str, Any] = json.loads((FIXTURES / "form_simple_0.json").read_text(encoding="utf-8"))
WIDTH = 64  # the bound: characters of sign, digits and decimal point
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


def _at(width: int, *, sign: int, digits: int, small: bool) -> Decimal:
    """A number whose plain form is ``width`` characters: ``digits`` significant digits (none zero),
    a minus sign if ``sign``, and a magnitude of at least one (below one if ``small``)."""
    coefficient = tuple(i % 9 + 1 for i in range(digits))
    return _num(sign + 2 - width if small else width - sign - digits, sign=sign, digits=coefficient)


OUT = {  # a number whose plain form is far wider than the bound
    "above": _num(OVER_EMAX), "negative above": _num(OVER_EMAX, sign=1),
    "rounds above": _num(CTX.Emax - 28, digits=(9,) * 29),  # 29 digits: rounding carries past Emax
    "top of the range": _num(CTX.Emax), "bottom of the range": _num(CTX.Etiny()),
    "below": _num(UNDER_ETINY), "negative below": _num(UNDER_ETINY, sign=1),
    "rounds up from below": _num(UNDER_ETINY, digits=(6,)),
    "rounds up from far below": _num(CTX.Etiny() - 20, digits=(9,) * 20),
    "rounds up past the bound": _num(WIDTH - 29, digits=(9,) * 29),  # lead 63, carries to 1e64
}  # fmt: skip
#: ``ir_hash(_doc("tolerance", x))`` on the parent commit: 1e30 and 1e-30 written with 28
#: significant digits, and a 30-digit value, which rounds to 28 as it always did.
PINNED = {
    "1e30 with 28 digits": (
        Decimal("1.000000000000000000000000000E+30"),
        "250b54bd0ed6668a6b9adc100aeaccb4f104e3edbc933a6bc9b120b15c9957e3",
    ),
    "1e-30 with 28 digits": (
        Decimal("1.000000000000000000000000000E-30"),
        "dd82cc6998d0f03dfae6916daf24389fe42e269a550eedc00df8ea145d226859",
    ),
    "30 digits": (
        Decimal("1.23456789012345678901234567891E+30"),
        "a8463e1838c57b9b577e730413215a8bffe82fdfe8318b5d22bb20c136855251",
    ),
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
def test_canonicalize_number_wider_than_the_bound_is_a_refusal_naming_its_path(
    where: str, label: str
) -> None:
    rule = Rule.model_validate(_doc(where, OUT[label]))  # the models take it: the hash refuses
    for hashing in (canonicalize, ir_hash):
        with pytest.raises(canonical.IrValueError) as caught:
            hashing(rule)
        assert (caught.value.loc, caught.value.reason) == (PATH[where], REASON)


@pytest.mark.parametrize("label", OUT)
def test_condition_hash_number_wider_than_the_bound_is_a_refusal_naming_its_path(
    label: str,
) -> None:
    rule = Rule.model_validate(_doc("tolerance", OUT[label]))
    with pytest.raises(canonical.IrValueError) as caught:
        canonical.condition_hash(rule.model_dump())  # the alert view of the same condition
    assert (caught.value.loc, caught.value.reason) == (PATH["tolerance"], REASON)


@pytest.mark.parametrize("label", OUT)
def test_dec_str_number_wider_than_the_bound_is_a_refusal_with_no_path_yet(label: str) -> None:
    with pytest.raises(canonical.IrValueError) as caught:
        canonical.dec_str(OUT[label])
    assert (caught.value.loc, caught.value.reason) == ((), REASON)


def test_dec_str_signalling_nan_is_a_refusal_not_an_invalid_operation() -> None:
    with pytest.raises(canonical.IrValueError) as caught:
        canonical.dec_str(Decimal("sNaN"))
    assert (caught.value.loc, caught.value.reason) == ((), "Input should be a finite number")


@pytest.mark.parametrize("small", [False, True], ids=["large", "small"])
@pytest.mark.parametrize("sign", [0, 1], ids=["positive", "negative"])
@pytest.mark.parametrize("digits", [1, 28])
def test_dec_str_form_of_exactly_64_characters_passes_and_65_is_refused(
    small: bool, sign: int, digits: int
) -> None:
    fits, over = (_at(w, sign=sign, digits=digits, small=small) for w in (WIDTH, WIDTH + 1))
    assert [len(format(n, "f")) for n in (fits, over)] == [WIDTH, WIDTH + 1]  # built to the width
    assert canonical.dec_str(fits) == format(fits, "f")
    with pytest.raises(canonical.IrValueError) as caught:
        canonical.dec_str(over)
    assert (caught.value.loc, caught.value.reason) == ((), REASON)


def test_dec_str_value_that_rounds_up_into_the_bound_is_measured_after_it_rounds() -> None:
    """29 nines at a leading exponent of -63 carry up to 1e-62, a form of exactly 64 characters,
    though the value as written lies further out than any form that fits."""
    rounds_up = _num(1 - WIDTH - 28, digits=(9,) * 29)
    assert canonical.dec_str(rounds_up) == "0." + "0" * (WIDTH - 3) + "1"


@pytest.mark.parametrize("where", PATH)
def test_canonicalize_form_of_exactly_64_characters_passes_and_65_is_refused_in_every_place(
    where: str,
) -> None:
    fits, over = (_at(w, sign=1, digits=28, small=True) for w in (WIDTH, WIDTH + 1))
    assert format(fits, "f").encode() in canonicalize(Rule.model_validate(_doc(where, fits)))
    with pytest.raises(canonical.IrValueError) as caught:
        canonicalize(Rule.model_validate(_doc(where, over)))
    assert (caught.value.loc, caught.value.reason) == (PATH[where], REASON)


@pytest.mark.parametrize("label", PINNED)
def test_ir_hash_number_of_28_significant_digits_within_the_bound_hashes_as_before(
    label: str,
) -> None:
    number, pinned = PINNED[label]
    assert ir_hash(Rule.model_validate(_doc("tolerance", number))) == pinned


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


def _fits(number: Decimal) -> bool:
    """The oracle, by Python's own formatting: the plain form is at most ``WIDTH`` characters. A
    number this far out is far wider, and is not formatted."""
    if number == 0:
        return True
    return abs(number.adjusted()) <= 4 * WIDTH and len(format(number.normalize(), "f")) <= WIDTH


_SIGN, _DIGITS = st.integers(0, 1), st.lists(st.integers(0, 9), min_size=1, max_size=31).map(tuple)
_NINES = st.builds(  # a run of nines, then up to two digits: the rounding carries
    lambda run, tail: (9,) * run + tail,
    st.integers(25, 31),
    st.lists(st.integers(0, 9), max_size=2).map(tuple),
)


def _lead(lead: int, sign: int, digits: tuple[int, ...]) -> Decimal:
    return _num(lead - len(digits) + 1, sign=sign, digits=digits)


#: Four windows: plain forms of 61 to 67 characters, leading exponents 3 either side of the bound
#: (where rounding can carry across it), 3 either side of both ends of the context's range, and
#: the wide middle between them.
NUMBER = st.one_of(
    st.builds(
        _at,
        st.integers(WIDTH - 3, WIDTH + 3),
        sign=_SIGN,
        digits=st.integers(1, 28),
        small=st.booleans(),
    ),
    st.builds(
        _lead,
        st.one_of(st.integers(-WIDTH - 3, -WIDTH + 3), st.integers(WIDTH - 3, WIDTH + 3)),
        _SIGN,
        st.one_of(_DIGITS, _NINES),
    ),
    st.builds(
        _num,
        st.one_of(
            st.integers(CTX.Etiny() - 3, CTX.Etiny() + 3), st.integers(CTX.Emax - 3, CTX.Emax + 3)
        ),
        sign=_SIGN,
        digits=_DIGITS,
    ),
    st.builds(_num, st.integers(CTX.Etiny(), CTX.Emax), sign=_SIGN, digits=_DIGITS),
)


@settings(max_examples=300, deadline=None, database=None)
@given(NUMBER, st.sampled_from(["tolerance", "limit", "metric param"]))
def test_any_drawn_number_hashes_and_writes_its_json_form_exactly_when_its_form_fits_the_bound(
    number: Decimal, where: str
) -> None:
    """An oracle on each side: a number hashes when its form fits, and is refused only when not. A
    number param's JSON form is the hash's digits when they fit, and its own text when they do not:
    nothing wide is built."""
    fits = _fits(number)
    try:
        canonicalize(Rule.model_validate(_doc(where, number)))
    except canonical.IrValueError as exc:
        assert exc.reason == REASON and not fits, number
    else:
        assert fits, number
    assert models._plain_decimal(number) == (canonical.dec_str(number) if fits else str(number))
