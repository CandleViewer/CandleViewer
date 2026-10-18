"""`RecordingPolicy` — the effective recorded set (ADR-0015 decision 1, E16-T02).

effective set = manual list + symbols with a chart open >= `autostart_delay_s`
                + symbols with an open position (immediately)
                + symbols in the stop grace window (B11 `lingering`).

The per-symbol lifecycle is B11 `recording`, built only via `statechart.build` and
driven only via `statechart.gateway`. This class is the synchronous enforcer
(C-2.21): it owns the trigger refs, the start delay and the grace deadline (checked
by `tick()`, a 1 s evaluation driven by the caller — no per-symbol sleeps, no chart
timers, so a restart re-derives deadlines). The chart only records.

Cap (`CV_RECORDER_MAX_SYMBOLS`): manual adds are rejected (422); an auto-start is
refused with a `RecorderCapRefused` warning, a metric and a denied audit record, then
retried every tick. A `position_open` start may pre-empt one evictable symbol. Disk pressure
(E16-T07) refuses a new chart-open start the same way (cause `disk_pressure`), nothing else.

Pin semantics (`set_pin`, audited `retention.change`): a pinned symbol's data is never
deleted by retention (E16-T06), and a pinned symbol is never a pre-emption victim and
is exempt from auto-eviction (E16-T07), like a manual entry. A pin alone does not start
recording; it only protects a symbol that is recording or recorded.

Warm-up gate: until `positions_reloaded()` is called, no stop decision is taken (grace
expiry or pre-emption), because the position cache may not be authoritative yet
(#2188 opens the gate after the startup reconcile).
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Final, Literal, Protocol

import structlog
from pydantic import ValidationError

import candleviewer.statechart.bindings.b11_recording as b11
from candleviewer.bus.models import Topic
from candleviewer.recorder.errors import (
    InvalidRecordedSymbolError,
    InvalidRecorderActorError,
    RecorderSymbolLimitError,
)
from candleviewer.recorder.metrics import (
    recorder_b11_error_total,
    recorder_cap_preempted_total,
    recorder_cap_refused_total,
)
from candleviewer.recorder.models import (
    PRECEDENCE,
    PRIORITY,
    SYSTEM_ACTOR,
    Actor,
    EffectiveEntry,
    Reason,
    RecorderCapRefused,
    RecorderSetChanged,
)
from candleviewer.statechart import build
from candleviewer.statechart.factory import default_clock
from candleviewer.statechart.factory import restore as restore_chart
from candleviewer.statechart.gateway import Gateway
from candleviewer.statechart.persistence import MachineKey, Restorer, SealedSnapshot

MACHINE: Final = "recording"
LANE: Final = "platform"
_ACTIVE: Final = frozenset({"starting", "recording", "degraded", "lingering"})
_SYMBOL_RE: Final = re.compile(r"^[A-Z0-9]{2,30}$")
_SETTLE_YIELDS: Final = 64
Change = Literal["added", "removed", "reason_changed"]
RefusalCause = Literal["symbol_cap", "disk_pressure"]
#: Backoff between `RETRY`s of a B11 machine in `error` (same shape as
#: `ingestion.clock._STEP_RETRY_BACKOFF_S`); the last step repeats.
_RETRY_BACKOFF_S: Final = (1.0, 2.0, 4.0, 8.0, 16.0, 30.0)


def user_actor(user_id: str | None) -> Actor:
    """The typed user principal for manual actions; empty/blank ids are refused."""
    try:
        return Actor(kind="user", id=user_id or "")
    except ValidationError:
        raise InvalidRecorderActorError("a non-empty user id is required") from None


def _valid(symbol: str) -> str:
    if not _SYMBOL_RE.fullmatch(symbol):
        raise InvalidRecordedSymbolError("symbol must match [A-Z0-9]{2,30}")
    return symbol


def logger() -> structlog.stdlib.BoundLogger:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)  # type: ignore[no-any-return]  # structlog returns Any


_BusEvent = RecorderSetChanged | RecorderCapRefused


class BusPublisher(Protocol):
    async def publish(
        self, topic: Topic, event: RecorderSetChanged | RecorderCapRefused
    ) -> None: ...


AuditState = Mapping[str, str | bool | None]


class AuditSink(Protocol):
    """The subset of `AuditWriter.emit` used here, injected (M11 may not import `audit`,
    C-3.3). `env` is the exchange env string the policy runs in (C-2.11)."""

    async def emit(
        self,
        action: str,
        *,
        actor_label: str,
        actor_user_id: str | None,
        object_kind: str,
        object_id: str,
        reason: str,
        after_state: AuditState,
        env: str,
        outcome: str = "success",
    ) -> None: ...


#: (symbol, B11 hook name, chart context) -> None; see `RecordingPolicy.observe_states`.
StateObserver = Callable[[str, str, Mapping[str, object]], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class PolicyConfig:
    """`CV_RECORDER_*` keys (20-architecture.md §7.2)."""

    autostart_delay_s: float = 60.0
    autostop_grace_s: float = 1800.0
    #: Gates chart-open convenience recording only; never position/manual recording.
    autorecord_enabled: bool = True
    max_symbols: int = 20
    #: Distinct symbols tracked for chart-open refs (client-driven, untrusted).
    max_chart_symbols: int = 1024
    #: Distinct ids per symbol per trigger kind.
    max_refs_per_symbol: int = 64


#: The library interpreter, opaque to M11 (only `statechart/` may type it).
_Interp = Any


class _Refusals:
    def __init__(self) -> None:
        self.counts: dict[str, int] = {}

    def record_send_refused(self, reason: str) -> None:
        self.counts[reason] = self.counts.get(reason, 0) + 1


@dataclass(frozen=True, slots=True)
class _Manual:
    actor: Actor
    streams: tuple[str, ...]
    depth: int | None


@dataclass
class _Sym:
    charts: dict[str, float] = field(default_factory=dict)  # chart_id -> opened_at
    positions: set[str] = field(default_factory=set)
    manual: _Manual | None = None
    pinned: bool = False
    linger_deadline: float | None = None
    started_reasons: set[Reason] = field(default_factory=set)  # reasons sent to B11
    #: Reasons refused by the cap (warned once each; retried every tick until started).
    refused: set[Reason] = field(default_factory=set)
    #: Set when this symbol is evicted for a position; the stop audit carries it.
    stop_cause: str | None = None
    error_attempts: int = 0
    retry_at: float | None = None
    #: Actor of the latest manual change (adder or remover) for the next audit record.
    last_actor: Actor = SYSTEM_ACTOR

    def refs(self, reason: Reason) -> list[str]:
        """Trigger refs per reason (not last-writer-wins)."""
        if reason == "manual":
            return [f"manual:{self.manual.actor.id}"] if self.manual else []
        if reason == "position_open":
            return sorted(f"position:{p}" for p in self.positions)
        return sorted(f"chart:{c}" for c in self.charts)

    def idle(self) -> bool:
        return not (self.charts or self.positions or self.manual or self.pinned)


#: Bound on symbols tracked for position/manual triggers (bounded memory, C-2.18).
#: Separate from the chart-ref bound so chart spam cannot starve positions.
MAX_PROTECTED: Final = 1024


class RecordingPolicy:
    def __init__(
        self,
        *,
        bus: BusPublisher,
        audit: AuditSink,
        env: str,
        now: Callable[[], float],
        disk_refuses: Callable[[], bool],
        config: PolicyConfig | None = None,
    ) -> None:
        self._bus, self._audit, self._env, self._now = bus, audit, env, now
        #: E16-T07 `DiskBudget.refuses_auto_record`: a plain bool, read on each new start.
        self._disk_refuses = disk_refuses
        self._cfg = config or PolicyConfig()
        self._syms: dict[str, _Sym] = {}
        self._charts: dict[str, _Interp] = {}
        self._published: dict[str, Reason] = {}
        self._gateway = Gateway()
        self.refusals = _Refusals()
        self._lock = asyncio.Lock()
        self._topic = Topic(env=env, domain="recorder", detail="set_changed")
        self._refused_topic = Topic(env=env, domain="recorder", detail="cap_refused")
        #: Warm-up gate (restart race): until the OMS position cache is authoritative,
        #: no grace expiry may stop a symbol (it could still hold a live position).
        #: Closed on construction; opened by `positions_reloaded()` (E16-T03/T04 wiring
        #: calls it after the startup reconcile).
        self._positions_ready = False
        #: E16-T04: B11 state-entry hooks are forwarded here (SessionManager.on_b11_state) so
        #: the session row mirrors the published state without querying the interpreter.
        self._state_observer: StateObserver | None = None

    def observe_states(self, observer: StateObserver) -> None:
        self._state_observer = observer

    # --- public triggers ---------------------------------------------------------------

    async def on_chart_opened(self, symbol: str, chart_id: str) -> None:
        s = self._sym(symbol, kind="chart")
        if s is None:
            logger().warning("recorder_chart_ref_refused", symbol=symbol, cause="symbol_cap")
            return
        if chart_id not in s.charts and len(s.charts) >= self._cfg.max_refs_per_symbol:
            logger().warning("recorder_chart_ref_refused", symbol=symbol, cause="ref_cap")
            return
        s.charts.setdefault(chart_id, self._now())
        await self._reconcile(symbol)

    async def on_chart_closed(self, symbol: str, chart_id: str) -> None:
        s = self._syms.get(_valid(symbol))
        if s is not None:
            s.charts.pop(chart_id, None)
            await self._reconcile(symbol)

    async def on_position_opened(self, symbol: str, position_id: str) -> None:
        """Money at risk: never refused by the chart caps (C-2.6 spirit, C-4.14)."""
        s = self._sym(symbol, kind="protected")
        if s is None:  # MAX_PROTECTED distinct symbols with positions: an incident, loud
            raise InvalidRecordedSymbolError(f"more than {MAX_PROTECTED} protected symbols")
        s.positions.add(position_id)
        await self._reconcile(symbol)

    async def on_position_closed(self, symbol: str, position_id: str) -> None:
        s = self._syms.get(_valid(symbol))
        if s is not None:
            s.positions.discard(position_id)
            await self._reconcile(symbol)

    async def add_manual(
        self,
        symbol: str,
        actor: Actor,
        streams: tuple[str, ...] = (),
        depth: int | None = None,
    ) -> None:
        if actor.kind != "user":
            raise InvalidRecorderActorError("manual add requires a user actor")
        _valid(symbol)
        existing = self._syms.get(symbol)
        already = existing is not None and existing.manual is not None
        if not already and symbol not in self._active() and self._at_cap():
            raise RecorderSymbolLimitError(f"max {self._cfg.max_symbols} recorded symbols")
        s = self._sym(symbol, kind="protected")
        if s is None:
            raise RecorderSymbolLimitError(f"more than {MAX_PROTECTED} tracked symbols")
        s.manual = _Manual(actor=actor, streams=tuple(streams), depth=depth)
        s.last_actor = actor
        await self._reconcile(symbol)

    async def remove_manual(self, symbol: str, actor: Actor) -> None:
        s = self._syms.get(_valid(symbol))
        if s is None or s.manual is None:
            return
        s.manual, s.last_actor = None, actor
        await self._reconcile(symbol)

    async def set_pin(self, symbol: str, pinned: bool, actor: Actor) -> None:
        """Pinning changes retention/eviction behaviour: audited with its actor (C-2.9)."""
        s = self._sym(symbol, kind="protected")
        if s is None:
            raise RecorderSymbolLimitError(f"more than {MAX_PROTECTED} tracked symbols")
        if s.pinned == pinned:
            return
        await self._audit_emit(
            "retention.change",
            symbol,
            actor,
            reason="pin" if pinned else "unpin",
            extra={"pinned": pinned},
        )
        s.pinned = pinned
        if s.idle():
            self._syms.pop(symbol, None)

    # --- evaluation --------------------------------------------------------------------

    def _sym(self, symbol: str, *, kind: Literal["chart", "protected"]) -> _Sym | None:
        """Get-or-create, within the bound for *kind*; `None` when that bound is full.
        Chart-only symbols and position/manual symbols are counted separately."""
        _valid(symbol)
        s = self._syms.get(symbol)
        if s is not None:
            return s
        chart_only = sum(1 for x in self._syms.values() if not (x.positions or x.manual))
        if kind == "chart" and chart_only >= self._cfg.max_chart_symbols:
            return None
        if kind == "protected" and len(self._syms) - chart_only >= MAX_PROTECTED:
            return None
        s = self._syms[symbol] = _Sym()
        return s

    def _desired(self, s: _Sym) -> set[Reason]:
        out: set[Reason] = set()
        if s.manual is not None:
            out.add("manual")
        if s.positions:
            out.add("position_open")
        delay, now = self._cfg.autostart_delay_s, self._now()
        if self._cfg.autorecord_enabled and any(now - t >= delay for t in s.charts.values()):
            out.add("chart_open")
        return out

    def leaf(self, symbol: str) -> str | None:
        interp = self._charts.get(symbol)
        return None if interp is None else str(next(iter(interp.current_state_ids))).split(".")[1]

    def _active(self) -> set[str]:
        return {sym for sym in self._charts if self.leaf(sym) in _ACTIVE}

    def _at_cap(self) -> bool:
        return len(self._active()) >= self._cfg.max_symbols

    def position_open(self, symbol: str) -> bool:
        """The `StreamWriter` gate's plain predicate (E16-T07): True until the warm-up gate
        opens (the position cache may not be authoritative yet), then the positions set."""
        s = self._syms.get(symbol)
        return not self._positions_ready or (s is not None and bool(s.positions))

    def positions_reloaded(self) -> None:
        """Open the warm-up gate: the position cache now reflects the exchange."""
        self._positions_ready = True

    async def tick(self) -> None:
        """The 1 s evaluation tick: only symbols with a due start (delay elapsed or a
        cap-refused start), grace deadline or error retry are reconciled."""
        for symbol in [sym for sym, s in self._syms.items() if self._due(sym, s)]:
            await self._reconcile(symbol)

    def _due(self, symbol: str, s: _Sym) -> bool:
        now = self._now()
        if self.leaf(symbol) == "error":
            return s.retry_at is None or now >= s.retry_at
        if s.linger_deadline is not None and now >= s.linger_deadline:
            return self._positions_ready
        return bool(self._desired(s) - s.started_reasons)

    async def _reconcile(self, symbol: str) -> None:
        async with self._lock:
            s = self._syms.get(symbol)
            if s is None:
                return
            if self.leaf(symbol) == "error":
                await self._retry_error(symbol, s)
                await self._publish(symbol)
                return
            want = self._desired(s)
            if self._cfg.autorecord_enabled and s.charts and self.leaf(symbol) == "lingering":
                want.add("chart_open")  # continuing an existing session is not a new start
            for reason in sorted(want - s.started_reasons, key=PRECEDENCE.index):
                await self._add(symbol, s, reason)
            for reason in sorted(s.started_reasons - want, key=PRECEDENCE.index):
                await self._remove(symbol, s, reason)
            leaf = self.leaf(symbol)
            if leaf == "lingering" and s.linger_deadline is not None and self._positions_ready:
                if self._now() >= s.linger_deadline:
                    await self._send_recording(
                        symbol, "LINGER_DUE", position_open=bool(s.positions)
                    )
            await self._settle(symbol)
            if not s.started_reasons and self.leaf(symbol) in ("recording", "degraded"):
                await self._linger_orphan(symbol, s)  # last reason left while `starting`
            if self.leaf(symbol) == "stopped":
                await self._prune(symbol)  # keeps `_charts` = live sessions only
            if self.leaf(symbol) is None and s.idle():
                self._syms.pop(symbol, None)
            await self._publish(symbol)

    async def _prune(self, symbol: str) -> None:
        interp = self._charts.pop(symbol, None)
        self._gateway.unregister(symbol)
        if interp is not None:
            await interp.stop()

    async def _retry_error(self, symbol: str, s: _Sym) -> None:
        """B11 `error --RETRY--> starting` with bounded backoff (audit outage, C-2.9)."""
        now = self._now()
        if s.retry_at is not None and now < s.retry_at:
            return
        step = _RETRY_BACKOFF_S[min(s.error_attempts, len(_RETRY_BACKOFF_S) - 1)]
        s.error_attempts += 1
        s.retry_at = now + step
        await self._send_recording(symbol, "RETRY")
        interp = self._charts.get(symbol)
        failed_stop = interp is not None and interp.context.get("direction") == "stopping"
        if failed_stop and self.leaf(symbol) == "recording" and not self._desired(s):
            # RETRY of a failed STOP: finish the stop (audited), never a new session.
            await self._send_recording(symbol, "REASON_REMOVED", linger_until_us=None)
            await self._send_recording(symbol, "LINGER_DUE", position_open=bool(s.positions))
            await self._settle(symbol)
        if self.leaf(symbol) in ("recording", "degraded", "lingering", "stopped"):
            s.error_attempts, s.retry_at = 0, None
        if self.leaf(symbol) == "stopped":
            await self._prune(symbol)

    async def _add(self, symbol: str, s: _Sym, reason: Reason) -> None:
        if self.leaf(symbol) == "error":
            return  # retried by `_retry_error`; the chart keeps its reasons
        new = symbol not in self._active()
        if new and reason == "chart_open" and self._disk_refuses():
            await self._refuse(symbol, s, reason, cause="disk_pressure")
            return
        if new and reason != "manual" and self._at_cap():
            if reason != "position_open" or not await self._preempt_for(symbol):
                await self._refuse(symbol, s, reason)
                return
        if symbol not in self._charts:
            interp = (await build(MACHINE, clock=default_clock(), lane=LANE)).interpreter
            self._register(symbol, interp)
        streams = list(s.manual.streams) if s.manual else []
        if await self._send_recording(
            symbol, "REASON_ADDED", reason=reason, symbol=symbol, streams=streams
        ):
            s.started_reasons.add(reason)
            s.refused.discard(reason)
            s.linger_deadline = None

    async def _refuse(
        self, symbol: str, s: _Sym, reason: Reason, cause: RefusalCause = "symbol_cap"
    ) -> None:
        """Cap or disk refusal: warning event + metric + audit, once per (symbol, reason) until
        it starts; `_due` keeps it queued so every tick retries it."""
        if reason in s.refused:
            return
        s.refused.add(reason)
        recorder_cap_refused_total.labels(reason=reason).inc()
        logger().warning(
            "recorder_cap_refused", symbol=symbol, reason=reason, cause=cause, env=self._env
        )
        await self._audit_emit(
            "recorder.start",
            symbol,
            SYSTEM_ACTOR,
            reason="cap_refused" if cause == "symbol_cap" else cause,
            extra={"trigger": reason},
            outcome="denied",
        )
        ev = RecorderCapRefused(
            symbol=symbol, reason=reason, ts_event=int(self._now() * 1e6), cause=cause
        )
        await self._bus.publish(self._refused_topic, ev)

    async def _preempt_for(self, symbol: str) -> bool:
        """A position is money at risk: stop the lowest-priority evictable symbol to make
        room. Never a victim: manual, pinned, or holding a position. Never while the
        warm-up gate is closed (the position cache is not authoritative yet). The slot
        is freed only once the victim's stop audit succeeded (C-2.9). False -> the
        requester is refused and queued (retried every tick)."""
        if not self._positions_ready:
            return False
        victims = [
            (0 if self.leaf(v) == "lingering" else 1, v)
            for v in self._active()
            if v != symbol
            and (vs := self._syms.get(v)) is not None
            and vs.manual is None
            and not vs.pinned
            and not vs.positions
        ]
        if not victims:
            return False
        victim = min(victims)[1]
        vs = self._syms[victim]
        vs.stop_cause = "cap_preempted"
        for r in list(vs.started_reasons):
            await self._send_recording(victim, "REASON_REMOVED", reason=r, linger_until_us=None)
        vs.started_reasons.clear()
        await self._send_recording(victim, "LINGER_DUE", position_open=False)
        await self._settle(victim)
        if self.leaf(victim) != "stopped":  # stop audit failed: victim stays, in `error`
            return False
        recorder_cap_preempted_total.inc()
        await self._prune(victim)
        vs.linger_deadline = None
        await self._publish(victim)
        return True

    async def _remove(self, symbol: str, s: _Sym, reason: Reason) -> None:
        deadline = self._now() + self._cfg.autostop_grace_s
        if await self._send_recording(
            symbol, "REASON_REMOVED", reason=reason, linger_until_us=int(deadline * 1e6)
        ):
            s.started_reasons.discard(reason)
            if self.leaf(symbol) == "lingering" and s.linger_deadline is None:
                s.linger_deadline = deadline

    async def _linger_orphan(self, symbol: str, s: _Sym) -> None:
        deadline = self._now() + self._cfg.autostop_grace_s
        if await self._send_recording(
            symbol, "REASON_REMOVED", linger_until_us=int(deadline * 1e6)
        ):
            s.linger_deadline = deadline

    def _register(self, symbol: str, interp: _Interp) -> None:
        b11.attach_hook(interp, self._hook)  # per interpreter: never shared across policies
        self._gateway.register(symbol, interp, kind="recording", lane=LANE, metrics=self.refusals)
        self._charts[symbol] = interp

    async def _send_recording(self, symbol: str, event: str, /, **payload: object) -> bool:
        """Refuse (never park on `onUnhandled: defer`, CV-C06) what the leaf cannot take."""
        interp = self._charts.get(symbol)
        ev: dict[str, object] = {"type": event, **payload}
        if interp is None or not interp.can(ev):
            self.refusals.record_send_refused("unhandled")
            return False
        await self._gateway.send(symbol, {"type": event, **payload})
        await self._settle(symbol)
        return True

    async def _settle(self, symbol: str) -> None:
        """Let an invoked service (pure hand-off) reach its outcome; bounded yields only."""
        interp = self._charts.get(symbol)
        if interp is None:
            return
        for _ in range(_SETTLE_YIELDS):
            busy = interp.pending_events or self.leaf(symbol) in ("starting", "stopping")
            if not busy:
                return
            await asyncio.sleep(0)

    # --- outputs -----------------------------------------------------------------------

    def _entry(self, symbol: str) -> EffectiveEntry | None:
        if self.leaf(symbol) not in _ACTIVE:
            return None
        s = self._syms.get(symbol) or _Sym()
        held = sorted(s.started_reasons, key=PRECEDENCE.index)
        lingering = self.leaf(symbol) == "lingering" or not held
        top: Reason = held[0] if held else self._last_reason(symbol)
        return EffectiveEntry(
            symbol=symbol,
            reason=top,
            reasons=tuple(held),
            priority=PRIORITY[top],
            auto_evictable=top != "manual",
            lingering=lingering,
            pinned=s.pinned,
            streams=s.manual.streams if s.manual else (),
            depth=s.manual.depth if s.manual else None,
        )

    def _last_reason(self, symbol: str) -> Reason:
        return self._published.get(symbol, "chart_open")

    def effective_set(self) -> dict[str, EffectiveEntry]:
        out = {sym: self._entry(sym) for sym in self._charts}
        return {sym: e for sym, e in out.items() if e is not None}

    async def _publish(self, symbol: str) -> None:
        entry, prev = self._entry(symbol), self._published.get(symbol)
        if entry is None and prev is None:
            return
        if entry is not None and entry.reason == prev:
            return
        change: Change = (
            "removed" if entry is None else "added" if prev is None else "reason_changed"
        )
        reason: Reason = entry.reason if entry is not None else prev or "chart_open"
        event = RecorderSetChanged(
            symbol=symbol,
            change=change,
            reason=reason,
            reasons=entry.reasons if entry is not None else (),
            priority=PRIORITY[reason],
            auto_evictable=reason != "manual",
            ts_event=int(self._now() * 1e6),
        )
        if entry is None:
            self._published.pop(symbol, None)
        else:
            self._published[symbol] = entry.reason
        await self._bus.publish(self._topic, event)

    async def _hook(self, name: str, context: Mapping[str, object]) -> None:
        """B11 side effects for THIS policy's charts. Audit is write-ahead and raises if
        unavailable, so the service fails and the chart goes to `error` (C-2.9)."""
        symbol = str(context.get("symbol") or "")
        if self._state_observer is not None:
            try:
                await self._state_observer(symbol, name, context)
            except Exception as exc:  # the mirror never fails the chart's audited I/O
                logger().error(
                    "recorder_session_mirror_failed", symbol=symbol, error=type(exc).__name__
                )
        if name == "error":
            recorder_b11_error_total.labels(env=self._env).inc()
            logger().error(
                "recorder_b11_error", symbol=symbol, env=self._env, error=context.get("error")
            )
            return
        if name not in ("subscribe", "unsubscribe"):
            logger().info("recorder_b11_event", hook=name, symbol=symbol, env=self._env)
            return
        s = self._syms.get(symbol) or _Sym()
        raw = context.get("reasons")
        held = [r for r in PRECEDENCE if isinstance(raw, list) and r in raw]
        reason: Reason = held[0] if held else self._published.get(symbol, "chart_open")
        actor = s.last_actor if reason == "manual" else SYSTEM_ACTOR
        cause = s.stop_cause if name == "unsubscribe" else None
        await self._audit_emit(
            "recorder.start" if name == "subscribe" else "recorder.stop",
            symbol,
            actor,
            reason=cause or reason,
            extra={"trigger_ref": ",".join(s.refs(reason)) or None},
        )
        if name == "unsubscribe":
            s.stop_cause = None

    async def _audit_emit(
        self,
        action: str,
        symbol: str,
        actor: Actor,
        *,
        reason: str,
        extra: Mapping[str, str | bool | None],
        outcome: str = "success",
    ) -> None:
        await self._audit.emit(
            action,
            actor_label=f"{actor.kind}:{actor.id}",
            actor_user_id=actor.id if actor.kind == "user" else None,
            object_kind="recorded_symbol",
            object_id=symbol,
            reason=reason,
            after_state={"symbol": symbol, "reason": reason, "actor": actor.id, **extra},
            env=self._env,
            outcome=outcome,
        )

    # --- lifecycle ---------------------------------------------------------------------

    async def restore(self, restorer: Restorer, key: MachineKey, sealed: SealedSnapshot) -> None:
        """Rehydrate one symbol's chart via `statechart.persistence` only. Reasons already
        recorded in the snapshot are adopted, so no duplicate session (REASON_ADDED from
        idle/stopped) is opened for a symbol that was recording or lingering."""
        res = await restore_chart(restorer, key, sealed)
        symbol = key.entity_id
        self._register(symbol, res.interpreter)
        s = self._sym(symbol, kind="protected") or _Sym()
        s.started_reasons = {r for r in res.interpreter.context.get("reasons") or ()}
        if self.leaf(symbol) == "lingering":
            until = res.interpreter.context.get("linger_until_us")
            s.linger_deadline = None if until is None else until / 1e6
        if self.leaf(symbol) in _ACTIVE:
            top = sorted(s.started_reasons, key=PRECEDENCE.index)
            self._published[symbol] = top[0] if top else "chart_open"

    async def stop(self) -> None:
        for symbol in list(self._charts):
            interp = self._charts.pop(symbol)
            self._gateway.unregister(symbol)
            await interp.stop()
