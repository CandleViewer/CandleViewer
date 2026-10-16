"""`/alerts` CRUD routes (E40-T02) - contract: `22-api-openapi.yaml` listAlerts..setAlertEnabled.

Notify-only by construction: every write runs `AlertCompiler` (structural allow-list, schema,
trigger, metric registry, canonical hash) before anything is persisted, so an action-bearing
payload is a 422 and never reaches storage - and nothing here imports the OMS.

RBAC (C-12.4) is enforced in dependencies, not per handler: `_need(perm)` resolves the caller
and checks `alerts:read` / `alerts:write`; `_owned` applies `scope: self` - another user's
alert is a 404 (existence is not disclosed) and the denial is audited. Every mutation writes
an append-only audit record (C-2.9) before the response is returned. The two reads take only
their declared query parameters (SR-026): any other key gets the shared 422 after the permission
check and before the store is read.
"""

# No `from __future__ import annotations`: FastAPI must evaluate `Depends(<closure>)` in the
# handler signatures at definition time (string annotations cannot see the closures).

import inspect
import time
from collections.abc import Awaitable, Callable, Coroutine
from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from candleviewer.alerts.compiler import AlertCompiler, validate_template
from candleviewer.alerts.errors import AlertIrInvalid
from candleviewer.api.query_allowlist import undeclared_query_refusal
from candleviewer.audit.models import AuditOutcome
from candleviewer.rules.manager import Actor
from candleviewer.rules.vocabulary.registry import MetricRegistry
from candleviewer.storage.repositories.alerts import (
    AlertConflictError,
    AlertNameTakenError,
    AlertRepository,
    AlertRow,
)

READ, WRITE = "alerts:read", "alerts:write"
#: SR-026 (#2632): declared query parameters (22-api-openapi.yaml) of `listAlerts` (`Cursor`,
#: `Limit`, `enabled`, `SymbolQueryOptional`) and `getAlert` (none); any other key is refused.
LIST_ALERTS_QUERY = frozenset({"cursor", "limit", "enabled", "symbol"})
GET_ALERT_QUERY: frozenset[str] = frozenset()
_SYMBOL = r"^[A-Z0-9]{2,20}USDT$"
Channel = Literal["in_app", "email", "webhook", "push", "desktop"]
OnCompile = Callable[[float, str | None], None]
#: E40-T03: the in-process change event (alert id) the evaluator re-keys on.
OnChange = Callable[[str], Awaitable[None]]


async def _no_change(_alert_id: str) -> None:
    return None


class AlertInput(BaseModel):
    """`AlertInput`; `extra="forbid"` so unknown top-level keys (e.g. `actions`) are refused."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    name: Annotated[str, Field(min_length=1, max_length=120)]
    symbol: Annotated[str, Field(pattern=_SYMBOL)] | None = None
    exchange_account_id: UUID | None = None
    trigger_mode: Literal["once", "every_time", "once_per_bar"] = "once"
    channels: Annotated[tuple[Channel, ...], Field(min_length=1, max_length=5)]
    condition_ir: Any
    message_template: Annotated[str, Field(max_length=500)] = ""
    severity: Literal["debug", "info", "warning", "error", "critical"] = "info"
    expires_at: datetime | None = None
    webhook_url: str | None = None
    enabled: bool = True


class _EnabledBody(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    enabled: bool


class _Problem(Exception):
    def __init__(self, status: int, code: str, title: str, detail: str, **extra: Any) -> None:
        super().__init__(detail)
        self.status, self.code, self.title, self.detail, self.extra = (
            status, code, title, detail, extra,
        )  # fmt: skip

    def response(self) -> JSONResponse:
        return JSONResponse(
            status_code=self.status,
            media_type="application/problem+json",
            content={
                "type": f"https://candleviewer.local/errors/{self.code}",
                "title": self.title,
                "status": self.status,
                "code": self.code,
                "detail": self.detail,
                **self.extra,
            },
        )


class _Refused(Exception):
    """A ready refusal raised from a dependency: the shared SR-026 query refusal, sent as is."""

    def __init__(self, response: JSONResponse) -> None:
        super().__init__(response.status_code)
        self.response = response


class _ProblemRoute(APIRoute):
    """Turns `_Problem` (or a ready `_Refused`) raised in a dependency or handler into an RFC 9457
    response."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        inner = super().get_route_handler()

        async def handler(request: Request) -> Response:
            try:
                return await inner(request)
            except _Problem as p:
                return p.response()
            except _Refused as r:
                return r.response

        return handler


def _not_found() -> _Problem:
    return _Problem(404, "not_found", "Not found", "No such alert.")


def _iso(d: datetime | None) -> str | None:
    return None if d is None else d.isoformat()


def _audit_view(row: AlertRow) -> dict[str, Any]:
    """Before/after for C-2.9: identity of the condition, never the template text."""
    return {"name": row.name, "condition_hash": row.condition_hash, "enabled": row.enabled,
            "channels": list(row.channels)}  # fmt: skip


class _Deps:
    """Per-router collaborators; each call re-reads its provider (module may restart)."""

    def __init__(
        self,
        repo: Callable[[], AlertRepository | None],
        registry: Callable[[], MetricRegistry | None],
        actor_resolver: Callable[[Request], Any] | None,
        audit: Any,
        on_compile: OnCompile,
        on_change: OnChange = _no_change,
    ) -> None:
        self.repo, self.registry, self.resolver = repo, registry, actor_resolver
        self.audit, self.on_compile, self.on_change = audit, on_compile, on_change

    def store(self) -> AlertRepository:
        r = self.repo()
        if r is None:
            raise _Problem(503, "service_unavailable", "Unavailable", "alerts store unavailable")
        return r

    def compiler(self) -> AlertCompiler:
        reg = self.registry()
        if reg is None:
            raise _Problem(503, "service_unavailable", "Unavailable", "metric registry unavailable")
        return AlertCompiler(reg)

    async def emit(self, action: str, actor: Actor, alert_id: str, **kw: Any) -> None:
        await self.audit.emit(
            action, actor_label=actor.user_id, actor_user_id=actor.user_id,
            object_kind="alert", object_id=alert_id, **kw,
        )  # fmt: skip

    def dump(self, row: AlertRow) -> dict[str, Any]:
        """`Alert`. Never carries `webhook_*_enc`: the repository does not select them."""
        return {
            "id": row.id, "owner_user_id": row.owner_user_id, "name": row.name,
            "symbol": row.symbol, "exchange_account_id": row.scope_account_id,
            "trigger_mode": row.trigger_mode, "channels": list(row.channels),
            "condition_ir": row.condition_ir, "condition_hash": row.condition_hash,
            "message_template": row.message_template, "severity": row.severity,
            "expires_at": _iso(row.expires_at), "webhook_url": None, "enabled": row.enabled,
            "fire_count": row.fire_count, "last_fired_at": _iso(row.last_fired_at),
            "created_at": _iso(row.created_at), "updated_at": _iso(row.updated_at),
        }  # fmt: skip

    def respond(self, row: AlertRow, status: int = 200, **extra: Any) -> JSONResponse:
        return JSONResponse(self.dump(row) | extra, status, headers={"ETag": f'"{row.etag}"'})


def make_alerts_router(
    repo_provider: Callable[[], AlertRepository | None],
    registry_provider: Callable[[], MetricRegistry | None],
    actor_resolver: Callable[[Request], Any] | None,
    audit: Any,
    on_compile: OnCompile = lambda seconds, reason: None,
    on_change: OnChange = _no_change,
) -> APIRouter:
    d = _Deps(repo_provider, registry_provider, actor_resolver, audit, on_compile, on_change)
    router = APIRouter(tags=["alerts"], route_class=_ProblemRoute)

    def need(
        perm: str, query: frozenset[str] | None = None
    ) -> Callable[[Request], Awaitable[Actor]]:
        """*query*: the operation's declared query parameters; any other key is refused (SR-026)
        once the caller holds *perm*, before anything is read."""

        async def dep(request: Request) -> Actor:
            if d.resolver is None:
                raise _Problem(501, "not_implemented", "Not implemented", "no principal resolver")
            got = d.resolver(request)
            actor: Actor | None = await got if inspect.isawaitable(got) else got
            if actor is None:
                raise _Problem(401, "unauthorized", "Unauthorized", "no verified session")
            if perm not in actor.perms:
                raise _Problem(403, "forbidden", "Forbidden", f"requires {perm}",
                               required_permissions=[perm])  # fmt: skip
            if query is not None:
                refusal = undeclared_query_refusal(request, query)
                if refusal is not None:
                    raise _Refused(refusal)
            return actor

        return dep

    def owned(
        perm: str, query: frozenset[str] | None = None
    ) -> Callable[..., Awaitable[tuple[Actor, AlertRow]]]:
        """`scope: self`: someone else's alert is indistinguishable from a missing one."""
        gate = need(perm, query)

        async def dep(alertId: UUID, actor: Annotated[Actor, Depends(gate)]) -> Any:
            row = await d.store().get(str(alertId))
            if row is None:
                raise _not_found()
            if row.owner_user_id != actor.user_id:
                await d.emit("alert.denied", actor, str(alertId), outcome=AuditOutcome.DENIED,
                             reason="alert owned by another user")  # fmt: skip
                raise _not_found()
            return actor, row

        return dep

    lister, writer = need(READ, LIST_ALERTS_QUERY), need(WRITE)
    owned_r, owned_w = owned(READ, GET_ALERT_QUERY), owned(WRITE)

    async def parse(request: Request, actor: Actor) -> tuple[AlertInput, Any]:
        try:
            body = AlertInput.model_validate(await request.json())
        except ValidationError as exc:
            errs = exc.errors(include_url=False, include_input=False)[:20]
            raise _Problem(422, "validation_failed", "Invalid alert", "The alert body is invalid.",
                           errors=[{"field": ".".join(map(str, e["loc"])), "rule": e["type"],
                                    "message": e["msg"]} for e in errs]) from None  # fmt: skip
        except ValueError:
            raise _Problem(422, "validation_failed", "Invalid alert", "Body is not JSON.") from None
        if "push" in body.channels:  # E40-T04: never accept an alert that can never deliver
            raise _Problem(422, "validation_failed", "Invalid alert",
                           "Push delivery is not available in this deployment.",
                           errors=[{"field": "channels", "rule": "channel_unavailable",
                                    "message": "push is not available"}])  # fmt: skip
        if body.webhook_url is not None or "webhook" in body.channels:
            raise _Problem(422, "validation_failed", "Invalid alert",
                           "Webhook delivery is not available yet.")  # fmt: skip
        acct = body.exchange_account_id
        if acct is not None and not actor.is_owner and str(acct) not in actor.granted_accounts:
            raise _Problem(403, "forbidden", "Forbidden", "no grant on that account")
        started = time.perf_counter()
        try:
            compiled = d.compiler().compile(body.condition_ir)
            validate_template(body.message_template, compiled.metrics)
        except AlertIrInvalid as exc:
            d.on_compile(time.perf_counter() - started, exc.reason)
            raise _Problem(422, "rule_ir_invalid",
                           "Rule intermediate representation failed semantic validation",
                           f"{len(exc.issues)} problem(s) in the alert.",
                           errors=[i.to_dict() for i in exc.issues]) from None  # fmt: skip
        d.on_compile(time.perf_counter() - started, None)
        return body, compiled

    def fields(body: AlertInput, compiled: Any) -> dict[str, Any]:
        return {
            "name": body.name, "symbol": body.symbol,
            "scope_account_id": None if body.exchange_account_id is None
            else str(body.exchange_account_id),
            "condition_ir": compiled.condition_ir, "condition_hash": compiled.condition_hash,
            "trigger_mode": body.trigger_mode, "expires_at": body.expires_at,
            "severity": body.severity, "channels": body.channels,
            "message_template": body.message_template, "enabled": body.enabled,
        }  # fmt: skip

    def update_fields(body: AlertInput, compiled: Any, row: AlertRow) -> dict[str, Any]:
        return fields(body, compiled) | {"cooldown_seconds": row.cooldown_seconds}

    def name_taken() -> _Problem:
        return _Problem(409, "conflict", "Conflict", "You already have an alert with this name.")

    @router.get("/alerts")
    async def list_alerts(
        actor: Annotated[Actor, Depends(lister)],
        cursor: Annotated[str | None, Query(max_length=512)] = None,
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
        enabled: bool | None = None,
        symbol: Annotated[str | None, Query(pattern=_SYMBOL)] = None,
    ) -> Response:
        try:
            page = await d.store().list_page(
                actor.user_id, cursor=cursor, limit=limit, enabled=enabled, symbol=symbol
            )
        except ValueError:
            raise _Problem(400, "validation_failed", "Bad request", "invalid cursor") from None
        items = [d.dump(r) for r in page.items]
        meta = {"next_cursor": page.next_cursor, "has_more": page.next_cursor is not None,
                "count": len(items)}  # fmt: skip
        return JSONResponse({"items": items, "meta": meta})

    @router.post("/alerts")
    async def create_alert(request: Request, actor: Annotated[Actor, Depends(writer)]) -> Response:
        body, compiled = await parse(request, actor)
        alert_id = str(uuid4())
        # Write-ahead (C-2.9): the audit record lands first; if it fails nothing is persisted.
        await d.emit("alert.created", actor, alert_id, after_state={
            "name": body.name, "condition_hash": compiled.condition_hash,
            "enabled": body.enabled, "channels": list(body.channels)})  # fmt: skip
        try:
            row = await d.store().create(
                owner_user_id=actor.user_id, alert_id=alert_id, **fields(body, compiled)
            )
        except AlertNameTakenError:
            raise name_taken() from None
        await d.on_change(row.id)
        return d.respond(row, 201, estimated_metrics=list(compiled.estimated_metrics))

    @router.get("/alerts/{alertId}")
    async def get_alert(got: Annotated[tuple[Actor, AlertRow], Depends(owned_r)]) -> Response:
        return d.respond(got[1])

    @router.put("/alerts/{alertId}")
    async def update_alert(
        request: Request, got: Annotated[tuple[Actor, AlertRow], Depends(owned_w)]
    ) -> Response:
        actor, row = got
        raw = request.headers.get("if-match", "").strip().removeprefix("W/").strip('"')
        try:
            if_match = datetime.fromisoformat(raw) if raw else row.updated_at
        except ValueError:
            raise _stale() from None
        body, compiled = await parse(request, actor)
        if if_match != row.updated_at:  # stale: refuse before auditing (store re-checks atomically)
            raise _stale()
        await d.emit("alert.updated", actor, row.id, before_state=_audit_view(row),
                     after_state={"name": body.name, "condition_hash": compiled.condition_hash,
                                  "enabled": body.enabled,
                                  "channels": list(body.channels)})  # fmt: skip
        try:
            new = await d.store().update(
                row.id, if_match=if_match, **update_fields(body, compiled, row)
            )
        except AlertConflictError:
            raise _stale() from None
        except AlertNameTakenError:
            raise name_taken() from None
        await d.on_change(new.id)
        return d.respond(new, estimated_metrics=list(compiled.estimated_metrics))

    @router.delete("/alerts/{alertId}")
    async def delete_alert(got: Annotated[tuple[Actor, AlertRow], Depends(owned_w)]) -> Response:
        actor, row = got
        await d.emit("alert.deleted", actor, row.id, before_state={"name": row.name})
        if not await d.store().soft_delete(row.id):
            raise _not_found()
        await d.on_change(row.id)
        return Response(status_code=204)

    @router.put("/alerts/{alertId}/enabled")
    async def set_enabled(
        request: Request, got: Annotated[tuple[Actor, AlertRow], Depends(owned_w)]
    ) -> Response:
        actor, row = got
        try:
            body = _EnabledBody.model_validate(await request.json())
        except (ValueError, ValidationError):
            raise _Problem(422, "validation_failed", "Invalid body",
                           "Body must be {\"enabled\": true|false}.") from None  # fmt: skip
        await d.emit("alert.enabled" if body.enabled else "alert.disabled", actor, row.id,
                     before_state={"enabled": row.enabled},
                     after_state={"enabled": body.enabled})  # fmt: skip
        new = await d.store().set_enabled(row.id, body.enabled)
        if new is None:
            raise _not_found()
        await d.on_change(new.id)
        return d.respond(new)

    return router


def _stale() -> _Problem:
    return _Problem(412, "version_conflict", "If-Match / ETag precondition failed",
                    "The alert was changed by another session; reload and retry.")  # fmt: skip


__all__ = ["READ", "WRITE", "AlertInput", "make_alerts_router"]
