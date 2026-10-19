"""E27-T04 W3 (#837): the one order-entry gate `create_app` composes, `OrderEntryGate(maintenance,
account_check)`. AC3's "order entry for that account is refused" through it; `no_active_key` and
`account_disabled_by_policy` from the real key standing the tracking read feeds; maintenance first.
The usable-key read is faked at its SQL edge, on a fake clock: no Docker, no network."""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

import pytest
from pydantic import SecretStr

import candleviewer.account_health_wiring as wiring
import candleviewer.app as appmod
from candleviewer.accounts.order_gate import DisabledReason, KeyStanding
from candleviewer.accounts.selfcheck import FRESHNESS_GRACE, KeyCheck
from candleviewer.domain.order_entry import GlobalOrderEntryCheck, OrderEntryCheck, OrderEntryGate
from candleviewer.settings import Environment, Settings
from candleviewer.storage.repositories.accounts import SelfCheckTargetRow
from candleviewer.storage.repositories.key_selfcheck_sqlalchemy import SqlAlchemyKeySelfCheckStore
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from tests.unit.accounts._fakes import ACC, ACC_B, FakeClock, key_of, key_row

#: Not the default hour, so a standing that ignored the configured interval would show.
INTERVAL_S = 600.0
WINDOW = timedelta(seconds=INTERVAL_S) + FRESHNESS_GRACE


def _real() -> Settings:
    return Settings(
        storage_backend="real",
        environment=Environment.TESTNET,
        auth_pepper=SecretStr("test-pepper"),
        auth_totp_key_hex=SecretStr("11" * 32),
        auth_recovery_hmac_key_hex=SecretStr("22" * 32),
        auth_csrf_key_hex=SecretStr("33" * 32),
        CV_KEY_SELFCHECK_INTERVAL_S=INTERVAL_S,
    )


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """The real-backend app on a fake clock, its usable-key read answering `rows`, or raising the
    error in `down`."""
    clock, rows, down = FakeClock(), list[SelfCheckTargetRow](), list[Exception]()

    async def targets(_store: SqlAlchemyKeySelfCheckStore) -> tuple[SelfCheckTargetRow, ...]:
        if down:
            raise down[0]
        return tuple(rows)

    async def dispose(_repository: SqlAlchemyRelationalRepository) -> None:
        return None

    monkeypatch.setattr(wiring, "SystemClock", lambda: clock)
    monkeypatch.setattr(SqlAlchemyKeySelfCheckStore, "targets", targets)
    monkeypatch.setattr(SqlAlchemyRelationalRepository, "dispose", dispose)
    monkeypatch.setattr(appmod, "_build_accounts_counts", lambda _settings: None)
    app = appmod.create_app(_real())
    ctx = app.state.app_context
    return SimpleNamespace(
        app=app,
        clock=clock,
        rows=rows,
        down=down,
        gate=app.state.order_entry_gate,
        runtime=app.state.account_health,
        maintenance=app.state.feature_flags.gate,
        feed=ctx.accounts.account_health,
        job=ctx.accounts._selfcheck,
    )


def _reason(gate: OrderEntryGate) -> str | None:
    refusal = gate.refusal(ACC)
    return None if refusal is None else refusal.reason


async def _admit(w: SimpleNamespace, *rows: SelfCheckTargetRow) -> None:
    """One tracking pass over `rows`, the flag poll's reading (both gate flags off) and one
    heartbeat of the private-WS consumer for `ACC`."""
    w.rows.extend(rows or [key_row(ACC, verified_at=w.clock.now())])
    await w.runtime.refresh_tracking()
    w.maintenance.set(False)
    w.feed.ws_heartbeat(ACC)


def test_create_app_serves_one_gate_the_maintenance_check_then_the_account_check(
    world: SimpleNamespace,
) -> None:
    gate: OrderEntryGate = world.app.state.order_entry_gate
    assert gate is world.app.state.feature_flags.order_entry_gate  # no gate without the account
    assert gate.checks == (world.maintenance, world.runtime.order_entry_check)


def test_create_app_builds_no_order_entry_gate_but_the_one_it_serves(
    world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C-2.21: no router or holder is ever handed a gate of the maintenance check alone, not even
    while `create_app` runs: the one gate it builds is the composed one it serves."""
    built: list[OrderEntryGate] = []
    init = OrderEntryGate.__init__

    def record(
        gate: OrderEntryGate, maintenance: GlobalOrderEntryCheck, *checks: OrderEntryCheck
    ) -> None:
        init(gate, maintenance, *checks)
        built.append(gate)

    monkeypatch.setattr(OrderEntryGate, "__init__", record)
    app = appmod.create_app(_real())
    assert len(built) == 1 and built[0] is app.state.order_entry_gate


@pytest.mark.parametrize("backend", ["fake", "real"])
def test_maintenance_refuses_first_and_an_untracked_account_once_it_is_off(
    backend: str, world: SimpleNamespace
) -> None:
    """Fail closed: an account with no standing and no health is refused, on either backend."""
    fake = Settings(environment=Environment.TESTNET)
    app = world.app if backend == "real" else appmod.create_app(fake)
    gate, maintenance = app.state.order_entry_gate, app.state.feature_flags.gate
    assert _reason(gate) == "maintenance"  # the flags are unread: engaged
    maintenance.set(False)
    assert _reason(gate) == "no_active_key"


async def test_ac3_an_account_down_30_s_after_its_last_success_is_refused_by_the_apps_gate(
    world: SimpleNamespace,
) -> None:
    await _admit(world)
    assert _reason(world.gate) is None
    world.clock.advance(29.5)  # degraded: the heartbeat window passed, the down window has not
    assert _reason(world.gate) is None
    world.clock.advance(0.5)  # 30 s after the last success, with no tick run
    assert _reason(world.gate) == "account_unhealthy"


async def test_the_apps_gate_refuses_once_the_last_good_tracking_read_is_a_minute_old(
    world: SimpleNamespace,
) -> None:
    """The standing's age bound is `TRACKING_FAULT_AFTER_S`, the tracking loop's fault threshold
    (`/readyz` degrades after four failed passes: as late as about 100 s after the last good read
    when reads hang to their timeout, so the gate refuses first): reads that keep failing never
    admit on a frozen list, however healthy."""
    await _admit(world)
    world.down.append(ConnectionError("the database is down"))
    world.clock.advance(wiring.TRACKING_FAULT_AFTER_S)
    with pytest.raises(ConnectionError):
        await world.runtime.refresh_tracking()
    world.feed.ws_heartbeat(ACC)
    assert _reason(world.gate) is None
    world.clock.advance(0.001)
    world.feed.ws_heartbeat(ACC)
    assert _reason(world.gate) == "no_active_key"


async def test_a_key_past_its_window_is_refused_as_no_active_key_on_a_healthy_account(
    world: SimpleNamespace,
) -> None:
    """SR-E27-18 at admission, on the configured self-check interval plus the grace."""
    await _admit(world, key_row(ACC, verified_at=world.clock.now() - WINDOW))
    assert _reason(world.gate) is None
    world.clock.advance(0.001)
    world.feed.ws_heartbeat(ACC)
    assert _reason(world.gate) == "no_active_key"


async def test_an_account_not_armed_for_trading_is_refused_as_disabled_by_policy(
    world: SimpleNamespace,
) -> None:
    await _admit(world, key_row(ACC, verified_at=world.clock.now(), armed=False))
    assert _reason(world.gate) == "account_disabled_by_policy"


async def test_the_apps_standing_reads_the_apps_self_check_and_its_failure_refuses_at_once(
    world: SimpleNamespace,
) -> None:
    await _admit(world)
    now = world.clock.now()
    failed = KeyCheck(key_of(ACC), ACC, now, "failed", "key_withdraw_permission", None, now, None)
    world.job.results[key_of(ACC)] = failed
    assert _reason(world.gate) == "account_disabled_by_policy"


async def test_the_tracking_read_feeds_the_standing_the_rows_of_its_own_environment(
    world: SimpleNamespace,
) -> None:
    other = key_row(ACC_B, env="live")  # the store filters on `env`: a row of another is a bug
    world.rows.extend([key_row(ACC, verified_at=world.clock.now(), enabled=False), other])
    await world.runtime.refresh_tracking()
    standings = world.runtime.standings
    assert standings.standing(ACC) == KeyStanding(True, DisabledReason.ACCOUNT_DISABLED)
    assert standings.standing(ACC_B) is None
