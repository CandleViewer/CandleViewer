"""`GET /rules/vocabulary`, `GET /schemas/rule-ir.json` (E35-T03).

RBAC (C-12.4): `rules:read`, fail-closed like `api/ticker.py`. The response
varies per caller (availability annotations), hence `Cache-Control: private`
and an ETag over content + permission set. An empty registry -> `503` problem
document, never an empty catalogue (SCR-081 engine-offline state).
"""

from __future__ import annotations

import inspect
import json
from collections.abc import Awaitable, Callable
from typing import Any, Protocol
from uuid import UUID

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from candleviewer.rules.compiler import compile_form, compile_graph
from candleviewer.rules.compiler.common import build_rule, check_bounds
from candleviewer.rules.errors import ScopeForbiddenError
from candleviewer.rules.ir import canonicalize, ir_hash
from candleviewer.rules.ir.schema import to_json_schema
from candleviewer.rules.issues import RuleCompileError
from candleviewer.rules.scope import ScopeResolver
from candleviewer.rules.validator import LOOSEN_STOP_PERMISSION, validate_rule
from candleviewer.rules.vocabulary import (
    MetricRegistry,
    VocabularyUnavailableError,
    build_vocabulary,
    etag_for,
)
from candleviewer.rules.vocabulary.catalogue import ARM_LIVE_PERMISSION

_REQUIRED = "rules:read"
#: Probed on the caller to annotate the vocabulary and feed the validator. Named constants,
#: never literals: they must match what the catalogue and the validator check (#2624).
_ADVISORY_PERMISSIONS = ("orders:write", LOOSEN_STOP_PERMISSION, ARM_LIVE_PERMISSION)
_CACHE = "private, max-age=60"
_Counter = Callable[[str], None]


def _diff(a: Any, b: Any, path: str = "") -> list[dict[str, Any]]:
    """Structured diff of two canonical documents (``model`` vs ``counterpart``)."""
    if isinstance(a, dict) and isinstance(b, dict):
        out: list[dict[str, Any]] = []
        for k in sorted(set(a) | set(b)):
            out += _diff(a.get(k), b.get(k), f"{path}/{k}")
        return out
    if isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        return [
            d for i, (x, y) in enumerate(zip(a, b, strict=True)) for d in _diff(x, y, f"{path}/{i}")
        ]
    return [] if a == b else [{"path": path or "/", "model": a, "counterpart": b}]


class _Principal(Protocol):
    def has(self, permission: str) -> bool: ...


class _Resolver(Protocol):
    """Sync or async resolver (`resolve(request)` may return an awaitable)."""

    def resolve(self, request: Request) -> Any: ...


def _problem(status: int, title: str, detail: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        media_type="application/problem+json",
        content={"type": "about:blank", "title": title, "status": status, "detail": detail},
    )


def make_rules_router(
    registry_provider: Callable[[], MetricRegistry | None],
    *,
    principal_resolver: _Resolver | None = None,
    recorded_symbols: Callable[[], frozenset[str]] = lambda: frozenset(),
    on_request: _Counter = lambda cache: None,
    on_compile: Callable[[str, str], None] = lambda editor, result: None,
    on_divergence: Callable[[str, int], Any] = lambda editor, n_diffs: None,
    scope_resolver: ScopeResolver | None = None,
    scope_refresh: Callable[[UUID], Awaitable[None]] | None = None,
) -> APIRouter:
    router = APIRouter(tags=["rules"])

    async def _authorize(request: Request) -> tuple[_Principal | None, JSONResponse | None]:
        if principal_resolver is None:
            return None, _problem(501, "Not implemented", "no principal resolver wired")
        resolved = principal_resolver.resolve(request)
        principal: _Principal | None = await resolved if inspect.isawaitable(resolved) else resolved
        if principal is None:
            return None, _problem(401, "Unauthorized", "no verified session for this request")
        if not principal.has(_REQUIRED):
            return None, _problem(403, "Forbidden", f"requires {_REQUIRED}")
        return principal, None

    def _caller(principal: _Principal) -> UUID | None:
        uid = getattr(principal, "user_id", None)
        return uid if isinstance(uid, UUID) else None

    async def _authorize_scope(principal: _Principal, rule: Any) -> JSONResponse | None:
        """C-12.4: 403 on any account/environment the caller may not use (no existence leak)."""
        if scope_resolver is None:
            if rule.scope.account_ids or "live" in rule.scope.environments:
                return _problem(501, "Not implemented", "no scope resolver wired")  # fail closed
            return None
        caller = _caller(principal)
        if caller is None:
            return _problem(401, "Unauthorized", "no verified user identity")
        if scope_refresh is not None:
            await scope_refresh(caller)  # current grants/freeze, never a stale cache
        try:
            await scope_resolver.authorize_accounts(
                caller, [UUID(str(a)) for a in rule.scope.account_ids]
            )
            await scope_resolver.authorize_environments(caller, rule.scope, audit_armed=False)
        except ScopeForbiddenError:
            return _problem(403, "Forbidden", ScopeForbiddenError.message)
        return None

    @router.get("/rules/accounts")
    async def list_rule_accounts(request: Request) -> Response:
        """AC2: only accounts the caller is granted; others are absent (no existence leak)."""
        principal, denied = await _authorize(request)
        if denied is not None or principal is None:
            return denied or _problem(401, "Unauthorized", "no session")
        if scope_resolver is None:
            return _problem(501, "Not implemented", "no scope resolver wired")
        caller = _caller(principal)
        if caller is None:
            return _problem(401, "Unauthorized", "no verified user identity")
        if scope_refresh is not None:
            await scope_refresh(caller)
        return JSONResponse(
            {"accounts": [str(a) for a in scope_resolver.listable_accounts(caller)]}
        )

    @router.get("/rules/vocabulary")
    async def get_vocabulary(request: Request, symbol: str | None = None) -> Response:
        principal, denied = await _authorize(request)
        if denied is not None or principal is None:
            return denied or _problem(401, "Unauthorized", "no session")
        if symbol is not None:
            if not (4 <= len(symbol) <= 20 and symbol.isascii() and symbol.isalnum()):
                return _problem(400, "Bad request", "invalid symbol")
            symbol = symbol.upper()
        registry = registry_provider()
        perms = frozenset(p for p in _ADVISORY_PERMISSIONS if principal.has(p))
        try:
            if registry is None:
                raise VocabularyUnavailableError("metric registry not wired")
            body: dict[str, Any] = build_vocabulary(
                registry, permissions=perms, symbol=symbol, recorded_symbols=recorded_symbols()
            )
        except VocabularyUnavailableError:
            return _problem(503, "Service unavailable", "rule engine vocabulary unavailable")
        etag = etag_for(body, perms, symbol)
        headers = {"ETag": etag, "Cache-Control": _CACHE, "Vary": "Authorization"}
        if request.headers.get("if-none-match") == etag:
            on_request("hit")
            return Response(status_code=304, headers=headers)
        on_request("miss")
        return Response(json.dumps(body), media_type="application/json", headers=headers)

    async def _notify_divergence(editor: str, n: int) -> None:
        res = on_divergence(editor, n)
        if inspect.isawaitable(res):
            await res

    async def _json_body(request: Request) -> dict[str, Any] | None:
        try:
            body = await request.json()
        except ValueError:
            return None
        return body if isinstance(body, dict) else None

    def _invalid(exc: RuleCompileError) -> JSONResponse:
        n = len(exc.issues)
        return JSONResponse(
            status_code=422,
            media_type="application/problem+json",
            content={
                "type": "https://candleviewer.local/errors/rule_ir_invalid",
                "title": "Rule intermediate representation failed semantic validation",
                "status": 422,
                "detail": f"{n} error{'s' if n != 1 else ''} in the rule IR.",
                "code": "rule_ir_invalid",
                "errors": [
                    {"field": i.path, "rule": i.code, "message": i.message,
                     "node_ids": list(i.node_ids)}
                    for i in exc.issues
                ],
            },
        )  # fmt: skip

    @router.post("/rules/validate")
    async def post_validate(request: Request) -> Response:
        principal, denied = await _authorize(request)
        if denied is not None or principal is None:
            return denied or _problem(401, "Unauthorized", "no session")
        registry = registry_provider()
        if registry is None:
            return _problem(503, "Service unavailable", "rule engine vocabulary unavailable")
        body = await _json_body(request)
        if body is None or not isinstance(body.get("ir"), dict) or set(body) - {"ir", "scope"}:
            return _problem(400, "Bad request", "body must be an object with an 'ir' object")
        perms = frozenset(p for p in _ADVISORY_PERMISSIONS if principal.has(p))
        try:
            check_bounds(body["ir"], "rule")
            rule = build_rule(body["ir"])
        except RuleCompileError as exc:  # a failing IR is still a 200 with valid=false
            errs = [i.to_dict() for i in exc.issues]
            return JSONResponse(
                {"valid": False, "errors": errs, "warnings": [], "referenced_variables": [],
                 "referenced_actions": [], "estimated_evaluations_per_minute": 0}
            )  # fmt: skip
        forbidden = await _authorize_scope(principal, rule)
        if forbidden is not None:
            return forbidden
        result = validate_rule(rule, registry, perms)
        return JSONResponse(result.to_dict())

    @router.post("/rules/{ruleId}/compile")
    async def post_compile(ruleId: UUID, request: Request) -> Response:
        principal, denied = await _authorize(request)
        if denied is not None or principal is None:
            return denied or _problem(401, "Unauthorized", "no session")
        registry = registry_provider()
        if registry is None:
            return _problem(503, "Service unavailable", "rule engine vocabulary unavailable")
        body = await _json_body(request)
        editor = body.get("editor") if body else None
        model = body.get("model") if body else None
        if body is None or editor not in ("form", "graph") or not isinstance(model, dict):
            return _problem(400, "Bad request", "body needs 'editor' (form|graph) and 'model'")
        perms = frozenset(p for p in _ADVISORY_PERMISSIONS if principal.has(p))
        compile_fn = compile_form if editor == "form" else compile_graph
        try:
            rule = compile_fn(model, ruleId)
        except RuleCompileError as exc:
            on_compile(editor, "invalid")
            return _invalid(exc)
        forbidden = await _authorize_scope(principal, rule)
        if forbidden is not None:
            return forbidden
        result = validate_rule(rule, registry, perms)
        on_compile(editor, "ok" if result.valid else "issues")
        issues = [*result.errors, *result.warnings]
        payload: dict[str, Any] = {
            "ir": json.loads(rule.model_dump_json()),
            "ir_hash": ir_hash(rule),
            "issues": [i.to_dict() for i in issues],
            "blocks_arming": result.blocks_arming,
        }
        other = body.get("counterpart_model")
        if other is not None:
            if not isinstance(other, dict):
                return _problem(400, "Bad request", "'counterpart_model' must be an object")
            other_fn = compile_graph if editor == "form" else compile_form
            try:
                other_rule = other_fn(other, ruleId)
            except RuleCompileError as exc:
                await _notify_divergence(editor, len(exc.issues))
                return _invalid(exc)
            diff = _diff(json.loads(canonicalize(rule)), json.loads(canonicalize(other_rule)))
            if diff:  # never auto-reconcile: report only, the caller aborts the switch
                await _notify_divergence(editor, len(diff))
            payload["round_trip"] = {"match": not diff, "diff": diff}
        return JSONResponse(payload)

    @router.get("/schemas/rule-ir.json")
    async def get_rule_ir_schema(request: Request) -> Response:
        _, denied = await _authorize(request)
        if denied is not None:
            return denied
        return JSONResponse(to_json_schema(), headers={"Cache-Control": _CACHE})

    return router


__all__ = ["make_rules_router"]
