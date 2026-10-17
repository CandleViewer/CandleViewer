"""SR-193 (#2293) through the real gateway (`23-ws-protocol.md` §5.4, §7.5): a `ctl`
re-snapshot loop is refused with `resync_rate_limited` while its stream carries on (a `resync`
it spent is refused, not revoked), a topic's own resync loop is revoked across an `unsub` and a
new `sub`, and the window slides on the connection's clock. Every frame received is validated
against the §13-§15 schemas."""

from __future__ import annotations

from typing import Any

import pytest

from candleviewer.ws._generated.error_codes import ERROR_META, ErrorCode
from tests.contract.ws._harness import OFFERS, Client, World, connect, publish

BOOK, HEAT = "book.BTCUSDT.50", "heatmap.BTCUSDT"


def _until_pong(c: Client) -> list[dict[str, Any]]:
    """Every frame the server sent before it answered a fence ping."""
    c.send({"t": "ping", "id": "fence"})
    out: list[dict[str, Any]] = []
    while (frame := c.recv())["t"] != "pong":
        out.append(frame)
    return out


def _flip(c: Client, rid: str, bucket: int) -> None:
    c.send({"t": "ctl", "id": rid, "ch": HEAT, "p": {"time_bucket_ms": bucket}})


@pytest.mark.parametrize("offer", OFFERS.values(), ids=OFFERS.keys())
def test_a_ctl_resnapshot_loop_is_refused_and_the_stream_carries_on(offer: list[str]) -> None:
    w = World()
    with connect(w, offer) as c:
        c.sub(HEAT)
        _until_pong(c)  # its `initial` snap
        for i in range(5):
            w.clock.now = float(i)
            _flip(c, f"k{i}", (1000, 500)[i % 2])
        _flip(c, "k5", 5000)
        frames = _until_pong(c)
        accepted = [(("ctl_ok", f"k{i}"), ("snap", "reconfigure")) for i in range(5)]
        assert [(f["t"], f.get("id") or f["meta"]["reason"]) for f in frames[:-1]] == [
            pair for both in accepted for pair in both
        ]
        err = frames[-1]
        assert (err["t"], err["id"], err["ch"]) == ("err", "k5", HEAT)
        assert (err["p"]["code"], err["p"]["retryable"]) == ("resync_rate_limited", True)
        c.send({"t": "resync", "id": "r", "ch": HEAT, "p": {"reason": "manual"}})
        assert [(f["t"], f["p"]["code"]) for f in _until_pong(c)] == [  # no `revoked`
            ("err", "resync_rate_limited")
        ]
        publish(w, "heatmap", HEAT)
        assert [f["t"] for f in _until_pong(c)] == ["d"]  # not paused, not pending: carries on
        w.advance(c, 60.0)  # the connection's clock: the first flip leaves the window
        _flip(c, "k6", 5000)
        assert [f["t"] for f in _until_pong(c)] == ["ctl_ok", "snap"]


@pytest.mark.parametrize("offer", OFFERS.values(), ids=OFFERS.keys())
def test_a_resync_after_an_unsub_and_a_new_sub_meets_the_same_budget(offer: list[str]) -> None:
    w = World()
    with connect(w, offer) as c:
        c.sub(BOOK)
        for i in range(5):
            c.send({"t": "resync", "id": f"r{i}", "ch": BOOK, "p": {"reason": "manual"}})
        c.send({"t": "unsub", "id": "u", "p": {"topics": [BOOK]}})
        assert [f["t"] for f in _until_pong(c)] == ["snap"] * 6 + ["unsub_ok"]
        c.sub(BOOK)
        c.send({"t": "resync", "id": "r5", "ch": BOOK, "p": {"reason": "manual"}})
        frames = _until_pong(c)
        assert [(f["t"], f.get("id")) for f in frames] == [
            ("snap", None),
            ("err", "r5"),
            ("revoked", None),
        ]
        assert frames[2]["p"]["reason"] == "resync_rate_limited"  # its own loop: AC-17
        assert frames[1]["p"]["message"] == ERROR_META[ErrorCode.RESYNC_RATE_LIMITED].title
        w.advance(c, 60.0)
        c.sub(BOOK)
        c.send({"t": "resync", "id": "r6", "ch": BOOK, "p": {"reason": "manual"}})
        snaps = [f["meta"]["reason"] for f in _until_pong(c)]
        assert snaps == ["initial", "client_resync"]
