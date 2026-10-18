"""The `wallet` WS topic: account health and balances (E27-T04, #837; 23-ws-protocol.md §6.2, §8.2,
§15.4). The accounts module's `ws/sequencing.py::SnapshotSource` for the family, and the deltas the
account health runtime publishes on it.

Adapters live in their owning module and the gateway only wires them (#1778 Q2). The accounts
module may not import `ws` (CONSTITUTION §3), so the protocol is met structurally, as the book's
is: `sub` is typed by the field read here, and the gateway's body constructor and its hub's
`publish` are injected (`ws_wiring.wallet_topic`). The runtime attaches its monitor and wallet
cache, and every item is read through the `ExchangeAccount` read model when it is sent, so `stale`
and `stale_since_ms` are REST `balance_stale` and `balance_stale_since`.

- Snapshot: the health of every monitored account of the subscription and the balance of each one
  that has a wallet snapshot, in account order. `sub.accounts` is the gateway's narrowing of the
  request to the caller's grants, at `sub` and on every grant change (§6.2, §9.5); no other
  account is read. Private: never cached (generation 0), and every `snapshot: false` attach is
  forced (§7.6), since no delta history is kept.
- Deltas name their account to the hub (`publish(account=)`), which delivers each only to the
  subscriptions holding that account whose principal holds `accounts:read` (C-12.4): an account's
  health entry with an empty `balances` when its monitoring starts and on each state transition, a
  discrete event to announce, never one per tick; its balance item on each refresh, and once more
  when a balance sent fresh turns stale, so a client's `stale` does not stay `false` past it.
- A delta that fails is logged by its error type, never its message, at most once per
  `LOG_INTERVAL_S` (the lines held back are counted on the next), and goes no further: the topic is
  a view, and neither the evidence calls nor the runtime's loops wait on it or see it fail. A
  failed send is not forgotten: the turn to stale that it carried is sent again by the next tick.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from typing import Any, Final, Protocol
from uuid import UUID

import structlog

from candleviewer.accounts.health import epoch_ms
from candleviewer.accounts.status import (
    AMOUNTS,
    AccountStatus,
    AccountStatusReader,
    HealthViews,
    WalletViews,
    plain_decimal,
)
from candleviewer.accounts.wallet import WalletSnapshot

#: Private topics are flat, scoped by their `exchange_account_ids` option (§6.2).
WALLET: Final = "wallet"
#: A failed delta is logged at most once in this many seconds, the ones held back counted on the
#: next line: a view that keeps failing, at every tick for every account, never floods the log.
LOG_INTERVAL_S: Final = 60.0


class WalletSub(Protocol):
    """The field of a WS `Subscription` read here: its accounts, narrowed to the caller's grants."""

    @property
    def accounts(self) -> frozenset[UUID]: ...


class Publish(Protocol):
    """`SequencingHub.publish`: one delta to every subscription of `ch` in `account`'s scope."""

    def __call__(self, ch: str, body: Mapping[str, Any], *, account: UUID) -> int: ...


class BodyFactory[B](Protocol):
    """The gateway's snapshot body from a §15.4 payload."""

    def __call__(self, structured: Mapping[str, Any]) -> B: ...


def balance_item(account: UUID, balance: WalletSnapshot, status: AccountStatus) -> dict[str, Any]:
    """One §15.4 `balances` item: plain digit amounts, and the status's staleness."""
    since = status.balance_stale_since
    item: dict[str, Any] = {"exchange_account_id": str(account), "coin": balance.coin}
    item |= {name: plain_decimal(getattr(balance, name)) for name in AMOUNTS}
    item |= {"stale": status.balance_stale}
    item["stale_since_ms"] = None if since is None else epoch_ms(since)
    return item | {"updated_at_ms": epoch_ms(balance.updated_at)}


class WalletTopic[B]:
    """The `wallet` topic's snapshot source and publisher (see the module docstring), for the event
    loop that runs the gateway and the account health runtime: no locks."""

    def __init__(
        self, publish: Publish, body: BodyFactory[B], *, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._publish, self._body, self._clock = publish, body, clock
        self._reader: AccountStatusReader | None = None
        self._fresh: set[UUID] = set()  # accounts whose last balance item went out not stale
        self._log_from = 0.0  # `_contained`: the clock reading from which a failure is logged again
        self._held = 0  # and how many it held back since its last line

    def attach(self, health: HealthViews, wallets: WalletViews) -> None:
        """Serve these views, the account health runtime's, once (`wire_account_health`). Before,
        `build` gives `None`, so a subscription stays `snapshot_pending` (§7.7)."""
        if self._reader is not None:
            raise ValueError("the wallet topic is already attached")
        self._reader = AccountStatusReader(health, wallets)

    # -- SnapshotSource

    def build(self, sub: WalletSub) -> B | None:
        if self._reader is None:
            return None
        balances: list[dict[str, Any]] = []
        health: list[dict[str, object]] = []
        for account_id in sorted(sub.accounts):
            status = self._reader.status(account_id)
            if status.health is not None:
                health.append(status.health.ws_entry(account_id))
            if status.balance is not None:
                balances.append(balance_item(account_id, status.balance, status))
        return self._body({"balances": balances, "health": health})

    def generation(self, sub: WalletSub) -> int:
        return 0  # a private family's snapshot is never cached (SR-190)

    def continuity(self, sub: WalletSub, from_ts_ms: int | None) -> bool:
        return False  # no delta history: `snapshot: false` is always `snapshot_forced`

    # -- deltas, which the account health runtime sends

    def health_changed(self, account_id: UUID) -> None:
        """The account's monitoring started, or its state moved: its health entry, alone."""
        with self._contained():
            status = self._status(account_id)
            if status is not None and status.health is not None:
                entry = status.health.ws_entry(account_id)
                self._publish(WALLET, {"balances": [], "health": [entry]}, account=account_id)

    def balance_refreshed(self, account_id: UUID) -> None:
        """The account's wallet snapshot was refreshed: its balance item, alone."""
        with self._contained():
            status = self._status(account_id)
            if status is not None and status.balance is not None:
                self._send_balance(account_id, status.balance, status)

    def stale_check(self) -> None:
        """Send each balance that went out fresh once more when it turns stale; the runtime's tick
        calls this, so a send that failed is tried again by the next. An account that is no longer
        tracked is forgotten."""
        for account_id in sorted(self._fresh):
            with self._contained():
                status = self._status(account_id)
                if status is None or status.balance is None:
                    self._fresh.discard(account_id)
                elif status.balance_stale:
                    self._send_balance(account_id, status.balance, status)

    def _status(self, account_id: UUID) -> AccountStatus | None:
        return None if self._reader is None else self._reader.status(account_id)

    def _send_balance(self, account: UUID, balance: WalletSnapshot, status: AccountStatus) -> None:
        """One balance item. A fresh one is recorded before it goes out, so that a send that fails
        still owes its turn to stale; a stale one is forgotten after, so that a send that fails is
        owed again (`stale_check`)."""
        if not status.balance_stale:
            self._fresh.add(account)
        item = balance_item(account, balance, status)
        self._publish(WALLET, {"balances": [item]}, account=account)
        if status.balance_stale:
            self._fresh.discard(account)

    @contextmanager
    def _contained(self) -> Iterator[None]:
        """A delta that fails stays here, logged by its error type (never its message, C-12.6) at
        most once per `LOG_INTERVAL_S`, with the count of those held back since the last line; a
        cancellation still propagates."""
        try:
            yield
        except Exception as exc:
            now = self._clock()
            if now < self._log_from:
                self._held += 1
                return
            held, self._held, self._log_from = self._held, 0, now + LOG_INTERVAL_S
            log = structlog.get_logger(__name__)
            log.error("wallet_topic.publish_failed", error=type(exc).__name__, suppressed=held)
