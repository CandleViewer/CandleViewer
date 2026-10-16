"""PR #2186 review fixes: per-interpreter audit hook, actors, bounded tracking, pruning."""

from __future__ import annotations

import asyncio

import pytest

import candleviewer.statechart.bindings.b11_recording as b11
from candleviewer.recorder.errors import InvalidRecorderActorError, RecorderSymbolLimitError
from candleviewer.recorder.models import SYSTEM_ACTOR
from candleviewer.recorder.policy import PolicyConfig, RecordingPolicy, user_actor
from candleviewer.statechart import build
from candleviewer.statechart.factory import default_clock
from tests.unit.recorder._fakes import FakeAudit, FakeBus, FakeClock

OWNER = user_actor("owner-1")


async def _stop_cycle(p: RecordingPolicy, clock: FakeClock) -> None:
    await p.on_position_opened("BTCUSDT", "p1")
    await p.on_position_closed("BTCUSDT", "p1")
    clock.advance(1_800)
    await p.tick()


async def test_two_policies_audit_to_their_own_sink_and_env(clock: FakeClock) -> None:
    live_audit, demo_audit = FakeAudit(), FakeAudit()
    live = RecordingPolicy(
        disk_refuses=bool, bus=FakeBus(), audit=live_audit, env="live", now=clock
    )
    live.positions_reloaded()
    demo = RecordingPolicy(
        disk_refuses=bool, bus=FakeBus(), audit=demo_audit, env="demo", now=clock
    )
    try:
        await live.on_position_opened("BTCUSDT", "p1")
        await demo.stop()  # stopping one policy must not detach the other's hook
        demo = RecordingPolicy(
            disk_refuses=bool, bus=FakeBus(), audit=demo_audit, env="demo", now=clock
        )
        demo.positions_reloaded()
        await _stop_cycle(demo, clock)
        await live.on_position_closed("BTCUSDT", "p1")
        clock.advance(1_800)
        await live.tick()
        assert live_audit.envs() == [("recorder.start", "live"), ("recorder.stop", "live")]
        assert demo_audit.envs() == [("recorder.start", "demo"), ("recorder.stop", "demo")]
    finally:
        await live.stop()
        await demo.stop()


async def test_b11_without_hook_refuses_unaudited_subscribe() -> None:
    interp = (await build("recording", clock=default_clock(), lane="platform")).interpreter
    try:
        await interp.send({"type": "REASON_ADDED", "reason": "manual", "symbol": "X"}, wait=True)
        for _ in range(64):
            if "recording.error" in interp.current_state_ids:
                break
            await asyncio.sleep(0)
        assert "recording.error" in interp.current_state_ids
        assert interp.context["error"] == "B11HookMissingError"
    finally:
        await interp.stop()
    assert b11.B11HookMissingError.__mro__[1] is RuntimeError


@pytest.mark.parametrize("bad", ["", "   ", None])
def test_user_actor_rejects_empty(bad: str | None) -> None:
    with pytest.raises(InvalidRecorderActorError):
        user_actor(bad)


async def test_add_manual_rejects_system_actor(policy: RecordingPolicy) -> None:
    with pytest.raises(InvalidRecorderActorError):
        await policy.add_manual("BTCUSDT", SYSTEM_ACTOR)
    assert policy.effective_set() == {}


async def test_remove_manual_audits_the_remover(
    policy: RecordingPolicy, audit: FakeAudit, clock: FakeClock
) -> None:
    await policy.add_manual("BTCUSDT", OWNER)
    await policy.remove_manual("BTCUSDT", user_actor("mgr-2"))
    clock.advance(1_800)
    await policy.tick()
    stop = audit.records[-1]
    assert stop[0] == "recorder.stop" and stop[1]["actor_label"] == "user:mgr-2"


async def test_set_pin_is_audited_with_actor(policy: RecordingPolicy, audit: FakeAudit) -> None:
    await policy.set_pin("BTCUSDT", True, OWNER)
    await policy.set_pin("BTCUSDT", True, OWNER)  # no-op: no second record
    assert [(a, kw["actor_label"]) for a, kw in audit.records] == [
        ("retention.change", "user:owner-1")
    ]


async def test_trigger_refs_kept_per_reason(
    policy: RecordingPolicy, audit: FakeAudit, clock: FakeClock
) -> None:
    await policy.on_position_opened("BTCUSDT", "p1")
    await policy.on_position_opened("BTCUSDT", "p2")
    assert audit.records[0][1]["after_state"]["trigger_ref"] == "position:p1"
    await policy.on_position_closed("BTCUSDT", "p1")
    await policy.on_position_closed("BTCUSDT", "p2")
    clock.advance(1_800)
    await policy.tick()
    assert audit.records[-1][1]["actor_label"] == "system:recorder-policy"


async def test_chart_flood_cannot_starve_position(clock: FakeClock) -> None:
    p = RecordingPolicy(disk_refuses=bool, bus=FakeBus(), audit=FakeAudit(), env="demo", now=clock)
    p.positions_reloaded()
    try:
        for i in range(1_024):
            await p.on_chart_opened(f"S{i:04d}USDT", "c")
        await p.on_chart_opened("EXTRAUSDT", "c")  # over cap: refused, not tracked
        assert "EXTRAUSDT" not in p._syms
        await p.on_position_opened("XRPUSDT", "p1")
        assert p.effective_set()["XRPUSDT"].reason == "position_open"
    finally:
        await p.stop()


async def test_refused_manual_add_leaves_no_residue(clock: FakeClock) -> None:
    cfg = PolicyConfig(max_symbols=1)
    p = RecordingPolicy(
        disk_refuses=bool, bus=FakeBus(), audit=FakeAudit(), env="demo", now=clock, config=cfg
    )
    p.positions_reloaded()
    try:
        await p.add_manual("BTCUSDT", OWNER)
        with pytest.raises(RecorderSymbolLimitError):
            await p.add_manual("ETHUSDT", OWNER)
        assert "ETHUSDT" not in p._syms
    finally:
        await p.stop()


async def test_stopped_chart_is_pruned(policy: RecordingPolicy, clock: FakeClock) -> None:
    await _stop_cycle(policy, clock)
    assert policy._charts == {} and policy._syms == {}
    await _stop_cycle(policy, clock)  # a fresh session after a real stop still works
    assert policy._charts == {}
