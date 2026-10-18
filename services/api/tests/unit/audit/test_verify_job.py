"""The start-up and nightly audit chain verify job (#2111): a fake clock and sleep, the scripted
`FakeVerifyRunner` and a real `VerifySlot`. No database, no network, no wall-clock sleeps."""

from __future__ import annotations

import asyncio
import gc
import math
from collections.abc import Awaitable
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import structlog
from audit_fakes import FakeAuditRepository
from verify_fakes import FakeVerifyRunner

from candleviewer.admin.wiring import build_audit_verify_job
from candleviewer.app import create_app
from candleviewer.audit.service import AuditService
from candleviewer.audit.verify_job import (
    LAST_OK_GAUGE,
    MAX_SLEEP_S,
    RUN_GRACE_S,
    STARTUP_DELAY_S,
    AuditVerifyJob,
    next_slot,
)
from candleviewer.audit.verify_runner import (
    VerifyOutcome,
    VerifyOutcomeKind,
    VerifyRunRequest,
    VerifyStopReason,
    VerifyTrigger,
)
from candleviewer.audit.verify_slot import VerifySlot
from candleviewer.observability.metrics import Metrics
from candleviewer.observability.metrics_catalogue import register_r0
from candleviewer.settings import Environment, Settings

OK, MISMATCH, STOPPED = VerifyOutcomeKind.OK, VerifyOutcomeKind.MISMATCH, VerifyOutcomeKind.STOPPED
STARTUP, SCHEDULED = VerifyTrigger.STARTUP, VerifyTrigger.SCHEDULED
_HANG_GUARD_S = 5.0  # as test_writer_cancel_safety: a passing test never waits on it


async def _guarded[T](aw: Awaitable[T]) -> T:
    """A regression that hangs fails here instead of hanging the suite."""
    async with asyncio.timeout(_HANG_GUARD_S):
        return await aw


def _at(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=UTC)


T0 = _at(16, 10)


def _outcome(kind: VerifyOutcomeKind, ended_at: datetime = T0, **fields: Any) -> VerifyOutcome:
    return VerifyOutcome(
        outcome=kind, started_at=ended_at, ended_at=ended_at, entries_checked=3, **fields
    )


class _Halt(BaseException):
    """Ends `run_forever` from inside a run. Not an `Exception`, so the job cannot absorb it."""


class FakeTime:
    """The injected clock and sleep: a sleep adds what it asked for, or goes to `jumps[nth]`."""

    def __init__(self, now: datetime, jumps: dict[int, datetime] | None = None) -> None:
        self.now, self.jumps = now, jumps or {}
        self.sleeps: list[float] = []

    def clock(self) -> datetime:
        return self.now

    async def sleep(self, seconds: float) -> None:
        assert len(self.sleeps) < 5000, "runaway loop"
        self.sleeps.append(seconds)
        self.now = self.jumps.get(len(self.sleeps), self.now + timedelta(seconds=seconds))
        await asyncio.sleep(0)  # one scheduler turn, no wall-clock time


class ClockedRunner(FakeVerifyRunner):
    """`FakeVerifyRunner` that notes when each run starts, and sets the clock to `steps[nth]`."""

    def __init__(self, time: FakeTime, *script: Any, **kw: Any) -> None:
        self._steps: dict[int, datetime] = kw.pop("steps", {})
        super().__init__(*script, **kw)
        self._time = time
        self.at: list[tuple[VerifyTrigger, datetime]] = []

    async def run(self, request: VerifyRunRequest) -> VerifyOutcome:
        self.at.append((request.trigger, self._time.now))
        self._time.now = self._steps.get(len(self.at), self._time.now)
        return await super().run(request)


def _metrics() -> Metrics:
    metrics = Metrics("demo")
    register_r0(metrics)
    return metrics


def _job(
    runner: FakeVerifyRunner, time: FakeTime | None = None, **kw: Any
) -> tuple[AuditVerifyJob, VerifySlot, Metrics]:
    time, slot, metrics = time or FakeTime(T0), VerifySlot(), _metrics()
    opts: dict[str, Any] = {"hour_utc": 4, "deadline_s": 1800, "clock": time.clock, **kw}
    job = AuditVerifyJob(runner, lambda: slot, metrics, sleep=time.sleep, **opts)
    return job, slot, metrics


def _last_ok(metrics: Metrics) -> float:
    return metrics.snapshot([LAST_OK_GAUGE])[LAST_OK_GAUGE]


def _runs(metrics: Metrics) -> dict[VerifyOutcomeKind, float]:
    snap = metrics.snapshot(["cv_audit_verify_runs"])
    return {k: snap[f"cv_audit_verify_runs_total{{result={k}}}"] for k in VerifyOutcomeKind}


@pytest.mark.parametrize(
    ("now", "hour", "slot"),
    [
        (_at(16, 3, 59), 4, _at(16, 4)),
        (_at(16, 4), 4, _at(17, 4)),  # strictly after: never the slot just reached
        (_at(16, 10), 4, _at(17, 4)),
        (_at(16, 23, 30), 0, _at(17, 0)),
        (_at(16, 22), 23, _at(16, 23)),
        (datetime(2026, 10, 16, 5, 30, tzinfo=timezone(timedelta(hours=2))), 4, _at(16, 4)),
    ],
)
def test_next_slot_is_the_first_configured_hour_strictly_after(
    now: datetime, hour: int, slot: datetime
) -> None:
    assert next_slot(now, hour) == slot


async def test_the_first_run_is_five_minutes_after_start_then_daily_at_the_hour() -> None:
    time = FakeTime(T0)
    runner = ClockedRunner(time, _outcome(OK), _outcome(OK), _outcome(OK), _Halt())
    job, _, _ = _job(runner, time)
    with pytest.raises(_Halt):
        await _guarded(job.run_forever())
    assert STARTUP_DELAY_S >= 300 and time.sleeps[0] == STARTUP_DELAY_S
    assert [at for _, at in runner.at] == [_at(16, 10, 5), _at(17, 4), _at(18, 4), _at(19, 4)]
    assert [t for t, _ in runner.at] == [STARTUP, SCHEDULED, SCHEDULED, SCHEDULED]
    assert {r.deadline_s for r in runner.requests} == {1800}


async def test_a_run_that_overruns_its_slot_queues_no_other_run() -> None:
    time, hold = FakeTime(_at(16, 3, 50)), asyncio.Event()
    runner = ClockedRunner(time, _outcome(OK), _outcome(OK), _Halt(), hold=hold)
    job, _, _ = _job(runner, time)
    loop = asyncio.ensure_future(job.run_forever())
    await _guarded(runner.entered.wait())  # the start-up run, at 03:55
    time.now = _at(16, 4, 25)  # it is still running past today's 04:00 slot
    hold.set()
    with pytest.raises(_Halt):
        await _guarded(loop)
    assert [at for _, at in runner.at] == [_at(16, 3, 55), _at(17, 4), _at(18, 4)]
    assert [t for t, _ in runner.at] == [STARTUP, SCHEDULED, SCHEDULED]


async def test_a_clock_stepped_back_during_a_run_never_re_runs_its_slot() -> None:
    time = FakeTime(T0)  # during the 17th 04:00 run the clock steps back to 03:30
    runner = ClockedRunner(time, _outcome(OK), _outcome(OK), _Halt(), steps={2: _at(17, 3, 30)})
    job, _, _ = _job(runner, time)
    with pytest.raises(_Halt):
        await _guarded(job.run_forever())
    assert [at for _, at in runner.at] == [_at(16, 10, 5), _at(17, 4), _at(18, 4)]


async def test_a_clock_jump_during_a_wait_starts_the_due_run_at_the_new_time() -> None:
    time = FakeTime(T0, jumps={3: _at(17, 5, 30)})  # the host resumes during the third wait
    job, _, _ = _job(runner := ClockedRunner(time, _outcome(OK), _outcome(OK), _Halt()), time)
    with pytest.raises(_Halt):
        await _guarded(job.run_forever())
    assert runner.at[1] == (SCHEDULED, _at(17, 5, 30)) and max(time.sleeps) <= MAX_SLEEP_S


async def test_a_resume_days_later_runs_once_then_keeps_the_daily_slot() -> None:
    """The next slot is the first one after the run: one catch-up run, not one per missed day
    (each a whole-chain walk with its own records)."""
    time = FakeTime(T0, jumps={3: _at(20, 9)})  # the host resumes past four 04:00 slots
    runner = ClockedRunner(time, _outcome(OK), _outcome(OK), _outcome(OK), _Halt())
    job, _, _ = _job(runner, time)
    with pytest.raises(_Halt):
        await _guarded(job.run_forever())
    assert [at for _, at in runner.at] == [_at(16, 10, 5), _at(20, 9), _at(21, 4), _at(22, 4)]


async def test_a_run_waits_behind_a_held_slot_and_is_never_skipped() -> None:
    runner = FakeVerifyRunner(_outcome(OK))
    job, slot, _ = _job(runner)
    assert slot.try_acquire()  # an on-demand verify is running
    run = asyncio.ensure_future(job.run_once(SCHEDULED))
    await asyncio.sleep(0)
    assert not run.done() and runner.requests == []
    assert not slot.try_acquire()  # the next on-demand run is refused while the job waits
    slot.release()  # the on-demand run ends: the slot passes to the job
    assert await _guarded(run) is OK
    assert len(runner.requests) == 1 and not slot.held


async def test_a_run_cancelled_while_it_waits_never_releases_the_holders_slot() -> None:
    """`acquire()` sits before the `try` (`verify_runner` port): inside it, the `finally` would
    free the on-demand run's slot, and the next run would overlap that run."""
    runner = FakeVerifyRunner(_outcome(OK))
    job, slot, metrics = _job(runner)
    assert slot.try_acquire()  # an on-demand verify is running
    run = asyncio.ensure_future(job.run_once(SCHEDULED))
    await asyncio.sleep(0)  # the job now waits for the slot
    run.cancel()
    with pytest.raises(asyncio.CancelledError):
        await _guarded(run)
    assert slot.held and runner.requests == []
    assert _runs(metrics) == dict.fromkeys(VerifyOutcomeKind, 0.0)


async def test_a_cancelled_run_gives_the_slot_back_and_re_raises() -> None:
    runner = FakeVerifyRunner(_outcome(OK), hold=asyncio.Event())
    job, slot, metrics = _job(runner)
    run = asyncio.ensure_future(job.run_once(SCHEDULED))
    await _guarded(runner.entered.wait())
    assert slot.held
    run.cancel()
    with pytest.raises(asyncio.CancelledError):
        await _guarded(run)
    assert not slot.held and _last_ok(metrics) == 0


async def test_a_runner_that_never_returns_is_stopped_at_the_backstop() -> None:
    delays: list[float] = []

    def due_now(delay: float) -> asyncio.Timeout:
        delays.append(delay)
        return asyncio.timeout(0)  # already due: fires at the runner's first wait

    runner = FakeVerifyRunner(_outcome(OK), hold=asyncio.Event())  # never set: a hung store
    job, slot, metrics = _job(runner, timeout=due_now)
    with structlog.testing.capture_logs() as logs:
        assert await _guarded(job.run_once(SCHEDULED)) is STOPPED
    assert delays == [1800 + RUN_GRACE_S] and not slot.held and _runs(metrics)[STOPPED] == 1
    [entry] = [e for e in logs if e["event"] == "audit.verify_job_run"]
    assert entry["error"] == "TimeoutError"


async def test_start_runs_one_owned_loop_and_stop_cancels_it_mid_run() -> None:
    hold = asyncio.Event()
    runner = FakeVerifyRunner(_outcome(OK), hold=hold)
    job, slot, _ = _job(runner)
    job.start()
    job.start()  # idempotent: one loop, so runs never overlap
    await _guarded(runner.entered.wait())
    assert [t.get_name() for t in asyncio.all_tasks()].count("cv-audit-verify") == 1
    try:
        await asyncio.wait_for(job.stop(), _HANG_GUARD_S)
    finally:
        hold.set()  # a loop that swallowed the cancel must fail here, not hang the teardown
    await job.stop()
    assert not slot.held and "cv-audit-verify" not in {t.get_name() for t in asyncio.all_tasks()}


async def test_a_loop_that_dies_logs_the_error_class_only_and_stop_leaves_no_report() -> None:
    time = FakeTime(T0)  # a naive clock reading after the start-up run breaks `next_slot`
    runner = ClockedRunner(time, _outcome(OK), steps={1: datetime(2026, 10, 16, 10, 6)})
    job, _, _ = _job(runner, time)
    reports: list[dict[str, Any]] = []  # asyncio reports a task error nobody retrieved
    asyncio.get_running_loop().set_exception_handler(lambda _, context: reports.append(context))
    with structlog.testing.capture_logs() as logs:
        job.start()
        [loop] = [t for t in asyncio.all_tasks() if t.get_name() == "cv-audit-verify"]
        await _guarded(asyncio.wait({loop}))
        await job.stop()  # returns, not raising the error again: it was logged as the loop died
    del loop
    gc.collect()  # the report, if any, comes when the dead task is collected
    [died] = [e for e in logs if e["event"] == "audit.verify_job_died"]
    assert died == {"event": "audit.verify_job_died", "error": "TypeError", "log_level": "error"}
    assert reports == []


@pytest.mark.parametrize(
    ("ended", "kind", "last_ok"),
    [
        (_outcome(OK, ended_at=_at(16, 4, 2)), OK, _at(16, 4, 2).timestamp()),
        (_outcome(MISMATCH, first_bad_id=7), MISMATCH, 0),
        (_outcome(STOPPED, stop_reason=VerifyStopReason.TIMEOUT), STOPPED, 0),
        (_outcome(STOPPED, stop_reason=VerifyStopReason.RECORD_FAILED), STOPPED, 0),
        (RuntimeError("store gone"), STOPPED, 0),
    ],
)
async def test_a_run_end_counts_under_its_result_and_only_a_pass_moves_the_gauge(
    ended: VerifyOutcome | Exception, kind: VerifyOutcomeKind, last_ok: float
) -> None:
    job, _, metrics = _job(FakeVerifyRunner(ended))
    assert await job.run_once(SCHEDULED) is kind
    assert _runs(metrics) == {k: float(k is kind) for k in VerifyOutcomeKind}
    assert _last_ok(metrics) == last_ok


def test_a_new_job_exports_each_result_at_0_so_the_first_run_after_a_restart_counts() -> None:
    """`increase()` spans the counter's reset, so the page outlives a restart (promtool)."""
    assert _runs(_job(FakeVerifyRunner())[2]) == dict.fromkeys(VerifyOutcomeKind, 0.0)


async def test_a_runner_exception_is_logged_as_a_stopped_run_never_a_success() -> None:
    job, slot, metrics = _job(FakeVerifyRunner(RuntimeError("store gone")))
    with structlog.testing.capture_logs() as logs:
        assert await job.run_once(STARTUP) is STOPPED
    [entry] = [e for e in logs if e["event"] == "audit.verify_job_run"]
    assert entry["outcome"] == "stopped" and entry["error"] == "RuntimeError"
    assert entry["log_level"] == "error" and "store gone" not in str(entry)
    assert not slot.held and _last_ok(metrics) == 0


@pytest.mark.parametrize(
    ("trigger", "ended", "logged"),
    [
        (STARTUP, _outcome(OK), ("info", "ok", None, None)),
        (SCHEDULED, _outcome(MISMATCH, first_bad_id=7), ("error", "mismatch", 7, None)),
        (
            SCHEDULED,
            _outcome(STOPPED, stop_reason=VerifyStopReason.TIMEOUT),
            ("warning", "stopped", None, "timeout"),
        ),
    ],
    ids=["ok", "mismatch", "stopped"],
)
async def test_a_run_end_logs_what_the_runbook_reads_at_its_level(
    trigger: VerifyTrigger, ended: VerifyOutcome, logged: tuple[str, str, int | None, str | None]
) -> None:
    """07 runbook, AuditVerifyNotPassing rows 5 and 7: the operator reads the stop reason and
    the `ok` outcome from these lines."""
    level, outcome, first_bad_id, stop_reason = logged
    job, _, _ = _job(FakeVerifyRunner(ended))
    with structlog.testing.capture_logs() as logs:
        await _guarded(job.run_once(trigger))
    [entry] = [e for e in logs if e["event"] == "audit.verify_job_run"]
    assert entry == {
        "event": "audit.verify_job_run",
        "log_level": level,
        "trigger": trigger.value,
        "outcome": outcome,
        "entries_checked": 3,
        "first_bad_id": first_bad_id,
        "stop_reason": stop_reason,
    }


async def test_a_run_without_the_audit_module_is_a_stopped_run() -> None:
    def no_audit() -> VerifySlot:
        raise RuntimeError("AuditService.start() has not wired a real backend")

    runner, metrics = FakeVerifyRunner(_outcome(OK)), _metrics()
    job = AuditVerifyJob(runner, no_audit, metrics, hour_utc=4, deadline_s=1800)
    assert await job.run_once(SCHEDULED) is STOPPED
    assert runner.requests == [] and _runs(metrics)[STOPPED] == 1


async def test_the_gauge_starts_at_the_job_start_so_runs_that_never_pass_still_page() -> None:
    runner = FakeVerifyRunner(_outcome(STOPPED, stop_reason=VerifyStopReason.TIMEOUT), _Halt())
    job, _, metrics = _job(runner)
    with pytest.raises(_Halt):
        await _guarded(job.run_forever())
    assert _last_ok(metrics) == T0.timestamp()


@pytest.mark.parametrize(
    ("hour", "deadline_s"), [(-1, 1800.0), (24, 1800.0), (4, 0.0), (4, math.inf), (4, math.nan)]
)
def test_a_job_with_a_bad_hour_or_deadline_is_refused(hour: int, deadline_s: float) -> None:
    with pytest.raises(ValueError, match=r"hour_utc|deadline_s"):
        _job(FakeVerifyRunner(), hour_utc=hour, deadline_s=deadline_s)


def test_the_app_builds_no_job_until_a_verify_runner_is_wired() -> None:
    settings = Settings(environment=Environment.DEMO)
    assert create_app(settings).state.audit_verify_job is None
    wired = create_app(settings, audit_verify_runner=FakeVerifyRunner())
    assert isinstance(wired.state.audit_verify_job, AuditVerifyJob)


def test_an_app_without_a_runner_leaves_the_gauge_at_0_and_the_counter_without_a_series() -> None:
    """07 (AuditChainVerificationFailed, interim state): nothing runs, so the page has no pass
    time to read (a gauge at 0 is dropped by its `> 0`) and no run to count: it cannot fire."""
    metrics: Metrics = create_app(Settings(environment=Environment.DEMO)).state.metrics_facade
    assert metrics.snapshot([LAST_OK_GAUGE]) == {LAST_OK_GAUGE: 0.0}
    assert metrics.snapshot(["cv_audit_verify_runs"]) == {}


def test_the_two_settings_reach_the_job_not_the_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """The operator's lever is `CV_AUDIT_VERIFY_NIGHTLY_*` and a restart (24 section 15.4): the
    app hands the job what the environment says, not the defaults (hour 4, deadline 1800 s)."""
    monkeypatch.setenv("CV_AUDIT_VERIFY_NIGHTLY_HOUR_UTC", "7")
    monkeypatch.setenv("CV_AUDIT_VERIFY_NIGHTLY_DEADLINE_S", "900")
    settings = Settings(_env_file=None)  # type: ignore[call-arg]  # pydantic-settings kwarg
    job = create_app(settings, audit_verify_runner=FakeVerifyRunner()).state.audit_verify_job
    assert isinstance(job, AuditVerifyJob)
    assert job._hour_utc == 7
    assert {r.deadline_s for r in job._requests.values()} == {900.0}


async def test_the_wired_job_waits_on_the_query_services_own_slot(tmp_path: Path) -> None:
    audit, metrics = AuditService(FakeAuditRepository()), _metrics()
    settings = SimpleNamespace(
        audit_wal_path=str(tmp_path / "a"), audit_page_structure_budget=50_000
    )
    ctx: Any = SimpleNamespace(settings=settings)
    await audit.start(ctx)
    try:
        job = build_audit_verify_job(
            audit, Settings(environment=Environment.DEMO), metrics, FakeVerifyRunner(_outcome(OK))
        )
        assert job is not None and audit.query.verify_slot.try_acquire()  # an on-demand run
        run = asyncio.ensure_future(job.run_once(SCHEDULED))
        await asyncio.sleep(0)
        assert not run.done()
        audit.query.verify_slot.release()
        assert await _guarded(run) is OK
    finally:
        await audit.stop(1)
