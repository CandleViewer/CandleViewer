"""`CvErrorHooks` — failure-path hooks for every catalogue machine (E50-T60).

C09 / C50 / C59 / C63 / C69: supervisors key on the sticky counters this
plugin maintains (`chain_trips`, `dropped_receipts`) and on
`interpreter.chain_trips`, never on the per-step `last_error`.
The control lane escalates unhandled and guard-denied events to a page
(`onUnhandled: "defer"` keeps the event; this makes it visible).
"""

from __future__ import annotations

from typing import Any

from candleviewer.statechart.config import Lane
from candleviewer.statechart.plugins._base import (
    HookFailureCounter,
    LogPager,
    Pager,
    contained,
    event_type,
    logger,
)


class CvErrorHooks(HookFailureCounter):
    """Logs, counts and escalates; never raises into the interpreter."""

    def __init__(self, *, machine_kind: str, lane: Lane, pager: Pager | None = None) -> None:
        super().__init__()
        self.machine_kind = machine_kind
        self.lane: Lane = lane
        self.pager: Pager = pager if pager is not None else LogPager()
        self.chain_trips = 0
        self.dropped_receipts = 0
        self.transition_failures = 0
        self.invalid_events = 0
        self.dropped_events = 0
        self.stranded_invocations = 0
        self.unhandled_events = 0
        self.guard_denials = 0

    def _page(self, summary: str) -> None:
        self.pager.raise_alert("page", summary, machine_kind=self.machine_kind)

    @contained
    def on_transition_failed(self, interpreter: Any, transition: Any, failed_actions: Any) -> None:
        self.transition_failures += 1
        names = [str(getattr(a, "type", a)) for a, _exc in (failed_actions or ())]
        logger().error(
            "statechart_transition_failed",
            kind=self.machine_kind,
            ev=str(getattr(transition, "event", "")),
            actions=names,
        )
        if self.lane in ("order", "control"):
            self._page(f"transition failed: {self.machine_kind}")

    @contained
    def on_invalid_event(self, interpreter: Any, error: BaseException, raw_event: Any) -> None:
        self.invalid_events += 1
        logger().warning(
            "statechart_invalid_event", kind=self.machine_kind, error=type(error).__name__
        )

    @contained
    def on_event_dropped(self, interpreter: Any, event: Any, reason: str) -> None:
        self.dropped_events += 1
        logger().warning(
            "statechart_event_dropped", kind=self.machine_kind, ev=event_type(event), reason=reason
        )
        if self.lane == "order":
            self._page(f"order-lane event dropped ({reason}): {self.machine_kind}")

    @contained
    def on_chain_budget_exceeded(self, interpreter: Any, error: BaseException, event: Any) -> None:
        self.chain_trips += 1
        logger().critical(
            "statechart_chain_trip",
            kind=self.machine_kind,
            ev=event_type(event),
            chain_trips=int(getattr(interpreter, "chain_trips", self.chain_trips)),
        )
        self._page(f"runaway chain latched (CV-C63): {self.machine_kind}")

    @contained
    def on_invocation_stranded(
        self, interpreter: Any, state_id: str, invoke_id: str, error: BaseException
    ) -> None:
        self.stranded_invocations += 1
        logger().critical(
            "statechart_invocation_stranded",
            kind=self.machine_kind,
            state=state_id,
            invoke=invoke_id,
        )
        self._page(f"invocation stranded in {state_id}: {self.machine_kind}")

    @contained
    def on_receipt_dropped(self, interpreter: Any, event_type: str) -> None:
        # Finaliser-safe (CV-C69): runs from `__del__`, so only counter
        # bumps and a synchronous alert call — no awaits, no allocation-heavy work.
        self.dropped_receipts += 1
        logger().error("statechart_receipt_dropped", kind=self.machine_kind, ev=event_type)
        self.pager.raise_alert(
            "alert",
            f"send(wait=True) receipt dropped: {event_type}",
            machine_kind=self.machine_kind,
        )

    @contained
    def on_unhandled_event(
        self, interpreter: Any, event: Any, active_state_ids: Any, disposition: str
    ) -> None:
        self.unhandled_events += 1
        logger().warning(
            "statechart_unhandled_event",
            kind=self.machine_kind,
            ev=event_type(event),
            disposition=disposition,
        )
        if self.lane == "control":
            self._page(f"control-lane unhandled {event_type(event)}: {self.machine_kind}")
        elif self.lane == "order" and disposition == "dropped":
            # The deferral buffer was full (the runtime's DEFER_MAX) and evicted its oldest
            # event: on the order lane that may be a fill (24 Sec.8.2 S10, #847).
            self._page(
                f"order-lane deferred event evicted {event_type(event)}: {self.machine_kind}"
            )

    @contained
    def on_guard_evaluated(
        self, interpreter: Any, guard_name: str, event: Any, result: bool
    ) -> None:
        if result:
            return
        self.guard_denials += 1
        if self.lane == "control":
            self._page(f"control-lane guard denied {guard_name}: {self.machine_kind}")

    @contained
    def on_guard_error(self, interpreter: Any, *args: Any) -> None:
        logger().error("statechart_guard_error", kind=self.machine_kind)
        if self.lane in ("order", "control"):
            self._page(f"guard raised: {self.machine_kind}")
