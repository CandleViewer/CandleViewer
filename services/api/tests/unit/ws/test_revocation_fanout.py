"""#2824: a permission-loss fan-out revokes every socket before it writes any audit row.

`ConnectionRegistry.roles_changed` (and `kill_switch_changed`) used to re-evaluate one socket at a
time and await that socket's `ws.subscription.revoked` rows before the next one, so socket k kept
its withdrawn subscriptions until the rows of sockets 1..k-1 were written: 7 s to the 8th socket of
8 x 200 at 5 ms per row (QA of E17-S02, #378). Every socket is now swapped and sent its frames
first; the rows follow one at a time, each bounded, and a failed row never stops the others.
A change that raises or is cancelled part-way still writes the row of every revocation that
happened, a swap that raises evicts only its own socket, closed before any send, and a lost row's
log line names its user (pre-PR reviews). Pure asyncio with event-gated sinks. The hung-row tests
wait out a 10 ms per-row bound, and only the `perf` budget test injects real latency.
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
from candleviewer.bars.errors import BarsError
from candleviewer.ws import limits, permissions
from candleviewer.ws.permissions import (
    ConnectionAuthz,
    ConnectionRegistry,
    SubscriptionServices,
    cv_ws_permission_snapshots_refused_total,
)

USER = uuid.UUID(int=0x2824)
PEER = uuid.UUID(int=0x2825)
THIRD = uuid.UUID(int=0x2826)
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


class _DroppedSeries:
    """`BarLeases` whose first release (each one, with `every`) raises `BarsError`, as
    `BarBuilderSet.release` does for a lease that another connection's failed build dropped with
    the shared series (#2735)."""

    def __init__(self, every: bool = False) -> None:
        self.released: list[str] = []
        self.every = every

    async def register(
        self, spec: Any, symbol: str, consumer: str, user: str | None = None
    ) -> None:
        return None

    def release(self, spec_hash: str, symbol: str, consumer: str) -> None:
        self.released.append(consumer)
        if self.every or len(self.released) == 1:
            raise BarsError("the series was dropped")


def _stuck(entered: asyncio.Event) -> Send:
    """A socket send that never returns: only a cancellation (or its 2 s bound) ends it."""

    async def send(_frame: dict[str, Any]) -> None:
        entered.set()
        await asyncio.Event().wait()

    return send


async def _poisoned(world: _World, every: bool = False) -> tuple[ConnectionAuthz, _DroppedSeries]:
    """A socket of USER whose three subscriptions each take a bar lease (tick bars start at 100)
    from a `_DroppedSeries`, so its first release (each, with `every`) and so its swap raises."""
    world.registry.services.bars = bars = _DroppedSeries(every)
    authz = world.connect(USER, [f"footprint.BTCUSDT.tick.{n}" for n in (100, 101, 102)])
    for sub in list(authz.by_id.values()):
        assert await authz.subscribe_upstream(sub) is None
    return authz, bars


class _World:
    """A registry over one `_Sink`: the principal each user resolves to, every socket's frames and
    the sockets closed (by index). `hold`, when set, parks the next read after it captured its
    principal."""

    def __init__(self, sink: _Sink) -> None:
        self.sink = sink
        self.principals: dict[uuid.UUID, PrincipalSnapshot] = {}
        self.frames: list[list[dict[str, Any]]] = []
        self.first_revoked: dict[int, float] = {}  # socket -> loop time of its first `revoked`
        self.closed: list[int] = []
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

        async def close() -> None:
            self.closed.append(index)

        self.registry.register(authz, send or record, close)
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
    assert (len(world.registry._conns[USER]), world.closed) == (1, [0])  # the first was evicted...
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
    assert [(e["log_level"], e["object_id"], e["actor_user_id"]) for e in lost] == [
        ("warning", "footprint.BTCUSDT.tick.2", USER),
        ("warning", "footprint.BTCUSDT.tick.1", USER),
    ]


async def test_cancelling_the_change_mid_audit_is_never_swallowed_and_logs_the_lost_rows() -> None:
    world = _World(_Sink(hang=frozenset({2})))
    sockets = []
    for uid in (USER, PEER):
        world.principals[uid] = _principal(uid, READ)
        sockets.append(world.connect(uid, _topics(3)))
        world.principals[uid] = _principal(uid, NONE)
    change = asyncio.create_task(world.registry.kill_switch_changed())
    async with asyncio.timeout(5):
        await world.sink.hung.wait()  # rows 0 and 1 are written; row 2 is in flight
    with capture_logs() as logs:
        change.cancel()
        with pytest.raises(asyncio.CancelledError):
            await change
    assert [len(frames) for frames in world.revoked()] == [3, 3]
    assert [len(s.by_id) for s in sockets] == [0, 0] and len(world.sink.rows) == 2
    # Rows 3-5 never reached the writer; row 2 was in flight (it lands if it held the WAL lock).
    (lost,) = [e for e in logs if e["event"] == "ws audit rows abandoned"]
    assert (lost["log_level"], lost["rows"], lost["cause"], lost["in_flight"]) == (
        "warning",
        3,
        "cancelled",
        "footprint.BTCUSDT.tick.3",
    )
    assert (lost["actor_user_ids"], lost["users"]) == ([USER, PEER], 2)  # row 2's user, then 3-5's


async def test_after_3_failed_audit_rows_in_a_row_the_rest_are_abandoned_and_counted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Row 0 fails, row 1 lands (ending that run), rows 2-4 fail in a row: 5-7 are never tried.
    monkeypatch.setattr(permissions, "_ABANDONED_USERS_LOGGED", 1)
    world = _World(_Sink(fail=frozenset({0, 3}), hang=frozenset({2, 4})))
    world.registry.audit_timeout_s = 0.01
    for uid, n in ((USER, 4), (PEER, 2), (THIRD, 2)):  # rows 0-3, 4-5 and 6-7
        world.principals[uid] = _principal(uid, READ)
        world.connect(uid, _topics(n))
        world.principals[uid] = _principal(uid, NONE)
    with capture_logs() as logs:
        async with asyncio.timeout(5):  # fail fast, not hang, if the bound regresses
            await world.registry.kill_switch_changed()
    assert world.sink.calls == 5 and [r["object_id"] for r in world.sink.rows] == _topics(2)[1:]
    lost = [e for e in logs if e["event"] == "ws audit not confirmed"]
    assert [e["object_id"] for e in lost] == [_topics(4)[n] for n in (0, 2, 3)] + _topics(1)
    assert [e["actor_user_id"] for e in lost] == [USER] * 3 + [PEER]  # whose row each one was
    (gone,) = [e for e in logs if e["event"] == "ws audit rows abandoned"]
    assert (gone["rows"], gone["cause"], gone["in_flight"]) == (3, "writer_down", None)
    assert (gone["actor_user_ids"], gone["users"]) == ([PEER], 2)  # PEER's and THIRD's: 1 named


def test_the_fan_out_audit_bounds_default_to_2s_a_row_and_3_failed_rows_in_a_row() -> None:
    registry = _World(_Sink()).registry
    assert registry.audit_timeout_s == limits.FANOUT_AUDIT_TIMEOUT_S == 2.0
    assert registry.audit_max_failures == limits.FANOUT_AUDIT_MAX_FAILURES == 3


# -- abnormal exits: a revocation that happened keeps its row --------------------------------------


async def test_a_raising_swap_evicts_its_socket_and_the_others_still_get_frames_and_rows() -> None:
    world = _World(_Sink())
    world.principals[USER] = _principal(USER, READ)
    sockets = [world.connect(USER, _topics(3))]
    poisoned, bars = await _poisoned(world)
    sockets += [poisoned, world.connect(USER, _topics(3))]
    world.principals[USER] = _principal(USER, NONE)
    with capture_logs() as logs:
        await world.registry.roles_changed(USER)  # contained: nothing is raised
    assert [len(frames) for frames in world.revoked()] == [3, 0, 3]
    assert [s.by_id for s in sockets] == [{}, {}, {}]  # nothing withdrawn stays live anywhere
    assert [e[0] for e in world.registry._conns[USER]] == [sockets[0], sockets[2]]
    assert (world.closed, len(bars.released)) == ([1], 3)  # evicted: closed, every lease released
    assert world.sink.rows == _revoked_rows(world)  # the other two sockets' rows, in order
    (failed,) = [e for e in logs if e["event"] == "ws permission swap failed; socket evicted"]
    assert (failed["log_level"], failed["connection_id"]) == ("error", poisoned.connection_id)


async def test_a_raising_logger_stops_neither_an_eviction_nor_the_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _BrokenLogger:
        def warning(self, *_args: Any, **_kw: Any) -> None:
            raise ValueError("log sink down")

        error = warning

    world = _World(_Sink(fail=frozenset({0, 2, 3, 4})))
    world.principals[USER] = _principal(USER, READ)
    poisoned, bars = await _poisoned(world, every=True)  # its swap and `release_all` both log
    after = world.connect(USER, _topics(6))
    world.principals[USER] = _principal(USER, NONE)
    monkeypatch.setattr(permissions, "_log", _BrokenLogger)
    await world.registry.roles_changed(USER)  # no failing log line is raised
    # Still evicted: every lease release tried, nothing kept, out of the registry and closed...
    assert (poisoned.by_id, len(bars.released), world.closed) == ({}, 3, [0])
    assert [e[0] for e in world.registry._conns[USER]] == [after]
    assert (after.by_id, len(world.revoked()[1])) == ({}, 6)  # ...and the socket after it swapped
    # Row 1 is still written after row 0 failed, and rows 2-4 failing in a row still end the writes.
    assert (world.sink.calls, [r["object_id"] for r in world.sink.rows]) == (5, _topics(6)[1:2])


@pytest.mark.parametrize("cancel", [False, True], ids=["send-raises", "cancelled-mid-send"])
async def test_a_change_ended_mid_send_still_closes_the_evicted_socket_and_writes_every_row(
    cancel: bool,
) -> None:
    world = _World(_Sink())
    world.principals[USER] = _principal(USER, READ)
    entered = asyncio.Event()

    async def broken(_frame: dict[str, Any]) -> None:
        raise ValueError("not a socket failure")  # unlike OSError: ends the change, as on main

    # The first socket's send raises, or is stuck when the change is cancelled; the second one's
    # swap raises, so it is evicted, before any send.
    sockets = [world.connect(USER, _topics(3), _stuck(entered) if cancel else broken)]
    sockets += [(await _poisoned(world))[0], world.connect(USER, _topics(3))]
    world.principals[USER] = _principal(USER, NONE)
    change = asyncio.create_task(world.registry.roles_changed(USER))
    raises = pytest.raises(ValueError, match="not a socket failure")
    with capture_logs() as logs, pytest.raises(asyncio.CancelledError) if cancel else raises:
        if cancel:
            async with asyncio.timeout(5):
                await entered.wait()  # the first send is stuck and no row is written yet
            change.cancel()
        await change
    assert [len(s.by_id) for s in sockets] == [0, 0, 0]  # all swapped before any send...
    assert [r["object_id"] for r in world.sink.rows] == _topics(3) * 2  # ...so they keep their rows
    assert world.closed == [1]  # and the evicted socket is closed on this exit too
    assert [e for e in logs if e["event"] == "ws audit rows abandoned"] == []


@pytest.mark.parametrize("cancel", [False, True], ids=["later-read-raises", "cancelled-mid-send"])
async def test_kill_switch_still_writes_every_swapped_users_rows_when_it_ends_early(
    cancel: bool,
) -> None:
    world = _World(_Sink())
    entered = asyncio.Event()
    for uid, send in ((USER, None), (PEER, _stuck(entered) if cancel else None)):
        world.principals[uid] = _principal(uid, READ)
        world.connect(uid, _topics(3), send)
        world.principals[uid] = _principal(uid, NONE)
    if not cancel:
        del world.principals[PEER]  # PEER's read raises (`StorePrincipalLoader` itself never does)
    change = asyncio.create_task(world.registry.kill_switch_changed())
    with pytest.raises(asyncio.CancelledError if cancel else KeyError):
        if cancel:
            async with asyncio.timeout(5):
                await entered.wait()  # USER is done; PEER is swapped and its send is stuck
            change.cancel()
        await change
    peer = [PEER] * 3 if cancel else []  # cancelled: PEER was swapped before its send
    assert [r["actor_user_id"] for r in world.sink.rows] == [USER] * 3 + peer


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
