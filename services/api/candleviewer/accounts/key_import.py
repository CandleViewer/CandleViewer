"""Key import, the flow of `createApiKey` over ports (E27-T03 slice 2b4, #836).

An M13 flow like `selfcheck.py`: it imports no M2 or M4 module and adds no import edge (C-3.1,
C-3.2, C-3.4); `key_import_wiring` binds its ports. For the acting Owner (SR-E27-09):

1. The account is read in the caller's owner scope (SR-051: the store's live-owner gate). An
   account of another environment is `not_found`, as a missing one is (C-2.11, no existence
   oracle), and a sent `expected_uid` must be its UID. An import already running for the account,
   an `active` key (one per account, `ux_api_keys_active`: rotation replaces a key) or an unrevoked
   key with the label is a `conflict`, answered before anything is signed.
2. M2 holds the pasted pair for one check (decision 7, SR-E27-01), which runs the pipeline
   (`verify()`) over the candidate's signed calls. A refusal or a call without a verdict stores
   nothing.
3. `api_key.import` names the Owner and their role, the outcome and the rule codes, never key
   material (decision 12). It is written ahead: a pass before M2 stores the key, every other
   outcome (an unexpected error or a cancellation too) before it leaves; after a pass's record,
   whatever fails gets a closing `failure` record naming the same key. A record that cannot be
   written refuses the import (`audit_unavailable`, C-2.9).
4. After the store M2 runs the activation: the verified columns, then the promotion from `pending`
   to `active`, `transition_key_status`'s one production caller (SR-E27-01, AC-34). If it fails, M2
   destroys the key (audited, revoked): nothing usable stays and its label is free, so the import
   may be sent again. The route runs `run` in a task a cancelled request does not stop.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final, Protocol
from uuid import UUID

import structlog

from candleviewer.accounts.errors import (
    AccountConflictError,
    AccountNotFoundError,
    AccountScopeDeniedError,
    AccountsError,
)
from candleviewer.accounts.models import ApiKeyMetadata, ExchangeAccount, KeyStatus
from candleviewer.accounts.repository import AccountsRepository
from candleviewer.accounts.selfcheck import AuditEmitter, SelfCheckCalls, _facts
from candleviewer.accounts.verification import (
    VerificationInconclusive,
    VerificationPolicy,
    VerificationResult,
    verify,
)
from candleviewer.observability.secret_type import Secret
from candleviewer.storage.repositories.accounts import OwnerScope, VerifiedKey

ACTION: Final = "api_key.import"
#: Each store read or write and each audit record; M2 bounds the whole check at 12 s.
IO_TIMEOUT_S: Final = 5.0
#: The problem codes (`x-error-codes`) of an import that stores no usable key.
CONFLICT, NOT_FOUND, FORBIDDEN, INVALID = "conflict", "not_found", "forbidden", "validation_failed"
STORE, AUDIT = "store_unavailable", "audit_unavailable"
NO_ANSWER, ERROR_ANSWER = "exchange_unavailable", "exchange_error"
#: No verdict because the exchange gave no answer, or none in time (`createApiKey`, No verdict).
_UNANSWERED: Final = frozenset({"transport_error", "timeout", "probe_slow", "probe_clock_step"})
#: Refusals of the request itself (`denied`); every other failure is an outage (`failure`).
_DENIED: Final = frozenset({CONFLICT, NOT_FOUND, FORBIDDEN, INVALID})
_UID: Final = ("expected_uid", "expected_uid_mismatch", "expected_uid must be the account's UID")
_NO_VERDICT: Final = {
    NO_ANSWER: "The exchange gave no answer, so the key could not be verified; nothing was stored.",
    ERROR_ANSWER: "The exchange refused the signed call, so the key could not be verified; "
    "nothing was stored.",
}

#: The check M2 runs while it holds the pair, given the candidate's calls and the id M2 minted for
#: it: the verified snapshot to store on a pass, `None` on a refusal.
Check = Callable[[SelfCheckCalls, UUID], Awaitable[Mapping[str, object] | None]]


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


class KeyImportFailed(AccountsError):
    """An import that stored no usable key, by its answer's problem code. `result` is a refused
    key's verdict, `errors` the `(field, rule, message)` its `422` names and `ret_code` the
    exchange's return code of a call without a verdict, when it sent one."""

    def __init__(
        self, code: str, detail: str, *, result: VerificationResult | None = None,
        errors: tuple[tuple[str, str, str], ...] = (), ret_code: int | None = None,
        transient: bool = False,  # a refusal that clears by itself: the route never replays it
    ) -> None:  # fmt: skip
        super().__init__(code)
        self.code, self.detail, self.result = code, detail, result
        self.errors, self.ret_code, self.transient = errors, ret_code, transient


@dataclass(frozen=True, slots=True)
class Importer:
    """The acting Owner, as the audit records name them (SR-E27-09)."""

    user_id: UUID
    role: str
    ip: str | None = None
    request_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class KeyImportRequest:
    """A validated `CreateApiKeyRequest` for one account; the pair stays masked (C-12.6). Without
    a label the key takes the account's (labels are unique per account)."""

    account_id: UUID
    api_key: Secret[str]
    api_secret: Secret[str]
    label: str | None = None
    read_only: bool = False
    expected_uid: str | None = None


@dataclass(frozen=True, slots=True)
class KeyImported:
    key: ApiKeyMetadata
    verification: VerificationResult
    at: datetime


class StoredKey(Protocol):
    @property
    def key_id(self) -> UUID: ...


class CandidatePort(Protocol):
    """M2's hold of the pasted pair with the adapter's calls for it (`key_import_wiring`)."""

    async def verify_and_store(
        self, account: ExchangeAccount, label: str, request: KeyImportRequest, check: Check,
        actor: Importer, activate: Callable[[StoredKey], Awaitable[None]],
    ) -> StoredKey | None:  # fmt: skip
        """The stored key, `activate`d, if `check` returned a snapshot, else `None`. If `activate`
        fails, M2 destroys the key and its error goes on. M2's own refusals arrive as
        `KeyImportFailed`; the check's errors propagate unchanged."""


class VerifiedColumns(Protocol):
    """The verified `api_keys` columns of the key this import stored: the self-check's store."""

    async def record_pass(self, key_id: UUID, verified: VerifiedKey) -> bool: ...


def problem_code(exc: AccountsError) -> str:
    if isinstance(exc, KeyImportFailed):
        return exc.code
    if isinstance(exc, AccountConflictError):
        return CONFLICT
    if isinstance(exc, AccountNotFoundError):
        return NOT_FOUND
    return FORBIDDEN if isinstance(exc, AccountScopeDeniedError) else STORE


def _codes(result: VerificationResult) -> dict[str, object]:
    return {"failures": [f.rule.value for f in result.failures], "warnings": list(result.warnings)}


class KeyImport:
    """`createApiKey` for the process environment (module docstring)."""

    def __init__(
        self, accounts: AccountsRepository, candidates: CandidatePort, verified: VerifiedColumns,
        *, audit: AuditEmitter, policy: VerificationPolicy, env: str,
        clock: Callable[[], datetime], timeout_s: float = IO_TIMEOUT_S,
    ) -> None:  # fmt: skip
        self._accounts, self._candidates, self._verified = accounts, candidates, verified
        self._audit, self._policy, self._env, self._clock = audit, policy, env, clock
        self._timeout_s = timeout_s
        #: Accounts with an import running, one each: bounded by the requests in flight.
        self._busy: set[UUID] = set()

    async def run(self, request: KeyImportRequest, actor: Importer) -> KeyImported:
        """The imported key, or the refusal (`KeyImportFailed`, `AccountNotFoundError`,
        `AccountScopeDeniedError`, `AccountConflictError`), recorded before it is raised; any
        other error or a cancellation is recorded too and goes on as it is."""
        passed: dict[str, object] = {}  # the key id of a pass's record, once it is written
        try:
            return await self._run(request, actor, passed)
        except BaseException as exc:
            result = exc.result if isinstance(exc, KeyImportFailed) else None
            if isinstance(exc, AccountsError):
                code = problem_code(exc)
                after: dict[str, object] = {"code": code} if result is None else _codes(result)
            else:  # a defect, M2's store-time refusal or a cancellation: its class, never its text
                code = "cancelled" if isinstance(exc, asyncio.CancelledError) else "error"
                after = {"code": code, "error": type(exc).__name__}
            reason = code if result is None else result.failures[0].rule.value
            outcome = "denied" if code in _DENIED and not passed else "failure"
            try:  # a closing record names the key the pass's record named
                await self._audit_row(actor, request.account_id, outcome, reason, after | passed)
            except KeyImportFailed:
                if isinstance(exc, AccountsError):
                    raise  # a refusal whose record is lost is `audit_unavailable`
            raise

    async def _run(
        self, request: KeyImportRequest, actor: Importer, passed: dict[str, object]
    ) -> KeyImported:
        scope = OwnerScope(actor.user_id)
        account = await self._io(self._accounts.get_account(scope, request.account_id))
        if account.env.value != self._env:  # never signed for on this environment's host
            raise AccountNotFoundError("account")
        if request.expected_uid not in (None, account.exchange_uid):
            raise KeyImportFailed(INVALID, "expected_uid is not the account's UID.", errors=(_UID,))
        if account.id in self._busy:
            raise KeyImportFailed(CONFLICT, "The account has an import running.", transient=True)
        self._busy.add(account.id)
        try:
            label = request.label or account.label
            keys = await self._io(self._accounts.list_keys(scope, account.id))
            if any(key.status is KeyStatus.ACTIVE for key in keys):
                raise KeyImportFailed(CONFLICT, "The account has an active key; rotate it.")
            if any(key.label.lower() == label.lower() for key in keys):
                raise KeyImportFailed(CONFLICT, "Another key of the account has this label.")
            return await self._import(scope, account, label, request, actor, passed)
        finally:
            self._busy.discard(account.id)

    async def _import(
        self, scope: OwnerScope, account: ExchangeAccount, label: str, request: KeyImportRequest,
        actor: Importer, passed: dict[str, object],
    ) -> KeyImported:  # fmt: skip
        now, seen, done = self._clock(), list[VerificationResult](), list[KeyImported]()

        async def check(calls: SelfCheckCalls, key_id: UUID) -> Mapping[str, object] | None:
            result = await verify(
                account, read_only=request.read_only, key_info=calls.key_info,
                probe=calls.probe, policy=self._policy, now=now,
            )  # fmt: skip
            seen.append(result)
            if not result.passed:
                return None
            after = {**_codes(result), "key_id": str(key_id)}
            await self._audit_row(actor, account.id, "success", None, after)  # ahead of the store
            passed["key_id"] = str(key_id)
            return _facts(result, now)

        async def activate(stored: StoredKey) -> None:  # M2 destroys the key if this raises
            done.append(await self._activate(scope, account.id, stored.key_id, seen[-1], now))

        try:
            stored = await self._candidates.verify_and_store(
                account, label, request, check, actor, activate
            )
        except VerificationInconclusive as exc:  # no verdict: nothing stored
            answer = NO_ANSWER if str(exc) in _UNANSWERED else ERROR_ANSWER
            raise KeyImportFailed(answer, _NO_VERDICT[answer], ret_code=exc.ret_code) from None
        if stored is None:  # a verdict refused the key: nothing stored
            result = seen[-1]
            errors = tuple(("api_key", f.rule.value, f.message) for f in result.failures)
            raise KeyImportFailed(INVALID, result.failures[0].message, result=result, errors=errors)
        return done[0]

    async def _activate(
        self, scope: OwnerScope, account_id: UUID, key_id: UUID, result: VerificationResult,
        now: datetime,
    ) -> KeyImported:  # fmt: skip
        """The verified columns, then the promotion: the key is usable only after both."""
        verified = VerifiedKey(
            _facts(result, now), result.can_trade, result.read_only, result.ip_whitelist,
            result.expires_at, now,
        )  # fmt: skip
        if not await self._io(self._verified.record_pass(key_id, verified)):
            raise KeyImportFailed(STORE, "The verified key could not be recorded.")
        promote = self._accounts.transition_key_status(
            scope, account_id, key_id, expected=KeyStatus.PENDING, new=KeyStatus.ACTIVE
        )
        key = await self._io(promote)
        _log().info("key_imported", key_id=str(key_id), account_id=str(account_id))
        return KeyImported(key, result, now)

    async def _io[T](self, step: Awaitable[T]) -> T:
        """One store read or write, bounded. An outage, a timeout or another store error is
        `store_unavailable`, logged by its class and SQLSTATE, never by its text (DETAIL)."""
        try:
            async with asyncio.timeout(self._timeout_s):
                return await step
        except (AccountNotFoundError, AccountScopeDeniedError, AccountConflictError):
            raise
        except Exception as exc:  # TimeoutError included; cancellation propagates
            sqlstate = getattr(getattr(exc, "orig", None), "sqlstate", None)
            _log().error("key_import_store_failed", error=type(exc).__name__, sqlstate=sqlstate)
            raise KeyImportFailed(STORE, "The relational store is unavailable.") from None

    async def _audit_row(
        self, actor: Importer, account_id: UUID, outcome: str, reason: str | None,
        after: dict[str, object],
    ) -> None:  # fmt: skip
        """`api_key.import`, durable before what it covers is done or answered (C-2.9)."""
        try:
            async with asyncio.timeout(self._timeout_s):
                await self._audit.emit(
                    ACTION, actor_label=f"user:{actor.role}", actor_user_id=actor.user_id,
                    actor_ip=actor.ip, object_kind="exchange_account",
                    object_id=str(account_id), outcome=outcome, reason=reason, after_state=after,
                    severity="info" if outcome == "success" else "warning",
                    request_id=actor.request_id, env=self._env,
                )  # fmt: skip
        except Exception as exc:  # TimeoutError included; cancellation propagates
            _log().error("key_import_audit_failed", error=type(exc).__name__)
            detail = "The audit record of the import could not be written; nothing was stored."
            raise KeyImportFailed(AUDIT, detail) from None
