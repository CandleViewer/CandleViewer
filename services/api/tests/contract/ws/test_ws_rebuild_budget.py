"""SR-193 (#2293) through the real gateway (`23-ws-protocol.md` §5.2, §5.4, §7.5): a topic's own
resync loop is revoked and its topic cannot restart within the window, and AC-30's `ctl` loop and
`sub` churn stay within the rebuild budget, on the connection's clock; a user's sockets share its
limit, which outlives them, and its first refusal in a window is audited (#3476, AC-31). Every
frame is validated."""

from __future__ import annotations

from typing import Any

import pytest

from candleviewer.audit.actions import AUDIT_ACTIONS
from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.ws._generated.error_codes import ERROR_META, ErrorCode
from tests.contract.ws._harness import OFFERS, Client, World, connect, publish
from tests.unit.ws._seq_support import USER

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


@pytest.mark.parametrize("offer", OFFERS.values(), ids=OFFERS.keys())
def test_ac31_a_user_s_sockets_share_one_rebuild_limit_that_outlives_them(offer: list[str]) -> None:
    """#3476 with a user limit of 12: A starts 8 topics and B 8, of which 4 pass; B's `resync` and
    A's resuming `ctl` get `err`, never a `revoked`; after both close, a new socket is refused
    until the window slides."""
    w = World()
    w.registry.services.user_rebuilds.limit = 12
    told = "Rebuild budget spent (12 a minute per user);"
    mine, theirs = [[f"trades.S{i:02d}USDT" for i in range(n, n + 8)] for n in (0, 8)]
    with w.client:
        with (
            w.client.websocket_connect("/ws", subprotocols=offer) as ws_a,
            w.client.websocket_connect("/ws", subprotocols=offer) as ws_b,
        ):
            a, b = Client(ws_a), Client(ws_b)
            a.open()
            b.open()
            assert all(r["ok"] for r in a.sub(*mine)["p"]["results"])
            results = b.sub(*theirs)["p"]["results"]
            assert [r.get("error", {}).get("message") for r in results] == [None] * 4 + [
                f"{told} not subscribed."
            ] * 4
            _until_pong(a), _until_pong(b)
            b.send({"t": "resync", "id": "r", "ch": theirs[0], "p": {"reason": "manual"}})
            assert [(f["t"], f["p"]["code"]) for f in _until_pong(b)] == [
                ("err", "resync_rate_limited")
            ]
            for i, paused in enumerate((True, False)):  # the resume would re-snapshot
                a.send({"t": "ctl", "id": f"k{i}", "ch": mine[0], "p": {"paused": paused}})
            assert [f["t"] for f in _until_pong(a)] == ["ctl_ok", "err"]
        with w.client.websocket_connect("/ws", subprotocols=offer) as ws_c:
            c = Client(ws_c)
            c.open()
            assert not c.sub(mine[0])["p"]["results"][0]["ok"]  # the user's window outlived both
            w.advance(c, 60.0)
            assert c.sub(mine[0])["p"]["results"][0]["ok"]


class _Rows:
    """An audit sink that keeps what it is given."""

    def __init__(self) -> None:
        self.rows: list[tuple[str, dict[str, Any]]] = []

    async def emit(self, action: str, **row: Any) -> None:
        self.rows.append((action, row))


@pytest.mark.parametrize("offer", OFFERS.values(), ids=OFFERS.keys())
def test_ac31_a_user_s_first_refusal_in_each_window_is_audited_once(offer: list[str]) -> None:
    """#3476 with a user limit of 1: one `ws.rebuild.refused` record per user per window, its first
    `user` refusal's, whichever path refused it: a resuming `ctl` at 0 s, a `resync` at 60 s and a
    `sub` entry at 120 s. The refusals after it in a window write none."""
    w, sink = World(), _Rows()
    w.registry.services.user_rebuilds.limit = 1
    w.registry.services.audit = sink
    with connect(w, offer) as c:
        c.sub(BOOK)  # the user's one draw
        for i, paused in enumerate((True, False)):  # the resume is refused, the first
            c.send({"t": "ctl", "id": f"k{i}", "ch": BOOK, "p": {"paused": paused}})
        assert [f["t"] for f in _until_pong(c) if f["t"] != "snap"] == ["ctl_ok", "err"]
        assert len(sink.rows) == 1  # written before the next frame was read
        c.send({"t": "resync", "id": "r0", "ch": BOOK, "p": {"reason": "manual"}})
        c.send({"t": "sub", "id": "s0", "p": {"topics": [{"ch": HEAT}]}})
        assert [f["t"] for f in _until_pong(c) if f["t"] != "snap"] == ["err", "sub_ok"]
        w.advance(c, 60.0)
        c.send({"t": "ctl", "id": "k2", "ch": BOOK, "p": {"paused": False}})  # draws the one
        c.send({"t": "resync", "id": "r1", "ch": BOOK, "p": {"reason": "manual"}})  # the first
        assert [f["t"] for f in _until_pong(c) if f["t"] != "snap"] == ["ctl_ok", "err"]
        assert len(sink.rows) == 2
        w.advance(c, 120.0)
        assert [r["ok"] for r in c.sub(HEAT)["p"]["results"]] == [True]
        assert [r["ok"] for r in c.sub("trades.BTCUSDT")["p"]["results"]] == [False]  # the first
    assert [(a, r["object_id"]) for a, r in sink.rows] == [
        ("ws.rebuild.refused", "book"),
        ("ws.rebuild.refused", "book"),
        ("ws.rebuild.refused", "trades"),
    ]
    assert {action for action, _ in sink.rows} <= AUDIT_ACTIONS  # the writer refuses others
    (_, row), *_ = sink.rows
    assert row == {
        "actor_label": "ws",
        "actor_user_id": USER,
        "object_kind": "ws_topic",
        "object_id": "book",
        "outcome": AuditOutcome.DENIED,
        "severity": Severity.WARNING,
        "reason": "user",
    }
