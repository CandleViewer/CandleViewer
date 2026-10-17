"""Wallet snapshot cache (E27-T04, US-ACCT-008).

One Decimal snapshot per tracked account. The private-WS `wallet` stream feeds it first, through
`WalletCache.apply`; a REST read only truth-checks it. The order gate's sizing flag reads
`risk_sizing_available` (`order_gate.SizingSource`); the read models read `view()`.

- Freshness is the age since the last refresh on the injected boot-time clock, never the exchange's
  `updated_at` or the wall clock, so a skewed exchange clock or a wall-clock step moves nothing.
  `balance_stale_since` is the last refresh plus the stale window, dated on the wall clock at that
  refresh. An account with no snapshot ages from when it is tracked and has unknown sizing.
- Snapshots are ordered by the exchange's `updated_at`: an older one never replaces a newer one or
  refreshes; one with the same time does both (a re-delivery, or a read confirming it).

Sizing follows the stale flag, as the ticket words it (a flag "consumed by risk-based sizing so
that it is disabled for a stale account"): unavailable from 10 s after the last refresh, not only
once a reconciliation has failed too (US-ACCT-008's "Stale data" scenario, `listExchangeAccounts`).
That fails closed. Three consequences show once the streams feed the cache (W2, W4):
- an account whose wallet stream is quiet (a flat one pushes only on change) reads stale, with
  sizing unavailable, for about 50 s of every 60 s, until the next truth-check;
- while the WS is down the read repeats every `CV_ACCOUNT_HEARTBEAT_S`, which is the stale window
  by default, so such an account shows stale for a moment at the end of each cycle (a poll below
  the stale window removes that);
- a tracked account with no snapshot waits a full reconcile window for its first figure while its
  WS is healthy, and `CV_ACCOUNT_HEARTBEAT_S` while it is down.
Sizing unavailable only after a failed reconciliation would need a "last attempt failed" input to
the flag: a contract decision, not one made here.

The cache is synchronous O(1) with no I/O (C-2.21), for one event loop.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from candleviewer.accounts.health import Clock
from candleviewer.accounts.models import UtcDatetime
from candleviewer.settings import (
    ACCOUNT_HEARTBEAT_MAX_S,
    WALLET_RECONCILE_S,
    WALLET_STALE_S,
    Settings,
)

#: A balance or rate: finite, and hidden from `repr()` (balances are Confidential, C-12.6).
Amount = Annotated[Decimal, Field(repr=False, allow_inf_nan=False)]


class WalletSnapshot(BaseModel):
    """One account's wallet as of the exchange's `updated_at` (22-api-openapi.yaml `WalletBalance`).
    Strict: `Decimal` amounts only, never a float, an int or a string. USDT only (C-1.3).

    A refusal's `str()` omits the figures it refused (`hide_input_in_errors`), but its `errors()`
    and `json()` still carry them: whoever builds a snapshot from an exchange frame logs only the
    type of a `ValidationError`, never the error itself (C-12.6, balances are Confidential)."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True, hide_input_in_errors=True)

    coin: Literal["USDT"]
    equity: Amount
    wallet_balance: Amount
    available_balance: Amount
    unrealised_pnl: Amount
    account_im_rate: Amount
    account_mm_rate: Amount
    updated_at: UtcDatetime


@dataclass(frozen=True, slots=True)
class WalletThresholds:
    """`CV_WALLET_STALE_S`: older than this is stale (`listExchangeAccounts`' display rule).
    `CV_WALLET_RECONCILE_S`: the REST read after this long without a refresh (US-ACCT-008's
    truth-check). `ws_down_poll_s` (`CV_ACCOUNT_HEARTBEAT_S`): the cadence while the private WS is
    down, never slower than `reconcile_s`. The first two must not be conflated.

    Neither of them may exceed its US-ACCT-008 default, which is also its cap: `WALLET_STALE_S` and
    `WALLET_RECONCILE_S`, written once in `settings`, where `Settings` bounds both fields by them.
    They are limits, not tuning room, and no flag may move them (C-4.14), so no caller can build a
    cache that holds an old snapshot fresh or truth-checks it later than the contract says."""

    stale_s: float = WALLET_STALE_S
    reconcile_s: float = WALLET_RECONCILE_S
    ws_down_poll_s: float = ACCOUNT_HEARTBEAT_MAX_S

    def __post_init__(self) -> None:
        windows = (self.stale_s, self.reconcile_s, self.ws_down_poll_s)
        if not all(math.isfinite(window) and window > 0 for window in windows):
            raise ValueError("wallet thresholds must be finite and greater than 0")
        if not self.stale_s < self.reconcile_s:
            raise ValueError("wallet thresholds need stale_s < reconcile_s")
        if self.stale_s > WALLET_STALE_S or self.reconcile_s > WALLET_RECONCILE_S:
            raise ValueError(
                f"wallet thresholds are capped at stale_s <= {WALLET_STALE_S:g} and "
                f"reconcile_s <= {WALLET_RECONCILE_S:g} (US-ACCT-008)"
            )

    @classmethod
    def from_settings(cls, settings: Settings) -> WalletThresholds:
        return cls(
            settings.wallet_stale_s, settings.wallet_reconcile_s, settings.account_heartbeat_s
        )


@dataclass(frozen=True, slots=True)
class WalletView:
    """REST `balance`, `balance_stale`, `balance_stale_since`; WS `stale`, `stale_since_ms`.
    `snapshot` is `None` until the first one arrives."""

    snapshot: WalletSnapshot | None
    stale: bool
    stale_since: datetime | None


@dataclass(slots=True)
class _Entry:
    refreshed: float  # monotonic: the last refresh, or when tracking began
    refreshed_at: datetime  # the same instant on the wall clock
    snapshot: WalletSnapshot | None = None


class WalletCache:
    """The latest snapshot per tracked account, and how fresh it is. A `WalletReconciler` follows
    its cache's `clock` and `thresholds`."""

    def __init__(self, clock: Clock, thresholds: WalletThresholds | None = None) -> None:
        self.clock = clock
        self.thresholds = thresholds or WalletThresholds()
        self._entries: dict[UUID, _Entry] = {}

    def track(self, account_id: UUID) -> None:
        if account_id not in self._entries:
            self._entries[account_id] = _Entry(self.clock.monotonic(), self.clock.now())

    def untrack(self, account_id: UUID) -> None:
        self._entries.pop(account_id, None)

    def apply(self, account_id: UUID, snapshot: WalletSnapshot) -> bool:
        """Take a snapshot from the WS stream or a REST read; `True` if it refreshed the cache. One
        for an untracked account, or older than the cached one, changes nothing."""
        entry = self._entries.get(account_id)
        held = None if entry is None else entry.snapshot
        if entry is None or (held is not None and snapshot.updated_at < held.updated_at):
            return False
        entry.snapshot, entry.refreshed = snapshot, self.clock.monotonic()
        entry.refreshed_at = self.clock.now()
        return True

    def view(self, account_id: UUID) -> WalletView | None:
        """Derived on every read, so a lapse shows without a tick; `None` if untracked."""
        entry = self._entries.get(account_id)
        if entry is None:
            return None
        stale = self._stale(entry)
        since = entry.refreshed_at + timedelta(seconds=self.thresholds.stale_s) if stale else None
        return WalletView(entry.snapshot, stale, since)

    def risk_sizing_available(self, account_id: UUID) -> bool | None:
        """`order_gate.SizingSource`: `True` fresh, `False` stale, `None` (unknown) for no
        snapshot yet or an untracked account."""
        entry = self._entries.get(account_id)
        if entry is None or entry.snapshot is None:
            return None
        return not self._stale(entry)

    def silence_s(self) -> dict[UUID, float]:
        """Seconds since each tracked account's last refresh, or since tracking began."""
        now = self.clock.monotonic()
        return {account_id: now - entry.refreshed for account_id, entry in self._entries.items()}

    def _stale(self, entry: _Entry) -> bool:
        """Older than the window: exactly 10 s old is not yet older than 10 s."""
        return self.clock.monotonic() - entry.refreshed > self.thresholds.stale_s
