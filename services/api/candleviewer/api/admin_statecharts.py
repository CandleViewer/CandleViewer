"""`GET /admin/statecharts` and `.../{machineKey}/export` (E42-T07, `listStatecharts` and
`exportStatechart`, `x-rbac: admin:read`) on the audited admin router. The `machines.{entity}.state`
rules are E17-T08's own (`candleviewer.ws.topics`): `parse_topic` holds the entity grammar and
`machine_refusal` is the per-entity check. Account grants are not loaded (the operations are
owner-only), so a non-Owner holding `admin:read` sees no account-scoped entity: fail closed.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Any, Final, Literal

from fastapi import APIRouter, Path, Query, Request
from fastapi.responses import JSONResponse

from candleviewer.admin.http import AuditEmitter, PrincipalResolver, admin_router
from candleviewer.admin.inspector import BoundScope, Machine, Position, StatechartInspector, Visible
from candleviewer.admin.overview.fanout import SliceResult, utc_now
from candleviewer.api._generated import openapi_models as api
from candleviewer.api.market_response import problem
from candleviewer.audit.access import AuditPrincipal
from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.scopes import PrincipalSnapshot
from candleviewer.statechart.errors import MachineNotFoundError
from candleviewer.ws.topics import EntityScope, TopicError, machine_refusal, parse_topic

#: B4-B7 share the `algo` entity (`23-ws-protocol.md` §6.4).
ALGO_KINDS: Final = frozenset({"oco", "iceberg", "twap", "chase"})
#: The shared `Cursor` parameter: a cursor expires after one hour.
CURSOR_TTL_S: Final = 3600
_UUID: Final = "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
#: The contract's `MachineKey` path parameter; a key it rejects is a validation error (422).
MACHINE_KEY: Final = rf"^[a-z_]{{1,32}}(:({_UUID}|[A-Z0-9]{{2,20}}USDT))?$"
_PERMISSIONS: Final = {p.value: p for p in Permission}


def entity_kind(machine_kind: str) -> str:
    return "algo" if machine_kind in ALGO_KINDS else machine_kind


def entity(key: str) -> str | None:
    """The §6.4 entity kind of a `machineKey`, or `None` off the grammar."""
    try:
        return parse_topic(f"machines.{key}.state").entity_kind
    except TopicError:
        return None


def machine_key(machine_kind: str, entity_id: str | None) -> str | None:
    """`KeyOf` on the E17-T08 grammar: `None` for no public id (B8, B9, B13, B15) or a bad id."""
    kind = entity_kind(machine_kind)
    key = kind if entity_id is None else f"{kind}:{entity_id}"
    return key if entity(key) == kind else None


def visibility(principal: PrincipalSnapshot) -> Visible:
    """E17-T08's `machine_refusal`, on the scope the owning module bound to the machine."""

    def visible(machine_kind: str, scope: BoundScope) -> bool:
        bound = EntityScope(scope.accounts, scope.user)
        return machine_refusal(principal, entity_kind(machine_kind), bound) is None

    return visible


def _cursor(position: Position, bound: list[Any], now: int) -> str:
    raw = json.dumps([list(position), bound, now], separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _after(cursor: str, bound: list[Any], now: int) -> Position:
    """Where this listing's cursor, issued within the hour, resumes; else ValueError/TypeError."""
    raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
    (kind, key, env), issued_for, iat = json.loads(raw)
    if issued_for != bound or type(iat) is not int or not 0 <= now - iat <= CURSOR_TTL_S:
        raise ValueError("foreign or expired cursor")
    if not all(isinstance(part, str) for part in (kind, key, env)):
        raise TypeError("malformed cursor")
    return kind, key, env


def _status(result: SliceResult[Any]) -> dict[str, Any]:
    block = {"status": result.status, "generated_at": result.generated_at, "detail": result.detail}
    status = api.AdminSliceStatus.model_validate({k: v for k, v in block.items() if v is not None})
    return status.model_dump(mode="json", exclude_unset=True)


def _machine(m: Machine) -> dict[str, Any]:
    row = m.row
    fields: dict[str, Any] = {"machine_key": m.key, "machine_kind": row.machine_kind}
    fields |= {"environment": row.environment, "state": m.state, "machine_hash": m.machine_hash}
    fields |= {"lock_matches": m.lock_matches, "chain_trips": m.chain_trips}
    fields |= {"degraded": m.chain_trips > 0, "deferred_depth": m.deferred_depth}
    fields["updated_at"] = row.updated_at
    return api.StatechartMachine.model_validate(fields).model_dump(mode="json")


def make_statechart_router(
    inspector: StatechartInspector,
    *,
    resolver: PrincipalResolver | None,
    audit: AuditEmitter | None,
    clock: Callable[[], datetime] = utc_now,
) -> APIRouter:
    router = admin_router(Permission.ADMIN_READ, resolver=resolver, audit=audit)

    @router.get("/statecharts")
    async def list_statecharts(
        request: Request,
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
        cursor: Annotated[str | None, Query(max_length=512)] = None,
        environment: Literal["live", "demo", "testnet"] | None = None,
        kind: Annotated[str | None, Query(pattern=r"^[a-z_]{1,32}$")] = None,
        degraded: bool | None = None,
    ) -> JSONResponse:
        now, bound = int(clock().timestamp()), [kind, environment, degraded]
        try:
            after = None if cursor is None else _after(cursor, bound, now)
        except (ValueError, TypeError):
            title = "Pagination cursor is malformed or expired"
            return problem(400, "invalid_cursor", title, "The cursor is not valid.")
        caller: AuditPrincipal = request.state.admin_principal  # known codes, no grants
        perms = frozenset(_PERMISSIONS[c] for c in caller.permissions if c in _PERMISSIONS)
        roles = frozenset({"owner"}) if caller.is_owner else frozenset()
        visible = visibility(PrincipalSnapshot(caller.user_id, roles, perms))
        found = await inspector.listing(
            visible, kind=kind, environment=environment, degraded=degraded, after=after, limit=limit
        )
        last = found.items[-1].position if found.has_more else None
        kinds = [api.StatechartKindSummary.model_validate(k) for k in found.kinds]
        next_cursor = None if last is None else _cursor(last, bound, now)
        meta = {"next_cursor": next_cursor, "has_more": found.has_more, "count": len(found.items)}
        return JSONResponse(
            {
                "items": [_machine(m) for m in found.items],
                "kinds": [k.model_dump(mode="json") for k in kinds],
                "snapshots": _status(found.snapshots),
                "metrics": _status(found.metrics),
                "meta": meta,
            }
        )

    @router.get("/statecharts/{machineKey}/export")
    async def export_statechart(
        key: Annotated[str, Path(alias="machineKey", max_length=80, pattern=MACHINE_KEY)],
    ) -> JSONResponse:
        """A bare B1-B20 kind, or an entity key's kind: no instance is read, so `algo:{id}` 404s."""
        try:
            body = inspector.export(entity(key) or key)
        except MachineNotFoundError:
            title = "Resource does not exist or is out of the caller's scope"
            return problem(404, "not_found", title, "No chart is registered for this key.")
        return JSONResponse(api.StatechartExport.model_validate(body).model_dump(mode="json"))

    return router
