"""Unit (E42-T05 #966 BK-9): a verification started in the plan's order, its job digest first, and
its outcome written in the job under the admission lock (contract-D; the coordinator's 09:00Z
decisions). Jobs run in the real admin job store; the trail joins records and row writes in order.
"""

from __future__ import annotations

import asyncio
import hmac
import inspect
import itertools
from collections.abc import Callable, Coroutine
from dataclasses import replace
from typing import Any
from uuid import UUID

import pytest
from structlog.testing import capture_logs

from candleviewer.admin.backups import limits, metrics, verify
from candleviewer.admin.backups.catalogue import BackupCatalogue
from candleviewer.admin.backups.gate import BackupConflict, BackupJobGate
from candleviewer.admin.backups.ports import BackupJobError, RunRecord
from candleviewer.admin.backups.verify import BackupVerifications, VerifiesLimited, VerifyNotUsable
from candleviewer.admin.errors import OpsAuditUnavailable, OpsNotWired, OpsUnavailable
from candleviewer.api._generated import openapi_models as api
from candleviewer.api.audit_limiter import AuditVerifyLimiter
from candleviewer.audit.models import Severity
from candleviewer.storage.backup_artefacts import ArtefactMissing, ArtefactUnreadable
from candleviewer.storage.repositories.audit_sqlalchemy import AuditReadBusy
from candleviewer.storage.repositories.backups import BackupRow
from tests.unit.admin import _run_fakes as rf
from tests.unit.admin._backup_fakes import row
from tests.unit.admin._run_fakes import BOUND, NOW, OWNER

ROW = row(1)  # `verified`, a single file whose `checksum_sha256` is `f"{1:064x}"`
SUM, OTHER = str(ROW.checksum_sha256), "f" * 64
JOB = UUID(int=2001)  # a world's first verification
_STARTED = [("record", "requested")]


def verified(stage: str, /, **over: Any) -> dict[str, Any]:
    """The whole `backup.verified` record of `ROW`'s first verification by the owner."""
    return rf.expected(stage, ROW.id, job_id=str(JOB), **over) | {"action": "backup.verified"}


def failed(code: str, severity: Severity = Severity.WARNING) -> dict[str, Any]:
    return verified("finished", error=code, reason=code, **(rf.FAILED | {"severity": severity}))


class Store(rf.Catalogue):
    """BK-3's verification write; the guard is BK-3's (`test_backups_sqlalchemy.py`)."""

    def __init__(self, trail: rf.Trail, faults: rf.Faults) -> None:
        super().__init__(trail, faults)
        self.marks: list[tuple[str, str | None]] = []

    async def record_verify_outcome(
        self, backup_id: UUID, *, method: str, at: Any, error: Any
    ) -> BackupRow | None:
        self.marks.append((method, error))
        await self.faults.at("mark")
        new: Any = {"status": "failed", "error_message": error}
        if error is None:
            new = {"status": "verified", "error_message": None, "verified_at": at}
        self.rows[backup_id] = marked = replace(self.rows[backup_id], **new)
        self.trail.append(("mark", marked.status))
        return marked


class File:
    """An `OpenArtefact` whose SHA-256 is `hex`; it counts its closes."""

    size = 1001

    def __init__(self, faults: rf.Faults) -> None:
        self.faults, self.hex, self.closes = faults, SUM, 0

    async def digest(self) -> str:
        await self.faults.at("digest")
        return str(self.hex)

    async def stream(self) -> Any:  # the fake verifier reads nothing
        yield b""

    def close(self) -> None:
        self.closes += 1


class Engine:
    """The artefact reader, the engine's `ScratchVerifier`, the run evidence, the freshness."""

    def __init__(self, faults: rf.Faults) -> None:
        self.faults, self.file, self.method = faults, File(faults), "restore_smoke"
        self.record: RunRecord | None = RunRecord(SUM)
        self.resolved, self.verified = list[str](), list[tuple[object, ...]]()
        self.go, self.fresh = asyncio.Event(), list[tuple[str, str]]()
        self.go.set()

    async def run_record(self, backup_id: UUID) -> RunRecord | None:
        await self.faults.at("evidence")
        return self.record

    async def resolve(self, location: str) -> File:
        self.resolved.append(location)
        await self.faults.at("resolve")
        return self.file

    async def verify(self, backup_id: UUID, location: str, artefact: Any, progress: Any) -> Any:
        self.verified.append((backup_id, location, artefact))
        progress(50.0)
        await self.go.wait()
        await self.faults.at("verify")
        return self.method

    def record_success(self, row: BackupRow) -> None:  # the freshness's two calls, kept too
        self.fresh.append(("success", row.status))

    async def recompute(self, row: BackupRow) -> None:
        self.fresh.append(("recompute", row.status))


class World:
    """A `BackupVerifications` over these fakes, `ROW` in the catalogue as `over` sets it."""

    def __init__(self, *, unwired: str = "", wait_s: float = 5.0, deadline_s: float = 600.0,
                 **over: Any) -> None:  # fmt: skip
        self.trail, self.faults, self.jobs = rf.Trail(), rf.Faults(), rf.Jobs()
        self.limit = rf.Limit()
        self.audit, self.store = rf.Audit(self.trail, self.faults), Store(self.trail, self.faults)
        self.store.rows[ROW.id] = self.row = replace(ROW, **over)
        self.engine = Engine(self.faults)
        self.gate = BackupJobGate(admit_wait_s=wait_s, deadlines_s={"backup_verify": deadline_s})
        ids = itertools.count(2001)
        ports: list[Any] = [None if unwired == p else x for p, x in (("store", self.store),
                 ("verifier", self.engine), ("reader", self.engine))]  # fmt: skip
        self.service = BackupVerifications(
            BackupCatalogue(self.store), *ports, evidence=self.engine, gate=self.gate,
            jobs=self.jobs, audit=self.audit, limit=self.limit, freshness=self.engine,
            now=lambda: NOW, new_id=lambda: UUID(int=next(ids)),
        )  # fmt: skip

    async def start(self, backup_id: UUID = ROW.id) -> UUID | None:
        async def write_ahead(backup: UUID, job: UUID) -> None:
            await self.service.audit_requested(OWNER, backup, job)

        async with asyncio.timeout(BOUND):
            return await self.service.start(OWNER, backup_id, write_ahead=write_ahead)

    async def ended(self, job: UUID = JOB) -> Any:
        async with asyncio.timeout(BOUND):
            await self.jobs.settled.wait()
        self.jobs.settled.clear()
        return self.jobs.store.get(str(job))

    async def run(self) -> Any:
        await self.start()
        return await self.ended()

    def fail(self, step: str, how: str, fault: BaseException | None = None) -> None:
        if how == "hangs":
            self.faults.hangs.add(step)
        else:
            self.faults.raises[step] = fault or OSError("/var/lib/cv/audit/wal.bin: no space left")

    def unchanged(self) -> bool:
        return (self.store.rows[ROW.id], self.store.marks) == (self.row, [])


@pytest.fixture
def counted(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    seen: list[str] = []
    monkeypatch.setattr(verify, "count_verify_failure", seen.append)
    return seen


@pytest.mark.parametrize("unwired", ["store", "verifier", "reader"])
async def test_an_unwired_verifier_is_501_and_writes_nothing(unwired: str) -> None:
    w = World(unwired=unwired)
    with pytest.raises(OpsNotWired):
        await w.start()
    assert (w.trail, w.gate.active()) == ([], [])


async def test_an_unknown_backup_is_none_and_writes_nothing() -> None:
    w = World()
    assert await w.start(UUID(int=99)) is None
    assert (w.trail, w.limit.starts, w.jobs.store.held()) == ([], [], 0)


@pytest.mark.parametrize(
    "over", [{"status": "running"}, {"deleted_at": NOW}, {"encrypted": False}], ids=str
)
async def test_running_deleted_or_plaintext_backup_is_409_backup_not_usable(over: Any) -> None:
    w = World(**over)
    with pytest.raises(VerifyNotUsable):
        await w.start()
    assert (w.trail, w.limit.starts, w.jobs.store.held(), w.gate.active()) == ([], [], 0, [])


async def test_thirteenth_verification_in_an_hour_is_429() -> None:
    w = World()
    limiter = AuditVerifyLimiter(rate_per_hour=limits.VERIFIES_PER_HOUR, clock=lambda: 1000.0)
    w.service._limit = limiter  # a fixed clock: the wait is exactly an hour (C-13.7)
    for n in range(12):  # one at a time: each ends before the next starts
        await w.start()
        await w.ended(UUID(int=2001 + n))
    with pytest.raises(VerifiesLimited) as refused:
        await w.start()
    assert (refused.value.retry_after_s, len(w.audit.records)) == (3600, 24)
    assert limiter._rate == 12  # the contract's "at most 12 verifications in a rolling hour"


async def test_a_spent_limit_is_429_without_waiting_for_the_lock() -> None:
    w = World()
    w.limit.wait = 60
    async with w.gate.serialized():  # held past the test's bound
        with pytest.raises(VerifiesLimited):
            await w.start()
    assert (w.trail, w.limit.starts) == ([], [])


async def test_a_spent_limit_seen_under_the_lock_is_429_and_writes_nothing() -> None:
    w, answers = World(), iter([None, 60])  # free before the lock, spent once it is held
    w.limit.retry_after = lambda user: next(answers)  # type: ignore[method-assign]  # stubbed answers
    with pytest.raises(VerifiesLimited):
        await w.start()
    assert (w.trail, w.limit.starts, w.gate.active()) == ([], [], [])


async def test_second_verification_is_409_verify_running() -> None:
    w = World()
    w.engine.go.clear()
    await w.start()
    with pytest.raises(BackupConflict, match=r"^verify_running$"):
        await w.start()
    assert (w.trail, w.limit.starts) == (_STARTED, [str(OWNER.user_id)])
    w.engine.go.set()
    await w.ended()


async def test_a_busy_lock_is_503_before_any_record() -> None:
    w = World(wait_s=0.05)
    async with w.gate.serialized():
        with pytest.raises(OpsUnavailable):
            await w.start()
    assert (w.trail, w.limit.starts, w.gate.active()) == ([], [], [])


@pytest.mark.parametrize("gone", [False, True])  # gone: never on Postgres, where rows stay
async def test_a_delete_that_landed_while_it_waited_is_409(gone: bool) -> None:
    w = World()
    async with w.gate.serialized():  # held, as a delete holds it
        pending = asyncio.create_task(w.start())
        await asyncio.sleep(0)  # one scheduler turn: it read the row and waits for the lock
        w.store.rows = {} if gone else {ROW.id: replace(ROW, deleted_at=NOW)}
    (answer,) = await asyncio.gather(pending, return_exceptions=True)
    assert type(answer) is (type(None) if gone else VerifyNotUsable)  # a row gone is unknown
    assert (w.trail, w.limit.starts) == ([], [])


@pytest.mark.parametrize(("how", "error"), [("raises", "OSError"), ("hangs", "TimeoutError")])
async def test_audit_failure_is_503_and_schedules_nothing(
    how: str, error: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(limits, "RECORD_BUDGET_S", 0.05)
    w = World()
    w.fail("requested", how)
    with capture_logs() as logs, pytest.raises(OpsAuditUnavailable):
        await w.start()
    assert (w.trail, w.limit.starts, w.jobs.store.held(), w.gate.active()) == ([], [], 0, [])
    where = {"stage": "requested", "backup_id": str(ROW.id), "log_level": "error"}
    assert logs == [{"event": "backups.verify_unrecorded", **where, "error": error}]


@pytest.mark.parametrize("status", ["ok", "verified", "restored", "failed"])
async def test_matching_digest_reaches_the_verifier_and_sets_verified_at(
    status: str, counted: list[str]
) -> None:
    w = World(status=status, error_message="verify_failed" if status == "failed" else None)
    job_id = await w.start()
    job = await w.ended()
    result = {"backup_id": str(ROW.id), "verify_method": "restore_smoke"}
    assert (job_id, job.status, job.result) == (JOB, "succeeded", result)
    assert w.engine.verified == [(ROW.id, ROW.target_path, w.engine.file)]  # the file it hashed
    marked = w.store.rows[ROW.id]
    assert (marked.status, marked.verified_at, marked.error_message) == ("verified", NOW, None)
    finished = verified("finished", error=None, verify_method="restore_smoke")
    assert (w.audit.records, w.store.marks) == ([verified("requested"), finished],
                                                [("restore_smoke", None)])  # fmt: skip
    assert (w.engine.fresh, w.engine.file.closes, counted) == ([("success", "verified")], 1, [])
    api.Job.model_validate(job.view())


async def test_digest_mismatch_fails_the_job_with_checksum_mismatch_and_marks_the_row_failed(
    counted: list[str],
) -> None:
    """The acceptance scenario "Backup verification fails", in the service."""
    w = World()
    w.engine.file.hex = OTHER  # the file on disk is not the one the run recorded
    view = api.Job.model_validate((await w.run()).view())
    assert (view.status, view.error, view.result) == ("failed", "checksum_mismatch", None)
    marked = w.store.rows[ROW.id]
    assert (marked.status, marked.error_message) == ("failed", "checksum_mismatch")
    assert marked.verified_at == ROW.verified_at  # the last pass stands
    mismatch = failed("checksum_mismatch", Severity.ERROR)  # possible tampering: decision 12
    assert w.audit.records == [verified("requested"), mismatch]
    assert (w.engine.verified, counted) == ([], ["checksum_mismatch"])
    assert (w.engine.fresh, w.engine.file.closes) == ([("recompute", "failed")], 1)


@pytest.mark.parametrize(
    ("on_disk", "bound", "on_row"),
    [(OTHER, SUM, SUM), (SUM, OTHER, SUM), (SUM, SUM, None), (SUM, None, SUM)],
    ids=["file", "bound-record", "row-has-none", "record-has-none"],
)
async def test_mismatch_never_calls_the_verifier(on_disk: str, bound: str, on_row: str) -> None:
    w = World(checksum_sha256=on_row)
    w.engine.file.hex, w.engine.record = on_disk, RunRecord(bound)
    assert ((await w.run()).error, w.engine.verified) == ("checksum_mismatch", [])
    assert w.store.rows[ROW.id].status == "failed"
    assert w.audit.records[-1] == failed("checksum_mismatch", Severity.ERROR)


@pytest.mark.parametrize(("on_row", "bound"), [(SUM, OTHER), (OTHER, SUM)], ids=["record", "row"])
async def test_both_digests_are_compared_in_constant_time(
    on_row: str, bound: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both comparisons always run, whichever digest differs (`&`, never a short circuit)."""
    seen: list[tuple[bytes, bytes]] = []

    def compare(actual: bytes, expected: bytes) -> bool:
        seen.append((actual, expected))
        return actual == expected

    monkeypatch.setattr(hmac, "compare_digest", compare)
    w = World(checksum_sha256=on_row)
    w.engine.record = RunRecord(bound)
    await w.run()
    assert seen == [(SUM.encode(), on_row.encode()), (SUM.encode(), bound.encode())]


async def test_no_bound_record_is_checksum_unbound() -> None:
    w = World()
    w.engine.record, w.service._freshness = None, None  # no freshness wired (#3319): none moved
    assert (await w.run()).error == "checksum_unbound"
    assert (w.engine.resolved, w.engine.verified) == ([], [])
    assert w.store.rows[ROW.id].error_message == "checksum_unbound"


@pytest.mark.parametrize(("on_disk", "status"), [(SUM, "verified"), (OTHER, "failed")])
async def test_verified_record_precedes_the_row_update(on_disk: str, status: str) -> None:
    w = World()
    w.engine.file.hex = on_disk
    await w.run()
    assert w.trail == [*_STARTED, ("record", "finished"), ("mark", status)]


async def test_a_directory_or_repository_is_verified_where_it_lies() -> None:
    w = World(checksum_sha256=None)
    w.engine.record = RunRecord(None)  # the run bound no digest (Q8)
    assert (await w.run()).status == "succeeded"
    assert (w.engine.resolved, w.engine.verified) == ([], [(ROW.id, ROW.target_path, None)])


_CONCLUSIVE = [  # (step, fault, the verifier's method, code)
    ("resolve", ArtefactMissing(), "restore_smoke", "artefact_missing"),
    ("verify", BackupJobError("verify_failed"), "restore_smoke", "verify_failed"),
    ("verify", ValueError("corrupt"), "restore_smoke", "verify_failed"),  # SR-CD2-02: content
    ("verify", BackupJobError("checksum_mismatch"), "restore_smoke", "verify_failed"),
    ("verify", BackupJobError("internal_error"), "restore_smoke", "verify_failed"),
    ("verify", None, "md5", "verify_failed"),  # a report outside the closed set: no pass
]


@pytest.mark.parametrize(("step", "fault", "method", "code"), _CONCLUSIVE)
async def test_a_conclusive_failure_marks_the_row_failed(
    step: str, fault: Exception | None, method: str, code: str, counted: list[str]
) -> None:
    """SR-CD2-02: a content failure inside the verifier is `verify_failed`, never internal."""
    w = World()
    w.engine.method, w.faults.raises[step] = method, [fault]  # its one call raises `fault`
    assert (await w.run()).error == code
    assert w.audit.records[-1] == failed(code) and w.trail[-1] == ("mark", "failed")
    assert (counted, w.engine.fresh) == ([code], [("recompute", "failed")])
    assert w.engine.file.closes == (step == "verify")  # a refused resolve opened nothing


async def _raising(row: BackupRow) -> None:
    raise RuntimeError("the freshness broke")


async def _hanging(row: BackupRow) -> None:
    await asyncio.Event().wait()


@pytest.mark.parametrize("reload", [_raising, _hanging], ids=["raises", "hangs"])
async def test_a_freshness_reload_that_fails_neither_changes_the_end_nor_holds_the_lock(
    reload: Callable[[BackupRow], Coroutine[Any, Any, None]],
    counted: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Contained, and bounded under the admission lock (SR-BK7A-02, C-2.18)."""
    monkeypatch.setattr(verify, "READ_BUDGET_S", 0.05)
    w = World()
    w.engine.file.hex = OTHER
    w.engine.recompute = reload  # type: ignore[method-assign,assignment]  # a freshness that fails
    assert ((await w.run()).error, counted) == ("checksum_mismatch", ["checksum_mismatch"])
    assert w.store.rows[ROW.id].status == "failed"
    async with asyncio.timeout(BOUND), w.gate.serialized(0.05):  # the lock is free again
        pass


def _broken(row: BackupRow) -> None:
    raise RuntimeError("the freshness broke")


async def test_a_pass_whose_freshness_fails_still_succeeds(counted: list[str]) -> None:
    """`record_success` is contained like `recompute`; the row, the record and the job stand."""
    w = World()
    w.engine.record_success = _broken  # type: ignore[method-assign]  # a freshness that fails
    job = await w.run()
    assert (job.status, w.store.rows[ROW.id].status, counted) == ("succeeded", "verified", [])
    assert w.audit.records[-1] == verified("finished", error=None, verify_method="restore_smoke")


_INCONCLUSIVE = [
    ("evidence", "raises", "store_unavailable"),  # the trail's read
    ("evidence", "hangs", "store_unavailable"),
    ("resolve", "raises", "store_unavailable"),  # the volume's
    ("resolve", "hangs", "store_unavailable"),
    ("digest", "raises", "store_unavailable"),
    ("digest", "breaks", "internal_error"),
    ("verify", "raises", "store_unavailable"),  # its stream of the volume
    ("verify", "stores", "store_unavailable"),  # the engine's own store
    ("verify", "hangs", "internal_error"),  # past the check's budget: a job past its deadline
]


@pytest.mark.parametrize(("step", "how", "code"), _INCONCLUSIVE)
async def test_an_inconclusive_end_is_recorded_and_leaves_the_row(
    step: str, how: str, code: str, counted: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(limits, "EVIDENCE_BUDGET_S", 0.05)
    monkeypatch.setattr(limits, "VERIFY_RESOLVE_BUDGET_S", 0.05)
    monkeypatch.setattr(limits, "RESOLVE_BUDGET_S", 600.0)  # the link issue's: never this one
    w = World()
    w.service._check_s = 0.2
    unread = AuditReadBusy() if step == "evidence" else ArtefactUnreadable()
    other = {"breaks": ValueError("closed"), "stores": BackupJobError("store_unavailable")}
    w.fail(step, how, other.get(how, unread))
    assert (await w.run()).error == code
    assert w.unchanged() and w.audit.records[-1] == failed(code)
    assert (counted, w.engine.fresh) == ([code], [])
    assert w.engine.file.closes == (step in ("digest", "verify"))


@pytest.mark.parametrize(("on_disk", "check"), [(SUM, None), (OTHER, "checksum_mismatch")])
async def test_a_lock_wait_past_its_bound_ends_store_unavailable_and_still_records(
    on_disk: str, check: str | None, counted: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(limits, "OUTCOME_WAIT_S", 0.05)  # not `ADMIT_WAIT_S` (5 s, the gate's)
    w = World()
    w.engine.file.hex = on_disk
    await w.start()
    async with w.gate.serialized():  # taken before the job's first step, as a delete would
        job = await w.ended()
    assert (job.error, w.unchanged(), counted) == ("store_unavailable", True, ["store_unavailable"])
    kept = failed("store_unavailable", Severity.ERROR if check else Severity.WARNING)  # decision 12
    kept["after_state"]["check"] = check  # what the check found, kept in the trail
    assert w.audit.records[-1] == kept


@pytest.mark.parametrize("how", ["raises", "hangs"])
async def test_an_unwritten_finished_record_ends_audit_unavailable_and_leaves_the_row(
    how: str, counted: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(limits, "RECORD_BUDGET_S", 0.05)
    w = World()
    w.fail("finished", how)
    assert (await w.run()).error == "audit_unavailable"
    assert (w.unchanged(), counted) == (True, ["audit_unavailable"])


@pytest.mark.parametrize("on_disk", [SUM, OTHER])
async def test_an_outcome_the_row_did_not_take_ends_store_unavailable(
    on_disk: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The record stands alone (never written again); the row, the truth, is tried again."""
    monkeypatch.setattr(limits, "WRITE_BUDGET_S", 0.05)
    w = World()
    w.engine.file.hex = on_disk
    w.fail("mark", "hangs")
    with capture_logs() as logs:
        assert (await w.run()).error == "store_unavailable"
    assert (w.store.rows[ROW.id], w.engine.fresh, len(w.store.marks)) == (w.row, [], 2)
    assert [r["after_state"]["stage"] for r in w.audit.records] == ["requested", "finished"]
    where = {"backup_id": str(ROW.id), "error": "TimeoutError", "log_level": "error"}
    marked = [{"event": "backups.verify_not_marked", **where, "attempt": n} for n in (1, 2)]
    assert [log for log in logs if log["event"] == "backups.verify_not_marked"] == marked


async def test_a_check_its_jobs_deadline_cut_short_is_recorded_after_its_end(
    counted: list[str],
) -> None:
    """The gate's backstop: the job store ends it `internal_error`, then its record follows."""
    w = World(deadline_s=0.1)
    w.service._check_s = 5.0  # the check's own budget is longer than the gate's deadline here
    w.fail("verify", "hangs")
    assert (await w.run()).error == "internal_error"
    assert (w.audit.records[-1], w.unchanged(), counted) == (failed("internal_error"), True,
                                                            ["internal_error"])  # fmt: skip
    assert w.engine.file.closes == 1


async def test_a_job_the_job_store_refuses_ends_its_request_and_is_503(counted: list[str]) -> None:
    w = World()
    w.jobs.store = None  # type: ignore[assignment]  # so its submit raises
    with pytest.raises(OpsUnavailable):
        await w.start()
    assert w.audit.records == [verified("requested"), failed("internal_error")]
    assert (w.gate.active(), counted, w.unchanged()) == ([], ["internal_error"], True)


@pytest.mark.parametrize("step", ["evidence", "resolve", "digest", "verify", "mark"])
async def test_a_cancelled_step_is_never_swallowed(step: str) -> None:
    w = World()
    w.fail(step, "hangs")
    await w.start()
    for _ in range(3):  # scheduler turns: the job runs up to its hung step
        await asyncio.sleep(0)
    await w.jobs.store.stop()  # a shutdown
    job = w.jobs.store.get(str(JOB))
    assert job is not None and job.status == "cancelled"
    assert w.trail == ([*_STARTED, ("record", "finished")] if step == "mark" else _STARTED)
    assert w.engine.file.closes == (step in ("digest", "verify", "mark"))


async def test_failure_increments_cv_backup_verify_failures_total() -> None:
    child = metrics.verify_failures_total.labels("checksum_unbound")
    before, w = child._value.get(), World()
    w.engine.record = None
    await w.run()
    assert child._value.get() - before == 1


def test_the_check_ends_a_minute_before_the_jobs_deadline() -> None:
    """Room for the outcome: the lock wait, a record, the row's tries and the freshness, about 40 s
    at worst, pinned under the 60 s margin (`test_the_shipped_bounds_are_pinned`)."""
    budget = inspect.signature(BackupVerifications).parameters["check_s"].default
    assert budget == limits.JOB_DEADLINE_S["backup_verify"] - 60.0 == 12 * 3600.0 - 60.0
