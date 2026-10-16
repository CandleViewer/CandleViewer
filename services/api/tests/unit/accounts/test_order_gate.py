"""E27-T04 account side of the composed order-entry gate (decision Q5 on #837): a down, policy-
disabled or keyless account refuses new orders; a stale wallet refuses risk-based sizing only."""

from __future__ import annotations

from uuid import UUID

import pytest

from candleviewer.accounts.health import AccountHealthMonitor
from candleviewer.accounts.order_gate import AccountHealthCheck, KeyStanding, OrderEntryRefusal
from tests.unit.accounts._fakes import ACC, Dms, FakeClock

ACTIVE = KeyStanding(has_active_key=True)


class Standings(dict[UUID, KeyStanding]):
    def standing(self, account_id: UUID) -> KeyStanding | None:
        return self.get(account_id)


class Sizing(set[UUID]):
    def risk_sizing_available(self, account_id: UUID) -> bool:
        return account_id in self


def _gate(
    standing: KeyStanding | None = ACTIVE,
) -> tuple[AccountHealthCheck, AccountHealthMonitor, FakeClock, Sizing]:
    clock, sizing = FakeClock(), Sizing({ACC})
    health = AccountHealthMonitor(clock, Dms())
    health.track(ACC)
    keys = Standings({ACC: standing} if standing else {})
    return AccountHealthCheck(health, keys, sizing), health, clock, sizing


@pytest.mark.parametrize("evidence", ["ws_heartbeat", "rest_ok"])
def test_a_healthy_or_degraded_account_with_an_active_key_accepts_orders(evidence: str) -> None:
    gate, health, _, _ = _gate()
    getattr(health, evidence)(ACC)
    assert gate.refusal(ACC) is None and gate.sizing_refusal(ACC) is None


@pytest.mark.parametrize("untrack", [False, True])
def test_a_down_or_unmonitored_account_refuses_order_entry(untrack: bool) -> None:
    gate, health, clock, _ = _gate()
    health.ws_heartbeat(ACC)
    clock.advance(30)
    health.tick()
    if untrack:
        health.untrack(ACC)
    refusal = gate.refusal(ACC)
    assert refusal is not None and refusal.reason == "account_unhealthy"


@pytest.mark.parametrize(
    ("standing", "expected"),
    [
        (None, "no_active_key"),
        (KeyStanding(has_active_key=False), "no_active_key"),
        (KeyStanding(True, "key_withdraw_permission"), "account_disabled_by_policy"),
    ],
)
def test_key_standing_refusals(standing: KeyStanding | None, expected: str) -> None:
    gate, health, _, _ = _gate(standing)
    health.ws_heartbeat(ACC)
    refusal = gate.refusal(ACC)
    assert refusal is not None and refusal.reason == expected
    if expected == "account_disabled_by_policy":
        assert refusal == OrderEntryRefusal(expected, "key_withdraw_permission")


def test_a_stale_wallet_refuses_risk_based_sizing_but_not_order_entry() -> None:
    gate, health, _, sizing = _gate()
    health.ws_heartbeat(ACC)
    sizing.clear()
    refusal = gate.sizing_refusal(ACC)
    assert refusal is not None and refusal.reason == "balance_stale"
    assert gate.refusal(ACC) is None
