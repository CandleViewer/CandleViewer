"""E17-T03 (#412, S2a-ii): the control-frame lane rule and the invalidation drops, flag on
(`23-ws-protocol.md` §8.4 Lanes, §9.5, §10.1). Control frames and `orders`, `executions` and
`system` frames ride the priority lane; one that ends or resets a subscription's stream drops what
the normal lane holds of it (`ConnectionAuthz.on_drop`). Router tests run the real `/ws` router
behind `_Wire`, a held send keeping the backlog queued; every wait is bounded, no sleeps.
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from collections.abc import AsyncIterator, Mapping
from typing import Any
from unittest.mock import Mock

import pytest

from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.scopes import AccountGrant
from candleviewer.ws import permissions
from candleviewer.ws.backpressure_config import BackpressureConfig
from candleviewer.ws.gateway import _Connection
from candleviewer.ws.metrics import cv_ws_malformed_updates_total
from candleviewer.ws.permissions import Subscription, VersionedSnapshot
from candleviewer.ws.sequencing import SnapReason, SnapshotBody
from tests.unit.ws._seq_support import ACC_A, ACC_B, USER, Conn, Source, principal
from tests.unit.ws.test_pipeline_ladder import _attached, _bid, _structured
from tests.unit.ws.test_pipeline_outbound import (
    _BOOK,
    _DEADLINE_S,
    _MARK,
    _PERMS,
    _counter,
    _d,
    _queued,
    _Rig,
    _Wire,
)
from tests.unit.ws.test_revocation_fanout import NONE, PEER, THIRD, _principal, _Sink, _World

_HEATMAP = "heatmap.BTCUSDT"
_RS = "bb000000-0000-4000-8000-000000000001"
_STRUCTURED = {"encoding": "structured"}


def _grants(*accounts: uuid.UUID) -> tuple[AccountGrant, ...]:
    return tuple(AccountGrant(account, True, False, False) for account in accounts)


def _both() -> dict[str, Any]:
    return {"ch": "positions", "opts": {"exchange_account_ids": [str(ACC_A), str(ACC_B)]}}


def _row(account: uuid.UUID, at: int = 1) -> dict[str, Any]:
    return {"id": f"p-{account}", "exchange_account_id": str(account), "updated_at_ms": at}


def _positions_rig(
    monkeypatch: pytest.MonkeyPatch, *accounts: uuid.UUID, flag: bool = True
) -> _Rig:
    """A rig whose user reads `positions` on `accounts`; a `positions` snapshot holds one row per
    account of the subscription as it is when it is built."""
    rig = _Rig(BackpressureConfig() if flag else None)
    rig.perms, rig.grants = _PERMS | {Permission.POSITIONS_READ}, _grants(*accounts)
    build = rig.source.build

    def by_account(sub: Subscription) -> SnapshotBody | None:
        if sub.topic.family.family != "positions":
            return build(sub)
        return SnapshotBody({"positions": [_row(a) for a in sorted(sub.accounts)]})

    monkeypatch.setattr(rig.source, "build", by_account)
    return rig


@contextlib.asynccontextmanager
async def _connected(rig: _Rig, sock: _Wire) -> AsyncIterator[_Connection]:
    """One connection past `auth_ok`, torn down on exit; every wait inside is bounded."""
    async with asyncio.timeout(_DEADLINE_S):
        handler, conn = await rig.open(sock)
        try:
            yield conn
        finally:
            handler.cancel()
            await asyncio.wait({handler})


async def _held(rig: _Rig, sock: _Wire) -> None:
    """Park the writer on one `system` frame: what is queued next waits behind it."""
    sock.hold()
    rig.hub.broadcast_system({"kind": "held"})
    await sock.parked.wait()


def _on_push(conn: _Connection, t: str, monkeypatch: pytest.MonkeyPatch) -> asyncio.Event:
    """Set once `conn` queues a frame of type `t`: the handler has finished what queued it."""
    pipe = conn.pipeline
    assert pipe is not None
    push, seen = pipe.push, asyncio.Event()

    def spy(frame: Mapping[str, Any], received: float | None = None) -> None:
        push(frame, received)
        if frame.get("t") == t:
            seen.set()

    monkeypatch.setattr(pipe, "push", spy)
    return seen


async def _released(sock: _Wire, conn: _Connection, n: int) -> list[dict[str, Any]]:
    """Let the held writer go: the `n` frames it sends, then nothing, sent or queued."""
    sock.release()
    frames = await sock.next(n)
    assert conn.pipeline is not None
    assert sock.sent.empty() and len(conn.pipeline.queue) == 0, "more than the expected frames"
    return frames


# -- order within the priority lane -------------------------------------------------------------


async def test_sub_ok_precedes_the_orders_snapshot() -> None:
    """§7.1 item 1, §8.4 Lanes: `sub_ok` and an `orders` snapshot share the priority lane."""
    rig, sock = _Rig(BackpressureConfig()), _Wire()
    async with _connected(rig, sock):
        frames = await rig.sub(sock, "orders")
    assert [(f["t"], f.get("ch")) for f in frames] == [("sub_ok", None), ("snap", "orders")]


async def test_permission_change_precedes_an_orders_revoked() -> None:
    """§8.4 Lanes, §9.5: `permission_change` precedes an `orders` `revoked`; an `orders` frame
    queued before them is delivered ahead of them, never dropped."""
    rig, sock = _Rig(BackpressureConfig()), _Wire()
    async with _connected(rig, sock) as conn:
        await rig.sub(sock, "orders")
        await _held(rig, sock)
        rig.sequencing.publish("orders", {"orders": []}, account=ACC_A)
        rig.perms = frozenset({Permission.MARKETDATA_READ})
        await rig.registry.roles_changed(USER)
        frames = await _released(sock, conn, 4)
    assert [(f["t"], f.get("ch")) for f in frames] == [
        ("d", "system"),
        ("d", "orders"),
        ("permission_change", None),
        ("revoked", "orders"),
    ]


async def test_pong_and_ctl_ok_overtake_queued_market_data(monkeypatch: pytest.MonkeyPatch) -> None:
    """§8.4 Lanes (D1): a `pong` and a `ctl_ok` that resets nothing overtake the queued deltas,
    which follow intact and in order."""
    rig, sock = _Rig(BackpressureConfig()), _Wire()
    async with _connected(rig, sock) as conn:
        await rig.sub(sock)
        await _held(rig, sock)
        for i in range(3):
            rig.book_delta(i)
        answered = _on_push(conn, "ctl_ok", monkeypatch)
        sock.feed({"t": "ping", "id": "p", "p": {"client_ms": 1}})
        sock.feed({"t": "ctl", "id": "c", "ch": _BOOK, "p": {"throttle_ms": 500}})
        await answered.wait()
        frames = await _released(sock, conn, 6)
    assert [f["t"] for f in frames] == ["d", "pong", "ctl_ok", "d", "d", "d"]
    assert [f["s"] for f in frames[3:]] == [2, 3, 4]


# -- what a control frame makes stale -------------------------------------------------------------


async def test_unsub_drops_the_topics_queued_frames_before_unsub_ok(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§8.4 Lanes, W10 (#3218): an `unsub` without `rs` ends the live subscription of a topic
    alone; `unsub_ok` overtakes its queued deltas, which go with it, and the replay one's follow."""
    rig, sock = _Rig(BackpressureConfig()), _Wire()
    async with _connected(rig, sock) as conn:
        await rig.sub(sock)
        entry = {"ch": _BOOK, "opts": _STRUCTURED}
        sock.feed({"t": "sub", "id": "r", "p": {"topics": [entry], "replay_session_id": _RS}})
        await sock.next(2)
        await _held(rig, sock)
        for i in range(3):
            rig.book_delta(i)
            rig.sequencing.publish(_BOOK, {"bids": [], "asks": []}, replay_session_id=_RS)
        answered = _on_push(conn, "unsub_ok", monkeypatch)
        sock.feed({"t": "unsub", "id": "u", "p": {"topics": [_BOOK]}})
        await answered.wait()
        frames = await _released(sock, conn, 5)
    replay = [("d", _BOOK, _RS)] * 3
    assert [(f["t"], f.get("ch"), f.get("rs")) for f in frames] == [
        ("d", "system", None),
        ("unsub_ok", None, None),
        *replay,
    ]


async def _heatmap_ctl(monkeypatch: pytest.MonkeyPatch, *, replay: bool) -> list[dict[str, Any]]:
    """Two deltas of `heatmap.BTCUSDT` queued (and two of a replay session's subscription to it),
    then a `ctl` that changes the live one's `time_bucket_ms`, a re-snapshot (§5.4)."""
    rig, sock = _Rig(BackpressureConfig()), _Wire()
    rig.source.bodies["heatmap"] = SnapshotBody({"symbol": "BTCUSDT", "columns": []})
    async with _connected(rig, sock) as conn:
        await rig.sub(sock, _HEATMAP)
        if replay:
            entry = {"ch": _HEATMAP, "opts": _STRUCTURED}
            sock.feed({"t": "sub", "id": "r", "p": {"topics": [entry], "replay_session_id": _RS}})
            await sock.next(2)
        await _held(rig, sock)
        for i in range(2):
            rig.clock.now += 1.0  # S3: past the 500 ms window, so each delta leaves at once
            rig.sequencing.publish(_HEATMAP, {"symbol": "BTCUSDT", "n": i})
            if replay:
                rig.sequencing.publish(_HEATMAP, {"n": i}, replay_session_id=_RS)
        snapped = _on_push(conn, "snap", monkeypatch)
        sock.feed({"t": "ctl", "id": "c", "ch": _HEATMAP, "p": {"time_bucket_ms": 1000}})
        await snapped.wait()
        return await _released(sock, conn, 5 if replay else 3)


async def test_ctl_resnapshot_drops_pre_ctl_deltas(monkeypatch: pytest.MonkeyPatch) -> None:
    """§8.4 Lanes: nothing of the old stream follows a re-snapshot's `ctl_ok`; its `snap` does."""
    frames = await _heatmap_ctl(monkeypatch, replay=False)
    assert [f["t"] for f in frames] == ["d", "ctl_ok", "snap"]
    assert frames[1]["p"]["resnapshot"] is True and frames[2]["meta"]["reason"] == "reconfigure"


async def test_replay_and_live_keys_drop_independently(monkeypatch: pytest.MonkeyPatch) -> None:
    """D13 (AC-28): a `ctl` re-snapshotting the live subscription drops its deltas only; the
    replay session's deltas of the same `ch` are all delivered, in order."""
    frames = await _heatmap_ctl(monkeypatch, replay=True)
    assert [(f["t"], f.get("rs")) for f in frames] == [
        ("d", None),
        ("ctl_ok", None),
        ("d", _RS),
        ("d", _RS),
        ("snap", None),
    ]


async def test_revoked_private_topic_gets_no_frame_after_revoked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """WS-E02, AC-13: the last account of a `positions` subscription is withdrawn while rows of it
    are queued: `permission_change` and `revoked` overtake them, and none of them follows."""
    rig, sock = _positions_rig(monkeypatch, ACC_A), _Wire()
    async with _connected(rig, sock) as conn:
        await rig.sub(sock, "positions", exchange_account_ids=[str(ACC_A)])
        await _held(rig, sock)
        for at in (1, 2):
            rig.sequencing.publish("positions", {"positions": [_row(ACC_A, at)]}, account=ACC_A)
        rig.grants = ()
        await rig.registry.grants_changed(USER)
        frames = await _released(sock, conn, 3)
    assert [f["t"] for f in frames] == ["d", "permission_change", "revoked"]
    revoked = frames[2]["p"]
    assert (revoked["removed_accounts"], revoked["resubscribe_allowed"]) == ([str(ACC_A)], False)


async def _narrowed(
    monkeypatch: pytest.MonkeyPatch, path: str
) -> tuple[list[dict[str, Any]], bool]:
    """`positions` on A and B, rows of both queued and a throttle window holding B's (and a book
    whose snapshot is pending); then B is withdrawn by a grant change or on an in-place re-`auth`.
    What follows the held frame, and whether the window outlived the narrowing."""
    rig, sock = _positions_rig(monkeypatch, ACC_A, ACC_B), _Wire()
    async with _connected(rig, sock) as conn:
        await rig.sub(sock, "positions", exchange_account_ids=[str(ACC_A), str(ACC_B)])
        assert conn.authz is not None and conn.pipeline is not None
        assert conn.pipeline.ladder is not None
        (sub,), pacer = conn.authz.by_id.values(), conn.pipeline.ladder.pacer
        rig.source.unavailable.add("BTCUSDT")  # a book whose snapshot is pending, then ready:
        sock.feed({"t": "sub", "id": "b", "p": {"topics": [{"ch": _BOOK, "opts": _STRUCTURED}]}})
        assert [f["t"] for f in await sock.next()] == ["sub_ok"]
        rig.source.unavailable.clear()  # not narrowed, so no settle may send it (§9.5)
        await _held(rig, sock)
        for account in (ACC_A, ACC_B):
            rig.sequencing.publish("positions", {"positions": [_row(account)]}, account=account)
        for at in (2, 3):  # both join the window that B's row from the hub opened
            pacer.offer(sub, {"positions": [_row(ACC_B, at)]})
        assert pacer.pending_bytes > 0
        rig.grants = _grants(ACC_A)
        if path == "grant_change":
            await rig.registry.grants_changed(USER)
        else:
            revoked = _on_push(conn, "revoked", monkeypatch)
            sock.feed({"t": "auth", "id": "a2", "p": {"access_token": "tok"}})
            await revoked.wait()
        window = sub.sub_id in pacer.lanes
        return (await _released(sock, conn, 4))[1:], window


@pytest.mark.parametrize("path", ["grant_change", "reauth"])
async def test_narrowing_delivers_no_row_of_a_removed_account_after_permission_change(
    path: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§9.5, WS-E02 (D2): no row of B follows the frame announcing the narrowing
    (`permission_change`, or `auth_ok` on a re-`auth`): B's queued rows and window went first."""
    frames, window = await _narrowed(monkeypatch, path)
    assert frames[0]["t"] == ("permission_change" if path == "grant_change" else "auth_ok")
    rows = [r for f in frames if f["t"] in ("d", "snap") for r in f["p"]["positions"]]
    assert rows and {r["exchange_account_id"] for r in rows} == {str(ACC_A)} and not window


@pytest.mark.parametrize("path", ["grant_change", "reauth"])
async def test_narrowing_re_pends_reconfigure_and_snapshots_after_revoked(
    path: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§9.5 (D2): the narrowed subscription goes on, re-pended `reconfigure`; its `snap`, built
    under the new scope (A's row only), is its next data frame, after `revoked`."""
    frames, _ = await _narrowed(monkeypatch, path)
    assert [f["t"] for f in frames[1:]] == ["revoked", "snap"]
    revoked, snap = frames[1]["p"], frames[2]
    assert (revoked["removed_accounts"], revoked["resubscribe_allowed"]) == ([str(ACC_B)], True)
    assert (snap["meta"]["reason"], snap["p"]["positions"]) == ("reconfigure", [_row(ACC_A)])


async def test_a_narrowed_paused_topic_snaps_on_resume(monkeypatch: pytest.MonkeyPatch) -> None:
    """§5.4, §8.4 step 1, §9.5: narrowing a paused subscription sends no `snap` and takes no
    sequence number; its resume answers with exactly one `reconfigure` snap, of A's row only."""
    rig, sock = _positions_rig(monkeypatch, ACC_A, ACC_B), _Wire()
    async with _connected(rig, sock) as conn:
        await rig.sub(sock, "positions", exchange_account_ids=[str(ACC_A), str(ACC_B)])
        sock.feed({"t": "ctl", "id": "p", "ch": "positions", "p": {"paused": True}})
        assert [f["t"] for f in await sock.next()] == ["ctl_ok"]
        rig.grants = _grants(ACC_A)
        await rig.registry.grants_changed(USER)
        sock.feed({"t": "ctl", "id": "r", "ch": "positions", "p": {"paused": False}})
        frames = await sock.next(4)
        assert conn.pipeline is not None and sock.sent.empty() and len(conn.pipeline.queue) == 0
    assert [f["t"] for f in frames] == ["permission_change", "revoked", "ctl_ok", "snap"]
    meta, rows = frames[3]["meta"], frames[3]["p"]["positions"]  # `s` 2: none taken while paused
    assert (meta["reason"], meta["previous_seq"], rows) == ("reconfigure", 1, [_row(ACC_A)])


@pytest.mark.parametrize(("family", "end"), [("positions", "snap"), ("orders", "bye")])
async def test_a_snapshot_that_raises_after_a_narrowing_is_contained_to_its_topic(
    family: str, end: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§10.1 (S3): a narrowed subscription's `reconfigure` snapshot that raises never reaches the
    registry's fan-out, so the user's other connection gets the change too. A droppable topic
    drops to its `backpressure` snapshot (parked and retried on the drain cadence), built under
    the new scope, the connection open; `orders`, never dropped, closes it `internal_error`."""
    rig, socks = _positions_rig(monkeypatch, ACC_A, ACC_B), [_Wire(), _Wire()]
    build = rig.source.build
    async with asyncio.timeout(_DEADLINE_S):
        handlers = []
        for sock in socks:
            handlers.append((await rig.open(sock))[0])
            await rig.sub(sock, family, exchange_account_ids=[str(ACC_A), str(ACC_B)])

        def raises(sub: Subscription) -> SnapshotBody | None:
            raise RuntimeError(_MARK)

        monkeypatch.setattr(rig.source, "build", raises)
        rig.grants = _grants(ACC_A)
        await rig.registry.grants_changed(USER)
        monkeypatch.setattr(rig.source, "build", build)
        rig.clock.now += 1.0  # the drain's retry pass is due, if it had parked the snapshot
        ends = [await sock.next(3) for sock in socks]
        for handler in handlers:
            handler.cancel()
        await asyncio.wait(handlers)
    assert [[f["t"] for f in frames] for frames in ends] == [
        ["permission_change", "revoked", end]
    ] * 2
    if family == "orders":
        assert [sock.closed_with for sock in socks] == [1011, 1011]
    else:
        snaps = [frames[2] for frames in ends]
        assert [(f["meta"]["reason"], f["p"]["positions"]) for f in snaps] == [
            ("backpressure", [_row(ACC_A)])
        ] * 2


async def test_an_on_settle_that_raises_evicts_only_its_socket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C-2.18: an `on_settle` that raises evicts its socket, though the logger raises too (#3193
    round 2); the users after it still get theirs."""
    world = _World(_Sink())
    world.principals = {uid: _principal(uid, _PERMS) for uid in (PEER, THIRD)}
    first, _ = (world.connect(uid, ["trades.BTCUSDT"]) for uid in (PEER, THIRD))
    first.on_settle = Mock(side_effect=RuntimeError(_MARK))
    monkeypatch.setattr(permissions, "_log", Mock(side_effect=RuntimeError(_MARK)))
    world.principals = {uid: _principal(uid, NONE) for uid in (PEER, THIRD)}
    await world.registry.kill_switch_changed()
    assert [len(f) for f in world.revoked()] == [1, 1] and world.closed == [0]


async def test_flag_off_narrowing_stays_in_place(monkeypatch: pytest.MonkeyPatch) -> None:
    """§9.5, C-4.14 flag off: a narrowed subscription goes on in place, not re-snapshotted, and
    neither a grant change nor a re-`auth` sends a snapshot that was pending (a book whose source
    became ready meanwhile)."""
    rig, sock = _positions_rig(monkeypatch, ACC_A, ACC_B, flag=False), _Wire()
    async with _connected(rig, sock) as conn:
        await rig.sub(sock, "positions", exchange_account_ids=[str(ACC_A), str(ACC_B)])
        rig.source.unavailable.add("BTCUSDT")
        sock.feed({"t": "sub", "id": "b", "p": {"topics": [{"ch": _BOOK, "opts": _STRUCTURED}]}})
        assert [f["t"] for f in await sock.next()] == ["sub_ok"]  # its snapshot is not ready
        rig.source.unavailable.clear()  # ready now: only a flush would send it
        rig.grants = _grants(ACC_A)
        await rig.registry.grants_changed(USER)
        rig.sequencing.publish("positions", {"positions": [_row(ACC_A, 2)]}, account=ACC_A)
        sock.feed({"t": "auth", "id": "a2", "p": {"access_token": "tok"}})
        frames = await sock.next(4)
        assert sock.sent.empty() and conn.outbound.empty()
    assert [f["t"] for f in frames] == ["permission_change", "revoked", "d", "auth_ok"]
    assert frames[2]["p"]["positions"] == [_row(ACC_A, 2)]  # the narrowed stream goes on


# -- the pipeline and the hook --------------------------------------------------------------------


async def test_invalidation_drops_the_normal_lane_frames_only() -> None:
    """§8.4 Lanes, §9.5: the hook drops what the normal lane holds of its subscriptions, and
    their windows. Their priority-lane frames (`orders`, ahead of the control frame), control
    frames (`revoked`, `ctl_ok`) and other subscriptions' frames and windows stay."""
    pipe, _, conn = _attached()
    book, eth = _structured(conn, _BOOK), _structured(conn, "book.ETHUSDT.50")
    _, orders = conn.authz.admit({"ch": "orders", "opts": {"exchange_account_ids": [str(ACC_A)]}})
    assert orders is not None and pipe.ladder is not None
    _queued(pipe)
    pacer = pipe.ladder.pacer
    for i in range(2):  # the first leaves at once, the second waits in the window
        pacer.offer(book, _bid(i))
        pacer.offer(eth, _bid(i) | {"symbol": "ETHUSDT"})
    pipe.push(_d("orders", n=1))
    pipe.push({"t": "revoked", "ch": _BOOK, "ts": 1, "p": {"reason": "permission_revoked"}})
    pipe.push({"t": "ctl_ok", "ch": _BOOK, "ts": 1, "p": {"effective": {}}})
    hook = conn.authz.on_drop  # `attach` set it
    assert hook is not None
    hook([book, orders])
    assert [(f["t"], f["ch"]) for f in _queued(pipe)] == [
        ("d", "orders"),
        ("revoked", _BOOK),
        ("ctl_ok", _BOOK),
        ("d", "book.ETHUSDT.50"),
    ]
    assert book.sub_id not in pacer.lanes and eth.sub_id in pacer.lanes


@pytest.mark.parametrize("refused", ["middle", "last"])
async def test_a_chunk_that_cannot_be_encoded_drops_its_set_and_the_topic_recovers(
    refused: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§10.1 with §3.6, §7.2: a refused chunk drops its topic like any droppable frame. The chunks
    queued before it go with the topic's queued frames, the rest of its set is never queued, and
    the topic is held for the ladder's `backpressure` snapshot, a new set under a new `id`."""
    pipe, asked, conn = _attached(50, max_frame_bytes=450)
    book = _structured(conn, _BOOK)
    assert len(_queued(pipe)) >= 3  # its initial snapshot: a set of three chunks or more
    conn.emitter.delta(book, _bid(0))
    encoded: list[dict[str, Any]] = []
    dumps = pipe._dumps

    def refuse_one(frame: Mapping[str, Any]) -> str | bytes:
        encoded.append(dict(frame))
        last = frame["s"] is not None and frame["meta"]["reason"] == "client_resync"
        if len(encoded) == 2 if refused == "middle" else last:
            raise ValueError("refused")
        return dumps(frame)

    monkeypatch.setattr(pipe, "_dumps", refuse_one)
    malformed = _counter(cv_ws_malformed_updates_total, topic="book")
    assert conn.emitter.snapshot(book, "client_resync")  # it pushed every chunk: it cannot tell
    chunks = [f["s"] is None for f in encoded]
    assert chunks == ([True, True] if refused == "middle" else [True] * (len(chunks) - 1) + [False])
    assert (len(pipe.queue), book.pending_reason, asked) == (0, "backpressure", [])
    assert pipe.queue.ready.is_set() and pipe._skips == {}  # the writer is woken to drain it
    assert _counter(cv_ws_malformed_updates_total, topic="book") == malformed + 1
    pipe.service(0.0)  # the writer's turn: the ladder's `drain`
    again = _queued(pipe)
    assert len(again) >= 3 and again[-1]["meta"]["reason"] == "backpressure"
    assert len({f["id"] for f in again}) == 1 and again[0]["id"] != encoded[0]["id"]


async def test_an_unencodable_frame_of_no_subscription_fails_closed() -> None:
    """§10.1: after `attach`, a refused `d` of an unsubscribed throttled topic fails closed."""
    pipe, asked, _ = _attached()
    pipe.push(_d("trades.ETHUSDT", x=float("nan")))
    assert asked == ["internal_error"] and len(pipe.queue) == 0


async def test_on_drop_fires_once_per_operation_with_every_stale_subscription() -> None:
    """§8.4 Lanes, §9.5 (every site, design risk 2): once per operation, before its reply, with
    every subscription it made stale, never for a `ctl` that resets nothing. A narrowing passes
    the dropped and the narrowed together, the narrowed before its re-pend (§9.5)."""
    conn = Conn(Source(), ACC_A, ACC_B)
    authz, calls = conn.authz, list[list[tuple[str, str | None, bool]]]()
    authz.on_drop = lambda subs: calls.append(
        [(s.ch, s.replay_session_id, s.snapshot_pending) for s in subs]
    )

    def admit(entry: dict[str, Any], **kw: Any) -> Subscription:
        result, sub = authz.admit(entry, **kw)
        assert sub is not None, result
        sub.snapshot_pending = False
        return sub

    admit({"ch": _BOOK, "opts": _STRUCTURED})
    admit({"ch": _BOOK, "opts": _STRUCTURED}, replay_session_id=_RS)
    authz.ctl(_BOOK, {"throttle_ms": 500})
    assert calls == []
    assert authz.unsubscribe(_BOOK) and calls == [[(_BOOK, None, False)]]  # W10: the live one
    assert authz.unsubscribe(_BOOK, _RS) and calls[1:] == [[(_BOOK, _RS, False)]]
    heatmap = admit({"ch": _HEATMAP, "opts": _STRUCTURED})
    authz.ctl(_HEATMAP, {"time_bucket_ms": 1000})
    authz.revoke(heatmap, "resync_rate_limited", 1)
    assert calls[2:] == [[(_HEATMAP, None, True)]] * 2
    authz.services.bars_off = True  # any refusal of a `sub`'s upstream (one exit for all)
    bars = admit({"ch": "bars.BTCUSDT.time.1"})
    assert (await authz.subscribe_upstream(bars) or {"ok": True})["ok"] is False
    assert calls[4:] == [[("bars.BTCUSDT.time.1", None, False)]]
    admit(_both())
    admit({"ch": "orders", "opts": {"exchange_account_ids": [str(ACC_B)]}})
    admit({"ch": "trades.BTCUSDT", "opts": _STRUCTURED})
    assert authz.apply_snapshot(VersionedSnapshot(principal(ACC_A), 1), 9) is not None
    assert calls[5:] == [[("orders", None, False), ("positions", None, False)]]
    authz.release_all()
    assert calls[6:] == [[("positions", None, True), ("trades.BTCUSDT", None, False)]]


@pytest.mark.parametrize("pending", [None, "client_resync"])
def test_a_narrowing_re_pends_reconfigure_while_the_hook_is_set(pending: SnapReason | None) -> None:
    """§9.5 flag on: a narrowed subscription is re-pended `reconfigure`, unless another reason is
    already pending (§5.4), which stays."""
    conn = Conn(Source(), ACC_A, ACC_B)
    conn.authz.on_drop = lambda subs: None
    _, sub = conn.authz.admit(_both())
    assert sub is not None
    sub.snapshot_pending, sub.pending_reason = pending is not None, pending or "initial"
    conn.authz.apply_snapshot(VersionedSnapshot(principal(ACC_A), 1), 9)
    assert (sub.accounts, sub.snapshot_pending) == (frozenset({ACC_A}), True)
    assert sub.pending_reason == (pending or "reconfigure")
