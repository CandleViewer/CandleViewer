"""E17-Q01: one named test per normative server requirement S1-S13 (`23-ws-protocol.md` §16.1).

Every test drives the REAL gateway (`make_ws_router`, `ConnectionRegistry`, `SequencingHub`,
`TopicEmitter`) through a socket and validates every received frame against the §13-§15 schemas
(`_harness.validate_frame`). Test names start `test_sN_` so the coverage matrix in
`conftest.py` can report which requirements ran.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from candleviewer.auth.generated_permissions import Permission
from candleviewer.ws.limits import MAX_INBOUND_FRAME_BYTES
from candleviewer.ws.topics import FAMILIES
from tests.contract.ws._harness import (
    OFFERS,
    SCHEMAS,
    World,
    connect,
    json_only,
)
from tests.unit.ws._seq_support import ACC_B

RS = "bb000000-0000-4000-8000-000000000001"
_ROWS = [
    pytest.param(f.family, shape, id=".".join((f.family, *shape)))
    for f in FAMILIES.values()
    for shape in f.shapes
    if f.family != "system"  # implicit, never a Subscription (§6.2); see S2 note in the plan
]
# -- S1 ----------------------------------------------------------------------------------------


@pytest.mark.parametrize("offer", OFFERS.values(), ids=OFFERS.keys())
def test_s1_one_sub_ok_result_per_requested_topic_in_request_order(offer: list[str]) -> None:
    w = World()
    topics: list[Any] = [
        {"ch": "trades.BTCUSDT"},
        {"ch": "nope.BTCUSDT"},  # unknown_topic
        {"ch": "book.BTCUSDT.50"},
        {"ch": "orders", "opts": {"exchange_account_ids": [str(ACC_B)]}},
        {"ch": "book.BTCUSDT.7"},  # invalid_topic_format
        {"ch": "trades.BTCUSDT"},  # duplicate_subscription
        {"ch": "ticker.BTCUSDT", "opts": {"bogus": 1}},  # invalid_options
    ]
    with connect(w, offer) as c:
        res = c.sub(*topics, conform=False)  # carries a deliberately invalid option
        results = res["p"]["results"]
        assert [r["ch"] for r in results] == [
            "trades.BTCUSDT",
            "nope.BTCUSDT",
            "book.BTCUSDT.50",
            "orders",
            "book.BTCUSDT.7",
            "trades.BTCUSDT",
            "ticker.BTCUSDT",
        ]
        assert [r["ok"] for r in results] == [True, False, True, True, False, False, False]
        assert res["id"] == "s"  # echoed correlation id
        # exactly ONE sub_ok for the request: the next frames are snaps, never a second sub_ok
        rest = c.drain(3)
        assert [f["t"] for f in rest] == ["snap"] * 3


def test_s1_every_topic_failing_still_yields_one_result_each() -> None:
    w = World()
    with connect(w) as c:
        bad = [{"ch": f"nope_{chr(97 + i)}.BTCUSDT"} for i in range(5)]
        results = c.sub(*bad)["p"]["results"]
        assert [r["ch"] for r in results] == [t["ch"] for t in bad]
        assert not any(r["ok"] for r in results)


# F2, F4, F6 (#2396, #2399): a `sub` whose shape breaks §13.5 is refused whole, with one
# `err invalid_options` naming the field and no `sub_ok` (orchestrator contract decision,
# 2026-10-15; §5.2). One result per requested topic applies to topics, not to entries that are not.


@pytest.mark.parametrize(
    ("entry", "field"),
    [
        ("Bad Topic", "topics[0]"),  # the string form of the #2396 repro
        ({"ch": "Bad Topic"}, "topics[0].ch"),
        ("t" * 130, "topics[0]"),  # past the 120-character topic bound
    ],
)
def test_s1_f2_a_malformed_topic_name_is_never_echoed(entry: Any, field: str) -> None:
    with connect(World()) as c:
        c.send({"t": "sub", "id": "z", "p": {"topics": [entry]}}, conform=False)
        f = c.recv()  # validated: an `err`, so no `results[].ch` echoes the name
        assert (f["t"], f["id"], f["p"]["code"], f["p"]["field"]) == (
            "err",
            "z",
            "invalid_options",
            field,
        )


def test_s1_f4_a_non_topic_entry_refuses_the_whole_sub() -> None:
    with connect(World()) as c:
        bad: list[Any] = [123, {"opts": {}}, None, {"ch": "ticker.BTCUSDT"}]
        c.send({"t": "sub", "id": "z", "p": {"topics": bad}}, conform=False)
        f = c.recv()
        assert (f["t"], f["p"]["code"], f["p"]["field"]) == ("err", "invalid_options", "topics[0]")


def test_s1_f6_unknown_key_in_sub_payload_refuses_it_without_a_strike() -> None:
    with connect(World()) as c:
        for i in range(4):  # past the 3 protocol strikes that close with `4400` (§4.3)
            frame = {"t": "sub", "id": f"z{i}", "p": {"topics": [{"ch": "trades.BTCUSDT"}], "x": 1}}
            c.send(frame, conform=False)
            f = c.recv()
            assert (f["t"], f["p"]["code"], f["p"]["field"]) == ("err", "invalid_options", "p")
        assert c.sub("trades.BTCUSDT")["p"]["results"][0]["ok"]


# SR-192 (#2292): a `sub` longer than the 50 entries §13.5 allows is refused whole, before any
# entry is read, with one `err too_many_topics`; neither its reply nor its audit writes grow with
# the frame (E17 threat model WS-D15, AC-29; §5.2).

#: §13.5 `sub.topics.maxItems`, the most entries one `sub` may hold (50).
CAP: int = SCHEMAS["cv://ws/v1/sub.schema.json"]["properties"]["topics"]["maxItems"]


def _footprints(n: int) -> list[str]:
    """`n` distinct public topics on one symbol, all of which a market-data principal may hold."""
    return [f"footprint.BTCUSDT.tick.{i}" for i in range(1, n + 1)]


class _Audit:
    """The gateway's audit sink: each `emit` is one append."""

    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    async def emit(self, action: str, **kw: Any) -> None:
        self.records.append({"action": action, **kw})


def test_s1_a_sub_of_exactly_the_cap_welcome_advertises_gets_one_result_per_topic() -> None:
    """The limit `welcome` advertises is the one `sub` enforces: `max_topics_per_request`
    entries are processed (the frame is schema-valid, so the harness validates it on send)."""
    with connect(World()) as c:
        welcome = next(f for f in c.seen if f["t"] == "welcome")
        assert welcome["p"]["limits"]["max_topics_per_request"] == CAP
        names = _footprints(CAP)
        results = c.sub(*names)["p"]["results"]
        assert [(r["ch"], r["ok"]) for r in results] == [(n, True) for n in names]


@pytest.mark.parametrize("offer", OFFERS.values(), ids=OFFERS.keys())
def test_s1_a_sub_over_the_cap_is_refused_whole_and_is_no_strike(offer: list[str]) -> None:
    """One `err too_many_topics` (`field: topics`) per frame, validated against §13, on both
    subprotocols (51 entries are within MessagePack's 128, §3.6). Four in a row are past the three
    strikes that close a socket (§4.3), and nothing was subscribed: the first name is still free."""
    names = _footprints(CAP + 1)
    with connect(World(), offer) as c:
        for i in range(4):
            frame = {"t": "sub", "id": f"z{i}", "p": {"topics": [{"ch": n} for n in names]}}
            c.send(frame, conform=False)
            f = c.recv()
            assert (f["t"], f["id"], f["p"]["code"], f["p"]["field"]) == (
                "err",
                f"z{i}",
                "too_many_topics",
                "topics",
            )
            assert f["p"]["retryable"] is True and "ch" not in f
        assert c.sub(names[0])["p"]["results"][0]["ok"] is True


@pytest.mark.parametrize("offer", OFFERS.values(), ids=OFFERS.keys())
def test_s1_denial_audit_of_a_sub_over_and_at_the_cap(offer: list[str]) -> None:
    """SR-192 on both subprotocols: a `sub` over the cap writes no audit row, and a frame of
    `CAP` audited refusals writes ONE `ws.subscribe.denied` record that counts them all."""
    w = World()
    w.perms = frozenset({Permission.MARKETDATA_READ})
    audit = _Audit()
    w.registry.services.audit = audit
    private = ["orders", "positions", "executions", "wallet"]
    over = [{"ch": n} for n in (private * CAP)[: CAP + 1]]
    with connect(w, offer) as c:
        c.send({"t": "sub", "id": "o", "p": {"topics": over}}, conform=False)
        f = c.recv()
        assert (f["t"], f["id"], f["p"]["field"]) == ("err", "o", "topics")
        assert f["p"]["code"] == "too_many_topics" and audit.records == []
        results = c.sub(*(private * CAP)[:CAP])["p"]["results"]
        assert [r["error"]["code"] for r in results] == ["forbidden"] * CAP
    ((action, count),) = [(r["action"], r["after_state"]["count"]) for r in audit.records]
    assert (action, count) == ("ws.subscribe.denied", CAP)


def _sub_text(topics: list[str]) -> str:
    return json.dumps({"t": "sub", "id": "s", "p": {"topics": topics}}, separators=(",", ":"))


@json_only  # the JSON text fills the cap; MessagePack caps an array at 128 entries (SR-185)
def test_s1_the_largest_sub_the_frame_cap_allows_gets_one_small_err_and_no_audit_row() -> None:
    """AC-29 at the socket, as a principal with market data only: the issue's frame, 21 842 bare
    `positions` names filling the 256 KiB cap, gets one `err` of a few hundred bytes and writes
    no audit row, and the socket is still served. A 50-entry frame of private families is then
    processed, and its 50 refusals are one `ws.subscribe.denied` record that counts them."""
    w = World()
    w.perms = frozenset({Permission.MARKETDATA_READ})
    audit = _Audit()
    w.registry.services.audit = audit
    entries = (MAX_INBOUND_FRAME_BYTES - len(_sub_text([])) + 1) // len('"positions",')
    text = _sub_text(["positions"] * entries)  # the very text that is sent below
    assert entries == 21_842
    assert MAX_INBOUND_FRAME_BYTES - 12 < len(text.encode()) <= MAX_INBOUND_FRAME_BYTES
    private = ["orders", "positions", "executions", "wallet"]
    with connect(w) as c:
        c.send_text(text)
        f = c.recv()
        assert (f["t"], f["id"], f["p"]["code"], f["p"]["field"]) == (
            "err",
            "s",
            "too_many_topics",
            "topics",
        )
        assert len(json.dumps(f)) < 400 and audit.records == []
        c.send({"t": "ping", "id": "k"})
        assert c.next_of("pong")["id"] == "k"
        results = c.sub(*(private * CAP)[:CAP])["p"]["results"]
        assert [r["error"]["code"] for r in results] == ["forbidden"] * CAP
    ((action, count),) = [(r["action"], r["after_state"]["count"]) for r in audit.records]
    assert (action, count) == ("ws.subscribe.denied", CAP)
