"""E27-T04 account side of the composed order-entry gate (decision Q5 on #837): a down, policy-
disabled or keyless account refuses new orders, with fixed text only; a stale or unknown wallet
refuses risk-based sizing only; health is derived on read, so no tick has to run first."""

from __future__ import annotations

from typing import cast
from uuid import UUID

import pytest

from candleviewer.accounts.health import AccountHealthMonitor, HealthState
from candleviewer.accounts.order_gate import (
    AccountHealthCheck,
    DisabledReason,
    KeyStanding,
    OrderEntryRefusal,
)
from tests.unit.accounts._fakes import ACC, Dms, FakeClock, Sizing, Standings

ACTIVE = KeyStanding(has_active_key=True)


def _gate(
    standing: KeyStanding | None = ACTIVE, wallets: dict[UUID, bool] | None = None
) -> tuple[AccountHealthCheck, AccountHealthMonitor, FakeClock]:
    clock = FakeClock()
    health = AccountHealthMonitor(clock, Dms())
    health.track(ACC)
    keys = Standings({ACC: standing} if standing else {})
    sizing = Sizing({ACC: True} if wallets is None else wallets)
    return AccountHealthCheck(health, keys, sizing), health, clock


@pytest.mark.parametrize("evidence", ["ws_heartbeat", "rest_ok"])
def test_a_healthy_or_degraded_account_with_an_active_key_accepts_orders(evidence: str) -> None:
    gate, health, _ = _gate()
    getattr(health, evidence)(ACC)
    assert gate.refusal(ACC) is None and gate.sizing_refusal(ACC) is None


@pytest.mark.parametrize("untrack", [False, True])
async def test_a_down_or_unmonitored_account_refuses_order_entry(untrack: bool) -> None:
    gate, health, clock = _gate()
    health.ws_heartbeat(ACC)
    clock.advance(30)
    health.tick()
    await health.drain()
    if untrack:
        health.untrack(ACC)
    refusal = gate.refusal(ACC)
    assert refusal is not None and refusal.reason == "account_unhealthy"


@pytest.mark.parametrize("silence", [30, 600])
def test_a_lapsed_account_is_refused_with_no_tick_ever_run(silence: int) -> None:
    gate, health, clock = _gate()
    health.ws_heartbeat(ACC)
    clock.advance(silence)  # the tick task died, or the laptop slept: no tick() runs
    refusal, view = gate.refusal(ACC), health.view(ACC)
    assert refusal is not None and refusal.reason == "account_unhealthy"
    assert view is not None and view.state is HealthState.DOWN
    assert view.heartbeat_age_ms == silence * 1000


@pytest.mark.parametrize(
    ("standing", "expected"),
    [
        (None, "no_active_key"),
        (KeyStanding(has_active_key=False), "no_active_key"),
        (KeyStanding(False, DisabledReason.ACCOUNT_DISABLED), "account_disabled_by_policy"),
    ],
)
def test_key_standing_refusals(standing: KeyStanding | None, expected: str) -> None:
    gate, health, _ = _gate(standing)
    health.ws_heartbeat(ACC)
    refusal = gate.refusal(ACC)
    assert refusal is not None and refusal.reason == expected


@pytest.mark.parametrize(
    ("disabled", "detail"),
    [
        (DisabledReason.KEY_WITHDRAW_PERMISSION, "The API key can withdraw or transfer funds."),
        (DisabledReason.KEY_IP_WHITELIST_MISSING, "The API key has no IP whitelist."),
        (
            DisabledReason.KEY_IP_WHITELIST_MISMATCH,
            "The API key's IP whitelist excludes this server.",
        ),
        (DisabledReason.ACCOUNT_DISABLED, "Trading is switched off for this account."),
    ],
)
def test_a_policy_disable_answers_with_fixed_text(disabled: DisabledReason, detail: str) -> None:
    gate, health, _ = _gate(KeyStanding(True, disabled))
    health.ws_heartbeat(ACC)
    assert gate.refusal(ACC) == OrderEntryRefusal("account_disabled_by_policy", detail)


def test_an_undeclared_disable_reason_never_reaches_the_detail() -> None:
    upstream = "retCode 10003: API key is invalid (key ...AbC1)"
    gate, health, _ = _gate(KeyStanding(True, cast(DisabledReason, upstream)))
    health.ws_heartbeat(ACC)
    refusal = gate.refusal(ACC)
    expected = "Trading is disabled for this account by policy."
    assert refusal == OrderEntryRefusal("account_disabled_by_policy", expected)


@pytest.mark.parametrize("wallets", [{ACC: False}, {}], ids=["stale", "no_snapshot"])
def test_a_stale_or_unknown_wallet_refuses_risk_based_sizing_but_not_order_entry(
    wallets: dict[UUID, bool],
) -> None:
    gate, health, _ = _gate(wallets=wallets)
    health.ws_heartbeat(ACC)
    refusal = gate.sizing_refusal(ACC)
    assert refusal is not None and refusal.reason == "balance_stale"
    assert gate.refusal(ACC) is None
