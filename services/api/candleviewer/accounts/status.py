"""The `ExchangeAccount` read model of an account's connection and wallet (E27-T04, #837).

`AccountStatusReader.status()` builds the five fields of REST `ExchangeAccount`
(22-api-openapi.yaml) that the health monitor and the wallet cache own: `connection_state`,
`health`, `balance`, `balance_stale` and `balance_stale_since`. The routes that will serve them,
`listExchangeAccounts` and `getExchangeAccount` (#895, #899), merge them into the account's row
under `accounts:read` and the caller's granted scope (C-12.4); this module mounts nothing. The
`wallet` WS topic serves the same status.

Derived from the two views on every read (no I/O, O(1)), so a lapse shows without waiting for a
tick:
- `connection_state`: `disabled` for an account the owner disabled (the row's `enabled`), else its
  health state's (`connected`, `degraded`, `disconnected`; decision Q2 on #837), else `pending`
  while this process does not monitor it (no signable key yet, or another environment's account).
- `health`: the monitor's view, `None` until the account is monitored.
- `balance`, `balance_stale`, `balance_stale_since`: the wallet cache's view, whose 10 s window is
  for display (risk-based sizing reads its own flag, `wallet.py`). `balance` is `None` until a
  first snapshot, and an account that is not monitored is never stale.
- Amounts stay `Decimal` in the model. In JSON they are plain digit strings, never an exponent:
  the `Decimal` pattern of both contracts refuses `1E-7`, which `str()` of a `Decimal` can give.
  One whose exponent is out of range (`wallet.AMOUNT_MAX_EXPONENT`) is refused, not expanded.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Final, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_serializer

from candleviewer.accounts.health import CONNECTION_STATE, AccountHealth, ConnectionState
from candleviewer.accounts.models import OptUtcDatetime
from candleviewer.accounts.wallet import WalletSnapshot, WalletView, bounded_amount

#: The amounts of a `WalletSnapshot`, as REST `WalletBalance` and WS `wallet` name them.
AMOUNTS: Final = (
    "equity",
    "wallet_balance",
    "available_balance",
    "unrealised_pnl",
    "account_im_rate",
    "account_mm_rate",
)


def plain_decimal(value: Decimal) -> str:
    """An amount on the wire: plain digits, never an exponent and never `-0`. One whose exponent is
    out of range (`WalletSnapshot` refuses it at the boundary) is refused, not expanded (C-2.17)."""
    bounded_amount(value)
    return format(value if value else value.copy_abs(), "f")


class HealthViews(Protocol):
    """`AccountHealthMonitor.view`: an account's health, `None` if it is not monitored."""

    def view(self, account_id: UUID) -> AccountHealth | None: ...


class WalletViews(Protocol):
    """`WalletCache.view`: an account's wallet snapshot and staleness, `None` if not tracked."""

    def view(self, account_id: UUID) -> WalletView | None: ...


class AccountStatus(BaseModel):
    """The five `ExchangeAccount` fields of one account, as of the read."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    connection_state: ConnectionState
    health: AccountHealth | None
    balance: WalletSnapshot | None
    balance_stale: bool
    balance_stale_since: OptUtcDatetime

    @field_serializer("balance", when_used="json")
    def _plain_amounts(self, balance: WalletSnapshot | None) -> dict[str, Any] | None:
        if balance is None:
            return None
        wire: dict[str, Any] = balance.model_dump(mode="json")
        return wire | {name: plain_decimal(getattr(balance, name)) for name in AMOUNTS}


class AccountStatusReader:
    """Reads an account's status from the monitor and the wallet cache, the ones the account health
    runtime holds (`monitor`, `wallets`)."""

    def __init__(self, health: HealthViews, wallets: WalletViews) -> None:
        self._health, self._wallets = health, wallets

    def status(self, account_id: UUID, *, enabled: bool = True) -> AccountStatus:
        """`enabled`: the account row's flag, which the caller holds."""
        health = self._health.view(account_id)
        wallet = self._wallets.view(account_id)
        state: ConnectionState = "disabled" if not enabled else "pending"
        if enabled and health is not None:
            state = CONNECTION_STATE[health.state]
        return AccountStatus(
            connection_state=state,
            health=health,
            balance=None if wallet is None else wallet.snapshot,
            balance_stale=wallet is not None and wallet.stale,
            balance_stale_since=None if wallet is None else wallet.stale_since,
        )
