"""Unit (E42-T05 #966 BK-13): the restore preconditions under the backups admission lock, in the
contract's order (maintenance, nothing running, usable, positions, #3084's check last); the
`backup.restore` record each attempt writes before its answer; `cv_restore_jobs_total`; and the
job's end (SR-BK7A-02, SR-BK7A-04). Every wait is bounded (`BOUND`)."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any, cast
from uuid import UUID

import pytest

from candleviewer.admin.backups import limits, restore
from candleviewer.admin.backups.gate import BackupJobGate
from candleviewer.admin.backups.ports import JobEnd
from candleviewer.admin.backups.restore import RestoreAccepted, RestoreGuard, RestoreRefused
from candleviewer.admin.errors import OpsAuditUnavailable, OpsUnavailable
from candleviewer.api.recorder_admin import AdminJobStore
from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.backups_wiring import AdminJobRunner
from candleviewer.storage.errors import StorageTierUnavailable
from candleviewer.storage.repositories.backups import BackupStatus
from tests.unit.admin import _restore_fakes as fx
from tests.unit.admin._restore_fakes import BACKUP, BOUND, DIGEST, HANG, REASON, Rig, counted, rig

FAILURE, SUCCESS, ERROR = AuditOutcome.FAILURE, AuditOutcome.SUCCESS, Severity.ERROR
OPEN, BUSY = "open_positions_unacknowledged", "backup_or_restore_running"
REVOKED = "revocations_unacknowledged"  # the fake check's rule; #3084 names the real one
READS = ["maintenance", "row", "digest", "positions", "revocations"]
DOWN = StorageTierUnavailable("down")


@pytest.fixture
def quick(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bounds a hung port meets at once; `test_the_shipped_bounds_are_pinned` pins the real ones."""
    monkeypatch.setattr(limits, "RESTORE_READ_BUDGET_S", 0.02)
    monkeypatch.setattr(limits, "RESTORE_RECORD_BUDGET_S", 0.02)


def _record(r: Rig, n: int = 0) -> tuple[object, ...]:
    record = r.audit.records[n]
    return record["outcome"], record["reason"], record["severity"]


async def test_maintenance_off_is_409_maintenance_mode_required_and_creates_no_job() -> None:
    r, before = rig(maintenance=False), fx.restores()
    refused = await r.admit()
    assert refused == RestoreRefused("maintenance_mode_required")
    assert refused.detail == "Restore requires maintenance mode to be on."
    assert (r.jobs.jobs, r.executor.calls) == ([], [])
    assert r.trail == ["maintenance", "record:requested"]  # nothing else read; recorded first
    assert (_record(r), counted(before)) == ((FAILURE, refused.rule, ERROR), {"refused": 1.0})


async def test_two_open_positions_without_the_flag_is_409_open_positions_unacknowledged() -> None:
    r = rig(positions=2)
    refused = await r.admit(acknowledge_unknown_positions=True)  # neither flag implies the other
    assert refused == RestoreRefused(OPEN, 2)
    assert refused.detail == "2 positions are open; acknowledge them to restore."
    assert (r.jobs.jobs, r.executor.calls, _record(r)) == ([], [], (FAILURE, OPEN, ERROR))
    assert r.audit.records[0]["after_state"]["open_positions"] == 2


async def test_preconditions_are_checked_in_the_contract_order() -> None:
    r = rig(maintenance=False, row=replace(BACKUP, status="failed"), positions=None,
            revocations=REVOKED)  # fmt: skip
    async with r.gate.admit("backup_verify", BACKUP.id) as verifying:  # Q6: a verification runs
        verifying.submit(r.jobs, UUID(int=9), cast(Any, None), cast(Any, None))  # never run
    clears: dict[str, tuple[int, Callable[[], object]]] = {  # in order: reads taken, the clear
        "maintenance_mode_required": (1, lambda: r.ports.answers.update(maintenance=True)),
        BUSY: (1, lambda: r.jobs.jobs.pop()[4]()),  # the verification settles
        "backup_not_usable": (2, lambda: r.ports.answers.update(row=BACKUP)),
        "positions_unknown": (4, lambda: r.ports.answers.update(positions=0)),
        REVOKED: (5, lambda: r.ports.answers.update(revocations=None)),
    }
    for rule, (reads, clear) in clears.items():
        r.trail.clear()
        assert await r.admit() == RestoreRefused(rule)
        assert r.trail == [*READS[:reads], "record:requested"]
        clear()
    r.trail.clear()
    assert isinstance(await r.admit(), RestoreAccepted)
    assert r.trail == [*READS, "record:requested", "submit"]
    assert RestoreRefused(BUSY).detail is None
    assert RestoreRefused("positions_unknown").detail == (
        "The open-position state could not be read; acknowledge it to restore."
    )


@pytest.mark.usefixtures("quick")
@pytest.mark.parametrize(
    "answer", [None, "true", DOWN, HANG], ids=["none", "not-a-bool", "outage", "past-its-bound"]
)
async def test_unknown_maintenance_is_503_store_unavailable_never_treated_as_on(
    answer: object,
) -> None:
    r = rig(maintenance=answer)
    with pytest.raises(OpsUnavailable):
        await r.admit()
    assert r.trail == ["maintenance", "record:requested"]  # nothing past it read, no job
    assert _record(r) == (FAILURE, "store_unavailable", ERROR)


UNUSABLE = {
    "edited-or-swapped": (BACKUP, "f" * 64),
    "unbound": (BACKUP, None),
    "no-digest": (replace(BACKUP, checksum_sha256=None), DIGEST),
    "not-ascii": (replace(BACKUP, checksum_sha256="é" * 64), DIGEST),
    "running": (replace(BACKUP, status="running"), DIGEST),
    "failed": (replace(BACKUP, status="failed"), DIGEST),
    "deleted": (replace(BACKUP, deleted_at=BACKUP.started_at), DIGEST),
    "unencrypted": (replace(BACKUP, encrypted=False), DIGEST),
    "no-row": (None, DIGEST),
}


@pytest.mark.parametrize(("backup", "bound"), list(UNUSABLE.values()), ids=list(UNUSABLE))
async def test_a_backup_whose_digest_differs_from_its_bound_record_is_not_usable(
    backup: object, bound: object
) -> None:
    r = rig(row=backup, digest=bound)
    assert await r.admit() == RestoreRefused("backup_not_usable")
    assert (r.jobs.jobs, r.executor.calls) == ([], [])


@pytest.mark.parametrize("status", ["ok", "verified", "restored"])
async def test_a_usable_status_with_its_bound_digest_is_compared_in_constant_time(
    status: BackupStatus, monkeypatch: pytest.MonkeyPatch
) -> None:
    compared: list[tuple[bytes, bytes]] = []

    def spy(a: bytes, b: bytes) -> bool:
        compared.append((a, b))
        return a == b

    monkeypatch.setattr(restore, "compare_digest", spy)
    r = rig(row=replace(BACKUP, status=status))
    assert isinstance(await r.admit(), RestoreAccepted)
    assert compared == [(DIGEST.encode(), DIGEST.encode())]
    assert ("digest", BACKUP.id) in r.ports.asked and ("row", BACKUP.id) in r.ports.asked


async def test_every_attempt_is_recorded_before_the_answer_at_severity_error() -> None:
    refused, r = rig(maintenance=False), rig(positions=2)
    await refused.admit()
    accepted = await r.admit(acknowledge_open_positions=True)
    assert isinstance(accepted, RestoreAccepted) and r.trail[-2:] == ["record:requested", "submit"]
    who = {"actor_label": "owner", "actor_user_id": fx.OWNER.user_id, "actor_ip": fx.OWNER.ip,
           "session_id": fx.OWNER.session_id, "request_id": fx.OWNER.request_id}  # fmt: skip
    state = {"stage": "requested", "challenge_id": str(fx.GRANT.challenge_id),
             "components": ["config", "postgres"], "acknowledge_open_positions": False,
             "acknowledge_unknown_positions": False}  # fmt: skip
    record = {"action": "backup.restore", **who, "object_kind": "backup",
              "object_id": str(BACKUP.id), "severity": ERROR}  # fmt: skip
    assert refused.audit.records == [record | {"outcome": FAILURE,
        "reason": "maintenance_mode_required", "after_state": state}]  # fmt: skip
    state |= {"acknowledge_open_positions": True, "open_positions": 2}
    assert r.audit.records == [record | {"outcome": SUCCESS, "reason": REASON,
        "after_state": state | {"job_id": str(accepted.job_id)}}]  # fmt: skip
    assert ("revocations", BACKUP, fx.request(acknowledge_open_positions=True)) in r.ports.asked


@pytest.mark.usefixtures("quick")
@pytest.mark.parametrize("fault", [RuntimeError("audit down"), HANG], ids=["raises", "hangs"])
@pytest.mark.parametrize("maintenance", [True, False], ids=["acceptance", "refusal"])
async def test_audit_failure_is_503_and_starts_no_job(fault: object, maintenance: bool) -> None:
    r, before = rig(maintenance=maintenance), fx.restores()
    r.audit.faults["requested"] = fault
    with pytest.raises(OpsAuditUnavailable):
        await r.admit()
    assert (r.audit.records, r.jobs.jobs, r.executor.calls) == ([], [], [])
    assert counted(before) == {"refused": 1.0}  # a 503 counts too: an outage's attempts are seen


@pytest.mark.parametrize("written", [True, False], ids=["recorded", "unrecorded"])
async def test_a_lock_wait_past_its_bound_is_recorded_then_503(written: bool) -> None:
    r, before = rig(gate=BackupJobGate(admit_wait_s=0.01)), fx.restores()
    if not written:
        r.audit.faults["requested"] = RuntimeError("audit down")
    async with r.gate.admit_delete(BACKUP.id):  # a delete holds the lock
        with pytest.raises(OpsUnavailable if written else OpsAuditUnavailable):
            await r.admit()
    assert r.trail == (["record:requested"] if written else [])  # the grant is spent, nothing read
    records = [(x["outcome"], x["reason"], x["severity"]) for x in r.audit.records]
    assert records == ([(FAILURE, "store_unavailable", ERROR)] if written else [])
    assert counted(before) == {"refused": 1.0}


@pytest.mark.usefixtures("quick")
@pytest.mark.parametrize("fault", [DOWN, HANG], ids=["raises", "past-its-bound"])
@pytest.mark.parametrize("read", ["row", "digest", "revocations"])
async def test_an_unread_precondition_is_503_store_unavailable(read: str, fault: object) -> None:
    answers: dict[str, Any] = {read: fault}
    r = rig(**answers)
    with pytest.raises(OpsUnavailable):
        await r.admit()
    assert r.trail == [*READS[: READS.index(read) + 1], "record:requested"]
    assert (_record(r), r.jobs.jobs) == ((FAILURE, "store_unavailable", ERROR), [])


@pytest.mark.usefixtures("quick")
@pytest.mark.parametrize("fault", [DOWN, HANG, -1], ids=["raises", "past-its-bound", "negative"])
async def test_unreadable_positions_are_unknown_never_zero(fault: object) -> None:
    r = rig(positions=fault)
    assert await r.admit() == RestoreRefused("positions_unknown")
    assert r.audit.records[0]["after_state"]["open_positions"] is None
    assert await r.admit(acknowledge_open_positions=True) == RestoreRefused("positions_unknown")
    assert isinstance(await r.admit(acknowledge_unknown_positions=True), RestoreAccepted)


@pytest.mark.parametrize("count", [1, 3])
async def test_any_open_position_needs_its_acknowledgement(count: int) -> None:
    r = rig(positions=count)
    assert await r.admit() == RestoreRefused(OPEN, count)
    assert isinstance(await r.admit(acknowledge_open_positions=True), RestoreAccepted)


async def test_any_answer_but_none_from_the_revocations_check_refuses() -> None:
    assert await rig(revocations="").admit() == RestoreRefused("")  # a faulty check fails closed


async def test_two_concurrent_restores_admit_one() -> None:
    r = rig()
    r.ports.held["positions"] = held = asyncio.Event()
    async with asyncio.timeout(BOUND):
        first = asyncio.create_task(r.admit())
        await r.ports.started("positions").wait()  # the first holds the lock at that read
        second = asyncio.create_task(r.admit())
        for _ in range(10):
            await asyncio.sleep(0)
        assert r.trail.count("maintenance") == 1  # the second waits for the lock, unread
        held.set()
        answers = await asyncio.gather(first, second)
    assert list(answers) == [RestoreAccepted(r.jobs.jobs[0][1]), RestoreRefused(BUSY)]
    assert len(r.jobs.jobs) == 1


def test_the_executor_is_reachable_only_through_the_guard() -> None:
    package = Path(restore.__file__).resolve().parents[2]
    naming = sorted(
        path.relative_to(package).as_posix()
        for path in package.rglob("*.py")
        if "RestoreExecutor" in path.read_text(encoding="utf-8")
    )
    assert naming == ["admin/backups/ports.py", "admin/backups/restore.py"]  # BK-14: the wiring
    guard = rig().guard
    assert [name for name in dir(guard) if not name.startswith("_")] == ["admit"]
    assert all(slot.startswith("_") for slot in RestoreGuard.__slots__)
    assert not hasattr(guard, "__dict__")


def test_no_guard_is_built_without_the_revocations_check() -> None:
    r = rig()
    ports: dict[str, Any] = {"rows": r.ports, "evidence": r.ports, "maintenance": r.ports}
    ports |= {"positions": r.ports, "gate": r.gate, "jobs": r.jobs, "audit": r.audit}
    with pytest.raises(TypeError):
        RestoreGuard(r.executor, **ports)  # no default
    with pytest.raises(TypeError, match="revocations"):
        RestoreGuard(r.executor, revocations=cast(Any, None), **ports)


@pytest.mark.parametrize("status", ["succeeded", "failed"])
async def test_a_job_end_is_recorded_first_then_counted(status: str) -> None:
    r, before = rig(), fx.restores()
    ok, error = status == "succeeded", None if status == "succeeded" else "verify_failed"
    await r.admit()
    _, _, work, done, _ = r.jobs.jobs[0]
    async with asyncio.timeout(BOUND):
        assert await work(lambda pct: None) == {"backup_id": str(BACKUP.id)}  # not the engine's
        await done(JobEnd("succeeded", None, None) if ok else JobEnd("failed", None, error))
    assert r.executor.calls == [(BACKUP.id, BACKUP.target_path, fx.COMPONENTS)]
    assert r.audit.counts[-1] == before  # the end's record came before its count
    assert _record(r, -1) == (SUCCESS if ok else FAILURE, error, ERROR)
    finished = r.audit.records[0]["after_state"] | {"stage": "finished", "result": status}
    assert (r.audit.records[-1]["after_state"], counted(before)) == (finished, {status: 1.0})


@pytest.mark.usefixtures("quick")
@pytest.mark.parametrize("status", ["succeeded", "failed"])
async def test_an_unwritten_end_still_counts_and_a_succeeded_job_says_so(status: str) -> None:
    r, before = rig(), fx.restores()
    r.audit.faults["finished"] = HANG
    await r.admit()
    _, _, work, done, _ = r.jobs.jobs[0]
    async with asyncio.timeout(BOUND):  # its record past its bound (SR-BK7A-02)
        result, ok = await work(lambda pct: None), status == "succeeded"
        await done(JobEnd("succeeded", result, None) if ok else JobEnd("failed", None, "x"))
    assert result == {"backup_id": str(BACKUP.id)} | ({"audit": "unavailable"} if ok else {})
    assert counted(before) == {status: 1.0}


async def test_a_job_that_cannot_start_ends_its_record_failed() -> None:
    r, before = rig(), fx.restores()
    r.jobs.error = RuntimeError("no job store")
    with pytest.raises(RuntimeError):
        await r.admit()
    stages = [(x["after_state"]["stage"], x["outcome"], x["reason"]) for x in r.audit.records]
    assert stages == [("requested", SUCCESS, REASON), ("finished", FAILURE, "internal_error")]
    assert (r.gate.active(), counted(before)) == ([], {"failed": 1.0})


async def test_a_deadline_cancelled_restore_keeps_trading_halted_and_writes_its_end() -> None:
    store, before = AdminJobStore(), fx.restores()
    r = rig(gate=BackupJobGate(deadlines_s={"backup_restore": 0.01}), runner=AdminJobRunner(store))
    r.executor.outcome = HANG  # a restore that outlasts its deadline (SR-BK7A-04)
    accepted = await r.admit()
    assert isinstance(accepted, RestoreAccepted)
    async with asyncio.timeout(BOUND):
        await r.audit.finished.wait()  # its count follows in the same step
    for _ in range(10):  # scheduler turns: the job settles
        await asyncio.sleep(0)
    assert r.executor.halted  # pin 1: only the executor's step 8 lifts it, no cancel path here
    job = store.get(str(accepted.job_id))  # pin 2: the finished record, then the count
    assert job is not None and (job.status, job.error) == ("failed", "internal_error")
    assert r.trail[-2:] == ["restore", "record:finished"]
    assert _record(r, -1) == (FAILURE, "internal_error", ERROR)
    finished = r.audit.records[0]["after_state"] | {"stage": "finished", "result": "cancelled"}
    assert (r.audit.records[-1]["after_state"], counted(before)) == (finished, {"cancelled": 1.0})


def test_the_shipped_bounds_are_pinned() -> None:
    assert (limits.RESTORE_READ_BUDGET_S, limits.RESTORE_RECORD_BUDGET_S) == (2.0, 2.0)
