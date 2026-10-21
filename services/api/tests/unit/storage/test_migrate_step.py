"""Unit tests for `candleviewer.storage.migrate` (#3897), the deploy's explicit schema step.

Fakes stand in for Alembic, the migration lock and QuestDB (no real connection is opened): the order
of the steps, the status and log line of each typed error, a second run, the DDL directory handed
on, the lock and the bounds of the Postgres phase, and, last, that nothing the API boots runs the
runner (20-architecture.md section 6.2). QuestDB's own end is the integration test.
"""

from __future__ import annotations

import ast
import asyncio
import dataclasses
import importlib.util
import io
import json
import os
import re
import shutil
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import cast

import asyncpg
import pytest
from alembic import command
from asyncpg.exceptions import ConnectionDoesNotExistError, ConnectionFailureError
from sqlalchemy import create_engine
from structlog.testing import capture_logs

import candleviewer
from candleviewer.migrations import boot
from candleviewer.observability.logging import reset_logging
from candleviewer.settings import Settings
from candleviewer.storage import migrate
from candleviewer.storage.errors import (
    StorageError,
    StorageQueryFailed,
    StorageSchemaDrift,
    StorageTierUnavailable,
    StorageWalNotApplied,
)
from candleviewer.storage.migrate import MigrateExit, Steps, alembic_config, main, run
from candleviewer.storage.questdb import runner
from candleviewer.storage.questdb.runner import QuestDbExecutor
from candleviewer.storage.service import StorageService
from tests.unit.storage.test_service_real_backend import _CTX, _Tiers

_LEAKY = "leaky-detail-must-not-surface"  # what a driver error may carry: never in a log line
_FILES = ("0001_core_tables.sql", "0002_footprint_cells.sql")
_EXECUTOR = cast("QuestDbExecutor", object())  # the fake steps only pass it along
_DRIFT = StorageSchemaDrift("questdb table 'trades' column drift: missing=['notional'] extra=[]")
_WAL = StorageWalNotApplied("questdb WAL apply stalled", reason="suspended", table="_cv_migrations")
_REFUSED = StorageQueryFailed("42000")
_HELD = boot.MigrationLockTimeout("the lock was not free in time")
_STEPS = ["lock", "alembic", "connect", "run_migrations", "drift_guard"]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in [n for n in os.environ if n.upper().startswith("CV_")]:
        monkeypatch.delenv(name)


@pytest.fixture
def settings() -> Settings:
    return Settings()


@pytest.fixture
def ddl_dir(tmp_path: Path) -> Path:
    """A directory with one DDL file in it: the step refuses a directory with none."""
    directory = tmp_path / "ddl"
    directory.mkdir()
    (directory / _FILES[0]).write_text("-- ddl\n", encoding="utf-8")
    return directory


class _Script:
    """The five steps as fakes: they record their order, and the named ones raise their error."""

    def __init__(
        self, raises: dict[str, Exception] | None = None, applied: tuple[str, ...] = _FILES
    ):
        self.calls: list[str] = []
        self.ddl_dirs: list[Path] = []
        self._raises, self._applied = raises or {}, list(applied)

    def _enter(self, name: str) -> None:
        self.calls.append(name)
        if name in self._raises:
            raise self._raises[name]

    def steps(self) -> Steps:
        @asynccontextmanager
        async def lock(_settings: Settings) -> AsyncIterator[None]:
            self._enter("lock")
            try:
                yield
            finally:
                self.calls.append("unlock")

        @asynccontextmanager
        async def connect(_settings: Settings) -> AsyncIterator[QuestDbExecutor]:
            self._enter("connect")
            try:
                yield _EXECUTOR
            finally:
                self.calls.append("close")

        async def apply(_executor: QuestDbExecutor, ddl_dir: Path) -> list[str]:
            self._enter("run_migrations")
            self.ddl_dirs.append(ddl_dir)
            return self._applied

        async def guard(_executor: QuestDbExecutor, _ddl_dir: Path) -> None:
            self._enter("drift_guard")

        return Steps(lambda _settings: self._enter("alembic"), connect, apply, guard, lock)


async def test_the_steps_run_under_the_lock_alembic_then_the_ddl_runner_then_the_drift_guard(
    settings: Settings, ddl_dir: Path
) -> None:
    script = _Script()
    assert await run(settings, ddl_dir, script.steps()) is MigrateExit.OK
    assert script.calls == [*_STEPS, "close", "unlock"]  # the connection closes, then the lock
    assert script.ddl_dirs == [ddl_dir]


_FAILURES = [  # (failing step, its error, its status, the number the runbook gives it, its fields)
    ("lock", _HELD, MigrateExit.POSTGRES_FAILED, 4, {}),
    ("alembic", RuntimeError(_LEAKY), MigrateExit.POSTGRES_FAILED, 4, {}),
    ("connect", StorageTierUnavailable("down"), MigrateExit.QUESTDB_UNAVAILABLE, 6, {}),
    ("run_migrations", StorageTierUnavailable("dropped"), MigrateExit.QUESTDB_UNAVAILABLE, 6, {}),
    ("run_migrations", _REFUSED, MigrateExit.DDL_REFUSED, 7, {"sqlstate": "42000"}),
    ("run_migrations", _WAL, MigrateExit.WAL_NOT_APPLIED, 8, {"reason": "suspended"}),
    ("drift_guard", _DRIFT, MigrateExit.SCHEMA_DRIFT, 9, {"detail": str(_DRIFT)}),
    ("drift_guard", KeyError(_LEAKY), MigrateExit.UNEXPECTED, 1, {}),
]


@pytest.mark.parametrize(("failing", "error", "status", "number", "fields"), _FAILURES)
async def test_a_failure_stops_the_later_steps_and_has_its_own_status_and_one_log_line(
    failing: str,
    error: Exception,
    status: MigrateExit,
    number: int,
    fields: dict[str, object],
    settings: Settings,
    ddl_dir: Path,
) -> None:
    script = _Script({failing: error})
    with capture_logs() as logs:
        assert await run(settings, ddl_dir, script.steps()) is status
    ran = _STEPS[: _STEPS.index(failing) + 1]  # what ran; the connection closes, then the lock goes
    closed = ["close"] if failing in _STEPS[3:] else []
    assert script.calls == [*ran, *closed, *([] if failing == "lock" else ["unlock"])]
    [line] = logs
    snake = re.sub(r"(?<=[a-z])(?=[A-Z])", "_", type(error).__name__).lower()
    assert (line["event"], line["log_level"]) == ("storage_migrate_failed", "error")
    assert (line["error"], line["exit_code"], int(status)) == (snake, number, number)
    assert fields.items() <= line.items()
    if isinstance(error, StorageError):
        assert line["code"] == error.code
    assert _LEAKY not in repr(logs)  # the class is logged, never the message


@pytest.mark.parametrize("missing", [True, False], ids=["missing", "empty"])
async def test_a_ddl_dir_with_no_sql_file_refuses_before_any_step(
    missing: bool, settings: Settings, tmp_path: Path
) -> None:
    """Else a missing directory globs to nothing, and an image without the DDL would exit 0."""
    script = _Script()
    with capture_logs() as logs:
        status = await run(settings, tmp_path / "absent" if missing else tmp_path, script.steps())
    assert (status, int(status)) == (MigrateExit.DDL_NOT_FOUND, 5)
    assert script.calls == []
    assert [line["error"] for line in logs] == ["storage_ddl_not_found"]


async def test_a_second_run_with_nothing_to_apply_exits_zero(
    settings: Settings, ddl_dir: Path
) -> None:
    first, second = _Script(applied=_FILES), _Script(applied=())
    with capture_logs() as logs:
        assert await run(settings, ddl_dir, first.steps()) is MigrateExit.OK
        assert await run(settings, ddl_dir, second.steps()) is MigrateExit.OK
    done = [e["questdb_files_applied"] for e in logs if e["event"] == "storage_migrate_done"]
    assert done == [2, 0]
    assert second.calls == first.calls  # the same steps ran: the runner found nothing left


@pytest.mark.parametrize(
    ("fails_at", "driver_error", "typed", "sqlstate"),
    [
        ("statement", asyncpg.exceptions.DuplicateColumnError(_LEAKY), StorageQueryFailed, "42701"),
        ("statement", ConnectionDoesNotExistError(_LEAKY), StorageTierUnavailable, None),  # 08003
        ("statement", ConnectionFailureError(_LEAKY), StorageTierUnavailable, None),  # 08006
        ("statement", asyncpg.InterfaceError(_LEAKY), StorageTierUnavailable, None),  # closed
        ("statement", TimeoutError(_LEAKY), StorageTierUnavailable, None),
        ("connect", OSError(_LEAKY), StorageTierUnavailable, None),
        ("connect", asyncpg.InterfaceError(_LEAKY), StorageTierUnavailable, None),
    ],
)
async def test_a_driver_failure_is_typed_and_carries_nothing_of_the_driver(
    monkeypatch: pytest.MonkeyPatch,
    settings: Settings,
    fails_at: str,
    driver_error: BaseException,
    typed: type[StorageError],
    sqlstate: str | None,
) -> None:
    class Conn:
        async def execute(self, sql: str, *args: object) -> None:
            raise driver_error

    async def connect(**_kwargs: object) -> Conn:
        if fails_at == "connect":
            raise driver_error
        return Conn()

    monkeypatch.setattr(asyncpg, "connect", connect)
    with pytest.raises(typed) as caught:
        async with migrate.connect_questdb(settings) as executor:
            await executor.execute("CREATE TABLE t (a INT)")
    assert _LEAKY not in str(caught.value)
    assert caught.value.__cause__ is None and caught.value.__suppress_context__  # `from None`
    assert getattr(caught.value, "sqlstate", None) == sqlstate


class _LockConn:
    """The Postgres session of the migration lock: records what it ran; `held` never answers."""

    def __init__(self, held: bool = False) -> None:
        self.ran: list[tuple[str, tuple[object, ...]]] = []
        self.closed = False
        self._held = held

    async def execute(self, sql: str, *args: object) -> None:
        self.ran.append((sql, args))
        if self._held:
            await asyncio.Event().wait()  # a lock another run holds: only the timeout ends this

    async def close(self, **_kwargs: object) -> None:
        self.closed = True


def _session(monkeypatch: pytest.MonkeyPatch, conn: _LockConn) -> list[str]:
    """Hand `conn` to asyncpg; the DSNs it was asked to connect with come back."""
    dsns: list[str] = []

    async def connect(dsn: str, **_kwargs: object) -> _LockConn:
        dsns.append(dsn)
        return conn

    monkeypatch.setattr(asyncpg, "connect", connect)
    return dsns


async def test_the_lock_is_the_boot_runners_advisory_lock_on_a_connection_of_its_own(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    conn = _LockConn()
    dsns = _session(monkeypatch, conn)
    async with migrate.hold_migration_lock(settings):
        assert conn.ran == [("SELECT pg_advisory_lock(hashtext($1))", (migrate.LOCK_KEY,))]
        assert not conn.closed
    assert conn.closed  # the end of the session releases a session lock
    assert migrate.LOCK_KEY == boot._LOCK_KEY_NAME  # one key: the two runners would serialise
    assert [dsn.startswith("postgresql://") for dsn in dsns] == [True]  # asyncpg's form, no +driver


async def test_a_run_that_cannot_get_the_lock_in_time_exits_4_before_anything_runs(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, ddl_dir: Path
) -> None:
    conn = _LockConn(held=True)
    _session(monkeypatch, conn)
    script = _Script()
    steps = dataclasses.replace(script.steps(), lock=migrate.hold_migration_lock)
    with capture_logs() as logs:
        quick = settings.model_copy(update={"migration_lock_timeout_s": 0.05})
        assert await run(quick, ddl_dir, steps) is MigrateExit.POSTGRES_FAILED
    assert script.calls == [] and conn.closed
    assert [(line["step"], line["error"]) for line in logs] == [
        ("pg_lock", "migration_lock_timeout")
    ]


def test_alembic_connects_with_a_connect_timeout_and_a_lock_wait_limit_unless_the_dsn_sets_them(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    plain = "postgresql+psycopg://u@h:1/d"
    own = f"{plain}?connect_timeout=3&options=-c%20lock_timeout%3D5s"
    seen: list[dict[str, object]] = []

    def upgrade(*_args: object, **_kwargs: object) -> None:
        for url in (plain, own):  # what env.py's engine hands psycopg: the hook sees the same dict
            engine = create_engine(url)
            params = engine.dialect.create_connect_args(engine.url)[1]
            for hook in engine.dialect.dispatch.do_connect:
                hook(engine.dialect, None, (), params)
            seen.append(dict(params))

    monkeypatch.setattr(command, "upgrade", upgrade)
    migrate.alembic_upgrade(settings)
    assert (seen[0]["connect_timeout"], seen[0]["options"]) == (10, "-c lock_timeout=300000ms")
    assert (str(seen[1]["connect_timeout"]), seen[1]["options"]) == ("3", "-c lock_timeout=5s")
    after = create_engine(plain).dialect.dispatch.do_connect
    assert [hook for hook in after if hook.__name__ == "bounded"] == []  # no hook outlives the call


def test_the_failure_is_one_json_line_through_the_real_log_chain(
    capsys: pytest.CaptureFixture[str], ddl_dir: Path
) -> None:
    script = _Script({"drift_guard": _DRIFT})
    assert main(["--ddl-dir", str(ddl_dir)], steps=script.steps()) == MigrateExit.SCHEMA_DRIFT
    reset_logging()  # stops the listener, which writes out what is still queued
    lines = [line for line in capsys.readouterr().out.splitlines() if line.startswith("{")]
    [failed] = [e for e in map(json.loads, lines) if e["event"] == "storage_migrate_failed"]
    # The redaction replaces a class name of 18 to 36 letters as an API key: this survives it.
    assert failed["level"] == "error" and failed["error"] == "storage_schema_drift"
    assert failed["code"] == "STORAGE_SCHEMA_DRIFT" and failed["detail"] == str(_DRIFT)
    assert failed["exit_code"] == MigrateExit.SCHEMA_DRIFT


def test_the_command_hands_the_runner_the_ddl_dir_it_is_given_or_the_images(
    monkeypatch: pytest.MonkeyPatch, ddl_dir: Path, tmp_path: Path
) -> None:
    shipped = tmp_path / "shipped"
    shutil.copytree(ddl_dir, shipped)
    given, default = _Script(), _Script()
    assert main(["--ddl-dir", str(ddl_dir)], steps=given.steps()) == MigrateExit.OK
    monkeypatch.setattr(migrate, "QUESTDB_DDL_DIR", shipped)  # the image's own path is not here
    assert main([], steps=default.steps()) == MigrateExit.OK
    assert (given.ddl_dirs, default.ddl_dirs) == ([ddl_dir], [shipped])


@pytest.mark.filterwarnings("ignore::SyntaxWarning")  # 0001, applied and never edited (C-5.4)
def test_env_py_renders_every_revision_from_a_config_without_an_ini_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The image has no `alembic.ini`. Offline (`--sql`): `env.py` opens no connection."""
    monkeypatch.setenv("CV_PG_DSN", "postgresql+asyncpg://cv:cv@localhost:5432/candleviewer")
    config, buffer = alembic_config(), io.StringIO()
    config.output_buffer = buffer
    assert config.config_file_name is None
    command.upgrade(config, "head", sql=True)
    assert "CREATE TABLE" in buffer.getvalue()


# --- the DDL is never applied at API boot (20-architecture.md section 6.2) ------------------------

PACKAGE = Path(candleviewer.__file__).resolve().parent
_QUESTDB = "candleviewer.storage.questdb"
_RUNNER = f"{_QUESTDB}.runner"
_ENTRY_POINTS = frozenset({"run_migrations", "assert_no_schema_drift", "applied_migrations"})
#: The step, the runner itself, the package `__init__`, which re-exports the entry points, and
#: Alembic's `env.py`, which calls Alembic's own `context.run_migrations()`.
_MAY_NAME_THEM = frozenset(
    {
        "storage/migrate.py",
        "storage/questdb/runner.py",
        "storage/questdb/__init__.py",
        "migrations/env.py",
    }
)


def _runner_uses(source: str, package: str = "") -> list[int]:
    """The lines that name a runner entry point (imported, aliased or reached through a module
    attribute) or import the runner's module, relative imports resolved against `package`."""
    lines = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Name | ast.Attribute):
            if (node.id if isinstance(node, ast.Name) else node.attr) in _ENTRY_POINTS:
                lines.add(node.lineno)
        elif isinstance(node, ast.Import):
            if any(alias.name == _RUNNER for alias in node.names):
                lines.add(node.lineno)
        elif isinstance(node, ast.ImportFrom):
            names = {alias.name for alias in node.names}
            module = importlib.util.resolve_name("." * node.level + (node.module or ""), package)
            if module == _RUNNER or (module == _QUESTDB and names & {"runner", "*"}):
                lines.add(node.lineno)
            if names & _ENTRY_POINTS:
                lines.add(node.lineno)
    return sorted(lines)


def test_nothing_but_the_migrate_step_names_the_ddl_runner() -> None:
    """A static pin: a boot that ran the runner would have to name it, in some import style."""
    for source, package, expected in (  # the check finds each way to do it
        ("from candleviewer.storage.questdb.runner import run_migrations", "", [1]),
        ("from candleviewer.storage.questdb import assert_no_schema_drift", "", [1]),
        ("from candleviewer.storage.questdb import runner", "", [1]),
        ("import candleviewer.storage.questdb.runner as questdb_runner", "", [1]),
        ("from candleviewer.storage import questdb\nquestdb.run_migrations(x)", "", [2]),
        ("import candleviewer.storage.questdb as q\nq.assert_no_schema_drift(x)", "", [2]),
        ("from .runner import applied_migrations", _QUESTDB, [1]),
        ("from . import runner", _QUESTDB, [1]),
    ):
        assert _runner_uses(source, package) == expected, source
    offenders = []
    for path in sorted(PACKAGE.rglob("*.py")):
        relative = path.relative_to(PACKAGE)
        if relative.as_posix() in _MAY_NAME_THEM or "versions" in relative.parts:
            continue  # applied revisions are never edited, and hold no such name
        package = ".".join(["candleviewer", *relative.parts[:-1]])
        uses = _runner_uses(path.read_text(encoding="utf-8"), package)
        offenders += [f"{relative.as_posix()}:{n}" for n in uses]
    assert offenders == [], f"only the migrate step may run the QuestDB DDL runner: {offenders}"


async def test_the_real_storage_start_never_runs_the_ddl(monkeypatch: pytest.MonkeyPatch) -> None:
    """Whoever imported the runner, each entry point's first call is one of these two lookups."""

    def refuse(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("the QuestDB DDL runner ran during the API's start")

    monkeypatch.setattr(runner, "applied_migrations", refuse)  # run_migrations' first call
    monkeypatch.setattr(runner, "parse_ddl_dir", refuse)  # assert_no_schema_drift's first call
    tiers = _Tiers()
    service = StorageService(backend="real", real_tiers=tiers.build)
    await service.start(_CTX)
    await service.stop(grace_s=1.0)
    assert tiers.calls[:3] == ["probe:postgres", "probe:questdb", "probe:cold"]
