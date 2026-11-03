"""`AlertEvaluator` — the server-side alert evaluator (M22 heart, E40-T03, ADR-0032 option B).

A separate, notify-only evaluator over the E35 metric bus: it calls E35's `evaluate`,
`SnapshotBuilder` and `MetricSource` directly, keeps **one subscription per distinct
`condition_hash`** and fans each result out to the member alerts. It runs in its own
tracked task (ADR-0032: isolated from rule evaluation) behind a bounded queue that sheds
the oldest tick with a counted metric (C-2.18). Condition evaluation is plain code
(C-2.20); each firing's lifecycle is recorded on a B10 chart (`alerts.lifecycle`).

Alerts never place or modify orders: the only side effects are `alert_deliveries` /
`outbox` rows, `alerts` counters, audit records and metrics.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Final, Protocol

import structlog
from pydantic import ValidationError

from candleviewer.alerts.gating import (
    AlertState,
    Muted,
    StormSuppressor,
    gate,
    to_ms,
)
from candleviewer.alerts.models import AlertCondition
from candleviewer.alerts.owners import OwnerGate
from candleviewer.alerts.ports import (
    AlertRecord,
    AuditSink,
    DisarmReason,
    FiringStore,
    MetricChildLike,
)
from candleviewer.observability import spawn
from candleviewer.rules.evaluator import MetricSource, SnapshotBuilder
from candleviewer.rules.evaluator.nodes import (
    EvalContext,
    InstanceState,
    evaluate,
    referenced_metrics,
)
from candleviewer.rules.evaluator.snapshot import Value
from candleviewer.rules.ir.models import MetricRef


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


QUEUE_BOUND: Final = 1024
SUMMARY_CHANNEL: Final = "in_app"
#: Provisional wording until E40-D02's copy deck lands (ticket a11y note); one place only.
SUMMARY_TITLE: Final = "{n} further alerts fired for {first}{others}"
DISARM_TITLE: Final = "Alert disarmed: {metric} data source unavailable"


@dataclass(frozen=True, slots=True)
class AlertTick:
    """One evaluation trigger from a metric producer (never per book delta, C-2.20)."""

    trigger_type: str
    event_ts_ms: int
    symbol: str | None = None


@dataclass(slots=True)
class _Subscription:
    condition: AlertCondition
    refs: tuple[MetricRef, ...]
    members: set[str] = field(default_factory=set)
    state: dict[str, InstanceState] = field(default_factory=dict)  # per symbol instance


@dataclass(slots=True)
class _Storm:
    """Suppressed firings in one user's storm window, flushed as ONE summary delivery."""

    window_end_ms: int
    alert_id: str
    count: int = 0
    symbols: dict[str, None] = field(default_factory=dict)


class AlertMetrics:
    """Ticket "Observability" names; children are injected (facade-registered in app)."""

    def __init__(self, sink: Callable[[str, tuple[str, ...]], MetricChildLike] | None = None):
        self._sink = sink

    def child(self, name: str, *labels: str) -> MetricChildLike | None:
        return None if self._sink is None else self._sink(name, labels)

    def inc(self, name: str, *labels: str) -> None:
        c = self.child(name, *labels)
        if c is not None:
            c.inc()

    def set(self, name: str, value: float) -> None:
        c = self.child(name)
        if c is not None:
            c.set(value)

    def observe(self, name: str, value: float) -> None:
        c = self.child(name)
        if c is not None:
            c.observe(value)


class ChartRecorder(Protocol):
    """B10 lifecycle recorder (`alerts.lifecycle.AlertCharts`): records, never decides."""

    async def fired(
        self,
        alert_id: str,
        delivery_ids: Sequence[int],
        channels: Sequence[str],
        *,
        owner: str | None = None,
    ) -> None: ...

    async def suppressed(
        self, alert_id: str, window_end_ms: int, *, owner: str | None = None
    ) -> None: ...

    async def suppression_expired(self, alert_id: str, *, owner: str | None = None) -> None: ...

    async def disabled(self, alert_id: str, *, owner: str | None = None) -> None: ...


#: `MetricValue.reason`s meaning the data source itself is gone (vs. warming up / stale).
SOURCE_LOST_REASONS: Final = frozenset({"source_unavailable", "source_degraded"})
#: Gate -> `cv_alert_suppressed_total{reason}` (bounded label set from the ticket).
_SUPPRESS_REASON: Final[dict[str, str]] = {
    "snoozed": "snoozed", "muted": "muted", "expired": "expired", "cooldown": "cooldown",
}  # fmt: skip


def _never(_a: AlertState) -> bool:
    return False  # E40-S02 mute preferences / critical-override list not shipped yet


def _wall_ms() -> int:
    return time.time_ns() // 1_000_000


def _dt(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=UTC)


def _jsonable(v: Value) -> Any:
    return str(v) if isinstance(v, Decimal) else v


def state_of(row: AlertRecord) -> AlertState:
    """Row -> in-memory state. Cooldown memory is rebuilt from `last_fired_at` (wall
    clock, as the cooldown gate uses wall clock); `once_per_bar` memory from the stored
    `last_bar_open_ms` of the latest firing (exchange event time, as the bar gate uses),
    so a restart can re-open neither a cooldown window nor an already-fired bar."""
    cond = AlertCondition.model_validate(row.condition_ir)
    a = AlertState(
        id=row.id, owner_user_id=row.owner_user_id, name=row.name, symbol=row.symbol,
        condition_hash=row.condition_hash, trigger_mode=row.trigger_mode,
        cooldown_seconds=row.cooldown_seconds, severity=row.severity,
        channels=tuple(row.channels), message_template=row.message_template,
        timeframe=cond.trigger.timeframe, enabled=row.enabled,
        expires_at_ms=to_ms(row.expires_at), snoozed_until_ms=to_ms(row.snoozed_until),
        last_fired_ms=to_ms(row.last_fired_at),
    )  # fmt: skip
    last_bar: int | None = getattr(row, "last_bar_open_ms", None)
    if a.trigger_mode == "once_per_bar" and last_bar is not None:
        a.remember_bar(last_bar)
    return a


class AlertEvaluator:
    """Warm-up, live reconfiguration, per-tick evaluation, gating, firing, storm, disarm."""

    def __init__(
        self,
        store: FiringStore,
        source: MetricSource,
        *,
        owners: OwnerGate,
        charts: ChartRecorder | None = None,
        audit: AuditSink | None = None,
        metrics: AlertMetrics | None = None,
        storm: StormSuppressor | None = None,
        muted: Muted = _never,
        critical_override: Muted = _never,
        clock: Callable[[], int] = _wall_ms,
        perf: Callable[[], float] = time.perf_counter,
        queue_bound: int = QUEUE_BOUND,
    ) -> None:
        self._store, self._charts, self._audit, self._owners = store, charts, audit, owners
        self._snapshots = SnapshotBuilder(source)
        self.metrics = metrics or AlertMetrics()
        self.storm = storm or StormSuppressor()
        self._muted, self._override = muted, critical_override
        self._clock, self._perf = clock, perf
        self.alerts: dict[str, AlertState] = {}
        self.subscriptions: dict[str, _Subscription] = {}
        self._storms: dict[str, _Storm] = {}
        self._lock = asyncio.Lock()  # one firing transaction at a time per process
        self._queue: asyncio.Queue[AlertTick] = asyncio.Queue(maxsize=queue_bound)
        self._task: asyncio.Task[None] | None = None
        self._inflight: asyncio.Task[None] | None = None
        self.dropped = 0

    # --- subscriptions -------------------------------------------------------------

    def _subscribe(self, a: AlertState, condition: AlertCondition) -> None:
        sub = self.subscriptions.get(a.condition_hash)
        if sub is None:
            refs = tuple(referenced_metrics(condition.conditions))
            sub = self.subscriptions[a.condition_hash] = _Subscription(condition, refs)
        sub.members.add(a.id)

    def _unsubscribe(self, a: AlertState) -> None:
        sub = self.subscriptions.get(a.condition_hash)
        if sub is not None:
            sub.members.discard(a.id)
            if not sub.members:  # last referent left: drop the subscription
                del self.subscriptions[a.condition_hash]

    def _gauges(self) -> None:
        self.metrics.set("cv_alerts_armed", sum(a.enabled for a in self.alerts.values()))
        self.metrics.set("cv_alert_subscriptions", len(self.subscriptions))

    def _admit(self, row: AlertRecord) -> None:
        old = self.alerts.pop(row.id, None)
        if old is not None:
            self._unsubscribe(old)
        if not row.enabled:
            return
        try:
            a = state_of(row)
            cond = AlertCondition.model_validate(row.condition_ir)
        except ValidationError:
            _log().error("alert_condition_invalid", alert_id=row.id)
            return
        if old is not None and old.condition_hash == a.condition_hash:
            a.fired_bars.update(old.fired_bars)  # same condition: bar memory survives edits
        self.alerts[a.id] = a
        self._subscribe(a, cond)

    async def warm_up(self) -> None:
        """One subscription per distinct `condition_hash`, fanned out to its alerts."""
        self.alerts.clear()
        self.subscriptions.clear()
        for row in await self._store.load_live():
            self._admit(row)
        self._gauges()

    async def on_alert_changed(self, alert_id: str) -> None:
        """The in-process create/update/delete/enable/snooze event (`alerts.events`):
        re-read the row; a changed condition re-keys its subscription."""
        row = await self._store.get(alert_id)
        if row is None:  # soft-deleted
            old = self.alerts.pop(alert_id, None)
            if old is not None:
                self._unsubscribe(old)
        else:
            self._admit(row)
        self._gauges()

    # --- tick loop (own task, bounded queue, ADR-0032 isolation) --------------------

    def submit(self, tick: AlertTick) -> None:
        """Sync, non-blocking. A full queue sheds the OLDEST tick, counted (C-2.18)."""
        if self._queue.full():
            with contextlib.suppress(asyncio.QueueEmpty):
                self._queue.get_nowait()
                self.dropped += 1
                self.metrics.inc("cv_alert_eval_dropped_total")
        self._queue.put_nowait(tick)
        self.metrics.set("cv_alert_eval_queue_depth", self._queue.qsize())

    def start(self) -> None:
        if self._task is None:
            self._task = spawn(self._run(), name="alert-evaluator")

    async def _run(self) -> None:
        while True:
            tick = await self._queue.get()
            self.metrics.set("cv_alert_eval_queue_depth", self._queue.qsize())
            self._inflight = spawn(self.process(tick), name="alert-eval-tick")
            try:
                await asyncio.shield(self._inflight)
            except asyncio.CancelledError:
                raise
            except Exception:  # one bad tick must not kill the evaluator task
                _log().exception("alert_tick_failed")

    async def stop(self, grace_s: float) -> None:
        """Graceful drain: an in-flight firing transaction completes (or the store rolls
        it back whole) before shutdown; pending storm summaries are flushed."""
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        inflight, self._inflight = self._inflight, None
        if inflight is not None and not inflight.done():
            with contextlib.suppress(Exception):
                await asyncio.wait_for(asyncio.shield(inflight), grace_s)
        await self.flush_storms(force=True)

    # --- evaluation: once per subscription, fanned out to members -------------------

    async def process(self, tick: AlertTick) -> None:
        start, now = self._perf(), self._clock()
        await self.flush_storms()
        self._snapshots.new_tick()  # memo shared by every subscription on this tick
        for sub in list(self.subscriptions.values()):
            if sub.condition.trigger.type != tick.trigger_type:
                continue
            members = [
                a for i in sorted(sub.members) if (a := self.alerts.get(i)) is not None
                and (tick.symbol is None or a.symbol in (None, tick.symbol))
            ]  # fmt: skip
            if not members:
                continue
            snap = self._snapshots.build(sub.refs, now)
            lost = sorted(r.metric for r in sub.refs if snap.get(r).reason in SOURCE_LOST_REASONS)
            if lost:
                for a in await self._active(members):
                    await self.disarm(a.id, lost[0])
                continue
            state = sub.state.setdefault(tick.symbol or "*", InstanceState())
            if snap.stale_keys():
                continue  # fail-safe (E35 E7): never fire on stale data
            ctx = EvalContext(snap, state, now, lambda: None)
            if not evaluate(sub.condition.conditions, ctx):
                continue
            values = {k: _jsonable(v) for k, v in ctx.metric_values.items()}
            for a in await self._active(members):
                await self._candidate(a, tick, now, values, start)

    async def _active(self, members: list[AlertState]) -> list[AlertState]:
        """The members whose owner is active (#3349, UL-F8), asked once the condition holds or a
        source is lost, before any gate and outside the firing lock. A skipped alert is left as it
        was (armed; no firing, disarm, cooldown, `once` or bar memory used), so enabling the user
        again resumes it. Each skip is counted; an unreadable status skips too (fail closed)."""
        skipped = await self._owners.skipped({a.owner_user_id for a in members})
        for a in members:
            if (why := skipped.get(a.owner_user_id)) is not None:
                self.metrics.inc("cv_alert_owner_skipped_total", "evaluate", why)
        return [a for a in members if a.owner_user_id not in skipped]

    async def _candidate(
        self, a: AlertState, tick: AlertTick, now: int, values: dict[str, Any], start: float
    ) -> None:
        async with self._lock:  # gate + commit atomically w.r.t. this process
            r = gate(a, now, tick.event_ts_ms, self.storm,
                     muted=self._muted, critical_override=self._override)  # fmt: skip
            context = {
                "condition_hash": a.condition_hash, "trigger_type": tick.trigger_type,
                "symbol": tick.symbol, "event_ts_ms": tick.event_ts_ms, "evaluated_at_ms": now,
                "values": values, "bar_open_ms": r.bar_open, "gates": list(r.checked),
            }  # fmt: skip
            if r.storm:
                await self._suppress(a, now, context)
                return
            if not r.passed:
                if r.reason in _SUPPRESS_REASON:
                    self.metrics.inc("cv_alert_suppressed_total", _SUPPRESS_REASON[r.reason])
                if r.reason == "expired":
                    # No timer expiry: only `expires_at` disarms. The row is untouched, so
                    # the API presents it as Triggered/Expired instead of it vanishing.
                    self._retire(a)
                return
            await self._fire(a, now, context, r.bar_open, start)

    def _title(self, a: AlertState) -> str:
        return a.message_template or a.name

    async def _fire(
        self, a: AlertState, now: int, context: dict[str, Any], bar: int | None, start: float
    ) -> None:
        once = a.trigger_mode == "once"
        ids = await self._store.record_firing(
            alert_id=a.id, user_id=a.owner_user_id, channels=a.channels, status="queued",
            title=self._title(a), body="", context=context, fired_at=_dt(now),
            once=once, bump=True,
        )  # fmt: skip
        if ids is None:  # `once` lost the conditional-update race: discard this firing
            a.enabled = False
            self._retire(a)
            return
        a.last_fired_ms = now
        if bar is not None:
            a.remember_bar(bar)
        self.storm.record(a.owner_user_id, now)
        self.metrics.inc("cv_alert_fires_total", a.trigger_mode)
        self.metrics.observe("cv_alert_eval_latency_seconds", self._perf() - start)
        _log().info("alert_fired", alert_id=a.id, condition_hash=a.condition_hash,
                  trigger_mode=a.trigger_mode, delivery_ids=ids)  # fmt: skip
        await self._emit("alert.fired", a, after_state={"delivery_ids": ids, "once": once})
        if self._charts is not None:
            await self._charts.fired(a.id, ids, a.channels, owner=a.owner_user_id)
            if once:
                await self._charts.disabled(a.id, owner=a.owner_user_id)
        if once:
            a.enabled = False
            self._retire(a)

    def _retire(self, a: AlertState) -> None:
        if self.alerts.pop(a.id, None) is not None:
            self._unsubscribe(a)
        self._gauges()

    async def _emit(self, action: str, a: AlertState, **kw: Any) -> None:
        """C-2.9: firings and disarms are audited (system actor; never order actions)."""
        if self._audit is None:
            return
        try:
            await self._audit.emit(
                action, actor_label="system:alert-evaluator", object_kind="alert",
                object_id=a.id, **kw,
            )  # fmt: skip
        except Exception:  # the delivery row is already committed; never lose it
            _log().exception("alert_audit_failed", alert_id=a.id, action=action)

    # --- storm suppression ----------------------------------------------------------

    async def _suppress(self, a: AlertState, now: int, context: dict[str, Any]) -> None:
        """Excess firing: recorded individually as `suppressed` (history keeps all of
        them), no outbox row, trigger-mode memory still advances (a suppressed `once`
        still disarms), and it is folded into the user's one summary delivery."""
        once = a.trigger_mode == "once"
        ids = await self._store.record_firing(
            alert_id=a.id, user_id=a.owner_user_id, channels=(SUMMARY_CHANNEL,),
            status="suppressed", title=self._title(a), body="",
            context=context | {"suppressed_reason": "storm"}, fired_at=_dt(now),
            once=once, bump=True,
        )  # fmt: skip
        if ids is None:
            a.enabled = False
            self._retire(a)
            return
        a.last_fired_ms = now
        if context.get("bar_open_ms") is not None:
            a.remember_bar(int(context["bar_open_ms"]))
        self.metrics.inc("cv_alert_suppressed_total", "storm")
        end = self.storm.window_end(a.owner_user_id, now)
        st = self._storms.setdefault(a.owner_user_id, _Storm(end, a.id))
        st.count += 1
        st.symbols[str(context.get("symbol") or a.symbol or a.name)] = None
        if self._charts is not None:
            await self._charts.suppressed(a.id, end, owner=a.owner_user_id)
        if once:
            a.enabled = False
            self._retire(a)

    def summary_title(self, st: _Storm) -> str:
        syms = list(st.symbols)
        rest = len(syms) - 1
        others = f" and {rest} other{'s' if rest != 1 else ''}" if rest > 0 else ""
        return SUMMARY_TITLE.format(n=st.count, first=syms[0], others=others)

    async def flush_storms(self, *, force: bool = False) -> None:
        """At window end, each user's suppressed firings become ONE summary delivery."""
        now = self._clock()
        for user, st in list(self._storms.items()):
            if not force and now < st.window_end_ms:
                continue
            del self._storms[user]
            # no owner check: the dispatcher drops this summary if the owner is no longer active
            await self._store.record_firing(
                alert_id=st.alert_id, user_id=user, channels=(SUMMARY_CHANNEL,),
                status="queued", title=self.summary_title(st), body="",
                context={"storm_summary": True, "suppressed": st.count,
                         "symbols": list(st.symbols)},
                fired_at=_dt(now), once=False, bump=False,
            )  # fmt: skip
            if self._charts is not None:
                await self._charts.suppression_expired(st.alert_id, owner=user)

    # --- auto-disarm on source loss (US-ALRT-002 scenario 2) ------------------------

    async def disarm(self, alert_id: str, metric: str) -> None:
        """Disarm loudly: `enabled = false` and a delivery stating why, in one transaction.
        Runs under the same lock as firing and the UPDATE is conditional on `enabled`, so a
        disarm can never interleave with a firing of the same alert (either order is safe)."""
        async with self._lock:
            a = self.alerts.get(alert_id)
            if a is None or not a.enabled:
                return
            now = self._clock()
            reason: DisarmReason = "source_unavailable"
            ids = await self._store.record_firing(
                alert_id=a.id, user_id=a.owner_user_id, channels=a.channels, status="queued",
                title=DISARM_TITLE.format(metric=metric), body="",
                context={"disarmed": True, "reason": reason, "metric": metric},
                fired_at=_dt(now), once=False, bump=False,
                disarm_reason=reason,
            )  # fmt: skip
            a.enabled = False
            if ids is None:  # already disarmed (a `once` firing won): nothing to announce
                self._retire(a)
                return
            self.metrics.inc("cv_alert_autodisarmed_total", "source_unavailable")
            await self._emit("alert.disarmed", a, reason="source_unavailable",
                             after_state={"enabled": False, "metric": metric})  # fmt: skip
            if self._charts is not None:
                await self._charts.disabled(a.id, owner=a.owner_user_id)
            self._retire(a)
