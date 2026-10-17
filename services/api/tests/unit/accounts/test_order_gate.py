"""E27-T04 account side of the composed order-entry gate (decision Q5 on #837): the account check
fills an account slot of the shared kernel's `OrderEntryGate`; a down, policy-disabled or keyless
account refuses new orders, with one fixed detail per reason that never names the key-policy rule;
a stale or unknown wallet makes risk-based sizing unavailable but refuses no order; health is
derived on read, so no tick has to run first."""

from __future__ import annotations

import inspect
from typing import ClassVar, Literal, cast
from uuid import UUID

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from candleviewer.accounts.health import AccountHealthMonitor, HealthState
from candleviewer.accounts.order_gate import AccountHealthCheck, DisabledReason, KeyStanding
from candleviewer.accounts.verification import Rule
from candleviewer.domain.order_entry import OrderEntryCheck, OrderEntryGate, OrderEntryRefusal
from tests.unit.accounts._fakes import ACC, Dms, FakeClock, Sizing, Standings

ACTIVE = KeyStanding(has_active_key=True)
POLICY_DETAIL = "Trading is disabled for this account by policy."


class _Maintenance:
    """The kernel's first slot takes only a `GlobalOrderEntryCheck`: the global scope, declared."""

    scope: ClassVar[Literal["global"]] = "global"

    def refusal(self, account_id: UUID) -> OrderEntryRefusal | None:
        return None


class _Health:
    """A `HealthStates` answering one fixed value, in the contract or out of it."""

    def __init__(self, state: object) -> None:
        self.state = state

    def current(self, account_id: UUID) -> HealthState | None:
        return cast(HealthState | None, self.state)


def _gate(
    standing: KeyStanding | None = ACTIVE, wallets: dict[UUID, bool] | None = None
) -> tuple[AccountHealthCheck, AccountHealthMonitor, FakeClock]:
    clock = FakeClock()
    health = AccountHealthMonitor(clock, Dms())
    health.track(ACC)
    keys = Standings({ACC: standing} if standing else {})
    sizing = Sizing({ACC: True} if wallets is None else wallets)
    return AccountHealthCheck(health, keys, sizing), health, clock


def test_the_account_check_fills_an_account_slot_of_the_shared_gate() -> None:
    check, health, _ = _gate()
    health.ws_heartbeat(ACC)
    gate = OrderEntryGate(_Maintenance(), check)  # CI's mypy proves the match in order_gate.py
    shared = inspect.signature(OrderEntryCheck.refusal)
    assert inspect.signature(AccountHealthCheck.refusal) == shared
    assert gate.refusal(ACC) is None
    health.untrack(ACC)
    refusal = gate.refusal(ACC)
    assert refusal is not None and refusal.reason == "account_unhealthy"


@pytest.mark.parametrize("evidence", ["ws_heartbeat", "rest_ok"])
def test_a_healthy_or_degraded_account_with_an_active_key_accepts_orders(evidence: str) -> None:
    check, health, _ = _gate()
    getattr(health, evidence)(ACC)
    assert check.refusal(ACC) is None and check.risk_sizing_available(ACC)


@pytest.mark.parametrize("untrack", [False, True])
async def test_a_down_or_unmonitored_account_refuses_order_entry(untrack: bool) -> None:
    check, health, clock = _gate()
    health.ws_heartbeat(ACC)
    clock.advance(30)
    health.tick()
    await health.drain()
    if untrack:
        health.untrack(ACC)
    refusal = check.refusal(ACC)
    assert refusal is not None and refusal.reason == "account_unhealthy"


@pytest.mark.parametrize("silence", [30, 600])
def test_a_lapsed_account_is_refused_with_no_tick_ever_run(silence: int) -> None:
    check, health, clock = _gate()
    health.ws_heartbeat(ACC)
    clock.advance(silence)  # the tick task died, or the laptop slept: no tick() runs
    refusal, view = check.refusal(ACC), health.view(ACC)
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
    check, health, _ = _gate(standing)
    health.ws_heartbeat(ACC)
    refusal = check.refusal(ACC)
    assert refusal is not None and refusal.reason == expected


@pytest.mark.parametrize("state", [*HealthState, None, "suspended", "unverified", "", 1], ids=repr)
def test_only_a_healthy_or_degraded_account_admits_an_order(state: object) -> None:
    """An allow-list (KV-T12): a state added later, or a value outside the contract, refuses."""
    check = AccountHealthCheck(_Health(state), Standings({ACC: ACTIVE}), Sizing())
    refusal = check.refusal(ACC)
    assert (refusal is None) == (state in {HealthState.HEALTHY, HealthState.DEGRADED})
    assert refusal is None or refusal.reason == "account_unhealthy"


@pytest.mark.parametrize("truthy", [1, "yes", "True"], ids=repr)
def test_only_an_active_key_that_is_exactly_true_admits_an_order(truthy: object) -> None:
    check, health, _ = _gate(KeyStanding(cast(bool, truthy)))
    health.ws_heartbeat(ACC)
    refusal = check.refusal(ACC)
    assert refusal is not None and refusal.reason == "no_active_key"


def test_the_policy_disable_codes_are_the_key_verifiers_rule_codes() -> None:
    """`DisabledReason` repeats three codes that `Rule` owns: a rename there must fail here."""
    verifier = {Rule.WITHDRAW_PERMISSION, Rule.IP_WHITELIST_MISSING, Rule.IP_WHITELIST_MISMATCH}
    assert {d.value for d in DisabledReason} == {r.value for r in verifier} | {"account_disabled"}


@pytest.mark.parametrize("disabled", list(DisabledReason))
def test_every_policy_disable_answers_one_detail_that_names_no_key_rule(
    disabled: DisabledReason,
) -> None:
    """The 403 reaches callers without `keys:read` (a manager): the failed rule stays unsaid."""
    check, health, _ = _gate(KeyStanding(True, disabled))
    health.ws_heartbeat(ACC)
    assert check.refusal(ACC) == OrderEntryRefusal("account_disabled_by_policy", POLICY_DETAIL)
    assert not {"key", "whitelist", "withdraw", "transfer", "ip"} & set(
        POLICY_DETAIL.lower().rstrip(".").split()
    )


def test_an_undeclared_disable_reason_never_reaches_the_detail() -> None:
    upstream = "retCode 10003: API key is invalid (key ...AbC1)"
    check, health, _ = _gate(KeyStanding(True, cast(DisabledReason, upstream)))
    health.ws_heartbeat(ACC)
    assert check.refusal(ACC) == OrderEntryRefusal("account_disabled_by_policy", POLICY_DETAIL)


@pytest.mark.parametrize("wallets", [{ACC: False}, {}], ids=["stale", "no_snapshot"])
def test_a_stale_or_unknown_wallet_makes_risk_sizing_unavailable_but_refuses_no_order(
    wallets: dict[UUID, bool],
) -> None:
    check, health, _ = _gate(wallets=wallets)
    health.ws_heartbeat(ACC)
    assert check.risk_sizing_available(ACC) is False
    assert check.refusal(ACC) is None


_STEPS = st.lists(
    st.tuples(
        st.integers(0, 40_000).map(lambda ms: ms / 1000),
        st.sampled_from(["hb", "drop", "rest", "tick"]),
    )
)


@settings(max_examples=100, deadline=None, derandomize=True)
@given(_STEPS)
async def test_health_refuses_exactly_while_the_monitor_derives_down(
    steps: list[tuple[float, str]],
) -> None:
    check, health, clock = _gate()
    act = {"hb": health.ws_heartbeat, "drop": health.ws_dropped, "rest": health.rest_ok}
    for dt, kind in steps:
        clock.advance(dt)
        if kind in act:
            act[kind](ACC)
        else:
            health.tick()
        await health.drain()
        refusal = check.refusal(ACC)
        assert (refusal is not None) == (health.current(ACC) is HealthState.DOWN)
