"""Unit (E42-T05 #966 BK-13): the restore preconditions under the backups admission lock, in the
contract's order (maintenance, nothing running, usable, positions, #3084's check last), and their
matrix; the `backup.restore` record each attempt writes before its answer; `cv_restore_jobs_total`;
the job's end (SR-BK7A-02, SR-BK7A-04); and `FlagStoreMaintenance`, the guard's fresh maintenance
read. Every wait is bounded (`BOUND`) or runs on the loop's fake clock."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import UUID

import pytest
from structlog.testing import capture_logs

from candleviewer.admin.backups import limits, restore
from candleviewer.admin.backups.gate import BackupJobGate
from candleviewer.admin.backups.ports import JobEnd
from candleviewer.admin.backups.restore import RestoreAccepted, RestoreGuard, RestoreRefused
from candleviewer.admin.errors import OpsAuditUnavailable, OpsUnavailable
from candleviewer.api.recorder_admin import AdminJobStore
from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.backups_wiring import AdminJobRunner, FlagStoreMaintenance
from candleviewer.storage.errors import StorageTierUnavailable
from candleviewer.storage.repositories.backups import BackupStatus
from candleviewer.storage.repositories.flags_sqlalchemy import FlagRow
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
    assert r.gate.active() == [("backup_restore", BACKUP.id)]  # what refuses its delete (F1)
    assert RestoreRefused(BUSY).detail is None
    assert RestoreRefused("positions_unknown").detail == (
        "The open-position state could not be read; acknowledge it to restore."
    )


@pytest.mark.parametrize("ack_unknown", [False, True])
@pytest.mark.parametrize("ack_open", [False, True])
@pytest.mark.parametrize("positions", list(fx.POSITIONS))
@pytest.mark.parametrize("maintenance", list(fx.MAINTENANCE))
async def test_precondition_matrix(
    maintenance: str, positions: str, ack_open: bool, ack_unknown: bool
) -> None:
    r = rig(maintenance=fx.MAINTENANCE[maintenance], positions=fx.POSITIONS[positions])
    before = fx.restores()
    acks = {"acknowledge_open_positions": ack_open, "acknowledge_unknown_positions": ack_unknown}
    rule = fx.expected(maintenance, positions, ack_open, ack_unknown)
    accepted = rule == "accepted"
    try:
        answer: object = await r.admit(**acks)
    except OpsUnavailable:
        answer = "503"  # raised, never a returned refusal of that name (N3)
    if accepted:
        assert answer == RestoreAccepted(r.jobs.jobs[0][1])
    else:
        assert getattr(answer, "rule", answer) == rule
    assert (len(r.jobs.jobs), r.executor.calls) == (int(accepted), [])  # only a job restores
    (record,) = r.audit.records
    reason = "store_unavailable" if rule == "503" else rule
    assert _record(r) == ((SUCCESS, REASON) if accepted else (FAILURE, reason)) + (ERROR,)
    assert {key: record["after_state"][key] for key in acks} == acks
    assert counted(before) == ({} if accepted else {"refused": 1.0})


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


_NO_ROW = object()


class _Flags:
    """`SqlAlchemyFlagRepository.load()` with `stored` as `maintenance.mode`'s value; its
    overrides say "on", which never counts for a kill switch."""

    def __init__(self, stored: object) -> None:
        self.stored, self.loads = stored, 0

    async def load(self) -> Mapping[str, FlagRow]:
        self.loads += 1
        if self.stored is HANG:
            await asyncio.Event().wait()
        if isinstance(self.stored, BaseException):
            raise self.stored
        at = datetime(2026, 10, 19, tzinfo=UTC)
        flag = FlagRow(self.stored, {UUID(int=1): True}, {"owner": True}, at, None)
        return {} if self.stored is _NO_ROW else {"maintenance.mode": flag}


STORED = {  # what `maintenance.mode` holds: (what the read answers, the error class it logs)
    "on": (True, True, None),
    "off": (False, False, None),
    "outage": (DOWN, None, "StorageTierUnavailable"),
    "error": (RuntimeError("bug"), None, "RuntimeError"),
    "past-the-budget": (HANG, None, "TimeoutError"),
    "string": ("true", None, None),
    "number": (1, None, None),
    "null": (None, None, None),
    "no-row": (_NO_ROW, None, None),
}


@pytest.mark.parametrize(("stored", "read", "error"), STORED.values(), ids=list(STORED))
async def test_flag_store_outage_never_reads_as_maintenance_on(
    stored: object, read: bool | None, error: str | None
) -> None:
    maintenance = FlagStoreMaintenance(_Flags(stored), read_budget_ms=20)
    with capture_logs() as logs:
        async with asyncio.timeout(BOUND):
            assert await maintenance.read() is read
    unread = {"event": "backups.maintenance_unread", "error": error, "log_level": "warning"}
    assert logs == ([] if error is None else [unread])  # the class only, never its text (N2)


async def test_the_maintenance_read_is_cut_at_the_default_flag_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loop, now = asyncio.get_running_loop(), [1000.0]
    monkeypatch.setattr(loop, "time", lambda: now[0])  # the loop's fake clock: no real wait (M1)
    reading = asyncio.create_task(FlagStoreMaintenance(_Flags(HANG)).read())
    try:
        for now[0], cut in ((1000.0, False), (1000.499, False), (1000.5, True)):
            for _ in range(5):
                await asyncio.sleep(0)
            assert reading.done() is cut  # 500 ms, `flags.read_budget_ms`'s default
        assert reading.result() is None
    finally:
        reading.cancel()
        await asyncio.gather(reading, return_exceptions=True)


async def test_the_maintenance_read_is_fresh_on_every_call() -> None:
    flags = _Flags(True)
    maintenance = FlagStoreMaintenance(flags, read_budget_ms=20)
    async with asyncio.timeout(BOUND):
        first = await maintenance.read()
        flags.stored = False  # the row changes between two restores (M2)
        assert (first, await maintenance.read(), flags.loads) == (True, False, 2)


async def test_a_cancelled_maintenance_read_is_not_swallowed() -> None:
    reading = asyncio.create_task(FlagStoreMaintenance(_Flags(HANG)).read())
    for _ in range(3):
        await asyncio.sleep(0)
    reading.cancel()  # a shutdown or a cancelled request (N1)
    with pytest.raises(asyncio.CancelledError):
        await reading


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


def test_a_request_names_at_least_one_component() -> None:
    with pytest.raises(ValueError, match="component"):  # never read as "all" or "none"
        fx.request(components=frozenset())


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
        "reason": "maintenance_mode_required",
        "after_state": state | {"operator_reason": REASON}}]  # fmt: skip
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
    state = r.audit.records[-1]["after_state"]  # the acknowledgement recorded as given (F3)
    assert (state["acknowledge_unknown_positions"], state["acknowledge_open_positions"]) == (
        True,
        False,
    )


@pytest.mark.parametrize("count", [1, 3])
async def test_any_open_position_needs_its_acknowledgement(count: int) -> None:
    r = rig(positions=count)
    assert await r.admit() == RestoreRefused(OPEN, count)
    assert isinstance(await r.admit(acknowledge_open_positions=True), RestoreAccepted)


async def test_any_answer_but_none_from_the_revocations_check_refuses() -> None:
    assert await rig(revocations="").admit() == RestoreRefused("")  # a faulty check fails closed


@pytest.mark.parametrize("parked", ["read", "record"])
async def test_a_cancel_parked_at_a_read_or_a_record_is_not_swallowed(parked: str) -> None:
    r = rig(maintenance=parked == "read")  # off: the refusal's record is where it parks
    if parked == "read":
        r.ports.held["maintenance"] = asyncio.Event()
    else:
        r.audit.faults["requested"] = HANG
    admitting = asyncio.create_task(r.admit())
    for _ in range(10):
        await asyncio.sleep(0)
    assert (r.trail, len(r.audit.counts)) == (["maintenance"], int(parked == "record"))
    admitting.cancel()  # a shutdown or a cancelled request (F2)
    with pytest.raises(asyncio.CancelledError):
        await admitting
    assert (r.audit.records, r.jobs.jobs, r.gate.active()) == ([], [], [])
    r.ports.held.clear()
    r.audit.faults.clear()
    assert await r.admit() is not None  # the lock was let go: the next admission is answered


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
    seen: list[float] = []
    async with asyncio.timeout(BOUND):
        assert await work(seen.append) == {"backup_id": str(BACKUP.id)}  # not the engine's
        await done(JobEnd("succeeded", None, None) if ok else JobEnd("failed", None, error))
    assert r.executor.calls == [(BACKUP.id, BACKUP.target_path, fx.COMPONENTS)]
    assert seen == [50.0]  # the executor's progress reaches the job (F4)
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
