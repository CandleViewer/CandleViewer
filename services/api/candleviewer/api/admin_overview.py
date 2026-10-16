"""`GET /admin/overview` and `GET /admin/capacity` (E42-T01; contract `getAdminOverview`,
`getCapacity`, `x-rbac: admin:read`, scope none).

Both routes sit on the audited admin router (`candleviewer.admin.http`). The handlers map the
internal read-model snapshots to the generated `AdminOverview` / `CapacityReport` models and
serialise with `exclude_unset`, so an unread field is omitted, never defaulted:
- a `TradingState` field that is `None` is omitted, never replaced with a boolean;
- when `tier_source` is `None` the four tier fields are omitted; `null` only for `unrecorded`;
- `days_until_full` keeps its meaningful `null` (no exhaustion ahead), per-symbol rows pass
  through whole (a pinned symbol's `retention_days` stays `null`), and `incidents_open` mirrors
  `incidents.open` only when that slice is `ok`.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from candleviewer.admin.http import AuditEmitter, PrincipalResolver, admin_router
from candleviewer.admin.overview.capacity import AdminCapacityService, CapacitySnapshot
from candleviewer.admin.overview.fanout import SliceResult
from candleviewer.admin.overview.service import AdminOverviewService, OverviewSnapshot
from candleviewer.api._generated import openapi_models as api
from candleviewer.auth.generated_permissions import Permission

#: `null` is a value here, not "unread", so this key survives the omission of `None`.
_MEANINGFUL_NULL = frozenset({"days_until_full"})
_TIER_FIELDS = ("tier", "cap", "tier_source", "recorded_at")


def _present(fields: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in fields.items() if v is not None or k in _MEANINGFUL_NULL}


def _slice(result: SliceResult[Any], fields: dict[str, Any] | None = None) -> dict[str, Any]:
    block: dict[str, Any] = {"status": result.status, "generated_at": result.generated_at}
    if result.detail is not None:
        block["detail"] = result.detail
    return block | _present(fields or {})


def _value(result: SliceResult[Any]) -> dict[str, Any]:
    return asdict(result.value) if result.value is not None else {}


def overview_payload(snap: OverviewSnapshot) -> dict[str, Any]:
    body: dict[str, Any] = {"generated_at": snap.generated_at}
    for name in ("users", "accounts", "recorder", "storage", "trading"):
        result = getattr(snap, name)
        body[name] = _slice(result, _value(result))
    open_count = snap.incidents.value
    body["incidents"] = _slice(snap.incidents, {"open": open_count})
    if snap.incidents.status == "ok":
        body["incidents_open"] = open_count
    return api.AdminOverview.model_validate(body).model_dump(mode="json", exclude_unset=True)


def capacity_payload(snap: CapacitySnapshot) -> dict[str, Any]:
    body: dict[str, Any] = {"generated_at": snap.generated_at}
    storage = _value(snap.storage)  # `projected_bytes` is not a contract field: the model drops it
    if "basis" in storage:
        storage["projection_basis"] = storage.pop("basis")
    body["storage"] = _slice(snap.storage, storage)
    body["ingestion"] = _slice(snap.ingestion, _value(snap.ingestion))
    body["rate_budget_status"] = _slice(snap.rate_budget)
    if snap.rate_budget.value is not None:
        body["rate_budget"] = [asdict(row) for row in snap.rate_budget.value]
    sub = _value(snap.subaccounts)
    tier = {k: sub.pop(k, None) for k in _TIER_FIELDS}
    body["subaccounts"] = _slice(snap.subaccounts, sub) | (
        tier if tier["tier_source"] is not None else {}  # unread: omitted; unrecorded: nulls
    )
    return api.CapacityReport.model_validate(body).model_dump(mode="json", exclude_unset=True)


def make_admin_overview_router(
    overview: AdminOverviewService,
    capacity: AdminCapacityService,
    *,
    resolver: PrincipalResolver | None,
    audit: AuditEmitter | None,
) -> APIRouter:
    router = admin_router(Permission.ADMIN_READ, resolver=resolver, audit=audit)

    @router.get("/overview")
    async def get_admin_overview() -> JSONResponse:
        return JSONResponse(overview_payload(await overview.overview()))

    @router.get("/capacity")
    async def get_capacity() -> JSONResponse:
        return JSONResponse(capacity_payload(await capacity.capacity()))

    return router
