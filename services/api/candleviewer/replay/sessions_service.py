"""`ReplaySessionService`: the replay session lifecycle on the B12 `replay` chart (E26-T01 3/3).

The chart *is* the lifecycle (C-2.19): interpreters are built only by
`statechart.factory.build("replay")` or restored only through `statechart.persistence`, every event
goes through `statechart.gateway`, and legality is whatever B12 handles (28 §B12.3). Statecharts
record, synchronous code enforces (C-2.21): the per-user quota, the window cap, the coverage check,
payload validation and the paper-account grant run here before anything is sent, and an event the
current state does not handle is refused with `can()` (never parked on `onUnhandled: "defer"`,
CV-C06) as `ReplaySessionIllegalUpdateError` (HTTP 409).

Row mirror (24 §13.7): `replay_sessions.state` takes every chart state, written from the settled
chart before a control call returns. The bindings publish plain values through a per-interpreter
hook; the service audits `error` from it.

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
from candleviewer.statechart import build
from candleviewer.statechart.config import Lane
from candleviewer.statechart.factory import default_clock
from candleviewer.statechart.gateway import Gateway, receipt_is_conclusive
from candleviewer.storage.repositories.replay_sessions import (
    LIVE_STATES,
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
_SYSTEM_ACTOR: Final = "system:replay-reclaimer"
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
#: States with an invoked service (`seek`, `step`) whose completion arrives later (B12.4).
_INVOKING: Final = frozenset({"buffering", "stepping"})


def logger() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


class ReplaySessionValidationError(ValueError):
    """A human-readable request error, raised before the database or the chart (HTTP 422)."""


class ReplayQuotaExceededError(Exception):
    """The user already holds `CV_REPLAY_MAX_SESSIONS_PER_USER` open sessions; nothing allocated."""


class ReplayWindowUncoveredError(Exception):
    """No recorded coverage in the window (`no_data_recorded`, HTTP 422); nothing allocated."""


class ReplayChartError(RuntimeError):
    """B12 failed to record an accepted event (an action raised and the step was rolled back)."""


@dataclass(frozen=True, slots=True)
class WindowCoverage:
    """Recorded coverage of one window as half-open µs pairs (24 §13.3.1), clipped to it."""

    covered: tuple[tuple[int, int], ...]
    gaps: tuple[tuple[int, int], ...] = ()


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


#: `(user_id, paper_account_id) -> bool`: a `demo` account the user is granted (C-2.11, C-12.5).
PaperAccountGate = Callable[[str, str], Awaitable[bool]]


@dataclass(frozen=True, slots=True)
class ReplayLimits:
    """The `CV_REPLAY_*` settings (24 §13.7)."""

    idle_ttl: timedelta
    max_sessions_per_user: int
    max_window: timedelta


def to_us(ts: datetime) -> int:
    return (ts - _EPOCH) // timedelta(microseconds=1)


def from_us(us: int) -> datetime:
    return _EPOCH + timedelta(microseconds=us)


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
        handles: SessionHandles,
        paper_gate: PaperAccountGate | None = None,
        gateway: Gateway | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._repo, self._coverage, self._audit, self._limits = repo, coverage, audit, limits
        self._handles = handles
        self._paper_gate, self._clock = paper_gate, clock
        self._gateway = gateway or Gateway()
        self._live: dict[str, _Live] = {}
        self._revive_lock = asyncio.Lock()
        #: Serialises quota decisions (create, `PREPARE`). Lock order: a session lock may be held
        #: when this is taken, never the reverse.
        self._quota_lock = asyncio.Lock()
        self.refusals = _Refusals()

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
            gate = self._paper_gate
            if gate is None or not await gate(uid, req.paper_account_id):
                raise ReplaySessionValidationError("paper account is not a demo account you hold")
        await self._check_quota(uid, opening=True)  # refused before any coverage I/O
        async with asyncio.timeout(_IO_TIMEOUT_S):
            lo, hi = to_us(req.range_start), to_us(req.range_end)
            cov = await self._coverage.window(req.symbol, lo, hi)
        if not any(b > a for a, b in cov.covered):
            raise ReplayWindowUncoveredError("no recorded data in the requested window")
        after = {
            "symbol": req.symbol, "state": ReplayState.CREATED.value,
            "range_start": req.range_start.isoformat(), "range_end": req.range_end.isoformat(),
            "paper_account_id": req.paper_account_id,  # RP-R02: paper attach is recorded
        }  # fmt: skip
        async with self._quota_lock:  # re-checked as one decision with the insert (no race)
            await self._check_quota(uid, opening=True)
            await self._emit("replay.session.created", req.id, uid, after, by_user=True)
            row = await self._repo.create(req)
            try:
                await self._adopt(row, await self._build(row, cov.gaps))
            except BaseException:
                await self._repo.delete(uid, row.id)
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
        destroyed (409): nothing is sent and the row is untouched.
        `ReplayQuotaExceededError`: entering a buffer-holding state (`PREPARE`, or `SEEK` out
        of `finished`/`error`) past the per-user quota."""
        data = _payload_for(event, payload)
        live = await self._owned(user_id, session_id)
        if live is None:
            raise ReplaySessionIllegalUpdateError(str(session_id), ReplayState.DESTROYED)
        async with live.lock:
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
            async with self._quota_lock if entering else contextlib.nullcontext():
                if entering and event in ("PREPARE", "SEEK"):
                    await self._check_quota(live.user_id, opening=False)
                await self._send_replay(live, event, **data)
                return await self._sync(live, control=event not in _SOURCE_EVENTS)

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
        row = await self._repo.get(uid, sid) if uid and sid else None
        if row is None:
            raise ReplaySessionNotFoundError(session_id)
        if row.state is ReplayState.DESTROYED:
            return None
        async with self._revive_lock:
            return self._live.get(row.id) or await self._revive(row)

    async def _revive(self, row: ReplaySessionRow) -> _Live:
        live = await self._adopt(row, await self._build(row))
        async with live.lock:
            await self._sync(live)
        return live

    async def _build(self, row: ReplaySessionRow, gaps: Sequence[tuple[int, int]] = ()) -> Any:
        """A fresh chart in `created`; the facts land under `context["input"]` (`b12.facts`)."""
        ctx = {
            "session_id": row.id, "symbols": [row.symbol], "range_start": to_us(row.range_start),
            "range_end": to_us(row.range_end), "cursor": to_us(row.cursor_ts or row.range_start),
            "speed": float(row.speed), "loop": row.loop_enabled,
            "paper_account_id": row.paper_account_id, "coverage_gaps": [[a, b] for a, b in gaps],
        }  # fmt: skip
        return (await build(MACHINE, ctx=ctx, clock=default_clock(), lane=LANE)).interpreter

    async def _adopt(self, row: ReplaySessionRow, interp: Any) -> _Live:
        try:
            releases = tuple(await self._handles.acquire(row))
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

        b12.attach_hook(interp, hook)
        self._gateway.register(live.key, interp, kind="replay", lane=LANE, metrics=self.refusals)
        self._live[row.id] = live
        return live

    async def _send_replay(self, live: _Live, event: str, /, **payload: object) -> None:
        """The one send path (`statechart.gateway`); literal call sites are checked against B12
        by `tools/statechart/event_coverage.py`."""
        receipt = await self._gateway.send(live.key, {"type": event, **payload}, wait=_AWAIT_STEP)
        if receipt_is_conclusive(receipt) and receipt.error is not None:
            raise ReplayChartError(f"B12 {event}: {type(receipt.error).__name__}")
        await self._settle(live)

    async def _settle(self, live: _Live) -> None:
        """Bounded cooperative yields while an invoke (`seek`/`step`) hands off; a slower one is
        mirrored on the session's next control call."""
        for _ in range(_SETTLE_YIELDS):
            if not live.interp.pending_events and leaf_of(live.interp) not in _INVOKING:
                return
            await asyncio.sleep(0)

    async def _sync(self, live: _Live, *, control: bool = False) -> ReplaySessionRow:
        """Mirror the chart onto the row (caller holds `live.lock`): cursor and speed first (a
        terminal row refuses updates), then the state, one structured line per state change."""
        uid, sid, now = live.user_id, live.id, self._clock()
        facts, state = b12.facts(live.interp.context), ReplayState(leaf_of(live.interp))
        if state is not ReplayState.DESTROYED:
            if (cursor := int(facts["cursor"])) != live.cursor:
                await self._repo.update_cursor(uid, sid, cursor_ts=from_us(cursor))
                live.cursor = cursor
            if (speed := Decimal(str(facts["speed"]))) != live.speed:
                await self._repo.update_speed(uid, sid, speed=speed)
                live.speed, live.touched = speed, now
            if control:  # a control call is activity even when the state comes back the same
                await self._repo.touch(uid, sid, now)
                live.touched = now
        if state is not live.state:
            error = str(facts["error"] or "source_error") if state is ReplayState.ERROR else None
            await self._repo.update_state(uid, sid, state=state, error_message=error)
            logger().info(
                "replay_session_transition", session_id=sid, user_id=uid, symbol=live.symbol,
                from_state=live.state.value, to_state=state.value,
            )  # fmt: skip
            live.state, live.touched = state, now
        row = await self._repo.get(uid, sid)
        if row is None:
            raise ReplaySessionNotFoundError(sid)
        return row

    # --- checks, hook, audit -----------------------------------------------------------------

    async def _check_quota(self, uid: str, *, opening: bool) -> None:
        """`count_active` counts the buffer-holding rows (`ix_rps_live`); opening a session also
        counts the user's held charts outside them (created/finished/error)."""
        used = await self._repo.count_active(uid)
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

    async def _on_fact(self, live: _Live, name: str, facts: Mapping[str, object]) -> None:
        """B12 hook, inside the step (takes no lock, sends nothing). `error`/`killed` are
        audited; an audit outage is logged, never raised: the chart must still reach `error`."""
        if name in ("error", "killed"):
            after = {"symbol": live.symbol, "state": "error", "reason": str(facts["error"])}
            try:
                await self._emit(
                    "replay.session.error", live.id, live.user_id, after, by_user=False
                )
            except Exception as exc:
                logger().critical(
                    "replay_session_audit_failed", session_id=live.id, error=type(exc).__name__
                )

    async def _emit(
        self, action: str, sid: str, uid: str, after: dict[str, Any], *, by_user: bool
    ) -> None:
        """C-2.9: raises when the record cannot be written, so the caller refuses the change."""
        async with asyncio.timeout(_IO_TIMEOUT_S):
            await self._audit.emit(
                action,
                actor_label=f"user:{uid}" if by_user else _SYSTEM_ACTOR,
                actor_user_id=uid if by_user else None,
                object_kind="replay_session",
                object_id=sid,
                reason=after.get("reason"),
                after_state=after,
            )


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
