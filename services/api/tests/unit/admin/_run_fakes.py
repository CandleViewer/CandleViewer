"""Backup run fakes (E42-T05 #966 BK-8): one trail that every `backup.run` record and catalogue
write joins in order, and an audit writer, a catalogue and an engine whose steps a test can fail
or stall (`Faults`); jobs run in the real admin job store."""

from __future__ import annotations

import asyncio
import itertools
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from candleviewer.admin.backups.gate import BackupJobGate
from candleviewer.admin.backups.metrics import BackupFreshness
from candleviewer.admin.backups.ports import JobDone, JobKind, JobWork, RunPlan
from candleviewer.admin.backups.rows import Actor, RunRows
from candleviewer.admin.backups.runs import BackupRuns
from candleviewer.api.recorder_admin import AdminJobStore
from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.backups_wiring import AdminJobRunner
from candleviewer.observability.metrics import Gauge
from candleviewer.storage.repositories.backups import BackupKind, BackupRow, NewBackup, RunFinished
from tests.unit.admin._admin_fakes import principal
from tests.unit.admin._backup_fakes import row

NOW = datetime(2026, 10, 18, 20, 0, tzinfo=UTC)
DIGEST = "ab" * 32
ALIAS = "age:" + "offsite-2026"  # a keyring alias: class S, never logged or served
PLAN = RunPlan("/srv/cv/backups/pg/2026-10-18.dump.age", True, ALIAS)
OWNER = principal("owner")
BOUND = 2.0  # seconds, a safety net only: no test waits on it when the code is right
Trail = list[tuple[str, str]]
ACTOR: Actor = {
    "actor_label": "owner", "actor_user_id": OWNER.user_id, "actor_ip": OWNER.ip,
    "session_id": OWNER.session_id, "request_id": OWNER.request_id,
}  # fmt: skip
FAILED = {"outcome": AuditOutcome.FAILURE, "severity": Severity.WARNING}
NOTHING = {"size_bytes": None, "checksum_sha256": None}


def expected(stage: str, backup_id: UUID, actor: Actor = ACTOR, /, **over: Any) -> dict[str, Any]:
    """The whole `backup.run` record: `over` sets the outcome, severity, reason or state."""
    record = {"action": "backup.run", **actor, "object_kind": "backup", "object_id": str(backup_id)}
    record |= {"outcome": AuditOutcome.SUCCESS, "severity": Severity.INFO, "reason": None}
    record |= {k: over.pop(k) for k in ("outcome", "severity", "reason") if k in over}
    return record | {"after_state": {"stage": stage, **over}}


class Faults:
    """Per step: raise `raises[step]` (a list: one per call, then none), or wait forever when
    `step` is in `hangs`."""

    def __init__(self) -> None:
        self.raises: dict[str, BaseException | list[BaseException | None]] = {}
        self.hangs: set[str] = set()

    async def at(self, step: str) -> None:
        if step in self.hangs:
            await asyncio.Event().wait()
        fault = self.raises.get(step)
        if isinstance(fault, list):
            if fault and (once := fault.pop(0)) is not None:
                raise once
        elif fault is not None:
            raise fault


class Audit:
    """`AuditWriter.emit` as the runs call it; a record is kept once it would be durable."""

    def __init__(self, trail: Trail, faults: Faults) -> None:
        self.trail, self.faults, self.records = trail, faults, list[dict[str, Any]]()

    async def emit(self, action: str, **record: Any) -> None:
        stage = record["after_state"]["stage"]
        await self.faults.at(stage)
        self.records.append({"action": action, **record})
        self.trail.append(("record", stage))


class Catalogue:
    """BK-3's run writes in memory, guarded as on Postgres (a run ends only while `running`)."""

    def __init__(self, trail: Trail, faults: Faults) -> None:
        self.trail, self.faults, self.rows = trail, faults, dict[UUID, BackupRow]()
        self.inserted, self.ending = list[NewBackup](), list[UUID]()

    async def page(
        self, kind: str | None, status: str | None, after: object, limit: int
    ) -> list[BackupRow]:
        await self.faults.at("page")
        return [r for r in self.rows.values() if r.status == status][:limit]

    async def get(self, backup_id: UUID) -> BackupRow | None:
        await self.faults.at("get")
        return self.rows.get(backup_id)

    async def insert_running(self, new: NewBackup) -> BackupRow:
        await self.faults.at("insert")
        self.inserted.append(new)
        self.rows[new.id] = BackupRow(
            new.id, new.kind, "running", new.target_path, None, None, new.encrypted, None, None,
            None, new.triggered_by, new.started_at, None, None, None,
        )  # fmt: skip
        self.trail.append(("insert", "running"))
        return self.rows[new.id]

    async def record_run_finished(self, backup_id: UUID, run: RunFinished) -> BackupRow | None:
        self.ending.append(backup_id)
        await self.faults.at("finish")
        found = self.rows.get(backup_id)
        if found is None or found.status != "running":
            return None
        status: Any = "failed" if run.error else "ok"
        self.rows[backup_id] = replace(
            found, status=status, error_message=run.error, finished_at=run.finished_at,
            size_bytes=run.size_bytes, checksum_sha256=run.checksum_sha256,
        )  # fmt: skip
        self.trail.append(("finish", status))
        await self.faults.at("commit")  # applied, and still the answer may be lost
        return self.rows[backup_id]


class Lost:
    """`LostCount`: what a boot adds to `cv_admin_jobs_lost_on_restart_total`."""

    def __init__(self) -> None:
        self.added: list[float] = []

    def inc(self, amount: float = 1) -> None:
        self.added.append(amount)


class Marked(dict[str, object]):
    """A job `result` whose every change joins the trail."""

    def __init__(self, trail: Trail, **items: object) -> None:
        super().__init__(items)
        self.trail = trail

    def __setitem__(self, key: str, value: object) -> None:
        self.trail.append(("result", key))
        super().__setitem__(key, value)


class Ledger:
    """A `RunRows` over these fakes: one trail, one set of faults, a gauge of its own."""

    def __init__(self) -> None:
        self.trail, self.faults, self.lost = Trail(), Faults(), Lost()
        self.store, self.audit = Catalogue(self.trail, self.faults), Audit(self.trail, self.faults)
        self.gauge = Gauge("cv_backup_last_success_age_seconds", "age", ["kind"], registry=None)
        freshness = BackupFreshness(None, now=lambda: NOW, gauge=self.gauge)
        self.rows = RunRows(
            self.store, self.audit, lost=self.lost, freshness=freshness, now=lambda: NOW
        )

    def ages(self) -> dict[str, float]:
        samples = [sample for family in self.gauge.collect() for sample in family.samples]
        return {sample.labels["kind"]: sample.value for sample in samples}

    def running(self, *ns: int) -> list[BackupRow]:
        """Rows `ns` (`_backup_fakes.row`), `running`, in the catalogue."""
        rows = [row(n, status="running", finished_at=None) for n in ns]
        self.store.rows |= {r.id: r for r in rows}
        return rows

    def fail(self, step: str, how: str) -> None:
        if how == "hangs":
            self.faults.hangs.add(step)
        else:  # its text, a path, is never logged
            self.faults.raises[step] = OSError("/var/lib/cv/audit/wal.bin: no space left")


class Engine:
    """A `BackupRunner`: the plan given, and a run that reports progress, then waits for `go`
    before it reports; it keeps every call."""

    def __init__(self, faults: Faults) -> None:
        self.faults, self.plan_given = faults, PLAN
        self.report: tuple[int, str | None] = (1234, DIGEST)
        self.go, self.calls = asyncio.Event(), list[tuple[object, ...]]()
        self.go.set()

    async def plan(self, kind: str) -> RunPlan:
        self.calls.append(("plan", kind))
        await self.faults.at("plan")
        return self.plan_given

    async def run(
        self, backup_id: UUID, plan: RunPlan, progress: Callable[[float], None]
    ) -> tuple[int, str | None]:
        self.calls.append(("run", backup_id, plan))
        progress(50.0)
        await self.go.wait()
        await self.faults.at("run")
        return self.report


class Jobs:
    """`AdminJobRunner` over a real job store; `settled` is set as each job's entry goes."""

    def __init__(self) -> None:
        self.store, self.settled = AdminJobStore(), asyncio.Event()

    def submit(
        self, kind: JobKind, job_id: UUID, work: JobWork, on_done: JobDone, on_settled: Any
    ) -> None:
        def settled() -> None:
            on_settled()
            self.settled.set()

        AdminJobRunner(self.store).submit(kind, job_id, work, on_done, settled)


class Limit:
    """A `StartLimit` that refuses with `wait` once set, and keeps every recorded start."""

    def __init__(self) -> None:
        self.wait: int | None = None
        self.starts: list[str] = []

    def retry_after(self, user: str) -> int | None:
        return self.wait

    def record_start(self, user: str) -> None:
        self.starts.append(user)


class World(Ledger):
    """A `BackupRuns` over the ledger's `RunRows`, an engine, a gate and a limit of its own; its
    runs are numbered from 1001 (`UUID(int=1001)`), outside every id `principal` gives."""

    def __init__(
        self, limit: Any = None, *, store: bool = True, engine: bool = True, gate: Any = None
    ) -> None:
        super().__init__()
        self.engine, self.jobs = Engine(self.faults), Jobs()
        self.gate = BackupJobGate() if gate is None else gate
        self.limit = Limit() if limit is None else limit
        ids = (UUID(int=n) for n in itertools.count(1001))
        self.runs = BackupRuns(
            self.rows if store else None, self.engine if engine else None, gate=self.gate,
            jobs=self.jobs, audit=self.audit, limit=self.limit, now=lambda: NOW,
            new_id=lambda: next(ids),
        )  # fmt: skip

    async def start(
        self, note: str | None = None, *, kind: BackupKind = "pg_dump", verify: bool = True
    ) -> BackupRow:
        """A run as the route starts one: its handler's `write_ahead` writes the record."""

        async def write_ahead(backup_id: UUID, kind: BackupKind) -> None:
            await self.runs.audit_requested(OWNER, backup_id, kind=kind, verify=verify, note=note)

        async with asyncio.timeout(BOUND):
            return await self.runs.start(OWNER, kind=kind, write_ahead=write_ahead)

    async def ended(self) -> None:
        """Until the last job's entry is released: its end has run, however it went."""
        async with asyncio.timeout(BOUND):
            await self.jobs.settled.wait()
        self.jobs.settled.clear()
