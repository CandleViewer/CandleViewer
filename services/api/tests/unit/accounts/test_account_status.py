"""E27-T04 (#837) W4a: the `ExchangeAccount` read model (`accounts/status.py`). AC1, AC2 and AC5 as
the account routes will serve them, the `connection_state` order, an account that is not monitored,
and Decimal amounts that leave as plain digit strings. Fake clock, no I/O."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from uuid import UUID

import pytest

from candleviewer.accounts.health import HealthState
from tests.unit.accounts._fakes import ACC, ACC_B, T0
from tests.unit.accounts._runtime_rig import snapshot
from tests.unit.accounts._status_world import StatusWorld

_ACC_C = UUID(int=3)


def test_a_healthy_account_reads_connected_with_its_heartbeat_age() -> None:
    world = StatusWorld()
    world.clock.advance(2)
    status = world.status(ACC)
    assert status.connection_state == "connected" and status.health is not None
    assert (status.health.state, status.health.heartbeat_age_ms) == (HealthState.HEALTHY, 2000)


def test_an_account_that_rest_polling_keeps_up_reads_degraded_and_rest_only() -> None:
    world = StatusWorld()
    world.monitor.ws_dropped(ACC)
    world.monitor.rest_ok(ACC)
    status = world.status(ACC)
    assert status.connection_state == "degraded" and status.health is not None
    assert (status.health.reason, status.health.rest_only) == ("rest_only", True)


def test_after_the_stream_and_the_reconciliation_failed_the_balance_reads_stale() -> None:
    world = StatusWorld()  # the stream refreshed it at T0, and nothing since
    world.wallets.record_attempt(ACC, ok=False)  # the truth-check failed too
    world.clock.advance(11)
    status = world.status(ACC)
    assert status.balance_stale and status.balance_stale_since == T0 + timedelta(seconds=10)
    assert world.wallets.risk_sizing_available(ACC) is False
    assert status.balance is not None and status.balance.equity == Decimal("1000.50")


@pytest.mark.parametrize(
    ("account", "enabled", "silent_s", "state"),
    [
        (ACC, True, 0, "connected"),
        (ACC, True, 31, "disconnected"),
        (ACC, False, 0, "disabled"),
        (_ACC_C, True, 0, "pending"),
        (_ACC_C, False, 0, "disabled"),
    ],
)
def test_connection_state_is_disabled_then_the_health_state_then_pending(
    account: UUID, enabled: bool, silent_s: float, state: str
) -> None:
    world = StatusWorld()
    world.clock.advance(silent_s)
    assert world.status(account, enabled=enabled).connection_state == state


def test_an_account_that_is_not_monitored_has_no_health_no_balance_and_nothing_stale() -> None:
    world = StatusWorld()
    world.clock.advance(11)
    status = world.status(_ACC_C)
    assert (status.health, status.balance, status.balance_stale) == (None, None, False)
    assert status.balance_stale_since is None


def test_the_json_form_serves_plain_digit_amounts_and_the_model_keeps_decimals() -> None:
    world = StatusWorld()
    world.clock.advance(1)
    odd = {"account_mm_rate": Decimal("1E-7"), "unrealised_pnl": Decimal("-0")}
    assert world.wallets.apply(ACC_B, snapshot(world.clock.now()).model_copy(update=odd))
    status = world.status(ACC_B)
    wire = status.model_dump(mode="json")["balance"]
    assert (wire["account_mm_rate"], wire["unrealised_pnl"], wire["equity"]) == (
        "0.0000001",
        "0",
        "1000.50",
    )
    assert status.balance is not None and status.balance.account_mm_rate == Decimal("1E-7")
