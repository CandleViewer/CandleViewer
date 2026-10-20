"""`api/audit_verify_runner.py` (#2966): the scheduled run's records, series and outcome, one test
per rule of the port (`audit/verify_runner.py`), then the real job over the real audit service on
the in-memory store. A scripted query service and writer drive each branch. No database, no
network, no sleeps, a fake clock."""

from __future__ import annotations

import asyncio
import json
import math
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from audit_fakes import FakeAuditRepository
from prometheus_client import REGISTRY
from structlog.testing import capture_logs

from candleviewer.api.audit_verify import VERIFY_STOPS
from candleviewer.api.audit_verify_runner import ChainVerifyRunner
from candleviewer.audit.hashing import ChainHasherBusy
from candleviewer.audit.models import ChainBreakKind, VerifyResult
from candleviewer.audit.query import VerifyPlan
from candleviewer.audit.service import AuditService
from candleviewer.audit.verify_job import AuditVerifyJob
from candleviewer.audit.verify_runner import (
    VERIFY_JOB_ACTOR,
    VerifyOutcome,
    VerifyOutcomeKind,
    VerifyRunRequest,
    VerifyStopReason,
    VerifyTrigger,
)
from candleviewer.observability.audit_query_metrics import cv_audit_chain_verified_state
from candleviewer.observability.health_probes import SystemEvent
from candleviewer.observability.metrics import Metrics
from candleviewer.observability.metrics_catalogue import register_r0
from candleviewer.storage.errors import AuditEntryTooLarge
from candleviewer.storage.repositories.audit_sqlalchemy import AuditReadFailed

OK, MISMATCH, STOPPED = VerifyOutcomeKind.OK, VerifyOutcomeKind.MISMATCH, VerifyOutcomeKind.STOPPED
STARTUP, SCHEDULED = VerifyTrigger.STARTUP, VerifyTrigger.SCHEDULED
T0 = datetime(2026, 10, 20, 4, 0, tzinfo=UTC)
REQUEST = VerifyRunRequest(trigger=STARTUP, deadline_s=1800)
STARTED = ("success", "info", "started", {"trigger": "startup"})


@pytest.fixture(autouse=True)
def _restore_chain_gauge() -> Iterator[None]:
    yield
    cv_audit_chain_verified_state.set(math.nan)  # a process-wide series: leave it as found


class _Clock:
    """Each read is a second later than the one before: a run reads it at its start and its end."""

    def __init__(self) -> None:
        self.reads = 0

    def __call__(self) -> datetime:
        self.reads += 1
        return T0 + timedelta(seconds=self.reads - 1)


class _Writer:
    """Keeps each record it is given. From the `fail_from`th attempt on it refuses them all."""

    def __init__(self, fail_from: int | None = None) -> None:
        self.records: list[dict[str, Any]] = []
        self.attempts = 0
        self._fail_from = fail_from

    async def emit(self, action: str, **fields: Any) -> None:
        self.attempts += 1
        if self._fail_from is not None and self.attempts >= self._fail_from:
            raise RuntimeError("audit down")
        self.records.append({"action": action, **fields})


class _Query:
    """`plan_verify` and `run_verify`: the scripted value is returned, an exception raised."""

    def __init__(
        self,
        result: VerifyResult | Exception | None = None,
        plan: VerifyPlan | Exception | None = None,
    ) -> None:
        self._result = result if result is not None else _result()
        self._plan = plan if plan is not None else VerifyPlan(1, 5, 5, full_chain=True)
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def plan_verify(self, **kwargs: Any) -> VerifyPlan:
        self.calls.append(("plan", kwargs))
        if isinstance(self._plan, Exception):
            raise self._plan
        return self._plan

    async def run_verify(self, plan: VerifyPlan, **kwargs: Any) -> VerifyResult:
        self.calls.append(("run", kwargs))
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


class _Events:
    def __init__(self) -> None:
        self.written: list[SystemEvent] = []

    async def write(self, event: SystemEvent) -> None:
        self.written.append(event)


class _DownAudit:
    """The audit module before `start()` has wired a real backend (or after `stop()`)."""

    @property
    def query(self) -> Any:
        raise RuntimeError("AuditService.start() has not wired a real backend")

    writer = query


def _result(
    *,
    verified: bool = True,
    full: bool = True,
    from_id: int | None = 1,
    checked: int = 5,
    bad: int | None = None,
    kind: ChainBreakKind | None = None,
) -> VerifyResult:
    return VerifyResult(
        verified=verified,
        entries_checked=checked,
        first_bad_id=bad,
        checked_at=T0,
        from_id=from_id,
        to_id=None if from_id is None else 5,
        anchor_hash="0" * 64,
        last_hash="a" * 64 if verified else None,
        kind=kind,
        full_chain=full,
    )


def _break() -> VerifyResult:
    return _result(
        verified=False, checked=3, bad=3, kind=ChainBreakKind.ENTRY_HASH_MISMATCH, full=False
    )


def _runner(query: _Query, writer: _Writer, events: _Events | None = None) -> ChainVerifyRunner:
    audit: Any = SimpleNamespace(query=query, writer=writer)
    return ChainVerifyRunner(audit, events, clock=_Clock())


def _records(writer: _Writer) -> list[tuple[str, str, str, dict[str, Any]]]:
    return [
        (r["outcome"].value, r["severity"].value, r["reason"], r["after_state"])
        for r in writer.records
        if r["action"] == "admin.audit_verify"
    ]


def _gauge() -> float:
    value = REGISTRY.get_sample_value("cv_audit_chain_verified_state")
    assert value is not None
    return value


def _failures() -> float:
    return REGISTRY.get_sample_value("audit_chain_verification_failures_total") or 0.0


# ---- a clean chain passes -------------------------------------------------------------------


async def test_chain_runner_intact_chain_writes_started_then_verified_and_sets_the_gauge_to_1() -> (
    None
):
    cv_audit_chain_verified_state.set(math.nan)
    failures, writer = _failures(), _Writer()
    runner = _runner(_Query(_result(checked=5)), writer)
    outcome = await runner.run(REQUEST)
    assert outcome == VerifyOutcome(OK, T0, T0 + timedelta(seconds=1), 5)
    verified: dict[str, Any] = {"from_id": 1, "to_id": 5, "entries_checked": 5, "verified": True}
    verified |= {"first_bad_id": None, "kind": None, "trigger": "startup"}
    assert _records(writer) == [STARTED, ("success", "info", "verified", verified)]
    assert [r["actor_label"] for r in writer.records] == [VERIFY_JOB_ACTOR] * 2  # the system actor
    assert {r["object_kind"] for r in writer.records} == {"audit_log"}
    assert not {"actor_user_id", "session_id", "actor_ip"} & set().union(*writer.records)
    assert _gauge() == 1 and _failures() == failures


async def test_chain_runner_walks_the_whole_chain_under_the_requests_deadline() -> None:
    query = _Query()
    request = VerifyRunRequest(trigger=SCHEDULED, deadline_s=77.5)
    await _runner(query, _Writer()).run(request)
    assert query.calls == [
        ("plan", {"from_id": None, "to_id": None, "max_span": 2**63 - 1}),  # no span cap
        ("run", {"deadline_s": 77.5}),
    ]


async def test_chain_runner_empty_log_is_a_pass_with_nothing_checked() -> None:
    cv_audit_chain_verified_state.set(math.nan)
    writer = _Writer()
    result = _result(full=False, from_id=None, checked=0)  # no entry, so no `from_id` either
    outcome = await _runner(_Query(result), writer).run(REQUEST)
    assert (outcome.outcome, outcome.entries_checked) == (OK, 0)
    assert _records(writer)[1][:3] == ("success", "info", "verified")
    assert _gauge() == 1


# ---- a tampered row is found ----------------------------------------------------------------


async def test_chain_runner_break_is_mismatch_with_critical_record_gauge_counter_event() -> None:
    cv_audit_chain_verified_state.set(1)
    failures, writer, events = _failures(), _Writer(), _Events()
    outcome = await _runner(_Query(_break()), writer, events).run(REQUEST)
    assert (outcome.outcome, outcome.first_bad_id, outcome.entries_checked) == (MISMATCH, 3, 3)
    broken: dict[str, Any] = {"from_id": 1, "to_id": 5, "entries_checked": 3, "verified": False}
    broken |= {"first_bad_id": 3, "kind": "entry_hash_mismatch", "trigger": "startup"}
    assert _records(writer) == [STARTED, ("failure", "critical", "entry_hash_mismatch@3", broken)]
    assert _gauge() == 0 and _failures() == failures + 1
    [event] = events.written
    assert (event.component, event.kind, event.severity) == ("db", "audit_chain_break", "critical")
    assert event.details == {"first_bad_id": "3", "kind": "entry_hash_mismatch"} | {
        "from_id": "1",
        "to_id": "5",
    }


class _CancellingWriter(_Writer):
    """Cancelled while the `cancel_at`th record is being written (a shutdown mid-write)."""

    def __init__(self, cancel_at: int) -> None:
        super().__init__()
        self._cancel_at = cancel_at

    async def emit(self, action: str, **fields: Any) -> None:
        if self.attempts + 1 == self._cancel_at:
            self.attempts += 1
            raise asyncio.CancelledError()
        await super().emit(action, **fields)


async def test_chain_runner_break_series_and_event_do_not_wait_for_a_cancelled_record() -> None:
    """The gauge, the counter and the event are observed before the critical record is written,
    so a cancellation during that write still leaves the break visible (the port's contract)."""
    cv_audit_chain_verified_state.set(1)
    failures, events = _failures(), _Events()
    writer = _CancellingWriter(cancel_at=2)  # `started` lands, the result record is cut short
    with pytest.raises(asyncio.CancelledError):
        await _runner(_Query(_break()), writer, events).run(REQUEST)
    assert _gauge() == 0 and _failures() == failures + 1 and writer.attempts == 2
    assert [e.kind for e in events.written] == ["audit_chain_break"]


@pytest.mark.parametrize("events", [_Events(), None], ids=["event writer", "no event writer"])
async def test_chain_runner_break_counts_and_reports_even_when_its_record_is_refused(
    events: _Events | None,
) -> None:
    """A break is `mismatch` whether or not its record was written: the series and the event
    do not depend on it (the port)."""
    failures = _failures()
    cv_audit_chain_verified_state.set(1)
    writer = _Writer(fail_from=2)  # `started` lands, the result record does not
    outcome = await _runner(_Query(_break()), writer, events).run(REQUEST)
    assert (outcome.outcome, outcome.first_bad_id) == (MISMATCH, 3)
    assert _gauge() == 0 and _failures() == failures + 1 and writer.attempts == 2
    assert events is None or [e.kind for e in events.written] == ["audit_chain_break"]


# ---- a run that cannot finish is never a pass -----------------------------------------------

_STOPS = [
    (TimeoutError("audit verify exceeded its deadline"), "timeout", VerifyStopReason.TIMEOUT),
    (ChainHasherBusy(), "hasher_busy", VerifyStopReason.HASHER_BUSY),
    (AuditEntryTooLarge(42), "entry_too_large@42", VerifyStopReason.ENTRY_TOO_LARGE),
    (AuditReadFailed("08006"), "store_unavailable", VerifyStopReason.STORE_UNAVAILABLE),
    (RuntimeError("x"), "internal_error", VerifyStopReason.INTERNAL_ERROR),
]


def test_every_stop_the_route_records_is_a_stop_reason_of_the_port() -> None:
    """The runner maps the route's stop table onto the port's enum: a new row there needs a
    member here, or a run that stops on it would end in an exception instead of `stopped`."""
    assert {reason for _, reason, _ in VERIFY_STOPS} <= {r.value for r in VerifyStopReason}


@pytest.mark.parametrize("stage", ["plan", "run"])
@pytest.mark.parametrize(("error", "reason", "kind"), _STOPS, ids=[s[1] for s in _STOPS])
async def test_chain_runner_run_that_cannot_finish_is_stopped_with_a_stop_record_and_no_1(
    error: Exception, reason: str, kind: VerifyStopReason, stage: str
) -> None:
    cv_audit_chain_verified_state.set(1)
    failures, writer = _failures(), _Writer()
    query = _Query(plan=error) if stage == "plan" else _Query(error)
    outcome = await _runner(query, writer).run(REQUEST)
    assert (outcome.outcome, outcome.stop_reason, outcome.entries_checked) == (STOPPED, kind, 0)
    assert _records(writer) == [STARTED, ("failure", "warning", reason, {"trigger": "startup"})]
    assert math.isnan(_gauge()) and _failures() == failures  # a stop is no break


@pytest.mark.parametrize(
    ("before", "after"), [(1.0, math.nan), (0.0, 0.0), (math.nan, math.nan)], ids=["1", "0", "NaN"]
)
async def test_chain_runner_stop_takes_a_gauge_of_1_to_unknown_and_never_clears_a_known_break(
    before: float, after: float
) -> None:
    cv_audit_chain_verified_state.set(before)
    await _runner(_Query(TimeoutError()), _Writer()).run(REQUEST)
    assert math.isnan(_gauge()) if math.isnan(after) else _gauge() == after


async def test_chain_runner_logs_an_entry_over_the_cap_by_id_and_a_failure_by_class_only() -> None:
    with capture_logs() as logs:
        await _runner(_Query(AuditEntryTooLarge(42)), _Writer()).run(REQUEST)
        # Assembled at runtime: the secret scanners must not see a DSN literal (CI-SEC-001).
        dsn_like = "://".join(("postgresql", "user:pw@host/db"))
        await _runner(_Query(RuntimeError(dsn_like)), _Writer()).run(REQUEST)
    big = {"event": "audit.verify.entry_too_large", "entry_id": 42, "log_level": "warning"}
    assert {**big, "error": "AuditEntryTooLarge"} in logs
    failed = {"event": "audit.verify.failed", "error": "RuntimeError", "log_level": "error"}
    assert failed in logs and "pw@host" not in str(logs)


async def test_chain_runner_refused_started_record_never_walks_and_leaves_no_stop_record() -> None:
    cv_audit_chain_verified_state.set(1)
    query, writer = _Query(), _Writer(fail_from=1)
    outcome = await _runner(query, writer).run(REQUEST)
    assert (outcome.outcome, outcome.stop_reason) == (STOPPED, VerifyStopReason.RECORD_FAILED)
    assert query.calls == [] and writer.attempts == 1  # it never walked, and tried no stop record
    assert math.isnan(_gauge())


async def test_chain_runner_pass_whose_result_record_is_refused_is_stopped_and_never_sets_1() -> (
    None
):
    cv_audit_chain_verified_state.set(1)
    writer = _Writer(fail_from=2)  # `started` lands, the result record does not
    outcome = await _runner(_Query(_result(checked=5)), writer).run(REQUEST)
    kind = (outcome.outcome, outcome.stop_reason, outcome.entries_checked)
    assert kind == (STOPPED, VerifyStopReason.RECORD_FAILED, 5)
    assert writer.attempts == 2 and math.isnan(_gauge())  # no stop record is tried for it


async def test_chain_runner_cancelled_walk_re_raises_leaves_only_started_and_clears_a_1() -> None:
    entered, hold = asyncio.Event(), asyncio.Event()

    class _Hanging(_Query):
        async def run_verify(self, plan: VerifyPlan, **kwargs: Any) -> VerifyResult:
            entered.set()
            await hold.wait()
            raise AssertionError("the walk is never released")

    cv_audit_chain_verified_state.set(1)
    writer = _Writer()
    task = asyncio.ensure_future(_runner(_Hanging(), writer).run(REQUEST))
    await asyncio.wait_for(entered.wait(), 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert _records(writer) == [STARTED] and math.isnan(_gauge())


async def test_chain_runner_without_the_audit_module_is_stopped_and_clears_a_1() -> None:
    cv_audit_chain_verified_state.set(1)
    audit: Any = _DownAudit()
    outcome = await ChainVerifyRunner(audit, clock=_Clock()).run(REQUEST)
    assert (outcome.outcome, outcome.stop_reason) == (STOPPED, VerifyStopReason.RECORD_FAILED)
    assert math.isnan(_gauge())


async def test_chain_runner_verified_but_partial_result_is_never_a_pass() -> None:
    cv_audit_chain_verified_state.set(1)
    writer = _Writer()
    result = _result(full=False, from_id=3)  # verified, but not from genesis to the head
    outcome = await _runner(_Query(result), writer).run(REQUEST)
    kind = (outcome.outcome, outcome.stop_reason, outcome.entries_checked)
    assert kind == (STOPPED, VerifyStopReason.INTERNAL_ERROR, 5)
    stop = ("failure", "warning", "internal_error", {"trigger": "startup"})
    assert _records(writer) == [STARTED, stop]  # no `verified` record for it
    assert math.isnan(_gauge())


# ---- the real job, the real runner, the real audit service on the in-memory store -------------


def _metrics() -> Metrics:
    metrics = Metrics("demo")
    register_r0(metrics)
    return metrics


def _runs(metrics: Metrics) -> dict[str, float]:
    snapshot = metrics.snapshot(["cv_audit_verify_runs"])
    return {k: snapshot[f"cv_audit_verify_runs_total{{result={k}}}"] for k in VerifyOutcomeKind}


async def _service(
    tmp_path: Path, rows: int, first_id: int = 1
) -> tuple[AuditService, FakeAuditRepository]:
    """The audit service started on the in-memory store, with `rows` entries from `first_id`."""
    repo = FakeAuditRepository()
    repo.burn_ids(first_id - 1)
    audit = AuditService(repo)
    settings = SimpleNamespace(
        audit_wal_path=str(tmp_path / "a.wal"), audit_page_structure_budget=50_000
    )
    ctx: Any = SimpleNamespace(settings=settings)
    await audit.start(ctx)
    for i in range(rows):
        await audit.writer.emit("auth.login", actor_label="it", object_id=str(i))
    await audit.writer.flush(5)
    return audit, repo


def _verify_rows(repo: FakeAuditRepository) -> list[dict[str, Any]]:
    return [r for r in repo.rows if r["action"] == "admin.audit_verify"]


async def test_job_with_the_real_runner_passes_an_intact_chain_and_counts_one_ok_run(
    tmp_path: Path,
) -> None:
    audit, repo = await _service(tmp_path, rows=5, first_id=4)  # ids have gaps: it starts at 4
    metrics, failures = _metrics(), _failures()
    cv_audit_chain_verified_state.set(math.nan)
    job = AuditVerifyJob(
        ChainVerifyRunner(audit),
        lambda: audit.query.verify_slot,
        metrics,
        hour_utc=4,
        deadline_s=60,
    )
    try:
        assert await job.run_once(STARTUP) is OK
        await audit.writer.flush(5)
    finally:
        await audit.stop(1)
    started, passed = _verify_rows(repo)
    assert [(r["outcome"], r["severity"], r["reason"]) for r in (started, passed)] == [
        ("success", "info", "started"),
        ("success", "info", "verified"),
    ]
    assert {r["actor_label"] for r in (started, passed)} == {VERIFY_JOB_ACTOR}
    assert not any(
        r["actor_user_id"] or r["session_id"] or r["actor_ip"] for r in (started, passed)
    )
    after = json.loads(passed["after_state"])
    assert (after["from_id"], after["verified"], after["trigger"]) == (4, True, "startup")
    assert after["entries_checked"] == after["to_id"] - 3 >= 5  # the whole chain, from its first id
    assert _gauge() == 1 and _failures() == failures
    assert _runs(metrics) == {"ok": 1.0, "mismatch": 0.0, "stopped": 0.0}


async def test_job_with_the_real_runner_finds_a_tampered_row_and_reports_it_once(
    tmp_path: Path,
) -> None:
    audit, repo = await _service(tmp_path, rows=5)
    victim = repo.rows[2]
    victim["reason"] = "forged"  # altered behind the chain: its `entry_hash` no longer matches
    events, metrics, failures = _Events(), _metrics(), _failures()
    runner = ChainVerifyRunner(audit, events)
    job = AuditVerifyJob(
        runner, lambda: audit.query.verify_slot, metrics, hour_utc=4, deadline_s=60
    )
    try:
        assert await job.run_once(SCHEDULED) is MISMATCH
        await audit.writer.flush(5)
    finally:
        await audit.stop(1)
    _, found = _verify_rows(repo)
    assert (found["severity"], found["reason"]) == (
        "critical",
        f"entry_hash_mismatch@{victim['id']}",
    )
    assert json.loads(found["after_state"])["first_bad_id"] == victim["id"]
    assert _gauge() == 0 and _failures() == failures + 1
    assert [e.kind for e in events.written] == ["audit_chain_break"]
    assert _runs(metrics) == {"ok": 0.0, "mismatch": 1.0, "stopped": 0.0}
