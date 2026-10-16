"""The account side of the composed order-entry gate (E27-T04; decision Q5 on #837).

Synchronous, O(1), no I/O (C-2.21): each answer reads a value already published in memory, never
an interpreter or the network. A down, policy-disabled or keyless account refuses new orders; a
stale wallet refuses risk-based sizing only (US-ACCT-008); key age never refuses (US-ACCT-005).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from candleviewer.accounts.health import HealthState

# TODO(#964): OrderEntryRefusal and OrderEntryCheck move to the shared composed gate
# (`candleviewer/api/order_entry_gate.py`, E42-T03). M13 may not import M23 (CONSTITUTION §3),
# so the shared types must live where both modules can import them.


@dataclass(frozen=True, slots=True)
class OrderEntryRefusal:
    reason: str
    detail: str


class OrderEntryCheck(Protocol):
    def refusal(self, account_id: UUID) -> OrderEntryRefusal | None: ...


@dataclass(frozen=True, slots=True)
class KeyStanding:
    """What the key verifier (E27-T03, #836) last established for an account."""

    has_active_key: bool
    disabled_reason: str | None = None


class KeyStandingPort(Protocol):
    """Verification port: an in-memory read of the verifier's last result; `None` is unknown."""

    def standing(self, account_id: UUID) -> KeyStanding | None: ...


class HealthStates(Protocol):
    def state(self, account_id: UUID) -> HealthState | None: ...


class SizingSource(Protocol):
    def risk_sizing_available(self, account_id: UUID) -> bool: ...


class AccountHealthCheck:
    """`OrderEntryCheck` for one account's health, key standing and wallet freshness."""

    def __init__(self, health: HealthStates, keys: KeyStandingPort, wallets: SizingSource) -> None:
        self._health = health
        self._keys = keys
        self._wallets = wallets

    def refusal(self, account_id: UUID) -> OrderEntryRefusal | None:
        standing = self._keys.standing(account_id)
        if standing is not None and standing.disabled_reason is not None:
            return OrderEntryRefusal("account_disabled_by_policy", standing.disabled_reason)
        if standing is None or not standing.has_active_key:
            return OrderEntryRefusal("no_active_key", "The account has no verified active key.")
        if self._health.state(account_id) in (None, HealthState.DOWN):
            return OrderEntryRefusal(
                "account_unhealthy", "Neither the private WS nor REST has succeeded recently."
            )
        return None

    def sizing_refusal(self, account_id: UUID) -> OrderEntryRefusal | None:
        """Risk-based sizing needs a trusted balance; other sizing modes do not ask."""
        if self._wallets.risk_sizing_available(account_id):
            return None
        return OrderEntryRefusal("balance_stale", "The wallet snapshot is stale.")
