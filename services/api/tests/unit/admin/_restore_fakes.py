"""Restore guard fakes (E42-T05 #966 BK-13): every port the guard reads in one object, an audit
writer and a job runner a test can fail or stall, an executor that halts trading, and one trail
that each read, record, submit and restore joins in order."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final, cast
from uuid import UUID

from candleviewer.admin.backups import metrics, ports, restore
from candleviewer.admin.backups.gate import BackupJobGate
from candleviewer.storage.repositories.backups import BackupRow
from tests.unit.admin._admin_fakes import principal
from tests.unit.admin._backup_fakes import row

OWNER: Final = principal("owner")
BACKUP: Final = row(1)  # verified, encrypted, kept
DIGEST: Final = f"{1:064x}"  # BACKUP's own, as its run's `backup.run` record bound it
REASON: Final = "roll back the 03:00 schema change"
COMPONENTS: Final = frozenset({"postgres", "config"})
HANG: Final = object()  # an answer that never comes
BOUND: Final = 2.0  # seconds, a safety net only: no test waits on it when the guard is right
Trail = list[str]
Job = tuple[ports.JobKind, UUID, ports.JobWork, ports.JobDone, ports.Settled]
#: The precondition matrix (`test_precondition_matrix`, unit and Postgres): each state's answer.
MAINTENANCE: Final[Mapping[str, object]] = {"on": True, "off": False, "unknown": None}
POSITIONS: Final[Mapping[str, object]] = {"none": 0, "two": 2, "unknown": None}


def expected(maintenance: str, positions: str, ack_open: bool, ack_unknown: bool) -> str:
    """The contract's answer: `accepted`, the refusing rule, or `503` (raised)."""
    if maintenance != "on":
        return "maintenance_mode_required" if maintenance == "off" else "503"
    if positions == "unknown" and not ack_unknown:
        return "positions_unknown"
    if positions == "two" and not ack_open:
        return "open_positions_unacknowledged"
    return "accepted"


@dataclass(frozen=True, slots=True)
class Grant:
    """The spent one-shot `backups` grant, named as `api.step_up.SpentGrant` names it."""

    challenge_id: UUID


GRANT: Final = Grant(UUID(int=0xC4A1))


def request(**over: Any) -> restore.RestoreRequest:
    fields: dict[str, Any] = {"backup_id": BACKUP.id, "reason": REASON, "components": COMPONENTS}
    return restore.RestoreRequest(**(fields | over))


async def _answer(value: object, held: asyncio.Event | None = None) -> Any:
    if held is not None:
        await held.wait()
    if value is HANG:
        await asyncio.Event().wait()
    if isinstance(value, BaseException):
        raise value
    return value


class Ports:
    """Each port the guard reads, in one object: `answers[name]` is what the read returns (a
    `BaseException` is raised, `HANG` never answers), once `held[name]`, if any, is set."""

    source = "fake"

    def __init__(self, trail: Trail, **answers: object) -> None:
        defaults = {"maintenance": True, "row": BACKUP, "digest": DIGEST, "positions": 0}
        self.answers: dict[str, object] = defaults | {"revocations": None} | answers
        self.trail, self.held, self.asked = trail, dict[str, asyncio.Event](), list[object]()
        self._started = dict[str, asyncio.Event]()

    def started(self, name: str) -> asyncio.Event:
        """Set once a read of `name` has begun."""
        return self._started.setdefault(name, asyncio.Event())

    async def _read(self, name: str, *args: object) -> Any:
        self.trail.append(name)
        self.asked.append((name, *args))
        self.started(name).set()
        return await _answer(self.answers[name], self.held.get(name))

    async def read(self) -> bool | None:  # `MaintenanceState`
        return cast("bool | None", await self._read("maintenance"))

    async def get(self, backup_id: UUID) -> BackupRow | None:  # the catalogue row
        return cast("BackupRow | None", await self._read("row", backup_id))

    async def bound_digest(self, backup_id: UUID) -> str | None:  # `RunEvidence`
        return cast("str | None", await self._read("digest", backup_id))

    async def count_open(self) -> int | None:  # `OpenPositions`
        return cast("int | None", await self._read("positions"))

    async def refusal(self, backup: BackupRow, request: Any) -> str | None:  # #3084's check
        return cast("str | None", await self._read("revocations", backup, request))


class Audit:
    """`AuditWriter.emit` as the guard calls it: a record is kept once it would be durable;
    `faults[stage]` raises (a `BaseException`) or never answers (`HANG`)."""

    def __init__(self, trail: Trail) -> None:
        self.trail, self.records, self.faults = trail, list[dict[str, Any]](), dict[str, object]()
        self.finished, self.counts = asyncio.Event(), list[dict[str, float]]()

    async def emit(self, action: str, **record: Any) -> None:
        stage = record["after_state"]["stage"]
        self.counts.append(restores())  # what `cv_restore_jobs_total` read as it was written
        await _answer(self.faults.get(stage))
        self.records.append({"action": action, **record})
        self.trail.append(f"record:{stage}")
        if stage == "finished":
            self.finished.set()


class Jobs:
    """`JobRunner` that keeps each job for the test to drive; `error` refuses to start one."""

    def __init__(self, trail: Trail) -> None:
        self.trail, self.error = trail, cast(BaseException | None, None)
        self.jobs: list[Job] = []

    def submit(self, kind: Any, job_id: UUID, work: Any, on_done: Any, on_settled: Any) -> None:
        if self.error is not None:
            raise self.error
        self.trail.append("submit")
        self.jobs.append((kind, job_id, work, on_done, on_settled))


class Executor:
    """`RestoreExecutor` that halts trading as it starts and holds the halt: only the end of the
    restore's step 8 lifts it (threat model §6 step 7), which no failure or cancel reaches."""

    def __init__(self, trail: Trail) -> None:
        self.trail, self.outcome, self.halted = trail, cast(object, None), False
        self.calls: list[tuple[UUID, str, frozenset[ports.Component]]] = []

    async def restore(self, backup_id: UUID, location: str, components: Any, progress: Any) -> Any:
        self.calls.append((backup_id, location, components))
        self.trail.append("restore")
        self.halted = True
        progress(50.0)
        await _answer(self.outcome)
        return {"engine": "its own detail"}  # never the job's result


@dataclass
class Rig:
    trail: Trail
    ports: Ports
    audit: Audit
    jobs: Jobs
    executor: Executor
    gate: BackupJobGate
    guard: restore.RestoreGuard

    async def admit(self, **over: Any) -> restore.RestoreAccepted | restore.RestoreRefused:
        async with asyncio.timeout(BOUND):
            return await self.guard.admit(request(**over), OWNER, GRANT)


def rig(
    *, gate: BackupJobGate | None = None, runner: ports.JobRunner | None = None, **answers: object
) -> Rig:
    trail = Trail()
    reads, audit, jobs = Ports(trail, **answers), Audit(trail), Jobs(trail)
    executor, gate = Executor(trail), gate or BackupJobGate()
    guard = restore.RestoreGuard(
        executor, revocations=reads, gate=gate, jobs=runner or jobs, audit=audit, rows=reads,
        evidence=reads, maintenance=reads, positions=reads,
    )  # fmt: skip
    return Rig(trail, reads, audit, jobs, executor, gate, guard)


def restores() -> dict[str, float]:
    """`cv_restore_jobs_total` by result, as the module's counter reads now."""
    return {r: metrics.restore_jobs_total.labels(r)._value.get() for r in metrics.RESTORE_RESULTS}


def counted(before: dict[str, float]) -> dict[str, float]:
    """What each result gained since `before`, the zeros dropped."""
    return {result: n - before[result] for result, n in restores().items() if n != before[result]}
