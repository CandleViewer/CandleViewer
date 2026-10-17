"""The account side of the composed order-entry gate (E27-T04; decision Q5 on #837).

`AccountHealthCheck` is an `OrderEntryCheck` of the shared kernel `candleviewer.domain.order_entry`:
the composition root builds it into `OrderEntryGate(maintenance, ...)` after the maintenance check.
Synchronous, O(1), no I/O (C-2.21): each answer reads in-memory state, never an interpreter or the
network, and health is derived from its evidence on every read, so no background task has to run
for a lapsed account to be refused. A down, policy-disabled or keyless account refuses new orders;
key age never refuses (US-ACCT-005). A wallet that is unknown, stale with its last reconciliation
failed, or not refreshed for a reconciliation period, is not an order-entry refusal: it makes
risk-based sizing unavailable for the account (US-ACCT-008), the flag `risk_sizing_available`
answers; the 10 s stale flag alone does not (ruling on #837). Each reason has one fixed `detail`
(24-internal-schemas.md §8.4.1): the 403 also reaches callers without `keys:read`, so it never
carries exchange-supplied text or names the key-policy rule that failed.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Final, Protocol
from uuid import UUID

from candleviewer.accounts.health import HealthState
from candleviewer.domain.order_entry import OrderEntryCheck, OrderEntryRefusal


class DisabledReason(StrEnum):
    """Why the key verifier (E27-T03) took an account out of trading: a failed key-policy rule, or
    trading switched off for the account. A revoked, expired or invalid key is not a policy
    disable; the verifier reports it as no active key."""

    KEY_WITHDRAW_PERMISSION = "key_withdraw_permission"
    KEY_PERMISSION_NOT_ALLOWED = "key_permission_not_allowed"
    KEY_NOT_READ_ONLY = "key_not_read_only"
    KEY_IP_WHITELIST_MISSING = "key_ip_whitelist_missing"
    KEY_IP_WHITELIST_MISMATCH = "key_ip_whitelist_mismatch"
    ACCOUNT_DISABLED = "account_disabled"


#: One detail for every policy disable, whatever the `DisabledReason`: which key-policy rule failed
#: is `keys:read` information, shown on the key-health screen, never in the 403.
_POLICY_DETAIL: Final = "Trading is disabled for this account by policy."
#: The only health states that admit an order, an allow-list: an unmonitored account (`None`), a
#: state added later and a value outside the contract all refuse (KV-T12: health is never asserted
#: optimistically; C-2.21).
_ADMITTING: Final = (HealthState.HEALTHY, HealthState.DEGRADED)


@dataclass(frozen=True, slots=True)
class KeyStanding:
    """What the key verifier (E27-T03, #836) last established for an account."""

    has_active_key: bool
    disabled_reason: DisabledReason | None = None


class KeyStandingPort(Protocol):
    """Verification port: an in-memory read of the verifier's last result; `None` is unknown and
    refuses. It holds only the codes above, never anything exchange-supplied (exchange error text,
    key ids, permission lists)."""

    def standing(self, account_id: UUID) -> KeyStanding | None: ...


class HealthStates(Protocol):
    def current(self, account_id: UUID) -> HealthState | None: ...


class SizingSource(Protocol):
    """Whether risk-based sizing may use each account's balance: `True` it may, `False` it may not
    (the snapshot is stale after a failed reconciliation, or older than one reconciliation period),
    `None` unknown (no snapshot yet)."""

    def risk_sizing_available(self, account_id: UUID) -> bool | None: ...


class AccountHealthCheck:
    """`OrderEntryCheck` for one account's key standing and health, and the sizing flag for its
    wallet freshness. It admits an order only for a verified active key (exactly `True`) and a
    `healthy` or `degraded` account; every other answer refuses."""

    def __init__(self, health: HealthStates, keys: KeyStandingPort, wallets: SizingSource) -> None:
        self._health = health
        self._keys = keys
        self._wallets = wallets

    def refusal(self, account_id: UUID) -> OrderEntryRefusal | None:
        standing = self._keys.standing(account_id)
        if standing is not None and standing.disabled_reason is not None:
            return OrderEntryRefusal("account_disabled_by_policy", _POLICY_DETAIL)
        if standing is None or standing.has_active_key is not True:
            return OrderEntryRefusal("no_active_key", "The account has no verified active key.")
        if self._health.current(account_id) not in _ADMITTING:
            return OrderEntryRefusal(
                "account_unhealthy", "Neither the private WS nor REST has succeeded recently."
            )
        return None

    def risk_sizing_available(self, account_id: UUID) -> bool:
        """Risk-based sizing reads this before any balance figure: only an answer of exactly `True`
        lets it use one, so a snapshot that is stale after a failed reconciliation or older than one
        period, and a missing one, answer `False` (US-ACCT-008)."""
        return self._wallets.risk_sizing_available(account_id) is True


if TYPE_CHECKING:  # CI's `mypy --strict candleviewer` proves the check fills a kernel gate slot

    def _fills_a_gate_slot(check: AccountHealthCheck) -> OrderEntryCheck:
        return check
