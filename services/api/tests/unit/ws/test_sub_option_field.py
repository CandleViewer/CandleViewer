"""#3479: a `sub` refusal of an unknown option key names it in `field` only when the server knows
the key as an option name (`23-ws-protocol.md` §5.1), as a `ctl` refusal does (§5.4, #3370). Any
other key is `opts`, whatever its length, and the message is fixed, so nothing the client sent is
reflected. The wire row is in `tests/contract/ws/test_ws_sub_option_field.py`."""

from __future__ import annotations

from typing import Any, Final

import pytest
from hypothesis import assume, given
from hypothesis import strategies as st

from candleviewer.ws.permissions import ConnectionAuthz
from candleviewer.ws.topics import (
    CTL_KEYS,
    FAMILIES,
    OPTION_NAMES,
    UNIVERSAL,
    TopicError,
    TopicFamily,
    validate_options,
)
from tests.unit.ws.test_subscriptions import A, _mgr, _services, _sub

UNKNOWN: Final = "Unknown option."
#: Every option name the registry declares, read from the registry and not from the server's set.
KNOWN: Final = frozenset(UNIVERSAL) | CTL_KEYS | {k for f in FAMILIES.values() for k in f.options}


def _refused(family: str, opts: Any) -> TopicError:
    with pytest.raises(TopicError) as caught:
        validate_options(FAMILIES[family], opts)
    return caught.value


def _error(ch: str, opts: Any) -> dict[str, Any]:
    """The per-entry `error` a `sub` of `ch` with `opts` gets; nothing is subscribed."""
    conn = ConnectionAuthz(_mgr(A), _services())
    (result,) = _sub(conn, {"ch": ch, "opts": opts})
    assert (result["ch"], result["ok"], conn.by_id) == (ch, False, {})
    assert set(result) == {"ch", "ok", "error"}
    error: dict[str, Any] = result["error"]
    return error


def _unknown(field: str) -> dict[str, Any]:
    return {"code": "invalid_options", "message": UNKNOWN, "field": field, "retryable": False}


@pytest.mark.parametrize(
    "key",
    [
        pytest.param("throttel_ms", id="typo"),
        pytest.param("zQ", id="2-chars"),
        pytest.param("zQ" * 21, id="past-the-old-40-char-cut"),
        pytest.param("zQ" * 250, id="500-chars"),
        pytest.param("THROTTLE_MS", id="case-differs"),
        pytest.param("throttle_ms ", id="trailing-space"),
        pytest.param("min_size\x00\r\n\x1b[31m", id="control-characters"),
        pytest.param("débit_ms \u202e \U0001f4a5", id="non-ascii"),
        pytest.param("", id="empty"),
        # The known exception: §13.5 declares `params`, and no topic takes it yet (#658).
        pytest.param("params", id="params"),
    ],
)
def test_sub_a_key_that_is_no_option_name_is_named_opts_with_a_fixed_message(key: str) -> None:
    """The whole `error` is the server's: nothing of the key, even beside a legal option."""
    assert _error("trades.BTCUSDT", {"throttle_ms": 500, key: 1}) == _unknown("opts")


@given(
    family=st.sampled_from(sorted(FAMILIES)),
    key=st.one_of(st.text(max_size=500), st.sampled_from(sorted(KNOWN))),
)
def test_sub_any_key_the_family_lacks_is_named_opts_unless_it_is_an_option_name(
    family: str, key: str
) -> None:
    assume(key not in {**UNIVERSAL, **FAMILIES[family].options})
    refusal = _refused(family, {key: 1})
    assert (refusal.code, refusal.message) == ("invalid_options", UNKNOWN)
    assert refusal.field in OPTION_NAMES | {"opts"}
    assert refusal.field == (key if key in KNOWN else "opts")


@pytest.mark.parametrize("family", sorted(FAMILIES))
def test_sub_names_every_option_name_the_registry_declares_that_the_family_lacks(
    family: str,
) -> None:
    """§5.1's names: any other family's option, a scope option, a `ctl` key. A value no option of
    a family that takes the name would accept; the key is refused before its value is read."""
    lacks = sorted(KNOWN - {**UNIVERSAL, **FAMILIES[family].options}.keys())
    assert lacks, family
    for name in lacks:
        refusal = _refused(family, {name: "junk"})
        assert (refusal.code, refusal.field, refusal.message) == ("invalid_options", name, UNKNOWN)


@pytest.mark.parametrize(
    ("ch", "key", "value"),
    [
        ("trades.BTCUSDT", "depth", 200),  # a `heatmap` option, on a topic that has no such option
        ("trades.BTCUSDT", "paused", True),  # a `ctl` key: `sub` does not take it
        ("trades.BTCUSDT", "exchange_account_ids", ["not-an-account"]),  # a scope option
        ("book.BTCUSDT.50", "price_grouping", 1),
        ("bars.BTCUSDT.time.1", "bar_type", "range"),  # fixed in the topic name
        ("footprint.BTCUSDT.time.5", "param", "10"),
        ("metrics.BTCUSDT", "history", 5),
    ],
)
def test_sub_a_known_name_the_topic_does_not_take_is_named_with_the_fixed_message(
    ch: str, key: str, value: Any
) -> None:
    assert _error(ch, {key: value}) == _unknown(key)


class _EqualsDepth:
    """No string, yet hashed and equal as `"depth"` is: a set test alone would name it."""

    def __hash__(self) -> int:
        return hash("depth")

    def __eq__(self, other: object) -> bool:
        return other == "depth"


@pytest.mark.parametrize(
    "key",
    [
        pytest.param(1, id="int"),
        pytest.param(1.5, id="float"),
        pytest.param(None, id="none"),
        pytest.param(b"throttle_ms", id="bytes-spelling-an-option-name"),
        pytest.param(("depth",), id="tuple"),
        pytest.param(_EqualsDepth(), id="object-equal-to-an-option-name"),
    ],
)
def test_sub_a_key_that_is_not_a_string_is_named_opts(key: Any) -> None:
    """The codecs refuse such a key before it gets here (`codec._check`), so this is the registry's
    own rule: a key is named only if it is a string that is an option name."""
    refusal = _refused("trades", {key: 1})
    assert (refusal.code, refusal.field, refusal.message) == ("invalid_options", "opts", UNKNOWN)
    conn = ConnectionAuthz(_mgr(A), _services())
    result, sub = conn.admit({"ch": "trades.BTCUSDT", "opts": {key: 1}})
    assert (sub, result["error"]) == (None, _unknown("opts"))


@pytest.mark.parametrize(
    ("ch", "key", "value"),
    [
        ("trades.BTCUSDT", "throttle_ms", -1),
        ("trades.BTCUSDT", "encoding", "xml"),
        ("trades.BTCUSDT", "coalesce", "yes"),
        ("trades.BTCUSDT", "min_size", 0.5),
        ("heatmap.BTCUSDT", "depth", 7),
        ("bars.BTCUSDT.time.1", "history", 1001),
    ],
)
def test_sub_a_known_key_with_a_bad_value_is_refused_as_out_of_range(
    ch: str, key: str, value: Any
) -> None:
    assert _error(ch, {key: value}) == {
        "code": "invalid_options",
        "message": f"Option '{key}' is out of range.",
        "field": key,
        "retryable": False,
    }


def test_sub_the_other_refusals_are_unchanged() -> None:
    refusal = _refused("book", [1])
    assert (refusal.code, refusal.field, refusal.message) == (
        ("invalid_options", "opts", "opts must be an object.")
    )
    assert validate_options(FAMILIES["book"], None) == {}
    needs = TopicFamily("t", ((),), None, None, 0, False, "X", required=frozenset({"x"}))
    with pytest.raises(TopicError) as caught:
        validate_options(needs, {})
    assert (caught.value.field, caught.value.message) == ("x", "Option 'x' is required.")


@pytest.mark.parametrize(
    ("opts", "refused"),
    [
        pytest.param(
            {"throttle_ms": -1, "zz": 1},
            ("throttle_ms", "Option 'throttle_ms' is out of range."),
            id="a-bad-value-sorts-first",
        ),
        pytest.param(
            {"aa": 1, "throttle_ms": -1}, ("opts", UNKNOWN), id="an-unknown-key-sorts-first"
        ),
    ],
)
def test_sub_keys_are_read_in_sorted_order_and_the_first_refusal_wins(
    opts: dict[str, Any], refused: tuple[str, str]
) -> None:
    refusal = _refused("trades", opts)
    assert (refusal.field, refusal.message) == refused
