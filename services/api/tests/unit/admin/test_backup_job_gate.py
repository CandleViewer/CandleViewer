"""Unit (E42-T05, #966 BK-7): the backups admission lock, its exclusion rules (Q6 both ways), its
bounds, and the release of a job's entry, once, when the job settles however it ends. Every lock
or event wait is bounded (`_BOUND`), so a leaked lock fails a test instead of hanging it."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any, Final, cast
from uuid import UUID, uuid4

import pytest

from candleviewer.admin.backups import limits
from candleviewer.admin.backups.gate import Admission, BackupConflict, BackupJobGate, JobAdmission
from candleviewer.admin.backups.limits import ADMIT_WAIT_S, JOB_DEADLINE_S
from candleviewer.admin.backups.ports import BackupJobError, JobEnd, JobKind
from candleviewer.admin.errors import OpsUnavailable
from candleviewer.api.recorder_admin import AdminJobStore
from candleviewer.backups_wiring import AdminJobRunner

X, Y = UUID(int=1), UUID(int=2)
RUN: Final = "backup"
VERIFY: Final = "backup_verify"
RESTORE: Final = "backup_restore"
BUSY = "backup_or_restore_running"
RESULT: dict[str, object] = {"backup_id": str(X), "verify_method": "checksum"}
_BOUND: Final = 2.0  # seconds, a safety net only: no test waits on it when the gate is right


def _runner() -> Any:  # a `JobRunner` whose jobs run until the test settles them
    settles: list[Callable[[], None]] = []
    return SimpleNamespace(settles=settles, submit=lambda *args: settles.append(args[-1]))


async def _ok(progress: Callable[[float], None]) -> dict[str, object]:
    return RESULT


async def _done(end: JobEnd) -> None:
    return None


@asynccontextmanager
async def _enter(gate: BackupJobGate, kind: str, on: UUID) -> AsyncIterator[Admission]:
    others = {"delete": gate.admit_delete, "link": gate.admit_link}
    entered = others[kind](on) if kind in others else gate.admit(cast(JobKind, kind), on)
    async with asyncio.timeout(_BOUND), entered as admission:
        yield admission


async def _start(
    gate: BackupJobGate, runner: Any, kind: str, on: UUID, work: Any = _ok, done: Any = _done
) -> UUID:
    job_id = uuid4()
    async with asyncio.timeout(_BOUND), gate.admit(cast(JobKind, kind), on) as admission:
        admission.check()
        admission.submit(runner, job_id, work, done)
    return job_id


async def _until(done: Callable[[], object]) -> None:
    for _ in range(100):  # scheduler turns, never wall-clock time
        if done():
            return
        await asyncio.sleep(0)
    raise AssertionError("never happened")


_TABLE: list[tuple[list[tuple[str, UUID]], str, UUID, str | None]] = [
    # (running jobs, the new admission, its backup, the rule refusing it)
    ([(RUN, Y)], RUN, X, BUSY),
    ([(RESTORE, Y)], RUN, X, BUSY),
    ([(VERIFY, Y)], RUN, X, None),
    ([(RESTORE, Y)], VERIFY, X, BUSY),  # Q6: a verification waits for a restore
    ([(VERIFY, Y)], VERIFY, X, "verify_running"),
    ([(RUN, Y)], VERIFY, X, None),
    ([(RUN, Y)], RESTORE, X, BUSY),
    ([(RESTORE, Y)], RESTORE, X, BUSY),
    ([(VERIFY, Y)], RESTORE, X, BUSY),  # Q6: and a restore for a verification
    ([(RUN, X)], "delete", X, "backup_in_use"),
    ([(VERIFY, X)], "delete", X, "backup_in_use"),
    ([(RESTORE, X)], "delete", X, "backup_in_use"),
    # A registry holds at most a run and a verification: its backup's job first or last.
    ([(RUN, Y), (VERIFY, X)], "delete", X, "backup_in_use"),
    ([(VERIFY, X), (RUN, Y)], "delete", X, "backup_in_use"),
    ([(RUN, X), (VERIFY, Y)], "delete", X, "backup_in_use"),
    ([(VERIFY, Y), (RUN, X)], "delete", X, "backup_in_use"),
    ([(RUN, Y), (VERIFY, Y)], "delete", X, None),  # another backup's jobs only
    # BK-10: a link runs no job, so no job refuses it; the backup's usability decides.
    *[([(kind, X)], "link", X, None) for kind in (RUN, VERIFY, RESTORE)],
    *[([], kind, X, None) for kind in (RUN, VERIFY, RESTORE, "delete", "link")],
]


def _row_id(row: tuple[list[tuple[str, UUID]], str, UUID, str | None]) -> str:
    running = "+".join(f"{kind}@{'x' if on == X else 'y'}" for kind, on in row[0]) or "idle"
    return f"{row[1]}@x-while-{running}"


@pytest.mark.parametrize(("running", "kind", "on", "rule"), _TABLE, ids=map(_row_id, _TABLE))
async def test_exclusion_table(
    running: list[tuple[str, UUID]], kind: str, on: UUID, rule: str | None
) -> None:
    gate, runner = BackupJobGate(), _runner()
    for running_kind, backup in running:
        await _start(gate, runner, running_kind, backup)
    async with _enter(gate, kind, on) as admission:
        if rule is None:
            admission.check()
        else:
            with pytest.raises(BackupConflict, match=f"^{rule}$") as refused:
                admission.check()
            assert refused.value.rule == rule
    assert sorted(gate.active()) == sorted(running)  # a check adds or removes nothing


@pytest.mark.parametrize(
    ("first", "second", "outcome"), [(RESTORE, RESTORE, BUSY), ("delete", RUN, "admitted")]
)
async def test_admission_is_held_across_an_await_so_two_restores_cannot_both_pass(
    first: str, second: str, outcome: str
) -> None:
    """The write-ahead record (a delete's store queries) is an await inside the admission: the
    second caller waits on the lock, short of its check, until the first has submitted."""
    gate, runner, written, record_open = BackupJobGate(), _runner(), list[str](), asyncio.Event()

    async def admit(name: str, kind: str) -> str:
        try:
            async with _enter(gate, kind, X) as admission:
                admission.check()
                written.append(name)
                await record_open.wait()
                if isinstance(admission, JobAdmission):
                    admission.submit(runner, uuid4(), _ok, _done)
        except BackupConflict as refused:
            return refused.rule
        return "admitted"

    both = asyncio.gather(admit("first", first), admit("second", second))
    await _until(lambda: written)
    for _ in range(5):
        await asyncio.sleep(0)  # the second runs as far as it can: up to the lock
    assert written == ["first"]
    record_open.set()
    async with asyncio.timeout(_BOUND):
        assert (list(await both), len(runner.settles)) == (["admitted", outcome], 1)


async def test_a_refused_admission_writes_nothing_and_holds_no_entry() -> None:
    gate, runner, written = BackupJobGate(), _runner(), list[str]()
    await _start(gate, runner, VERIFY, X)
    with pytest.raises(BackupConflict):
        async with _enter(gate, RESTORE, Y) as admission:
            admission.check()
            written.append("backup.restore")
    assert (written, len(runner.settles), gate.active()) == ([], 1, [(VERIFY, X)])


async def test_submit_checks_again_for_a_caller_that_skipped_the_check() -> None:
    gate, runner = BackupJobGate(), _runner()
    await _start(gate, runner, VERIFY, X)
    with pytest.raises(BackupConflict):
        async with asyncio.timeout(_BOUND), gate.admit(RESTORE, Y) as admission:
            admission.submit(runner, uuid4(), _ok, _done)
    assert (len(runner.settles), gate.active()) == (1, [(VERIFY, X)])


async def test_a_lock_held_past_the_wait_bound_refuses_and_registers_nothing() -> None:
    gate, runner, holding = BackupJobGate(admit_wait_s=0.05), _runner(), asyncio.Event()

    async def hold() -> None:
        async with gate.admit_delete(Y):  # a delete whose store query stalls
            holding.set()
            await asyncio.Event().wait()

    holder = asyncio.create_task(hold())
    async with asyncio.timeout(_BOUND):
        await holding.wait()
        with pytest.raises(OpsUnavailable, match="busy"):
            await _start(gate, runner, RUN, X)
        assert (runner.settles, gate.active()) == ([], [])
        holder.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await holder
    await _start(gate, runner, RUN, X)  # the cancelled holder released the lock


async def test_a_job_the_runner_cannot_start_holds_no_entry() -> None:
    def full(*args: object) -> None:
        raise RuntimeError("job store full")

    gate = BackupJobGate()
    with pytest.raises(RuntimeError, match="full"):
        await _start(gate, SimpleNamespace(submit=full), RUN, X)
    assert gate.active() == []


async def test_an_admission_is_refused_once_its_lock_is_released() -> None:
    gate, runner = BackupJobGate(), _runner()
    async with asyncio.timeout(_BOUND), gate.admit(RUN, X) as admission:
        pass
    with pytest.raises(RuntimeError, match="released"):
        admission.submit(runner, uuid4(), _ok, _done)
    assert (runner.settles, gate.active()) == ([], [])


@pytest.mark.parametrize("end", ["failed", "cancelled"])  # cancelled: by a shutdown
async def test_release_happens_when_the_job_ends_failed_or_cancelled(end: str) -> None:
    gate, store, go = BackupJobGate(), AdminJobStore(), asyncio.Event()

    async def work(progress: Callable[[float], None]) -> dict[str, object]:
        await go.wait()
        raise BackupJobError("verify_failed")

    job = store.get(str(await _start(gate, AdminJobRunner(store), VERIFY, X, work)))
    assert job is not None
    await _until(lambda: job.status == "running")
    async with asyncio.timeout(_BOUND):
        if end == "failed":
            go.set()
        else:
            await store.stop()
    await _until(lambda: not gate.active())
    assert (job.status, job.error) == (end, "verify_failed" if end == "failed" else None)
    await _start(gate, _runner(), RESTORE, X)  # nothing holds the lock or the registry


async def test_a_hung_job_is_ended_by_its_kinds_deadline_and_released() -> None:
    deadlines: dict[JobKind, float] = {
        "backup": 3600.0,
        "backup_verify": 0.05,
        "backup_restore": 3600.0,
    }
    gate, store, ended = BackupJobGate(deadlines_s=deadlines), AdminJobStore(), asyncio.Event()

    async def hung(progress: Callable[[float], None]) -> dict[str, object]:
        await asyncio.Event().wait()
        return {}

    async def done(end: JobEnd) -> None:
        ended.set()

    job = store.get(str(await _start(gate, AdminJobRunner(store), VERIFY, X, hung, done)))
    async with asyncio.timeout(_BOUND):
        await ended.wait()  # the deadline ended it: nothing else does
    await _until(lambda: not gate.active())
    assert job is not None and (job.status, job.error) == ("failed", "internal_error")


async def test_a_second_settle_never_frees_another_jobs_entry() -> None:
    gate, runner = BackupJobGate(), _runner()
    await _start(gate, runner, VERIFY, X)
    runner.settles[0]()
    await _start(gate, runner, VERIFY, X)  # the next verification of the same backup
    runner.settles[0]()
    assert gate.active() == [(VERIFY, X)]


async def test_the_entry_is_held_until_on_done_has_run() -> None:
    gate, store = BackupJobGate(), AdminJobStore()
    ends, record_open = list[JobEnd](), asyncio.Event()

    async def done(end: JobEnd) -> None:
        ends.append(end)
        await record_open.wait()  # the finished record, still being written

    await _start(gate, AdminJobRunner(store), VERIFY, X, done=done)
    await _until(lambda: ends)
    assert (ends, gate.active()) == ([JobEnd("succeeded", RESULT, None)], [(VERIFY, X)])
    record_open.set()
    await _until(lambda: not gate.active())


async def test_a_shutdown_releases_a_job_cancelled_before_its_first_step() -> None:
    gate, store = BackupJobGate(), AdminJobStore()
    job = store.get(str(await _start(gate, AdminJobRunner(store), VERIFY, X)))
    async with asyncio.timeout(_BOUND):
        await store.stop()  # no scheduler turn between: the job never ran
    assert (job and job.status, gate.active()) == ("queued", [])


async def test_a_kind_with_no_deadline_registers_nothing() -> None:
    """SR-BK7A-01: the deadline is looked up before the entry is made."""
    gate = BackupJobGate(deadlines_s={"backup": 3600.0})
    with pytest.raises(KeyError):
        await _start(gate, _runner(), VERIFY, X)
    assert gate.active() == []


def test_the_shipped_bounds_are_pinned() -> None:
    """R2-02: a change to a shipped bound changes this test with it."""
    hour = 3600.0
    deadlines = {"backup": 24 * hour, "backup_verify": 12 * hour, "backup_restore": 24 * hour}
    assert (ADMIT_WAIT_S, dict(JOB_DEADLINE_S)) == (5.0, deadlines)
    gate = BackupJobGate()
    assert (gate._admit_wait_s, gate._deadlines_s) == (ADMIT_WAIT_S, JOB_DEADLINE_S)
    budgets = (limits.RECORD_BUDGET_S, limits.WRITE_BUDGET_S, limits.LOST_READ_BUDGET_S)
    assert (budgets, limits.WRITE_TRIES, limits.LOST_RUNS_LIMIT) == ((2.0, 2.0, 2.0), 2, 16)
    assert (limits.RUNS_PER_HOUR, limits.PLAN_BUDGET_S) == (4, 2.0)
