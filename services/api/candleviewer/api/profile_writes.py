"""The profile writes (E28-T02, #906 D2-4 to D2-6), `createAccountProfile` first; none is mounted
before D2-m (ruling B12). Behind the middleware (the view-as guard refuses a viewing session, the
path guard asks for the `risk_caps` step-up, SR-E28-02), `admit` answers: no resolver 501; no
session 401; `accounts:write`, the Owner's alone (C-12.4), before any store read: a 403 audited as
`rbac.denied`, or `503 audit_unavailable` when that record cannot be written (#906's ruling of
2026-10-22 17:25Z (3)); no store 503; the account in the Owner's scope, a missing, deleted or
other-environment one the same 404 (C-2.11), the store's live-owner gate a 403. Then the
`Idempotency-Key`, the body under its cap and the replay of the caller's own `2xx` (SR-E28-17).
`answer` maps every refusal: one `profile.save_refused` per audited rule (`native_stop_mandatory`
from every path, SR-E28-08), none for shape; a record not written is `503 audit_unavailable`, with
nothing stored (C-2.9). Logs carry classes and rule names, never a value (C-12.6).
"""

from __future__ import annotations

import inspect
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Any, Final

import structlog
from fastapi import APIRouter, Path, Request
from fastapi.responses import JSONResponse, Response
from pydantic import ValidationError

from candleviewer.accounts.errors import (
    AccountConflictError,
    AccountNotFoundError,
    AccountRuleError,
    AccountScopeDeniedError,
    AccountsError,
)
from candleviewer.accounts.models import ExchangeEnv
from candleviewer.accounts.profile_input import (
    ProfileFieldError,
    check_profile_input,
    map_profile_input,
    schema_errors,
)
from candleviewer.accounts.profile_repository import ProfilesRepository
from candleviewer.accounts.profile_validator import (
    InstrumentLimitsPort,
    InstrumentLimitsUnavailable,
    check_exchange_limits,
)
from candleviewer.accounts.profiles import to_us
from candleviewer.api import profile_body as edge
from candleviewer.api._generated import openapi_models as api
from candleviewer.api.csrf import source_ip
from candleviewer.api.idempotency import (
    IdempotencyCache,
    IdempotencyKeyReuse,
    remember,
    replay,
    request_fingerprint,
)
from candleviewer.api.profile_audit import Emitter, ProfileActor, ProfileAudit, ProfileAuditRefused
from candleviewer.api.profile_projection import profile_document, profile_etag
from candleviewer.api.profiles import AccountReads, OnAccount, not_owner, problem
from candleviewer.api.refusal_session import NamesSession, SessionsLike
from candleviewer.api.storage_outage import is_storage_outage
from candleviewer.api.users import SnapshotResolver
from candleviewer.audit.errors import AuditError
from candleviewer.auth.generated_permissions import Permission, Scope
from candleviewer.auth.scopes import ForbiddenError, PrincipalSnapshot, enforce
from candleviewer.domain.primitives import Environment
from candleviewer.observability.context import current_request_uuid
from candleviewer.storage.errors import StorageError, StorageQueryFailed, WriteAheadTimeout
from candleviewer.storage.repositories.accounts import OwnerScope

_NO_ACCOUNT: Final = "No such exchange account."
_NAME_TAKEN: Final = "A profile of this account already uses that name, in any letter case."
#: The schema phase's own entry, so the store's `ap_native_sl` CHECK answers as the body's does.
_NATIVE_STOP: Final = schema_errors({"require_native_stop": False}, [])[0]


def _log() -> Any:
    """Resolved per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ProfileWrites:
    """The stores: the reads' facade (one cache, SR-E28-15), and this environment's (C-2.11)."""

    profiles: ProfilesRepository
    accounts: AccountReads
    limits: InstrumentLimitsPort
    environment: Environment


@dataclass(frozen=True, slots=True)
class _Admitted:
    """A write past `admit`; its refusals' records name the caller's session (#4174)."""

    request: Request
    principal: PrincipalSnapshot
    account_id: uuid.UUID
    writes: ProfileWrites
    actor: ProfileActor
    scope: OwnerScope
    records: ProfileAudit
    refusals: ProfileAudit


def _forbidden() -> JSONResponse:
    return problem("forbidden", "Requires accounts:write.", required_permissions=["accounts:write"])


def _unaudited() -> JSONResponse:
    return problem("audit_unavailable", "The audit record could not be written; nothing was saved.")


def _schema(raw: object) -> dict[str, Any]:
    """The generated model, then B1a's own rules on a body it refuses; else the members sent."""
    try:
        model = api.AccountProfileInput.model_validate(raw)
    except ValidationError as exc:
        raise edge.refused(schema_errors(raw, edge.model_errors(exc))) from None
    return model.model_dump(mode="json", exclude_unset=True)


def make_profile_writes_router(
    writes: ProfileWrites | None, audit: Emitter, resolver: SnapshotResolver | None, *,
    auth: SessionsLike | None = None, replays: IdempotencyCache | None = None,
    new_id: Callable[[], uuid.UUID] = uuid.uuid4,
) -> APIRouter:  # fmt: skip
    """The writes over `writes` (`None`: 503); `resolver=None` (no identity wired): 501."""
    router = APIRouter(tags=["exchange-accounts"])
    cache = IdempotencyCache() if replays is None else replays

    async def admit(request: Request, account_id: uuid.UUID) -> _Admitted | Response:
        """The admission, in the module docstring's order."""
        if resolver is None:
            return problem("not_implemented", "No principal resolver is wired.")
        got = resolver.resolve(request)
        if (principal := await got if inspect.isawaitable(got) else got) is None:
            return problem("unauthenticated", "No verified session for this request.")
        ip, request_id = source_ip(request.scope), current_request_uuid()
        named = NamesSession(audit, auth, request)
        try:
            await enforce(
                principal, Permission.ACCOUNTS_WRITE, scope=Scope.NONE,
                emitter=OnAccount(named, account_id), actor_ip=ip, request_id=request_id,
            )  # fmt: skip
        except ForbiddenError:
            return _forbidden()
        except (AuditError, RuntimeError):  # RuntimeError: the audit writer is not started
            return _unaudited()
        if writes is None:
            return problem("store_unavailable", "Profiles are not available on this backend.")
        actor = ProfileActor(principal.user_id, ip, request_id, ExchangeEnv(writes.environment))
        admitted = _Admitted(
            request, principal, account_id, writes, actor, OwnerScope(principal.user_id),
            ProfileAudit(audit, actor, account_id), ProfileAudit(named, actor, account_id),
        )  # fmt: skip
        try:
            held = await writes.accounts.get_account(admitted.scope, account_id)
        except Exception as exc:  # mapped, or raised as a defect
            return await answer(exc, admitted)
        return admitted if held.env is actor.env else problem("not_found", _NO_ACCOUNT)

    async def answer(exc: Exception, got: _Admitted) -> Response:
        """A write that stored nothing: an unwritten record before the `StorageError` a
        `WriteAheadTimeout` is, a stale listing before its `AccountsError`; a defect is raised."""
        if isinstance(exc, edge.Refused):
            try:
                await got.refusals.audit_refused(exc.errors, profile_id=None)
            except ProfileAuditRefused:
                return _unaudited()
            entries = [entry.to_dict() for entry in exc.errors]
            return problem("validation_failed", exc.detail, errors=entries)
        if isinstance(exc, edge.BodyTooLarge):
            return problem("payload_too_large", str(exc))
        if isinstance(exc, IdempotencyKeyReuse):
            return problem("idempotency_key_reuse", "The key was used for another request.")
        if isinstance(exc, ProfileAuditRefused | WriteAheadTimeout):
            return _unaudited()
        if isinstance(exc, InstrumentLimitsUnavailable):
            detail = "The exchange's limits could not be refreshed in time; nothing was saved."
            return problem("instrument_cache_unavailable", detail, retry_s=2)
        if isinstance(exc, AccountNotFoundError):
            return problem("not_found", _NO_ACCOUNT)
        if isinstance(exc, AccountConflictError) and exc.constraint == "ux_ap_name":
            return problem("conflict", _NAME_TAKEN)
        if isinstance(exc, AccountRuleError):  # the store's own CHECK, which the passes missed
            if exc.rule == "ap_native_sl":
                return await answer(edge.refused([_NATIVE_STOP]), got)
            _log().error("profile_write_refused_by_constraint", rule=exc.rule)
            stored = ProfileFieldError("", exc.rule, "The profile breaks a stored rule.")
            return await answer(edge.refused([stored]), got)
        if isinstance(exc, AccountScopeDeniedError):  # the store's live-owner gate (SR-051)
            await not_owner(
                NamesSession(audit, auth, got.request), got.principal, got.account_id,
                permission=Permission.ACCOUNTS_WRITE, ip=got.actor.ip,
                request_id=got.actor.request_id,
            )  # fmt: skip
            return _forbidden()
        if not isinstance(exc, AccountsError | StorageError) and not is_storage_outage(exc):
            raise exc
        facts = exc if isinstance(exc, StorageQueryFailed) else getattr(exc, "orig", None)
        sqlstate = getattr(facts, "sqlstate", None)  # a driver error names it on its `orig`
        _log().warning("profile_write_unavailable", error=type(exc).__name__, sqlstate=sqlstate)
        return problem("store_unavailable", "The profile store is unavailable.")

    @router.post("/exchange-accounts/{accountId}/profiles", status_code=201)  # nosem: no-raw-account-id reason=owner-only-write-OwnerScope-live-owner-gate-and-account-predicate-in-SQL-SR-051-PF-T01 owner=@CandleViewer/security review=2027-04-15  # noqa: E501 -- suppression metadata must stay on the matched line  # fmt: skip
    async def create_account_profile(
        request: Request, account_id: Annotated[uuid.UUID, Path(alias="accountId")]
    ) -> Response:
        if isinstance(got := await admit(request, account_id), Response):
            return got
        try:
            key = edge.idempotency(request, "createAccountProfile")
            raw = await edge.read_capped(request, edge.MAX_PROFILE_BODY_BYTES)
            digest = request_fingerprint(request.method, request.url.path, raw)
            if (hit := replay(cache, str(got.principal.user_id), key, digest)) is not None:
                return hit
            body = _schema(edge.decode(raw))
            if errors := check_profile_input(body, stored_is_default=None) + edge.name_errors(body):
                raise edge.refused(errors)
            profile = map_profile_input(
                body, profile_id=new_id(), account_id=account_id, version=1,
                updated_at=to_us(datetime.now(UTC)),  # the store writes its own
            )  # fmt: skip
            second = await check_exchange_limits(
                profile, environment=got.writes.environment, instruments=got.writes.limits,
                stored=None,
            )  # fmt: skip
            if second.errors:
                raise edge.refused(second.errors, limits=True)
            stored = await got.writes.profiles.create_profile(
                got.scope, account_id, profile, write_ahead=got.records.audit_created()
            )
        except Exception as exc:  # mapped, or raised as a defect
            return await answer(exc, got)
        doc = profile_document(
            stored.profile, created_at=stored.created_at, environment=got.actor.env,
            warnings=second.warnings,
        )  # fmt: skip
        out = JSONResponse(doc, 201, {"ETag": profile_etag(stored.profile)})
        return remember(cache, str(got.principal.user_id), key, digest, out)

    return router
