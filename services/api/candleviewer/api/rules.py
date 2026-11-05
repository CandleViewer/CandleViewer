"""`GET /rules/vocabulary`, `GET /schemas/rule-ir.json` (E35-T03).

RBAC (C-12.4): `rules:read`, fail-closed like `api/ticker.py`. The response
varies per caller (availability annotations), hence `Cache-Control: private`
and an ETag over content + permission set. An empty registry -> `503` problem
document, never an empty catalogue (SCR-081 engine-offline state).
"""

from __future__ import annotations

import asyncio
import inspect
import json
from collections.abc import Awaitable, Callable
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import Any, Final, Protocol
from uuid import UUID

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from candleviewer.api.preview_limiter import PreviewLimiter
from candleviewer.api.rule_body import read_object
from candleviewer.audit.writer import AuditUnavailable
from candleviewer.domain.text import escape_unpaired
from candleviewer.observability.context import executor_future
from candleviewer.rules.compiler import compile_form, compile_graph
from candleviewer.rules.compiler.common import (
    ConditionNodeBoundError,
    build_rule,
    check_bounds,
    holds_more_values,
    value_issues,
)
from candleviewer.rules.errors import ScopeForbiddenError
from candleviewer.rules.ir import Rule, canonicalize, ir_hash
from candleviewer.rules.ir.canonical import IrValueError
from candleviewer.rules.ir.schema import to_json_schema
from candleviewer.rules.issues import MAX_RETURNED_ISSUES, RuleCompileError
from candleviewer.rules.scope import ScopeResolver
from candleviewer.rules.validator import RuleValidationResult, validate_rule
from candleviewer.rules.vocabulary import (
    MetricRegistry,
    VocabularyUnavailableError,
    build_vocabulary,
    etag_for,
)
from candleviewer.rules.vocabulary.catalogue import ARM_LIVE_PERMISSION
from candleviewer.ws._generated.error_codes import ERROR_META, ErrorCode

_REQUIRED = "rules:read"
#: Probed on the caller to annotate the vocabulary. Named constants, never literals: they must
#: match what the catalogue declares (#2624). The validator takes none (24 §8.8 rule 5).
_ADVISORY_PERMISSIONS = ("orders:write", ARM_LIVE_PERMISSION)
_CACHE = "private, max-age=60"
_Counter = Callable[[str], None]
#: `validateRule` and `compileRule` share one token bucket per user, its burst this many times its
#: rate (22 `validateRule`).
CHECK_BURST_FACTOR: Final = 2
#: The checks that bucket covers, the closed set of `rule_authoring_rate_limited_total{route}`.
CHECK_ROUTES: Final = ("validate", "compile")
#: The one bucket of every principal that carries no user id.
_NO_USER: Final = UUID(int=0)
#: A check whose body holds more values than this, counted as `check_bounds` counts a document's,
#: parses, compiles and validates on the check worker; one with no more runs in place. Why this
#: many: per value, the costliest bodies are the widest valid content (each condition checked as a
#: rule's) and the deepest failing content (refused field by field, every list stopping at its
#: first refused entry); at this count either stays a fraction of C-2.17's 50 ms on the loop (the
#: perf test pins both), while a rule the editors validate, a few hundred values, stays in place.
OFF_LOOP_VALUES: Final = 512
#: Checks the worker admits at once, running or waiting; past it a check that would run there is
#: `429 rate_limited` (22 "Bounded answer"), so the worker's queue is bounded (C-2.18).
MAX_CHECKS_IN_FLIGHT: Final = 4
_Compiler = Callable[[dict[str, Any], Any], Rule]


def _diff(a: Any, b: Any, out: list[dict[str, Any]], path: str = "") -> int:
    """The leaves where two canonical documents differ (``model`` vs ``counterpart``), counted;
    `out` gets the first `MAX_RETURNED_ISSUES` of them, in document order."""
    if isinstance(a, dict) and isinstance(b, dict):
        return sum(_diff(a.get(k), b.get(k), out, f"{path}/{k}") for k in sorted(set(a) | set(b)))
    if isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        pairs = enumerate(zip(a, b, strict=True))
        return sum(_diff(x, y, out, f"{path}/{i}") for i, (x, y) in pairs)
    if a == b:
        return 0
    if len(out) < MAX_RETURNED_ISSUES:
        out.append({"path": path or "/", "model": a, "counterpart": b})
    return 1


def _compile_error(exc: RuleCompileError | IrValueError) -> RuleCompileError:
    """A value the hash cannot hold (NaN in ``params``) is refused as a compile error is: 422."""
    return exc if isinstance(exc, RuleCompileError) else RuleCompileError(value_issues(exc))


def _parsed(ir: dict[str, Any]) -> Rule:
    """`validateRule`'s document as a rule: its bounds, its schema, then what compile hashes, so
    a value the hash cannot hold is not valid."""
    check_bounds(ir, "rule")
    rule = build_rule(ir)
    canonicalize(rule)
    return rule


def _validated(rule: Rule, registry: MetricRegistry) -> RuleValidationResult:
    return validate_rule(rule, registry, limit_caps=True)


def _compiled(compile_fn: _Compiler, model: dict[str, Any], rule_id: UUID) -> tuple[Rule, str]:
    rule = compile_fn(model, rule_id)
    return rule, ir_hash(rule)


def _round_trip(
    rule: Rule, other_fn: _Compiler, other: dict[str, Any], rule_id: UUID
) -> tuple[list[dict[str, Any]], int]:
    """The counterpart model compiled, then the diff of the two canonical documents: its first
    entries and the count of all."""
    other_view = json.loads(canonicalize(other_fn(other, rule_id)))
    diff: list[dict[str, Any]] = []
    return diff, _diff(json.loads(canonicalize(rule)), other_view, diff)


async def _in_place[T](fn: Callable[..., T], /, *args: Any) -> T:
    return fn(*args)


class CheckWorker:
    """The one thread the large checks run on, their own and never the loop's default executor
    (which the audit write-ahead shares), and the checks admitted to it: at most `limit`."""

    def __init__(self, limit: int = MAX_CHECKS_IN_FLIGHT) -> None:
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="cv-rule-check")
        self._limit = limit
        self.admitted = 0

    def admit(self) -> bool:
        """A slot for one check, else False: `limit` checks hold one."""
        if self.admitted >= self._limit:
            return False
        self.admitted += 1
        return True

    def release(self) -> None:
        self.admitted -= 1

    async def run[T](self, fn: Callable[..., T], /, *args: Any) -> T:
        """`fn(*args)` on the worker. A cancelled caller waits for it to return before the
        cancellation goes on, so a check holds its slot while the thread works for it."""
        job = executor_future(self._pool, fn, *args)
        cancel: asyncio.CancelledError | None = None
        while not job.done():
            try:
                await asyncio.wait([job])  # never cancels the job
            except asyncio.CancelledError as exc:
                cancel = cancel or exc
        if cancel is not None:
            raise cancel
        return job.result()


class _Principal(Protocol):
    def has(self, permission: str) -> bool: ...


class _Run(Protocol):
    """How a check runs each step: in place, or on the check worker."""

    def __call__[T](self, fn: Callable[..., T], /, *args: Any) -> Awaitable[T]: ...


class _Resolver(Protocol):
    """Sync or async resolver (`resolve(request)` may return an awaitable)."""

    def resolve(self, request: Request) -> Any: ...


#: The scope resolver as `make_rules_router` takes it: the resolver itself, or a provider read on
#: every request (the composition root wires the scope after it builds the router).
_ResolverSource = ScopeResolver | Callable[[], ScopeResolver | None] | None


def _scope_resolver(source: _ResolverSource) -> ScopeResolver | None:
    """The resolver `source` names now: an instance as given, a provider called, `None` unwired."""
    if source is None or isinstance(source, ScopeResolver):
        return source
    return source()


def _problem(status: int, title: str, detail: str, *, code: str | None = None) -> JSONResponse:
    """An RFC 7807 problem; `code` is the contract's machine-readable code (22 `x-error-codes`),
    for the answers that have one."""
    content: dict[str, Any] = {
        "type": "about:blank",
        "title": title,
        "status": status,
        "detail": detail,
    }
    if code is not None:
        content["code"] = code
    return JSONResponse(status_code=status, media_type="application/problem+json", content=content)


def _rate_limited(wait: int) -> JSONResponse:
    """`429 rate_limited` (22 `RateLimited`): the wait, whole seconds and at least one, in
    `Retry-After` and again in the body. It writes no audit record."""
    code = ErrorCode.RATE_LIMITED
    body = {
        "type": f"https://candleviewer.local/errors/{code.value}",
        "title": ERROR_META[code].title,
        "status": 429,
        "code": code.value,
        "detail": "Too many rule checks; retry after the delay given.",
        "retry_after_seconds": wait,
    }
    headers = {"Retry-After": str(wait)}
    return JSONResponse(body, 429, headers, media_type="application/problem+json")


def make_rules_router(
    registry_provider: Callable[[], MetricRegistry | None],
    *,
    principal_resolver: _Resolver | None = None,
    recorded_symbols: Callable[[], frozenset[str]] = lambda: frozenset(),
    on_request: _Counter = lambda cache: None,
    on_compile: Callable[[str, str], None] = lambda editor, result: None,
    on_divergence: Callable[[str, int], Any] = lambda editor, n_diffs: None,
    scope_resolver: _ResolverSource = None,
    scope_refresh: Callable[[UUID], Awaitable[None]] | None = None,
    check_limiter: PreviewLimiter,
    on_rate_limited: _Counter = lambda route: None,
    on_cap_refused: _Counter = lambda cap: None,
    check_worker: CheckWorker | None = None,
) -> APIRouter:
    router = APIRouter(tags=["rules"])
    worker = CheckWorker() if check_worker is None else check_worker

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

    def _throttled(principal: _Principal, route: str) -> JSONResponse | None:
        """The check's token from the caller's bucket, else the `429`: one bucket per user, shared
        by validate and compile and across the user's sessions, and one for every principal with
        no user id. Taken after `_authorize` and before the body is read. A router is never built
        without its limiter (a required argument)."""
        caller = _caller(principal)
        wait = check_limiter.try_take(_NO_USER if caller is None else caller)
        if wait is None:
            return None
        on_rate_limited(route)
        return _rate_limited(wait)

    async def _authorize_scope(principal: _Principal, rule: Any) -> JSONResponse | None:
        """C-12.4: 403 on any account/environment the caller may not use (no existence leak)."""
        resolver = _scope_resolver(scope_resolver)
        if resolver is None:
            if rule.scope.account_ids or "live" in rule.scope.environments:
                return _problem(501, "Not implemented", "no scope resolver wired")  # fail closed
            return None
        caller = _caller(principal)
        if caller is None:
            return _problem(401, "Unauthorized", "no verified user identity")
        if scope_refresh is not None:
            await scope_refresh(caller)  # current grants/freeze, never a stale cache
        try:
            await resolver.authorize_accounts(
                caller, [UUID(str(a)) for a in rule.scope.account_ids]
            )
            await resolver.authorize_environments(caller, rule.scope, audit_armed=False)
        except ScopeForbiddenError:
            return _problem(403, "Forbidden", ScopeForbiddenError.message)
        except AuditUnavailable:  # the scope's record was not written (C-2.9): nothing proceeds
            return _problem(
                503,
                "Service unavailable",
                "the scope check could not be recorded",
                code="audit_unavailable",
            )
        return None

    @router.get("/rules/accounts")
    async def list_rule_accounts(request: Request) -> Response:
        """AC2: only accounts the caller is granted; others are absent (no existence leak)."""
        principal, denied = await _authorize(request)
        if denied is not None or principal is None:
            return denied or _problem(401, "Unauthorized", "no session")
        # Read per request: the composition root wires the scope after it builds this router.
        resolver = _scope_resolver(scope_resolver)
        if resolver is None:
            return _problem(501, "Not implemented", "no scope resolver wired")
        caller = _caller(principal)
        if caller is None:
            return _problem(401, "Unauthorized", "no verified user identity")
        if scope_refresh is not None:
            await scope_refresh(caller)
        return JSONResponse({"accounts": [str(a) for a in resolver.listable_accounts(caller)]})

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

    async def _json_body(request: Request) -> dict[str, Any] | JSONResponse | None:
        """Read as the rule write routes read (`api/rule_body.py`): the 413 past the ceiling, a 400
        for a body nested too deep, None for anything but a JSON object."""
        return await read_object(request, lambda detail: _problem(400, "Bad request", detail))

    def _counted(exc: RuleCompileError | IrValueError) -> RuleCompileError:
        """`_compile_error`, a refusal of the condition-node bound counted on the way."""
        if isinstance(exc, ConditionNodeBoundError):
            on_cap_refused(exc.cap)
        return _compile_error(exc)

    def _invalid(exc: RuleCompileError) -> JSONResponse:
        """`422 rule_ir_invalid`: the first `MAX_RETURNED_ISSUES` errors, and every one found
        counted in `detail` and in `issues_total`."""
        n = exc.total
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
                    {"field": escape_unpaired(i.path), "rule": i.code,
                     "message": escape_unpaired(i.message),
                     "node_ids": [escape_unpaired(nid) for nid in i.node_ids]}
                    for i in exc.issues[:MAX_RETURNED_ISSUES]
                ],
                "issues_total": n,
            },
        )  # fmt: skip

    async def _checked(
        body: dict[str, Any], check: Callable[[_Run], Awaitable[Response]]
    ) -> Response:
        """`check(run)`, `run` taking each step in place, or on the check worker for a body of more
        than `OFF_LOOP_VALUES` values: `429 rate_limited` while it holds its limit of checks."""
        if not holds_more_values(body, OFF_LOOP_VALUES):
            return await check(_in_place)
        if not worker.admit():
            return _rate_limited(1)
        try:
            return await check(worker.run)
        finally:
            worker.release()

    @router.post("/rules/validate")
    async def post_validate(request: Request) -> Response:
        principal, denied = await _authorize(request)
        if denied is not None or principal is None:
            return denied or _problem(401, "Unauthorized", "no session")
        if (limited := _throttled(principal, "validate")) is not None:
            return limited
        registry = registry_provider()
        if registry is None:
            return _problem(503, "Service unavailable", "rule engine vocabulary unavailable")
        body = await _json_body(request)
        if isinstance(body, JSONResponse):
            return body
        if body is None or not isinstance(body.get("ir"), dict) or set(body) - {"ir", "scope"}:
            return _problem(400, "Bad request", "body must be an object with an 'ir' object")
        return await _checked(body, partial(_validate, principal, registry, body["ir"]))

    async def _validate(
        principal: _Principal, registry: MetricRegistry, ir: dict[str, Any], run: _Run
    ) -> Response:
        try:
            rule = await run(_parsed, ir)
        except (RuleCompileError, IrValueError) as exc:  # still a 200 with valid=false
            err = _counted(exc)
            errs = [i.to_dict() for i in err.issues[:MAX_RETURNED_ISSUES]]
            return JSONResponse(
                {"valid": False, "errors": errs, "warnings": [], "issues_total": err.total,
                 "referenced_variables": [], "referenced_actions": [],
                 "estimated_evaluations_per_minute": 0}
            )  # fmt: skip
        forbidden = await _authorize_scope(principal, rule)
        if forbidden is not None:
            return forbidden
        result = await run(_validated, rule, registry)
        return JSONResponse(result.to_dict())

    @router.post("/rules/{ruleId}/compile")
    async def post_compile(ruleId: UUID, request: Request) -> Response:
        principal, denied = await _authorize(request)
        if denied is not None or principal is None:
            return denied or _problem(401, "Unauthorized", "no session")
        if (limited := _throttled(principal, "compile")) is not None:
            return limited
        registry = registry_provider()
        if registry is None:
            return _problem(503, "Service unavailable", "rule engine vocabulary unavailable")
        body = await _json_body(request)
        if isinstance(body, JSONResponse):
            return body
        editor = body.get("editor") if body else None
        model = body.get("model") if body else None
        if body is None or editor not in ("form", "graph") or not isinstance(model, dict):
            return _problem(400, "Bad request", "body needs 'editor' (form|graph) and 'model'")
        check = partial(_compile, principal, registry, body, editor, model, ruleId)
        return await _checked(body, check)

    async def _compile(
        principal: _Principal,
        registry: MetricRegistry,
        body: dict[str, Any],
        editor: str,
        model: dict[str, Any],
        ruleId: UUID,
        run: _Run,
    ) -> Response:
        compile_fn = compile_form if editor == "form" else compile_graph
        try:
            rule, rule_hash = await run(_compiled, compile_fn, model, ruleId)
        except (RuleCompileError, IrValueError) as exc:
            on_compile(editor, "invalid")
            return _invalid(_counted(exc))
        forbidden = await _authorize_scope(principal, rule)
        if forbidden is not None:
            return forbidden
        result = await run(_validated, rule, registry)
        on_compile(editor, "ok" if result.valid else "issues")
        issues = [*result.errors, *result.warnings]
        payload: dict[str, Any] = {
            "ir": json.loads(rule.model_dump_json()),
            "ir_hash": rule_hash,
            "issues": [i.to_dict() for i in issues[:MAX_RETURNED_ISSUES]],
            "issues_total": len(issues),
            "blocks_arming": result.blocks_arming,
        }
        other = body.get("counterpart_model")
        if other is not None:
            if not isinstance(other, dict):
                return _problem(400, "Bad request", "'counterpart_model' must be an object")
            other_fn = compile_graph if editor == "form" else compile_form
            try:
                diff, differ = await run(_round_trip, rule, other_fn, other, ruleId)
            except (RuleCompileError, IrValueError) as exc:
                err = _counted(exc)
                await _notify_divergence(editor, err.total)
                return _invalid(err)
            if differ:  # never auto-reconcile: report only, the caller aborts the switch
                await _notify_divergence(editor, differ)
            payload["round_trip"] = {"match": not differ, "diff": diff, "diff_total": differ}
        return JSONResponse(payload)

    @router.get("/schemas/rule-ir.json")
    async def get_rule_ir_schema(request: Request) -> Response:
        _, denied = await _authorize(request)
        if denied is not None:
            return denied
        return JSONResponse(to_json_schema(), headers={"Cache-Control": _CACHE})

    return router


__all__ = ["CheckWorker", "make_rules_router"]
