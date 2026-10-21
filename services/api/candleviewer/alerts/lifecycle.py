"""`AlertCharts`: B10 `alert` lifecycle recorder (E40-T03, C-2.19).

One chart per live alert, built only through `statechart.factory.build("alert")` and
driven only through `statechart.gateway`. Statecharts record, synchronous code enforces
(C-2.21): by the time an event is sent the evaluator has already gated, decided and
committed. A send the current state does not handle is refused here via `can()` and
never parked on the `onUnhandled: "defer"` queue (CV-C06). Each firing's terminal
outcome resets the chart (the alert re-arms for the next firing). Sealed-snapshot
restore goes through `statechart.persistence.restore` once a snapshot repository is
wired (E50); until then the `alerts` row is the durable truth and charts are rebuilt.
"""

from __future__ import annotations

import asyncio
import uuid
from collections import OrderedDict
from collections.abc import Sequence
from typing import Any, Final

import candleviewer.statechart.bindings.b10_alert as b10
from candleviewer.statechart import build
from candleviewer.statechart.factory import default_clock
from candleviewer.statechart.gateway import ALWAYS_ADMIT, Gateway
from candleviewer.statechart.plugins import FeedBinding, MachineStatePort, feed_plugins

MACHINE: Final = "alert"
LANE: Final = "platform"
MAX_CHARTS: Final = 4096
_TERMINAL: Final = frozenset({"delivered", "partially_delivered", "delivery_failed"})
_SETTLE_YIELDS: Final = 64
#: Await each event's macrostep so a failed B10 action surfaces here. Safe: sends come only
#: from the evaluator task, never from a B10 action, so the CV-C51 self-receipt hang cannot
#: arise (same pattern as `rules.lifecycle`).
_AWAIT_STEP: Final = True


class _Refusals:
    def __init__(self) -> None:
        self.counts: dict[str, int] = {}

    def record_send_refused(self, reason: str) -> None:
        self.counts[reason] = self.counts.get(reason, 0) + 1


def leaf_of(interp: Any) -> str:
    state: str = next(iter(interp.current_state_ids))
    return state.split(".", 1)[1]


class AlertCharts:
    def __init__(
        self,
        *,
        max_charts: int = MAX_CHARTS,
        hook: b10.Hook | None = None,
        feed: MachineStatePort | None = None,
    ) -> None:
        self._feed = feed  # 23 §6.4: `machines.alert:{id}.state`, scoped to the alert's owner
        self._charts: OrderedDict[str, Any] = OrderedDict()
        self._gateway = Gateway(admission=ALWAYS_ADMIT)  # E50-T63: until it adopts the bundle
        self.refusals = _Refusals()
        self._lock = asyncio.Lock()
        self._max = max_charts
        self._owns_hook = hook is not None
        if hook is not None:
            b10.set_hook(hook)

    def leaf(self, alert_id: str) -> str | None:
        interp = self._charts.get(alert_id)
        return None if interp is None else leaf_of(interp)

    def _plugins(self, alert_id: str, owner: str | None) -> tuple[Any, ...]:
        """B10's feed: `alert:{id}` scoped to its owner, which the evaluator names on each call.
        With none the feed can read, the binding is refused and logged: no entry, never a failed
        firing."""
        if self._feed is None:
            return ()
        try:
            user = None if owner is None else uuid.UUID(owner)
        except ValueError:
            user = None
        return feed_plugins(self._feed, FeedBinding(MACHINE, alert_id, user=user))

    async def _get(self, alert_id: str, owner: str | None) -> Any:
        async with self._lock:
            interp = self._charts.get(alert_id)
            if interp is not None and leaf_of(interp) not in _TERMINAL | {"resolved"}:
                self._charts.move_to_end(alert_id)
                return interp
            old = interp  # a finished firing: the fresh chart takes its entry over (23 §6.4)
            if old is not None:
                del self._charts[alert_id]
                self._gateway.unregister(alert_id)
            try:
                plugins = self._plugins(alert_id, owner)
                built = await build(MACHINE, clock=default_clock(), lane=LANE, plugins=plugins)
                interp = built.interpreter
                self._gateway.register(
                    alert_id, interp, kind="alert", lane=LANE, metrics=self.refusals
                )
                self._charts[alert_id] = interp
            finally:
                if old is not None:  # after the fresh chart published: its `remove` is a no-op
                    await old.stop()
            while len(self._charts) > self._max:
                await self._drop(next(iter(self._charts)))
            return interp

    async def _drop(self, alert_id: str) -> None:
        interp = self._charts.pop(alert_id, None)
        self._gateway.unregister(alert_id)
        if interp is not None:
            await interp.stop()

    async def _send_alert(
        self, key: str, event: str, /, *, owner: str | None = None, **payload: Any
    ) -> str:
        """Unique name + literal event so `tools/statechart/event_coverage.py` checks
        every alert send against the B10 descriptor."""
        ev: dict[str, Any] = {"type": event, **payload}
        interp = await self._get(key, owner)
        if not interp.can(ev):
            self.refusals.record_send_refused("unhandled")
            return leaf_of(interp)
        await self._gateway.send(key, {"type": event, **payload}, wait=_AWAIT_STEP)
        return leaf_of(interp)

    async def fired(
        self,
        alert_id: str,
        delivery_ids: Sequence[int],
        channels: Sequence[str],
        *,
        owner: str | None = None,
    ) -> None:
        await self._send_alert(
            alert_id,
            "CONDITION_MET",
            owner=owner,
            storm=False,
            alert_id=alert_id,
            delivery_ids=list(delivery_ids),
            channels=list(channels),
        )
        await self._settle(alert_id)

    async def _settle(self, alert_id: str) -> None:
        """Let the `deliver` invoke (a pure hand-off, no I/O) reach its outcome so the
        next firing finds a terminal chart. Bounded cooperative yields, never a timed wait."""
        for _ in range(_SETTLE_YIELDS):
            if self.leaf(alert_id) != "firing":
                return
            await asyncio.sleep(0)

    async def suppressed(
        self, alert_id: str, window_end_ms: int, *, owner: str | None = None
    ) -> None:
        await self._send_alert(
            alert_id,
            "CONDITION_MET",
            owner=owner,
            storm=True,
            alert_id=alert_id,
            storm_window_end_us=window_end_ms * 1000,
        )

    async def suppression_expired(self, alert_id: str, *, owner: str | None = None) -> None:
        await self._send_alert(alert_id, "SUPPRESSION_EXPIRED", owner=owner)

    async def disabled(self, alert_id: str, *, owner: str | None = None) -> None:
        await self._send_alert(alert_id, "DISABLE", owner=owner)

    async def stop(self) -> None:
        async with self._lock:
            for aid in list(self._charts):
                await self._drop(aid)
        if self._owns_hook:
            b10.set_hook(None)
