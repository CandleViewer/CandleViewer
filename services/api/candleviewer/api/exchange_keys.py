"""The key routes (E27-T03, #836; #897 and #898 extend them): `createApiKey`, `testApiKey`.

The path-gated `DANGEROUS_ROUTES` guard asks for the `keys` step-up first (SR-025), FastAPI checks
the closed body (the shared `422`, no value echoed); then the session (401), `keys:manage` (C-12.4,
`rbac.denied` audited: 403), the required `Idempotency-Key` (400) and the import, which audits.
The key binds only after those admission checks (#2304). Its fingerprint holds the path, the label,
`read_only`, `expected_uid` and `api_key` as an HMAC under a per-process key, never `api_secret`
(SR-E27-20). A `201`, `404`, `409` or `422` is kept for replay; a `403`, `502` or `503` never is,
nor a `409` that clears by itself (an import of the account still running, as E42-T05's), so its
re-send is a first submission. The fake backend has no import flow: `503 store_unavailable`. An
import runs to its end in a task of its own (`key_import_wiring.KeyImports`, which the lifespan
drains), its answer kept as above, so a cancelled request never stops it between M2's store and
the promotion. No frame here holds the pasted key in clear.

`testApiKey` (slice 2b6) takes no step-up (04 §7.2.2 row 44) and no idempotency key: the session,
then `keys:read` on the account (`granted_accounts`, a refusal audited as `rbac.denied` and always
a 403: a test never answers on an audit record), then `accounts.key_test`, which reads, throttles,
probes and has the self-check enforce the verdict (decision 11). Its read refused by the store's
live-owner gate (SR-051) is audited and answered the same way. Every failure the exchange gives
is a `200` with `passed: false`; a test that probed nothing is its problem. The fake backend has
no test: `503 store_unavailable`.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import inspect
import json
import os
import uuid
from collections.abc import Coroutine
from typing import Annotated, Any, Final, Protocol

import structlog
from fastapi import APIRouter, Path, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict

from candleviewer.accounts.errors import AccountScopeDeniedError, AccountsError
from candleviewer.accounts.key_age import KeyRotationPolicy
from candleviewer.accounts.key_import import (
    Importer,
    KeyImport,
    KeyImported,
    KeyImportFailed,
    KeyImportRequest,
    problem_code,
)
from candleviewer.accounts.key_test import KeyTest, KeyTested, KeyTestRefused
from candleviewer.accounts.verification import Rule, VerificationResult
from candleviewer.api._generated import openapi_models as api
from candleviewer.api.csrf import source_ip
from candleviewer.api.idempotency import IdempotencyCache, StoredResponse
from candleviewer.api.users import SnapshotResolver
from candleviewer.audit.errors import AuditError
from candleviewer.auth.generated_permissions import Permission, Scope
from candleviewer.auth.metrics import authz_denied_total, normalise_permission
from candleviewer.auth.scopes import ForbiddenError, PrincipalSnapshot, enforce
from candleviewer.observability.context import current_request_id
from candleviewer.observability.secret_type import Secret
from candleviewer.ws._generated.error_codes import ERROR_META, ErrorCode

_RETRY_AFTER_S: Final = 5
_STATUS: Final = {
    "validation_failed": 422, "conflict": 409, "not_found": 404, "forbidden": 403,
    "kek_unavailable": 403, "exchange_error": 502, "exchange_unavailable": 503,
    "store_unavailable": 503, "audit_unavailable": 503, "not_implemented": 501,
    "unauthenticated": 401, "idempotency_key_reuse": 409, "idempotency_in_flight": 409,
    "rate_limited": 429,
}  # fmt: skip
#: The answers kept for replay; nothing else is (`createApiKey`, Other statuses).
_REPLAYED: Final = frozenset({201, 404, 409, 422})
#: The stored key's metadata `ApiKey` shows as stored (`ApiKeyMetadata`).
_SHOWN: Final = {
    "id", "exchange_account_id", "label", "status", "read_only", "expires_at", "created_at",
}  # fmt: skip
#: The two rules of the permission gate (step 2): the checks after it never ran.
_GATE: Final = frozenset({Rule.WITHDRAW_PERMISSION, Rule.PERMISSION_NOT_ALLOWED})
#: `rbac.denied`'s reason when the store's live-owner gate refuses a test (`enforce`'s shape).
_NOT_OWNER: Final = f"not_owner:{Permission.KEYS_READ.value}:{Scope.GRANTED_ACCOUNTS.value}"


class _Emitter(Protocol):
    async def emit(self, action: str, **kwargs: Any) -> None: ...


class _Imports(Protocol):
    """`key_import_wiring.KeyImports`: the flow, and the task each import runs to its end in."""

    @property
    def flow(self) -> KeyImport: ...

    def run(self, work: Coroutine[Any, Any, Response]) -> asyncio.Task[Response]: ...


class _OnAccount:
    """`enforce` names no object: a refused import's `rbac.denied` names its account (C-2.9)."""

    def __init__(self, audit: _Emitter, account_id: uuid.UUID) -> None:
        self._audit, self._account = audit, str(account_id)

    async def emit(self, action: str, **kwargs: Any) -> None:
        named = {"object_kind": "exchange_account", "object_id": self._account}
        await self._audit.emit(action, **kwargs | named)


def _problem(
    code: str, detail: str, *, status: int | None = None, retry_s: int | None = None, **extra: Any
) -> JSONResponse:
    """A problem of a registered code (`x-error-codes`); a `503` or a throttled test says when to
    retry."""
    status, headers = status or _STATUS[code], {}
    body = {"type": f"https://candleviewer.local/errors/{code}", "status": status, "code": code}
    body |= {"title": ERROR_META[ErrorCode(code)].title, "detail": detail, **extra}
    if (retry_s := retry_s or (_RETRY_AFTER_S if status == 503 else None)) is not None:
        body["retry_after_seconds"], headers["Retry-After"] = retry_s, str(retry_s)
    return JSONResponse(body, status, headers, media_type="application/problem+json")


def verification(result: VerificationResult, egress_ip: str | None) -> dict[str, Any]:
    """`KeyVerification`, leaving out the fields of a check that did not run; for a key refused
    before its rights were read, `KeyVerificationNotRead`, never `withdraw_enabled` (C-2.8)."""
    if result.key_info_ret_code != 0:
        return {"passed": False, "egress_ip": egress_ip}
    shown: dict[str, Any] = {
        "passed": result.passed, "uid": result.uid, "uta": result.uta,
        "read_only": result.read_only, "withdraw_enabled": result.withdraw_enabled,
        "permissions": {g: list(r[:32]) for g, r in list(result.permissions.items())[:32]},
        "ip_whitelist": list(result.ip_whitelist[:20]), "egress_ip": egress_ip,
        "warnings": [w.value for w in result.warnings],
    }  # fmt: skip
    if not (result.failures and result.failures[0].rule in _GATE):
        shown["ip_whitelist_matches_egress"] = result.ip_whitelist_matches_egress
    if result.probe_ret_code is not None:
        shown["probe_ret_code"] = result.probe_ret_code
    if result.clock_offset_ms is not None:
        shown["clock_offset_ms"] = result.clock_offset_ms
    return shown


def _created(done: KeyImported, egress_ip: str | None, rotation: KeyRotationPolicy) -> Any:
    """`ApiKeyWithVerification`: the stored key's metadata (the masked tail) and verification."""
    key, due = done.key, rotation.evaluate(done.key.created_at, done.key.status, now=done.at)
    meta = key.model_dump(mode="json", include=_SHOWN)
    meta |= {"key_id_masked": key.key_id_masked, "rotation_state": due.rotation_state}
    meta |= {"last_verified_at": key.permission_snapshot_at.isoformat()}
    meta["rotation_due_at"] = due.rotation_due_at and due.rotation_due_at.isoformat()
    return {"key": meta, "verification": verification(done.verification, egress_ip)}


def _refused(exc: AccountsError, egress_ip: str | None) -> JSONResponse:
    """A refused key's `422` carries its `verification`, a no-verdict its return code alone."""
    if not isinstance(exc, KeyImportFailed):  # the account store's own refusals
        return _problem(problem_code(exc), "The key was not imported.")
    extra: dict[str, Any] = {}
    if exc.errors:
        extra["errors"] = [{"field": f, "rule": r, "message": m} for f, r, m in exc.errors]
    if exc.result is not None:
        extra["verification"] = verification(exc.result, egress_ip)
    if exc.ret_code is not None:
        extra["exchange"] = {"ret_code": exc.ret_code}
    return _problem(exc.code, exc.detail, **extra)


class _TestBody(BaseModel):
    """`testApiKey`'s optional body: closed, `include_ws` true unless sent false."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    include_ws: bool = True


def _tested(done: KeyTested, egress_ip: str | None) -> dict[str, Any]:
    """`KeyTestResult`: no `verification` without a verdict (SR-E27-18), no `websocket` for a half
    that did not run."""
    rest, ws = done.rest, done.websocket
    shown: dict[str, Any] = {
        "passed": done.passed, "checked_at": done.checked_at.isoformat(),
        "rest": {"ok": rest.ok, "latency_ms": rest.latency_ms, "ret_code": rest.ret_code,
                 "error": rest.error},
    }  # fmt: skip
    if ws is not None:
        shown["websocket"] = {"ok": ws.ok, "latency_ms": ws.latency_ms, "error": ws.error}
    if done.verdict is not None:
        shown["verification"] = verification(done.verdict, egress_ip)
    return shown


def _untested(exc: AccountsError) -> JSONResponse:
    """A test that probed nothing; a missing account or key, or one of another environment or
    account, is the same `not_found` (no oracle)."""
    if isinstance(exc, KeyTestRefused):
        return _problem(exc.code, exc.detail, retry_s=exc.retry_after_s)
    return _problem(problem_code(exc), "The key was not tested.")


async def _not_owner(audit: _Emitter, actor: Importer, account_id: uuid.UUID) -> None:
    """`rbac.denied` for a caller the store's live-owner gate refused once `enforce` let it
    through (SR-051), with `enforce`'s fields and its reason's shape, naming the account.
    Counted before the record, as `enforce` counts (SR-125), so a lost record never hides it: a
    refusal whose record fails is still a 403, logged by actor, account and error class (C-12.6)."""
    authz_denied_total.labels(permission=normalise_permission(Permission.KEYS_READ)).inc()
    try:
        await _OnAccount(audit, account_id).emit(
            "rbac.denied", actor_label=str(actor.user_id), actor_user_id=actor.user_id,
            actor_ip=actor.ip, session_id=None, outcome="denied", severity="warning",
            reason=_NOT_OWNER, request_id=actor.request_id,
        )  # fmt: skip
    except (AuditError, RuntimeError) as exc:  # RuntimeError: the audit writer is not started
        log = structlog.get_logger(__name__)  # per call: a module logger pins a stale chain (#2008)
        ids = {"actor_user_id": str(actor.user_id), "account_id": str(account_id)}
        log.warning("key_test_denial_unaudited", **ids, error=type(exc).__name__)


def _actor(principal: PrincipalSnapshot, request: Request) -> Importer:
    """The acting Owner, as the audit records name them (SR-E27-09)."""
    rid, role = current_request_id(), ",".join(sorted(principal.roles))
    request_id = uuid.UUID(rid) if rid else None
    return Importer(principal.user_id, role, source_ip(request.scope), request_id)


def make_exchange_keys_router(
    imports: _Imports | None, audit: _Emitter, resolver: SnapshotResolver | None, *,
    egress_ip: str | None, rotation: KeyRotationPolicy, replays: IdempotencyCache | None = None,
    tests: KeyTest | None = None,
) -> APIRouter:  # fmt: skip
    """The key routes. `resolver=None` (no identity wired): 501 for every call."""
    router, running = APIRouter(tags=["exchange-accounts"]), set[tuple[str, str]]()
    replays, mac_key = replays if replays is not None else IdempotencyCache(), os.urandom(32)

    async def answer(
        flow: KeyImport, wanted: KeyImportRequest, actor: Importer, held: tuple[str, str], fp: str
    ) -> Response:
        """The import and its answer, kept for replay as the contract says (module docstring)."""
        kept = True
        try:
            out = JSONResponse(_created(await flow.run(wanted, actor), egress_ip, rotation), 201)
        except AccountsError as exc:
            out = _refused(exc, egress_ip)
            kept = not (isinstance(exc, KeyImportFailed) and exc.transient)
        finally:
            running.discard(held)
        if kept and out.status_code in _REPLAYED:
            replays.put(*held, StoredResponse(fp, out.status_code, bytes(out.body), None))
        return out

    @router.post("/exchange-accounts/{accountId}/keys", status_code=201)  # nosem: audit-write-required,no-raw-account-id reason=audited-in-accounts.key_import-api_key.import-write-ahead-and-OwnerScope-store-gate-#836 owner=@CandleViewer/security review=2027-03-25  # noqa: E501 -- suppression metadata must stay on the matched line  # fmt: skip
    async def create_api_key(
        request: Request,
        account_id: Annotated[uuid.UUID, Path(alias="accountId")],
        body: api.CreateApiKeyRequest,
    ) -> Response:
        if resolver is None:
            return _problem("not_implemented", "No principal resolver is wired.")
        got = resolver.resolve(request)
        if (principal := await got if inspect.isawaitable(got) else got) is None:
            return _problem("unauthenticated", "No verified session for this request.")
        actor = _actor(principal, request)
        try:
            await enforce(
                principal, Permission.KEYS_MANAGE, scope=Scope.NONE,
                emitter=_OnAccount(audit, account_id), actor_ip=actor.ip,
                request_id=actor.request_id,
            )  # fmt: skip
        except ForbiddenError:
            need = ["keys:manage"]
            return _problem("forbidden", "Requires keys:manage.", required_permissions=need)
        except (AuditError, RuntimeError):  # RuntimeError: the audit writer is not started
            return _problem("audit_unavailable", "The refusal could not be audited.")
        try:
            once = f"createApiKey:{uuid.UUID(request.headers.get('idempotency-key', ''))}"
        except ValueError:
            return _problem("validation_failed", "Send an Idempotency-Key (UUID).", status=400)
        if imports is None:
            return _problem("store_unavailable", "Key import is not available on this backend.")
        owner = str(principal.user_id)  # the pasted pair is never a local in clear (C-12.6)
        tag = hmac.new(mac_key, body.api_key.get_secret_value().encode(), "sha256").hexdigest()
        shown = [request.url.path, body.label, body.read_only, body.expected_uid, tag]
        digest = hashlib.sha256(json.dumps(shown).encode()).hexdigest()
        if (hit := replays.get(owner, once)) is not None:
            if hit.digest != digest:
                return _problem("idempotency_key_reuse", "The key was used for another request.")
            media = "application/json" if hit.status < 400 else "application/problem+json"
            replayed = {"Idempotency-Replayed": "true"}
            return Response(hit.body, hit.status, replayed, media_type=media)
        if (owner, once) in running:
            return _problem("idempotency_in_flight", "A request with this key is being processed.")
        wanted = KeyImportRequest(
            account_id=account_id,
            api_key=Secret(body.api_key.get_secret_value()),
            api_secret=Secret(body.api_secret.get_secret_value()),
            label=body.label,
            read_only=bool(body.read_only),
            expected_uid=body.expected_uid,
        )
        running.add((owner, once))
        work = imports.run(answer(imports.flow, wanted, actor, (owner, once), digest))
        return await asyncio.shield(work)

    @router.post("/exchange-accounts/{accountId}/keys/{keyId}/test")  # nosem: audit-write-required,no-raw-account-id reason=audited-in-accounts.selfcheck-account.tested-write-ahead-and-enforce-granted_accounts-plus-OwnerScope-store-gate-#836 owner=@CandleViewer/security review=2027-03-25  # noqa: E501 -- suppression metadata must stay on the matched line  # fmt: skip
    async def test_api_key(
        request: Request,
        account_id: Annotated[uuid.UUID, Path(alias="accountId")],
        key_id: Annotated[uuid.UUID, Path(alias="keyId")],
        body: _TestBody | None = None,
    ) -> Response:
        if resolver is None:
            return _problem("not_implemented", "No principal resolver is wired.")
        got = resolver.resolve(request)
        if (principal := await got if inspect.isawaitable(got) else got) is None:
            return _problem("unauthenticated", "No verified session for this request.")
        actor = _actor(principal, request)
        try:
            await enforce(
                principal, Permission.KEYS_READ, scope=Scope.GRANTED_ACCOUNTS,
                exchange_account_id=account_id, emitter=_OnAccount(audit, account_id),
                actor_ip=actor.ip, request_id=actor.request_id,
            )  # fmt: skip
        except (ForbiddenError, AuditError, RuntimeError):  # an unaudited refusal still refuses
            need = ["keys:read"]
            return _problem("forbidden", "Requires keys:read.", required_permissions=need)
        if tests is None:
            return _problem("store_unavailable", "Key tests are not available on this backend.")
        include_ws = body is None or body.include_ws
        try:
            done = await tests.run(account_id, key_id, actor, include_ws=include_ws)
        except AccountScopeDeniedError as exc:  # SR-051: the store's live-owner gate refused
            await _not_owner(audit, actor, account_id)
            return _untested(exc)
        except AccountsError as exc:
            return _untested(exc)
        return JSONResponse(_tested(done, egress_ip))

    return router
