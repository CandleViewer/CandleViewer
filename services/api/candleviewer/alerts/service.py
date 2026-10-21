"""Lifecycle for the alerts module (M22): starts/stops the `AlertEvaluator` (E40-T03), the
delivery dispatcher and the `alerts` WS topic (E40-T04).

The composition root `bind()`s a factory; `start()` warms the evaluator up (one
subscription per distinct `condition_hash`) and runs it in its own tracked task;
`stop()` drains so an in-flight firing completes or rolls back whole. Without a bound
factory (or with `alerts_evaluator_enabled` off, C-4.13) the evaluator stays idle; the topic
(`bind_topic`) runs either way, since the inbox routes change deliveries too.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from candleviewer.alerts.dispatcher import AlertDispatcher
from candleviewer.alerts.evaluator import AlertEvaluator, AlertTick
from candleviewer.alerts.ws_topic import AlertsTopic
from candleviewer.observability.health import HealthReport, HealthStatus

if TYPE_CHECKING:
    from candleviewer.app import AppContext

EvaluatorFactory = Callable[[], Awaitable[AlertEvaluator | None]]


class AlertsService:
    def __init__(self) -> None:
        self._started = False
        self._factory: EvaluatorFactory | None = None
        self.evaluator: AlertEvaluator | None = None
        self.dispatcher: AlertDispatcher | None = None
        self.topic: AlertsTopic[Any] | None = None

    def bind(self, factory: EvaluatorFactory, dispatcher: AlertDispatcher | None = None) -> None:
        """`dispatcher` (E40-T04) drains `alert.deliver`; it starts before the evaluator so
        no firing waits on a cold poller, and stops after it so in-flight firings drain."""
        self._factory = factory
        self.dispatcher = dispatcher

    def bind_topic(self, topic: AlertsTopic[Any]) -> None:
        """The `alerts` WS topic (E40-T04): its worker starts with the module and stops last."""
        self.topic = topic

    async def start(self, ctx: AppContext) -> None:
        self._started = True
        if self.topic is not None:
            self.topic.start()
        if self._factory is None:
            return
        if self.dispatcher is not None:
            self.dispatcher.start()
        ev = await self._factory()
        if ev is not None:
            await ev.warm_up()
            ev.start()
        self.evaluator = ev

    async def on_alert_changed(self, alert_id: str) -> None:
        """The in-process create/update/delete/enable event emitted by `/alerts`."""
        if self.evaluator is not None:
            await self.evaluator.on_alert_changed(alert_id)

    def submit_tick(self, tick: AlertTick) -> bool:
        if self.evaluator is None:
            return False
        self.evaluator.submit(tick)
        return True

    async def stop(self, grace_s: float) -> None:
        ev, self.evaluator = self.evaluator, None
        self._started = False
        try:
            if ev is not None:
                await ev.stop(grace_s)
        finally:
            try:
                if self.dispatcher is not None:
                    await self.dispatcher.stop()
            finally:
                if self.topic is not None:  # last: the dispatcher's final settles may tell it
                    await self.topic.stop()

    def health(self) -> HealthReport:
        status = HealthStatus.OK if self._started else HealthStatus.STOPPED
        detail = "evaluator running" if self.evaluator is not None else "evaluator idle"
        return HealthReport(module="", status=status, detail=detail)
