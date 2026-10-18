"""E27-T04 (#837): AC Healthy, Degraded, Down within 30 s, Wallet reconciliation after silence
and Stale balances, proved on the runtime `create_app` wires (`wire_account_health`), run in this
process against a fake private socket on a fake clock, as the E29-T05 consumer will feed it: no
Docker, no network, no wall-clock wait (the loops sleep on a fake sleeper the scenario moves)."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from datetime import timedelta
from typing import Any

import pytest
from structlog.testing import capture_logs

from candleviewer.account_health_wiring import TICK_S
from candleviewer.accounts.health import HealthState
from candleviewer.accounts.order_gate import AccountHealthCheck, KeyStanding
from tests.unit.accounts._fakes import ACC, T0, Standings
from tests.unit.accounts._runtime_rig import PING_S, START, Rig, snapshot

_STEPS = pytest.mark.parametrize(
    "step", [timedelta(minutes=5), timedelta(minutes=-5)], ids=["forwards", "backwards"]
)


def _changes(logs: Sequence[Mapping[str, Any]]) -> list[tuple[str, str]]:
    return [
        (e["from_state"], e["to_state"]) for e in logs if e["event"] == "account.health_changed"
    ]


async def test_an_idle_account_with_5_s_pongs_is_healthy_reports_its_age_and_never_flaps() -> None:
    rig = Rig()
    await rig.boot()
    with capture_logs() as logs:
        rig.ws.connect()
        for _ in range(120):  # two minutes with no traffic but the pongs
            await rig.run(1)
            assert rig.runtime.monitor.current(ACC) is HealthState.HEALTHY
    view = rig.runtime.monitor.view(ACC)  # at 120 s: the last pong was at 120 s
    await rig.run(2)
    aged = rig.runtime.monitor.view(ACC)
    await rig.close()
    assert _changes(logs) == [("down", "healthy")] and rig.dms.calls == []
    assert rig.ws.beats[:3] == [0.0, PING_S, 2 * PING_S]
    assert view is not None and aged is not None and view.heartbeat_age_ms == 0
    assert (aged.reason, aged.heartbeat_age_ms, aged.rest_only) == ("ws_heartbeat", 2000, False)


async def test_a_dropped_socket_is_degraded_with_rest_polls_then_healthy_on_restore() -> None:
    rig = Rig(rest=True)
    await rig.boot()
    monitor = rig.runtime.monitor
    with capture_logs() as logs:
        rig.ws.connect()
        await rig.run(12)  # pongs at 0, 5 and 10 s
        assert monitor.current(ACC) is HealthState.HEALTHY and rig.rest.calls == []
        rig.ws.drop()
        seen = []
        for _ in range(12):  # a minute: the 30 s that would take it down pass in the middle
            await rig.run(5)
            view = monitor.view(ACC)
            assert view is not None
            seen.append((view.state, view.reason, view.rest_only))
        polls = len(rig.rest.calls)
        rig.ws.connect()
        await rig.run(1)
        restored = monitor.view(ACC)
        await rig.run(30)
    await rig.close()
    assert seen == [(HealthState.DEGRADED, "rest_only", True)] * 12  # rest_only: the payload flag
    gaps = [b - a for a, b in zip(rig.rest.calls, rig.rest.calls[1:], strict=False)]
    assert 12 <= rig.rest.calls[0] <= 13 and gaps == [10.0] * (polls - 1)  # CV_ACCOUNT_HEARTBEAT_S
    assert restored is not None and restored.state is HealthState.HEALTHY and not restored.rest_only
    assert len(rig.rest.calls) == polls  # the socket is back: the polling stops
    assert _changes(logs) == [("down", "healthy"), ("healthy", "degraded"), ("degraded", "healthy")]
    assert rig.dms.calls == []


@pytest.mark.parametrize("hangs", [False, True], ids=["unavailable", "hung"])
async def test_silence_takes_an_account_down_30_s_after_its_last_success_by_the_tick_loop(
    hangs: bool,
) -> None:
    rig = Rig(rest=hangs)  # unavailable: the production adapter, every read fails at once
    rig.rest.hold = asyncio.Event() if hangs else None  # hung: a fake whose reads never answer
    await rig.boot()
    gate = AccountHealthCheck(
        rig.runtime.monitor, Standings({ACC: KeyStanding(has_active_key=True)}), rig.runtime.wallets
    )
    rig.ws.connect()
    await rig.run(12)
    rig.ws.go_silent()  # the socket hangs after its pong at 10 s: no close event, no evidence
    await rig.run(27.5)  # 39.5 s: still inside the 30 s window
    assert rig.runtime.monitor.current(ACC) is HealthState.DEGRADED
    assert gate.refusal(ACC) is None and rig.dms.calls == []
    await rig.run(1)  # 40.5 s: the tick at 40 s found the window lapsed
    refusal = gate.refusal(ACC)
    await rig.close()
    assert rig.runtime.monitor.current(ACC) is HealthState.DOWN
    assert refusal is not None and refusal.reason == "account_unhealthy"
    assert rig.dms.calls == [(ACC, "no_success")] and bool(rig.rest.calls) is hangs
    called = rig.dms.called_at[0] - START - rig.ws.beats[-1]  # after the last success
    assert rig.ws.beats == [0.0, 5.0, 10.0] and 30 <= called <= 30 + TICK_S


@_STEPS
async def test_a_wall_clock_step_changes_neither_health_nor_the_down_time(step: timedelta) -> None:
    rig = Rig()
    await rig.boot()
    with capture_logs() as logs:
        rig.ws.connect()
        await rig.run(12)
        rig.clock.wall += step  # a clock set or an NTP step: only the wall clock moves
        for _ in range(8):
            await rig.run(1)
            assert rig.runtime.monitor.current(ACC) is HealthState.HEALTHY
        rig.ws.go_silent()  # its last pong was at 20 s, so it is down at 50 s
        await rig.run(29.5)
        assert rig.runtime.monitor.current(ACC) is HealthState.DEGRADED and rig.dms.calls == []
        await rig.run(1)
    await rig.close()
    assert rig.runtime.monitor.current(ACC) is HealthState.DOWN
    assert _changes(logs) == [("down", "healthy"), ("healthy", "degraded"), ("degraded", "down")]
    assert [t - START for t in rig.dms.called_at] == [50.0]


async def test_after_60_s_of_wallet_silence_a_rest_read_runs_and_freshens_the_snapshot() -> None:
    rig = Rig(rest=True)
    await rig.boot()
    wallets = rig.runtime.wallets
    rig.ws.connect()
    assert rig.runtime.wallet_pushed(ACC, snapshot(rig.clock.now()))  # the stream's only push
    await rig.run(59.5)
    stale = wallets.view(ACC)
    assert rig.rest.calls == [] and stale is not None and stale.stale
    await rig.run(1)  # 60.5 s: the tick at 60 s found the truth-check due
    fresh = wallets.view(ACC)
    await rig.close()
    assert rig.rest.calls == [60.0]
    assert fresh is not None and not fresh.stale and fresh.snapshot is not None
    assert fresh.snapshot.updated_at == T0 + timedelta(seconds=60)
    assert wallets.risk_sizing_available(ACC) is True


async def test_with_no_adapter_yet_sizing_is_off_once_a_quiet_snapshot_is_a_period_old() -> None:
    rig = Rig()  # the production REST adapter: every truth-check is a failed attempt
    await rig.boot()
    wallets = rig.runtime.wallets
    rig.ws.connect()
    rig.runtime.wallet_pushed(ACC, snapshot(rig.clock.now()))
    await rig.run(30)
    quiet = wallets.view(ACC)
    assert quiet is not None and quiet.stale  # the 10 s flag is for display
    assert wallets.risk_sizing_available(ACC) is True  # ruling on #837: a quiet healthy account
    await rig.run(31)  # 61 s: the read due at 60 s was unavailable, and the period has passed
    assert wallets.risk_sizing_available(ACC) is False
    await rig.close()
    counted = rig.metrics.registry.get_sample_value(
        "cv_wallet_sizing_old_snapshot_total", {"env": "demo"}
    )
    assert counted == 1.0  # the one decision on a snapshot older than the period
