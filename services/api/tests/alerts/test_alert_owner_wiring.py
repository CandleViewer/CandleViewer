"""E40 #3349: the app puts the owner gate in front of the dispatcher and the evaluator, and both
metric sinks serve the counter of its skips (an unknown name raises)."""

from __future__ import annotations

from types import SimpleNamespace

from candleviewer.alerts.owners import OwnerGate
from candleviewer.observability.metrics import Metrics
from tests.alerts._evaluator_env import Source

SKIPPED = "cv_alert_owner_skipped_total"


def test_app_dispatcher_has_an_owner_gate_and_the_four_skip_series_at_zero() -> None:
    from candleviewer.app import _alert_delivery_sink, _alert_dispatcher, _alert_metric_sink

    facade = Metrics("dev")
    d = _alert_dispatcher(None, facade, False)  # type: ignore[arg-type]  # pg is lazy
    assert isinstance(d._owners, OwnerGate)
    assert facade.get(SKIPPED).series_count == 4  # {evaluate, dispatch} x {inactive, unreadable}
    _alert_delivery_sink(facade)(SKIPPED, ("dispatch", "inactive")).inc()
    _alert_metric_sink(facade)(SKIPPED, ("evaluate", "unreadable")).inc()
    assert facade.get(SKIPPED).series_count == 4  # both sinks serve the same four


async def test_app_evaluator_factory_builds_the_evaluator_with_an_owner_gate() -> None:
    from candleviewer.app import _alert_evaluator_factory

    ctx = SimpleNamespace(rules=SimpleNamespace(metric_source=Source()), audit=None)
    ev = await _alert_evaluator_factory(ctx, None, Metrics("dev"))()  # type: ignore[arg-type]  # lazy
    assert ev is not None and isinstance(ev._owners, OwnerGate)
