"""Unit (E42-T05 #966 BK-8): a backup run started in the plan's order, and how its job's end
reaches the row through BK-8a's `RunRows`."""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

import pytest
from structlog.testing import capture_logs

from candleviewer.admin.backups import limits
from candleviewer.admin.backups.gate import BackupConflict, BackupJobGate
from candleviewer.admin.backups.ports import BackupJobError, JobEnd, RunPlan
from candleviewer.admin.backups.runs import BackupEngineInvalid, RunsLimited
from candleviewer.admin.errors import OpsAuditUnavailable, OpsNotWired, OpsUnavailable
from candleviewer.api.audit_limiter import AuditVerifyLimiter
from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.storage.errors import StorageQueryFailed
from candleviewer.storage.repositories.backups import BackupKind, NewBackup
from tests.unit.admin._run_fakes import (
    ALIAS,
    BOUND,
    DIGEST,
    FAILED,
    NOTHING,
    NOW,
    OWNER,
    PLAN,
    World,
    expected,
)

_RUN = UUID(int=1001)  # a world's first run
_USER = str(OWNER.user_id)
_UNRECORDED = {"event": "backups.run_unrecorded", "backup_id": str(_RUN)}
_REQUESTED = [("record", "requested"), ("insert", "running")]
_ENDED = [("record", "finished"), ("finish", "failed")]


@pytest.mark.parametrize("missing", ["engine", "store"])
async def test_unwired_runner_is_501_and_writes_nothing(missing: str) -> None:
    w = World(**{missing: False})
    with pytest.raises(OpsNotWired):
        await w.start("a note")
    assert (w.trail, w.engine.calls, w.jobs.store.held(), w.gate.active()) == ([], [], 0, [])
    assert w.limit.starts == []


async def test_run_is_recorded_before_the_row_and_the_job_exist() -> None:
    w, seen = World(), list[object]()
    w.engine.go.clear()  # the run waits, so its job is seen while it runs

    async def write_ahead(backup_id: UUID, kind: BackupKind) -> None:
        seen.append((dict(w.store.rows), w.jobs.store.held(), w.gate.active(), w.limit.starts[:]))
        await w.runs.audit_requested(OWNER, backup_id, kind=kind, verify=True, note=None)

    await w.runs.start(OWNER, kind="pg_dump", write_ahead=write_ahead)
    assert (seen, w.trail) == ([({}, 0, [], [])], _REQUESTED)
    w.engine.go.set()
    await w.ended()


@pytest.mark.parametrize(("kind", "verify"), [("pg_dump", True), ("config_bundle", False)])
async def test_a_run_of_a_kind_is_recorded_planned_inserted_and_counted(
    kind: BackupKind, verify: bool
) -> None:
    w = World()
    w.engine.go.clear()
    started = await w.start(kind=kind, verify=verify)
    assert w.audit.records == [expected("requested", _RUN, kind=kind, verify=verify)]
    new = NewBackup(_RUN, kind, PLAN.location, True, "manual", OWNER.user_id, NOW, ALIAS)
    assert (w.engine.calls[0], w.store.inserted) == (("plan", kind), [new])
    assert started == w.store.rows[_RUN]
    assert ALIAS not in repr(PLAN) + repr(new)  # the alias is class S: never in a repr
    assert (w.gate.active(), w.limit.starts) == ([("backup", _RUN)], [_USER])
    w.engine.go.set()
    await w.ended()


async def test_the_job_runs_the_planned_run_under_the_row_id() -> None:
    w = World()
    w.engine.go.clear()
    await w.start()
    await asyncio.sleep(0)  # one scheduler turn: the job runs up to the engine's wait
    job = w.jobs.store.get(str(_RUN))  # the job's id is the row's
    assert job is not None and (job.kind, job.status, job.progress_pct) == ("backup", "running", 50)
    assert w.engine.calls == [("plan", "pg_dump"), ("run", _RUN, PLAN)]
    w.engine.go.set()
    await w.ended()


@pytest.mark.parametrize("digest", [DIGEST, None], ids=["one-file", "directory-or-repository"])
async def test_a_run_that_succeeds_ends_ok_and_its_job_succeeded(digest: str | None) -> None:
    w = World()
    w.engine.report = (1234, digest)  # no digest for a directory or a repository (Q8)
    await w.start()
    await w.ended()
    assert w.trail == [*_REQUESTED, ("record", "finished"), ("finish", "ok")]
    state = {"size_bytes": 1234, "checksum_sha256": digest, "error": None}
    assert w.audit.records[1] == expected("finished", _RUN, **state)
    job = w.jobs.store.get(str(_RUN))
    assert job is not None and (job.status, job.result) == ("succeeded", {"backup_id": str(_RUN)})


@pytest.mark.parametrize("how", ["raises", "hangs"])
async def test_a_job_whose_finished_record_fails_carries_the_audit_mark(
    how: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(limits, "RECORD_BUDGET_S", 0.05)
    w = World()
    w.fail("finished", how)
    await w.start()
    await w.ended()
    job, marked = w.jobs.store.get(str(_RUN)), {"backup_id": str(_RUN), "audit": "unavailable"}
    assert job is not None and (job.status, job.result) == ("succeeded", marked)  # the row decides
    assert w.trail[-1] == ("finish", "failed")
    assert w.store.rows[_RUN].error_message == "audit_unavailable"


@pytest.mark.parametrize(("how", "error"), [("raises", "OSError"), ("hangs", "TimeoutError")])
async def test_audit_failure_is_503_and_starts_nothing(
    how: str, error: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(limits, "RECORD_BUDGET_S", 0.05)
    w = World()
    w.fail("requested", how)
    with capture_logs() as logs, pytest.raises(OpsAuditUnavailable):
        await w.start()
    assert (w.trail, w.store.rows, w.jobs.store.held(), w.gate.active()) == ([], {}, 0, [])
    assert w.limit.starts == []  # a run that never started never counts
    assert logs == [_UNRECORDED | {"stage": "requested", "error": error, "log_level": "error"}]


async def test_a_second_run_while_one_runs_is_409_and_unrecorded() -> None:
    w = World()
    w.engine.go.clear()
    await w.start()
    with pytest.raises(BackupConflict, match=r"^backup_or_restore_running$"):
        await w.start("a second run")
    assert (w.trail, len(w.audit.records), w.limit.starts) == (_REQUESTED, 1, [_USER])
    assert [call[0] for call in w.engine.calls].count("plan") == 1  # never asked to plan it
    w.engine.go.set()
    await w.ended()
    assert w.store.rows[_RUN].status == "ok"


async def test_a_spent_limit_is_429_without_waiting_for_the_lock() -> None:
    w = World()
    w.limit.wait = 60
    async with w.gate.admit_delete(UUID(int=99)):  # held past the start's bound
        with pytest.raises(RunsLimited):
            await w.start()


async def test_a_start_that_waited_for_the_lock_is_429_once_the_hour_is_spent() -> None:
    """SR-BK8A-03: two starts pass the first check at 3 of 4 and queue on the lock; the second is
    429 once admitted, ahead of the 409 the first's run would give, and never planned."""
    limit = AuditVerifyLimiter(rate_per_hour=limits.RUNS_PER_HOUR, clock=lambda: 0.0)
    w = World(limit)
    for _ in range(limits.RUNS_PER_HOUR - 1):
        limit.record_start(_USER)
    w.engine.go.clear()
    async with w.gate.admit_delete(UUID(int=98)):  # both queue behind this holder
        queued = []
        for waiter in (w.start(), w.start()):
            queued.append(asyncio.create_task(waiter))
            await asyncio.sleep(0)  # it runs as far as it can: up to the lock
    async with asyncio.timeout(BOUND):
        await queued[0]
        with pytest.raises(RunsLimited):
            await queued[1]
    assert (list(w.store.rows), len(w.audit.records)) == ([_RUN], 1)  # one run, nothing more
    assert [call[0] for call in w.engine.calls].count("plan") == 1
    w.engine.go.set()
    await w.ended()


async def test_a_busy_admission_lock_is_503_and_writes_nothing() -> None:
    w = World(gate=BackupJobGate(admit_wait_s=0.05))
    async with w.gate.admit_delete(UUID(int=99)):  # held past the start's wait
        with pytest.raises(OpsUnavailable):
            await w.start()
    assert (w.trail, w.engine.calls, w.limit.starts) == ([], [], [])


async def test_note_lands_only_in_the_record_reason() -> None:
    w = World()
    with capture_logs() as logs:
        await w.start("before the 2.4 release, ticket 42")
        await w.ended()
    requested, finished = w.audit.records
    assert (requested["reason"], finished["reason"]) == ("before the 2.4 release, ticket 42", None)
    job = w.jobs.store.get(str(_RUN))
    elsewhere = repr((w.store.rows, w.store.inserted, job and job.view(), finished, logs))
    assert "ticket 42" not in elsewhere


async def test_fifth_run_in_an_hour_is_429() -> None:
    clock = [0.0]
    limit = AuditVerifyLimiter(rate_per_hour=limits.RUNS_PER_HOUR, clock=lambda: clock[0])
    w = World(limit)
    for minute in range(4):
        clock[0] = 60.0 * minute
        await w.start()
        await w.ended()
    clock[0] = 300.0
    with pytest.raises(RunsLimited) as limited:
        await w.start()
    assert (limited.value.retry_after_s, len(w.audit.records)) == (3300, 8)  # it wrote nothing
    clock[0] = 3600.0  # the first run has left the rolling hour
    await w.start()
    await w.ended()


def test_the_hourly_limit_is_the_contracts() -> None:
    spec: dict[str, Any] = load_openapi_spec()
    create: str = spec["paths"]["/admin/backups"]["post"]["description"]
    cited = f"A user may start at most {limits.RUNS_PER_HOUR} runs in a rolling hour"
    assert cited in " ".join(create.split())


@pytest.mark.parametrize(
    ("raised", "report", "code"),
    [(BackupJobError("artefact_missing"), None, "artefact_missing"),
     (OSError("/srv/cv/backups: gone"), None, "internal_error"),
     (None, (-1, DIGEST), "internal_error"), (None, (0, DIGEST), "internal_error"),
     (None, (1234, DIGEST.upper()), "internal_error"),
     (None, (1234, DIGEST[:63]), "internal_error"), (None, (1234, DIGEST + "a"), "internal_error")],
    ids=["engine-code", "engine-error", "negative-size", "empty", "digest-uppercase",
         "digest-63-long", "digest-65-long"],
)  # fmt: skip
async def test_a_failed_run_ends_failed_with_its_code_recorded_first(
    raised: Exception | None, report: tuple[int, str] | None, code: str
) -> None:
    w = World()
    if raised is not None:
        w.faults.raises["run"] = raised
    if report is not None:
        w.engine.report = report
    await w.start()
    await w.ended()
    assert w.trail == [*_REQUESTED, *_ENDED]
    over = {**FAILED, "reason": code, **NOTHING, "error": code}
    assert w.audit.records[1] == expected("finished", _RUN, **over)
    assert w.store.rows[_RUN].error_message == code


@pytest.mark.parametrize("error", [None, "OSError", "/srv/cv/backups: gone"])
async def test_a_failed_job_with_no_closed_code_ends_internal_error(
    error: str | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    w, ends = World(), list[Any]()
    monkeypatch.setattr(w.jobs, "submit", lambda *job: ends.append(job[3]))  # keeps its `on_done`
    await w.start()
    await ends[0](JobEnd("failed", None, error))  # a job runner that kept no closed code
    ended = w.store.rows[_RUN]
    assert (ended.status, ended.error_message) == ("failed", "internal_error")


_UNSTORABLE = {
    "relative": RunPlan("srv/cv/backups/1.age", True, ALIAS),
    "url": RunPlan("/s3://cv-backups/1.age", True, ALIAS),
    "userinfo": RunPlan("/srv/cv@vault/1.age", True, ALIAS),
}


@pytest.mark.parametrize("case", [*_UNSTORABLE, "raises", "hangs"])
async def test_an_unstorable_or_failed_plan_is_503_and_writes_nothing(
    case: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(limits, "PLAN_BUDGET_S", 0.05)
    w = World()
    if case in _UNSTORABLE:
        w.engine.plan_given = _UNSTORABLE[case]
    else:
        w.fail("plan", case)
    with capture_logs() as logs, pytest.raises(OpsUnavailable):
        await w.start()
    assert (w.trail, w.gate.active(), w.limit.starts) == ([], [], [])
    error = {"raises": "OSError", "hangs": "TimeoutError"}.get(case, "unstorable_plan")
    assert logs == [{"event": "backups.plan_failed", "error": error, "log_level": "error"}]


_UNENCRYPTED = {
    "plaintext": RunPlan(PLAN.location, False),
    "plaintext-with-alias": RunPlan(PLAN.location, False, ALIAS),
    "encrypted-without-alias": RunPlan(PLAN.location, True, None),
    "encrypted-with-empty-alias": RunPlan(PLAN.location, True, ""),
    "plaintext-at-a-url": RunPlan("/s3://cv-backups/1", False),  # refused as plaintext first
}


@pytest.mark.parametrize("kind", ["pg_dump", "parquet_sync"])
@pytest.mark.parametrize("case", [*_UNENCRYPTED])
async def test_an_unencrypted_plan_is_refused_with_its_record_first(
    case: str, kind: BackupKind
) -> None:
    w = World()
    w.engine.plan_given = _UNENCRYPTED[case]
    with capture_logs() as logs, pytest.raises(BackupEngineInvalid):
        await w.start("a note", kind=kind)
    invalid = "backup_engine_invalid"
    over = {**FAILED, "reason": invalid, "kind": kind, "error": invalid}
    assert w.audit.records == [expected("refused", _RUN, **over)]
    assert w.trail == [("record", "refused")]
    assert (w.store.rows, w.jobs.store.held(), w.gate.active()) == ({}, 0, [])
    assert w.limit.starts == [_USER]  # counted like a start: refusals never flood the trail
    assert logs == [{"event": "backups.plan_refused", "error": invalid, "log_level": "error"}]


@pytest.mark.parametrize(("how", "error"), [("raises", "OSError"), ("hangs", "TimeoutError")])
async def test_a_refusal_whose_record_fails_is_503_audit_unavailable(
    how: str, error: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(limits, "RECORD_BUDGET_S", 0.05)
    w = World()
    w.engine.plan_given = RunPlan(PLAN.location, False)
    w.fail("refused", how)
    with capture_logs() as logs, pytest.raises(OpsAuditUnavailable):
        await w.start()
    assert (w.trail, w.store.rows, w.limit.starts) == ([], {}, [])
    assert logs == [_UNRECORDED | {"stage": "refused", "error": error, "log_level": "error"}]


async def test_a_refused_insert_is_503_and_its_start_still_counts() -> None:
    w = World()
    w.faults.raises["insert"] = StorageQueryFailed("23503")
    with pytest.raises(OpsUnavailable):
        await w.start()
    assert (w.trail, w.gate.active()) == ([("record", "requested"), ("record", "finished")], [])
    assert w.limit.starts == [_USER]  # its record was written, so it counts


async def test_a_job_the_job_store_refuses_ends_its_request_and_is_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    w = World()

    def refuse(*job: object) -> None:
        raise RuntimeError("the job store is stopped")

    monkeypatch.setattr(w.jobs, "submit", refuse)
    with capture_logs() as logs, pytest.raises(OpsUnavailable):
        await w.start()
    assert w.trail == [*_REQUESTED, *_ENDED]
    over = {**FAILED, "reason": "internal_error", **NOTHING, "error": "internal_error"}
    assert w.audit.records[1] == expected("finished", _RUN, **over)
    assert (w.store.rows[_RUN].status, w.gate.active(), w.limit.starts) == ("failed", [], [_USER])
    refused = {"event": "backups.run_not_submitted", "backup_id": str(_RUN)}
    assert logs == [refused | {"error": "RuntimeError", "log_level": "error"}]
