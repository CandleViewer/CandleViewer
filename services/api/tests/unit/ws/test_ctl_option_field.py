"""#3370: a `ctl` refusal names its option key in `field` only when the server knows the key as an
option name (`23-ws-protocol.md` §5.4). Any other key is `p`, whatever its length, and the message
is fixed, so nothing the client sent is reflected. The wire row is in `tests/contract/ws/`."""

from __future__ import annotations

import json
from typing import Any, Final

import pytest
from hypothesis import given
from hypothesis import strategies as st

from candleviewer.ws.permissions import ConnectionAuthz
from candleviewer.ws.topics import CTL_KEYS, FAMILIES, UNIVERSAL
from tests.unit.ws.test_subscriptions import A, _ctl, _mgr, _services, _sub

UNKNOWN: Final = "Unknown ctl option."
#: Every option name the registry declares, read from the registry and not from the server's set.
KNOWN: Final = frozenset(UNIVERSAL) | CTL_KEYS | {k for f in FAMILIES.values() for k in f.options}
TOPICS: Final = ("book.BTCUSDT.50", "trades.BTCUSDT", "heatmap.BTCUSDT", "metrics.BTCUSDT")


def _refusal(ch: str, body: Any) -> dict[str, Any]:
    """The `err` a `ctl` of `body` gets on a new subscription of `ch`, which it leaves unchanged."""
    conn = ConnectionAuthz(_mgr(A), _services())
    assert _sub(conn, ch)[0]["ok"]
    sub = conn.find(ch)
    assert sub is not None
    before = (dict(sub.opts), dict(sub.effective), sub.snapshot_pending)
    err = _ctl(conn, ch, body)
    assert (err["t"], err["id"], err["ch"]) == ("err", "c-9", ch)
    assert (sub.opts, sub.effective, sub.snapshot_pending) == before
    return err


def _what(err: dict[str, Any]) -> tuple[str, str, str]:
    return err["p"]["code"], err["p"]["field"], err["p"]["message"]


@pytest.mark.parametrize(
    "key",
    [
        pytest.param("throttel_ms", id="typo"),
        pytest.param("zQ", id="2-chars"),
        pytest.param("zQ" * 21, id="past-the-old-40-char-cut"),
        pytest.param("zQ" * 250, id="500-chars"),
        pytest.param("THROTTLE_MS", id="case-differs"),
        pytest.param("throttle_ms ", id="trailing-space"),
        pytest.param("", id="empty"),
        # The known exception: §13.5 declares `params`, and no topic takes it yet (#658).
        pytest.param("params", id="params"),
    ],
)
def test_ctl_a_key_that_is_no_option_name_is_named_p_with_a_fixed_message(key: str) -> None:
    """Small, free of the key, and nothing changed (`_refusal`), even beside a legal retune."""
    err = _refusal("trades.BTCUSDT", {"throttle_ms": 500, key: 1})
    assert _what(err) == ("invalid_options", "p", UNKNOWN)
    assert len(json.dumps(err)) < 400 and (key == "" or key not in json.dumps(err))


@given(key=st.text(max_size=500).filter(lambda k: k not in KNOWN))
def test_ctl_any_key_that_is_no_option_name_is_named_p(key: str) -> None:
    err = _refusal("trades.BTCUSDT", {key: 1})
    assert _what(err) == ("invalid_options", "p", UNKNOWN) and len(json.dumps(err)) < 400


def test_ctl_names_every_option_name_the_registry_declares() -> None:
    """§5.4's list (`encoding`, `from_seq`, `depth` on `book`, `bar_type`, `param`, a scope option)
    and every other name: given a value no option takes, `field` is the name, on any topic."""
    for ch in TOPICS:
        conn = ConnectionAuthz(_mgr(A), _services())
        assert _sub(conn, ch)[0]["ok"]
        for name in sorted(KNOWN):
            err = _ctl(conn, ch, {name: "junk"})
            assert (err["p"]["code"], err["p"]["field"]) == ("invalid_options", name), (ch, name)


@pytest.mark.parametrize(
    ("ch", "key", "value"),
    [
        ("book.BTCUSDT.50", "depth", 200),  # a `ctl` key, on a topic that has no such option
        ("trades.BTCUSDT", "encoding", "binary"),  # a `sub` option
        ("trades.BTCUSDT", "from_seq", 1),
        ("metrics.BTCUSDT", "bar_type", "range"),  # fixed at `sub` (§5.4)
        ("metrics.BTCUSDT", "param", "10"),
    ],
)
def test_ctl_a_known_name_it_does_not_take_is_named_with_the_fixed_message(
    ch: str, key: str, value: Any
) -> None:
    assert _what(_refusal(ch, {key: value})) == ("invalid_options", key, UNKNOWN)


@pytest.mark.parametrize(
    ("ch", "key", "value"),
    [
        ("trades.BTCUSDT", "throttle_ms", -1),
        ("trades.BTCUSDT", "coalesce", "yes"),
        ("trades.BTCUSDT", "min_size", "x"),
        ("heatmap.BTCUSDT", "depth", 7),
        ("trades.BTCUSDT", "paused", "yes"),  # a boolean on every topic, though no family lists it
        ("trades.BTCUSDT", "paused", 1),
    ],
)
def test_ctl_a_known_key_with_a_bad_value_is_refused_as_out_of_range(
    ch: str, key: str, value: Any
) -> None:
    assert _what(_refusal(ch, {key: value})) == (
        ("invalid_options", key, f"Option '{key}' is out of range.")
    )
