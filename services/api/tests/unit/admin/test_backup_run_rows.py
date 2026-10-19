"""Unit (E42-T05 #966 BK-8): a backup run's row and its `backup.run` records. The `finished`
record ahead of the row's end, a bound on every await, a second try at the row's write, a row
that cannot be inserted ending its request, and the runs a restart lost (SR-BK7-05)."""

from __future__ import annotations

import asyncio
from uuid import UUID

import pytest
from structlog.testing import capture_logs

from candleviewer.admin.backups import limits
from candleviewer.admin.backups.rows import Actor, LostRuns
from candleviewer.admin.errors import OpsUnavailable
from candleviewer.audit.redact import redact
from candleviewer.storage.errors import StorageQueryFailed, StorageTierUnavailable
from candleviewer.storage.repositories.backups import NewBackup, RunFinished
from tests.unit.admin._backup_fakes import row
from tests.unit.admin._run_fakes import (
    ACTOR,
    BOUND,
    DIGEST,
    FAILED,
    NOTHING,
    NOW,
    OWNER,
    Ledger,
    Marked,
    expected,
)

_SYSTEM: Actor = {
    "actor_label": "system:backups", "actor_user_id": None, "actor_ip": None,
    "session_id": None, "request_id": None,
}  # fmt: skip
_ID = UUID(int=7)
_OK = RunFinished(NOW, None, size_bytes=1234, checksum_sha256=DIGEST)
_NEW = NewBackup(_ID, "pg_dump", "/srv/cv/backups/7.dump.age", True, "manual", OWNER.user_id, NOW)


async def test_an_end_writes_its_finished_record_before_the_row() -> None:
    w = Ledger()
    w.running(7)
    assert await w.rows.end(ACTOR, _ID, _OK) is True
    assert w.trail == [("record", "finished"), ("finish", "ok")]
    finished = w.audit.records[0]
    assert finished == expected(
        "finished", _ID, size_bytes=1234, checksum_sha256=DIGEST, error=None
    )
    assert redact(finished["after_state"]) == finished["after_state"]  # BK-9 reads the digest


async def test_an_ok_end_binds_the_digest_and_moves_the_freshness() -> None:
    w, result = Ledger(), dict[str, object](backup_id=str(_ID))
    w.running(7)
    await w.rows.end(ACTOR, _ID, _OK, result=result)
    ended = w.store.rows[_ID]
    assert (ended.status, ended.size_bytes, ended.checksum_sha256) == ("ok", 1234, DIGEST)
    assert (ended.finished_at, w.ages(), result) == (NOW, {"pg_dump": 0.0}, {"backup_id": str(_ID)})


async def test_a_failed_end_records_its_code_and_moves_no_freshness() -> None:
    w = Ledger()
    w.running(7)
    await w.rows.end(ACTOR, _ID, RunFinished(NOW, "artefact_missing"))
    over = {**FAILED, "reason": "artefact_missing", **NOTHING, "error": "artefact_missing"}
    assert w.audit.records == [expected("finished", _ID, **over)]
    assert (w.store.rows[_ID].status, w.ages()) == ("failed", {})


@pytest.mark.parametrize("how", ["raises", "hangs"])  # hangs: cut off at its own bound
async def test_an_end_whose_record_fails_marks_the_job_then_never_ends_ok(
    how: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(limits, "RECORD_BUDGET_S", 0.05)
    w = Ledger()
    w.running(7)
    w.fail("finished", how)
    result = Marked(w.trail, backup_id=str(_ID))
    with capture_logs() as logs:
        async with asyncio.timeout(BOUND):  # an unbounded record fails here, never hangs
            assert await w.rows.end(ACTOR, _ID, _OK, result=result) is True
    assert w.trail == [("result", "audit"), ("finish", "failed")]  # the job's mark, then the row
    ended = w.store.rows[_ID]
    assert (ended.status, ended.error_message) == ("failed", "audit_unavailable")
    assert (ended.size_bytes, ended.checksum_sha256, w.ages()) == (None, None, {})
    assert result == {"backup_id": str(_ID), "audit": "unavailable"}
    error = "TimeoutError" if how == "hangs" else "OSError"
    unrecorded = {"event": "backups.run_unrecorded", "stage": "finished", "error": error}
    assert logs == [unrecorded | {"log_level": "error"}]


async def test_an_end_write_that_fails_once_is_tried_again() -> None:
    w = Ledger()
    w.running(7)
    w.faults.raises["finish"] = [StorageTierUnavailable("backups: down")]
    with capture_logs() as logs:
        assert await w.rows.end(ACTOR, _ID, _OK) is True
    assert (w.store.ending, w.store.rows[_ID].status, w.ages()) == ([_ID] * 2, "ok", {"pg_dump": 0})
    first = {"event": "backups.run_not_ended", "backup_id": str(_ID), "attempt": 1}
    assert logs == [first | {"error": "StorageTierUnavailable", "log_level": "error"}]


@pytest.mark.parametrize("how", ["raises", "hangs"])
async def test_an_end_write_that_fails_twice_leaves_the_row_running(
    how: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(limits, "WRITE_BUDGET_S", 0.05)
    w = Ledger()
    w.running(7)
    if how == "hangs":
        w.faults.hangs.add("finish")
    else:
        w.faults.raises["finish"] = StorageTierUnavailable("backups: down")
    with capture_logs() as logs:
        async with asyncio.timeout(BOUND):  # an unbounded write fails here, never hangs
            assert await w.rows.end(ACTOR, _ID, _OK) is False
    assert (w.store.ending, w.store.rows[_ID].status) == ([_ID] * 2, "running")  # a boot ends it
    error = "TimeoutError" if how == "hangs" else "StorageTierUnavailable"
    tried = dict[str, object](event="backups.run_not_ended", backup_id=str(_ID), error=error)
    assert logs == [tried | {"attempt": n, "log_level": "error"} for n in (1, 2)]


async def test_an_insert_adds_the_running_row_and_records_nothing() -> None:
    w = Ledger()
    inserted = await w.rows.insert(ACTOR, _NEW)
    assert (w.trail, w.store.inserted, inserted) == (
        [("insert", "running")],
        [_NEW],
        w.store.rows[_ID],
    )


_UNINSERTED = {
    "outage": StorageTierUnavailable("backups: down /srv/cv"),
    "refused": StorageQueryFailed("23503"),
    "bad-value": ValueError("target_path /srv/cv"),
}


@pytest.mark.parametrize("case", [*_UNINSERTED, "hangs"])
async def test_an_insert_that_fails_ends_its_request_then_is_503(
    case: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(limits, "WRITE_BUDGET_S", 0.05)
    w = Ledger()
    if case == "hangs":
        w.faults.hangs.add("insert")
    else:
        w.faults.raises["insert"] = _UNINSERTED[case]
    with capture_logs() as logs, pytest.raises(OpsUnavailable):
        async with asyncio.timeout(BOUND):  # an unbounded insert fails here, never hangs
            await w.rows.insert(ACTOR, _NEW)
    code = "store_unavailable" if case in ("outage", "hangs") else "internal_error"
    over = {**FAILED, "reason": code, **NOTHING, "error": code}
    assert (w.audit.records, w.trail) == (
        [expected("finished", _ID, **over)],
        [("record", "finished")],
    )
    assert (w.store.rows, w.store.ending) == ({}, [_ID])  # a row whose commit landed is ended too
    error = "TimeoutError" if case == "hangs" else type(_UNINSERTED[case]).__name__
    inserted = {"event": "backups.run_not_inserted", "backup_id": str(_ID), "error": error}
    assert logs == [inserted | {"log_level": "error"}]


async def test_lost_runs_end_failed_once_record_first_and_are_counted() -> None:
    w = Ledger()
    lost = w.running(1, 2)
    w.store.rows[row(3).id] = row(3)
    with capture_logs() as logs:
        await LostRuns(w.rows).start()  # what the lifespan awaits at boot
    assert w.trail == [("record", "finished"), ("finish", "failed")] * 2
    over = {**FAILED, "reason": "lost_on_restart", **NOTHING, "error": "internal_error"}
    assert w.audit.records == [expected("finished", r.id, _SYSTEM, **over) for r in lost]
    assert [w.store.rows[r.id].error_message for r in lost] == ["internal_error"] * 2
    ended = {"event": "backups.lost_runs_ended", "count": 2, "log_level": "info"}
    assert (w.lost.added, logs, w.store.rows[row(3).id]) == ([2], [ended], row(3))
    with capture_logs() as again:
        assert await w.rows.close_lost() == 0  # a second boot finds none
    assert (again, w.lost.added, len(w.trail)) == ([], [2], 4)


@pytest.mark.parametrize("how", ["raises", "hangs"])
async def test_lost_runs_ended_in_an_audit_outage_are_counted_all_the_same(
    how: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#966 Q4: such a row ends `audit_unavailable` with no record, and the counter shows it."""
    monkeypatch.setattr(limits, "RECORD_BUDGET_S", 0.05)
    w = Ledger()
    lost = w.running(1, 2)
    w.fail("finished", how)
    async with asyncio.timeout(BOUND):
        assert await w.rows.close_lost() == 2
    assert (w.trail, w.lost.added) == ([("finish", "failed")] * 2, [2])
    assert [w.store.rows[r.id].error_message for r in lost] == ["audit_unavailable"] * 2


@pytest.mark.parametrize("how", ["page-raises", "page-hangs", "finish-raises"])
async def test_lost_runs_that_cannot_be_read_or_ended_never_fail_boot(
    how: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(limits, "LOST_READ_BUDGET_S", 0.05)
    w = Ledger()
    lost = w.running(1, 2)
    if how == "page-hangs":
        w.faults.hangs.add("page")
    else:
        w.faults.raises[how.split("-")[0]] = StorageTierUnavailable("backups: down")
    with capture_logs() as logs:
        async with asyncio.timeout(BOUND):  # an unbounded read fails here, never hangs
            assert await w.rows.close_lost() == 0
    stopped = [("record", "finished")] if how == "finish-raises" else []  # at the first outage
    statuses = [w.store.rows[r.id].status for r in lost]
    assert (w.trail, statuses, w.lost.added) == (stopped, ["running"] * 2, [])
    assert "backups: down" not in repr(logs)  # the class only, never the store's text


async def test_a_boot_ends_at_most_its_limit_of_lost_runs() -> None:
    w = Ledger()
    w.running(*range(1, limits.LOST_RUNS_LIMIT + 2))  # one more than a boot ends
    assert await w.rows.close_lost() == limits.LOST_RUNS_LIMIT
    assert [r.status for r in w.store.rows.values()].count("running") == 1
    assert (await w.rows.close_lost(), w.lost.added) == (1, [limits.LOST_RUNS_LIMIT, 1])
