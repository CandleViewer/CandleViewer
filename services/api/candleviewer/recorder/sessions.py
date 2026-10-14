"""Recording sessions and gap detection (E16-T04, 21-database-schema.md §3.6.2).

A `recording_sessions` row is one continuous capture run of one symbol. The lifecycle
(`starting -> recording -> degraded -> stopping -> stopped|error`) is the B11 chart's; this
module only MIRRORS it into Postgres from the state-entry hooks the chart already publishes
(`RecordingPolicy` forwards them via `on_b11_state`) — it never queries an interpreter per
event (C-2.20) and owns no state machine of its own (ADR-0016).

Gap sources (cause, `recording_gaps.cause`):
- `ws_disconnect`: E08 `FeedHealthEvent` windows (`stale`/`degraded`/`resubscribing` ->
  `healthy`); topics are normalised by the adapter-provided `TopicResolver`.
  On recovery the session is closed (`end_reason='ws_disconnect'`), one gap per affected
  stream covering exactly the outage is written on it, and a new session is opened.
- `seq_jump`: the StreamWriter's `seq_jump_windows` signal (E16-T03) — not re-detected here.
- `exchange_outage`: `on_exchange_outage(...)` (no E08 emitter exists yet; see the PR).
- `process_restart`: `recover_on_startup()` closes every session left open by a dead process
  and writes a gap from its `last_event_ts` (or `started_at`) to process start.
- `backpressure_drop`: written by the StreamWriter itself on the live session this module
  opens (its buffered gaps flush once `open` has run).

Startup order (#2188): `recover_on_startup()` -> B11 snapshot restore -> OMS position cache
reload -> `policy.positions_reloaded()` — see `startup_reconcile`.

Every external await is bounded by `store_timeout_s`; the clock is injected (epoch µs).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Final, Literal, Protocol

import structlog

from candleviewer.recorder.metrics import (
    recorder_gap_seconds_total,
    recorder_gaps_total,
    recorder_sessions_open,
)
from candleviewer.recorder.models import RecorderSetChanged

GapCause = Literal[
    "ws_disconnect", "backpressure_drop", "process_restart", "seq_jump", "exchange_outage"
]
_EPOCH: Final = datetime(1970, 1, 1, tzinfo=UTC)
#: Default recorded streams (Postgres `stream_kind`) when the policy names none.
DEFAULT_STREAMS: Final[tuple[str, ...]] = (
    "trades",
    "orderbook_delta",
    "orderbook_snapshot",
    "tickers",
    "liquidations",
)
#: Feed states that mean "the socket is not delivering" (stale = quiet, not lost).
_DOWN: Final = frozenset({"degraded", "resubscribing"})
#: B11 hook name (state entry) -> `recording_state` mirrored on the session row.
_B11_STATE: Final[dict[str, str]] = {
    "subscribe": "starting",
    "recording": "recording",
    "degraded": "degraded",
    "unsubscribe": "stopping",
}


def logger() -> structlog.stdlib.BoundLogger:
    return structlog.get_logger("candleviewer.recorder.sessions")  # type: ignore[no-any-return]  # structlog: Any


def to_dt(us: int) -> datetime:
    return _EPOCH + timedelta(microseconds=us)


def to_us(value: datetime) -> int:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    delta = value - _EPOCH
    return (delta.days * 86_400 + delta.seconds) * 1_000_000 + delta.microseconds


class SessionStore(Protocol):
    """`SqlAlchemyRecorderRepository` conforms."""

    async def get_by_symbol(self, symbol: str, env: str = "live") -> dict[str, Any] | None: ...

    async def upsert_auto(
        self, symbol: str, reason: str, ref: dict[str, str], env: str = "live"
    ) -> str: ...

    async def open_session_at(
        self,
        *,
        recorded_symbol_id: str,
        symbol: str,
        streams: Sequence[str],
        orderbook_depth: int,
        ws_endpoint: str,
        started_at: datetime,
    ) -> str: ...

    async def close_session_at(
        self, session_id: str, *, reason: str, ended_at: datetime, error: bool = False
    ) -> bool: ...

    async def set_session_state(self, session_id: str, state: str) -> bool: ...

    async def touch_session_events(
        self, session_id: str, *, first: datetime, last: datetime
    ) -> bool: ...

    async def record_gap(
        self,
        *,
        session_id: str,
        symbol: str,
        stream: str,
        gap_start: datetime,
        gap_end: datetime,
        cause: str,
    ) -> int: ...

    async def list_live_sessions(self) -> list[dict[str, Any]]: ...


class SessionAudit(Protocol):
    """Subset of `AuditWriter.emit` (same shape as `recorder.policy.AuditSink`; injected —
    M11 may not import `audit`, C-3.3).

    The sink MUST be cancellation-safe, as `AuditWriter` is (#2250): `_audit_restart`
    bounds `emit` with `asyncio.timeout`, so a cancelled emit must neither corrupt the
    sink nor be lost half-written. It may still land after the timeout, and the retry on
    the next start then audits the close again: over-audit, never under-audit (C-2.9)."""

    async def emit(
        self,
        action: str,
        *,
        actor_label: str,
        actor_user_id: str | None,
        object_kind: str,
        object_id: str,
        reason: str,
        after_state: Mapping[str, str | bool | None],
        env: str,
        outcome: str = "success",
    ) -> None: ...


#: Actor for automatic recorder session actions (crash recovery).
SYSTEM_RECORDER: Final = "system:recorder"


class WriterSignals(Protocol):
    """The StreamWriter's outputs this module consumes (E16-T03)."""

    def take_seq_jump_windows(self) -> list[tuple[str, int, int]]: ...

    def take_event_bounds(self) -> dict[str, tuple[int, int]]: ...


Invalidate = Callable[[str], None]


@dataclass(slots=True)
class _Live:
    session_id: str
    started_us: int
    streams: tuple[str, ...]
    reason: str = "chart_open"
    #: stream -> outage start (µs) while E08 reports it down.
    down: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SessionConfig:
    env: str = "live"
    ws_endpoint: str = "public"
    orderbook_depth: int = 200
    store_timeout_s: float = 5.0


#: Venue topic -> (symbol | None, stream_kind names). Injected: the adapter owns the venue
#: vocabulary (`exchange.base.ports.StreamForTopic`, implemented by the exchange adapter, C-2.2).
TopicResolver = Callable[[str], tuple[str | None, tuple[str, ...]]]


def _all_streams(topic: str) -> tuple[str | None, tuple[str, ...]]:
    """Fallback resolver when none is injected: treat every event as socket-wide."""
    return None, DEFAULT_STREAMS


class SessionManager:
    """Opens/closes `recording_sessions` rows and writes gap rows (module docstring)."""

    def __init__(
        self,
        store: SessionStore,
        *,
        now_us: Callable[[], int],
        config: SessionConfig | None = None,
        invalidate: Invalidate | None = None,
        topics: TopicResolver | None = None,
        audit: SessionAudit | None = None,
    ) -> None:
        self._audit = audit
        self._store = store
        self._topics = topics or _all_streams
        self._now_us = now_us
        self._cfg = config or SessionConfig()
        self._invalidate = invalidate or (lambda _symbol: None)
        self._live: dict[str, _Live] = {}
        self._lock = asyncio.Lock()

    # -- queries -------------------------------------------------------------------------------

    def live_session(self, symbol: str) -> str | None:
        live = self._live.get(symbol)
        return None if live is None else live.session_id

    # -- bounded store calls -------------------------------------------------------------------

    async def _call[T](self, op: Callable[[], Awaitable[T]]) -> T:
        async with asyncio.timeout(self._cfg.store_timeout_s):
            return await op()

    async def _gap(
        self, symbol: str, session_id: str, stream: str, lo: int, hi: int, cause: GapCause
    ) -> int | None:
        if hi <= lo:
            return None  # zero-length windows are not gaps (rg_window CHECK)
        gap_id = await self._call(
            lambda: self._store.record_gap(
                session_id=session_id,
                symbol=symbol,
                stream=stream,
                gap_start=to_dt(lo),
                gap_end=to_dt(hi),
                cause=cause,
            )
        )
        recorder_gaps_total.labels(cause=cause).inc()
        recorder_gap_seconds_total.labels(symbol=symbol).inc((hi - lo) / 1e6)
        logger().warning(
            "recorder_gap", symbol=symbol, stream=stream, cause=cause, start_us=lo, end_us=hi
        )
        self._invalidate(symbol)
        return gap_id

    # -- lifecycle -----------------------------------------------------------------------------

    async def on_set_changed(self, event: RecorderSetChanged, streams: Sequence[str] = ()) -> None:
        async with self._lock:
            if event.change == "added" and event.symbol not in self._live:
                await self._open(event.symbol, event.reason, tuple(streams) or DEFAULT_STREAMS)
            elif event.change == "removed" and event.symbol in self._live:
                await self._close(event.symbol, "stopped", self._now_us())

    async def _open(self, symbol: str, reason: str, streams: tuple[str, ...]) -> str:
        env = self._cfg.env
        row = await self._call(lambda: self._store.get_by_symbol(symbol, env))
        if row is not None:
            rsid = str(row["id"])
        else:
            # Auto-record rows are created here until #2188 item 4 persists them on add; the
            # ref is constant so a re-open never grows `reason_refs` (containment check).
            ref = {"kind": "recorder", "id": "session"}
            rsid = await self._call(lambda: self._store.upsert_auto(symbol, reason, ref, env))
        started = self._now_us()
        sid = await self._call(
            lambda: self._store.open_session_at(
                recorded_symbol_id=rsid,
                symbol=symbol,
                streams=streams,
                orderbook_depth=self._cfg.orderbook_depth,
                ws_endpoint=self._cfg.ws_endpoint,
                started_at=to_dt(started),
            )
        )
        self._live[symbol] = _Live(sid, started, streams, reason)
        recorder_sessions_open.set(len(self._live))
        logger().info("recorder_session_opened", symbol=symbol, session_id=sid)
        self._invalidate(symbol)
        return sid

    async def _close(self, symbol: str, reason: str, at_us: int, *, error: bool = False) -> None:
        live = self._live.pop(symbol)
        recorder_sessions_open.set(len(self._live))
        await self._call(
            lambda: self._store.close_session_at(
                live.session_id, reason=reason, ended_at=to_dt(at_us), error=error
            )
        )
        logger().info(
            "recorder_session_closed", symbol=symbol, session_id=live.session_id, reason=reason
        )
        self._invalidate(symbol)

    async def on_b11_state(self, symbol: str, hook: str, context: Mapping[str, object]) -> None:
        """Mirror a B11 state-entry hook (published by the chart; never a per-event query)."""
        async with self._lock:
            live = self._live.get(symbol)
            if live is None:
                return
            if hook in ("error", "killed"):
                await self._close(symbol, hook, self._now_us(), error=hook == "error")
                return
            state = _B11_STATE.get(hook)
            if state is not None:
                sid = live.session_id
                await self._call(lambda: self._store.set_session_state(sid, state))

    # -- gap sources ---------------------------------------------------------------------------

    async def on_feed_health(self, topic: str, state: str, age_s: float = 0.0) -> None:
        """E08 `FeedHealthEvent` (`age_s` = its `last_msg_age_s`). A `stale` topic writes its
        silent window immediately. A `degraded|resubscribing` -> `healthy` window is a
        `ws_disconnect` gap; when the last down stream of a symbol recovers, the session is
        closed (`end_reason='ws_disconnect'`) and a new one opened at the recovery instant."""
        symbol, streams = self._topics(topic)
        now = self._now_us()
        async with self._lock:
            targets = [symbol] if symbol is not None else list(self._live)
            for sym in targets:
                live = self._live.get(sym)
                if live is None:
                    continue
                wanted = [s for s in streams if s in live.streams]
                if state == "stale" and age_s > 0:
                    # A stale topic is resubscribed on the live socket and recovers with no
                    # per-topic `healthy` event (E08 watchdog), so the observed silent window
                    # is written now; the session continues (the socket was not lost).
                    lo = max(live.started_us, now - int(age_s * 1_000_000))
                    for s in wanted:
                        if s not in live.down:
                            await self._gap(sym, live.session_id, s, lo, now, "ws_disconnect")
                elif state in _DOWN:
                    for s in wanted:
                        live.down.setdefault(s, now)
                elif state == "healthy":
                    await self._recover_streams(sym, live, wanted, now)

    async def _recover_streams(
        self, symbol: str, live: _Live, streams: Sequence[str], now: int
    ) -> None:
        recovered = [s for s in streams if s in live.down]
        if not recovered:
            return
        for s in recovered:
            await self._gap(symbol, live.session_id, s, live.down.pop(s), now, "ws_disconnect")
        if not live.down:
            await self._close(symbol, "ws_disconnect", now)
            await self._open(symbol, live.reason, live.streams)

    async def on_exchange_outage(self, symbol: str | None, start_us: int, end_us: int) -> None:
        """An exchange-side outage window (venue maintenance/incident): one gap per stream."""
        async with self._lock:
            for sym in [symbol] if symbol else list(self._live):
                live = self._live.get(sym)
                if live is None:
                    continue
                lo = max(start_us, live.started_us)
                for s in live.streams:
                    await self._gap(sym, live.session_id, s, lo, end_us, "exchange_outage")

    async def poll_writer(self, writer: WriterSignals) -> None:
        """Consume the StreamWriter's seq-jump windows and event bounds (E16-T03 signals)."""
        jumps = writer.take_seq_jump_windows()
        bounds = writer.take_event_bounds()
        async with self._lock:
            for sym, lo, hi in jumps:
                live = self._live.get(sym)
                if live is not None:
                    await self._gap(sym, live.session_id, "orderbook_delta", lo, hi, "seq_jump")
            for sym, (first, last) in bounds.items():
                live = self._live.get(sym)
                if live is None:
                    continue
                await self._touch(live.session_id, first, last)

    async def _audit_restart(self, symbol: str, sid: str, lo: int, hi: int) -> None:
        """C-2.9 write-ahead: the `recorder.stop` audit precedes the gap row and the close; an
        audit failure raises, so recovery stops with the session still open (retried on the
        next start) - never an unaudited close. The sink is cancellation-safe (#2250): a
        timeout cancels an emit still queued for the WAL (nothing is appended), while one
        already appending finishes inside the sink. So a timeout leaves at most one in-flight
        record - over-audit, never under-audit - and no orphan task here."""
        if self._audit is None:
            return
        async with asyncio.timeout(self._cfg.store_timeout_s):
            await self._audit.emit(
                "recorder.stop",
                actor_label=SYSTEM_RECORDER,
                actor_user_id=None,
                object_kind="recorded_symbol",
                object_id=symbol,
                reason="process_restart",
                after_state={
                    "symbol": symbol,
                    "session_id": sid,
                    "reason": "process_restart",
                    "gap_start_us": str(lo),
                    "gap_end_us": str(hi),
                },
                env=self._cfg.env,
            )

    async def _touch(self, sid: str, first: int, last: int) -> None:
        await self._call(
            lambda: self._store.touch_session_events(sid, first=to_dt(first), last=to_dt(last))
        )

    async def _close_row(self, sid: str, reason: str, at_us: int) -> None:
        await self._call(
            lambda: self._store.close_session_at(sid, reason=reason, ended_at=to_dt(at_us))
        )

    # -- crash recovery (C-13.6 scenario 12) ---------------------------------------------------

    async def recover_on_startup(self, process_start_us: int) -> int:
        """Close every session a dead process left open: `end_reason='process_restart'` and one
        gap per stream from `last_event_ts` (else `started_at`) to process start. Must run
        before any session is opened by this process. Returns the number closed."""
        async with self._lock:
            rows = await self._call(self._store.list_live_sessions)
            closed = 0
            for row in rows:
                sid, symbol = str(row["id"]), str(row["symbol"])
                if sid in {lv.session_id for lv in self._live.values()}:
                    continue  # opened by this process
                # Starts at `last_event_ts` once the writer's bounds are tracked (poll_writer);
                # until then `started_at` (overstates, never understates, the loss).
                last = row.get("last_event_ts") or row["started_at"]
                lo = to_us(last)
                await self._audit_restart(symbol, sid, lo, process_start_us)
                for s in row.get("streams") or DEFAULT_STREAMS:
                    await self._gap(symbol, sid, str(s), lo, process_start_us, "process_restart")
                await self._close_row(sid, "process_restart", process_start_us)
                closed += 1
                logger().warning("recorder_session_crash_closed", symbol=symbol, session_id=sid)
            return closed

    async def stop(self) -> None:
        """Graceful shutdown: close every live session (`end_reason='shutdown'`)."""
        async with self._lock:
            now = self._now_us()
            for sym in list(self._live):
                try:
                    await self._close(sym, "shutdown", now)
                except (TimeoutError, OSError) as exc:
                    logger().error(
                        "recorder_session_close_failed", symbol=sym, error=type(exc).__name__
                    )


class WarmupGate(Protocol):
    def positions_reloaded(self) -> None: ...


async def startup_reconcile(
    sessions: SessionManager,
    gate: WarmupGate,
    *,
    process_start_us: int,
    restore_b11: Callable[[], Awaitable[None]] | None = None,
    reload_positions: Callable[[], Awaitable[None]] | None = None,
) -> None:
    """#2188 startup order: (1) crash-close stale sessions, (2) restore B11 snapshots, (3)
    reload the OMS position cache, and only then (4) open the policy's warm-up gate. A failure
    in any step leaves the gate CLOSED (no grace-expiry stop on a stale position view)."""
    await sessions.recover_on_startup(process_start_us)
    if restore_b11 is not None:
        await restore_b11()
    if reload_positions is not None:
        await reload_positions()
    gate.positions_reloaded()
