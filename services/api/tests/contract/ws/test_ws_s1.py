"""E17-Q01: one named test per normative server requirement S1-S13 (`23-ws-protocol.md` §16.1).

Every test drives the REAL gateway (`make_ws_router`, `ConnectionRegistry`, `SequencingHub`,
`TopicEmitter`) through a socket and validates every received frame against the §13-§15 schemas
(`_harness.validate_frame`). Test names start `test_sN_` so the coverage matrix in
`conftest.py` can report which requirements ran.
"""

from __future__ import annotations

from typing import Any

import pytest

from candleviewer.ws.topics import FAMILIES
from tests.contract.ws._harness import (
    OFFERS,
    World,
    connect,
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
