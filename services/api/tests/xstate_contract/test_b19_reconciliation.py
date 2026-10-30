"""tests/xstate_contract/test_b19_reconciliation.py — B19 `reconciliation` contract (E50-T31;
E29-T06 #914 PR 2a).

Membership module of the blocking gate (29-statechart-adoption-plan.md §1.7). Every §B19.3 arm, both
service spellings, the persist→restore round-trip at every quiescence point, envelope refusal,
guard-denied / unhandled audit and latch-survives-restore run from the generated suites
(`test_contract_transitions.py`, `test_contract_persistence.py`) on recording bindings. This module
pins the §B19.7 invariant ledger to the catalogue and proves the invariants on the real bindings
over the pass (`oms.reconcile_phases`, the recording OMS of `tests/unit/oms/reconcile_rig.py`): the
job's own faults lock it rather than retry forever (a), diffs pair by the bound id or after the full
match and resolve by lookup, never by resubmission (c), `auto_remediate` is the context's (d), and a
machine restored mid-fetch is re-driven (e). It also round-trips the real bindings' context at each
state B19 rests in, and refuses a snapshot whose hash or seal does not verify. The chart is
unchanged (version 1).
"""

from __future__ import annotations

import asyncio
import dataclasses
from collections.abc import Iterator
from decimal import Decimal
from typing import Any

import pytest
from xstate_statemachine import SimulatedClock

from candleviewer.exchange.base.models import RateHeadroom
from candleviewer.oms.reconcile_standing import STALE_AFTER_S, ReconcileStanding
from candleviewer.statechart.bindings import b19_reconciliation as b19
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
from candleviewer.statechart.registry import Registry, default_registry
from tests.unit.oms.reconcile_rig import ACCOUNT, Job, leaf, remote, rest, row, started
from tests.xstate_contract._harness import Audit, Keys, Pager, Repo, entry_of
from tests.xstate_contract.membership import check_ledger

REG = default_registry()  # one validated registry for the module (the suite budget, 29 §1.7)
CHART = REG.get("reconciliation")
WINDOW_US = round(STALE_AFTER_S * 1_000_000)
KEY = MachineKey("reconciliation", str(ACCOUNT), "demo")

INVARIANTS: dict[str, str | tuple[str, ...]] = {
    "INV-B19-a": "test_inv_b19_a_the_jobs_own_faults_lock_it_rather_than_retry_forever",
    "INV-B19-b": (
        "test_e50_t14b_round5_fixes.py::"
        "test_oc05_property_inv_b19_b_only_operator_resolved_clears_lockout"
    ),
    "INV-B19-c": (
        "test_inv_b19_c_an_unknown_order_is_resolved_by_lookup_never_resubmitted",
        "test_inv_b19_c_an_order_that_fails_the_full_match_is_held_never_adopted",
    ),
    "INV-B19-d": "test_inv_b19_d_auto_remediate_is_a_context_value",
    "INV-B19-e": (
        "test_inv_b19_e_a_machine_restored_mid_fetch_is_re_driven",
        "test_inv_b19_e_a_machine_restored_backing_off_retries",
    ),
    "INV-B19-f": "test_inv_b19_f_every_sweep_persists_a_report",
}


@pytest.fixture
def job() -> Iterator[Job]:
    wired = Job()
    b19.set_ports(wired.phases)
    yield wired
    b19.set_ports(None)


def test_b19_invariant_ledger_matches_catalogue() -> None:
    check_ledger(19, INVARIANTS, globals())


def test_inv_b19_b_stale_lockout_locks_account() -> None:
    assert "lock_account_for_new_orders" in entry_of(CHART, "stale_lockout")


def test_inv_b19_f_every_sweep_persists_a_report() -> None:
    assert entry_of(CHART, "reporting")[0] == "persist_report"


def _starve(job: Job, starved: bool = True) -> None:
    tokens, wait = (0.0, 60.0) if starved else (100.0, 0.0)
    job.world.venue.set_headroom(ACCOUNT, RateHeadroom(lane="poll", tokens=tokens, wait_s=wait))


async def test_inv_b19_a_the_jobs_own_faults_lock_it_rather_than_retry_forever(job: Job) -> None:
    """A fault of the job's own (here: the stored watermark cannot be read) is a failed fetch: it
    backs off inside the stale window and locks, standing first, once the window is spent."""
    job.watermarks.refuse_read = True
    interp = await started()
    try:
        await interp.send("STARTUP")
        assert await rest(interp) == "backing_off"
        job.world.now_us += WINDOW_US
        await interp.send("RETRY_DUE")
        assert await rest(interp) == "stale_lockout"
        assert job.standing.is_stale(ACCOUNT)
    finally:
        await interp.stop()


async def test_inv_b19_c_an_unknown_order_is_resolved_by_lookup_never_resubmitted(job: Job) -> None:
    job.world.oms.seed(row(1, "unknown", exchange_order_id=None, lifecycle_state="unknown"))
    job.world.venue.seed_order(remote(1), uid="1001")  # passes the full match
    interp = await started()
    try:
        await interp.send("STARTUP")
        assert await rest(interp) == "idle"
        assert [e[2] for e in job.world.oms.effects("command")] == ["RECON_FOUND_LIVE"]
        assert [c.method for c in job.world.venue.calls if c.method == "place_order"] == []
    finally:
        await interp.stop()


async def test_inv_b19_c_an_order_that_fails_the_full_match_is_held_never_adopted(
    job: Job,
) -> None:
    job.world.oms.seed(row(1, "unknown", exchange_order_id=None, lifecycle_state="unknown"))
    job.world.venue.seed_order(remote(1, qty=Decimal(2)), uid="1001")
    interp = await started()
    try:
        await interp.send("STARTUP")
        assert await rest(interp) == "divergent"  # `held` waits for the Owner
        assert [e[2] for e in job.world.oms.effects("command")] == ["MISMATCH"]
    finally:
        await interp.stop()


@pytest.mark.parametrize("auto", [True, False])
async def test_inv_b19_d_auto_remediate_is_a_context_value(job: Job, auto: bool) -> None:
    """One chart: the build's capability decides whether a pass with divergences remediates
    (testnet reports drift and never acts, 24 Sec.14.3)."""
    job.world.oms.seed(row(1))  # found nowhere: a divergence
    interp = await started(auto_remediate=auto)
    try:
        await interp.send("STARTUP")
        assert await rest(interp) == "idle"
        assert interp.context["auto_remediate"] is auto
        assert bool(job.world.oms.effects("command")) is auto
        assert len(job.records.rows) == 1
    finally:
        await interp.stop()


# --- Persist -> restore at each state B19 rests in, with its real context ------------------------


def _restorer(registry: Registry | None = None) -> Restorer:
    return Restorer(
        registry=registry or REG,
        keys=Keys(),
        journal=InMemoryDrainJournal(),
        audit=Audit(),
        pager=Pager(),
        latch=ChainTripLatch(),
        plugins=lambda _key: [],
        clock=SimulatedClock(),
        lane="order",
    )


async def _persisted(interp: Any) -> SealedSnapshot:
    repo, keys = Repo(), Keys()
    await Persister(
        repo=repo,
        journal=InMemoryDrainJournal(),
        audit=Audit(),
        seal=hmac_sealer(keys, CHART),
        machine_hash_of=REG.hash,
        pager=Pager(),
    ).persist(interp, key=KEY)
    envelope: SealedSnapshot = repo.rows[KEY]
    return envelope


async def _at(job: Job, state: str) -> Any:
    interp = await started()
    if state == "divergent":
        job.world.oms.seed(row(3, "cancelled"))
        job.world.venue.seed_order(remote(3), uid="1001")
        await interp.send("SWEEP_DUE", trigger="manual")
    elif state in ("backing_off", "stale_lockout"):
        _starve(job)
        await interp.send("STARTUP")
        if state == "stale_lockout":
            assert await rest(interp) == "backing_off"
            job.world.now_us += WINDOW_US
            await interp.send("RETRY_DUE")
    elif state == "idle":
        await interp.send("STARTUP")
    assert await rest(interp) == state
    return interp


@pytest.mark.parametrize("state", ["idle", "divergent", "backing_off", "stale_lockout"])
async def test_a_round_trip_at_each_rest_state_restores_the_real_context(
    job: Job, state: str
) -> None:
    interp = await _at(job, state)
    before = dict(interp.context)
    envelope = await _persisted(interp)
    restored = (await _restorer().restore(KEY, envelope)).interpreter
    try:
        assert (leaf(restored), dict(restored.context)) == (state, before)
        fresh = ReconcileStanding()  # a new process: rebuilt from the restored state
        fresh.restored(ACCOUNT, leaf(restored))
        assert fresh.is_stale(ACCOUNT) is (state == "stale_lockout")
        assert b19.redrive_after_restore(state, restored.context) == (
            (("RETRY_DUE", {}),) if state == "backing_off" else ()
        )
    finally:
        await restored.stop()


async def test_inv_b19_e_a_machine_restored_backing_off_retries(job: Job) -> None:
    interp = await _at(job, "backing_off")
    envelope = await _persisted(interp)
    restored = (await _restorer().restore(KEY, envelope)).interpreter
    try:
        _starve(job, starved=False)
        plan = b19.redrive_after_restore(leaf(restored), restored.context)
        assert plan == (("RETRY_DUE", {}),)  # the host timer died with the process
        for event, payload in plan:
            await restored.send(event, **payload)
        assert await rest(restored) == "idle"
        assert len(job.records.rows) == 1
    finally:
        await restored.stop()


async def test_inv_b19_e_a_machine_restored_mid_fetch_is_re_driven(
    job: Job, monkeypatch: pytest.MonkeyPatch
) -> None:
    """LC-19: a static restore resumes no invoke, so a machine parked in `fetching` hangs unless
    the driver cancels it and sends its trigger again, its pass's id kept."""
    hold = asyncio.Event()
    real = job.phases.fetch

    async def held(*a: Any, **k: Any) -> Any:
        await hold.wait()
        return await real(*a, **k)

    monkeypatch.setattr(job.phases, "fetch", held)
    interp = await started()
    sweep = "00000000-0000-4000-8000-00000000e0e0"
    await interp.send("RECONNECTED", pass_id=sweep)
    for _ in range(64):
        await asyncio.sleep(0)
    assert leaf(interp) == "fetching"
    envelope = await _persisted(interp)  # persist stops it; its service never answers
    hold.set()
    monkeypatch.setattr(job.phases, "fetch", real)
    restored = (await _restorer().restore(KEY, envelope)).interpreter
    try:
        for _ in range(64):
            await asyncio.sleep(0)
        assert leaf(restored) == "fetching"  # parked: nothing would ever move it
        plan = b19.redrive_after_restore("fetching", restored.context)
        assert plan == (("CANCEL", {}), ("RECONNECTED", {"pass_id": sweep}))
        for event, payload in plan or ():
            await restored.send(event, **payload)
        assert await rest(restored) == "idle"
        [(_, reported, state)] = job.records.rows
        assert (reported, state["trigger"]) == (sweep, "reconnect")
    finally:
        await restored.stop()


@pytest.mark.parametrize("state", ["diffing", "remediating", "reporting"])
def test_a_state_no_event_leaves_is_rebuilt_never_resumed(state: str) -> None:
    assert b19.redrive_after_restore(state, {}) is None
    assert state not in b19.REST_STATES


@pytest.mark.parametrize("defect", ["hash", "hmac"])
async def test_a_snapshot_whose_hash_or_seal_does_not_verify_is_refused(
    job: Job, defect: str
) -> None:
    interp = await _at(job, "stale_lockout")
    envelope = await _persisted(interp)
    if defect == "hash":
        envelope = dataclasses.replace(envelope, machine_hash="0" * 64)
    else:
        forged = {**envelope.snapshot["context"], "unresolved": 7}
        envelope = dataclasses.replace(envelope, snapshot={**envelope.snapshot, "context": forged})
    audit, pager = Audit(), Pager()
    restorer = dataclasses.replace(_restorer(), audit=audit, pager=pager)
    with pytest.raises(RestoreRefusedError):
        await restorer.restore(KEY, envelope)
    assert (len(audit.quarantined), pager.pages) == (1, ["P1"])
