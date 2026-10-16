"""#2824: a permission-loss fan-out revokes every socket before it writes any audit row.

`ConnectionRegistry.roles_changed` (and `kill_switch_changed`) used to re-evaluate one socket at a
time and await that socket's `ws.subscription.revoked` rows before the next one, so socket k kept
its withdrawn subscriptions until the rows of sockets 1..k-1 were written: 7 s to the 8th socket of
8 x 200 at 5 ms per row (QA of E17-S02, #378). Every socket is now swapped and sent its frames
first; the rows follow one at a time, each bounded, and a failed row never stops the others.
Pure asyncio with event-gated sinks. The hung-row test waits out a 10 ms per-row bound, and only
the `perf` budget test injects real latency.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from structlog.testing import capture_logs

from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.scopes import AccountGrant, PrincipalSnapshot
from candleviewer.ws import limits
from candleviewer.ws.permissions import (
    ConnectionAuthz,
    ConnectionRegistry,
    SubscriptionServices,
    cv_ws_permission_snapshots_refused_total,
)

USER = uuid.UUID(int=0x2824)
PEER = uuid.UUID(int=0x2825)
A = uuid.UUID(int=0xA)
B = uuid.UUID(int=0xB)
SOCKETS, SUBS = 8, 200  # the issue's scenario: 8 connections x 200 subscriptions
READ = frozenset({Permission.MARKETDATA_READ, Permission.ORDERS_READ, Permission.POSITIONS_READ})
NONE: frozenset[Permission] = frozenset()  # every permission withdrawn
Send = Callable[[dict[str, Any]], Awaitable[None]]


def _principal(
    uid: uuid.UUID, perms: frozenset[Permission], *accounts: uuid.UUID
) -> PrincipalSnapshot:
    grants = tuple(AccountGrant(a, True, False, False) for a in accounts)
    return PrincipalSnapshot(uid, frozenset({"manager"}), perms, grants)


def _topics(n: int) -> list[str]:
    """`n` public topics on one symbol (the 40-symbol cap is a separate limit). Footprint, not
    the issue's `bars.*`: that family has its own 16-per-connection cap (SR-E12-07)."""
    return [f"footprint.BTCUSDT.tick.{i}" for i in range(1, n + 1)]


def _mixed() -> list[Any]:
    """One revocation of each kind once A stays, B goes and market data is withdrawn."""
    return [
        {"ch": "positions", "opts": {"exchange_account_ids": [str(A), str(B)]}},
        {"ch": "orders", "opts": {"exchange_account_ids": [str(B)]}},
        "trades.BTCUSDT",
    ]


class _Sink:
    """Audit sink recording each row. A write waits for `release` (already set unless `gated`),
    sleeps `latency_s` (the perf budget only), then write number n raises if n is in `fail` and
    never returns if n is in `hang` (setting `hung`). Counts the writes in flight."""

    def __init__(
        self,
        *,
        gated: bool = False,
        latency_s: float = 0.0,
        fail: frozenset[int] = frozenset(),
        hang: frozenset[int] = frozenset(),
    ) -> None:
        self.rows: list[dict[str, Any]] = []
        self.started, self.release, self.hung = asyncio.Event(), asyncio.Event(), asyncio.Event()
        if not gated:
            self.release.set()
        self.latency_s, self.fail, self.hang = latency_s, fail, hang
        self.calls = self.in_flight = self.max_in_flight = 0

    async def emit(self, action: str, **kw: Any) -> None:
        call, self.calls = self.calls, self.calls + 1
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        self.started.set()
        try:
            await self.release.wait()
            if self.latency_s:
                await asyncio.sleep(self.latency_s)
            if call in self.hang:
                self.hung.set()
                await asyncio.Event().wait()  # never returns: only the per-row bound ends it
            if call in self.fail:
                raise RuntimeError("audit sink down")
        finally:
            self.in_flight -= 1
        self.rows.append({"action": action, **kw})


class _World:
    """A registry over one `_Sink`: the principal each user resolves to and every socket's frames.
    `hold`, when set, parks the next read after it captured its principal."""

    def __init__(self, sink: _Sink) -> None:
        self.sink = sink
        self.principals: dict[uuid.UUID, PrincipalSnapshot] = {}
        self.frames: list[list[dict[str, Any]]] = []
        self.first_revoked: dict[int, float] = {}  # socket -> loop time of its first `revoked`
        self.hold: asyncio.Event | None = None
        self.held = asyncio.Event()
        services = SubscriptionServices(audit=sink)
        self.registry = ConnectionRegistry(self.resolve, lambda: 42, services)

    async def resolve(self, uid: uuid.UUID) -> PrincipalSnapshot:
        snapshot = self.principals[uid]
        if (hold := self.hold) is not None:
            self.hold = None
            self.held.set()
            await hold.wait()
        return snapshot

    def connect(
        self, uid: uuid.UUID, topics: list[Any], send: Send | None = None
    ) -> ConnectionAuthz:
        authz = ConnectionAuthz(self.principals[uid], self.registry.services)
        for topic in topics:
            assert authz.admit(topic)[1] is not None
        index, frames = len(self.frames), list[dict[str, Any]]()
        self.frames.append(frames)

        async def record(frame: dict[str, Any]) -> None:
            if frame["t"] == "revoked" and index not in self.first_revoked:
                self.first_revoked[index] = asyncio.get_running_loop().time()
            frames.append(frame)

        self.registry.register(authz, send or record)
        return authz

    def revoked(self) -> list[list[dict[str, Any]]]:
        """Each socket's `revoked` frames, in the order it got them."""
        return [[f for f in frames if f["t"] == "revoked"] for frames in self.frames]


def _revoked_rows(world: _World) -> list[dict[str, Any]]:
    """The `ws.subscription.revoked` row each `revoked` frame needs: socket, then frame order."""
    return [
        {
            "action": "ws.subscription.revoked",
            "actor_label": "ws",
            "actor_user_id": USER,
            "object_kind": "ws_topic",
            "object_id": f["ch"],
            "reason": f["p"]["reason"],
            "after_state": {"removed_accounts": f["p"].get("removed_accounts", [])},
        }
        for frames in world.revoked()
        for f in frames
    ]


# -- ordering: frames first, rows after (the defect) -----------------------------------------------


async def test_roles_changed_revokes_every_socket_before_any_audit_row_is_written() -> None:
    world = _World(_Sink(gated=True))
    world.principals[USER] = _principal(USER, READ)
    sockets = [world.connect(USER, _topics(SUBS)) for _ in range(SOCKETS)]
    world.principals[USER] = _principal(USER, NONE)
    change = asyncio.create_task(world.registry.roles_changed(USER))
    try:
        async with asyncio.timeout(5):  # fail fast, not hang, if no row is ever written
            await world.sink.started.wait()
        # The first row is held: every socket already lost its subscriptions and has its frames.
        assert [len(frames) for frames in world.revoked()] == [SUBS] * SOCKETS
        assert [len(s.by_id) for s in sockets] == [0] * SOCKETS
        assert (world.sink.rows, world.sink.in_flight) == ([], 1)
    finally:
        world.sink.release.set()
        await change
    assert world.sink.rows == _revoked_rows(world)  # one row per frame, socket then frame order
    assert world.sink.max_in_flight == 1  # one row at a time (see `_write_rows`)


async def test_kill_switch_revokes_every_users_sockets_before_any_audit_row_is_written() -> None:
    world = _World(_Sink(gated=True))
    for uid in (USER, PEER):
        world.principals[uid] = _principal(uid, READ)
    for uid in (USER, USER, PEER, PEER):
        world.connect(uid, _topics(3))
    for uid in (USER, PEER):
        world.principals[uid] = _principal(uid, NONE)
    change = asyncio.create_task(world.registry.kill_switch_changed())
    try:
        async with asyncio.timeout(5):
            await world.sink.started.wait()
        assert [len(frames) for frames in world.revoked()] == [3] * 4  # both users, every socket
    finally:
        world.sink.release.set()
        await change
    assert [r["actor_user_id"] for r in world.sink.rows] == [USER] * 6 + [PEER] * 6


async def test_a_stalled_send_never_delays_another_sockets_revocation() -> None:
    world = _World(_Sink())
    world.principals[USER] = _principal(USER, READ)
    entered, unblock = asyncio.Event(), asyncio.Event()

    async def stalled(_frame: dict[str, Any]) -> None:
        entered.set()
        await unblock.wait()
        raise OSError("socket gone")  # evicted after its first frame

    first = world.connect(USER, _topics(3), stalled)
    second = world.connect(USER, _topics(3))
    world.principals[USER] = _principal(USER, NONE)
    change = asyncio.create_task(world.registry.roles_changed(USER))
    try:
        async with asyncio.timeout(5):
            await entered.wait()  # the first socket's send is stuck...
        assert (first.by_id, second.by_id) == ({}, {})  # ...and both already lost every topic
    finally:
        unblock.set()
        await change
    assert [len(frames) for frames in world.revoked()] == [0, 3]  # `stalled` records nothing
    assert len(world.registry._conns[USER]) == 1  # the first socket was evicted...
    assert len(world.sink.rows) == 6  # ...and its revocations were still audited


# -- C-2.9: every revocation still gets its row ----------------------------------------------------


async def test_every_revoked_frame_gets_exactly_one_audit_row_in_socket_then_frame_order() -> None:
    world = _World(_Sink())
    world.principals[USER] = _principal(USER, READ, A, B)
    for _ in range(3):
        world.connect(USER, _mixed())
    world.principals[USER] = _principal(USER, READ - {Permission.MARKETDATA_READ}, A)
    await world.registry.grants_changed(USER)
    assert world.sink.rows == _revoked_rows(world) and len(world.sink.rows) == 9
    assert [(r["object_id"], r["reason"], r["after_state"]) for r in world.sink.rows[:3]] == [
        ("orders", "account_scope_changed", {"removed_accounts": [str(B)]}),
        ("positions", "account_scope_changed", {"removed_accounts": [str(B)]}),
        ("trades.BTCUSDT", "permission_revoked", {"removed_accounts": []}),
    ]


async def test_a_failed_or_hung_audit_row_never_stops_the_other_rows_or_the_fan_out() -> None:
    world = _World(_Sink(fail=frozenset({1}), hang=frozenset({3})))
    world.registry.audit_timeout_s = 0.01
    world.principals[USER] = _principal(USER, READ)
    for _ in range(2):
        world.connect(USER, _topics(3))
    world.principals[USER] = _principal(USER, NONE)
    with capture_logs() as logs:
        async with asyncio.timeout(5):  # fail fast, not hang, if the per-row bound regresses
            await world.registry.roles_changed(USER)  # never raises into the fan-out
    assert [len(frames) for frames in world.revoked()] == [3, 3]
    assert world.sink.calls == 6  # every row was attempted
    tick = [f"footprint.BTCUSDT.tick.{n}" for n in (1, 3, 2, 3)]  # rows 1 and 3 are lost
    assert [r["object_id"] for r in world.sink.rows] == tick
    lost = [e for e in logs if e["event"] == "ws audit not confirmed"]
    assert [(e["log_level"], e["object_id"]) for e in lost] == [
        ("warning", "footprint.BTCUSDT.tick.2"),
        ("warning", "footprint.BTCUSDT.tick.1"),
    ]


async def test_cancelling_the_change_mid_audit_is_never_swallowed_and_logs_the_lost_rows() -> None:
    world = _World(_Sink(hang=frozenset({2})))
    world.principals[USER] = _principal(USER, READ)
    sockets = [world.connect(USER, _topics(3)) for _ in range(2)]
    world.principals[USER] = _principal(USER, NONE)
    change = asyncio.create_task(world.registry.roles_changed(USER))
    async with asyncio.timeout(5):
        await world.sink.hung.wait()  # rows 0 and 1 are written; row 2 is in flight
    with capture_logs() as logs:
        change.cancel()
        with pytest.raises(asyncio.CancelledError):
            await change
    assert [len(frames) for frames in world.revoked()] == [3, 3]
    assert [len(s.by_id) for s in sockets] == [0, 0] and len(world.sink.rows) == 2
    (lost,) = [e for e in logs if e["event"] == "ws audit rows abandoned"]
    assert (lost["log_level"], lost["rows"]) == ("warning", 4)


def test_each_fan_out_audit_row_is_bounded_by_2s_by_default() -> None:
    assert _World(_Sink()).registry.audit_timeout_s == limits.FANOUT_AUDIT_TIMEOUT_S == 2.0


# -- SR-189: a newer snapshot is never undone ------------------------------------------------------


async def test_a_stale_fan_out_is_refused_on_every_socket_and_never_undoes_the_newer_one() -> None:
    world = _World(_Sink())
    world.principals[USER] = _principal(USER, READ, A, B)
    sockets = [world.connect(USER, _mixed()) for _ in range(3)]
    world.hold = resume = asyncio.Event()
    stale = asyncio.create_task(world.registry.grants_changed(USER))  # version 1 reads A and B
    async with asyncio.timeout(5):
        await world.held.wait()
    world.principals[USER] = _principal(USER, READ, A)  # B withdrawn: version 2 lands first
    await world.registry.grants_changed(USER)
    refused = cv_ws_permission_snapshots_refused_total.labels(event="grant_change")
    before = refused._value.get()
    resume.set()
    await stale
    assert refused._value.get() - before == 3
    for s in sockets:
        assert (s.version, s.subs) == (2, {("positions", A), ("trades.BTCUSDT", None)})
    assert [[f["t"] for f in frames] for frames in world.frames] == [
        ["permission_change", "revoked", "revoked"]  # the stale change sent nothing
    ] * 3
    rows = world.sink.rows
    assert [r["action"] for r in rows] == ["ws.subscription.revoked"] * 6 + [
        "ws.permission_snapshot.refused"
    ] * 3
    assert rows[6:] == [
        {
            "action": "ws.permission_snapshot.refused",
            "actor_label": "ws",
            "actor_user_id": USER,
            "object_kind": "ws_connection",
            "object_id": s.connection_id,
            "outcome": AuditOutcome.DENIED,
            "severity": Severity.WARNING,
            "reason": "stale",
            "after_state": {"event": "grant_change", "applied_version": 2, "refused_version": 1},
        }
        for s in sockets
    ]


# -- the issue's budget (#378 Performance notes), wall clock ---------------------------------------


@pytest.mark.perf
async def test_perf_8_sockets_x_200_subscriptions_are_revoked_within_1s_at_2ms_per_row() -> None:
    """Every socket's first `revoked` frame lands within 1 s of the change while each audit row
    takes 2 ms (1 600 rows, so 3.2 s of rows in all). Wall time: the latency is real."""
    world = _World(_Sink(latency_s=0.002))
    world.principals[USER] = _principal(USER, READ)
    for _ in range(SOCKETS):
        world.connect(USER, _topics(SUBS))
    world.principals[USER] = _principal(USER, NONE)
    t0 = asyncio.get_running_loop().time()
    await world.registry.roles_changed(USER)
    assert len(world.first_revoked) == SOCKETS
    assert max(world.first_revoked.values()) - t0 < 1.0
    assert len(world.sink.rows) == SOCKETS * SUBS
