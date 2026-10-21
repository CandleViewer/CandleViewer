"""The deploy's explicit schema step: Postgres, then the QuestDB DDL, then its drift guard (#3897).

`python -m candleviewer.storage.migrate` runs three steps and stops at the first failure:
`alembic upgrade head` (Alembic's Python API, on `CV_PG_DSN`); the E07-T03 runner's `run_migrations`
over the DDL the API image ships at `QUESTDB_DDL_DIR` (on `CV_QUESTDB_PG`); then
`assert_no_schema_drift`. All three run under one Postgres advisory lock, so two runs never overlap,
and Alembic's connection is bounded (a connect timeout, a lock wait limit; a long statement is not
cut). Everything applied, or nothing left to apply, is exit 0. A failure is one
`storage_migrate_failed` log line (the step, the error's class and stable code, never a DSN, a
password or a driver message: C-12.6) and its own `MigrateExit` status, so a deploy stops before it
starts the API on a schema it cannot write. A directory with no `.sql` file fails too: the runner
would find nothing to apply and report success.

Never run at API boot or by a request handler (20-architecture.md section 6.2); an automated apply
waits for #3093. Runbook: `docs/ops/runbooks/storage-migrate.md`.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import re
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path
from typing import Any, Final

import asyncpg
import structlog
from alembic import command
from alembic.config import Config
from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.engine.interfaces import Dialect
from sqlalchemy.pool import ConnectionPoolEntry

import candleviewer
from candleviewer.migrations.boot import MigrationLockTimeout
from candleviewer.migrations.dsn import to_asyncpg_dsn
from candleviewer.observability.logging import configure_logging
from candleviewer.settings import QUESTDB_PG_DEFAULT_PORT, Settings
from candleviewer.storage.errors import (
    StorageDdlNotFound,
    StorageError,
    StorageQueryFailed,
    StorageSchemaDrift,
    StorageTierUnavailable,
    StorageWalNotApplied,
)
from candleviewer.storage.questdb.runner import (
    QuestDbExecutor,
    assert_no_schema_drift,
    run_migrations,
)

#: Where `infra/images/Dockerfile.api` copies `backend/db/questdb` (test_migrate_image_content).
QUESTDB_DDL_DIR: Final = Path("/app/backend/db/questdb")
CONNECT_TIMEOUT_S: Final = 10.0
STATEMENT_TIMEOUT_S: Final = 60.0
CLOSE_TIMEOUT_S: Final = 5.0
#: The advisory lock key `migrations/boot.py` takes: the two runners would serialise on it.
LOCK_KEY: Final = "cv_migrations"


class MigrateExit(IntEnum):
    """The exit status (runbook: `storage-migrate.md`). 2 is argparse's; a refused setting exits 1
    with its traceback, as at an API start."""

    OK = 0
    UNEXPECTED = 1  # any other error: its class name only
    POSTGRES_FAILED = 4  # the migration lock was not got, or `alembic upgrade head` failed
    DDL_NOT_FOUND = 5  # `StorageDdlNotFound`: no `.sql` file to apply
    QUESTDB_UNAVAILABLE = 6  # `StorageTierUnavailable`
    DDL_REFUSED = 7  # `StorageQueryFailed`: QuestDB refused a statement
    WAL_NOT_APPLIED = 8  # `StorageWalNotApplied`
    SCHEMA_DRIFT = 9  # `StorageSchemaDrift`


#: The log redaction replaces a run of 18 to 36 letters as an API key (`StorageSchemaDrift`), so the
#: class is logged in snake_case.
_WORDS: Final = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")

_STATUS: Final[tuple[tuple[type[Exception], MigrateExit], ...]] = (
    (StorageDdlNotFound, MigrateExit.DDL_NOT_FOUND),
    (StorageTierUnavailable, MigrateExit.QUESTDB_UNAVAILABLE),
    (StorageQueryFailed, MigrateExit.DDL_REFUSED),
    (StorageWalNotApplied, MigrateExit.WAL_NOT_APPLIED),
    (StorageSchemaDrift, MigrateExit.SCHEMA_DRIFT),
)


def _log() -> Any:
    """Resolved per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


class _PgWireExecutor:
    """`QuestDbExecutor` over one asyncpg connection: a refused statement is `StorageQueryFailed`
    (its SQLSTATE only); a connection that drops or stops answering (SQLSTATE class 08, a closed
    connection, a timeout, an `OSError`) is `StorageTierUnavailable`. Both `from None` (C-12.6).
    """

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    async def execute(self, sql: str, *args: object) -> None:
        await self._call(self._conn.execute, sql, *args)

    async def fetch(self, sql: str, *args: object) -> list[dict[str, object]]:
        return [dict(row) for row in await self._call(self._conn.fetch, sql, *args)]

    @staticmethod
    async def _call(method: Callable[..., Awaitable[Any]], sql: str, *args: object) -> Any:
        try:
            async with asyncio.timeout(STATEMENT_TIMEOUT_S):
                return await method(sql, *args)
        except asyncpg.PostgresError as exc:
            if (exc.sqlstate or "").startswith("08"):  # SQLSTATE class 08: the connection dropped
                raise StorageTierUnavailable("questdb stopped answering") from None
            raise StorageQueryFailed(exc.sqlstate) from None
        except (OSError, TimeoutError, asyncpg.InterfaceError):  # InterfaceError: already closed
            raise StorageTierUnavailable("questdb stopped answering") from None


@asynccontextmanager
async def connect_questdb(settings: Settings) -> AsyncIterator[QuestDbExecutor]:
    """One PG-wire connection: the runner needs `execute`, which the API's `LazyPgWire` lacks."""
    host, _, port = settings.questdb_pg.partition(":")
    try:
        async with asyncio.timeout(CONNECT_TIMEOUT_S):
            conn = await asyncpg.connect(
                host=host,
                port=int(port or QUESTDB_PG_DEFAULT_PORT),
                user=settings.questdb_pg_user,
                password=settings.questdb_pg_password.get_secret_value(),
                database="qdb",
            )
    except (asyncpg.PostgresError, asyncpg.InterfaceError, OSError, TimeoutError):  # names the host
        raise StorageTierUnavailable("questdb did not accept the connection") from None
    try:
        yield _PgWireExecutor(conn)
    finally:
        # A close that fails aborts the connection (asyncpg) and never hides the step's result.
        with contextlib.suppress(Exception):
            await conn.close(timeout=CLOSE_TIMEOUT_S)


def alembic_config() -> Config:
    """The packaged scripts, with no `alembic.ini`: the image has none, and without one `env.py`
    leaves the logging `configure_logging` set."""
    config = Config()
    migrations = Path(candleviewer.__file__).resolve().parent / "migrations"
    config.set_main_option("script_location", str(migrations))
    return config


def alembic_upgrade(settings: Settings) -> None:
    """`alembic upgrade head`; `env.py` takes the DSN from `CV_PG_DSN`, else `Settings.pg_dsn`.

    Alembic's connection is bounded (a DSN that sets either value wins): a dead host ends in an
    error, and so does a lock another session holds. A long-running statement is not cut.
    """
    lock_wait = f"-c lock_timeout={round(settings.migration_lock_timeout_s * 1000)}ms"

    def bounded(
        _dialect: Dialect,
        _record: ConnectionPoolEntry | None,
        _args: tuple[Any, ...],
        params: dict[str, Any],
    ) -> None:
        params.setdefault("connect_timeout", round(CONNECT_TIMEOUT_S))
        params.setdefault("options", lock_wait)

    event.listen(Engine, "do_connect", bounded)  # `env.py` builds its own engine: hook its connect
    try:
        command.upgrade(alembic_config(), "head")
    finally:
        event.remove(Engine, "do_connect", bounded)


@asynccontextmanager
async def hold_migration_lock(settings: Settings) -> AsyncIterator[None]:
    """One run at a time: `pg_advisory_lock` on a connection of its own, for the whole step.

    Closing that connection releases the lock, whatever happened. A run that cannot get it within
    `migration_lock_timeout_s` is a `MigrationLockTimeout`.
    """
    wait_s = settings.migration_lock_timeout_s
    conn = await asyncpg.connect(
        to_asyncpg_dsn(settings.pg_dsn.get_secret_value()), timeout=CONNECT_TIMEOUT_S
    )
    try:
        try:
            async with asyncio.timeout(wait_s):
                await conn.execute("SELECT pg_advisory_lock(hashtext($1))", LOCK_KEY)
        except TimeoutError:
            raise MigrationLockTimeout(f"'{LOCK_KEY}' lock not free in {wait_s:g}s") from None
        yield
    finally:
        with contextlib.suppress(Exception):
            await conn.close(timeout=CLOSE_TIMEOUT_S)


@dataclass(frozen=True, slots=True)
class Steps:
    """The five collaborators, replaceable so a test runs the order without a database."""

    upgrade: Callable[[Settings], None] = alembic_upgrade
    connect: Callable[[Settings], AbstractAsyncContextManager[QuestDbExecutor]] = connect_questdb
    apply: Callable[[QuestDbExecutor, Path], Awaitable[list[str]]] = run_migrations
    guard: Callable[[QuestDbExecutor, Path], Awaitable[None]] = assert_no_schema_drift
    lock: Callable[[Settings], AbstractAsyncContextManager[None]] = hold_migration_lock


def _has_sql_files(ddl_dir: Path) -> bool:
    return any(ddl_dir.glob("*.sql"))  # a missing directory globs to nothing, as an empty one


def _status(step: str, exc: Exception) -> MigrateExit:
    if step in ("pg_lock", "alembic"):
        return MigrateExit.POSTGRES_FAILED
    return next((s for kind, s in _STATUS if isinstance(exc, kind)), MigrateExit.UNEXPECTED)


def _fields(exc: Exception) -> dict[str, object]:
    """What a failure's line carries besides its class: the stable code and the typed error's own
    fields, none of them a credential."""
    fields: dict[str, object] = {}
    if isinstance(exc, StorageError):
        fields["code"] = exc.code
    if isinstance(exc, StorageWalNotApplied):
        fields |= {"reason": exc.reason, "table": exc.table, "waited_s": round(exc.waited_s, 1)}
    elif isinstance(exc, StorageQueryFailed):
        fields["sqlstate"] = exc.sqlstate
    elif isinstance(exc, StorageSchemaDrift):
        fields["detail"] = str(exc)  # a table and its column names
    return fields


async def run(settings: Settings, ddl_dir: Path, steps: Steps | None = None) -> MigrateExit:
    """The three steps in order, under the lock. The status is `OK`, or the first failure's once
    it is logged."""
    steps = steps or Steps()
    step, applied = "ddl_files", 0
    try:
        if not _has_sql_files(ddl_dir):
            raise StorageDdlNotFound("the QuestDB DDL directory holds no .sql file")
        step = "pg_lock"
        async with steps.lock(settings):
            step = "alembic"
            await asyncio.to_thread(steps.upgrade, settings)  # blocking: off the event loop
            step = "questdb_ddl"
            async with steps.connect(settings) as executor:
                applied = len(await steps.apply(executor, ddl_dir))
                step = "drift_guard"
                await steps.guard(executor, ddl_dir)
    except Exception as exc:  # classified by its step and class; only the class is logged
        status = _status(step, exc)
        fields = {
            "step": step,
            "error": _WORDS.sub("_", type(exc).__name__).lower(),
            "exit_code": int(status),
        }
        _log().error("storage_migrate_failed", ddl_dir=str(ddl_dir), **fields, **_fields(exc))
        return status
    _log().info("storage_migrate_done", questdb_files_applied=applied)
    return MigrateExit.OK


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m candleviewer.storage.migrate",
        description="Apply the Postgres migrations and the QuestDB DDL, then check QuestDB for "
        "schema drift. A deploy step: the API never runs it at boot.",
    )
    parser.add_argument(
        "--ddl-dir", type=Path, default=QUESTDB_DDL_DIR, help="default: the image's"
    )
    return parser


def main(argv: Sequence[str] | None = None, *, steps: Steps | None = None) -> int:
    """`python -m candleviewer.storage.migrate`; returns a `MigrateExit` status."""
    args = _parser().parse_args(argv)
    settings = Settings()  # a refused setting raises here: exit 1 with its traceback (main.py)
    configure_logging(
        env=settings.environment.value, level=settings.log_level, fmt=settings.log_format
    )
    return int(asyncio.run(run(settings, args.ddl_dir, steps)))


if __name__ == "__main__":
    raise SystemExit(main())
