"""`ReplaySessionService`: the replay session lifecycle on the B12 `replay` chart (E26-T01 3/3).

The chart *is* the lifecycle (C-2.19): interpreters are built only by
`statechart.factory.build("replay")` or restored only through `statechart.persistence`, every event
goes through `statechart.gateway`, and legality is whatever B12 handles (28 §B12.3). Statecharts
record, synchronous code enforces (C-2.21): the per-user quota, the window cap, the coverage check,
payload validation and the paper-account grant run here before anything is sent, and an event the
settled chart does not handle is refused with `can()` before sending (CV-C06) as
`ReplaySessionIllegalUpdateError` (HTTP 409). A send that still races an invoke completion and is
held by the chart (`onUnhandled: "defer"`) is refused and counted as well (`_send_replay`).

Row mirror (24 §13.7): `replay_sessions.state` takes every chart state. B12 declares entry actions
only on `playing`, so the row follows the interpreter's state-entry notification (`subscribe`):
written before a control call returns, and by one tracked mirror task for invoke completions that
arrive later. The bindings publish plain values through a per-interpreter hook; the service audits
`error` from it. Idle reclaim and client destroy both send `DESTROY` (#624 decision): `destroyed` is
the only final state, so the paper account and source handles are released exactly once
(INV-B12-e) and a second destroy is a no-op.

M12 may not import `recorder`, `audit` or `paper` (CONSTITUTION §3): coverage, audit, the paper
account grant and the session handles are ports the composition root injects.
"""

from __future__ import annotations

import asyncio
import contextlib
import re
import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Final, Protocol, cast

import structlog

import candleviewer.statechart.bindings.b12_replay as b12
from candleviewer.observability.context import spawn
from candleviewer.replay.errors import ReplayError
from candleviewer.statechart import build
from candleviewer.statechart.config import Lane
from candleviewer.statechart.factory import default_clock
from candleviewer.statechart.factory import restore as restore_chart
from candleviewer.statechart.gateway import Gateway, receipt_is_conclusive
from candleviewer.statechart.persistence import (
    MachineKey,
    Persister,
    Restorer,
    RestoreRefusedError,
    SealedSnapshot,
)
from candleviewer.storage.repositories.replay_sessions import (
    LIVE_STATES,
    MAX_PAGE_LIMIT,
    ReplaySessionCreate,
    ReplaySessionIllegalUpdateError,
    ReplaySessionNotFoundError,
    ReplaySessionRepository,
    ReplaySessionRow,
    ReplayState,
)

MACHINE: Final = "replay"
LANE: Final[Lane] = "control"
#: Await each event's macrostep so a failed step surfaces to the caller. Safe: sends come only
#: from this service's entry points and tasks, never from a B12 action (the hook never sends),
#: so the CV-C51 self-receipt hang cannot arise (same pattern as `rules.lifecycle`).
_AWAIT_STEP: Final = True
_SETTLE_YIELDS: Final = 64
_IO_TIMEOUT_S: Final = 10.0
#: Actor of chart-observed rows (`replay.session.error`): the chart, not a user or the reclaimer.
_CHART_ACTOR: Final = "system:replay-chart"
#: Actor of `replay.session.destroyed{reason=idle_reclaim}`.
_RECLAIM_ACTOR: Final = "system:replay-reclaimer"
_SYMBOL: Final = re.compile(r"[A-Z0-9]{4,20}")
_EPOCH: Final = datetime(1970, 1, 1, tzinfo=UTC)
#: Events a caller may name and the payload keys each takes. `DESTROY` has its own entry point;
#: `KILL` belongs to the kill switch. The last three come from the replay clock (E26-T03/E36).
_EVENTS: Final[dict[str, frozenset[str]]] = {
    "PREPARE": frozenset(), "PLAY": frozenset(), "PAUSE": frozenset(), "STEP": frozenset(),
    "CANCEL": frozenset(), "SEEK": frozenset({"cursor"}), "SET_SPEED": frozenset({"speed"}),
    "RANGE_END": frozenset(), "CONSUMER_SLOW": frozenset(), "SOURCE_ERROR": frozenset({"error"}),
}  # fmt: skip
_SOURCE_EVENTS: Final = frozenset({"RANGE_END", "CONSUMER_SLOW", "SOURCE_ERROR"})
_REASONS: Final = frozenset({"client", "idle_reclaim"})
#: States with an invoked service (`seek`, `step`) whose completion arrives later (B12.4).
_INVOKING: Final = frozenset({"buffering", "stepping"})


def logger() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


class ReplaySessionValidationError(ReplayError, ValueError):
    """A human-readable request error, raised before the database or the chart (HTTP 422)."""


class ReplayQuotaExceededError(ReplayError):
    """The user already holds `CV_REPLAY_MAX_SESSIONS_PER_USER` open sessions; nothing allocated."""


class ReplayWindowUncoveredError(ReplayError):
    """No recorded coverage in the window (`no_data_recorded`, HTTP 422); nothing allocated."""


class ReplayChartError(ReplayError):
    """B12 failed to record an accepted event (an action raised and the step was rolled back)."""


class ReplayUnavailableError(ReplayError):
    """A dependency (repository, coverage, audit, handles) timed out or failed before the
    change was recorded (HTTP 503); retry later."""


@dataclass(frozen=True, slots=True)
class WindowCoverage:
    """Recorded coverage of one window as half-open µs intervals (24 §13.3.1), clipped to it.
    Everything else in the window is a gap (`_uncovered`)."""

    covered: tuple[tuple[int, int], ...]


class CoverageReader(Protocol):
    async def window(self, symbol: str, lo_us: int, hi_us: int) -> WindowCoverage: ...


class SessionAudit(Protocol):
    """The subset of `AuditWriter.emit` used here (M12 may not import `audit`, C-3.3)."""

    async def emit(
        self,
        action: str,
        *,
        actor_label: str,
        actor_user_id: str | None,
        object_kind: str,
        object_id: str,
        reason: str | None,
        after_state: dict[str, Any],
    ) -> None: ...


#: Releases one paper-account or source handle; the service calls each at most once (INV-B12-e).
Release = Callable[[], Awaitable[None]]


class SessionHandles(Protocol):
    """Allocates a session's paper-account and source handles (E36 supplies the real ones)."""

    async def acquire(self, row: ReplaySessionRow) -> Sequence[Release]: ...


class NoHandles:
    """Until E36: a session holds nothing to release."""

    async def acquire(self, row: ReplaySessionRow) -> Sequence[Release]:
        return ()


#: `(user_id, paper_account_id) -> bool`: a `demo` account the user is granted (C-2.11, C-12.5).
#: E26-T05/E36 wire it; until then the service refuses every paper account (fail closed).
PaperAccountGate = Callable[[str, str], Awaitable[bool]]


class SnapshotSource(Protocol):
    async def load(self, key: MachineKey) -> SealedSnapshot | None: ...


#: `(session_id, user_id, reason)` once a session is destroyed (`client` | `idle_reclaim`): the
#: seam E26-T05's WS layer uses to revoke the session's subscriptions with
#: `replay_session_ended` (#624 reclaim AC). No-op until it is wired; failures are logged.
SessionEnded = Callable[[str, str, str], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class ReplayLimits:
    """The `CV_REPLAY_*` settings (24 §13.7)."""

    idle_ttl: timedelta
    max_sessions_per_user: int
    max_window: timedelta
    reclaim_interval_s: float = 60.0
    reclaim_batch: int = 50


def to_us(ts: datetime) -> int:
    return (ts - _EPOCH) // timedelta(microseconds=1)


def from_us(us: int) -> datetime:
    return _EPOCH + timedelta(microseconds=us)


def uncovered(lo: int, hi: int, covered: Sequence[tuple[int, int]]) -> list[list[int]]:
    """Every span of `[lo, hi)` no covered interval reaches, merged and in order: recorder gaps
    and spans no session recorded alike, so a partly covered window is replayed with its holes
    explicit (C-2.14, INV-B12-d)."""
    out: list[list[int]] = []
    at = lo
    for a, b in sorted((max(a, lo), min(b, hi)) for a, b in covered):
        if b <= at:
            continue
        if a > at:
            out.append([at, a])
        at = b
    if at < hi:
        out.append([at, hi])
    return out


def leaf_of(interp: Any) -> str:
    state: str = next(iter(interp.current_state_ids))
    return state.split(".", 1)[1]


def _canon(value: str) -> str | None:
    try:
        return str(uuid.UUID(str(value)))
    except ValueError:
        return None


class _Refusals:
    def __init__(self) -> None:
        self.counts: dict[str, int] = {}

    def record_send_refused(self, reason: str) -> None:
        self.counts[reason] = self.counts.get(reason, 0) + 1


@dataclass(slots=True, eq=False)
class _Live:
    """One session this process holds: its interpreter plus the last values mirrored to the row."""

    id: str
    user_id: str
    symbol: str
    interp: Any
    state: ReplayState
    cursor: int
    speed: Decimal
    touched: datetime
    releases: tuple[Release, ...] = ()
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    unsubscribe: Callable[[], None] | None = None
    done: bool = False

    @property
    def key(self) -> str:
        return f"{MACHINE}:{self.id}"


class ReplaySessionService:
    def __init__(
        self,
        repo: ReplaySessionRepository,
        *,
        coverage: CoverageReader,
        audit: SessionAudit,
        limits: ReplayLimits,
        handles: SessionHandles | None = None,
        paper_gate: PaperAccountGate | None = None,
        gateway: Gateway | None = None,
        env: str = "demo",
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        snapshots: SnapshotSource | None = None,
        restorer: Restorer | None = None,
        persister: Persister | None = None,
        on_ended: SessionEnded | None = None,
    ) -> None:
        self._repo, self._coverage, self._audit, self._limits = repo, coverage, audit, limits
        self._handles: SessionHandles = handles or NoHandles()
        self._paper_gate, self._env, self._clock, self._sleep = paper_gate, env, clock, sleep
        self._gateway = gateway or Gateway()
        self._snapshots, self._restorer, self._persister = snapshots, restorer, persister
        self._on_ended = on_ended
        self._live: dict[str, _Live] = {}
        #: Sessions whose chart entered a state since the last mirror (<= one entry per session).
        self._dirty: dict[str, None] = {}
        self._wake = asyncio.Event()
        self._revive_lock = asyncio.Lock()
        #: One lock per user serialises that user's quota decisions (create, entering a
        #: buffer-holding state). Lock order: a session lock may be held when one is taken,
        #: never the reverse. Bounded by the user base (the owner and a few managers).
        self._quota_locks: dict[str, asyncio.Lock] = {}
        self._tasks: list[asyncio.Task[None]] = []
        self.refusals = _Refusals()

    def _quota_lock(self, uid: str) -> asyncio.Lock:
        return self._quota_locks.setdefault(uid, asyncio.Lock())

    async def _io[T](self, what: str, pending: Awaitable[T]) -> T:
        """Every external await is bounded; a timeout is `ReplayUnavailableError` (C-2.18)."""
        try:
            async with asyncio.timeout(_IO_TIMEOUT_S):
                return await pending
        except TimeoutError as exc:
            raise ReplayUnavailableError(f"{what} timed out") from exc

    # --- lifecycle ---------------------------------------------------------------------------

    async def start(self) -> None:
        """Revive every live (`ix_rps_live`) row, then start the mirror and the reclaimer.

        US-RPL-009: a sealed snapshot is restored through `statechart.persistence`; without one
        the chart is rebuilt from the row in `created`. Other rows hold no buffers and are
        revived on their owner's next call."""
        horizon = self._clock() + timedelta(days=1)
        try:  # a database outage must not fail the boot: the sessions revive on next use
            live_rows = await self._io(
                "repository", self._repo.list_idle_since(horizon, MAX_PAGE_LIMIT)
            )
        except Exception as exc:
            logger().error("replay_session_revive_failed", error=type(exc).__name__)
            live_rows = []
        for idle in live_rows:
            try:
                await self._owned(idle.user_id, idle.id)
            except Exception as exc:
                logger().error(
                    "replay_session_revive_failed", session_id=idle.id, error=type(exc).__name__
                )
        if not self._tasks:
            self._tasks = [
                spawn(self._mirror_loop(), name="replay-session-mirror"),
                spawn(self._reclaim_loop(), name="replay-session-reclaim"),
            ]

    async def stop(self) -> None:
        """Cancel both tasks, then persist each chart (drain -> journal -> sealed snapshot ->
        stop, CV-C65') when a persister is wired, else stop it. Handles stay with the session:
        it survives the restart, and only `destroyed` releases them."""
        tasks, self._tasks = self._tasks, []
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        for live in list(self._live.values()):
            await self._retire(live, persist=True)

    @property
    def tasks_alive(self) -> bool:
        """Both tracked tasks are running (module health, `ReplayService.health`)."""
        return bool(self._tasks) and not any(task.done() for task in self._tasks)

    @property
    def limits(self) -> ReplayLimits:
        return self._limits

    async def _ended(self, live: _Live, reason: str) -> None:
        """Tell `on_ended` the session is gone (best effort: a failure is logged, never raised)."""
        if self._on_ended is None:
            return
        try:
            await self._io("on_ended", self._on_ended(live.id, live.user_id, reason))
        except Exception as exc:
            logger().error("replay_session_ended_failed", session_id=live.id, error=str(exc))

    async def _mirror_loop(self) -> None:
        while True:
            await self._wake.wait()
            self._wake.clear()
            while self._dirty:
                sid = next(iter(self._dirty))
                del self._dirty[sid]
                live = self._live.get(sid)
                if live is None:
                    continue
                try:
                    async with live.lock:
                        if self._live.get(sid) is live:
                            await self._sync(live)
                except Exception as exc:
                    logger().error(
                        "replay_session_mirror_failed", session_id=sid, error=type(exc).__name__
                    )

    async def _reclaim_loop(self) -> None:
        while True:
            await self._sleep(self._limits.reclaim_interval_s)
            try:
                await self.reclaim_idle(self._clock())
            except Exception as exc:
                logger().error("replay_session_reclaim_failed", error=type(exc).__name__)

    # --- create ------------------------------------------------------------------------------

    async def create(
        self, user_id: str, req: ReplaySessionCreate, *, prepare: bool = False
    ) -> ReplaySessionRow:
        """Validate, check the quota and the recorded coverage, audit (write-ahead), persist in
        `created`, build the chart, then allocate the handles: a refused request allocates
        nothing. The id is minted here and `user_id` is the authenticated principal (the request's
        own `id`/`user_id` are ignored). `prepare=True` then sends `PREPARE` (buffers)."""
        uid = _canon(user_id)
        if uid is None:
            raise ReplaySessionValidationError("user id must be a uuid")
        cursor = req.cursor_ts or req.range_start
        req = replace(req, id=str(uuid.uuid4()), user_id=uid, cursor_ts=cursor)
        self._validate(req)
        if req.paper_account_id is not None:
            gate = self._paper_gate  # E26-T05/E36 wire the grant port; unwired fails closed
            if gate is None or not await self._io("grant", gate(uid, req.paper_account_id)):
                raise ReplaySessionValidationError("paper account is not a demo account you hold")
        await self._check_quota(uid, opening=True)  # refused before any coverage I/O
        lo, hi = to_us(req.range_start), to_us(req.range_end)
        cov = await self._io("coverage", self._coverage.window(req.symbol, lo, hi))
        gaps = uncovered(lo, hi, cov.covered)
        if gaps == [[lo, hi]]:
            raise ReplayWindowUncoveredError("no recorded data in the requested window")
        after = {
            "symbol": req.symbol, "state": ReplayState.CREATED.value,
            "range_start": req.range_start.isoformat(), "range_end": req.range_end.isoformat(),
            "paper_account_id": req.paper_account_id,  # RP-R02: paper attach is recorded
        }  # fmt: skip
        async with self._quota_lock(uid):  # re-checked as one decision with the insert
            await self._check_quota(uid, opening=True)
            await self._emit("replay.session.created", req.id, uid, after, actor=None)
            row = await self._io("repository", self._repo.create(req))
            try:
                await self._adopt(row, await self._build(row, gaps))
            except BaseException:
                await self._io("repository", self._repo.delete(uid, row.id))
                raise
        return await self.transition(uid, row.id, "PREPARE") if prepare else row

    # --- control -----------------------------------------------------------------------------

    async def transition(
        self,
        user_id: str,
        session_id: str,
        event: str,
        payload: Mapping[str, object] | None = None,
    ) -> ReplaySessionRow:
        """Send one event through the gateway; return the row mirroring the settled chart.

        `ReplaySessionNotFoundError`: missing or another user's (404, never 403).
        `ReplaySessionValidationError`: unknown event or payload (422).
        `ReplaySessionIllegalUpdateError`: B12 does not handle it here, or the session is
        destroyed (409): refused before sending, the row untouched. A send that races an invoke
        completion and is held by the chart is refused too (counted `deferred`, see `_send_replay`).
        `ReplayQuotaExceededError`: entering a buffer-holding state (`PREPARE`, or `SEEK` out
        of `finished`/`error`) past the per-user quota."""
        data = _payload_for(event, payload)
        live = await self._owned(user_id, session_id)
        if live is None:
            raise ReplaySessionIllegalUpdateError(_canon(session_id) or "", ReplayState.DESTROYED)
        async with live.lock:
            if live.done:
                raise ReplaySessionIllegalUpdateError(live.id, ReplayState.DESTROYED)
            await self._settle(live)  # a queued invoke completion lands before `can()` reads
            facts = b12.facts(live.interp.context)
            if event == "SEEK":
                cursor = cast(int, data["cursor"])  # typed by `_payload_for`
                if not facts["range_start"] <= cursor <= facts["range_end"]:
                    raise ReplaySessionValidationError("cursor must lie inside the session window")
            if not live.interp.can({"type": event, **data}):
                self.refusals.record_send_refused("unhandled")
                state = ReplayState(leaf_of(live.interp))
                logger().info(
                    "replay_session_event_refused", session_id=live.id, control=event, state=state
                )
                raise ReplaySessionIllegalUpdateError(live.id, state)
            # Entering a buffer-holding state (`created` -PREPARE->, `finished`/`error` -SEEK->
            # `buffering`) is one quota decision with its send and mirrored row: no concurrent
            # double pass, and no quota bypass by reviving an old session (RP-D03).
            entering = ReplayState(leaf_of(live.interp)) not in LIVE_STATES
            lock = self._quota_lock(live.user_id) if entering else contextlib.nullcontext()
            async with lock:
                if entering and event in ("PREPARE", "SEEK"):
                    await self._check_quota(live.user_id, opening=False)
                try:
                    await self._send_replay(live, event, **data)
                except ReplaySessionIllegalUpdateError:
                    await self._sync(live)  # the racing completion moved the chart: mirror it
                    raise
                return await self._sync(live, control=event not in _SOURCE_EVENTS)

    async def destroy(self, user_id: str, session_id: str, *, reason: str = "client") -> bool:
        """Send `DESTROY`, audited write-ahead with `reason` (`client` | `idle_reclaim`).

        B12.3 handles `DESTROY` only in created/paused/finished/error, so a `playing` session is
        paused and a `buffering` one cancelled first (a `stepping` step is let finish; if it has
        not, this refuses and the next sweep retries). The handles are released exactly once
        and the interpreter is always retired, even when mirroring the row fails: the row then
        stays live and a retry revives and destroys it. `on_ended` is told in every case.
        False when already destroyed (INV-B12-e)."""
        if reason not in _REASONS:
            raise ReplaySessionValidationError("reason must be 'client' or 'idle_reclaim'")
        live = await self._owned(user_id, session_id)
        if live is None:
            return False
        async with live.lock:
            if live.done:
                return False
            interp = live.interp
            await self._settle(live)
            if interp.can("PAUSE"):
                await self._send_replay(live, "PAUSE")
            if interp.can("CANCEL"):
                await self._send_replay(live, "CANCEL")
            if not interp.can("DESTROY"):
                raise ReplaySessionIllegalUpdateError(live.id, ReplayState(leaf_of(interp)))
            after = {"symbol": live.symbol, "state": "destroyed", "reason": reason}
            actor = None if reason == "client" else _RECLAIM_ACTOR
            await self._emit("replay.session.destroyed", live.id, live.user_id, after, actor=actor)
            await self._send_replay(live, "DESTROY", reason=reason)
            live.done = True
            try:
                await self._release(live)
                await self._sync(live)
            finally:
                await self._retire(live)
                await self._ended(live, reason)
        return True

    async def reclaim_idle(self, now: datetime) -> int:
        """Destroy (`idle_reclaim`) every session with no control call for `idle_ttl`: live rows
        from `list_idle_since` (`ix_rps_live`) plus sessions this process holds in
        created/finished/error, which that index leaves out. One bounded batch per call; a
        session already destroyed is skipped, so a second pass is a no-op. Returns the count."""
        cutoff = now - self._limits.idle_ttl
        batch = self._limits.reclaim_batch
        idle = await self._io("repository", self._repo.list_idle_since(cutoff, batch))
        due = {r.id: r.user_id for r in idle}
        due.update({s.id: s.user_id for s in self._live.values() if s.touched < cutoff})
        reclaimed = 0
        for sid, uid in list(due.items())[:batch]:
            try:
                reclaimed += await self.destroy(uid, sid, reason="idle_reclaim")
            except Exception as exc:  # e.g. a step still running: the next sweep retries
                logger().warning(
                    "replay_session_reclaim_skipped", session_id=sid, error=type(exc).__name__
                )
        return reclaimed

    def state_of(self, session_id: str) -> str | None:
        """The chart's current state for a session this process holds (supervision, tests)."""
        live = self._live.get(_canon(session_id) or "")
        return None if live is None else leaf_of(live.interp)

    def facts_of(self, session_id: str) -> dict[str, Any] | None:
        """The chart's session facts (cursor, speed, coverage gaps, error) for a held session."""
        live = self._live.get(_canon(session_id) or "")
        return None if live is None else b12.facts(live.interp.context)

    # --- charts ------------------------------------------------------------------------------

    async def _owned(self, user_id: str, session_id: str) -> _Live | None:
        """The caller's session, revived from its row when this process does not hold it.
        Missing, malformed and another user's ids are all `ReplaySessionNotFoundError`; a
        destroyed row is None."""
        uid, sid = _canon(user_id), _canon(session_id)
        live = self._live.get(sid or "")
        if live is not None and live.user_id == uid:
            return live
        row = await self._io("repository", self._repo.get(uid, sid)) if uid and sid else None
        if row is None:
            raise ReplaySessionNotFoundError(session_id)
        if row.state is ReplayState.DESTROYED:
            return None
        async with self._revive_lock:
            return self._live.get(row.id) or await self._revive(row)

    async def _revive(self, row: ReplaySessionRow) -> _Live:
        key = MachineKey(MACHINE, row.id, self._env)
        sealed = None
        if self._snapshots is not None and self._restorer is not None:
            sealed = await self._io("snapshot", self._snapshots.load(key))
        interp: Any = None
        if sealed is not None and self._restorer is not None:
            try:  # a refused envelope is quarantined and paged by the Restorer; rebuild instead
                restored = await self._io("restore", restore_chart(self._restorer, key, sealed))
                interp = restored.interpreter
            except RestoreRefusedError:
                interp = None
        if interp is None:
            interp = await self._build(row)
        live = await self._adopt(row, interp)
        async with live.lock:
            await self._sync(live)
        return live

    async def _build(self, row: ReplaySessionRow, gaps: Sequence[Sequence[int]] = ()) -> Any:
        """A fresh chart in `created`; the facts land under `context["input"]` (`b12.facts`)."""
        ctx = {
            "session_id": row.id, "symbols": [row.symbol], "range_start": to_us(row.range_start),
            "range_end": to_us(row.range_end), "cursor": to_us(row.cursor_ts or row.range_start),
            "speed": float(row.speed), "loop": row.loop_enabled,
            "paper_account_id": row.paper_account_id, "coverage_gaps": [list(g) for g in gaps],
        }  # fmt: skip
        return (await build(MACHINE, ctx=ctx, clock=default_clock(), lane=LANE)).interpreter

    async def _adopt(self, row: ReplaySessionRow, interp: Any) -> _Live:
        """Allocate the handles and register the chart; on any failure after the allocation the
        handles are released and the chart stopped, so nothing leaks (the caller drops the row)."""
        try:
            releases = tuple(await self._io("handles", self._handles.acquire(row)))
        except BaseException:
            await interp.stop()
            raise
        live = _Live(
            id=row.id, user_id=row.user_id, symbol=row.symbol, interp=interp, state=row.state,
            cursor=to_us(row.cursor_ts or row.range_start), speed=row.speed,
            touched=row.updated_at, releases=releases,
        )  # fmt: skip

        async def hook(name: str, facts: Mapping[str, object]) -> None:
            await self._on_fact(live, name, facts)

        try:
            b12.attach_hook(interp, hook)
            live.unsubscribe = interp.subscribe(lambda _interp: self._mark(row.id))
            self._gateway.register(
                live.key, interp, kind="replay", lane=LANE, metrics=self.refusals
            )
        except BaseException:
            await self._release(live)
            await interp.stop()
            raise
        self._live[row.id] = live
        return live

    async def _retire(self, live: _Live, *, persist: bool = False) -> None:
        self._live.pop(live.id, None)
        self._dirty.pop(live.id, None)
        if live.unsubscribe is not None:
            live.unsubscribe()
        self._gateway.unregister(live.key)
        if persist and self._persister is not None and live.interp.is_running:
            key = MachineKey(MACHINE, live.id, self._env)
            try:
                await self._io("persist", self._persister.persist(live.interp, key=key))
                return
            except Exception as exc:  # e.g. a faulted context (MUST-01): stop without a snapshot
                logger().error(
                    "replay_session_persist_failed", session_id=live.id, error=type(exc).__name__
                )
        await live.interp.stop()  # a `destroyed` chart has completed: this is the idle teardown

    async def _send_replay(self, live: _Live, event: str, /, **payload: object) -> None:
        """The one send path (`statechart.gateway`); literal call sites are checked against B12
        by `tools/statechart/event_coverage.py`.

        `can()` ran on the settled chart, but an invoke completion can still land between it and
        this send. The chart then holds the event (`deferred`, `onUnhandled: "defer"`) or its
        guards deny it: that is a refusal, counted and logged. A held event stays on the chart's
        deferral buffer and runs on its next state change: the library has no public purge."""
        receipt = await self._gateway.send(live.key, {"type": event, **payload}, wait=_AWAIT_STEP)
        if receipt_is_conclusive(receipt) and receipt.error is not None:
            raise ReplayChartError(f"B12 {event}: {type(receipt.error).__name__}")
        if receipt.deferred or receipt.denied:  # `changed=False` alone is fine: internal arms
            self.refusals.record_send_refused("deferred")
            state = ReplayState(leaf_of(live.interp))
            logger().warning(
                "replay_session_event_parked", session_id=live.id, control=event, state=state
            )
            raise ReplaySessionIllegalUpdateError(live.id, state)
        await self._settle(live)

    async def _settle(self, live: _Live) -> None:
        """Bounded cooperative yields while an invoke (`seek`/`step`) hands off; a slower one is
        mirrored by the mirror task when its completion enters a state."""
        for _ in range(_SETTLE_YIELDS):
            if not live.interp.pending_events and leaf_of(live.interp) not in _INVOKING:
                return
            await asyncio.sleep(0)

    async def _sync(self, live: _Live, *, control: bool = False) -> ReplaySessionRow:
        """Mirror the chart onto the row (caller holds `live.lock`): cursor and speed first (a
        terminal row refuses updates), then the state, one structured line per state change."""
        uid, sid, now = live.user_id, live.id, self._clock()
        facts, state = b12.facts(live.interp.context), ReplayState(leaf_of(live.interp))
        repo = self._repo
        if state is not ReplayState.DESTROYED:
            if (cursor := int(facts["cursor"])) != live.cursor:
                await self._io(
                    "repository", repo.update_cursor(uid, sid, cursor_ts=from_us(cursor))
                )
                live.cursor = cursor
            if (speed := Decimal(str(facts["speed"]))) != live.speed:
                await self._io("repository", repo.update_speed(uid, sid, speed=speed))
                live.speed, live.touched = speed, now
            if control:  # a control call is activity even when the state comes back the same
                await self._io("repository", repo.touch(uid, sid, now))
                live.touched = now
        if state is not live.state:
            error = str(facts["error"] or "source_error") if state is ReplayState.ERROR else None
            await self._io(
                "repository", repo.update_state(uid, sid, state=state, error_message=error)
            )
            logger().info(
                "replay_session_transition", session_id=sid, user_id=uid, symbol=live.symbol,
                from_state=live.state.value, to_state=state.value,
            )  # fmt: skip
            live.state, live.touched = state, now
        row = await self._io("repository", repo.get(uid, sid))
        if row is None:
            raise ReplaySessionNotFoundError(sid)
        return row

    async def _release(self, live: _Live) -> None:
        """INV-B12-e: each handle is taken out before it runs, so none runs twice; a failing
        release is logged and the others still run."""
        releases, live.releases = live.releases, ()
        for release in releases:
            try:
                async with asyncio.timeout(_IO_TIMEOUT_S):
                    await release()
            except Exception as exc:
                logger().error(
                    "replay_session_release_failed", session_id=live.id, error=type(exc).__name__
                )

    # --- checks, hook, audit -----------------------------------------------------------------

    async def _check_quota(self, uid: str, *, opening: bool) -> None:
        """`count_active` counts the buffer-holding rows (`ix_rps_live`); opening a session also
        counts the user's held charts outside them (created/finished/error)."""
        used = await self._io("repository", self._repo.count_active(uid))
        if opening:
            used += sum(
                s.user_id == uid and s.state not in LIVE_STATES for s in self._live.values()
            )
        if used >= self._limits.max_sessions_per_user:
            raise ReplayQuotaExceededError(
                f"at most {self._limits.max_sessions_per_user} open replay sessions per user"
            )

    def _validate(self, req: ReplaySessionCreate) -> None:
        """The `rps_*` CHECKs and the window cap, worded for a person (before the database)."""
        problems: list[str] = []
        if not _SYMBOL.fullmatch(req.symbol):
            problems.append("symbol must be an upper-case instrument code such as BTCUSDT")
        if req.range_end <= req.range_start:
            problems.append("range_end must be after range_start")
        elif req.range_end - req.range_start > self._limits.max_window:
            problems.append(f"the window may span at most {self._limits.max_window}")
        if not (req.speed.is_finite() and Decimal("0.1") <= req.speed <= 100):
            problems.append("speed must be between 0.1 and 100")
        cursor = req.cursor_ts
        if cursor is not None and not req.range_start <= cursor <= req.range_end:
            problems.append("the cursor must lie inside the window")
        if req.paper_trading and req.paper_account_id is None:
            problems.append("paper trading needs a paper account")
        if problems:
            raise ReplaySessionValidationError("; ".join(problems))

    def _mark(self, session_id: str) -> None:
        """State-entry notification (`subscribe`): on the chart's loop, cheap, never blocks."""
        self._dirty[session_id] = None
        self._wake.set()

    async def _on_fact(self, live: _Live, name: str, facts: Mapping[str, object]) -> None:
        """B12 hook, inside the step (takes no lock, sends nothing). `error`/`killed` are
        audited; an audit outage is logged, never raised: the chart must still reach `error`."""
        if name in ("error", "killed"):
            after = {"symbol": live.symbol, "state": "error", "reason": str(facts["error"])}
            try:
                await self._emit(
                    "replay.session.error", live.id, live.user_id, after, actor=_CHART_ACTOR
                )
            except ReplayUnavailableError as exc:
                logger().critical("replay_session_audit_failed", session_id=live.id, error=str(exc))
        self._mark(live.id)

    async def _emit(
        self, action: str, sid: str, uid: str, after: dict[str, Any], *, actor: str | None
    ) -> None:
        """C-2.9: `actor=None` is the session's user, else a system actor label. Raises
        `ReplayUnavailableError` when the record cannot be written, so the caller refuses."""
        record = self._audit.emit(
            action,
            actor_label=actor or f"user:{uid}",
            actor_user_id=None if actor else uid,
            object_kind="replay_session",
            object_id=sid,
            reason=after.get("reason"),
            after_state=after,
        )
        try:
            await self._io("audit", record)
        except ReplayUnavailableError:
            raise
        except Exception as exc:
            raise ReplayUnavailableError(f"audit {type(exc).__name__}") from exc


def _payload_for(event: str, payload: Mapping[str, object] | None) -> dict[str, object]:
    """Closed payloads (RP-S06): a caller names one of `_EVENTS` with only its keys, typed."""
    data = dict(payload or {})
    allowed = _EVENTS.get(event)
    if allowed is None or set(data) != allowed:
        raise ReplaySessionValidationError("unsupported replay event or payload")
    if event == "SET_SPEED":
        speed = data["speed"]
        if not (
            isinstance(speed, int | float)
            and not isinstance(speed, bool)
            and b12.SPEED_MIN <= speed <= b12.SPEED_MAX
        ):
            raise ReplaySessionValidationError("speed must be between 0.1 and 100")
    cursor, error = data.get("cursor"), data.get("error")
    if event == "SEEK" and (not isinstance(cursor, int) or isinstance(cursor, bool)):
        raise ReplaySessionValidationError("cursor must be an integer microsecond timestamp")
    if event == "SOURCE_ERROR" and not (isinstance(error, str) and 0 < len(error) <= 256):
        raise ReplaySessionValidationError("error must be a short string")
    return data
