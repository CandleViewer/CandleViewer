"""`/rules` store, versions, active-version and mode routes (E35-S01).

Thin HTTP adapter over `rules.manager.RulesManager` (`22-api-openapi.yaml`
`listRules`..`setRuleMode`). Authorization is server-side (C-12.4): the injected
`actor_resolver` returns the caller's `Actor` (permissions, granted accounts, owner flag,
fresh step-up) or `None` (401). `rules:read` gates reads, `rules:write` gates writes;
live arming additionally needs `rules:arm_live` + a fresh one-shot step-up, enforced by the
manager's synchronous arming check (statecharts record, code enforces - C-2.21).
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from candleviewer.rules.errors import ScopeForbiddenError
from candleviewer.rules.ir.models import RuleScope
from candleviewer.rules.manager import Actor, RuleError, RulesManager
from candleviewer.rules.scope import ScopeResolver

_READ = "rules:read"
_WRITE = "rules:write"


def _problem(status: int, code: str, title: str, detail: str, **extra: Any) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        media_type="application/problem+json",
        content={
            "type": f"https://candleviewer.local/errors/{code}",
            "title": title,
            "status": status,
            "code": code,
            "detail": detail,
            **extra,
        },
    )


def _from_error(exc: RuleError) -> JSONResponse:
    """The problem a `RuleError` names: its `title` when it carries one (#2304: the contract's
    step-up title), else the humanised code."""
    extra = dict(exc.extra)
    title = str(extra.pop("title", exc.code.replace("_", " ").capitalize()))
    return _problem(exc.status, exc.code, title, exc.message, **extra)


def _doc(body: dict[str, Any]) -> dict[str, Any] | None:
    ir = body.get("ir")
    if not isinstance(ir, dict):
        return None
    doc = dict(ir)
    if isinstance(body.get("name"), str):
        doc["name"] = body["name"]
    if "scope" not in doc and isinstance(body.get("scope"), str):
        doc["scope"] = {"level": body["scope"]}
    return doc


def make_rules_crud_router(
    manager_provider: Callable[[], RulesManager | None],
    actor_resolver: Callable[[Request], Any] | None,
    scope_resolver: Callable[[], ScopeResolver | None] | None = None,
    scope_refresh: Callable[[UUID], Awaitable[None]] | None = None,
) -> APIRouter:
    router = APIRouter(tags=["rules"])

    async def _scope_check(actor: Actor, raw_scope: Any, *, arming: bool) -> JSONResponse | None:
        """C-12.4 on every state-changing route: 403 for accounts the caller has no grant on and,
        when live is in scope, without `rules.arm_live`. `arming` additionally writes the
        high-severity `rule_live_scope_armed` audit (the real arm transition only)."""
        resolver = scope_resolver() if scope_resolver is not None else None
        try:
            scope = RuleScope.model_validate(raw_scope if isinstance(raw_scope, dict) else {})
        except ValidationError:
            return None  # the manager's own validation reports the malformed scope (422)
        if resolver is None:
            if scope_resolver is not None and (scope.account_ids or "live" in scope.environments):
                return _problem(501, "not_implemented", "Not implemented", "no scope resolver")
            return None
        try:
            caller = UUID(actor.user_id)
        except ValueError:
            return _problem(403, "forbidden", "Forbidden", "Forbidden")
        if scope_refresh is not None:
            await scope_refresh(caller)  # current grants/freeze, never a stale cache
        try:
            await resolver.authorize_accounts(caller, [UUID(str(a)) for a in scope.account_ids])
            await resolver.authorize_environments(caller, scope, audit_armed=arming)
        except ScopeForbiddenError:
            return _problem(403, "forbidden", "Forbidden", ScopeForbiddenError.message)
        return None

    async def _active_scope(mgr: RulesManager, rule_id: str, actor: Actor) -> Any:
        """Scope of the version that would run (IDOR-checked by `get`)."""
        view = await mgr.get(rule_id, actor)
        vid = view.get("active_version_id")
        if not isinstance(vid, str):
            return {}
        ver = await mgr.version(rule_id, vid)
        return ver["ir"].get("scope", {})

    async def _gate(request: Request, perm: str) -> tuple[Actor, RulesManager] | JSONResponse:
        if actor_resolver is None:
            return _problem(
                501, "not_implemented", "Not implemented", "no principal resolver wired"
            )
        got = actor_resolver(request)
        actor: Actor | None = await got if inspect.isawaitable(got) else got
        if actor is None:
            return _problem(401, "unauthorized", "Unauthorized", "no verified session")
        if perm not in actor.perms:
            return _problem(403, "forbidden", "Forbidden", f"requires {perm}")
        mgr = manager_provider()
        if mgr is None:
            return _problem(503, "service_unavailable", "Unavailable", "rule engine unavailable")
        return actor, mgr

    async def _body(request: Request) -> dict[str, Any] | None:
        try:
            body = await request.json()
        except ValueError:
            return None
        return body if isinstance(body, dict) else None

    def _bad(detail: str) -> JSONResponse:
        return _problem(400, "validation_failed", "Bad request", detail)

    @router.get("/rules")
    async def list_rules(
        request: Request,
        mode: str | None = None,
        scope: str | None = None,
        cursor: str | None = None,
        limit: int = 100,
    ) -> Response:
        g = await _gate(request, _READ)
        if isinstance(g, JSONResponse):
            return g
        actor, mgr = g
        page = await mgr.list_rules(actor, mode, scope, cursor, max(1, min(limit, 200)))
        return JSONResponse(
            {
                "items": page["items"],
                "meta": {
                    "next_cursor": page["next_cursor"],
                    "has_more": page["next_cursor"] is not None,
                    "count": len(page["items"]),
                },
            }
        )

    @router.post("/rules")
    async def create_rule(request: Request) -> Response:
        g = await _gate(request, _WRITE)
        if isinstance(g, JSONResponse):
            return g
        actor, mgr = g
        body = await _body(request)
        doc = _doc(body) if body is not None else None
        if body is None or doc is None:
            return _bad("body needs an 'ir' object")
        denied = await _scope_check(actor, doc.get("scope"), arming=False)
        if denied is not None:
            return denied
        try:
            return JSONResponse(await mgr.create(doc, actor, str(body.get("note", ""))), 201)
        except RuleError as exc:
            return _from_error(exc)

    @router.get("/rules/{ruleId}")
    async def get_rule(ruleId: UUID, request: Request) -> Response:
        g = await _gate(request, _READ)
        if isinstance(g, JSONResponse):
            return g
        actor, mgr = g
        try:
            return JSONResponse(await mgr.get(str(ruleId), actor))
        except RuleError as exc:
            return _from_error(exc)

    @router.put("/rules/{ruleId}")
    async def update_rule(ruleId: UUID, request: Request) -> Response:
        g = await _gate(request, _WRITE)
        if isinstance(g, JSONResponse):
            return g
        actor, mgr = g
        body = await _body(request)
        doc = _doc(body) if body is not None else None
        raw = request.headers.get("if-match", "").strip().strip('"')
        if raw == "" and body is not None:
            raw = str(body.get("expected_version", ""))
        if body is None or doc is None:
            return _bad("body needs an 'ir' object")
        if not raw.isdigit():
            return _bad("send the version you edited in If-Match (or expected_version)")
        denied = await _scope_check(actor, doc.get("scope"), arming=False)
        if denied is not None:
            return denied
        try:
            out = await mgr.update(str(ruleId), doc, int(raw), actor, str(body.get("note", "")))
        except RuleError as exc:
            return _from_error(exc)
        return JSONResponse(out)

    @router.delete("/rules/{ruleId}")
    async def delete_rule(ruleId: UUID, request: Request) -> Response:
        g = await _gate(request, _WRITE)
        if isinstance(g, JSONResponse):
            return g
        actor, mgr = g
        try:
            await mgr.delete(str(ruleId), actor)
        except RuleError as exc:
            return _from_error(exc)
        return Response(status_code=204)

    @router.get("/rules/{ruleId}/versions")
    async def list_versions(ruleId: UUID, request: Request) -> Response:
        g = await _gate(request, _READ)
        if isinstance(g, JSONResponse):
            return g
        actor, mgr = g
        try:
            await mgr.get(str(ruleId), actor)  # visibility (IDOR) check
            items = await mgr.versions(str(ruleId))
        except RuleError as exc:
            return _from_error(exc)
        return JSONResponse(
            {"items": items, "meta": {"next_cursor": None, "has_more": False, "count": len(items)}}
        )

    @router.get("/rules/{ruleId}/versions/{versionId}")
    async def get_version(ruleId: UUID, versionId: UUID, request: Request) -> Response:
        g = await _gate(request, _READ)
        if isinstance(g, JSONResponse):
            return g
        actor, mgr = g
        try:
            await mgr.get(str(ruleId), actor)
            return JSONResponse(await mgr.version(str(ruleId), str(versionId)))
        except RuleError as exc:
            return _from_error(exc)

    @router.put("/rules/{ruleId}/active-version")
    async def set_active(ruleId: UUID, request: Request) -> Response:
        g = await _gate(request, _WRITE)
        if isinstance(g, JSONResponse):
            return g
        actor, mgr = g
        body = await _body(request)
        if body is None or not isinstance(body.get("version_id"), str):
            return _bad("body needs 'version_id'")
        try:
            # Visibility first (#2574): on a rule the caller cannot see, a real version and a
            # missing rule or version are one 404, never the scope pre-check's 403 (04 §7.3).
            ver = await mgr.visible_version(
                str(ruleId), body["version_id"], actor, "set_active_version"
            )
            denied = await _scope_check(actor, ver["ir"].get("scope"), arming=False)
            if denied is not None:
                return denied
            out = await mgr.set_active_version(
                str(ruleId), body["version_id"], str(body.get("note", "")), actor
            )
        except RuleError as exc:
            return _from_error(exc)
        return JSONResponse(out)

    @router.put("/rules/{ruleId}/mode")
    async def set_mode(ruleId: UUID, request: Request) -> Response:
        g = await _gate(request, _WRITE)
        if isinstance(g, JSONResponse):
            return g
        actor, mgr = g
        body = await _body(request)
        if (
            body is None
            or not isinstance(body.get("mode"), str)
            or set(body)
            - {
                "mode",
                "reason",
                "acknowledge_flatten_all",
            }
        ):
            return _bad("body must be {mode, reason?, acknowledge_flatten_all?}")
        try:
            if body["mode"] == "armed":
                denied = await _scope_check(
                    actor, await _active_scope(mgr, str(ruleId), actor), arming=True
                )
                if denied is not None:
                    return denied
            out = await mgr.set_mode(
                str(ruleId),
                body["mode"],
                actor,
                request.headers.get("idempotency-key"),
                flatten_ack=body.get("acknowledge_flatten_all") is True,
                override_reason=body.get("reason") if isinstance(body.get("reason"), str) else None,
            )
        except RuleError as exc:
            return _from_error(exc)
        return JSONResponse(out)

    return router


__all__ = ["make_rules_crud_router"]
