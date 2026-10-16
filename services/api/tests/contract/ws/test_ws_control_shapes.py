"""#2572: `unsub`, `ctl` and `resync` read their shape as §13 does, and no reply echoes a value the
envelope schema constrains: a `ch` that is not a topic name, or an `id` over 64 characters.

The other control frames' analogue of the `sub` refusals (#2567, `test_ws_s1.py`). Every frame the
client receives is validated against §13 by the harness, so an echoed value fails on receipt."""

from __future__ import annotations

import json
from typing import Any

import pytest

from candleviewer.ws.limits import ENVELOPE_ID_MAX_LEN
from candleviewer.ws.permissions import UNSUB_KEYS
from tests.contract.ws._harness import SCHEMAS, World, connect

LONG = "t" * 10_000  # the issue's repro: a 10 000-character name
LONG_ID = "i" * (ENVELOPE_ID_MAX_LEN + 1)
#: Envelope `ch` values that are not a topic name (`common.schema.json#/$defs/topic`).
BAD_CH = [
    pytest.param("Bad Topic", id="bad-name"),
    pytest.param(LONG, id="10000-chars"),
    pytest.param("trades.BTCUSDT\n", id="trailing-newline"),
    pytest.param(5, id="int"),
    pytest.param({"a": 1}, id="object"),
]
CTL = {"throttle_ms": 100}
RESYNC = {"reason": "manual"}


def test_contract_unsub_payload_keys_equal_the_schema() -> None:
    """A key §13.5 adds to `unsub.p` must not be refused as unknown."""
    assert UNSUB_KEYS == set(SCHEMAS["cv://ws/v1/unsub.schema.json"]["properties"])


def test_contract_envelope_id_bound_equals_the_schema() -> None:
    envelope = SCHEMAS["cv://ws/v1/envelope.schema.json"]
    assert ENVELOPE_ID_MAX_LEN == envelope["properties"]["id"]["maxLength"]


@pytest.mark.parametrize(
    ("p", "field"),
    [
        pytest.param({"topics": ["Bad Topic", 7, LONG]}, "topics[0]", id="the-2572-repro"),
        pytest.param({"topics": ["trades.BTCUSDT", 7]}, "topics[1]", id="int-entry"),
        pytest.param({"topics": [{"ch": "trades.BTCUSDT"}]}, "topics[0]", id="object-entry"),
        pytest.param({"topics": ["trades.BTCUSDT"], "bogus": 1}, "p", id="unknown-key"),
        pytest.param({"topics": []}, "topics", id="topics-empty"),
    ],
)
def test_contract_unsub_with_a_malformed_shape_is_refused_whole(p: Any, field: str) -> None:
    with connect(World()) as c:
        c.sub("trades.BTCUSDT")
        c.send({"t": "unsub", "id": "u", "p": p}, conform=False)
        f = c.next_validated("err")  # the `snap` that follows `sub_ok` is skipped
        assert (f["id"], f["p"]["code"], f["p"]["field"]) == ("u", "invalid_options", field)
        assert "ch" not in f and len(json.dumps(f)) < 400  # no `unsub_ok`, nothing reflected
        c.send({"t": "ctl", "id": "k", "ch": "trades.BTCUSDT", "p": CTL})
        assert c.next_validated("ctl_ok")["id"] == "k"  # the subscription the frame named stays


@pytest.mark.parametrize("ch", BAD_CH)
@pytest.mark.parametrize(("t", "p"), [("ctl", CTL), ("resync", RESYNC)])
def test_contract_a_non_topic_ch_is_refused_without_being_echoed(t: str, p: Any, ch: Any) -> None:
    with connect(World()) as c:
        c.send({"t": t, "id": "k", "ch": ch, "p": p}, conform=False)
        f = c.recv()
        assert (f["t"], f["id"], f["p"]["code"], f["p"]["field"]) == (
            ("err", "k", "invalid_options", "ch")
        )
        assert "ch" not in f and len(json.dumps(f)) < 400  # the `ch` is omitted, not nulled


def test_contract_refused_control_frames_are_not_protocol_strikes() -> None:
    refused: list[dict[str, Any]] = [
        {"t": "unsub", "id": "u", "p": {"topics": ["Bad Topic"]}},
        {"t": "ctl", "id": "k", "ch": "Bad Topic", "p": CTL},
        {"t": "resync", "id": "r", "ch": "Bad Topic", "p": RESYNC},
    ]
    with connect(World()) as c:
        for _ in range(4):  # past the 3 protocol strikes that close with `4400` (§4.3)
            for frame in refused:
                c.send(frame, conform=False)
                assert c.recv()["p"]["code"] == "invalid_options"
        assert c.sub("trades.BTCUSDT")["p"]["results"][0]["ok"]  # the socket is still served


# -- the envelope `id` --------------------------------------------------------------------------

_REQUESTS: list[tuple[str, dict[str, Any]]] = [
    ("ping", {"t": "ping"}),
    ("sub", {"t": "sub", "p": {"topics": [{"ch": "trades.BTCUSDT"}]}}),
    ("unsub", {"t": "unsub", "p": {"topics": ["trades.BTCUSDT"]}}),
    ("ctl", {"t": "ctl", "ch": "trades.BTCUSDT", "p": CTL}),
    ("resync", {"t": "resync", "ch": "trades.BTCUSDT", "p": RESYNC}),
]


@pytest.mark.parametrize(
    "frame_id",
    [
        pytest.param(LONG_ID, id="65-chars"),
        pytest.param("i" * 10_000, id="10000-chars"),
        pytest.param(5, id="int"),
        pytest.param(None, id="null"),
    ],
)
@pytest.mark.parametrize(("name", "request_"), _REQUESTS, ids=[n for n, _ in _REQUESTS])
def test_contract_an_id_the_envelope_forbids_is_never_echoed(
    name: str, request_: dict[str, Any], frame_id: Any
) -> None:
    """§13.1: `id` is a string of at most 64 characters. Any other value is dropped, so the
    reply (validated on receipt) has none; the request itself is still handled."""
    with connect(World()) as c:
        c.send({**request_, "id": frame_id}, conform=False)
        assert "id" not in c.recv()


@pytest.mark.parametrize("unit", ["i", "é", "😀"])  # the bound counts characters, not bytes
def test_contract_the_id_bound_counts_characters_not_bytes(unit: str) -> None:
    with connect(World()) as c:
        at_bound = unit * ENVELOPE_ID_MAX_LEN
        c.send({"t": "ping", "id": at_bound})
        assert c.next_of("pong")["id"] == at_bound  # the bound itself is echoed
        c.send({"t": "ping", "id": at_bound + unit}, conform=False)
        assert "id" not in c.next_of("pong")  # one character more is not


def test_contract_handshake_and_violation_replies_do_not_echo_a_long_id() -> None:
    hello = {"client": "conformance", "client_version": "1.0.0", "protocol": "cv.v1"}
    auth = {"access_token": "good-" + "x" * 20}
    with connect(World(), handshake=False) as c:
        for frame, want in (
            ({"t": "hello", "p": hello}, "welcome"),
            ({"t": "sub", "p": {"topics": ["trades.BTCUSDT"]}}, "not_authenticated"),
            ({"t": "auth", "p": auth}, "auth_ok"),
            ({"t": "bogus"}, "frame_malformed"),
        ):
            c.send({**frame, "id": LONG_ID}, conform=False)
            f = c.recv()
            assert (f["t"] if f["t"] != "err" else f["p"]["code"], "id" in f) == (want, False)
