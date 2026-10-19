"""Unit (E42-T05, #966): the backups composition. BK-7: stable job codes (C-12.6), unknown
positions. BK-4: the catalogue reads answer `501` on every backend until `BACKUPS_CATALOGUED` is
set (Q3); once it is, what each backend serves. BK-8: a run answers `501` until an engine is
wired, through the app's one admission gate."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any, Literal, cast
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from structlog.testing import capture_logs

import candleviewer.app as app_module
import candleviewer.backups_wiring as wiring
from candleviewer.admin.backups import limits, ports
from candleviewer.admin.backups.gate import BackupJobGate
from candleviewer.admin.backups.ports import BackupJobError, JobEnd, JobErrorCode, OpenPositions
from candleviewer.admin.backups.rows import LostRuns
from candleviewer.admin.errors import OpsNotWired, PositionsUnknownError
from candleviewer.api.audit_limiter import AuditVerifyLimiter
from candleviewer.api.deny_by_default import served_operations
from candleviewer.api.recorder_admin import AdminJobStore
from candleviewer.app import create_app
from candleviewer.backups_wiring import AdminJobRunner, UnknownOpenPositions
from candleviewer.settings import Settings
from candleviewer.storage.repositories import backups
from candleviewer.storage.repositories.system_settings_sqlalchemy import SqlAlchemySystemSettings
from tests.unit.admin._admin_fakes import principal
from tests.unit.admin._backup_fakes import Store, row
from tests.unit.admin._run_fakes import Lost

_PATH = "/srv/cv/backups/2026-10-18/pg_dump.age"


async def _failed(raised: Exception) -> tuple[dict[str, object], list[JobEnd]]:
    """The view of a backups job whose work raised `raised`, and what its `on_done` got."""
    store, ends, settled, job_id = AdminJobStore(), list[JobEnd](), asyncio.Event(), uuid4()

    async def work(progress: Callable[[float], None]) -> dict[str, object]:
        raise raised

    async def done(end: JobEnd) -> None:
        ends.append(end)

    AdminJobRunner(store).submit("backup_verify", job_id, work, done, settled.set)
    for _ in range(10):  # scheduler turns: the job fails in its first step, then settles
        await asyncio.sleep(0)
    job = store.get(str(job_id))
    assert settled.is_set() and job is not None
    return job.view(), ends


@pytest.mark.parametrize(
    ("raised", "code"),
    [
        (BackupJobError("checksum_mismatch"), "checksum_mismatch"),
        (BackupJobError(cast(JobErrorCode, f"{_PATH} vanished")), "internal_error"),
        (FileNotFoundError(_PATH), "internal_error"),
        (PositionsUnknownError(_PATH), "internal_error"),  # another module's typed `code`
    ],
    ids=["closed-set", "foreign-code", "os-error", "typed-error-of-another-module"],
)
async def test_job_errors_are_stable_codes_never_class_names_or_messages(
    raised: Exception, code: str
) -> None:
    with capture_logs() as logs:
        view, ends = await _failed(raised)
    assert (view["status"], view["error"], ends) == ("failed", code, [JobEnd("failed", None, code)])
    assert type(raised).__name__ not in str(view) and _PATH not in f"{view}{logs}"
    failed = {"event": "backups.job_failed", "kind": "backup_verify", "job_id": view["id"]}
    failed |= {"error": type(raised).__name__, "log_level": "error"}  # the operator's, alone
    assert logs == ([failed] if code == "internal_error" else [])


async def test_a_failing_logger_never_replaces_the_closed_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def down(*args: object, **kwargs: object) -> None:
        raise RuntimeError("log sink down")

    logger = SimpleNamespace(error=down)
    monkeypatch.setattr("candleviewer.backups_wiring.structlog.get_logger", lambda *_: logger)
    view, ends = await _failed(FileNotFoundError(_PATH))
    assert (view["error"], ends) == ("internal_error", [JobEnd("failed", None, "internal_error")])


def test_job_error_codes_are_the_catalogues() -> None:
    """BK-7 open question 1: a job's `error` and its row's are one closed set, not two copies."""
    assert ports.JOB_ERROR_CODES is backups.BACKUP_ERROR_CODES
    assert ports.JobErrorCode == backups.BackupErrorCode
    assert ports.VerifyMethod == backups.VerifyMethod


async def test_unknown_positions_are_none_never_zero() -> None:
    positions: OpenPositions = UnknownOpenPositions()
    assert (positions.source, await positions.count_open()) == ("not_deployed", None)


@pytest.fixture
def engines(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """The engine each `SqlAlchemyBackups` stand-in was built on; each serves backup 1."""
    built: list[Any] = []

    def store(relational: Any) -> Store:
        built.append(relational)
        return Store([row(1)])

    monkeypatch.setattr(wiring, "SqlAlchemyBackups", store)
    monkeypatch.setattr(wiring, "SqlAlchemyRelationalRepository", lambda dsn, suffix: suffix)
    return built


@pytest.fixture
def catalogued(monkeypatch: pytest.MonkeyPatch) -> None:
    """What the engine's PR sets: something now records runs in the catalogue."""
    monkeypatch.setattr(wiring, "BACKUPS_CATALOGUED", True)


@pytest.mark.parametrize("backend", ["fake", "real"])
async def test_backups_answer_501_on_every_backend_until_catalogued(
    backend: Literal["fake", "real"], engines: list[Any]
) -> None:
    # Manual backups exist outside the catalogue: an empty page would read as "no backups".
    catalogue = wiring.build_admin_backups(Settings(storage_backend=backend), system_settings=None)
    with pytest.raises(OpsNotWired):
        await catalogue.page(kind=None, status=None, cursor=None, limit=1)
    with pytest.raises(OpsNotWired):
        await catalogue.get(UUID(int=1))
    assert engines == []  # no reader and no engine were even built


@pytest.mark.usefixtures("catalogued")
async def test_the_fake_backend_never_has_a_catalogue(engines: list[Any]) -> None:
    catalogue = wiring.build_admin_backups(Settings(storage_backend="fake"), system_settings=None)
    with pytest.raises(OpsNotWired):
        await catalogue.get(UUID(int=1))
    assert engines == []


@pytest.mark.usefixtures("catalogued")
async def test_the_real_backend_reads_the_catalogue_on_the_admin_engine(engines: list[Any]) -> None:
    catalogue = wiring.build_admin_backups(Settings(storage_backend="real"), system_settings=None)
    assert (await catalogue.get(UUID(int=1)), engines) == (row(1), ["admin"])


@pytest.mark.usefixtures("catalogued")
def test_the_real_backend_shares_the_settings_stores_engine(engines: list[Any]) -> None:
    shared: Any = object()
    store = SqlAlchemySystemSettings(shared)
    wiring.build_admin_backups(Settings(storage_backend="real"), system_settings=store)
    assert engines == [shared]  # not a second engine


@pytest.mark.parametrize(
    ("backend", "catalogued"), [("fake", False), ("fake", True), ("real", False)]
)
async def test_a_run_answers_501_until_a_backup_engine_is_wired(
    backend: Literal["fake", "real"],
    catalogued: bool,
    engines: list[Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(wiring, "BACKUPS_CATALOGUED", catalogued)
    audit, gate = SimpleNamespace(emit=AsyncMock()), BackupJobGate()
    runs, lost_runs = wiring.build_backup_runs(
        Settings(storage_backend=backend), AdminJobStore(), audit, gate=gate, lost=Lost(),
        system_settings=None, freshness=None,
    )  # fmt: skip
    with pytest.raises(OpsNotWired):
        await runs.start(principal("owner"), kind="pg_dump", write_ahead=AsyncMock())
    assert (audit.emit.await_count, runs._rows, lost_runs, engines) == (0, None, None, [])
    assert (runs._gate, cast(AuditVerifyLimiter, runs._limit)._rate) == (gate, limits.RUNS_PER_HOUR)


async def test_once_catalogued_the_real_backend_has_the_boot_pass(
    engines: list[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(wiring, "BACKUPS_CATALOGUED", True)
    freshness, gate, lost = cast(Any, object()), BackupJobGate(), Lost()
    runs, lost_runs = wiring.build_backup_runs(
        Settings(storage_backend="real"), AdminJobStore(), SimpleNamespace(emit=AsyncMock()),
        gate=gate, lost=lost, system_settings=None, freshness=freshness,
    )  # fmt: skip
    with pytest.raises(OpsNotWired):  # still no engine
        await runs.start(principal("owner"), kind="pg_dump", write_ahead=AsyncMock())
    rows = runs._rows
    assert rows is not None and isinstance(lost_runs, LostRuns) and engines == ["admin"]
    assert (runs._gate, rows._freshness, rows._lost) == (gate, freshness, lost)  # the app's gate


def test_create_app_hands_its_one_admission_gate_to_the_run_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[dict[str, Any]] = []
    build, settings_store = wiring.build_backup_runs, object()

    def spy(*args: Any, **kwargs: Any) -> Any:
        seen.append(kwargs)
        return build(*args, **kwargs)

    monkeypatch.setattr(app_module, "build_backup_runs", spy)
    monkeypatch.setattr(app_module, "build_system_settings", lambda resolved: settings_store)
    monkeypatch.setattr(wiring, "BACKUPS_CATALOGUED", True)  # so BK-5's freshness exists
    app = create_app()
    assert ("POST", "/admin/backups") in served_operations(app)
    gate = app.state.backups_gate  # BK-9, BK-10, BK-12 and BK-13 take this one too
    assert isinstance(gate, BackupJobGate) and [kwargs["gate"] for kwargs in seen] == [gate]
    lost = app.state.metrics_facade.get("cv_admin_jobs_lost_on_restart_total").child()
    assert (seen[0]["lost"], app.state.backup_lost_runs) == (lost, None)  # the fake backend's
    freshness = app.state.backup_freshness
    assert (seen[0]["freshness"], seen[0]["system_settings"]) == (freshness, settings_store)


def test_create_app_builds_exactly_one_backups_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    """Whichever of BK-8c and BK-10b lands second takes this one gate rather than its own."""
    built: list[BackupJobGate] = []
    init = BackupJobGate.__init__

    def counted(gate: BackupJobGate, *args: Any, **kwargs: Any) -> None:
        built.append(gate)
        init(gate, *args, **kwargs)

    monkeypatch.setattr(BackupJobGate, "__init__", counted)
    app = create_app()
    assert built == [app.state.backups_gate]
