"""The account side of the composed order-entry gate (E27-T04; decision Q5 on #837).

Synchronous, O(1), no I/O (C-2.21): each answer reads in-memory state, never an interpreter or
the network, and health is derived from its evidence on every read, so no background task has to
run for a lapsed account to be refused. A down, policy-disabled or keyless account refuses new
orders; a stale or unknown wallet refuses risk-based sizing only (US-ACCT-008); key age never
refuses (US-ACCT-005). Every `detail` is fixed text, so nothing exchange-supplied reaches a body.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Literal, Protocol
from uuid import UUID

from candleviewer.accounts.health import HealthState

# TODO(#964): OrderEntryReason, OrderEntryRefusal and OrderEntryCheck are proposed to move to
# `candleviewer/domain/order_entry.py`, which every module may import, so that the composed gate
# of E42-T03 and this check share one definition. `candleviewer/api/order_entry_gate.py` cannot
# hold them: M13 may not import M23 (CONSTITUTION §3).

#: The gate's closed `reason` set (24-internal-schemas.md §8.4.1); `maintenance` is E42-T03's.
OrderEntryReason = Literal[
    "maintenance",
    "account_disabled_by_policy",
    "no_active_key",
    "account_unhealthy",
    "balance_stale",
]


@dataclass(frozen=True, slots=True)
class OrderEntryRefusal:
    reason: OrderEntryReason
    detail: str


class OrderEntryCheck(Protocol):
    def refusal(self, account_id: UUID) -> OrderEntryRefusal | None: ...


class DisabledReason(StrEnum):
    """Why the key verifier (E27-T03) took an account out of trading: a failed key-policy rule, or
    trading switched off for the account. A revoked, expired or invalid key is not a policy
    disable; the verifier reports it as no active key."""

    KEY_WITHDRAW_PERMISSION = "key_withdraw_permission"
    KEY_IP_WHITELIST_MISSING = "key_ip_whitelist_missing"
    KEY_IP_WHITELIST_MISMATCH = "key_ip_whitelist_mismatch"
    ACCOUNT_DISABLED = "account_disabled"


_POLICY_DETAIL: Final[Mapping[DisabledReason, str]] = {
    DisabledReason.KEY_WITHDRAW_PERMISSION: "The API key can withdraw or transfer funds.",
    DisabledReason.KEY_IP_WHITELIST_MISSING: "The API key has no IP whitelist.",
    DisabledReason.KEY_IP_WHITELIST_MISMATCH: "The API key's IP whitelist excludes this server.",
    DisabledReason.ACCOUNT_DISABLED: "Trading is switched off for this account.",
}
#: Answers a value outside `DisabledReason`, which a well-typed port never stores.
_POLICY_FALLBACK: Final = "Trading is disabled for this account by policy."


@dataclass(frozen=True, slots=True)
class KeyStanding:
    """What the key verifier (E27-T03, #836) last established for an account."""

    has_active_key: bool
    disabled_reason: DisabledReason | None = None


class KeyStandingPort(Protocol):
    """Verification port: an in-memory read of the verifier's last result; `None` is unknown and
    refuses. It holds only the codes above, never anything exchange-supplied (exchange error text,
    key ids, permission lists): the gate's answer reaches the 403 body seen by callers without
    `keys:read`."""

    def standing(self, account_id: UUID) -> KeyStanding | None: ...


class HealthStates(Protocol):
    def current(self, account_id: UUID) -> HealthState | None: ...


class SizingSource(Protocol):
    """Wallet freshness per account: `True` fresh, `False` stale, `None` unknown (no snapshot
    yet). Risk-based sizing calls `AccountHealthCheck.sizing_refusal` before it reads any balance
    figure; unknown refuses like stale."""

    def risk_sizing_available(self, account_id: UUID) -> bool | None: ...


class AccountHealthCheck:
    """`OrderEntryCheck` for one account's key standing, health and wallet freshness."""

    def __init__(self, health: HealthStates, keys: KeyStandingPort, wallets: SizingSource) -> None:
        self._health = health
        self._keys = keys
        self._wallets = wallets

    def refusal(self, account_id: UUID) -> OrderEntryRefusal | None:
        standing = self._keys.standing(account_id)
        if standing is not None and standing.disabled_reason is not None:
            detail = _POLICY_DETAIL.get(standing.disabled_reason, _POLICY_FALLBACK)
            return OrderEntryRefusal("account_disabled_by_policy", detail)
        if standing is None or not standing.has_active_key:
            return OrderEntryRefusal("no_active_key", "The account has no verified active key.")
        if self._health.current(account_id) in (None, HealthState.DOWN):
            return OrderEntryRefusal(
                "account_unhealthy", "Neither the private WS nor REST has succeeded recently."
            )
        return None

    def sizing_refusal(self, account_id: UUID) -> OrderEntryRefusal | None:
        """Risk-based sizing needs a trusted balance: only a fresh snapshot passes."""
        if self._wallets.risk_sizing_available(account_id) is True:
            return None
        return OrderEntryRefusal("balance_stale", "The wallet balance is stale or not loaded yet.")
