"""The profile reads (E28-T02, #906 slice D1c): `listAccountProfiles`, `getAccountProfile`.

The session (401), then `accounts:read` on the permission alone (`Scope.NONE`: a refusal is a 403,
audited as `rbac.denied`, else logged by ids and class), then the store (503 on the fake
backend). The account scope is the stores' own, in SQL (`auth.scopes.account_scope`, SR-051), so
an account outside the caller's grants answers as a missing one: one unaudited 404 per operation
(PF-I06). Each read resolves the account first, in that scope, for the environment its documents
carry (an account of any environment is answered), then its profiles; an empty list (a soft
delete in between) is that same 404. A store's live-owner gate refusing an Owner is a 403, counted
and audited (`not_owner`); an outage or an unreadable stored row is 503, logged by its class and
SQLSTATE only (C-12.6); any other error is a defect (500). The list is one page (a C3 exemption)
with no `ETag`; a profile answers its weak `ETag`. The profile writes (#906 D2) reuse `problem`,
`OnAccount` and `not_owner`.
"""

from __future__ import annotations

import inspect
import uuid
from typing import Annotated, Any, Final, Protocol

import structlog
from fastapi import APIRouter, Path, Request
from fastapi.responses import JSONResponse, Response

from candleviewer.accounts.errors import (
    AccountNotFoundError,
    AccountScopeDeniedError,
    AccountsError,
)
from candleviewer.accounts.models import ExchangeAccount
from candleviewer.accounts.profile_repository import StoredProfile
from candleviewer.api.csrf import source_ip
from candleviewer.api.profile_projection import profile_document, profile_etag
from candleviewer.api.refusal_session import NamesSession, SessionsLike
from candleviewer.api.storage_outage import is_storage_outage
from candleviewer.api.users import SnapshotResolver
from candleviewer.audit.errors import AuditError
from candleviewer.auth.generated_permissions import Permission, Scope
from candleviewer.auth.metrics import authz_denied_total, normalise_permission
from candleviewer.auth.scopes import ForbiddenError, PrincipalSnapshot, account_scope, enforce
from candleviewer.observability.context import current_request_uuid
from candleviewer.storage.errors import StorageError, StorageQueryFailed
from candleviewer.storage.repositories.accounts import AccountScope
from candleviewer.ws._generated.error_codes import ERROR_META, ErrorCode

_RETRY_AFTER_S: Final = 5
_STATUS: Final = {
    "not_found": 404, "forbidden": 403, "store_unavailable": 503, "not_implemented": 501,
    "unauthenticated": 401,
}  # fmt: skip


def _log() -> Any:
    """Resolved per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


class _Emitter(Protocol):
    async def emit(self, action: str, **kwargs: Any) -> None: ...


class ProfileReads(Protocol):
    """`ProfilesRepository`'s two REST reads (#906 D1b)."""

    async def read_profiles(
        self, scope: AccountScope, account_id: uuid.UUID
    ) -> tuple[StoredProfile, ...]: ...

    async def read_profile(
        self, scope: AccountScope, account_id: uuid.UUID, profile_id: uuid.UUID
    ) -> StoredProfile: ...


class AccountReads(Protocol):
    """`AccountsRepository`'s one read here: the account, in the caller's scope."""

    async def get_account(self, scope: AccountScope, account_id: uuid.UUID) -> ExchangeAccount: ...


class OnAccount:
    """`enforce` names no object: a refused read's `rbac.denied` names its account (C-2.9)."""

    def __init__(self, audit: _Emitter, account_id: uuid.UUID) -> None:
        self._audit, self._account = audit, str(account_id)

    async def emit(self, action: str, **kwargs: Any) -> None:
        named = {"object_kind": "exchange_account", "object_id": self._account}
        await self._audit.emit(action, **kwargs | named)


def problem(
    code: str, detail: str, *, status: int | None = None, retry_s: int | None = None, **extra: Any
) -> JSONResponse:
    """A problem of a registered code (`x-error-codes`); a `503` says when to retry."""
    status, headers = status or _STATUS[code], {}
    body = {"type": f"https://candleviewer.local/errors/{code}", "status": status, "code": code}
    body |= {"title": ERROR_META[ErrorCode(code)].title, "detail": detail, **extra}
    if (retry_s := retry_s or (_RETRY_AFTER_S if status == 503 else None)) is not None:
        body["retry_after_seconds"], headers["Retry-After"] = retry_s, str(retry_s)
    return JSONResponse(body, status, headers, media_type="application/problem+json")


def _forbidden(permission: Permission) -> JSONResponse:
    need = [permission.value]
    return problem("forbidden", f"Requires {permission.value}.", required_permissions=need)


async def not_owner(
    audit: _Emitter, principal: PrincipalSnapshot, account_id: uuid.UUID, *,
    permission: Permission, ip: str | None, request_id: uuid.UUID | None,
) -> None:  # fmt: skip
    """`rbac.denied` for a caller the store's live-owner gate refused once `enforce` let it
    through (SR-051), with `enforce`'s fields and its reason's shape, naming the account. Counted
    before the record, as `enforce` counts (SR-125): a record that cannot be written is logged by
    the ids and its error class (C-12.6), and the refusal stands."""
    authz_denied_total.labels(permission=normalise_permission(permission)).inc()
    actor = principal.user_id
    try:
        await OnAccount(audit, account_id).emit(
            "rbac.denied", actor_label=str(actor), actor_user_id=actor, actor_ip=ip,
            outcome="denied", severity="warning", request_id=request_id,
            reason=f"not_owner:{permission.value}:{Scope.GRANTED_ACCOUNTS.value}",
        )  # fmt: skip
    except (AuditError, RuntimeError) as exc:  # RuntimeError: the audit writer is not started
        ids = {"actor_user_id": str(actor), "account_id": str(account_id)}
        _log().warning("profile_read_denial_unaudited", **ids, error=type(exc).__name__)


def make_profiles_router(
    reads: ProfileReads | None, accounts: AccountReads | None, audit: _Emitter,
    resolver: SnapshotResolver | None, *, auth: SessionsLike | None = None,
) -> APIRouter:  # fmt: skip
    """The two reads over the profile store's facade and the accounts store (`None`, the fake
    backend: 503); `resolver=None` (no identity wired): 501 for every call. A refusal's record
    names the caller's session, read through `auth` (#4174)."""
    router = APIRouter(tags=["exchange-accounts"])

    async def admit(
        request: Request, account_id: uuid.UUID
    ) -> tuple[PrincipalSnapshot, ProfileReads, AccountReads] | Response:
        """The session, `accounts:read`, then the store (module docstring)."""
        if resolver is None:
            return problem("not_implemented", "No principal resolver is wired.")
        got = resolver.resolve(request)
        if (principal := await got if inspect.isawaitable(got) else got) is None:
            return problem("unauthenticated", "No verified session for this request.")
        try:
            await enforce(
                principal, Permission.ACCOUNTS_READ, scope=Scope.NONE,
                emitter=OnAccount(NamesSession(audit, auth, request), account_id),
                actor_ip=source_ip(request.scope), request_id=current_request_uuid(),
            )  # fmt: skip
        except ForbiddenError:
            return _forbidden(Permission.ACCOUNTS_READ)
        except (AuditError, RuntimeError) as exc:  # unrecordable: logged, and still refused
            ids = {"actor_user_id": str(principal.user_id), "account_id": str(account_id)}
            _log().warning("profile_read_denial_unaudited", **ids, error=type(exc).__name__)
            return _forbidden(Permission.ACCOUNTS_READ)
        if reads is None or accounts is None:
            return problem("store_unavailable", "Profiles are not available on this backend.")
        return principal, reads, accounts

    async def refused(
        request: Request, principal: PrincipalSnapshot, account_id: uuid.UUID, exc: Exception,
        missing: str,
    ) -> Response:  # fmt: skip
        """A read that answered no document: the owner gate (403, audited), a miss (the one 404),
        an outage (503, logged); anything else is raised."""
        if isinstance(exc, AccountScopeDeniedError):
            await not_owner(
                NamesSession(audit, auth, request), principal, account_id,
                permission=Permission.ACCOUNTS_READ, ip=source_ip(request.scope),
                request_id=current_request_uuid(),
            )  # fmt: skip
            return _forbidden(Permission.ACCOUNTS_READ)
        if isinstance(exc, AccountNotFoundError):
            return problem("not_found", missing)
        if not isinstance(exc, AccountsError | StorageError) and not is_storage_outage(exc):
            raise exc
        facts = exc if isinstance(exc, StorageQueryFailed) else getattr(exc, "orig", None)
        sqlstate = getattr(facts, "sqlstate", None)  # a driver error names it on its `orig`
        _log().warning("profile_read_unavailable", error=type(exc).__name__, sqlstate=sqlstate)
        return problem("store_unavailable", "The profile store is unavailable.")

    @router.get("/exchange-accounts/{accountId}/profiles")  # nosem: no-raw-account-id reason=account-and-profile-scope-from-auth.scopes.account_scope-applied-in-SQL-by-both-stores-SR-051-PF-I06 owner=@CandleViewer/security review=2027-04-15  # noqa: E501 -- suppression metadata must stay on the matched line  # fmt: skip
    async def list_account_profiles(
        request: Request, account_id: Annotated[uuid.UUID, Path(alias="accountId")]
    ) -> Response:
        if isinstance(admitted := await admit(request, account_id), Response):
            return admitted
        principal, profiles, held = admitted
        scope = account_scope(principal)
        try:
            env = (await held.get_account(scope, account_id)).env
            found = await profiles.read_profiles(scope, account_id)
        except Exception as exc:  # mapped, or raised as a defect
            return await refused(request, principal, account_id, exc, "No such exchange account.")
        if not found:  # the account's profiles soft-deleted since its read: the same 404
            return problem("not_found", "No such exchange account.")
        docs = [
            profile_document(s.profile, created_at=s.created_at, environment=env) for s in found
        ]
        return JSONResponse({"items": docs})

    @router.get("/exchange-accounts/{accountId}/profiles/{profileId}")  # nosem: no-raw-account-id reason=account-and-profile-scope-from-auth.scopes.account_scope-applied-in-SQL-by-both-stores-SR-051-PF-I06 owner=@CandleViewer/security review=2027-04-15  # noqa: E501 -- suppression metadata must stay on the matched line  # fmt: skip
    async def get_account_profile(
        request: Request,
        account_id: Annotated[uuid.UUID, Path(alias="accountId")],
        profile_id: Annotated[uuid.UUID, Path(alias="profileId")],
    ) -> Response:
        if isinstance(admitted := await admit(request, account_id), Response):
            return admitted
        principal, profiles, held = admitted
        scope = account_scope(principal)
        try:
            env = (await held.get_account(scope, account_id)).env
            stored = await profiles.read_profile(scope, account_id, profile_id)
        except Exception as exc:  # mapped, or raised as a defect
            return await refused(request, principal, account_id, exc, "No such profile.")
        doc = profile_document(stored.profile, created_at=stored.created_at, environment=env)
        return JSONResponse(doc, headers={"ETag": profile_etag(stored.profile)})

    return router
