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


@pytest.mark.xfail(
    strict=True, reason="#2396: sub_ok echoes a malformed topic name in results[].ch"
)
def test_s1_xfail_f2_sub_ok_never_echoes_a_malformed_topic_name() -> None:
    with connect(World()) as c:
        c.sub("Bad Topic", conform=False)  # the reply is validated against common#/$defs/topic


@pytest.mark.xfail(strict=True, reason="#2399: non-string topic entries are dropped, not answered")
def test_s1_xfail_f4_every_requested_topic_gets_a_result_even_if_not_a_string() -> None:
    """Contract (§5.2 + S1): either one result per requested entry (4 here, `null` included) or a
    whole-frame `err frame_malformed` rejecting the request. Silently answering fewer is neither."""
    with connect(World()) as c:
        bad: list[Any] = [123, {"opts": {}}, None, {"ch": "ticker.BTCUSDT"}]
        c.send({"t": "sub", "id": "z", "p": {"topics": bad}}, conform=False)
        f = c.recv(validate=False)
        if f["t"] == "err":
            assert f["p"]["code"] == "frame_malformed"
        else:
            assert len(f["p"]["results"]) == len(bad)


@pytest.mark.xfail(strict=True, reason="#2399: unknown keys in sub.p are accepted and ignored")
def test_s1_xfail_f6_unknown_key_in_sub_payload_is_rejected() -> None:
    with connect(World()) as c:
        c.send(
            {"t": "sub", "id": "z", "p": {"topics": [{"ch": "trades.BTCUSDT"}], "bogus": 1}},
            conform=False,
        )
        f = c.recv()
        assert f["t"] == "err" or not any(r["ok"] for r in f["p"]["results"])
