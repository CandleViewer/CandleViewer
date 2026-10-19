"""Unit (E42-T05 #966 BK-12): `BackupDeletion.delete`, once the step-up grant is spent. Under the
admission lock, one delete at a time: the row read again, the contract's three conflicts in order
(Q4: a kind keeps its last verified backup), each refusal recorded first; then the write-ahead
`backup.deleted` record, the row's own artefact removed, the row marked and kept, and the
freshness reloaded. A failed removal or mark is a second record and a 503, the row unmarked; an
unwritten record is `503 audit_unavailable`. Every wait is bounded, and a cancel passes through."""

from __future__ import annotations

import asyncio
import contextlib
import copy
from collections.abc import AsyncIterator, Callable
from dataclasses import replace
from typing import Any, Final
from uuid import UUID

import pytest
from structlog.testing import capture_logs

from candleviewer.admin.backups import limits
from candleviewer.admin.backups.catalogue import READ_BUDGET_S
from candleviewer.admin.backups.deletion import DeleteRecord, DeleteRefused
from candleviewer.admin.backups.gate import BackupJobGate
from candleviewer.admin.errors import OpsAuditUnavailable, OpsUnavailable
from candleviewer.audit.actions import validate_action
from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.storage.errors import StorageQueryFailed, StorageTierUnavailable
from tests.unit.admin._admin_fakes import principal
from tests.unit.admin._backup_fakes import NOW, row
from tests.unit.admin._delete_fakes import HANG, World, job_on, world

WHO, GRANT, BID = principal("owner"), UUID(int=0xC0FFEE), UUID(int=1)
_BOUND: Final = 2.0  # seconds, a safety net only: no test waits on it when the service is right
_DOWN, _REFUSED = StorageTierUnavailable("driver text"), StorageQueryFailed("42501")
_STORE_DOWN: Final = r"^backups: store unavailable$"  # the route's detail: a fixed literal
_PAIR = (row(1), row(2))  # two verified `pg_dump`s; backup 1 is the newer


async def _delete(w: World) -> None:
    async with asyncio.timeout(_BOUND):
        await w.deletion.delete(BID, WHO, GRANT, w.write_ahead(WHO))


def _record(reason: str | None = None, status: str | None = "verified") -> dict[str, Any]:
    """The whole `backup.deleted` record of a delete of backup 1 by the owner."""
    outcome = AuditOutcome.SUCCESS if reason is None else AuditOutcome.FAILURE
    return {
        "action": "backup.deleted", "actor_label": "owner", "actor_user_id": WHO.user_id,
        "actor_ip": WHO.ip, "session_id": WHO.session_id, "object_kind": "backup",
        "object_id": str(BID), "outcome": outcome, "severity": Severity.WARNING, "reason": reason,
        "before_state": None if status is None else {"status": status},
        "after_state": {"challenge_id": str(GRANT)}, "request_id": WHO.request_id,
    }  # fmt: skip


def _held(*steps: str) -> list[tuple[str, bool]]:
    return [(step, True) for step in steps]


async def test_a_delete_records_ahead_then_removes_the_rows_artefact_then_marks_it() -> None:
    """SR-BK0-08 and SR-BK3-01: the read, the count, the record, the removal and the mark all run
    under the admission lock, the one lock BK-9's verify-outcome write takes too."""
    w = world(_PAIR)
    await _delete(w)
    assert w.trail.records == [_record()]
    assert w.log == _held("get", "usable_count", "record", "remove", "mark_deleted")
    assert w.remover.removed == [(BID, row(1).target_path)]  # the row's own, never a client's
    assert w.store.rows[0] == replace(row(1), deleted_at=NOW)  # kept, its status unchanged
    assert w.store.marked_by == {BID: WHO.user_id}


@pytest.mark.parametrize(
    ("rows", "job", "rule", "status", "steps"),
    [
        ([row(1, deleted_at=NOW)], True, "backup_deleted", "verified", ["get"]),
        ([row(1, status="running", finished_at=None)], False, "backup_in_use", "running", ["get"]),
        ([row(1)], True, "backup_in_use", "verified", ["get"]),  # before its last-usable check
        ([row(1), row(2, kind="pg_basebackup")], False, "last_usable_backup", "verified",
         ["get", "usable_count"]),
        ([], False, "not_found", None, ["get"]),  # no catalogue row is ever deleted (21 Sec.7)
    ],
    ids=["deleted", "running", "job-on-it", "last-usable", "row-gone"],
)  # fmt: skip
async def test_conflicts_are_refused_in_the_contract_order_each_recorded_first(
    rows: list[Any], job: bool, rule: str, status: str | None, steps: list[str]
) -> None:
    w = world(rows)
    if job:  # a verification running on backup 1
        await job_on(w.gate, "backup_verify", BID)
    with pytest.raises(DeleteRefused) as refused:
        await _delete(w)
    assert refused.value.rule == rule and w.trail.records == [_record(rule, status)]
    assert w.log == _held(*steps, "record") and w.remover.removed == []


@pytest.mark.parametrize(
    ("target", "other", "kept"),
    [
        ({"status": "ok", "verified_at": None}, None, False),  # never verified: protects nothing
        ({}, {}, False),
        ({"status": "restored"}, None, True),
        ({}, {"deleted_at": NOW}, True),
        ({}, {"status": "ok", "verified_at": None}, True),
        ({"status": "failed", "error_message": "verify_failed"}, None, False),  # verified once
        ({"verified_at": None}, None, False),
    ],
    ids=["ok", "another-verified", "restored", "other-deleted", "other-unverified",
         "failed-reverify", "no-verified-at"],
)  # fmt: skip
async def test_only_a_verified_undeleted_backup_is_its_kinds_last_usable(
    target: dict[str, Any], other: dict[str, Any] | None, kept: bool
) -> None:
    """Q4 and SR-BK0-07: `verified` or `restored` with `verified_at` and no `deleted_at`; the
    narrower sense of usable, so an `ok` backup never verified protects no kind."""
    w = world([row(1, **target)] + ([] if other is None else [row(2, **other)]))
    if kept:
        with pytest.raises(DeleteRefused, match="last_usable_backup"):
            await _delete(w)
    else:
        await _delete(w)
    assert (w.store.rows[0].deleted_at is None) == kept


async def test_two_deletes_of_a_kinds_last_two_verified_backups_keep_one() -> None:
    """SR-BK0-08: each counts under the lock, after the other's mark, so both cannot pass."""
    w = world(_PAIR)
    other = UUID(int=2)
    async with asyncio.timeout(_BOUND):
        ends = await asyncio.gather(
            w.deletion.delete(BID, WHO, GRANT, w.write_ahead(WHO)),
            w.deletion.delete(other, WHO, GRANT, w.write_ahead(WHO)),
            return_exceptions=True,
        )
    assert ends[0] is None and isinstance(ends[1], DeleteRefused)
    assert ends[1].rule == "last_usable_backup" and w.remover.removed == [(BID, row(1).target_path)]
    assert [r.deleted_at for r in w.store.rows] == [NOW, None]


@pytest.mark.parametrize(
    "fault", [OSError(f"{row(1).target_path}: EIO"), RuntimeError(row(1).target_path), HANG],
    ids=["raises", "engine-error", "stalls"],
)  # fmt: skip
async def test_a_failed_removal_is_503_with_a_second_record_and_the_row_unmarked(
    fault: Any,
) -> None:
    w = world(_PAIR, remove=fault, remove_budget_s=0.05)
    with capture_logs() as logs, pytest.raises(OpsUnavailable) as raised:
        await _delete(w)
    assert str(raised.value) == "backups: store unavailable"  # the route's detail: no location
    assert w.trail.records == [_record(), _record("store_unavailable")]
    assert w.log == _held("get", "usable_count", "record", "remove", "record")
    assert w.store.rows == list(_PAIR) and row(1).target_path not in repr(logs)  # the class alone
    error = "TimeoutError" if fault == HANG else type(fault).__name__
    events = [(e["event"], e["backup_id"], e["error"]) for e in logs]
    assert events == [("admin_backups.artefact_not_removed", str(BID), error)]


@pytest.mark.parametrize(
    ("faults", "marked"),
    [([_DOWN], True), ([_DOWN, HANG], False), ([HANG, _DOWN], False),
     ([_REFUSED, RuntimeError("bug")], False)],
    ids=["retried", "down-then-stalls", "stalls-then-down", "refused-then-bug"],
)  # fmt: skip
async def test_a_mark_is_tried_twice_then_503_with_a_second_record(
    faults: list[Any], marked: bool
) -> None:
    """The guard (`deleted_at IS NULL`) makes a retry after a lost commit match nothing. The
    artefact is gone either way, so a refused statement ends as an outage does, not in a 500 after
    the write-ahead record; a retried delete removes it again, idempotently, and marks."""
    w = world(_PAIR, faults={"mark_deleted": list(faults)}, mark_budget_s=0.05)
    with capture_logs() as logs:
        if marked:
            await _delete(w)
        else:
            with pytest.raises(OpsUnavailable, match=_STORE_DOWN):
                await _delete(w)
    errors = ["TimeoutError" if f == HANG else type(f).__name__ for f in faults]
    events = [(e["event"], e["backup_id"], e["attempt"], e["error"]) for e in logs]
    marks = enumerate(errors, 1)
    assert events == [("admin_backups.delete_not_marked", str(BID), n, x) for n, x in marks]
    steps = ["get", "usable_count", "record", "remove", "mark_deleted", "mark_deleted"]
    assert w.log == _held(*steps, *([] if marked else ["record"]))
    second = [] if marked else [_record("store_unavailable")]
    assert w.trail.records == [_record(), *second] and (w.store.rows[0].deleted_at == NOW) == marked


@contextlib.asynccontextmanager
async def _locked(gate: BackupJobGate) -> AsyncIterator[None]:
    """A link issue holding the admission lock for the block."""
    holding, release = asyncio.Event(), asyncio.Event()

    async def hold() -> None:
        async with gate.admit_link(UUID(int=9)):
            holding.set()
            await release.wait()

    task = asyncio.create_task(hold())
    await holding.wait()
    try:
        yield
    finally:
        release.set()
        await task


async def test_a_lock_wait_past_its_bound_is_503_recorded_ahead() -> None:
    """SR-BK7A-03: refused after the spend, so the grant is gone and the refusal is recorded."""
    w = world(_PAIR, gate=BackupJobGate(admit_wait_s=0.05))
    async with _locked(w.gate):
        with pytest.raises(OpsUnavailable, match="busy"):
            await _delete(w)
    assert w.trail.records == [_record("store_unavailable", None)] and w.store.calls == []


@pytest.mark.parametrize(
    ("faults", "status"),
    [({"get": _DOWN}, None), ({"get": HANG}, None), ({"usable_count": _DOWN}, "verified"),
     ({"usable_count": HANG}, "verified")],
    ids=["read-down", "read-stalls", "count-down", "count-stalls"],
)  # fmt: skip
async def test_a_catalogue_failing_under_the_lock_is_503_recorded_ahead(
    faults: dict[str, Any], status: str | None
) -> None:
    w = world(_PAIR, faults=faults, read_budget_s=0.05)
    with capture_logs() as logs, pytest.raises(OpsUnavailable, match=_STORE_DOWN):
        await _delete(w)
    assert w.trail.records == [_record("store_unavailable", status)] and w.remover.removed == []
    assert "driver text" not in repr(logs)
    error = "TimeoutError" if HANG in faults.values() else "StorageTierUnavailable"
    assert [(e["event"], e["error"]) for e in logs] == [("admin_backups.delete_read_failed", error)]


@pytest.mark.parametrize(
    ("rows", "fail_on", "remove", "gate_wait"),
    [
        (_PAIR, None, None, None),  # the write-ahead record: nothing is removed
        ([row(1)], "last_usable_backup", None, None),  # never the 409
        (_PAIR, "store_unavailable", OSError("EIO"), None),  # the removal's second record
        (_PAIR, "store_unavailable", None, 0.05),  # the lock-wait refusal's
    ],
    ids=["write-ahead", "conflict", "removal", "lock-wait"],
)
async def test_an_unwritten_record_is_503_audit_unavailable_and_the_row_unmarked(
    rows: list[Any], fail_on: str | None, remove: Any, gate_wait: float | None
) -> None:
    """SEC-LW-01: each record is written ahead of its answer; unwritten, the answer is
    `audit_unavailable` (the grant, spent by the route, stays spent)."""
    gate = None if gate_wait is None else BackupJobGate(admit_wait_s=gate_wait)
    w = world(rows, remove=remove, gate=gate)
    w.trail.fail_on = frozenset({fail_on})
    async with _locked(w.gate) if gate_wait else contextlib.nullcontext():
        unwritten = r"^backups: the record could not be written$"
        with capture_logs() as logs, pytest.raises(OpsAuditUnavailable, match=unwritten):
            await _delete(w)
    assert all(r.deleted_at is None for r in w.store.rows)
    assert w.remover.removed == ([(BID, row(1).target_path)] if remove else [])
    events = [(e["event"], e["error"]) for e in logs if e["event"].endswith("audit_failed")]
    assert events == [("admin_backups.delete_audit_failed", "RuntimeError")]


async def test_a_record_that_stalls_is_503_audit_unavailable() -> None:
    w = world(_PAIR, record_budget_s=0.05)

    async def stalls(_record: Any) -> None:
        await asyncio.Event().wait()

    with pytest.raises(OpsAuditUnavailable):
        async with asyncio.timeout(_BOUND):
            await w.deletion.delete(BID, WHO, GRANT, stalls)
    assert w.remover.removed == [] and w.store.rows == list(_PAIR)


async def _turns(done: Callable[[], bool]) -> None:
    """Scheduler turns, never wall-clock time, until `done()`."""
    for _ in range(100):
        if done():
            return
        await asyncio.sleep(0)
    raise AssertionError("never happened")


@pytest.mark.parametrize(
    ("setup", "step", "marked"),
    [({"remove": HANG}, "remove", False),
     ({"faults": {"mark_deleted": HANG}}, "mark_deleted", False),
     ({"remove": OSError("EIO")}, "second record", False),
     ({"faults": {"last_success_by_kind": [None, HANG]}}, "last_success_by_kind", True)],
    ids=["removal", "mark", "second-record", "recompute"],
)  # fmt: skip
async def test_a_cancel_after_the_write_ahead_record_passes_through_and_frees_the_lock(
    setup: dict[str, Any], step: str, marked: bool
) -> None:
    """A shutdown cancels a delete wherever it waits after its write-ahead record: no catch-all
    swallows the cancel (each is `except Exception`), the lock is freed and nothing more is
    written; the row stays unmarked unless its mark had landed (SR-BK12A-R3-01)."""
    w = world(_PAIR, **copy.deepcopy(setup))
    await w.freshness.start()  # so the delete's recompute reloads the kind
    write_ahead = w.write_ahead(WHO)

    async def second_stalls(entry: DeleteRecord) -> None:
        if entry.reason is not None:  # a second record never lands
            w.log.append(("second record", w.gate._lock.locked()))
            await asyncio.Event().wait()
        await write_ahead(entry)

    task = asyncio.create_task(w.deletion.delete(BID, WHO, GRANT, second_stalls))
    await _turns(lambda: (step, True) in w.log)
    task.cancel()
    await _turns(task.done)
    assert task.cancelled() and not w.gate._lock.locked() and w.trail.records == [_record()]
    assert (w.store.rows[0].deleted_at == NOW) == marked


@pytest.mark.parametrize(("target", "reloaded"), [(1, True), (2, False)], ids=["newest", "older"])
async def test_deleting_its_kinds_newest_success_reloads_the_freshness(
    target: int, reloaded: bool
) -> None:
    """BK-5 open question 2: the age never reads fresher than the catalogue; the reload runs under
    the lock, after the mark, and only for the kind's newest success."""
    w = world((row(1), row(2), row(3)))
    await w.freshness.start()
    await w.deletion.delete(UUID(int=target), WHO, GRANT, w.write_ahead(WHO))
    newest = row(2 if reloaded else 1).finished_at
    assert newest is not None
    ages = {s.labels["kind"]: s.value for f in w.gauge.collect() for s in f.samples}
    assert ages == {"pg_dump": (NOW - newest).total_seconds()}
    reads = [held for step, held in w.log if step == "last_success_by_kind"]
    assert reads == ([False, True] if reloaded else [False])  # the boot load, then the reload


def test_each_wait_defaults_to_its_limits_budget() -> None:
    d = world().deletion
    budgets = (d._read_budget_s, d._record_budget_s, d._remove_budget_s, d._mark_budget_s)
    assert budgets == (READ_BUDGET_S, limits.DELETE_RECORD_BUDGET_S, limits.REMOVE_BUDGET_S,
                       limits.WRITE_BUDGET_S) == (2.0, 2.0, 10.0, 2.0)  # fmt: skip
    assert limits.WRITE_TRIES == 2


def test_backup_deleted_is_a_registered_action() -> None:
    assert validate_action("backup.deleted") == "backup.deleted"  # SR-E42-11, AD-F17
