"""#3469: an option value of the wrong JSON type is `invalid_options` on `sub` and on `ctl`.

`Opt.check` runs one `_CHECKS` entry per option kind. The `enum` entry tested membership
(`v in o.choices`) before the type of the value, and a list or an object is unhashable, so it
raised `TypeError`; the gateway answers a raise by closing the connection `internal_error` (1011),
where §10.2 says `invalid_options`. The options are read from the registry, so a new option, or a
new kind of check, is covered when it is added.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from candleviewer.ws.permissions import ConnectionAuthz, Subscription, handle_ctl
from candleviewer.ws.topics import _CHECKS, FAMILIES, UNIVERSAL, Opt, TopicError, validate_options
from tests.unit.ws.test_subscriptions import A, _ctl, _mgr, _services, _sub

#: Every option a family takes, its own and the universal ones (§5.1, §6.1), with the family.
DECLARED: list[tuple[str, str, Opt]] = [
    (f.family, name, opt)
    for f in FAMILIES.values()
    for name, opt in {**UNIVERSAL, **f.options}.items()
]
#: The kinds of check no registered option uses: none today. A new kind that no option uses is
#: named here, and tested by its own rows.
UNUSED_KINDS: frozenset[str] = frozenset()
#: What the JSON path decodes (`json.loads`) and MessagePack refuses: NaN and the infinities. They
#: are floats that no option takes, and `nan` is not even equal to itself.
NON_FINITE = (float("nan"), float("inf"), float("-inf"))
#: A number or a string of the wrong kind, per kind: every value is refused by every option of it.
#: `True` is `1` to a membership test, and `1` is a `depth`.
WRONG_SCALARS: dict[str, tuple[Any, ...]] = {
    "int": ("5", 1.5, True, *NON_FINITE),
    "number": ("5", True, *NON_FINITE),
    "bool": (0, 1, "true", *NON_FINITE),
    "enum": (True, 7, "7", 1.5, *NON_FINITE),
    "decimal": (5, 1.5, True, *NON_FINITE),
    "str": (5, True, *NON_FINITE),
    "uuids": ("x", 5, True, *NON_FINITE),
    "symbols": ("BTCUSDT", 5, True, *NON_FINITE),
    "strings": ("x", 5, True, *NON_FINITE),
}
_LISTS = frozenset({"uuids", "symbols", "strings"})


def _distinct() -> list[tuple[str, str, Opt]]:
    """One row per distinct check: an `Opt` under one name checks alike in every family."""
    seen: dict[tuple[str, Opt], str] = {}
    for family, name, opt in DECLARED:
        seen.setdefault((name, opt), family)
    return [(family, name, opt) for (name, opt), family in seen.items()]


def _wrong_values(opt: Opt) -> list[Any]:
    """What `opt` must refuse: a list and an object (nested too), `None`, and a number or a string
    of the wrong kind. A list option takes a list, so for it the list holds the wrong items. An
    enum also refuses the digits of each numeric choice: `"50"` is no `depth`, though `50` is."""
    if opt.kind in _LISTS:
        structured: list[Any] = [
            {},
            {"a": []},
            [[]],
            [{}],
            [None],
            *([[]] if opt.min_items else []),
        ]
    else:
        structured = [[], {}, [[]], {"a": []}]
    digits = [str(c) for c in sorted(opt.choices, key=repr) if isinstance(c, int)]
    return [*structured, None, *WRONG_SCALARS.get(opt.kind, ()), *digits]


def _label(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"))


OPTIONS = _distinct()
ENUMS = [(family, name, opt) for family, name, opt in OPTIONS if opt.kind == "enum"]
WRONG = [
    pytest.param(family, name, value, id=f"{family}.{name}={_label(value)}")
    for family, name, opt in OPTIONS
    for value in _wrong_values(opt)
]
CHOICES = [
    pytest.param(family, name, choice, id=f"{family}.{name}={_label(choice)}")
    for family, name, opt in ENUMS
    for choice in sorted(opt.choices, key=str)
]
NUMERIC_CHOICES = [p for p in CHOICES if isinstance(p.values[2], int)]


def test_every_kind_of_check_has_an_option_in_the_registry_and_wrong_values() -> None:
    assert set(_CHECKS) - {opt.kind for _, _, opt in DECLARED} == UNUSED_KINDS
    assert set(_CHECKS) - UNUSED_KINDS == set(WRONG_SCALARS)


@pytest.mark.parametrize(("family", "name", "value"), WRONG)
def test_validate_options_a_value_of_the_wrong_type_is_out_of_range(
    family: str, name: str, value: Any
) -> None:
    with pytest.raises(TopicError) as exc:
        validate_options(FAMILIES[family], {name: value})
    err = exc.value
    assert (err.code, err.field) == ("invalid_options", name)
    assert err.message == f"Option '{name}' is out of range."


@pytest.mark.parametrize(("family", "name", "choice"), CHOICES)
def test_validate_options_every_choice_of_an_enum_is_still_accepted(
    family: str, name: str, choice: Any
) -> None:
    out = validate_options(FAMILIES[family], {name: choice})
    assert out == {name: choice} and type(out[name]) is type(choice)


@pytest.mark.parametrize(("family", "name", "choice"), NUMERIC_CHOICES)
def test_validate_options_a_float_equal_to_a_numeric_choice_stays_accepted(
    family: str, name: str, choice: int
) -> None:
    """`{"depth": 50.0}` is valid today, as in JSON Schema, where `enum` compares numbers by
    value (§13.5): the type check lets a float through, and it is returned as it was sent."""
    out = validate_options(FAMILIES[family], {name: float(choice)})
    assert out == {name: choice} and type(out[name]) is float


def test_validate_options_a_bool_is_no_enum_value_though_true_equals_a_choice() -> None:
    depth = FAMILIES["heatmap"].options["depth"]
    assert 1 in depth.choices and True in depth.choices  # the premise: a bool is a member
    with pytest.raises(TopicError) as exc:
        validate_options(FAMILIES["heatmap"], {"depth": True})
    assert (exc.value.code, exc.value.field) == ("invalid_options", "depth")


#: Any JSON value a frame can carry, nested. `floats()` holds NaN and the infinities, which the JSON
#: path decodes (`json.loads`); MessagePack refuses them.
JSON = st.recursive(
    st.none() | st.booleans() | st.integers() | st.floats() | st.text(max_size=8),
    lambda inner: (
        st.lists(inner, max_size=4) | st.dictionaries(st.text(max_size=4), inner, max_size=4)
    ),
    max_leaves=12,
)
#: Every choice of every enum, in a stable order: a frozenset iterates its strings by the hash seed,
#: so the examples a derandomized Hypothesis draws would differ from one process to the next.
ENUM_CHOICES = [c for _, _, o in ENUMS for c in sorted(o.choices, key=repr)]
#: Values on the edge of an enum: each choice, its float twin and its digits, and what equals one
#: (`True`, `1.0`).
EDGE = st.sampled_from(
    [
        *ENUM_CHOICES,
        *(float(c) for c in ENUM_CHOICES if isinstance(c, int)),
        *(str(c) for c in ENUM_CHOICES if isinstance(c, int)),
        *(True, False, 0, 1, None, ""),
    ]
)


@settings(max_examples=400, deadline=None)
@given(option=st.sampled_from(DECLARED), value=JSON)
def test_validate_options_any_json_value_is_a_valid_value_or_a_topic_error(
    option: tuple[str, str, Opt], value: Any
) -> None:
    family, name, _ = option
    try:
        out = validate_options(FAMILIES[family], {name: value})
    except TopicError as err:  # any other exception fails the test
        assert (err.code, err.field) == ("invalid_options", name)
    else:
        assert set(out) == {name}


@settings(max_examples=400, deadline=None)
@given(option=st.sampled_from(ENUMS), value=EDGE | JSON)
def test_enum_check_keeps_every_answer_the_old_check_gave(
    option: tuple[str, str, Opt], value: Any
) -> None:
    """No value accepted before is refused now, and no value refused before is accepted: the old
    check, `not isinstance(v, bool) and v in o.choices`, judged every value that has a hash. The
    one it could not judge, a list or an object, it raised on; that is refused now."""
    _, _, opt = option
    try:
        before = not isinstance(value, bool) and value in opt.choices
    except TypeError:
        before = False
    assert _CHECKS["enum"](opt, value) == before


# -- sub -------------------------------------------------------------------------------------------


def test_sub_an_option_of_the_wrong_type_refuses_that_entry_alone() -> None:
    conn = ConnectionAuthz(_mgr(A), _services())
    res = _sub(
        conn,
        "book.BTCUSDT.50",
        {"ch": "heatmap.BTCUSDT", "opts": {"depth": []}},
        {"ch": "trades.BTCUSDT", "opts": {"encoding": {}}},
        "ticker.BTCUSDT",
    )
    assert [r["ok"] for r in res] == [True, False, False, True]
    errors = [(r["error"]["code"], r["error"]["field"]) for r in res[1:3]]
    assert errors == [("invalid_options", "depth"), ("invalid_options", "encoding")]
    assert conn.topics == {"book.BTCUSDT.50", "ticker.BTCUSDT"}  # nothing is held for the other two


# -- ctl -------------------------------------------------------------------------------------------


def _state(sub: Subscription) -> tuple[Any, ...]:
    return (dict(sub.opts), dict(sub.effective), sub.snapshot_pending, sub.pending_reason, sub.seq)


def _subscribed(ch: str) -> tuple[ConnectionAuthz, Subscription]:
    conn = ConnectionAuthz(_mgr(A), _services())
    _sub(conn, ch)
    sub = conn.find(ch)
    assert sub is not None
    sub.snapshot_pending = False  # a re-snapshot a refusal wrongly caused would show as pending
    return conn, sub


def _refused(ch: str, key: str, value: Any) -> TopicError:
    """`ctl` of `{key: value}` on a subscription to `ch`: refused, and nothing is changed."""
    conn, sub = _subscribed(ch)
    before = _state(sub)
    with pytest.raises(TopicError) as exc:  # a `TypeError` would fail the test, not satisfy this
        conn.ctl(ch, {key: value})
    err = _ctl(conn, ch, {key: value})  # the gateway's hook: an `err` frame, no raise
    assert (err["t"], err["id"], err["p"]["code"], err["p"]["field"]) == (
        ("err", "c-9", "invalid_options", key)
    )
    assert _state(sub) == before
    return exc.value


@pytest.mark.parametrize("value", [[], {}], ids=["list", "object"])
@pytest.mark.parametrize("key", ["depth", "time_bucket_ms"])
def test_ctl_an_enum_option_of_the_wrong_type_is_out_of_range(key: str, value: Any) -> None:
    err = _refused("heatmap.BTCUSDT", key, value)
    assert (err.code, err.field) == ("invalid_options", key)
    assert err.message == f"Option '{key}' is out of range."


@pytest.mark.parametrize("value", [[], {}], ids=["list", "object"])
@pytest.mark.parametrize(
    "ch", ["heatmap.BTCUSDT", "book.BTCUSDT.50", "trades.BTCUSDT", "profile.BTCUSDT.volume"]
)
def test_ctl_encoding_of_the_wrong_type_is_refused_whatever_the_topic(ch: str, value: Any) -> None:
    """`encoding` is no `ctl` key (§13.6): it is refused as an unknown key before its value is
    read. This pins that no value of it can fault there; that refusal's wording is #3370's."""
    err = _refused(ch, "encoding", value)
    assert (err.code, err.field) == ("invalid_options", "encoding")


def test_ctl_a_wrong_type_beside_legal_retunes_changes_nothing() -> None:
    """`depth` and `throttle_ms` sort before the bad `time_bucket_ms`, and are not applied."""
    ch = "heatmap.BTCUSDT"
    conn, sub = _subscribed(ch)
    before = _state(sub)
    body = {"depth": 200, "throttle_ms": 900, "time_bucket_ms": []}
    err = handle_ctl(conn, {"t": "ctl", "id": "c-9", "ch": ch, "p": body}, 7)
    assert (err["p"]["code"], err["p"]["field"]) == ("invalid_options", "time_bucket_ms")
    assert _state(sub) == before
    ok = _ctl(conn, ch, {"throttle_ms": 900})  # the subscription is still served
    assert (ok["t"], ok["p"]["effective"]["throttle_ms"]) == ("ctl_ok", 900)
