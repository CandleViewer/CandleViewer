"""`GET /indicators` (`listIndicators`, `docs/plan/22-api-openapi.yaml`; E13-T02).

The indicator catalogue the chart settings dialogs render their forms from (SCR-034, SCR-035):
one `IndicatorDescriptor` per definition of the `IndicatorCatalogue` the router is given, in
its order, read on every request, so registering a definition changes the response with no
frontend release. Static, code-defined metadata: no store, no I/O and nothing user-scoped.

RBAC (C-12.4) mirrors `api/ticker.py`, fail-closed: no resolver -> 501, no session -> 401, no
`marketdata:read` -> 403. Each item is built from an explicit allowlist of the contract's fields
(IR-25): no kernel, module path or internal field reaches the wire, and `compute` comes from the
definition, never from the request (IR-41).
"""

from __future__ import annotations

import inspect
from typing import Any, Protocol

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from candleviewer.auth.generated_permissions import Permission
from candleviewer.orderflow.indicators.catalogue import IndicatorCatalogue, IndicatorDef, JsonValue

_REQUIRED_PERMISSION = Permission.MARKETDATA_READ


class _Principal(Protocol):
    def has(self, permission: str) -> bool: ...


class _Resolver(Protocol):
    """Sync or async resolver (`resolve(request)` may return an awaitable)."""

    def resolve(self, request: Request) -> Any: ...


def _problem(status: int, code: str, title: str, detail: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        media_type="application/problem+json",
        content={
            "type": f"https://candleviewer.local/errors/{code}",
            "title": title,
            "status": status,
            "detail": detail,
            "code": code,
        },
    )


def serialize_descriptor(definition: IndicatorDef) -> dict[str, JsonValue]:
    """One `IndicatorDescriptor`: exactly the contract's fields (IR-25)."""
    return {
        "id": definition.id,
        "name": definition.title,
        "category": definition.category,
        "pane": definition.pane,
        "compute": definition.compute,
        "estimated": definition.estimated,
        "params_schema": definition.params_schema(),
        "defaults": definition.json_defaults(),
        "outputs": [{"id": o.id, "name": o.name} for o in definition.outputs],
        "warmup_bars": definition.warmup_bars(),
        "unit": definition.unit,
        "nullable_when": definition.nullable_when,
    }


def make_indicators_router(
    catalogue: IndicatorCatalogue, *, principal_resolver: _Resolver | None = None
) -> APIRouter:
    router = APIRouter(tags=["workspaces"])

    @router.get("/indicators")
    async def list_indicators(request: Request) -> JSONResponse:
        if principal_resolver is None:
            return _problem(
                501, "not_implemented", "Not implemented", "no principal resolver wired"
            )
        resolved = principal_resolver.resolve(request)
        principal: _Principal | None = await resolved if inspect.isawaitable(resolved) else resolved
        if principal is None:
            return _problem(401, "unauthenticated", "Unauthorized", "no verified session")
        if not principal.has(_REQUIRED_PERMISSION):
            return _problem(403, "forbidden", "Forbidden", f"requires {_REQUIRED_PERMISSION}")
        items = [serialize_descriptor(definition) for definition in catalogue]
        return JSONResponse(status_code=200, content={"items": items})

    return router


__all__ = ["make_indicators_router", "serialize_descriptor"]
