"""The key routes (E27-T03, #836; #897 and #898 extend them): `createApiKey`, `testApiKey`.

FastAPI checks the closed body (the shared `422`, no value echoed); then the session (401),
`keys:manage` (C-12.4, `rbac.denied` audited: 403), the required `Idempotency-Key` (400), the
account the import names (`KeyImport.admit`: `404`, or `422` for another UID, recorded as the
import's are), and only then the `keys` step-up (SR-025; `HANDLER_GATED_ROUTES`, #2304 slice 3b),
whose challenge names the account and the key's kind, never key material or the key's label. Then
the replay (a kept answer, or `409 idempotency_key_reuse` for another request; after the step-up, so
a session holding no live window never reads one back), the in-flight check and the import, which
audits. The key binds only after those admission checks (22, Binding point), so a refusal before the
step-up is never kept. Its fingerprint holds the path, the label, `read_only`, `expected_uid` and
`api_key` as an HMAC under a per-process key, never `api_secret` (SR-E27-20). The import's `201`,
`404`, `409` or `422` is kept for replay; a `403`, `502` or `503` never is, nor a `409` that clears
by itself (an import of the account still running, as E42-T05's), so its re-send is a first
submission. The fake backend has no import flow: `503 store_unavailable`. An import runs to its end
in a task of its own (`key_import_wiring.KeyImports`, which the lifespan drains), its answer kept as
above, so a cancelled request never stops it between M2's store and the promotion. No frame here
holds the pasted key in clear.

`revokeApiKey` (E27-S04 B3d, #898) revokes a key locally (CandleViewer never deletes it at the
exchange): the session, `keys:manage` (scope none, the Owner's alone; a 403 audited naming the
account, `503` when that record cannot be written), the store (503 on the fake backend), the `422`
of a choice outside the enum (FastAPI's, before anything), one byte-equal `404` for a key absent,
of another account, or of an account absent, deleted or of another environment; then the step-up: a
`flatten_first` spends a fresh no-grace `accounts` code bound to the method and the raw target with
its query, even when it turns out a no-op, and any other revoke a live `keys` window, both
challenges restating the key and its account. Under the account's lock (`AccountLocks`, the
delete's too) the key is read again (gone: `404`, the grant spent). A key already `revoked` is a
repeat: no ahead record and no destroy, the pending effects completed and the close awaited again.
A first revoke of the last signable key reads and gates the exposure (each `409` recorded denied
ahead of its answer, the grant spent); another key's `flatten_first` is a recorded no-op. Then
`api_key.revoke` is written ahead, and `accounts.key_revoke` destroys the key through M2, holds the
standing and, for the last signable key, revokes the account's subscriptions and disarms its
rules, then closes its private streams within 2 s. An overrun is `503 exchange_unavailable`, with
no completion record and never kept for replay; the retry completes it. Otherwise the completion
record `api_key.revoked` is written keyed by the key's id, so a revoke has exactly one whatever
crashes or retries came between (R7), and the answer is `204`. `204`s and the exposure `409`s are
kept for replay for 24 h, under the caller's key and the fingerprint of the method and raw target.

`testApiKey` (slice 2b6) takes no step-up (04 §7.2.2 row 44) and no idempotency key: the session,
then `keys:read` on the account (`granted_accounts`, a refusal audited as `rbac.denied` and always
a 403: a test never answers on an audit record), then `accounts.key_test`, which reads, throttles,
probes and has the self-check enforce the verdict (decision 11). Its read refused by the store's
live-owner gate (SR-051) is audited and answered the same way. Every failure the exchange gives
is a `200` with `passed: false`; a test that probed nothing is its problem. The fake backend has
no test: `503 store_unavailable`. A test runs in the request's task: a stop cancelling it past the
latch may skip the disarm (the latch holds order entry off; the boot pass re-derives the verdict).
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import inspect
import json
import os
import uuid
from collections.abc import Callable, Coroutine
from typing import Annotated, Any, Final, Literal, Protocol, runtime_checkable

import structlog
from fastapi import APIRouter, Path, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict

from candleviewer.accounts.consequences import AccountConsequences, ConsequenceRead
from candleviewer.accounts.errors import (
    AccountNotFoundError,
    AccountScopeDeniedError,
    AccountsError,
    KeyDestroyFailedError,
)
from candleviewer.accounts.exposure import ExposureFailed
from candleviewer.accounts.exposure_gate import Proceed, Refuse, gate
from candleviewer.accounts.flatten import Flattener, NoFlatten
from candleviewer.accounts.key_age import KeyRotationPolicy
from candleviewer.accounts.key_import import (
    Importer,
    KeyImport,
    KeyImported,
    KeyImportFailed,
    KeyImportRequest,
    problem_code,
)
from candleviewer.accounts.key_revoke import Completion, KeyRevoke, completion, last_signable
from candleviewer.accounts.key_test import KeyTest, KeyTested, KeyTestRefused
from candleviewer.accounts.models import ApiKeyMetadata, ExchangeAccount, KeyStatus
from candleviewer.accounts.repository import AccountsRepository
from candleviewer.accounts.verification import Rule, VerificationResult
from candleviewer.api._generated import openapi_models as api
from candleviewer.api.csrf import source_ip
from candleviewer.api.exchange_accounts import consequence_document, exposure_problem
from candleviewer.api.idempotency import IdempotencyCache, StoredResponse, idempotency_key
from candleviewer.api.refusal_session import NamesSession, SessionsLike
from candleviewer.api.step_up import (
    BoundRequestElevation,
    RequestElevation,
    SpentGrant,
    demand_bound_elevation,
    demand_elevation,
)
from candleviewer.api.step_up_challenge import (
    ChallengeText,
    account_reference,
    import_key_text,
    raw_request_target,
    request_fingerprint,
)
from candleviewer.api.users import SnapshotResolver
from candleviewer.audit.errors import AuditError
from candleviewer.auth.generated_permissions import Permission, Scope
from candleviewer.auth.metrics import count_authz_denial
from candleviewer.auth.scopes import ForbiddenError, PrincipalSnapshot, account_scope, enforce
from candleviewer.exchange.base.errors import PrivateStreamCloseOverran
from candleviewer.observability.context import current_request_id
from candleviewer.observability.secret_type import Secret
from candleviewer.storage.errors import StorageError
from candleviewer.storage.repositories.accounts import OwnerScope
from candleviewer.ws._generated.error_codes import ERROR_META, ErrorCode

_RETRY_AFTER_S: Final = 5
_STATUS: Final = {
    "validation_failed": 422, "conflict": 409, "not_found": 404, "forbidden": 403,
    "kek_unavailable": 403, "exchange_error": 502, "exchange_unavailable": 503,
    "store_unavailable": 503, "audit_unavailable": 503, "not_implemented": 501,
    "unauthenticated": 401, "idempotency_key_reuse": 409, "idempotency_in_flight": 409,
    "rate_limited": 429, "open_exposure": 409, "exposure_unknown": 409,
}  # fmt: skip
#: The answers kept for replay; nothing else is (`createApiKey`, Other statuses).
_REPLAYED: Final = frozenset({201, 404, 409, 422})
#: The stored key's metadata `ApiKey` shows as stored (`ApiKeyMetadata`).
_SHOWN: Final = {
    "id", "exchange_account_id", "label", "status", "read_only", "expires_at", "created_at",
}  # fmt: skip
#: The two rules of the permission gate (step 2): the checks after it never ran.
_GATE: Final = frozenset({Rule.WITHDRAW_PERMISSION, Rule.PERMISSION_NOT_ALLOWED})
#: A record not written: the writer refused it, has not started (`RuntimeError`), or timed out.
_UNWRITTEN: Final = (AuditError, RuntimeError, TimeoutError)
_NO_KEY: Final = "No such API key."  # one text for absent, foreign and another account's
#: `rbac.denied`'s reason when the store's live-owner gate refuses a test (`enforce`'s shape).
_NOT_OWNER: Final = f"not_owner:{Permission.KEYS_READ.value}:{Scope.GRANTED_ACCOUNTS.value}"


class _Emitter(Protocol):
    async def emit(self, action: str, **kwargs: Any) -> None: ...


@runtime_checkable
class _KeyedEmitter(_Emitter, Protocol):
    """The writer's keyed write too (`AuditWriter.emit_keyed`): `revokeApiKey`'s completion."""

    async def emit_keyed(self, action: str, name: str, **kwargs: Any) -> None: ...


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
    """A problem of a registered code (`x-error-codes`); a `503` or a `429` says when to retry."""
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
    count_authz_denial(Permission.KEYS_READ, actor.role.split(","))
    try:
        await _OnAccount(audit, account_id).emit(
            "rbac.denied", actor_label=str(actor.user_id), actor_user_id=actor.user_id,
            actor_ip=actor.ip, outcome="denied", severity="warning",
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
    tests: KeyTest | None = None, auth: SessionsLike | None = None,
    elevation: RequestElevation | None = None, accounts: AccountsRepository | None = None,
    revoker: KeyRevoke | None = None, consequences: ConsequenceRead | None = None,
    bound: BoundRequestElevation | None = None, flattener: Flattener | None = None,
    environment: str | None = None, keyed: _KeyedEmitter | None = None,
    revocations: Callable[[str], None] | None = None,
) -> APIRouter:  # fmt: skip
    """The key routes. `resolver=None` (no identity wired): 501 for every call. A refusal's
    `rbac.denied` names the caller's session, read through `auth` (#4174); `elevation` demands
    the import's and the revoke's `keys` step-up (None: 503, nothing imported or revoked). The
    revoke stores through `accounts` and `revoker` (None: 503) for the process's `environment`,
    reads the exposure through `consequences`, spends a `flatten_first`'s `accounts` code through
    `bound`, flattens with `flattener` (the null one until E29/E39's lands) and writes its keyed
    completion record through `keyed` (`audit`, when it is one)."""
    router, running = APIRouter(tags=["exchange-accounts"]), set[tuple[str, str]]()
    replays, mac_key = replays if replays is not None else IdempotencyCache(), os.urandom(32)
    #: `revokeApiKey`'s own replays: its `204`s and its exposure `409`s for 24 h, never a
    #: `502`/`503` (22 `OpenExposure`, ruling R5).
    revokes = IdempotencyCache()
    flatten: Flattener = NoFlatten() if flattener is None else flattener
    completer = keyed if keyed is not None else _as_keyed(audit)

    async def answer(
        flow: KeyImport, wanted: KeyImportRequest, actor: Importer, held: tuple[str, str], fp: str
    ) -> Response:
        """The import and its answer, kept for replay as the contract says (module docstring)."""
        try:
            out = JSONResponse(_created(await flow.run(wanted, actor), egress_ip, rotation), 201)
        except AccountsError as exc:
            return keep(held, fp, _refused(exc, egress_ip), exc)
        finally:
            running.discard(held)
        return keep(held, fp, out, None)

    def keep(
        held: tuple[str, str], fp: str, out: JSONResponse, exc: AccountsError | None
    ) -> JSONResponse:
        """`out`, kept for replay unless it is transient or of a status never kept."""
        transient = isinstance(exc, KeyImportFailed) and exc.transient
        if not transient and out.status_code in _REPLAYED:
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
                emitter=_OnAccount(NamesSession(audit, auth, request), account_id),
                actor_ip=actor.ip, request_id=actor.request_id,
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
        wanted = KeyImportRequest(
            account_id=account_id,
            api_key=Secret(body.api_key.get_secret_value()),
            api_secret=Secret(body.api_secret.get_secret_value()),
            label=body.label,
            read_only=bool(body.read_only),
            expected_uid=body.expected_uid,
        )
        try:  # the account, read and refused as the import would, before the step-up (#2304)
            account = await imports.flow.admit(wanted, actor)
        except AccountsError as exc:  # before the step-up: never kept (22, Binding point)
            return _refused(exc, egress_ip)
        named = account_reference(account.label, account.env.value, account.exchange_uid)
        restated = import_key_text(named, read_only=wanted.read_only)
        if (refused := await demand_elevation(elevation, request, restated)) is not None:
            return refused
        # The replay after the step-up (#2304 review): a kept answer is read back only by a
        # session the gate admits, never one holding no live `keys` window.
        if (hit := replays.get(owner, once)) is not None:
            if hit.digest != digest:
                return _problem("idempotency_key_reuse", "The key was used for another request.")
            media = "application/json" if hit.status < 400 else "application/problem+json"
            replayed = {"Idempotency-Replayed": "true"}
            return Response(hit.body, hit.status, replayed, media_type=media)
        if (owner, once) in running:
            return _problem("idempotency_in_flight", "A request with this key is being processed.")
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
                exchange_account_id=account_id,
                emitter=_OnAccount(NamesSession(audit, auth, request), account_id),
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
            await _not_owner(NamesSession(audit, auth, request), actor, account_id)
            return _untested(exc)
        except AccountsError as exc:
            return _untested(exc)
        return JSONResponse(_tested(done, egress_ip))

    def kept(who: str, key: str | None, digest: str, out: Response) -> Response:
        """`out` kept for replay under the caller's key: a `204` or an exposure `409` only."""
        if key is not None:
            revokes.put(who, key, StoredResponse(digest, out.status_code, bytes(out.body), None))
        return out

    def replayed(hit: StoredResponse, digest: str) -> Response:
        if hit.digest != digest:
            return _problem("idempotency_key_reuse", "The key was used for another request.")
        if hit.status == 204:
            return Response(status_code=204, headers={"Idempotency-Replayed": "true"})
        return Response(hit.body, hit.status, {"Idempotency-Replayed": "true"},
                        media_type="application/problem+json")  # fmt: skip

    def unavailable(exc: Exception) -> Response:
        """An outage, logged by class alone; anything else is a defect, raised."""
        if not isinstance(exc, AccountsError | StorageError):
            raise exc
        log = structlog.get_logger(__name__)  # per call: a module logger pins a stale chain (#2008)
        log.warning("key_revoke_store_unavailable", error=type(exc).__name__)
        return _problem("store_unavailable", "The account store is unavailable.")

    @router.delete("/exchange-accounts/{accountId}/keys/{keyId}", status_code=204)  # nosem: no-raw-account-id reason=enforce-keys:manage-scope-none-Owner-only-then-OwnerScope-live-owner-gate-in-SQL-SR-051-one-404-and-api_key.revoke-written-ahead-#898 owner=@CandleViewer/security review=2027-04-15  # noqa: E501 -- suppression metadata must stay on the matched line  # fmt: skip
    async def revoke_api_key(
        request: Request,
        account_id: Annotated[uuid.UUID, Path(alias="accountId")],
        key_id: Annotated[uuid.UUID, Path(alias="keyId")],
        open_exposure: Literal["leave_positions", "flatten_first"] | None = None,
    ) -> Response:
        if resolver is None:
            return _problem("not_implemented", "No principal resolver is wired.")
        got = resolver.resolve(request)
        if (principal := await got if inspect.isawaitable(got) else got) is None:
            return _problem("unauthenticated", "No verified session for this request.")
        actor, named = _actor(principal, request), NamesSession(audit, auth, request)
        try:  # 22: `keys:manage`, scope none (the Owner's alone); a refusal names the account
            await enforce(
                principal, Permission.KEYS_MANAGE, scope=Scope.NONE,
                emitter=_OnAccount(named, account_id), actor_ip=actor.ip,
                request_id=actor.request_id,
            )  # fmt: skip
        except ForbiddenError:
            need = ["keys:manage"]
            return _problem("forbidden", "Requires keys:manage.", required_permissions=need)
        except (AuditError, RuntimeError):  # RuntimeError: the audit writer is not started
            return _problem("audit_unavailable", "The refusal could not be audited.")
        if accounts is None or revoker is None or consequences is None or completer is None:
            return _problem("store_unavailable", "Key revoke is not available on this backend.")
        try:
            once = idempotency_key(request, "revokeApiKey")
        except ValueError:
            msg = "The Idempotency-Key is not a UUID."
            entry = {"field": "Idempotency-Key", "rule": "uuid", "message": msg}
            return _problem("validation_failed", "The request was refused.", errors=[entry])
        owner, who, store = OwnerScope(principal.user_id), str(principal.user_id), accounts

        async def read() -> tuple[ExchangeAccount, ApiKeyMetadata] | Response:
            """The account and the key as stored now, or the answer that ends the request."""
            try:
                account = await store.get_account(owner, account_id)
                if account.env.value != environment:  # C-2.11: never served here
                    raise AccountNotFoundError("account")
                return account, await store.get_key(owner, account_id, key_id)
            except AccountNotFoundError:  # absent, deleted, another account's or environment's
                return _problem("not_found", _NO_KEY)
            except AccountScopeDeniedError:  # the store's live-owner gate (SR-051)
                await _revoke_not_owner(named, actor, account_id)
                need = ["keys:manage"]
                return _problem("forbidden", "Requires keys:manage.", required_permissions=need)
            except Exception as exc:  # mapped, or raised as a defect
                return unavailable(exc)

        if isinstance(found := await read(), Response):
            return found
        account, _key = found
        digest = request_fingerprint(request.method, raw_request_target(request), None)
        reference = account_reference(account.label, account.env.value, account.exchange_uid)
        tail = "" if open_exposure is None else f", open_exposure={open_exposure}"
        text = ChallengeText(f"Revoke key '{key_id}' of account {reference}{tail}")
        grant: dict[str, str] = {}
        if open_exposure == "flatten_first":  # moves money: a fresh `accounts` code, bound
            spent = await demand_bound_elevation(bound, request, digest, text)
            if not isinstance(spent, SpentGrant):
                return spent  # every refusal before it spent nothing (22)
            grant = {"challenge_id": str(spent.challenge_id)}
        elif (refused := await demand_elevation(elevation, request, text)) is not None:
            return refused
        if once is not None and (hit := revokes.get(who, once)) is not None:
            return replayed(hit, digest)  # read back only behind the gate
        rid = actor.request_id

        async def record(action: str, outcome: str, after: dict[str, Any], **kw: Any) -> None:
            await audit.emit(
                action, actor_label=who, actor_user_id=principal.user_id, actor_ip=actor.ip,
                object_kind="api_key", object_id=str(key_id), outcome=outcome,
                severity="warning", request_id=rid, env=account.env, after_state=after, **kw,
            )  # fmt: skip

        async def completed(payload: Completion, result: str) -> Response:
            """R7: the completion record, keyed by the key, then the `204`."""
            try:
                await completer.emit_keyed(
                    "api_key.revoked", str(key_id), actor_label=who,
                    actor_user_id=principal.user_id, actor_ip=actor.ip, object_kind="api_key",
                    object_id=str(key_id), outcome="success", severity="warning", request_id=rid,
                    env=account.env, after_state=payload.state(account_id),
                )  # fmt: skip
            except _UNWRITTEN:  # the revoke stands; the retry, a repeat, writes it
                return _problem("audit_unavailable", "The completion record could not be written.")
            if revocations is not None:
                revocations(result)
            return kept(who, once, digest, Response(status_code=204))

        def overran() -> Response:
            if revocations is not None:
                revocations("overran")
            log = structlog.get_logger(__name__)
            log.warning("key_revoke_close_overran", account_id=str(account_id))
            detail = "The key is revoked; its private streams are still closing. Retry."
            return _problem("exchange_unavailable", detail)

        role = actor.role
        async with revoker.locks.hold(account_id):  # one revoke or delete of the account at once
            if isinstance(found := await read(), Response):
                return found  # the grant stays spent
            account, stored = found
            try:
                keys = await store.list_keys(owner, account_id)
            except Exception as exc:  # mapped, or raised as a defect
                return unavailable(exc)
            if stored.status is KeyStatus.REVOKED:  # a repeat, decided after the gate
                try:
                    payload = await revoker.complete(
                        account_id, key_id, keys=keys, choice=open_exposure,
                        actor=principal.user_id, role=role,
                    )  # fmt: skip
                except PrivateStreamCloseOverran:
                    return overran()
                return await completed(payload, "completed")
            last = last_signable(keys, key_id)
            decision: Proceed | Refuse = Proceed(False, ())
            read_out: Any = None
            if last:  # the account's exposure decides (22 `OpenExposure`)
                try:
                    read_out = await consequences.read(account_scope(principal), owner, account_id)
                except AccountNotFoundError:
                    return _problem("not_found", _NO_KEY)
                except Exception as exc:  # mapped, or raised as a defect
                    return unavailable(exc)
                decision = await gate(
                    "revoke", read_out, open_exposure, last_signable=True, flattener=flatten,
                    actor=principal.user_id,
                )  # fmt: skip
            intent: dict[str, Any] = {
                "exchange_account_id": str(account_id), "open_exposure": open_exposure,
                "last_signable": last, **grant,
            }  # fmt: skip
            if isinstance(decision, Refuse):
                if isinstance(read_out, ExposureFailed):  # retryable: no record, never kept
                    return exposure_problem(read_out)
                why = {"why": decision.why} if decision.why else {}
                try:  # a refusal after the gate, written ahead of its answer (R4)
                    await record("api_key.revoke", "denied", intent | why, reason=decision.kind)
                except _UNWRITTEN:
                    return _problem("audit_unavailable", "The refusal could not be audited.")
                if not isinstance(read_out, AccountConsequences):  # `exposure_unknown`
                    return kept(who, once, digest, exposure_problem(read_out))
                out = _problem(
                    "open_exposure", _not_flat(read_out, decision.why), status=409,
                    consequences=consequence_document(read_out),
                )  # fmt: skip
                return kept(who, once, digest, out)
            if decision.lifted:  # 22 Dead: the code, each signable key's error, the lift
                errors = [{"key_id": str(k), "error": e} for k, e in decision.key_errors]
                intent |= {"code": "exposure_unknown", "key_errors": errors, "lifted": True}
            try:  # C-2.9: the decided intent, ahead of the destroy
                await record("api_key.revoke", "success", intent)
            except _UNWRITTEN:
                return _problem(
                    "audit_unavailable", "The audit record could not be written; nothing changed."
                )
            payload = completion(
                account_id, choice=open_exposure, last=last, flattened=decision.flattened
            )
            try:
                await revoker.revoke(
                    account_id, key_id, last=last, payload=payload, actor=principal.user_id,
                    role=role,
                )  # fmt: skip
            except PrivateStreamCloseOverran:
                return overran()
            except KeyDestroyFailedError:
                return _problem(
                    "store_unavailable", "The key could not be destroyed; nothing changed. Retry."
                )
            return await completed(payload, "revoked")

    return router


def _as_keyed(audit: _Emitter) -> _KeyedEmitter | None:
    """`audit` when it writes keyed records too (the app's writer), else `None`: the revoke then
    answers 503 rather than complete without its completion record."""
    return audit if isinstance(audit, _KeyedEmitter) else None


def _not_flat(read: AccountConsequences, why: str | None) -> str:
    """The `open_exposure` refusal's detail for the last signable key's revoke."""
    held = (
        f"{len(read.open_positions)} open position(s), {read.working_orders} working order(s) "
        f"and {read.running_algos} running algo(s)"
    )
    if why == "native_stop_missing":
        bare = sum(1 for p in read.open_positions if not p.native_stop_present)
        return (
            f"{bare} open position(s) without a native stop-loss, so "
            "open_exposure=leave_positions is refused; resend with open_exposure=flatten_first."
        )
    if why == "still_not_flat":
        return f"The account is still not flat: {held}; nothing was revoked."
    return f"{held}; resend with an open_exposure choice."


async def _revoke_not_owner(audit: _Emitter, actor: Importer, account_id: uuid.UUID) -> None:
    """`rbac.denied` for a caller the store's live-owner gate refused once `enforce` let it
    through (SR-051), in `enforce`'s reason shape for `keys:manage`, naming the account; counted
    first (SR-125), a record not written logged and the refusal standing."""
    count_authz_denial(Permission.KEYS_MANAGE, actor.role.split(","))
    try:
        await _OnAccount(audit, account_id).emit(
            "rbac.denied", actor_label=str(actor.user_id), actor_user_id=actor.user_id,
            actor_ip=actor.ip, outcome="denied", severity="warning",
            reason=f"not_owner:{Permission.KEYS_MANAGE.value}:{Scope.NONE.value}",
            request_id=actor.request_id,
        )  # fmt: skip
    except (AuditError, RuntimeError) as exc:  # RuntimeError: the audit writer is not started
        log = structlog.get_logger(__name__)
        log.warning("key_revoke_denial_unaudited", actor_user_id=str(actor.user_id),
                    error=type(exc).__name__)  # fmt: skip
