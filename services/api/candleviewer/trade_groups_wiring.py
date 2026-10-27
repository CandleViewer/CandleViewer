"""Composition-root wiring (not a module) of trade-group readiness (E28-T05 S2a, #909). Nothing
mounts it until S2b's definition reads.

`GateReadiness` is the `ReadinessSource` over what refuses an order, read as the OMS reads it (24
Sec.8.4, 8.10): in-memory reads only (C-2.21). It fails closed, and the first reason wins: no gate
composed (the fake backend), the account row switched off, the order-entry gate's refusal (only its
reason is read, never its `detail`; a reason the table does not hold is `trading_disabled`), the
B18 kill switch, the live gate for a live account (the `CV_TRADING_LIVE_ENABLED` setting and the
`trading.live_enabled` flag, read for a live account alone; only demo and testnet are not live),
then a lockout.

`NoLockouts` stands in for the lockout source until E39-S02. `GateReadiness.announce` says so at
startup, as the OMS does for its interims (a WARNING; no gauge, for `oms_interim_ports` is the
OMS's closed set).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import ClassVar, Final, Protocol
from uuid import UUID

import structlog

from candleviewer.accounts.trade_group_readiness import ReadinessReason
from candleviewer.domain.order_entry import OrderEntryCheck, RefusalReason
from candleviewer.domain.primitives import AccountId, Environment

#: The environments whose orders meet no live precondition, as the OMS's switches read it
#: (`oms_wiring`): any other value is live's, so an unknown one fails closed.
_NOT_LIVE: Final = frozenset({"demo", "testnet"})
#: What each refusal of the gate reads as; a reason E27 adds must be decided here.
GATE_REASONS: Final[Mapping[RefusalReason, ReadinessReason]] = {
    "no_active_key": "key_invalid",
    "account_disabled_by_policy": "account_disabled",
    "account_unhealthy": "account_unhealthy",
    "maintenance": "trading_disabled",
}


class LockoutSource(Protocol):
    """Whether the account is locked out (E39-S02); a source that cannot tell raises."""

    def locked(self, account_id: UUID) -> bool: ...


class NoLockouts:
    """`LockoutSource` until E39-S02: no engine exists, so no lockout is ever reported."""

    port: ClassVar = "risk_lockouts"
    replaced_by: ClassVar = "E39-S02"
    serves: ClassVar = "no lockout is read: no account reads account_locked"

    def locked(self, account_id: UUID) -> bool:
        return False


class GateReadiness:
    """`ReadinessSource` over the gate (`None`: none composed), the kill switch (the `refusal` the
    OMS asks of its `KillSwitch`: a refusal, or `None`), the live gate (the setting and the flag's
    view) and the lockouts (module docstring)."""

    def __init__(
        self,
        gate: OrderEntryCheck | None,
        *,
        kill_switch: Callable[[AccountId], object | None],
        live_enabled: bool,
        live_flag: Callable[[], bool],
        lockouts: LockoutSource,
    ) -> None:
        self._gate, self._kill_switch, self._lockouts = gate, kill_switch, lockouts
        self._live_enabled, self._live_flag = live_enabled, live_flag

    def reason(
        self, account_id: UUID, environment: Environment, *, account_enabled: bool
    ) -> ReadinessReason | None:
        if self._gate is None:
            return "trading_disabled"
        if account_enabled is not True:
            return "account_disabled"
        refusal = self._gate.refusal(account_id)
        if refusal is not None:
            return GATE_REASONS.get(refusal.reason, "trading_disabled")
        if self._kill_switch(AccountId(account_id)) is not None:
            return "kill_switch_engaged"
        live = environment not in _NOT_LIVE  # the flag is read for a live account alone
        if live and not (self._live_enabled is True and self._live_flag() is True):
            return "trading_disabled"
        if self._lockouts.locked(account_id) is not False:
            return "account_locked"
        return None

    def announce(self) -> bool:
        """At startup: a WARNING while `NoLockouts` serves; returns whether it does."""
        interim = isinstance(self._lockouts, NoLockouts)
        if interim:
            structlog.get_logger(__name__).warning(
                "trade_groups_interim_port",
                port=NoLockouts.port,
                replaced_by=NoLockouts.replaced_by,
                serves=NoLockouts.serves,
            )
        return interim
