"""Composition-root wiring (not a module) for the wallet reconciler's REST read (E27, #5282).

M13's reconciler reads an account's wallet through `WalletRestPort.wallet(account_id)`; M4 reads it
signed (`BybitTradingPort.wallet(AccountRef)`). This glue binds them, as `exposure_wiring.py` binds
the exposure read, and neither module imports the other (C-3.1, C-3.2).

- The `AccountRef` of an account is its `exchange_uid` and its active key id, kept from the
  tracking pass's usable-key rows (`observe`): no read of its own. A ref that lags a rotation by up
  to one tracking pass (15 s) is signed with a key the venue may refuse: the exchange answers 10003,
  which the probe vocabulary names `auth_error`, so it fails closed as `WalletUnavailable` (not
  `KeyRefused`), and the next pass picks the new ref. An account with no ref (not tracked, or no
  active key) is `WalletUnavailable`. This file touches no key material: the port asks M2 to sign
  (C-3.2), and the log carries the error's type only (C-12.6).
- Each read builds its own port from the adapter, bound to the process environment (C-2.11), and
  reads on its `poll` lane through the account-reads budget, never the reserve that stops and
  cancels draw on (C-12.7). The port is closed when the read ends, cancelled or not, within
  `CLOSE_BOUND_S`.
- The port strips every failure of its cause, so its hook names each one first
  (`exposure_probe_error`, the `KeyProbeError` vocabulary). `unknown_key`, `ip_not_allowed`,
  `permission_denied` and `key_expired` are `Refusal` values of the same name: `KeyRefused`, but
  today's `probe_error` produces only the words that match (`unknown_key` and `key_expired` never
  occur: 10003 is `auth_error`, 33004 `exchange_unknown`). Anything else, including a port that
  cannot be built (testnet, no credentials wired), is `WalletUnavailable`: sizing then goes off
  once the snapshot is stale, so every such outcome fails closed.
- The reply is the exchange's `Wallet`, read as the private stream's is (`oms/stream_consumer.py`):
  USDT only, a time more than `MAX_FUTURE_SKEW` ahead refused (it would block every later refresh),
  a figure that fails validation refused by its error type alone (balances are Confidential).

Only the real backend binds it; the fake backend (dev/CI) keeps `UnavailableWalletRest` (C-13.5).
Nothing here does I/O until a read is asked for.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterable
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Final, Protocol
from uuid import UUID

import structlog
from pydantic import ValidationError

from candleviewer.accounts.health import Clock, SystemClock
from candleviewer.accounts.verification import KeyRefused, Refusal
from candleviewer.accounts.wallet import WalletSnapshot, WalletUnavailable
from candleviewer.domain.primitives import AccountId
from candleviewer.exchange.base.errors import ExchangeError
from candleviewer.exchange.base.models import AccountRef, Wallet
from candleviewer.observability import spawn
from candleviewer.storage.repositories.accounts import SelfCheckTargetRow
from candleviewer.storage.repositories.positions import MAX_FUTURE_SKEW

if TYPE_CHECKING:
    from candleviewer.app import AppContext

__all__ = ["CLOSE_BOUND_S", "AccountRefs", "ExchangeWalletRest", "wire_wallet_rest"]

#: The bound on closing one read's port (its client, never the shared transport).
CLOSE_BOUND_S: Final = 0.1
#: The one asset this product reads (C-1.3).
_COIN: Final = "USDT"
#: The `KeyProbeError` words that are verdicts about the key: `Refusal`'s values, same names.
_REFUSALS: Final = frozenset(r.value for r in Refusal)
_EPOCH: Final = datetime(1970, 1, 1, tzinfo=UTC)


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


class WalletReadPort(Protocol):
    """The trading port's calls this file uses."""

    async def wallet(self, account: AccountRef) -> Wallet: ...
    async def aclose(self) -> None: ...


class WalletVenue(Protocol):
    """The adapter surface the read uses (`AppContext.exchange_bybit`)."""

    def exposure_port(
        self,
        env: str,
        *,
        on_failure: Callable[[Exception], None],
        clock_offset_ms: Callable[[], int | None] | None = None,
    ) -> WalletReadPort: ...

    def exposure_probe_error(self, error: Exception) -> str | None: ...


class AccountRefs:
    """Each tracked account's `exchange_uid` and active key id, as of the last tracking pass."""

    def __init__(self) -> None:
        self._refs: dict[UUID, tuple[str, UUID]] = {}

    def observe(self, rows: Iterable[SelfCheckTargetRow]) -> None:
        """Replace the refs with those of `rows`' active keys (a rotating key is the old key's
        successor-to-be, never the one the account signs with). Synchronous: a pass publishes whole.

        When a tracking pass fails `observe` is not called and the refs stay as last observed. That
        is acceptable: the read is read-only, and the key standing refuses every account after a
        minute without a good repository read.
        """
        refs: dict[UUID, tuple[str, UUID]] = {}
        for row in rows:
            if row.status == "active":
                refs[row.account.id] = (row.account.exchange_uid, row.key_id)
        self._refs = refs

    def get(self, account_id: UUID) -> tuple[str, UUID] | None:
        return self._refs.get(account_id)


class ExchangeWalletRest:
    """`WalletRestPort` over the adapter: one fresh port per read, on the process environment."""

    def __init__(
        self,
        venue: WalletVenue,
        env: str,
        clock_offset_ms: Callable[[], int | None],
        refs: AccountRefs | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._venue, self._env, self._offset = venue, env, clock_offset_ms
        self.refs = refs or AccountRefs()
        self._clock = clock or SystemClock()
        self._closing: set[asyncio.Task[None]] = set()

    def observe(self, rows: Iterable[SelfCheckTargetRow]) -> None:
        """The tracking pass's usable-key rows of this environment (C-2.11)."""
        self.refs.observe(row for row in rows if row.account.env == self._env)

    async def wallet(self, account_id: UUID) -> WalletSnapshot:
        ref = self.refs.get(account_id)
        if ref is None:
            raise WalletUnavailable("no active key is known for the account")
        uid, key_id = ref
        named: list[str] = []

        def hook(raw: Exception) -> None:
            """The port's `on_failure`: name the raw failure while its cause is intact."""
            word = self._venue.exposure_probe_error(raw)
            if word is not None:
                named.append(word)

        port: WalletReadPort | None = None
        try:
            account = AccountRef.model_validate(
                {
                    "account_id": AccountId(account_id),
                    "uid": uid,
                    "environment": self._env,
                    "key_ref": str(key_id),
                }
            )
            port = self._venue.exposure_port(
                self._env, on_failure=hook, clock_offset_ms=self._offset
            )
            wallet = await port.wallet(account)
        except ExchangeError as error:
            word = named[-1] if named else self._venue.exposure_probe_error(error)
            if word in _REFUSALS:
                raise KeyRefused(Refusal(word), error.exchange_ret_code) from None
            _log().info("wallet_rest_failed", account_id=str(account_id), probe_error=word)
            raise WalletUnavailable("the exchange gave no wallet") from None
        except Exception as fault:  # the type only: a message may echo exchange text (C-12.6)
            _log().info(
                "wallet_rest_failed", account_id=str(account_id), fault=type(fault).__name__
            )
            raise WalletUnavailable("the wallet read failed") from None
        finally:
            if port is not None:
                await self._close(port, account_id)
        return self._snapshot(account_id, wallet)

    async def _close(self, port: WalletReadPort, account_id: UUID) -> None:
        """Close the read's port, also while the read is being cancelled: shielded and bounded; a
        cancel is never swallowed, any other close fault is only logged. The task is held in
        `_closing` so none is collected mid-way; each is bounded by `CLOSE_BOUND_S`."""
        closing = spawn(_close_one(port, account_id), name=f"wallet-rest-close-{account_id}")
        self._closing.add(closing)
        closing.add_done_callback(self._closing.discard)
        await asyncio.shield(closing)

    def _snapshot(self, account_id: UUID, w: Wallet) -> WalletSnapshot:
        stamp = _EPOCH + timedelta(microseconds=w.updated_at)
        if stamp > self._clock.now() + MAX_FUTURE_SKEW:  # it would block every refresh
            _log().warning("wallet_rest_ahead", account_id=str(account_id))
            raise WalletUnavailable("the wallet is dated ahead of the clock")
        if w.coin != _COIN:
            raise WalletUnavailable("the wallet is not USDT")
        try:
            return WalletSnapshot(
                coin="USDT", equity=w.equity, wallet_balance=w.wallet_balance,
                available_balance=w.available_margin, unrealised_pnl=w.unrealised_pnl,
                account_im_rate=w.account_im_rate, account_mm_rate=w.account_mm_rate,
                updated_at=stamp,
            )  # fmt: skip
        except ValidationError as exc:  # its type only: balances are Confidential (C-12.6)
            _log().warning(
                "wallet_rest_invalid", account_id=str(account_id), kind=type(exc).__name__
            )
            raise WalletUnavailable("the wallet figures are invalid") from None


async def _close_one(port: WalletReadPort, account_id: UUID) -> None:
    try:
        async with asyncio.timeout(CLOSE_BOUND_S):
            await port.aclose()
    except TimeoutError:
        _log().warning("wallet_rest_close_slow", account_id=str(account_id))
    except Exception as fault:  # the read's result or cancel stands; the type name only
        _log().warning(
            "wallet_rest_close_failed", account_id=str(account_id), fault=type(fault).__name__
        )


def wire_wallet_rest(ctx: AppContext) -> ExchangeWalletRest | None:
    """The wallet REST read on the real backend, on the process environment; `None` on the fake
    one, which keeps the stand-in (C-13.5). Requests carry the exchange's clock once the ingestion
    clock guard has measured it."""
    settings = ctx.settings
    if settings.storage_backend != "real":
        return None

    def offset_ms() -> int | None:
        return ctx.ingestion.clock_offset_ms()

    venue: WalletVenue = ctx.exchange_bybit
    return ExchangeWalletRest(venue, settings.environment.value, offset_ms)
