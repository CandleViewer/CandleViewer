"""Composition-root wiring (not a module) for the stored-key self-check (E27-T03, #836).

M13 judges keys and may import neither M3 nor M4 (C-3.1); M4 makes the signed calls and may not
import M13. This glue binds them: a refusal that is a verdict about the key becomes `KeyRefused`,
every other adapter error `VerificationInconclusive` carrying its `KeyProbeError` name,
never exchange text (SR-E27-08). Each call, its budget wait and its signing included, is cut at the
adapter's own per-call bound, read from the adapter surface (`key_call_timeout_s`; ticket
performance notes), so this file imports no venue module (C-2.2). The store, the calls and the job
are bound to the process environment, so a key is read, signed and sent on its own environment
only (C-2.11, US-ACCT-007). Requests carry the exchange's clock once the ingestion clock guard has
measured the offset (E08-S07), so a skewed host clock shows in the verdict's offset instead of a
refusal. Only the real backend gets a self-check: the fake one (dev/CI) stores no key and makes no
call (C-13.5). Nothing here does I/O: `AccountsService.start()` runs the check, and `stop()`
releases its Postgres pool. A borrow that M2's C-2.8 re-check refuses (SR-E27-14) becomes
`WithdrawPermissionError`: the job's `key_withdraw_permission` verdict, never `check_error`.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol
from uuid import UUID

from candleviewer.accounts.errors import WithdrawPermissionError
from candleviewer.accounts.selfcheck import AuditEmitter, KeySelfCheck
from candleviewer.accounts.verification import (
    KeyFacts,
    KeyRefused,
    ProbeFacts,
    Refusal,
    VerificationInconclusive,
    VerificationPolicy,
)
from candleviewer.exchange.base.errors import ExchangeError
from candleviewer.storage.repositories.key_selfcheck_sqlalchemy import SqlAlchemyKeySelfCheckStore
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)

if TYPE_CHECKING:
    from candleviewer.app import AppContext
    from candleviewer.observability.metrics import Metrics

__all__ = [
    "JudgedCalls",
    "KeyVerifyingExchange",
    "VenueCalls",
    "wire_key_selfcheck",
]


class VenueCalls(Protocol):
    async def key_info(self) -> KeyFacts: ...
    async def probe(self) -> ProbeFacts: ...
    async def aclose(self) -> None: ...


class KeyVerifyingExchange(Protocol):
    """The exchange adapter surface the self-check uses (`AppContext.exchange_bybit`)."""

    @property
    def key_call_timeout_s(self) -> float:
        """The adapter's bound on one call, its budget wait and its signing included."""

    def key_verification_calls(
        self,
        env: str,
        credential_id: UUID,
        *,
        uid: str,
        recv_window_ms: int,
        clock_offset_ms: Callable[[], int],
    ) -> VenueCalls: ...

    def key_refusal(self, error: ExchangeError) -> tuple[str, int] | None: ...

    def key_probe_error(self, error: ExchangeError) -> str: ...

    def key_borrow_refused(self, error: Exception) -> bool: ...


@asynccontextmanager
async def _judging(exchange: KeyVerifyingExchange) -> AsyncIterator[None]:
    """One signed call within the adapter's per-call bound, its errors in the M13 verdict
    vocabulary."""
    try:
        async with asyncio.timeout(exchange.key_call_timeout_s):
            yield
    except TimeoutError:
        raise VerificationInconclusive("timeout") from None
    except ExchangeError as error:
        verdict = exchange.key_refusal(error)
        if verdict is not None:
            raise KeyRefused(Refusal(verdict[0]), verdict[1]) from None
        raise VerificationInconclusive(exchange.key_probe_error(error)) from None
    except Exception as error:  # cancellation propagates
        if exchange.key_borrow_refused(error):
            raise WithdrawPermissionError("key_withdraw_permission") from None
        raise


class JudgedCalls:
    """One key's adapter calls, each error translated into the M13 verdict vocabulary."""

    def __init__(self, exchange: KeyVerifyingExchange, calls: VenueCalls) -> None:
        self._exchange, self._calls = exchange, calls

    async def key_info(self) -> KeyFacts:
        async with _judging(self._exchange):
            return await self._calls.key_info()

    async def probe(self) -> ProbeFacts:
        async with _judging(self._exchange):
            return await self._calls.probe()

    async def aclose(self) -> None:
        await self._calls.aclose()


def wire_key_selfcheck(
    ctx: AppContext, audit: AuditEmitter, metrics: Metrics
) -> KeySelfCheck | None:
    """Attach the self-check to `ctx.accounts` on the real backend; `None` on the fake one. Its
    series are the catalogue's, registered on `metrics` (`register_r0`) before this runs."""
    settings = ctx.settings
    if settings.storage_backend != "real":
        return None
    env, window = settings.environment.value, settings.recv_window_ms
    exchange: KeyVerifyingExchange = ctx.exchange_bybit

    def offset_ms() -> int:
        """Exchange minus host clock, read per request: 0 until the guard has measured it."""
        return ctx.ingestion.clock_offset_ms() or 0

    def calls(key_id: UUID, uid: str) -> JudgedCalls:
        venue = exchange.key_verification_calls(
            env, key_id, uid=uid, recv_window_ms=window, clock_offset_ms=offset_ms
        )
        return JudgedCalls(exchange, venue)

    relational = SqlAlchemyRelationalRepository(settings.pg_dsn.get_secret_value(), "key-selfcheck")
    selfcheck = KeySelfCheck(
        SqlAlchemyKeySelfCheckStore(relational, env=env),
        calls,
        gate=ctx.oms_read_only_gate,
        audit=audit,
        policy=VerificationPolicy(egress_ip=settings.egress_ip, recv_window_ms=window),
        env=env,
        clock=lambda: datetime.now(UTC),
        metrics=metrics,
        interval_s=settings.selfcheck_interval_s,
    )
    ctx.accounts.attach_key_selfcheck(selfcheck, release=relational.dispose)
    return selfcheck
