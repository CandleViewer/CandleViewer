"""`SessionChart`: per-session B16 `session` interpreters, driven by
`StepUpService` (E09-S04, PR #1674 security review finding 3).

C-2.21: the synchronous step-up code has already enforced (and persisted to the
`sessions` row) before any event is sent here; the chart only *records*. Its
audit actions write through the sink the composition root installs
(`b16_session.set_audit_sink`), so a recording failure surfaces as
`SessionChartError` and the HTTP edge refuses to answer 2xx (C-2.9).

A chart is built lazily, the first time a session needs one in this process,
and hydrated from the persisted row with `replay=True` events (already audited
when they happened, so not re-recorded). Charts are bounded per process
(C-2.18) and dropped once revoked.

A chart that has ended, or is past the state an event must reach, never takes
an event it must record quietly (#5512): the send raises
`SessionChartUnrecorded` and the chart is dropped, to be rebuilt from the row
on its next use.
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from datetime import datetime
from typing import Any, Final, Literal

import structlog

from candleviewer.auth.models import SessionRecord
from candleviewer.observability.context import current_request_uuid
from candleviewer.statechart import build
from candleviewer.statechart.bindings import b16_session
from candleviewer.statechart.factory import default_clock
from candleviewer.statechart.gateway import ALWAYS_ADMIT, Gateway, receipt_is_conclusive
from candleviewer.statechart.plugins import FeedBinding, MachineStatePort, feed_plugins

#: Max live interpreters per process; least-recently-used is stopped first
#: (it is rebuilt from the row on next use).
MAX_CHARTS = 1024
_US = 1_000_000
#: Await each event's macrostep receipt so a failed audit action surfaces to
#: the caller (C-2.9). Safe: see `_send` (not an action; CV-C51 n/a).
_AWAIT_STEP = True
#: B16.7 (C-2.9): the state each of these events must reach. A step that moves
#: both regions can roll one back while the receipt reads `error=None` (CV-C06),
#: so the configuration, not the receipt, proves that the region holding the
#: event's audit action (`auth.idle_locked`, `auth.session_revoked`) committed.
_MUST_REACH: dict[str, str] = {
    "IDLE_DEADLINE": "auth.idle_locked",
    "LOGOUT": "auth.revoked",
    "ABSOLUTE_DEADLINE": "auth.revoked",
    "REVOKE": "auth.revoked",
}
#: C-2.9 (#5512): the B16 events with a transition that writes an audit record, by its own
#: actions or by the entry actions of the state it enters (catalogue B16.2, B16.3). Synchronous
#: code has decided each one before it is sent. `ELEVATION_DEADLINE` and `READONLY_EXPIRED` write
#: none.
_MUST_RECORD: frozenset[str] = frozenset(
    {
        "MFA_OK",
        "MFA_FAILED",
        "MFA_TIMEOUT",
        "REQUEST",
        "IDLE_DEADLINE",
        "ABSOLUTE_DEADLINE",
        "REVOKE",
        "LOGOUT",
        "UNLOCK_OK",
        "UNLOCK_FAILED",
        "STEP_UP_OK",
        "STEP_UP_FAILED",
        "ACTION_REQUEST",
    }
)
#: B16.2's final `elevation` state, which only a revocation reaches; an event it holds never runs.
_ENDED = "session.elevation.dead"
#: #5512: the bound (s) on stopping a dropped chart; its caller may still hold the row locks.
CHART_STOP_TIMEOUT_S: Final = 1.0


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


class SessionChartError(RuntimeError):
    """The B16 chart refused or failed to record an event (e.g. audit down)."""


class SessionChartUnrecorded(SessionChartError):
    """#5512 (C-2.9): the chart did not record *event*, which it had to (`_MUST_RECORD`): past its
    end, or as a `STEP_UP_OK`, it held the event (`deferred`), or one of `_MUST_REACH` changed
    nothing (`unchanged`): the chart was already past the state it must reach, whose entry writes
    the record. A `SessionChartError`, so every caller's arm for a failed record applies; the
    chart has been dropped."""

    def __init__(self, event: str, reason: Literal["deferred", "unchanged"]) -> None:
        super().__init__(f"B16 {event}: {reason}")
        self.event = event
        self.reason = reason


class _Refusals:
    """`RefusalRecorder` for the gateway: counts refused sends by reason."""

    def __init__(self) -> None:
        self.counts: dict[str, int] = {}

    def record_send_refused(self, reason: str) -> None:
        self.counts[reason] = self.counts.get(reason, 0) + 1


def to_us(when: datetime) -> int:
    return int(when.timestamp() * _US)


class SessionChart:
    def __init__(
        self, *, max_charts: int = MAX_CHARTS, feed: MachineStatePort | None = None
    ) -> None:
        self._feed = feed  # 23 §6.4: each chart publishes `machines.session:{id}.state`
        self._charts: OrderedDict[str, Any] = OrderedDict()
        self._gateway = Gateway(admission=ALWAYS_ADMIT)  # E50-T63: until it adopts the bundle
        self.refusals = _Refusals()
        self._lock = asyncio.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._max = max_charts

    def _bind_loop(self) -> None:
        """Interpreters are bound to the loop they started on. If the running
        loop changed (the old one closed), the cached charts are unusable:
        drop them; each is rebuilt from its `sessions` row on next use."""
        loop = asyncio.get_running_loop()
        if loop is not self._loop:
            self._loop = loop
            self._charts = OrderedDict()
            self._gateway = Gateway(admission=ALWAYS_ADMIT)
            self._lock = asyncio.Lock()

    def interpreter(self, session_id: str) -> Any | None:
        """The live interpreter for *session_id* (tests / supervision)."""
        return self._charts.get(session_id)

    def state(self, session_id: str) -> frozenset[str]:
        interp = self._charts.get(session_id)
        if interp is None:
            return frozenset()
        return frozenset(s.split(".", 1)[1] for s in interp.current_state_ids)

    def in_state(self, session_id: str, state: str) -> bool:
        """`state` is a leaf name (`elevated`) or a region path (`elevation.elevated`)."""
        return any(s == state or s.endswith("." + state) for s in self.state(session_id))

    async def _send(self, sid: str, event: str, **payload: Any) -> None:
        """Send via the statechart gateway (the only send path, E50-T15) and
        wait for this event's macrostep. A receipt is read only through
        `receipt_is_conclusive` (CV-C06): an action error (e.g. audit down)
        fails loud; a deferred/no-op receipt alone is no error (the chart
        records, it never gates: C-2.21) unless the event must be recorded
        (below). An event in `_MUST_REACH` also fails loud unless the chart
        reached its state (B16.7). An event that is not a replay carries the
        id of the request it happens in, a UUID string, or none outside a
        request (#3990): B16's actions run in the chart's own task, outside
        the request's context, so the id rides on the payload and its audit
        record names it. It is always this request's: no caller sets it.

        #5512 (C-2.9): a send of a `_MUST_RECORD` event that is not a replay
        raises `SessionChartUnrecorded` when the chart cannot record it: the
        chart is past its end (`elevation.dead`, which only a revocation
        reaches) and holds the event for good (`deferred`), or a `_MUST_REACH`
        event's receipt is not conclusive (its step changed nothing: the chart
        was already past the state, so the entry that writes the record did
        not run). A held `STEP_UP_OK` raises in any state (`deferred`). The
        chart is dropped first, so a held event never runs later and the next
        use rebuilds the chart from the row."""
        replay = bool(payload.get("replay"))
        if not replay:
            request_uuid = current_request_uuid()
            payload["request_id"] = None if request_uuid is None else str(request_uuid)
        # Called from request handlers only - never from a B16 action - so the
        # CV-C51 self-receipt hang cannot arise (no action awaits this chart).
        receipt = await self._gateway.send(sid, {"type": event, **payload}, wait=_AWAIT_STEP)
        if receipt_is_conclusive(receipt) and receipt.error is not None:
            raise SessionChartError(f"B16 {event}: {type(receipt.error).__name__}")
        must_reach = _MUST_REACH.get(event)
        # A replay was recorded when it happened (`_hydrate`), so it is never refused here.
        if event in _MUST_RECORD and not replay:
            # The hold check reads the held chart's state from its receipt. A held `STEP_UP_OK`
            # raises in any state, so the step-up ends its grant (`StepUpUnrecorded`).
            if getattr(receipt, "deferred", False) is True and (
                event == "STEP_UP_OK" or _ENDED in getattr(receipt, "state_ids", ())
            ):
                await self._drop(sid)
                raise SessionChartUnrecorded(event, "deferred")
            if must_reach is not None and not receipt_is_conclusive(receipt):
                await self._drop(sid)
                raise SessionChartUnrecorded(event, "unchanged")
        if must_reach is not None and not self.in_state(sid, must_reach):
            raise SessionChartError(f"B16 {event}: {must_reach} not reached")

    async def _hydrate(self, sid: str, record: SessionRecord, now: datetime) -> None:
        await self._send(sid, "MFA_OK", replay=True)
        for cls, until in record.step_up_elevations.items():
            if cls in b16_session.ACTION_CLASSES and until > now:
                await self._send(
                    sid,
                    "STEP_UP_OK",
                    replay=True,
                    action_class=cls,
                    elevated_until_us=to_us(until),
                )
        downgraded = record.readonly_until is not None and record.readonly_until > now
        strikes = b16_session.STEP_UP_FAILURE_CAP if downgraded else record.step_up_failures
        for _ in range(min(strikes, b16_session.STEP_UP_FAILURE_CAP)):
            await self._send(sid, "STEP_UP_FAILED", replay=True, now_us=to_us(now))

    async def _get(self, record: SessionRecord, now: datetime) -> Any:
        sid = str(record.id)
        self._bind_loop()
        async with self._lock:
            interp = self._charts.get(sid)
            if interp is not None:
                self._charts.move_to_end(sid)
                return interp
            result = await build(
                "session",
                ctx={"session_id": sid, "user_id": str(record.user_id)},
                clock=default_clock(),
                lane="control",
                plugins=feed_plugins(self._feed, FeedBinding("session", sid, user=record.user_id)),
            )
            interp = result.interpreter
            self._gateway.register(
                sid, interp, kind="session", lane="control", metrics=self.refusals
            )
            try:
                await self._hydrate(sid, record, now)
            except BaseException:
                self._gateway.unregister(sid)
                await interp.stop()
                raise
            self._charts[sid] = interp
            while len(self._charts) > self._max:
                old_sid, old = self._charts.popitem(last=False)
                self._gateway.unregister(old_sid)
                await old.stop()
            return interp

    async def _observed(self, record: SessionRecord, now: datetime) -> Any:
        """The session's interpreter, built and hydrated from *record* if needed, with
        an idle lock the row shows but the chart has not seen yet recorded first
        (INV-B16-e, #2301): `IDLE_DEADLINE`, and no other event. The event carries the lock's
        own moment from the row (`idle_locked_at_us`, #4743), never the time of this read: a
        lock by request's `locked_at` (`POST /auth/lock` sends the chart nothing), else the
        idle deadline that fell due; `auth.idle_locked` records it. It goes to any chart not
        in `idle_locked` (#5512): one that cannot take it raises (`_send`)."""
        interp = await self._get(record, now)
        sid = str(record.id)
        if record.is_idle_locked(now=now) and not self.in_state(sid, "idle_locked"):
            before = b16_session.elevation_view(dict(interp.context))
            moment = record.locked_at if record.locked_at is not None else record.idle_deadline()
            await self._send(sid, "IDLE_DEADLINE", before=before, idle_locked_at_us=to_us(moment))
        return interp

    async def observe(self, record: SessionRecord, now: datetime) -> None:
        """Bring the chart up to the row and send nothing else. `POST /auth/unlock`
        (#2300) records the lock with it before `unlock()` runs (B16.7), so the
        route never sends `REQUEST`; a failed `auth.idle_locked` raises here."""
        await self._observed(record, now)

    async def record(
        self, record: SessionRecord, now: datetime, event: str, **payload: Any
    ) -> None:
        """Send *event* to the session's chart, after enforcement already ran.

        `before` (the elevation view prior to the event) rides on the payload
        so the audit action can write before/after state (C-12.8). An idle
        lock the row shows but the chart has not seen yet is recorded first
        (INV-B16-e, #2301): an unlock is recorded against the still-locked row."""
        interp = await self._observed(record, now)
        before = b16_session.elevation_view(dict(interp.context))
        await self._send(str(record.id), event, before=before, **payload)

    async def revoke(self, record: SessionRecord, now: datetime, reason: str) -> None:
        """Session revoked by sync code: record `REVOKE`, then drop the chart. #5512: the
        chart is dropped however the record ends (written, refused, or cut short by the
        caller's bound), at once (`_drop`), so a slow audit writer never leaves a revoked
        chart cached over a row that stays live."""
        try:
            await self.record(record, now, "REVOKE", reason=reason)
        finally:
            await self._drop(str(record.id))

    async def _drop(self, session_id: str) -> None:
        """Drop the session's chart at once, never waiting for `_lock`, which another session's
        build may hold while the caller holds the session's row locks: it leaves the cache and
        the gateway here, and its next use rebuilds it from the row. Its interpreter is then
        stopped within `CHART_STOP_TIMEOUT_S`, no longer than the role change's drop bound. A stop
        that fails or overruns is logged with its error class only (C-12.6) and never replaces
        what the caller raises or returns; a new cancellation goes on."""
        self._bind_loop()
        interp = self._charts.pop(session_id, None)
        if interp is None:  # none cached; one being built comes from the row
            return
        self._gateway.unregister(session_id)
        try:
            async with asyncio.timeout(CHART_STOP_TIMEOUT_S):
                await interp.stop()
        except Exception as exc:  # a timeout included; logged, never the caller's outcome
            _log().error(
                "auth.session_chart.chart_not_stopped",
                session_id=session_id,
                error=type(exc).__name__,
            )

    async def forget(self, session_id: str) -> None:
        """Drop the session's chart without recording anything; its next use rebuilds it
        from the `sessions` row, as after an eviction. `POST /auth/unlock` (#2300) drops a
        chart that failed to record an outcome the session service already committed."""
        self._bind_loop()
        async with self._lock:
            interp = self._charts.pop(session_id, None)
            self._gateway.unregister(session_id)
        if interp is not None:
            await interp.stop()

    async def stop(self) -> None:
        self._bind_loop()
        async with self._lock:
            charts, self._charts = list(self._charts.items()), OrderedDict()
        for sid, interp in charts:
            self._gateway.unregister(sid)
            await interp.stop()


__all__ = ["MAX_CHARTS", "SessionChart", "SessionChartError", "SessionChartUnrecorded", "to_us"]
