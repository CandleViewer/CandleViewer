"""E40-T04 PR-A wiring: `create_app()` serves the inbox ahead of the `/alerts` CRUD router (whose
`/alerts/{alertId}` would take `GET /alerts/deliveries`), serves `GET /notifications`, and shares
the dispatcher's `cv_alert_delivery_*` series with the desktop report-back."""

from __future__ import annotations

from typing import Any

from candleviewer.app import _alert_delivery_sink, create_app
from candleviewer.observability.metrics import Metrics
from candleviewer.settings import Settings


def _routes() -> list[tuple[str, frozenset[str]]]:
    """Served routes in match order. On FastAPI 0.141 the top level of `app.routes` holds
    `_IncludedRouter` wrappers, so this walks them as `deny_by_default.served_operations` does."""
    out: list[tuple[str, frozenset[str]]] = []

    def walk(routes: Any, prefix: str) -> None:
        for route in routes:
            inner = getattr(route, "original_router", None)
            if inner is not None:
                ctx = getattr(getattr(route, "include_context", None), "prefix", "") or ""
                walk(inner.routes, prefix + ctx)
            elif getattr(route, "methods", None):
                out.append((prefix + route.path, frozenset(route.methods) - {"HEAD"}))

    walk(create_app(Settings(alerts_evaluator_enabled=False)).routes, "")
    return out


def test_the_inbox_is_mounted_before_the_alert_crud_routes() -> None:
    routes = _routes()
    deliveries = routes.index(("/alerts/deliveries", frozenset({"GET"})))
    crud = routes.index(("/alerts/{alertId}", frozenset({"GET"})))
    assert deliveries < crud


def test_every_inbox_and_notification_operation_is_served() -> None:
    served = set(_routes())
    for path, method in [
        ("/alerts/deliveries", "GET"),
        ("/alerts/deliveries/{deliveryId}/ack", "POST"),
        ("/alerts/deliveries/ack-all", "POST"),
        ("/alerts/deliveries/{deliveryId}/desktop-outcome", "POST"),
        ("/notifications", "GET"),
    ]:
        assert (path, frozenset({method})) in served


def test_the_delivery_sink_is_one_set_of_series_for_both_callers() -> None:
    facade = Metrics("dev")
    first, second = _alert_delivery_sink(facade), _alert_delivery_sink(facade)
    first("cv_alert_delivery_total", ("desktop", "sent")).inc()
    second("cv_alert_delivery_total", ("desktop", "sent")).inc()
    value = facade.registry.get_sample_value(
        "cv_alert_delivery_total", {"env": "dev", "transport": "desktop", "state": "sent"}
    )
    assert value == 2.0
