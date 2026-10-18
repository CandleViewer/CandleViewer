"""The key routes (E27-T03, #836; #897 and #898 extend them): `createApiKey`.

The path-gated `DANGEROUS_ROUTES` guard asks for the `keys` step-up first (SR-025), FastAPI checks
the closed body (the shared `422`, no value echoed); then the session (401), `keys:manage` (C-12.4,
`rbac.denied` audited: 403), the required `Idempotency-Key` (400) and the import, which audits.
The key binds only after those admission checks (#2304). Its fingerprint holds the path, the label,
`read_only`, `expected_uid` and `api_key` as an HMAC under a per-process key, never `api_secret`
(SR-E27-20). A `201`, `404`, `409` or `422` is kept for replay; a `403`, `502` or `503` never is, so
its re-send is a first submission. The fake backend has no import flow: `503 store_unavailable`.
An import runs in a task of its own to its end, its answer kept as above, so a cancelled request
never stops it between M2's store and the promotion. No frame here holds the pasted key in clear.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import inspect
import json
import os
import uuid
from typing import Annotated, Any, Final, Protocol

import structlog
from fastapi import APIRouter, Path, Request
from fastapi.responses import JSONResponse, Response

from candleviewer.accounts.errors import AccountsError
from candleviewer.accounts.key_age import KeyRotationPolicy
from candleviewer.accounts.key_import import (
    Importer,
    KeyImport,
    KeyImported,
    KeyImportFailed,
    KeyImportRequest,
    problem_code,
)
from candleviewer.accounts.verification import Rule, VerificationResult
from candleviewer.api._generated import openapi_models as api
from candleviewer.api.csrf import source_ip
from candleviewer.api.idempotency import IdempotencyCache, StoredResponse
from candleviewer.api.users import SnapshotResolver
from candleviewer.audit.errors import AuditError
from candleviewer.auth.generated_permissions import Permission, Scope
from candleviewer.auth.scopes import ForbiddenError, enforce
from candleviewer.observability.context import current_request_id, spawn
from candleviewer.observability.secret_type import Secret
from candleviewer.ws._generated.error_codes import ERROR_META, ErrorCode

_RETRY_AFTER_S: Final = 5
_STATUS: Final = {
    "validation_failed": 422, "conflict": 409, "not_found": 404, "forbidden": 403,
    "kek_unavailable": 403, "exchange_error": 502, "exchange_unavailable": 503,
    "store_unavailable": 503, "audit_unavailable": 503, "not_implemented": 501,
    "unauthenticated": 401, "idempotency_key_reuse": 409, "idempotency_in_flight": 409,
}  # fmt: skip
#: The answers kept for replay; nothing else is (`createApiKey`, Other statuses).
_REPLAYED: Final = frozenset({201, 404, 409, 422})
#: The stored key's metadata `ApiKey` shows as stored (`ApiKeyMetadata`).
_SHOWN: Final = {
    "id", "exchange_account_id", "label", "status", "read_only", "expires_at", "created_at",
}  # fmt: skip
#: The two rules of the permission gate (step 2): the checks after it never ran.
_GATE: Final = frozenset({Rule.WITHDRAW_PERMISSION, Rule.PERMISSION_NOT_ALLOWED})


class _Emitter(Protocol):
    async def emit(self, action: str, **kwargs: Any) -> None: ...


class _OnAccount:
    """`enforce` names no object: a refused import's `rbac.denied` names its account (C-2.9)."""

    def __init__(self, audit: _Emitter, account_id: uuid.UUID) -> None:
        self._audit, self._account = audit, str(account_id)

    async def emit(self, action: str, **kwargs: Any) -> None:
        named = {"object_kind": "exchange_account", "object_id": self._account}
        await self._audit.emit(action, **kwargs | named)


def _problem(code: str, detail: str, *, status: int | None = None, **extra: Any) -> JSONResponse:
    """A problem of a registered code (`x-error-codes`); a `503` says when to retry."""
    status, headers = status or _STATUS[code], {}
    body = {"type": f"https://candleviewer.local/errors/{code}", "status": status, "code": code}
    body |= {"title": ERROR_META[ErrorCode(code)].title, "detail": detail, **extra}
    if status == 503:
        body["retry_after_seconds"], headers["Retry-After"] = _RETRY_AFTER_S, str(_RETRY_AFTER_S)
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


def make_exchange_keys_router(
    imports: KeyImport | None, audit: _Emitter, resolver: SnapshotResolver | None, *,
    egress_ip: str | None, rotation: KeyRotationPolicy, replays: IdempotencyCache | None = None,
) -> APIRouter:  # fmt: skip
    """The key routes. `resolver=None` (no identity wired): 501 for every call."""
    router, running = APIRouter(tags=["exchange-accounts"]), set[tuple[str, str]]()
    replays, mac_key = replays if replays is not None else IdempotencyCache(), os.urandom(32)
    importing: set[asyncio.Task[Response]] = set()  # each import runs to its end, tracked here

    async def answer(
        flow: KeyImport, wanted: KeyImportRequest, actor: Importer, held: tuple[str, str], fp: str
    ) -> Response:
        """The import and its answer, kept for replay as the contract says."""
        try:
            out = JSONResponse(_created(await flow.run(wanted, actor), egress_ip, rotation), 201)
        except AccountsError as exc:
            out = _refused(exc, egress_ip)
        finally:
            running.discard(held)
        if out.status_code in _REPLAYED:
            replays.put(*held, StoredResponse(fp, out.status_code, bytes(out.body), None))
        return out

    def settled(task: asyncio.Task[Response]) -> None:
        """A raise is logged here too: once the request is gone, no one awaits the import."""
        importing.discard(task)
        if not task.cancelled() and (exc := task.exception()) is not None:
            structlog.get_logger(__name__).error("key_import_failed", error=type(exc).__name__)

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
        rid, role = current_request_id(), ",".join(sorted(principal.roles))
        request_id = uuid.UUID(rid) if rid else None
        actor = Importer(principal.user_id, role, source_ip(request.scope), request_id)
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
        work = spawn(answer(imports, wanted, actor, (owner, once), digest), name="create-api-key")
        importing.add(work)
        work.add_done_callback(settled)
        return await asyncio.shield(work)

    return router
