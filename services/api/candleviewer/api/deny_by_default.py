"""Global deny-by-default wiring (E09-T03, QA #1648 defect 3).

- Build time: `assert_app_routes_declared(app, spec)` fails `create_app()`
  when a served route is neither RBAC-declared nor explicitly public in the
  OpenAPI contract (and not an allow-listed operational route).
- Runtime: `deny_undeclared_dependency` is a global FastAPI dependency; a
  request to a route absent from the declared set is refused with 403.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, WebSocketException
from starlette.requests import HTTPConnection

from candleviewer.api.contract_conformance import NON_CONTRACT_ROUTES

#: Operational endpoints intentionally outside the REST contract and public.
PUBLIC_OPERATIONAL_ROUTES = NON_CONTRACT_ROUTES | frozenset({"/healthz", "/readyz", "/metrics"})

#: WebSocket routes (`23-ws-protocol.md`): authenticated in-band (`auth`
#: frame) with per-topic RBAC; any other WS path is refused (1008). `/api/v1/ws` is the same route
#: under the server base, the external URL (#3907): one endpoint, one topic matrix.
DECLARED_WS_ROUTES = frozenset({"/ws", "/api/v1/ws"})

_METHODS = frozenset({"get", "put", "post", "delete", "patch", "options", "head"})


class UndeclaredRouteAtBuildError(Exception):
    """A served route has no RBAC declaration and is not explicitly public."""


def declared_operations(spec: dict[str, Any]) -> set[tuple[str, str]]:
    """(METHOD, path) pairs that carry `x-rbac` or `security: []`."""
    out: set[tuple[str, str]] = set()
    for path, item in spec.get("paths", {}).items():
        if not isinstance(item, dict):
            continue
        for method, op in item.items():
            if method in _METHODS and isinstance(op, dict):
                if isinstance(op.get("x-rbac"), dict) or op.get("security") == []:
                    out.add((method.upper(), path))
    return out


def served_operations(app: FastAPI) -> set[tuple[str, str]]:
    """Every (METHOD, path) the app serves, including included routers.
    Walks the route tree (cheaper than building the OpenAPI document)."""
    out: set[tuple[str, str]] = set()

    def walk(routes: Any, prefix: str) -> None:
        for route in routes:
            inner = getattr(route, "original_router", None)
            if inner is not None:
                ctx_prefix = getattr(getattr(route, "include_context", None), "prefix", "") or ""
                walk(inner.routes, prefix + ctx_prefix)
                continue
            path = getattr(route, "path", None)
            methods = getattr(route, "methods", None)
            if path is None or methods is None:
                continue
            for method in methods:
                if method != "HEAD":
                    out.add((method, prefix + path))

    walk(app.routes, "")
    return out


def assert_app_routes_declared(app: FastAPI, spec: dict[str, Any]) -> None:
    declared = declared_operations(spec)
    missing = sorted(
        op
        for op in served_operations(app)
        if op[1] not in PUBLIC_OPERATIONAL_ROUTES and op not in declared
    )
    if missing:
        raise UndeclaredRouteAtBuildError(
            "RBAC-CON-003: routes without x-rbac or explicit public marker: "
            + ", ".join(f"{m} {p}" for m, p in missing)
        )


def make_deny_undeclared_dependency(declared: set[tuple[str, str]]) -> Any:
    async def deny_undeclared_dependency(request: HTTPConnection) -> None:
        route = request.scope.get("route")
        path = getattr(route, "path", None)
        if request.scope["type"] == "websocket":
            if path not in DECLARED_WS_ROUTES:
                raise WebSocketException(code=1008, reason="forbidden")
            return
        if path is None or path in PUBLIC_OPERATIONAL_ROUTES:
            return
        if (str(request.scope["method"]).upper(), path) not in declared:
            raise HTTPException(status_code=403, detail="forbidden")

    return deny_undeclared_dependency
