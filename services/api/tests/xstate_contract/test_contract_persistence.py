"""Per-machine persist -> restore contract (29 §1.7, E50-T31).

For every committed chart:
* a snapshot round-trip at **every quiescence point** (each stable leaf)
  restores the identical configuration, context and scheduled sends;
* the drain journal replays exactly once;
* a wrong `machine_hash`, a bad HMAC or `version < 3` is refused loudly
  (quarantined + P1 page);
* a chain-trip latch survives restore.
"""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest
from xstate_statemachine import Event, SimulatedClock

from candleviewer.statechart.persistence import (
    ChainTripLatch,
    InMemoryDrainJournal,
    MachineKey,
    Persister,
    Restorer,
    RestoreRefusedError,
    SealedSnapshot,
    hmac_sealer,
    split_sealed_drain,
)
from candleviewer.statechart.registry import Registry
from tests.xstate_contract._harness import (
    SPELLINGS,
    Audit,
    AuditTap,
    Charts,
    Keys,
    Pager,
    Repo,
    Spelling,
    instrument,
    lane_of,
    park,
    settle,
    stable_states,
)

_REG = Registry()
POINTS = [(k, s) for k in _REG.keys() for s in stable_states(_REG.get(k))]
MACHINES = _REG.keys()


@dataclasses.dataclass
class Rig:
    machine: str
    registry: Registry
    keys: Keys
    journal: InMemoryDrainJournal
    audit: Audit
    pager: Pager
    latch: ChainTripLatch

    @property
    def key(self) -> MachineKey:
        return MachineKey(self.machine, "00000000-0000-0000-0000-00000000e531", "demo")

    def restorer(self) -> Restorer:
        return Restorer(
            registry=self.registry,
            keys=self.keys,
            journal=self.journal,
            audit=self.audit,
            pager=self.pager,
            latch=self.latch,
            plugins=lambda _key: [AuditTap()],
            clock=SimulatedClock(),
            lane=lane_of(self.machine),
        )


async def _persisted(
    machine: str, source: str, charts: Charts, *, pending: str | None = None, trips: int = 0
) -> tuple[Rig, SealedSnapshot, dict[str, Any]]:
    res = await park(machine, _REG.get(machine), source, charts)
    reg = charts.registry(machine, _REG.get(machine), source)
    rig = Rig(machine, reg, Keys(), InMemoryDrainJournal(), Audit(), Pager(), ChainTripLatch())
    interp = res.interpreter
    interp.chain_trips = trips
    before = {
        "states": set(interp.current_state_ids),
        "context": dict(interp.context),
        "scheduled": len(interp.get_persisted_snapshot().get("scheduled_sends") or []),
    }
    if pending is not None:
        interp._enqueue_restored(Event(pending, {}))
    repo = Repo()
    await Persister(
        repo=repo,
        journal=rig.journal,
        audit=rig.audit,
        seal=hmac_sealer(rig.keys, reg.get(machine)),
        machine_hash_of=reg.hash,
        pager=rig.pager,
    ).persist(interp, key=rig.key)
    return rig, repo.rows[rig.key], before


@pytest.mark.parametrize("spelling", SPELLINGS)
@pytest.mark.parametrize(("machine", "source"), POINTS, ids=[f"{m}:{s}" for m, s in POINTS])
async def test_round_trip_at_quiescence_point_is_identical_and_replays_once(
    machine: str, source: str, spelling: Spelling, charts: Charts, monkeypatch: pytest.MonkeyPatch
) -> None:
    instrument(machine, monkeypatch, spelling)
    rig, env, before = await _persisted(machine, source, charts, pending="__CV_PROBE__")
    assert [e.event_type for e in rig.journal.rows(rig.key)] == ["__CV_PROBE__"]
    res = await rig.restorer().restore(rig.key, env)
    interp = res.interpreter
    try:
        assert set(interp.current_state_ids) == before["states"]
        assert dict(interp.context) == before["context"]
        snap = interp.get_persisted_snapshot()
        assert len(snap.get("scheduled_sends") or []) == before["scheduled"]
        assert res.replayed == 1 and not res.degraded
        await settle()
        assert interp.error is None  # an unknown replayed event never bricks
        drain, _ = split_sealed_drain(env.snapshot)
        assert (await rig.journal.replay_once(rig.key, interp, drain)).replayed == 0  # once
    finally:
        await interp.stop()


def _rest(machine: str) -> str:
    """First quiescence point (a chart initial may chase into a final)."""
    return stable_states(_REG.get(machine))[0]


def _wrong_hash(env: SealedSnapshot) -> SealedSnapshot:
    return dataclasses.replace(env, machine_hash="0" * 64)


def _bad_hmac(env: SealedSnapshot) -> SealedSnapshot:
    ctx = {**env.snapshot["context"], "__forged__": True}
    return dataclasses.replace(env, snapshot={**env.snapshot, "context": ctx})


def _version_2(env: SealedSnapshot) -> SealedSnapshot:
    return dataclasses.replace(env, version=2)


@pytest.mark.parametrize(
    "defect", [_wrong_hash, _bad_hmac, _version_2], ids=["wrong_hash", "bad_hmac", "version_2"]
)
@pytest.mark.parametrize("machine", MACHINES)
async def test_bad_envelope_refused_loudly(
    machine: str, defect: Any, charts: Charts, monkeypatch: pytest.MonkeyPatch
) -> None:
    instrument(machine, monkeypatch, "async_def")
    rig, env, _ = await _persisted(machine, _rest(machine), charts)
    with pytest.raises(RestoreRefusedError):
        await rig.restorer().restore(rig.key, defect(env))
    assert len(rig.audit.quarantined) == 1
    assert rig.pager.pages == ["P1"]


@pytest.mark.parametrize("machine", MACHINES)
async def test_chain_trip_latch_survives_restore(
    machine: str, charts: Charts, monkeypatch: pytest.MonkeyPatch
) -> None:
    instrument(machine, monkeypatch, "async_def")
    rig, env, _ = await _persisted(machine, _rest(machine), charts, trips=1)
    res = await rig.restorer().restore(rig.key, env)
    try:
        assert res.degraded and res.interpreter.chain_trips == 1
        assert rig.latch.is_latched(rig.key)
        assert rig.pager.pages == ["P1"]
    finally:
        await res.interpreter.stop()


@pytest.mark.parametrize("machine", MACHINES)
async def test_a_restored_machine_persists_again_under_the_next_generation(
    machine: str, charts: Charts, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F2 for the catalogue (CR-E50T62R2-07): every committed chart, once restored, persists again,
    under its life's epoch and the next generation, and that snapshot restores cleanly."""
    instrument(machine, monkeypatch, "async_def")
    rig, env, before = await _persisted(machine, _rest(machine), charts)
    first = await rig.restorer().restore(rig.key, env)
    await settle()
    repo = Repo()
    await Persister(
        repo=repo,
        journal=rig.journal,
        audit=rig.audit,
        seal=hmac_sealer(rig.keys, rig.registry.get(machine)),
        machine_hash_of=rig.registry.hash,
        pager=rig.pager,
    ).persist(first.interpreter, key=rig.key)
    again = repo.rows[rig.key]
    assert first.interpreter.status == "stopped"
    assert again.snapshot["cv_epoch"] == env.snapshot["cv_epoch"]
    assert (env.snapshot["cv_generation"], again.snapshot["cv_generation"]) == (1, 2)
    second = await rig.restorer().restore(rig.key, again)
    try:
        assert set(second.interpreter.current_state_ids) == before["states"]
        assert rig.pager.pages == [] and rig.audit.quarantined == []
    finally:
        await second.interpreter.stop()
