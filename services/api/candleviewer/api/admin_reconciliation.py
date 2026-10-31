"""`POST /admin/reconciliation/{accountId}` (`reconcileAccount`) and
`POST /admin/reconciliation/{accountId}/resolve` (`resolveReconciliation`), E29-T06 #914 (22, the
ruling of record's BQ-7; 24-internal-schemas.md Sec.8.5, Sec.15.5), on the audited admin router
(`admin.http`, `admin:write`, scope none): a caller without it is counted, recorded as a denied
`admin.area_entered` and refused 403 before anything is read. CSRF and the session state are the
middleware's.

Each handler then runs 22's order, and every answer it gives carries `Cache-Control: no-store`:

1. the request: the path id a UUID (FastAPI's 422), the `Idempotency-Key` a UUID and, on the
   resolve, the body against `ReconciliationResolveRequest`, read under `MAX_BODY_BYTES`: a 422
   `validation_failed` naming the field and the rule, never a value;
2. the resolve only: one fresh `accounts` code bound to this request (its method, raw target and
   validated body; `HANDLER_GATED_ROUTES`, no grace), its challenge naming the account by its id;
3. the 24 h record of the caller's first `202` or `200` under the key: the same request is that
   answer (`Idempotency-Replayed: true`), another request under the key `409
   idempotency_key_reuse`, the key's first call still running `409 idempotency_in_flight`;
4. the account, read in the Owner's scope (C-12.4): absent, deleted or of another environment is
   one `404` (C-2.11); no store, or one that fails, `503 store_unavailable`;
5. the OMS: none composed, or none composing reconciliation, `501 not_implemented`; one not ready
   `503 oms_not_ready` with `Retry-After`;
6. the account's job, on the order lane, where its lock is (`OnLaneReconciliation`): `409
   conflict` with rule `reconciliation_locked` (a locked job runs no pass) or `nothing_to_resolve`
   (neither locked nor waiting for the operator, or no job at all);
7. the record, written ahead on the serving loop before B19 is told (`oms.reconcile`, `stage`
   `requested` or `resolved`, the latter with the state it left, the reason and the spent
   grant's `challenge_id`): one that is not durable is `503 audit_unavailable`, and B19 is told
   nothing (C-2.9);
8. the answer, kept for 24 h under the key: `202 ReconciliationPass` (`joined` when a running
   pass answered, and no second one starts) or `200 ReconciliationResolved`, sent once B19 has
   recorded the decision, so the standing has cleared (BQ-5).

A refusal is never kept, so a retry is evaluated afresh. Logs and problems carry the account id,
the pass id and codes only, never the key, the reason or a fingerprint (C-12.6).
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from typing import Annotated, Any, Final, Protocol

import structlog
from fastapi import APIRouter, Path, Request
from fastapi.responses import JSONResponse, Response
from pydantic import ValidationError

from candleviewer.accounts.errors import AccountNotFoundError, AccountScopeDeniedError
from candleviewer.accounts.models import ExchangeAccount
from candleviewer.admin.http import PrincipalResolver, admin_router
from candleviewer.api._generated import openapi_models as api
from candleviewer.api.idempotency import IdempotencyCache, StoredResponse
from candleviewer.api.step_up import SpentGrant, StepUpAuth, StepUpEmitter, require_bound_elevation
from candleviewer.api.step_up_challenge import (
    ChallengeText,
    raw_request_target,
    request_fingerprint,
)
from candleviewer.audit.access import AuditPrincipal
from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.auth.generated_permissions import Permission
from candleviewer.domain.primitives import AccountId
from candleviewer.oms.errors import OmsNotReady, ReconciliationUnavailable
from candleviewer.oms.reconcile_job import JobLocked, NoSuchJob, NothingToResolve, PassTaken
from candleviewer.storage.repositories.accounts import OwnerScope
from candleviewer.ws._generated.error_codes import ERROR_META, ErrorCode

__all__ = [
    "MAX_BODY_BYTES",
    "MAX_IN_FLIGHT",
    "RECONCILE",
    "AccountReads",
    "ReconcileRuntime",
    "ReconciliationService",
    "make_admin_reconciliation_router",
]

#: The record both routes write ahead (24 Sec.15.5), registered in `audit/actions.py`.
RECONCILE: Final = "oms.reconcile"
#: The resolve's body is one reason of at most 280 characters: past this it is refused unread.
MAX_BODY_BYTES: Final = 2048
#: The keys a router holds in flight at once (C-2.18): past it a call is told to come back.
MAX_IN_FLIGHT: Final = 16
#: Each await of the routes' own, bounded (C-2.18): the account's read and the record's write.
STORE_READ_S: Final = 5.0
RECORD_WRITE_S: Final = 5.0
_RETRY_AFTER_S: Final = 5
_NO_STORE: Final = {"Cache-Control": "no-store"}
_PROBLEM: Final = "application/problem+json"
_STATUS: Final[dict[ErrorCode, int]] = {
    ErrorCode.FORBIDDEN: 403,
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.CONFLICT: 409,
    ErrorCode.IDEMPOTENCY_KEY_REUSE: 409,
    ErrorCode.IDEMPOTENCY_IN_FLIGHT: 409,
    ErrorCode.VALIDATION_FAILED: 422,
    ErrorCode.NOT_IMPLEMENTED: 501,
    ErrorCode.OMS_NOT_READY: 503,
    ErrorCode.STORE_UNAVAILABLE: 503,
    ErrorCode.AUDIT_UNAVAILABLE: 503,
}
#: A `409 conflict`'s message, by its rule (22).
_CONFLICTS: Final[dict[str, str]] = {
    "reconciliation_locked": (
        "The account's reconciliation is locked stale; no pass runs until it is resolved."
    ),
    "nothing_to_resolve": (
        "The account's reconciliation is neither locked stale nor waiting for the operator."
    ),
}


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


def _utc_now() -> datetime:
    return datetime.now(UTC)


class AccountReads(Protocol):
    """`AccountsRepository.get_account`: the account in the caller's scope, else
    `AccountNotFoundError` (absent or deleted), or `AccountScopeDeniedError` for a caller who
    holds no live owner role (SR-051)."""

    async def get_account(self, scope: OwnerScope, account_id: uuid.UUID) -> ExchangeAccount: ...


class ReconciliationService(Protocol):
    """`oms_wiring.OnLaneReconciliation`: each call on the order lane, its `write_ahead` run on
    the serving loop before B19 is told."""

    @property
    def wired(self) -> bool: ...

    async def reconcile_now(
        self,
        account: AccountId,
        *,
        write_ahead: Callable[[PassTaken], Coroutine[Any, Any, None]],
    ) -> PassTaken: ...

    async def resolve(
        self,
        account: AccountId,
        *,
        decided_by: str,
        write_ahead: Callable[[str], Coroutine[Any, Any, None]],
    ) -> str: ...


class ReconcileRuntime(Protocol):
    """`oms_wiring.OmsRuntime` as these routes read it: its readiness and the service."""

    @property
    def readiness(self) -> str: ...

    @property
    def reconciliation(self) -> ReconciliationService: ...


class _Unwritten(Exception):
    """The record written ahead is not durable: B19 was told nothing (`503 audit_unavailable`)."""


def _problem(
    code: ErrorCode, detail: str, *, retry_after: int = _RETRY_AFTER_S, **extra: Any
) -> JSONResponse:
    """An RFC 9457 problem with the catalogued title; a retryable code carries `Retry-After`."""
    status, meta = _STATUS[code], ERROR_META[code]
    body: dict[str, Any] = {"type": f"https://candleviewer.local/errors/{code.value}"}
    body |= {"title": meta.title, "status": status, "code": code.value, "detail": detail, **extra}
    headers = dict(_NO_STORE)
    if meta.retryable:
        body["retry_after_seconds"] = retry_after
        headers["Retry-After"] = str(retry_after)
    return JSONResponse(body, status, headers, media_type=_PROBLEM)


def _invalid(field: str, rule: str) -> JSONResponse:
    return _problem(ErrorCode.VALIDATION_FAILED, "The request is invalid.",
                    errors=[{"field": field, "rule": rule}])  # fmt: skip


def _conflict(rule: str) -> JSONResponse:
    message = _CONFLICTS[rule]
    return _problem(
        ErrorCode.CONFLICT, message, errors=[{"field": "", "rule": rule, "message": message}]
    )


def _key(request: Request) -> uuid.UUID | None:
    """The `Idempotency-Key`, a UUID (22 `IdempotencyKeyRequired`), else None."""
    try:
        return uuid.UUID(request.headers.get("idempotency-key", ""))
    except ValueError:
        return None


async def _reason(request: Request) -> str | JSONResponse:
    """The resolve's `reason`, the body read under `MAX_BODY_BYTES` and checked strictly against
    `ReconciliationResolveRequest`, or its `422`, naming no value and no unknown member."""
    raw = bytearray()
    async for chunk in request.stream():
        raw += chunk
        if len(raw) > MAX_BODY_BYTES:
            return _invalid("", "body_too_large")
    try:
        body = api.ReconciliationResolveRequest.model_validate_json(bytes(raw), strict=True)
    except ValidationError as exc:
        first = exc.errors()[0]
        field = "" if first["type"] == "extra_forbidden" else ".".join(map(str, first["loc"]))
        return _invalid(field, first["type"])
    return body.reason


def make_admin_reconciliation_router(
    accounts: AccountReads | None,
    runtime: Callable[[], ReconcileRuntime | None],
    *,
    environment: str,
    auth: StepUpAuth,
    resolver: PrincipalResolver | None,
    audit: StepUpEmitter,
    replays: IdempotencyCache | None = None,
    clock: Callable[[], datetime] = _utc_now,
) -> APIRouter:
    """The two routes (module docstring). `accounts` is the M13 store (None on the fake backend:
    `503`), `runtime` the OMS runtime, read per request (None: `501`), `environment` the
    process's (C-2.11), `auth` the step-up the resolve demands, and `audit` writes the guard's,
    the step-up's and the routes' records; `replays` is the 24 h record of first answers."""
    router = admin_router(Permission.ADMIN_WRITE, resolver=resolver, audit=audit)
    kept = IdempotencyCache() if replays is None else replays
    running: set[tuple[str, str]] = set()

    def replayed(held: tuple[str, str], digest: str) -> Response | None:
        """The key's first answer to this request, or `409 idempotency_key_reuse` for another."""
        hit = kept.get(*held)
        if hit is None:
            return None
        if hit.digest != digest:
            return _problem(
                ErrorCode.IDEMPOTENCY_KEY_REUSE, "The key was used for another request."
            )
        headers = {"Idempotency-Replayed": "true", **_NO_STORE}
        return Response(hit.body, hit.status, headers, media_type="application/json")

    def busy(held: tuple[str, str]) -> JSONResponse | None:
        """`409 idempotency_in_flight` while the key's first call runs, or the guard is full."""
        if held in running or len(running) >= MAX_IN_FLIGHT:
            detail = "A request with this key is still being processed."
            return _problem(ErrorCode.IDEMPOTENCY_IN_FLIGHT, detail, retry_after=1)
        return None

    def columns(
        who: AuditPrincipal, account: ExchangeAccount, after: dict[str, Any], severity: Severity
    ) -> dict[str, Any]:
        """An `oms.reconcile` record's columns: the Owner its actor, the account its object."""
        return {
            "actor_label": who.actor_name, "actor_user_id": who.actor_id, "actor_ip": who.ip,
            "session_id": who.session_id, "object_kind": "exchange_account",
            "object_id": str(account.id), "outcome": AuditOutcome.SUCCESS, "severity": severity,
            "reason": after["stage"], "after_state": after, "request_id": who.request_id,
            "env": account.env,
        }  # fmt: skip

    async def account_of(
        who: AuditPrincipal, account_id: uuid.UUID
    ) -> ExchangeAccount | JSONResponse:
        """The account in the Owner's scope and the process's environment, or its refusal."""
        if accounts is None:
            detail = "Accounts are not available on this backend."
            return _problem(ErrorCode.STORE_UNAVAILABLE, detail)
        try:
            async with asyncio.timeout(STORE_READ_S):
                account = await accounts.get_account(OwnerScope(who.actor_id), account_id)
        except AccountNotFoundError:
            return _problem(ErrorCode.NOT_FOUND, "No such account.")
        except AccountScopeDeniedError:  # the store's live-owner gate (SR-051)
            return await refused(who, account_id)
        except Exception as exc:  # down, slow or failing: retryable, logged by its class
            _log().warning("reconcile_route_account_unread", account_id=str(account_id),
                           error=type(exc).__name__)  # fmt: skip
            return _problem(ErrorCode.STORE_UNAVAILABLE, "The account could not be read.")
        if account.env.value != environment:  # C-2.11: never served by this process
            return _problem(ErrorCode.NOT_FOUND, "No such account.")
        return account

    async def refused(who: AuditPrincipal, account_id: uuid.UUID) -> JSONResponse:
        """A caller the store finds no live owner: `403`, its `rbac.denied` written first."""
        try:
            async with asyncio.timeout(RECORD_WRITE_S):
                await audit.emit(
                    "rbac.denied", actor_label=who.actor_name, actor_user_id=who.actor_id,
                    actor_ip=who.ip, session_id=who.session_id, object_kind="exchange_account",
                    object_id=str(account_id), outcome=AuditOutcome.DENIED,
                    severity=Severity.WARNING, reason="owner_only", request_id=who.request_id,
                )  # fmt: skip
        except Exception as exc:
            _log().error("reconcile_route_denial_unrecorded", error=type(exc).__name__)
            return _problem(ErrorCode.AUDIT_UNAVAILABLE, "The refusal could not be audited.")
        return _problem(ErrorCode.FORBIDDEN, "Only the Owner acts on an account's reconciliation.")

    def service_of() -> ReconciliationService | JSONResponse:
        """The OMS's reconciliation, composed and ready, or its `501` or `503`."""
        oms = runtime()
        if oms is None:
            return _problem(ErrorCode.NOT_IMPLEMENTED, "No OMS is composed on this backend.")
        not_ready = _problem(ErrorCode.OMS_NOT_READY, "The order service is not ready.")
        if oms.readiness != "ok":
            return not_ready
        try:
            service = oms.reconciliation
        except OmsNotReady:
            return not_ready
        if not service.wired:
            detail = "No reconciliation is composed on this backend."
            return _problem(ErrorCode.NOT_IMPLEMENTED, detail)
        return service

    def kept_answer(held: tuple[str, str], digest: str, out: JSONResponse) -> JSONResponse:
        kept.put(*held, StoredResponse(digest, out.status_code, bytes(out.body), None))
        return out

    @router.post("/reconciliation/{accountId}", status_code=202)
    async def reconcile_account(
        request: Request, account_id: Annotated[uuid.UUID, Path(alias="accountId")]
    ) -> Response:
        """`reconcileAccount` (module docstring)."""
        who: AuditPrincipal = request.state.admin_principal  # left there by the guard
        if (key := _key(request)) is None:
            return _invalid("Idempotency-Key", "uuid")
        digest = request_fingerprint(request.method, raw_request_target(request), None)
        held = (str(who.actor_id), f"reconcileAccount:{key}")
        if (answer := replayed(held, digest) or busy(held)) is not None:
            return answer
        running.add(held)
        try:
            found = await account_of(who, account_id)
            if isinstance(found, JSONResponse):
                return found
            account, service = found, service_of()
            if isinstance(service, JSONResponse):
                return service

            async def write_ahead(taken: PassTaken) -> None:
                """`stage: requested`, written ahead of the pass's send (24 Sec.15.5, C-2.9)."""
                after = {"stage": "requested", "trigger": "manual", "pass_id": taken.pass_id,
                         "joined": taken.joined}  # fmt: skip
                try:
                    async with asyncio.timeout(RECORD_WRITE_S):
                        await audit.emit(RECONCILE, **columns(who, account, after, Severity.INFO))
                except Exception as exc:
                    _log().error("reconcile_request_unrecorded", account_id=str(account.id),
                                 error=type(exc).__name__)  # fmt: skip
                    raise _Unwritten from None

            try:
                taken = await service.reconcile_now(AccountId(account.id), write_ahead=write_ahead)
            except _Unwritten:
                detail = "The request's record could not be written; no pass started."
                return _problem(ErrorCode.AUDIT_UNAVAILABLE, detail)
            except JobLocked:
                return _conflict("reconciliation_locked")
            except (OmsNotReady, ReconciliationUnavailable):
                detail = "The account's reconciliation job cannot run a pass yet."
                return _problem(ErrorCode.OMS_NOT_READY, detail)
            body = api.ReconciliationPass.model_validate(
                {"pass_id": taken.pass_id, "exchange_account_id": str(account.id),
                 "trigger": "manual", "joined": taken.joined}
            )  # fmt: skip
            _log().info("reconcile_route_requested", account_id=str(account.id),
                        pass_id=taken.pass_id, joined=taken.joined)  # fmt: skip
            out = JSONResponse(body.model_dump(mode="json"), 202, dict(_NO_STORE))
            return kept_answer(held, digest, out)
        finally:
            running.discard(held)

    @router.post("/reconciliation/{accountId}/resolve", status_code=200)
    async def resolve_reconciliation(
        request: Request, account_id: Annotated[uuid.UUID, Path(alias="accountId")]
    ) -> Response:
        """`resolveReconciliation` (module docstring): the operator's unlock, behind one fresh
        `accounts` code bound to this request, which the decision's record names."""
        who: AuditPrincipal = request.state.admin_principal  # left there by the guard
        if (key := _key(request)) is None:
            return _invalid("Idempotency-Key", "uuid")
        reason = await _reason(request)
        if isinstance(reason, JSONResponse):
            return reason
        body = {"reason": reason}
        digest = request_fingerprint(request.method, raw_request_target(request), body)
        spent = await require_bound_elevation(
            auth, who.session_id, "accounts", fingerprint=digest, emitter=audit,
            text=ChallengeText(f"Resolve the reconciliation of account {account_id}"),
        )  # fmt: skip
        if not isinstance(spent, SpentGrant):
            spent.headers.update(_NO_STORE)  # a challenge is an answer of this router too
            return spent  # nothing was spent, nothing kept (22)
        held = (str(who.actor_id), f"resolveReconciliation:{key}")
        if (answer := replayed(held, digest) or busy(held)) is not None:
            return answer
        running.add(held)
        try:
            found = await account_of(who, account_id)
            if isinstance(found, JSONResponse):
                return found
            account, service = found, service_of()
            if isinstance(service, JSONResponse):
                return service

            async def write_ahead(state: str) -> None:
                """`stage: resolved`, written ahead of `OPERATOR_RESOLVED` (24 Sec.15.5, C-2.9):
                the state it leaves, the reason and the spent grant's `challenge_id`."""
                after = {"stage": "resolved", "state": state, "reason": reason,
                         "challenge_id": str(spent.challenge_id)}  # fmt: skip
                try:
                    async with asyncio.timeout(RECORD_WRITE_S):
                        await audit.emit(
                            RECONCILE, **columns(who, account, after, Severity.WARNING)
                        )
                except Exception as exc:
                    _log().error("reconcile_decision_unrecorded", account_id=str(account.id),
                                 error=type(exc).__name__)  # fmt: skip
                    raise _Unwritten from None

            try:
                state = await service.resolve(
                    AccountId(account.id), decided_by=str(who.actor_id), write_ahead=write_ahead
                )
            except _Unwritten:
                detail = "The decision's record could not be written; nothing changed."
                return _problem(ErrorCode.AUDIT_UNAVAILABLE, detail)
            except (NothingToResolve, NoSuchJob):
                return _conflict("nothing_to_resolve")
            except (OmsNotReady, ReconciliationUnavailable):
                detail = "The account's reconciliation job cannot take a decision yet."
                return _problem(ErrorCode.OMS_NOT_READY, detail)
            answer_body = api.ReconciliationResolved.model_validate(
                {"exchange_account_id": str(account.id), "resolved": state,
                 "resolved_at": clock()}
            )  # fmt: skip
            _log().warning("reconcile_route_resolved", account_id=str(account.id), state=state)
            out = JSONResponse(answer_body.model_dump(mode="json"), 200, dict(_NO_STORE))
            return kept_answer(held, digest, out)
        finally:
            running.discard(held)

    return router
