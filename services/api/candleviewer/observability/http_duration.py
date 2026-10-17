"""HTTP request-duration middleware: `cv_http_request_duration_seconds` (#2421).

Pure ASGI, HTTP scopes only (WebSocket and lifespan pass straight through). One histogram
observation per request, labelled `route`, `method`, `status_class`:

- `route` is the matched route *template* (`/v1/drawings/{drawingId}`), read from
  `scope["route"].path` after the downstream app ran. The raw path is never a label.
- Requests that never reach a route (404s, and refusals produced by an inner middleware before
  routing: CSRF 403, 413, 401) fall into the single `unmatched` series. Matching them against the
  router would re-run Starlette's route scan on every refused request, so the cheap, bounded
  choice is taken; they are still timed.
- `method` is a closed set; anything else is `other`.
- `status_class` is `1xx`..`5xx` from the first `http.response.start`; an exception that escapes
  before any response was sent counts as `5xx` and is re-raised unchanged.

Timing runs until the downstream app returns, so a streaming response is timed to completion of
its body. A request cancelled with no response started (`asyncio.CancelledError`, client gone) is
NOT recorded and the error is re-raised: a disconnect is not a server error and must not distort
5xx-based alerts. Any other escaping exception counts as `5xx`.

No user, account, symbol, query-string or header label exists (C-12.6, C-2.18). The series bound
is route templates x observed method/status combinations, capped by `HTTP_DURATION_MAX_SERIES`
on the catalogue entry (buckets live there too). At the cap `BoundedMetric` hands back a no-op
child: new series are dropped, each refused observation is counted in
`metric_cardinality_breach_total` and existing series keep recording, so memory cannot grow.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, MutableMapping
from typing import Any, Final

from candleviewer.observability.metrics import BoundedMetric

METRIC_NAME: Final = "cv_http_request_duration_seconds"
UNMATCHED_ROUTE: Final = "unmatched"
OTHER_METHOD: Final = "other"
_METHODS: Final = frozenset({"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"})


def _status_class(status: int) -> str:
    return f"{status // 100}xx" if 100 <= status <= 599 else "5xx"


def _route_template(scope: MutableMapping[str, Any]) -> str:
    path = getattr(scope.get("route"), "path", None)
    return path if isinstance(path, str) and path else UNMATCHED_ROUTE


class HttpDurationMiddleware:
    """Time every HTTP request, refusals by inner middleware included."""

    def __init__(
        self,
        app: Any,
        *,
        histogram: BoundedMetric,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self._app = app
        self._histogram = histogram
        self._clock = clock

    async def __call__(self, scope: MutableMapping[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        start = self._clock()
        status: list[int] = []

        async def send_wrapper(message: MutableMapping[str, Any]) -> None:
            if message["type"] == "http.response.start" and not status:
                status.append(int(message["status"]))
            await send(message)

        try:
            await self._app(scope, receive, send_wrapper)
        except asyncio.CancelledError:
            if status:
                self._observe(scope, status[0], self._clock() - start)
            raise
        except BaseException:
            self._observe(scope, status[0] if status else 500, self._clock() - start)
            raise
        else:
            self._observe(scope, status[0] if status else 500, self._clock() - start)

    def _observe(self, scope: MutableMapping[str, Any], status: int, elapsed: float) -> None:
        method = str(scope.get("method", ""))
        self._histogram.labels(
            _route_template(scope),
            method if method in _METHODS else OTHER_METHOD,
            _status_class(status),
        ).observe(max(0.0, elapsed))
