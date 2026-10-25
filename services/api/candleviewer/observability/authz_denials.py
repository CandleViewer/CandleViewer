"""`authz_denied_by_route_total{permission, route, role}` (#902, SR-125): each denied HTTP request
once, by its first denial's labels and the route template a pre-routing guard named or
`http_duration.route_template` (`unmatched`); a WebSocket denial at once under `ws`; nothing
outside a request. Past `max_series` a new series is dropped. Nothing is pre-bound."""

from __future__ import annotations

from collections.abc import MutableMapping
from contextvars import ContextVar
from typing import Any, Final

from candleviewer.observability.http_duration import route_template
from candleviewer.observability.metrics import BoundedMetric

METRIC_NAME: Final = "authz_denied_by_route_total"
_Denial = tuple[str, str, str | None]  # permission, role, route
#: A request's first denial, or a WebSocket connection's counter (each denial counts at once).
_CURRENT: ContextVar[list[_Denial] | BoundedMetric | None] = ContextVar("cv_authz", default=None)


def note_authz_denial(permission: str, role: str, *, route: str | None = None) -> None:
    """Mark the running request or connection denied (labels already clamped by the caller)."""
    if isinstance(cell := _CURRENT.get(), BoundedMetric):
        cell.labels(permission, "ws", role).inc()
    elif cell is not None and not cell:  # the first denial names the request
        cell.append((permission, role, route))


class AuthzDenialMiddleware:
    def __init__(self, app: Any, *, counter: BoundedMetric) -> None:
        self._app, self._counter = app, counter

    async def __call__(self, scope: MutableMapping[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self._app(scope, receive, send)
            return
        first: list[_Denial] = []
        token = _CURRENT.set(self._counter if scope["type"] == "websocket" else first)
        try:
            await self._app(scope, receive, send)
        finally:
            _CURRENT.reset(token)
            for permission, role, route in first:
                self._counter.labels(permission, route or route_template(scope), role).inc()
