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
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from datetime import datetime
from typing import Any

from candleviewer.auth.models import SessionRecord
from candleviewer.statechart import build
from candleviewer.statechart.bindings import b16_session
from candleviewer.statechart.factory import default_clock
from candleviewer.statechart.gateway import Gateway, receipt_is_conclusive

#: Max live interpreters per process; least-recently-used is stopped first
#: (it is rebuilt from the row on next use).
MAX_CHARTS = 1024
_US = 1_000_000
#: Await each event's macrostep receipt so a failed audit action surfaces to
#: the caller (C-2.9). Safe: see `_send` (not an action; CV-C51 n/a).
_AWAIT_STEP = True


class SessionChartError(RuntimeError):
    """The B16 chart refused or failed to record an event (e.g. audit down)."""


class _Refusals:
    """`RefusalRecorder` for the gateway: counts refused sends by reason."""

    def __init__(self) -> None:
        self.counts: dict[str, int] = {}

    def record_send_refused(self, reason: str) -> None:
        self.counts[reason] = self.counts.get(reason, 0) + 1


def to_us(when: datetime) -> int:
    return int(when.timestamp() * _US)


class SessionChart:
    def __init__(self, *, max_charts: int = MAX_CHARTS) -> None:
        self._charts: OrderedDict[str, Any] = OrderedDict()
        self._gateway = Gateway()
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
            self._gateway = Gateway()
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
        fails loud; a deferred/no-op receipt is not an error here — the
        chart records, it never gates (C-2.21)."""
        # Called from request handlers only - never from a B16 action - so the
        # CV-C51 self-receipt hang cannot arise (no action awaits this chart).
        receipt = await self._gateway.send(sid, {"type": event, **payload}, wait=_AWAIT_STEP)
        if receipt_is_conclusive(receipt) and receipt.error is not None:
            raise SessionChartError(f"B16 {event}: {type(receipt.error).__name__}")

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

    async def record(
        self, record: SessionRecord, now: datetime, event: str, **payload: Any
    ) -> None:
        """Send *event* to the session's chart, after enforcement already ran.

        `before` (the elevation view prior to the event) rides on the payload
        so the audit action can write before/after state (C-12.8). An idle
        lock the row shows but the chart has not seen yet is recorded first
        (INV-B16-e, #2301): an unlock is recorded against the still-locked row."""
        interp = await self._get(record, now)
        sid = str(record.id)
        if record.is_idle_locked(now=now) and self.in_state(sid, "active"):
            before = b16_session.elevation_view(dict(interp.context))
            await self._send(sid, "IDLE_DEADLINE", before=before)
        before = b16_session.elevation_view(dict(interp.context))
        await self._send(sid, event, before=before, **payload)

    async def revoke(self, record: SessionRecord, now: datetime, reason: str) -> None:
        """Session revoked by sync code: record `REVOKE`, then drop the chart."""
        await self.record(record, now, "REVOKE", reason=reason)
        self._bind_loop()
        async with self._lock:
            interp = self._charts.pop(str(record.id), None)
            self._gateway.unregister(str(record.id))
        if interp is not None:
            await interp.stop()

    async def stop(self) -> None:
        self._bind_loop()
        async with self._lock:
            charts, self._charts = list(self._charts.items()), OrderedDict()
        for sid, interp in charts:
            self._gateway.unregister(sid)
            await interp.stop()


__all__ = ["MAX_CHARTS", "SessionChart", "SessionChartError", "to_us"]
