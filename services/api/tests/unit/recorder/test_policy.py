"""E16-T02 acceptance scenarios for `RecordingPolicy` (fake clock; B11 via factory)."""

from __future__ import annotations

import pytest

from candleviewer.recorder.errors import InvalidRecordedSymbolError, RecorderSymbolLimitError
from candleviewer.recorder.policy import PolicyConfig, RecordingPolicy, user_actor
from tests.unit.recorder.conftest import FakeAudit, FakeBus, FakeClock

OWNER = user_actor("owner-1")


async def test_policy_fresh_install_effective_set_is_empty(
    policy: RecordingPolicy, bus: FakeBus, audit: FakeAudit
) -> None:
    await policy.tick()
    assert policy.effective_set() == {}
    assert bus.events == [] and audit.records == []


async def test_policy_manual_add_publishes_within_5s(
    policy: RecordingPolicy, bus: FakeBus, audit: FakeAudit, clock: FakeClock
) -> None:
    t0 = clock()
    await policy.add_manual("BTCUSDT", OWNER, ("trades",), 200)
    topic, ev = bus.events[-1]
    assert topic == "demo.recorder.set_changed"
    assert (ev.symbol, ev.change, ev.reason) == ("BTCUSDT", "added", "manual")
    assert ev.ts_event / 1e6 - t0 <= 5
    assert policy.leaf("BTCUSDT") == "recording"  # subscribe_streams ran
    action, kw = audit.records[0]
    assert action == "recorder.start"
    assert kw["after_state"] == {
        "symbol": "BTCUSDT", "reason": "manual", "actor": "owner-1", "trigger_ref": "manual:owner-1"
    }  # fmt: skip
    assert kw["actor_label"] == "user:owner-1" and kw["env"] == "demo"
    entry = policy.effective_set()["BTCUSDT"]
    assert entry.priority == 300 and not entry.auto_evictable and entry.streams == ("trades",)


async def test_policy_chart_browsing_under_delay_never_records(
    policy: RecordingPolicy, bus: FakeBus, clock: FakeClock
) -> None:
    await policy.on_chart_opened("SOLUSDT", "c1")
    clock.advance(20)
    await policy.tick()
    await policy.on_chart_closed("SOLUSDT", "c1")
    clock.advance(120)
    await policy.tick()
    assert policy.effective_set() == {} and bus.events == []


@pytest.mark.parametrize(("held", "recorded"), [(59.0, False), (60.0, True)])
async def test_policy_chart_open_delay_boundary(
    policy: RecordingPolicy, clock: FakeClock, held: float, recorded: bool
) -> None:
    await policy.on_chart_opened("SOLUSDT", "c1")
    clock.advance(held)
    await policy.tick()
    assert ("SOLUSDT" in policy.effective_set()) is recorded


async def test_policy_position_open_records_immediately_and_holds(
    policy: RecordingPolicy, bus: FakeBus, clock: FakeClock
) -> None:
    await policy.on_position_opened("XRPUSDT", "pos-1")
    assert policy.effective_set()["XRPUSDT"].reason == "position_open"
    assert bus.events[-1][1].reason == "position_open"
    clock.advance(10_000)
    await policy.tick()
    assert policy.leaf("XRPUSDT") == "recording"


async def test_policy_grace_period_prevents_fragmentation(
    policy: RecordingPolicy, audit: FakeAudit, clock: FakeClock
) -> None:
    await policy.on_chart_opened("ETHUSDT", "c1")
    clock.advance(60)
    await policy.tick()
    await policy.on_chart_closed("ETHUSDT", "c1")
    assert policy.effective_set()["ETHUSDT"].lingering
    clock.advance(300)
    await policy.tick()
    await policy.on_chart_opened("ETHUSDT", "c2")  # re-acquired at once, no 60 s delay
    assert policy.leaf("ETHUSDT") == "recording"
    clock.advance(3_600)
    await policy.tick()
    assert audit.actions() == ["recorder.start"]  # never stopped, no new session


async def test_policy_grace_expiry_stops_and_audits(
    policy: RecordingPolicy, audit: FakeAudit, bus: FakeBus, clock: FakeClock
) -> None:
    await policy.on_position_opened("ETHUSDT", "p1")
    await policy.on_position_closed("ETHUSDT", "p1")
    clock.advance(1_799)
    await policy.tick()
    assert "ETHUSDT" in policy.effective_set()
    clock.advance(1)
    await policy.tick()
    assert policy.effective_set() == {}
    assert audit.actions() == ["recorder.start", "recorder.stop"]
    assert bus.events[-1][1].change == "removed"


async def test_policy_manual_survives_trigger_loss(
    policy: RecordingPolicy, clock: FakeClock
) -> None:
    await policy.add_manual("BTCUSDT", OWNER)
    await policy.on_chart_opened("BTCUSDT", "c1")
    clock.advance(60)
    await policy.tick()
    await policy.on_chart_closed("BTCUSDT", "c1")
    clock.advance(10_000)
    await policy.tick()
    entry = policy.effective_set()["BTCUSDT"]
    assert entry.reason == "manual" and not entry.lingering


@pytest.mark.parametrize(
    ("triggers", "expected"),
    [
        (("chart",), "chart_open"),
        (("position",), "position_open"),
        (("chart", "position"), "position_open"),
        (("manual", "chart"), "manual"),
        (("manual", "position"), "manual"),
        (("manual", "chart", "position"), "manual"),
    ],
)
async def test_policy_reason_precedence(
    policy: RecordingPolicy, clock: FakeClock, triggers: tuple[str, ...], expected: str
) -> None:
    if "chart" in triggers:
        await policy.on_chart_opened("ADAUSDT", "c1")
        clock.advance(60)
        await policy.tick()
    if "position" in triggers:
        await policy.on_position_opened("ADAUSDT", "p1")
    if "manual" in triggers:
        await policy.add_manual("ADAUSDT", OWNER)
    entry = policy.effective_set()["ADAUSDT"]
    assert entry.reason == expected
    assert entry.auto_evictable is (expected != "manual")


async def test_policy_remove_manual_then_grace_and_pin_exposed(
    policy: RecordingPolicy, clock: FakeClock, bus: FakeBus
) -> None:
    await policy.add_manual("BTCUSDT", OWNER)
    await policy.set_pin("BTCUSDT", True, OWNER)
    assert policy.effective_set()["BTCUSDT"].pinned
    await policy.on_position_opened("BTCUSDT", "p1")
    await policy.remove_manual("BTCUSDT", OWNER)
    assert bus.events[-1][1].change == "reason_changed"
    assert policy.effective_set()["BTCUSDT"].reason == "position_open"


async def test_policy_autorecord_disabled_gates_chart_only(
    clock: FakeClock, bus: FakeBus, audit: FakeAudit
) -> None:
    cfg = PolicyConfig(autorecord_enabled=False)
    p = RecordingPolicy(disk_refuses=bool, bus=bus, audit=audit, env="demo", now=clock, config=cfg)
    p.positions_reloaded()
    try:
        await p.on_chart_opened("SOLUSDT", "c1")
        clock.advance(600)
        await p.tick()
        assert "SOLUSDT" not in p.effective_set()
        await p.on_position_opened("SOLUSDT", "p1")  # money at risk: never gated
        assert p.effective_set()["SOLUSDT"].reason == "position_open"
    finally:
        await p.stop()


async def test_policy_capacity_guard(clock: FakeClock, bus: FakeBus, audit: FakeAudit) -> None:
    p = RecordingPolicy(
        disk_refuses=bool,
        bus=bus,
        audit=audit,
        env="demo",
        now=clock,
        config=PolicyConfig(max_symbols=1),
    )
    p.positions_reloaded()
    try:
        await p.add_manual("BTCUSDT", OWNER)
        with pytest.raises(RecorderSymbolLimitError):
            await p.add_manual("ETHUSDT", OWNER)
        await p.on_chart_opened("SOLUSDT", "c1")
        clock.advance(60)
        await p.tick()
        assert set(p.effective_set()) == {"BTCUSDT"}  # auto-start refused, not silent start
    finally:
        await p.stop()


@pytest.mark.parametrize("bad", ["btcusdt", "BTC.USDT", "*", "B"])
async def test_policy_rejects_invalid_symbol(policy: RecordingPolicy, bad: str) -> None:
    with pytest.raises(InvalidRecordedSymbolError):
        await policy.on_chart_opened(bad, "c1")
