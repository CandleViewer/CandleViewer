"""SR-193 (#2293) through the real gateway (`23-ws-protocol.md` §5.2, §5.4, §7.5): a topic's own
resync loop is revoked and its topic cannot restart within the window, and AC-30's `ctl` loop and
`sub` churn stay within the rebuild budget, on the connection's clock. Every frame is validated."""

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


@pytest.mark.parametrize("offer", OFFERS.values(), ids=OFFERS.keys())
def test_a_resync_loop_is_revoked_and_its_topic_cannot_restart_within_the_window(
    offer: list[str],
) -> None:
    w = World()
    with connect(w, offer) as c:
        c.sub(BOOK)
        for i in range(6):
            c.send({"t": "resync", "id": f"r{i}", "ch": BOOK, "p": {"reason": "manual"}})
        frames = _until_pong(c)
        assert [f["t"] for f in frames] == ["snap"] * 6 + ["err", "revoked"]  # AC-17
        assert frames[-1]["p"]["reason"] == "resync_rate_limited"
        assert frames[-2]["p"]["message"] == ERROR_META[ErrorCode.RESYNC_RATE_LIMITED].title
        refused = c.sub(BOOK)["p"]["results"][0]  # released by the revocation: its five are spent
        assert (refused["ok"], refused["error"]["code"]) == (False, "resync_rate_limited")
        w.advance(c, 60.0)
        assert c.sub(BOOK)["p"]["results"][0]["ok"]
        c.send({"t": "resync", "id": "r6", "ch": BOOK, "p": {"reason": "manual"}})
        assert [f["meta"]["reason"] for f in _until_pong(c)] == ["initial", "client_resync"]


@pytest.mark.parametrize("offer", OFFERS.values(), ids=OFFERS.keys())
def test_ac30_a_ctl_loop_and_a_50_topic_churn_for_60_s_stay_within_the_budget(
    offer: list[str],
) -> None:
    """AC-30 on the fake clock: a `ctl` flip each second and an `unsub` + `sub` of 50 topics every
    2 s, under the inbound limits (§8.5), with a new generation each step so no `snap` is cached."""
    w = World()
    churn = [f"trades.S{i:02d}USDT" for i in range(39)] + [
        f"ticker.S{i:02d}USDT" for i in range(11)
    ]
    with connect(w, offer) as c:
        c.sub(HEAT)
        c.sub(*churn)
        _until_pong(c)
        builds, frames = w.source.builds, list[dict[str, Any]]()
        for step in range(60):
            w.clock.now, w.source.gen = float(step), w.source.gen + 1
            bucket = (1000, 500)[step % 2]
            c.send({"t": "ctl", "id": f"k{step}", "ch": HEAT, "p": {"time_bucket_ms": bucket}})
            if step % 2 == 0:
                c.send({"t": "unsub", "id": f"u{step}", "p": {"topics": churn}})
                c.send(
                    {"t": "sub", "id": f"s{step}", "p": {"topics": [{"ch": ch} for ch in churn]}}
                )
            frames += _until_pong(c)
        snaps = [f["meta"]["reason"] for f in frames if f["t"] == "snap"]
        refused = [f["p"]["code"] for f in frames if f["t"] == "err"]
        results = [r for f in frames if f["t"] == "sub_ok" for r in f["p"]["results"]]
        assert (snaps.count("reconfigure"), snaps.count("initial")) == (5, 5 * 50)
        # A refused flip leaves the bucket as it was, so only every other one would change it.
        assert refused == ["resync_rate_limited"] * 28 and w.source.builds - builds == 5 + 5 * 50
        assert sum(not r["ok"] for r in results) == 25 * 50  # every one `resync_rate_limited`
        assert {r["error"]["code"] for r in results if not r["ok"]} == {"resync_rate_limited"}
        err = next(f for f in frames if f["t"] == "err")
        assert (err["id"], err["ch"], err["p"]["retryable"]) == ("k5", HEAT, True)
        c.send({"t": "resync", "id": "r", "ch": HEAT, "p": {"reason": "manual"}})
        assert [f["t"] for f in _until_pong(c)] == ["err"]  # spent by `ctl`: not revoked
        publish(w, "heatmap", HEAT)
        assert [f["t"] for f in _until_pong(c)] == ["d"]  # the refused `ctl`s changed nothing
        w.advance(c, 70.0)  # the socket stayed open, and the window slides
        c.send({"t": "ctl", "id": "k-last", "ch": HEAT, "p": {"time_bucket_ms": 5000}})
        assert [f["t"] for f in _until_pong(c)] == ["ctl_ok", "snap"]
