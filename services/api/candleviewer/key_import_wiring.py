"""Composition-root wiring (not a module) for key import, `createApiKey` (E27-T03 slice 2b4, #836).

It holds M2's `CandidateKeys` (minted in `admin.wiring`) for `accounts.key_import`, typed by a
protocol: no import edge (C-3.2, C-3.4). M2's signer goes to the adapter's candidate calls on the
process environment's host only (C-2.11), judged and bounded as the self-check's (`JudgedCalls`).
M2 runs the flow's activation on the key it stored and destroys the key if that fails. M2's
refusals become problem codes by their code and reason, all its errors carry (C-12.6); any other
error propagates. `KeyImports` runs each import to its end in a task of its own, so a cancelled
request never stops one between M2's store and the promotion; `main._lifespan` drains them before
`stop_all` stops the audit writer and M2 (C-2.9), then releases the flow's Postgres pool. The fake
backend (dev/CI) has no store: no import. Nothing here does I/O.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Coroutine, Mapping
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final, Protocol
from uuid import UUID

import structlog

from candleviewer.accounts import key_import as ki
from candleviewer.accounts.models import ExchangeAccount
from candleviewer.accounts.repository import AccountsRepository
from candleviewer.accounts.selfcheck import AuditEmitter
from candleviewer.accounts.verification import VerificationPolicy
from candleviewer.key_selfcheck_wiring import JudgedCalls, KeyVerifyingExchange, VenueCalls
from candleviewer.observability.context import spawn
from candleviewer.observability.secret_type import Secret
from candleviewer.storage.repositories.accounts_sqlalchemy import SqlAlchemyAccountsStore
from candleviewer.storage.repositories.key_selfcheck_sqlalchemy import SqlAlchemyKeySelfCheckStore
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)

if TYPE_CHECKING:
    from candleviewer.app import AppContext

__all__ = ["CandidateKeyHolder", "CandidateVerifier", "KeyImports", "wire_key_import"]

_SIGNING, _STORING, _PENDING = (
    "A signing could not be audited; nothing was stored.",
    "The key was not stored.",
    "The key was stored but neither activated nor removed: it stays pending, unable to trade.",
)
#: M2's refusals by reason, as the import's problem codes, with what the answer says.
_M2_REFUSALS: Final = {
    "kek_unavailable": ("kek_unavailable", "The credential key is unavailable; nothing stored."),
    "credential_shape_invalid": (ki.INVALID, "api_key and api_secret: 1 to 128 visible ASCII."),
    "candidate_timeout": (ki.NO_ANSWER, "The key could not be verified in time; nothing stored."),
    "audit_unavailable": (ki.AUDIT, _SIGNING),
    "audit_timeout": (ki.AUDIT, _SIGNING),
    "store_unavailable": (ki.STORE, _STORING),
    "store_failed": (ki.STORE, _STORING),
    "candidate_not_removed": (ki.STORE, _PENDING),
}
#: The shutdown's wait for the imports in flight, as the account-access drain's: the container's
#: stop budget (#2565) holds no more. An import still running then is left to its own bounds.
DRAIN_S: Final = 5.0


class CandidateKeyHolder(Protocol):
    async def store_if_verified(
        self, env: str, account_id: UUID, label: str, api_key: Secret[str], api_secret: Secret[str],
        check: Callable[[Any], Awaitable[Mapping[str, Any] | None]], *, actor_user_id: str,
        actor_role: str, activate: Callable[[Any], Awaitable[None]],
    ) -> ki.StoredKey | None:  # fmt: skip
        """M2's `CandidateKeys`, typed here so that this file imports no M2 module (C-3.2)."""


class CandidateExchange(KeyVerifyingExchange, Protocol):
    def candidate_verification_calls(
        self, env: str, candidate: Any, *, uid: str, recv_window_ms: int,
        clock_offset_ms: Callable[[], int] | None = None,
    ) -> VenueCalls:  # fmt: skip
        """The adapter's calls for a candidate key (`AppContext.exchange_bybit`)."""


def _m2_refusal(exc: Exception) -> ki.KeyImportFailed | None:
    """An M2 refusal (`KekUnavailable`, `CredentialUnavailable`: a class `code`, the reason as the
    message) as the import's failure; `None` for any other error."""
    if getattr(type(exc), "code", None) not in ("kek_unavailable", "credential_unavailable"):
        return None
    if (refused := _M2_REFUSALS.get(str(exc))) is None:
        return None
    code, text = refused
    errors = (("body", "credential_shape_invalid", text),) if code == ki.INVALID else ()
    return ki.KeyImportFailed(code, text, errors=errors)


async def _close(calls: JudgedCalls) -> None:
    try:
        async with asyncio.timeout(ki.IO_TIMEOUT_S):
            await calls.aclose()
    except Exception as exc:  # TimeoutError included; never changes the outcome
        structlog.get_logger(__name__).warning("key_import_close_failed", error=type(exc).__name__)


class CandidateVerifier:
    """`KeyImport`'s candidate port: M2's hold of the pasted pair over the adapter's calls."""

    def __init__(
        self, keys: CandidateKeyHolder, exchange: CandidateExchange, *, env: str,
        recv_window_ms: int, clock_offset_ms: Callable[[], int],
    ) -> None:  # fmt: skip
        self._keys, self._exchange, self._env = keys, exchange, env
        self._window, self._offset = recv_window_ms, clock_offset_ms

    async def verify_and_store(
        self, account: ExchangeAccount, label: str, request: ki.KeyImportRequest, check: ki.Check,
        actor: ki.Importer, activate: Callable[[ki.StoredKey], Awaitable[None]],
    ) -> ki.StoredKey | None:  # fmt: skip

        async def signed(signer: Any) -> Mapping[str, object] | None:
            venue = self._exchange.candidate_verification_calls(
                self._env, signer, uid=account.exchange_uid, recv_window_ms=self._window,
                clock_offset_ms=self._offset,
            )  # fmt: skip
            calls = JudgedCalls(self._exchange, venue)
            try:
                return await check(calls, signer.key_id)
            finally:
                await _close(calls)

        pair = (request.api_key, request.api_secret)
        try:
            return await self._keys.store_if_verified(
                self._env, account.id, label, *pair, signed, actor_user_id=str(actor.user_id),
                actor_role=actor.role, activate=activate,
            )  # fmt: skip
        except Exception as exc:  # cancellation propagates
            if (refused := _m2_refusal(exc)) is None:
                raise
            raise refused from None


class KeyImports:
    """The import flow on the real backend and the imports it runs, each to its end in a task of
    its own (`run`). At shutdown, before `stop_all`, `drain()` waits for them (bounded, never
    cancelling one), then releases the flow's Postgres pool (#2526)."""

    def __init__(
        self, flow: ki.KeyImport, release: Callable[[], Awaitable[None]], *,
        drain_s: float = DRAIN_S,
    ) -> None:  # fmt: skip
        self.flow, self._release, self._drain_s = flow, release, drain_s
        self._running: set[asyncio.Task[Any]] = set()

    def run[T](self, work: Coroutine[Any, Any, T]) -> asyncio.Task[T]:
        """`work`, an import and its answer, in a task tracked to its end."""
        task = spawn(work, name="create-api-key")
        self._running.add(task)
        task.add_done_callback(self._settled)
        return task

    def _settled(self, task: asyncio.Task[Any]) -> None:
        """A raise is logged here too: once the request is gone, no one awaits the import."""
        self._running.discard(task)
        if not task.cancelled() and (exc := task.exception()) is not None:
            structlog.get_logger(__name__).error("key_import_failed", error=type(exc).__name__)

    async def drain(self) -> int:
        """Wait up to `drain_s` for the imports in flight, then release the pool; returns how many
        still run (logged)."""
        left: set[asyncio.Task[Any]] = set()
        if self._running:
            _, left = await asyncio.wait(set(self._running), timeout=self._drain_s)
        if left:
            structlog.get_logger(__name__).warning("key_imports_left_running", imports=len(left))
        try:
            async with asyncio.timeout(ki.IO_TIMEOUT_S):
                await self._release()
        except Exception as exc:  # TimeoutError included; a shutdown step never raises
            structlog.get_logger(__name__).warning(
                "key_import_release_failed", error=type(exc).__name__
            )
        return len(left)


def wire_key_import(
    ctx: AppContext, keys: CandidateKeyHolder, audit: AuditEmitter
) -> KeyImports | None:
    """The import flow on the real backend, holding `keys`, and its runtime; `None` on the fake
    one."""
    settings = ctx.settings
    if settings.storage_backend != "real":
        return None
    env, window = settings.environment.value, settings.recv_window_ms

    def offset_ms() -> int:
        """Exchange minus host clock, read per request: 0 until the guard has measured it."""
        return ctx.ingestion.clock_offset_ms() or 0

    relational = SqlAlchemyRelationalRepository(settings.pg_dsn.get_secret_value(), "key-import")
    verifier = CandidateVerifier(
        keys, ctx.exchange_bybit, env=env, recv_window_ms=window, clock_offset_ms=offset_ms
    )
    flow = ki.KeyImport(
        AccountsRepository(SqlAlchemyAccountsStore(relational)),
        verifier,
        SqlAlchemyKeySelfCheckStore(relational, env=env),
        audit=audit,
        policy=VerificationPolicy(egress_ip=settings.egress_ip, recv_window_ms=window),
        env=env,
        clock=lambda: datetime.now(UTC),
    )
    return KeyImports(flow, relational.dispose)
