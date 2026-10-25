"""The account routes (E27-S01 backend, #895): `listExchangeAccounts`, `createExchangeAccount`.

`createExchangeAccount`: the path guard asks for the `keys` step-up first (SR-E27-02), FastAPI
checks the closed body (the shared `422`, no value echoed); then the session (401), `accounts:write`
(C-12.4, the Owner's alone: a 403 audited as `rbac.denied`, `503 audit_unavailable` when that
record cannot be written), the store (503 on the fake backend), the optional `Idempotency-Key`
(a key that is no UUID is `422`; the replay of the caller's own `201`, or `409
idempotency_key_reuse` for another body). The shape rules run before the database: a `sub` names
its parent, a `main` none, and the account's environment is the process's (C-2.11: an account
of another environment could never hold a key here). The store's live-owner gate refusing an Owner
is a 403, audited. `accounts.create` is written ahead of the commit, in the insert's transaction
(C-2.9): a record not written is `503 audit_unavailable`, with nothing stored. A taken UID or label
is `409 conflict`, as is a sub past its parent's cap (the 6th; the store locks the parent and counts
before the insert), a parent that is missing, not a `main` or of another environment `422`.

`listExchangeAccounts`: the session, `accounts:read` (a refusal is a 403 whatever its record), then
the store, in the caller's scope applied in SQL (`auth.scopes.account_scope`, SR-051): an Owner
sees every account, anyone else only the accounts granted to them. Each item merges the health
monitor's and the wallet cache's view (`accounts.status`); `include_balance=false` leaves out the
three wallet members. The cursor is opaque, bound to its caller and filters, and expires after an
hour; one that is not is `400 invalid_cursor`. Logs carry classes and ids, never a value (C-12.6).
"""

from __future__ import annotations

import base64
import inspect
import json
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated, Any, Final, Literal, get_args

import structlog
from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, Response

from candleviewer.accounts.errors import (
    AccountConflictError,
    AccountRuleError,
    AccountScopeDeniedError,
    AccountsError,
)
from candleviewer.accounts.models import AccountKind, ExchangeAccount, ExchangeEnv
from candleviewer.accounts.repository import AccountsRepository
from candleviewer.accounts.status import AccountStatusReader
from candleviewer.api._generated import openapi_models as api
from candleviewer.api.csrf import source_ip
from candleviewer.api.idempotency import (
    IdempotencyCache,
    IdempotencyKeyReuse,
    idempotency_key,
    remember,
    replay,
    request_fingerprint,
)
from candleviewer.api.profile_audit import Emitter
from candleviewer.api.profiles import problem
from candleviewer.api.refusal_session import NamesSession, SessionsLike
from candleviewer.api.storage_outage import is_storage_outage
from candleviewer.api.users import SnapshotResolver
from candleviewer.audit.errors import AuditError
from candleviewer.auth.generated_permissions import Permission, Scope
from candleviewer.auth.metrics import count_authz_denial
from candleviewer.auth.scopes import ForbiddenError, PrincipalSnapshot, account_scope, enforce
from candleviewer.observability.context import current_request_uuid
from candleviewer.storage.errors import StorageError, StorageQueryFailed, WriteAheadTimeout
from candleviewer.storage.repositories.accounts import (
    SUB_ACCOUNT_CAP_CONFLICT,
    AccountKey,
    OwnerScope,
)

CURSOR_TTL_S: Final = 3600
#: The one `ExchangeCode` the contract declares (v1 scope): the domain model carries no exchange.
(_EXCHANGE,) = get_args(api.CreateExchangeAccountRequest.model_fields["exchange"].annotation)
_MAX_CURSOR: Final = 512
_UID_TAKEN: Final = "This UID is already registered as {label}."
_LABEL_TAKEN: Final = "This label is already used by another account of this environment."
_SUB_CAP: Final = "The parent account already holds as many sub-accounts as its tier allows."
#: A record not written: the writer refused it, has not started (`RuntimeError`), or timed out.
_UNWRITTEN: Final = (AuditError, RuntimeError, TimeoutError)


def _log() -> Any:
    """Resolved per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


class AccountAuditRefused(Exception):
    """`accounts.create` could not be written ahead; the insert rolled back (503)."""


class _Refused(Exception):
    """A request refused before the store: `validation_failed` with its field entries."""

    def __init__(self, detail: str, *errors: tuple[str | None, str, str]) -> None:
        super().__init__(detail)
        self.detail, self.errors = detail, errors


def _validation(exc: _Refused) -> JSONResponse:
    entries = [
        {"rule": r, "message": m} if f is None else {"field": f, "rule": r, "message": m}
        for f, r, m in exc.errors
    ]
    return problem("validation_failed", exc.detail, status=422, errors=entries)


def _forbidden(permission: Permission) -> JSONResponse:
    need = [permission.value]
    return problem("forbidden", f"Requires {permission.value}.", required_permissions=need)


def _stamp(value: datetime | None) -> str | None:
    return None if value is None else value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def account_document(
    account: ExchangeAccount, statuses: AccountStatusReader | None, *, balance: bool = True,
    key_status: str | None = None,
) -> dict[str, Any]:  # fmt: skip
    """REST `ExchangeAccount`: the row, then the status the monitor and the wallet cache hold
    (`connection_state` alone, `pending` or `disabled`, when none is wired)."""
    doc: dict[str, Any] = {
        "id": str(account.id), "exchange": _EXCHANGE, "environment": account.env.value,
        "kind": account.kind.value, "label": account.label, "exchange_uid": account.exchange_uid,
        "parent_account_id": None if account.parent_account_id is None
        else str(account.parent_account_id),
        "position_mode": account.position_mode, "margin_mode": account.margin_mode,
        "enabled": account.is_enabled, "created_at": _stamp(account.created_at),
        "updated_at": _stamp(account.updated_at),
    }  # fmt: skip
    if key_status is not None:
        doc["key_status"] = key_status
    if statuses is None:
        doc["connection_state"] = "pending" if account.is_enabled else "disabled"
        return doc
    status = statuses.status(account.id, enabled=account.is_enabled).model_dump(mode="json")
    if not balance:
        for member in ("balance", "balance_stale", "balance_stale_since"):
            status.pop(member)
    return doc | status


def encode_cursor(owner: uuid.UUID, filters: list[str | None], after: AccountKey, iat: int) -> str:
    """Opaque keyset cursor: base64url JSON bound to its caller, filters and issue time."""
    position = [after.created_at.isoformat(), str(after.id)]
    raw = json.dumps({"v": 1, "u": str(owner), "f": filters, "a": position, "iat": iat})
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_cursor(
    cursor: str, owner: uuid.UUID, filters: list[str | None], now: int
) -> AccountKey | None:
    """The position of a cursor this caller was issued for these filters within the hour."""
    try:
        if len(cursor) > _MAX_CURSOR:
            return None
        data = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
        if not isinstance(data, dict) or set(data) != {"v", "u", "f", "a", "iat"}:
            return None
        if (data["v"], data["u"], data["f"]) != (1, str(owner), filters):
            return None
        iat, (at, after) = data["iat"], data["a"]
        if type(iat) is not int or not 0 <= now - iat <= CURSOR_TTL_S:
            return None
        created = datetime.fromisoformat(at)
        return AccountKey(created, uuid.UUID(after)) if created.tzinfo is not None else None
    except (ValueError, TypeError):  # bad base64, JSON, shape, time or UUID
        return None


def _shape(body: api.CreateExchangeAccountRequest, env: str) -> None:
    """The rules the database would refuse, checked before it (E27-S01)."""
    if body.kind == "sub" and body.parent_account_id is None:
        msg = "A sub-account names its main account."
        raise _Refused("The account was not registered.", ("parent_account_id", "required", msg))
    if body.kind == "main" and body.parent_account_id is not None:
        msg = "A main account has no parent."
        raise _Refused("The account was not registered.", ("parent_account_id", "forbidden", msg))
    if body.environment != env:
        msg = f"This server registers {env} accounts only."
        raise _Refused("The account was not registered.", ("environment", "environment", msg))


async def _written(record: Any) -> None:
    try:
        await record
    except _UNWRITTEN as exc:
        raise AccountAuditRefused("accounts.create could not be written") from exc


async def _not_owner(
    audit: Emitter, principal: PrincipalSnapshot, permission: Permission, scope: Scope,
    request: Request,
) -> None:  # fmt: skip
    """`rbac.denied` for a caller the store's live-owner gate refused once `enforce` let it through
    (SR-051), in `enforce`'s reason shape; counted first (SR-125), and a record not written is
    logged by the actor and its class, the refusal standing."""
    count_authz_denial(permission, principal.roles)
    actor = principal.user_id
    try:
        await audit.emit(
            "rbac.denied", actor_label=str(actor), actor_user_id=actor,
            actor_ip=source_ip(request.scope), outcome="denied", severity="warning",
            request_id=current_request_uuid(),
            reason=f"not_owner:{permission.value}:{scope.value}",
        )  # fmt: skip
    except (AuditError, RuntimeError) as exc:  # RuntimeError: the audit writer is not started
        _log().warning(
            "account_denial_unaudited", actor_user_id=str(actor), error=type(exc).__name__
        )


def _unavailable(exc: Exception) -> JSONResponse:
    """An outage, logged by class and SQLSTATE alone; anything else is a defect, raised."""
    if not isinstance(exc, AccountsError | StorageError) and not is_storage_outage(exc):
        raise exc
    facts = exc if isinstance(exc, StorageQueryFailed) else getattr(exc, "orig", None)
    sqlstate = getattr(facts, "sqlstate", None)  # a driver error names it on its `orig`
    _log().warning("account_store_unavailable", error=type(exc).__name__, sqlstate=sqlstate)
    return problem("store_unavailable", "The account store is unavailable.")


def make_exchange_accounts_router(
    accounts: AccountsRepository | None, audit: Emitter, resolver: SnapshotResolver | None, *,
    environment: str, statuses: AccountStatusReader | None = None,
    auth: SessionsLike | None = None, replays: IdempotencyCache | None = None,
    new_id: Callable[[], uuid.UUID] = uuid.uuid4,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> APIRouter:  # fmt: skip
    """The two routes over `accounts` (`None`, the fake backend: 503) for the process's
    `environment`; `resolver=None` (no identity wired): 501 for every call."""
    router = APIRouter(tags=["exchange-accounts"])
    cache = IdempotencyCache() if replays is None else replays

    async def admit(
        request: Request, permission: Permission
    ) -> tuple[PrincipalSnapshot, AccountsRepository] | Response:
        if resolver is None:
            return problem("not_implemented", "No principal resolver is wired.")
        got = resolver.resolve(request)
        if (principal := await got if inspect.isawaitable(got) else got) is None:
            return problem("unauthenticated", "No verified session for this request.")
        try:
            await enforce(
                principal, permission, scope=Scope.NONE, emitter=NamesSession(audit, auth, request),
                actor_ip=source_ip(request.scope), request_id=current_request_uuid(),
            )  # fmt: skip
        except ForbiddenError:
            return _forbidden(permission)
        except (AuditError, RuntimeError) as exc:  # RuntimeError: the audit writer is not started
            if permission is Permission.ACCOUNTS_WRITE:  # a write never passes an unwritten record
                return problem("audit_unavailable", "The refusal could not be audited.")
            ids = {"actor_user_id": str(principal.user_id), "error": type(exc).__name__}
            _log().warning("account_denial_unaudited", **ids)
            return _forbidden(permission)
        if accounts is None:
            return problem("store_unavailable", "Accounts are not available on this backend.")
        return principal, accounts

    async def uid_holder(
        store: AccountsRepository, principal: PrincipalSnapshot,
        body: api.CreateExchangeAccountRequest,
    ) -> str:  # fmt: skip
        """The conflict's message: the label of the account that holds the UID, read in the
        Owner's own scope (every account), else the plain conflict; the 409 stands either way."""
        plain = "This UID is already registered."
        env = ExchangeEnv(body.environment)
        try:
            page = await store.list_accounts(OwnerScope(principal.user_id), env=env, limit=500)
        except Exception as exc:  # an outage only words the message; a defect is raised
            _unavailable(exc)
            return plain
        held = next((a.label for a in page.items if a.exchange_uid == body.exchange_uid), None)
        return plain if held is None else _UID_TAKEN.format(label=held)

    @router.post("/exchange-accounts", status_code=201)  # nosem: no-raw-account-id reason=owner-only-create-OwnerScope-live-owner-gate-in-SQL-SR-051-and-accounts.create-written-ahead-#895 owner=@CandleViewer/security review=2027-04-15  # noqa: E501 -- suppression metadata must stay on the matched line  # fmt: skip
    async def create_exchange_account(
        request: Request, body: api.CreateExchangeAccountRequest
    ) -> Response:
        if isinstance(admitted := await admit(request, Permission.ACCOUNTS_WRITE), Response):
            return admitted
        principal, store = admitted
        owner, ip, request_id = (
            str(principal.user_id),
            source_ip(request.scope),
            current_request_uuid(),
        )
        try:
            key = idempotency_key(request, "createExchangeAccount")
        except ValueError:
            msg = "The Idempotency-Key is not a UUID."
            return _validation(
                _Refused("The request was refused.", ("Idempotency-Key", "uuid", msg))
            )
        sent = json.dumps(body.model_dump(mode="json"), sort_keys=True).encode()
        digest = request_fingerprint(request.method, request.url.path, sent)
        try:
            if (hit := replay(cache, owner, key, digest)) is not None:
                return hit
            _shape(body, environment)
        except IdempotencyKeyReuse:
            return problem("idempotency_key_reuse", "The key was used for another request.")
        except _Refused as exc:
            return _validation(exc)

        async def created(account: ExchangeAccount) -> None:
            after = {
                "exchange": body.exchange, "env": account.env.value, "kind": account.kind.value,
                "label": account.label, "exchange_uid": account.exchange_uid,
                "parent_account_id": body.parent_account_id and str(body.parent_account_id),
            }  # fmt: skip
            await _written(
                audit.emit(
                    "accounts.create", actor_label=owner, actor_user_id=principal.user_id,
                    actor_ip=ip, object_kind="exchange_account", object_id=str(account.id),
                    outcome="success", severity="info", request_id=request_id,
                    env=account.env, after_state=after,
                )
            )  # fmt: skip

        try:
            account = await store.create_account(
                OwnerScope(principal.user_id), id=new_id(), exchange=body.exchange,
                env=ExchangeEnv(body.environment), kind=AccountKind(body.kind),
                exchange_uid=body.exchange_uid, label=body.label,
                parent_account_id=body.parent_account_id, write_ahead=created,
            )  # fmt: skip
        except AccountScopeDeniedError:  # the store's live-owner gate (SR-051)
            await _not_owner(
                NamesSession(audit, auth, request), principal, Permission.ACCOUNTS_WRITE,
                Scope.NONE, request,
            )  # fmt: skip
            return _forbidden(Permission.ACCOUNTS_WRITE)
        except (AccountAuditRefused, WriteAheadTimeout):
            return problem(
                "audit_unavailable", "The audit record could not be written; nothing was saved."
            )
        except AccountConflictError as exc:
            if exc.constraint == "ux_ea_uid":
                return problem("conflict", await uid_holder(store, principal, body))
            if exc.constraint == "ux_ea_label":
                return problem("conflict", _LABEL_TAKEN)
            if exc.constraint == SUB_ACCOUNT_CAP_CONFLICT:
                return problem("conflict", _SUB_CAP)
            return problem("conflict", "The account conflicts with a stored one.")
        except AccountRuleError as exc:
            entry: tuple[str | None, str, str]
            if "parent" in exc.rule:
                msg = "The parent is not a live main account of this environment."
                entry = ("parent_account_id", exc.rule, msg)
            else:
                entry = (None, exc.rule, "The account breaks a stored rule.")
            return _validation(_Refused("The account was not registered.", entry))
        except Exception as exc:  # mapped, or raised as a defect
            return _unavailable(exc)
        doc = account_document(account, statuses, key_status="missing")
        return remember(cache, owner, key, digest, JSONResponse(doc, 201))

    @router.get("/exchange-accounts")
    async def list_exchange_accounts(
        request: Request,
        cursor: Annotated[str | None, Query(max_length=_MAX_CURSOR)] = None,
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
        environment: Literal["live", "demo", "testnet"] | None = None,
        kind: Literal["main", "sub"] | None = None,
        include_balance: bool = True,
    ) -> Response:
        if isinstance(admitted := await admit(request, Permission.ACCOUNTS_READ), Response):
            return admitted
        principal, store = admitted
        filters: list[str | None] = [environment, kind]
        now = int(clock().timestamp())
        after = None
        if cursor is not None:
            after = decode_cursor(cursor, principal.user_id, filters, now)
            if after is None:
                detail = "The cursor is malformed, expired or for another query."
                return problem("invalid_cursor", detail, status=400)
        env = None if environment is None else ExchangeEnv(environment)
        try:
            page = await store.list_accounts(
                account_scope(principal), env=env,
                kind=None if kind is None else AccountKind(kind), after=after, limit=limit,
            )  # fmt: skip
        except AccountScopeDeniedError:  # the store's live-owner gate (SR-051)
            await _not_owner(
                NamesSession(audit, auth, request), principal, Permission.ACCOUNTS_READ,
                Scope.GRANTED_ACCOUNTS, request,
            )  # fmt: skip
            return _forbidden(Permission.ACCOUNTS_READ)
        except Exception as exc:  # mapped, or raised as a defect
            return _unavailable(exc)
        items = [account_document(a, statuses, balance=include_balance) for a in page.items]
        nxt = page.next_after and encode_cursor(principal.user_id, filters, page.next_after, now)
        meta = {"next_cursor": nxt, "has_more": nxt is not None, "count": len(items)}
        return JSONResponse({"items": items, "meta": meta})

    return router
