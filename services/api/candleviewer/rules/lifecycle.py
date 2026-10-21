"""`RuleLifecycle`: the B9 `rule_instance` chart *is* the rule mode lifecycle (E35-S01).

There is no hand-written mode enum or transition table here (ticket scope, C-2.19): every
mode change is an event sent through `statechart.gateway` to an interpreter built only by
`statechart.factory.build("rule_instance")`, and legality is whatever the committed chart
(28-statechart-catalogue.md §B9) accepts. The API's three modes are a *projection* of the
chart's states (`mode_of`), and a requested target names the B9 events that can reach it
(`_EVENTS_FOR`); the chart decides which, if any, the current state handles.

C-2.21: `RulesManager` runs the synchronous RBAC / arming checks *before* anything is
sent; the chart records. Every send is pre-checked with `can()` (guards evaluated, no side
effects) so an event the current state does not handle is refused here and never parked on
the `onUnhandled: "defer"` queue, where it could fire later (CV-C06).

Interpreters are built lazily per rule and hydrated from the persisted `rules.mode` with
`replay=True` events; they are bounded per process (C-2.18) and rebuilt from the row on
next use. Sealed-snapshot restore (`statechart.persistence.restore`) replaces hydration
once a snapshot repository is wired (E50); until then the row is the durable truth.
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from typing import Any, Final

import candleviewer.statechart.bindings.b09_rule_instance  # noqa: F401  (registers B9 logic)
from candleviewer.statechart import build
from candleviewer.statechart.factory import default_clock
from candleviewer.statechart.gateway import ALWAYS_ADMIT, Gateway, receipt_is_conclusive

MACHINE: Final = "rule_instance"
MAX_CHARTS: Final = 4096
MODES: Final = ("disabled", "simulate", "armed")
#: Await each event's macrostep so a failed B9 action surfaces to the caller (C-2.9).
#: Safe: `_send` is called from request handlers only, never from a B9 action, so the
#: CV-C51 self-receipt hang cannot arise (same pattern as `auth.session_chart`).
_AWAIT_STEP: Final = True

#: Projection of B9 leaf states onto the persisted `rule_mode` enum (21-database-schema).
_MODE_OF: Final[dict[str, str]] = {
    "draft": "disabled",
    "disarmed": "disabled",
    "kill_switched": "disabled",
    "simulating": "simulate",
    "armed": "armed",
    "evaluating": "armed",
    "pending_confirmation": "armed",
    "acting": "armed",
    "cooling_down": "armed",
    "paused_degraded": "armed",
    "spent": "armed",
}
#: B9 events (catalogue §B9.3 names) whose purpose is to reach each requested mode.
_EVENTS_FOR: Final[dict[str, tuple[str, ...]]] = {
    "simulate": ("SAVE", "EDIT"),
    "armed": ("ARM_REQUESTED", "HUMAN_REARM"),
    "disabled": ("DISARM",),
}


class LifecycleError(RuntimeError):
    """The B9 chart failed to record an accepted event (action error, overload)."""


class _Refusals:
    def __init__(self) -> None:
        self.counts: dict[str, int] = {}

    def record_send_refused(self, reason: str) -> None:
        self.counts[reason] = self.counts.get(reason, 0) + 1


def mode_of(leaf: str) -> str:
    return _MODE_OF[leaf]


def events_for(target: str) -> tuple[str, ...]:
    return _EVENTS_FOR.get(target, ())


class RuleLifecycle:
    def __init__(self, *, max_charts: int = MAX_CHARTS) -> None:
        self._charts: OrderedDict[str, Any] = OrderedDict()
        self._hydrating: dict[str, Any] = {}
        self._gateway = Gateway(admission=ALWAYS_ADMIT)  # E50-T63: until it adopts the bundle
        self.refusals = _Refusals()
        self._lock = asyncio.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._max = max_charts

    def _bind_loop(self) -> None:
        """Interpreters are loop-bound; if the running loop changed, drop the cache
        (each chart is rebuilt from its `rules` row on next use)."""
        loop = asyncio.get_running_loop()
        if loop is not self._loop:
            self._loop = loop
            self._charts = OrderedDict()
            self._gateway = Gateway(admission=ALWAYS_ADMIT)
            self._lock = asyncio.Lock()

    @staticmethod
    def _leaf_of(interp: Any) -> str:
        state: str = next(iter(interp.current_state_ids))
        return state.split(".", 1)[1]

    def leaf(self, rule_id: str) -> str | None:
        """Current B9 leaf state of a live chart (tests / supervision)."""
        interp = self._charts.get(rule_id)
        return None if interp is None else self._leaf_of(interp)

    async def _send(self, rule_id: str, event: dict[str, Any]) -> str:
        """Send via the gateway and wait for this event's macrostep; return the new leaf.

        Called from request handlers only, never from a B9 action (no CV-C51 self-wait).
        A receipt is read only through `receipt_is_conclusive` (CV-C06) to surface action
        errors; whether the chart *moved* is observed by state entry (the leaf)."""
        receipt = await self._gateway.send(rule_id, event, wait=_AWAIT_STEP)
        if receipt_is_conclusive(receipt) and receipt.error is not None:
            raise LifecycleError(f"B9 {event['type']}: {type(receipt.error).__name__}")
        return self._leaf_of(self._gateway_interp(rule_id))

    def _gateway_interp(self, rule_id: str) -> Any:
        interp = self._charts.get(rule_id) or self._hydrating.get(rule_id)
        if interp is None:
            raise LifecycleError(f"B9 chart for rule {rule_id} is not running")
        return interp

    async def _hydrate(self, rule_id: str, mode: str, disabled_reason: str | None) -> None:
        """Re-enter the persisted state with `replay=True` events (already enforced and
        audited when they happened; never re-recorded)."""
        steps: tuple[str, ...]
        if mode == "simulate":
            steps = ("SAVE",)
        elif mode == "armed":
            steps = ("SAVE", "ARM_REQUESTED")
        elif disabled_reason == "kill_switched":
            steps = ("KILL",)
        elif disabled_reason == "disarmed":
            steps = ("SAVE", "ARM_REQUESTED", "DISARM")
        else:
            steps = ()  # draft
        for ev in steps:
            before = self._leaf_of(self._gateway_interp(rule_id))
            if await self._send(rule_id, {"type": ev, "replay": True, "permitted": True}) == before:
                raise LifecycleError(f"B9 hydration {ev} did not transition from {before}")

    async def _get(self, rule_id: str, mode: str, disabled_reason: str | None) -> Any:
        self._bind_loop()
        async with self._lock:
            interp = self._charts.get(rule_id)
            if interp is not None:
                self._charts.move_to_end(rule_id)
                return interp
            result = await build(
                MACHINE, ctx={"rule_id": rule_id}, clock=default_clock(), lane="control"
            )
            interp = result.interpreter
            self._gateway.register(
                rule_id, interp, kind=MACHINE, lane="control", metrics=self.refusals
            )
            self._hydrating[rule_id] = interp
            try:
                await self._hydrate(rule_id, mode, disabled_reason)
            except BaseException:
                self._gateway.unregister(rule_id)
                await interp.stop()
                raise
            finally:
                self._hydrating.pop(rule_id, None)
            self._charts[rule_id] = interp
            while len(self._charts) > self._max:
                old_id, old = self._charts.popitem(last=False)
                self._gateway.unregister(old_id)
                await old.stop()
            return interp

    async def current(self, rule_id: str, mode: str, disabled_reason: str | None) -> str:
        """The rule's B9 leaf, building/hydrating the chart from its row if needed."""
        await self._get(rule_id, mode, disabled_reason)
        return self._live_leaf(rule_id)

    def _live_leaf(self, rule_id: str) -> str:
        leaf = self.leaf(rule_id)
        if leaf is None:
            raise LifecycleError(f"B9 chart for rule {rule_id} is not running")
        return leaf

    async def handled_event(
        self, rule_id: str, mode: str, disabled_reason: str | None, target: str, **payload: Any
    ) -> str | None:
        """The first B9 event for *target* the current state handles (`can()`: guards
        evaluated, no side effects), or None. A handled event is never deferred; whether
        it actually transitions is decided by the chart when sent (`send`)."""
        interp = await self._get(rule_id, mode, disabled_reason)
        for ev in events_for(target):
            if interp.can({"type": ev, **payload}):
                return ev
        return None

    async def send(self, rule_id: str, event: str, **payload: Any) -> tuple[str, str]:
        """Record an already-enforced change; returns `(leaf before, leaf after)`. Equal
        leaves mean the chart refused it (its guard-denied arm has recorded why)."""
        before = self._live_leaf(rule_id)
        return before, await self._send(rule_id, {"type": event, **payload})

    async def evict(self, rule_id: str) -> None:
        """Drop a chart (e.g. its row write failed) so the next use rebuilds from the row."""
        self._bind_loop()
        async with self._lock:
            interp = self._charts.pop(rule_id, None)
            self._gateway.unregister(rule_id)
        if interp is not None:
            await interp.stop()

    async def stop(self) -> None:
        self._bind_loop()
        async with self._lock:
            charts, self._charts = list(self._charts.items()), OrderedDict()
        for rid, interp in charts:
            self._gateway.unregister(rid)
            await interp.stop()


__all__ = ["MODES", "LifecycleError", "RuleLifecycle", "events_for", "mode_of"]
