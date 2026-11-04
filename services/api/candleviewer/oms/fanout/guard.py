"""E28-T04's leg-guard hook for the trade-group planner (E28-T05 S3a2, #909).

`LegGuard` is the port: a sized, ready leg's refusal, read from memory (C-2.21), in 22's
`TradeGroupPreview.legs[].rejection.code` (S0, `RejectionCode`). `S4SGuard` binds it to what #913
S4-S serves the order path: `max_mkt_order_qty` for a market leg (the comparator leaves it to its
caller, #2635), the OMS's `TradingSwitches` and fence, and its `RiskGate`, which is
`InterimRiskGate` today (demo admitted unevaluated, any other environment `risk_state_unavailable`).
A port that raises refuses the leg, logged by account and error class alone (C-12.6); a leg whose
effect opens a position (any but `REDUCE`; the planner's legs are entries) is counted fail-closed
too (`fail_closed`, `cv_risk_guard_fail_closed_total`, E28-T04 BQ-8(a)). The guard cannot tell the
preview from E34's submit (both run the planner, so what is previewed is sent), so a preview's
refused leg counts as well: the port that raised would refuse that leg's entry on the submit. The
counter call never raises out of `refusal` (`LegGuard` must not raise). When #954 lands, only the
composition root's binding changes.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import suppress
from typing import Final, Literal, Protocol, cast, get_args

import structlog

from candleviewer.accounts.profiles import AccountProfile
from candleviewer.domain.events import Instrument
from candleviewer.oms import ports
from candleviewer.oms.errors import OmsNotReady
from candleviewer.risk.models import RiskRefusal

#: 22 `TradeGroupPreview.legs[].rejection.code` (S0), closed; `rate_budget_exhausted` is E34's.
RejectionCode = Literal[
    "cap_breached", "symbol_not_allowed", "insufficient_margin", "rate_budget_exhausted",
    "account_locked", "key_invalid", "leverage_unavailable", "kill_switch_engaged",
    "profile_disabled", "symbol_denied", "below_min_notional", "skipped", "no_reference_price",
    "invalid_stop_distance", "figure_unknown", "stop_beyond_liquidation", "account_disabled",
    "account_unhealthy", "trading_disabled", "risk_state_unavailable",
]  # fmt: skip
_CODES: Final = frozenset(get_args(RejectionCode))


def rejection_code(value: object, fallback: RejectionCode) -> RejectionCode:
    """`value` as 22's code; a value outside the set (`member_disabled`) fails closed to
    `fallback`."""
    return cast(RejectionCode, str(value)) if value in _CODES else fallback


class LegGuard(Protocol):
    """E28-T04's hook (#908, which rebinds it): a sized, ready leg's refusal, or `None`, from
    memory (C-2.21). It must not raise; an implementation fails closed, with a refusal."""

    def refusal(
        self, order: ports.SizedOrder, *, profile: AccountProfile, instrument: Instrument
    ) -> RejectionCode | None: ...


class S4SGuard:
    """`LegGuard` over #913 S4-S's order path (module docstring)."""

    def __init__(
        self,
        risk_gate: ports.RiskGate,
        switches: ports.TradingSwitches,
        *,
        fail_closed: Callable[[], None] = lambda: None,
    ) -> None:
        self._risk_gate, self._switches, self._fail_closed = risk_gate, switches, fail_closed

    def refusal(
        self, order: ports.SizedOrder, *, profile: AccountProfile, instrument: Instrument
    ) -> RejectionCode | None:
        if order.order_type == "market" and order.qty > instrument.max_mkt_order_qty:
            return "cap_breached"
        try:
            if self._switches.refusal(order.account_id, order.environment) is not None:
                return "trading_disabled"
            decision = self._risk_gate.check(order, profile=profile)
        except OmsNotReady:  # the runtime's fence: order entry is not open yet
            return "trading_disabled"
        except Exception as exc:  # fail closed, logged by its class alone (C-12.6)
            account_id, error = str(order.account_id), type(exc).__name__
            log = structlog.get_logger(__name__)  # per call: never a stale processor chain (#2008)
            log.error("trade_group_guard_failed", account_id=account_id, error=error)
            if order.effect is not ports.OrderEffect.REDUCE:  # a position-opening leg (BQ-8(a))
                with suppress(Exception):  # a counter's fault never turns a refusal into a raise
                    self._fail_closed()
            return "risk_state_unavailable"
        if decision.allowed is True:
            return None
        if decision.code is RiskRefusal.RISK_LIMIT_BREACHED:  # a cap breached, in 22's words
            return "cap_breached"
        return rejection_code(decision.code, "risk_state_unavailable")  # none, or no state
