"""Restore across a grace window via `statechart.persistence` opens no duplicate session."""

from __future__ import annotations

import pytest

from candleviewer.recorder.policy import RecordingPolicy
from candleviewer.statechart.factory import default_clock
from candleviewer.statechart.persistence import (
    ChainTripLatch,
    InMemoryDrainJournal,
    MachineKey,
    Persister,
    Restorer,
    RestoreRefusedError,
    SealedSnapshot,
    hmac_sealer,
)
from candleviewer.statechart.registry import Registry
from tests.unit.recorder._fakes import FakeAudit, FakeBus, FakeClock
from tests.xstate_contract._harness import Audit, Keys, Pager, Repo

KEY = MachineKey("recording", "ETHUSDT", "demo")
_REG = Registry()


def _restorer(journal: InMemoryDrainJournal) -> Restorer:
    return Restorer(
        registry=_REG,
        keys=Keys(),
        journal=journal,
        audit=Audit(),
        pager=Pager(),
        latch=ChainTripLatch(),
        plugins=lambda: [],
        clock=default_clock(),
        lane="platform",
    )


async def _lingering_snapshot(clock: FakeClock) -> tuple[SealedSnapshot, InMemoryDrainJournal]:
    p = RecordingPolicy(disk_refuses=bool, bus=FakeBus(), audit=FakeAudit(), env="demo", now=clock)
    p.positions_reloaded()
    await p.on_position_opened("ETHUSDT", "p1")
    await p.on_position_closed("ETHUSDT", "p1")
    assert p.leaf("ETHUSDT") == "lingering"
    repo, journal = Repo(), InMemoryDrainJournal()
    await Persister(
        repo=repo,
        journal=journal,
        audit=Audit(),
        seal=hmac_sealer(Keys(), _REG.get("recording")),
        machine_hash_of=_REG.hash,
    ).persist(p._charts["ETHUSDT"], key=KEY)
    await p.stop()
    return repo.rows[KEY], journal


async def test_policy_restore_in_grace_reacquire_opens_no_duplicate_session(
    clock: FakeClock,
) -> None:
    env, journal = await _lingering_snapshot(clock)
    bus, audit = FakeBus(), FakeAudit()
    p = RecordingPolicy(disk_refuses=bool, bus=bus, audit=audit, env="demo", now=clock)
    p.positions_reloaded()
    try:
        await p.restore(_restorer(journal), KEY, env)
        assert p.leaf("ETHUSDT") == "lingering"
        assert p.effective_set()["ETHUSDT"].lingering
        clock.advance(600)
        await p.on_position_opened("ETHUSDT", "p2")
        assert p.leaf("ETHUSDT") == "recording"
        assert audit.actions() == []  # no recorder.start: same session continues
    finally:
        await p.stop()


async def test_policy_restore_grace_deadline_survives_restart(clock: FakeClock) -> None:
    env, journal = await _lingering_snapshot(clock)
    audit = FakeAudit()
    p = RecordingPolicy(disk_refuses=bool, bus=FakeBus(), audit=audit, env="demo", now=clock)
    p.positions_reloaded()
    try:
        await p.restore(_restorer(journal), KEY, env)
        clock.advance(1_800)
        await p.tick()
        assert p.effective_set() == {}
        assert audit.actions() == ["recorder.stop"]
    finally:
        await p.stop()


async def test_policy_restore_refuses_tampered_snapshot(clock: FakeClock) -> None:
    env, journal = await _lingering_snapshot(clock)
    bad = SealedSnapshot(
        key=env.key, version=env.version, machine_hash="0" * 64, snapshot=env.snapshot,
        seal=env.seal,
    )  # fmt: skip
    p = RecordingPolicy(disk_refuses=bool, bus=FakeBus(), audit=FakeAudit(), env="demo", now=clock)
    p.positions_reloaded()
    try:
        with pytest.raises(RestoreRefusedError):
            await p.restore(_restorer(journal), KEY, bad)
    finally:
        await p.stop()
