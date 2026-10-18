"""`SqlAlchemyBackups` with a fake unit of work (E42-T05 #966 BK-3): the statements it builds and
the errors it raises, never with the driver's text. Postgres: `test_backups_pg.py`."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import asdict, fields, replace
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, get_args
from uuid import UUID

import pytest
import sqlalchemy as sa
from sqlalchemy import exc as sa_exc
from structlog.testing import capture_logs

from candleviewer.db.models import BACKUP_KINDS, BACKUP_STATUSES, backups
from candleviewer.storage.errors import (
    BackupCheckViolation,
    BackupWriteOnceViolation,
    StorageError,
    StorageQueryFailed,
    StorageTierUnavailable,
)
from candleviewer.storage.repositories import backups as port
from candleviewer.storage.repositories import backups_sqlalchemy as repo

NOW = datetime(2026, 10, 18, 9, 0, tzinfo=UTC)
NAIVE = datetime(2026, 10, 18, 9, 0)  # no tzinfo: what the store refuses
ID, USER = UUID(int=7), UUID(int=5)
_DSN = "postgresql://cv:" + "hunter2" + "@db/cv"  # by concatenation: no scanner sees a credential
_ALIAS = "age:" + "offsite-2026"  # a CHECK's DETAIL carries the whole row, this alias included
_ROW = port.BackupRow(
    id=ID, kind="pg_dump", status="ok", target_path="/b/7", size_bytes=3, checksum_sha256="a" * 64,
    encrypted=True, covers_to=None, verified_at=None, error_message=None, triggered_by="manual",
    started_at=NOW, finished_at=NOW, retention_until=None, deleted_at=None,
)  # fmt: skip
_NEW = port.NewBackup(ID, "pg_dump", "/b/7", True, "manual", USER, NOW, encryption_ref=_ALIAS)
_Call = Callable[[repo.SqlAlchemyBackups], Awaitable[object]]
_ONE = [asdict(_ROW)]
_WRITES: dict[str, _Call] = {
    "insert_running": lambda s: s.insert_running(_NEW),
    "record_run_finished": lambda s: s.record_run_finished(ID, port.RunFinished(NOW, None)),
    "record_verify_outcome": lambda s: s.record_verify_outcome(
        ID, method="checksum", at=NOW, error=None
    ),
    "mark_deleted": lambda s: s.mark_deleted(ID, by=USER, at=NOW),
}
_CALLS: dict[str, tuple[_Call, list[dict[str, Any]]]] = {  # each read, and what answers it
    "page": (lambda s: s.page("pg_dump", "ok", (NOW, ID), 5), _ONE),
    "get": (lambda s: s.get(ID), _ONE),
    "last_success_by_kind": (
        lambda s: s.last_success_by_kind(), [{"kind": "pg_dump", "finished_at": NOW}]
    ),
    "usable_count": (lambda s: s.usable_count("pg_dump"), [{"n": 2}]),
}  # fmt: skip


class _Rel:
    """`events`: the unit of work in order, its cap first; `rows` answer every statement."""

    def __init__(self, rows: list[dict[str, Any]], error: Exception | None = None) -> None:
        self.rows, self.error = rows, error
        self.events: list[Any] = []

    @asynccontextmanager
    async def unit_of_work(self) -> AsyncIterator[Any]:
        async def execute(stmt: Any, params: Any = None) -> Any:
            capped = stmt is repo._TIMEOUT
            self.events.append(("cap", params["timeout"]) if capped else stmt)
            if self.error is not None and not capped:
                raise self.error
            return SimpleNamespace(mappings=lambda: self.rows)

        async def commit() -> None:
            self.events.append("commit")

        yield SimpleNamespace(session=SimpleNamespace(execute=execute), commit=commit)


class _Driver(Exception):
    """`DBAPIError.orig`: the row in text and `detail`; the CHECK named on the cause or `diag`."""

    def __init__(self, sqlstate: str | None, constraint: str | None, pg3: bool) -> None:
        self.detail = f"Failing row contains ({ID}, pg_dump, /b/7, {_ALIAS})"
        super().__init__(f"{_DSN} violates check constraint DETAIL: {self.detail}")
        self.sqlstate, self.diag = sqlstate, SimpleNamespace(message_detail=self.detail)
        self.__cause__ = Exception(str(self))
        vars(self.diag if pg3 else self.__cause__)["constraint_name"] = constraint


def _dbapi(kind: Any, state: str | None, name: str | None = None, pg3: bool = False) -> Any:
    return kind("SELECT backups", {"encryption_ref": _ALIAS}, _Driver(state, name, pg3))


async def _executed(
    call: _Call, rows: list[dict[str, Any]] = _ONE, *, write: bool = False
) -> tuple[str, dict[str, Any]]:
    """The statement `call` ran, as SQLAlchemy renders it for any dialect, and its bound values;
    the unit of work's 1 s cap ran first, and a write committed."""
    rel = _Rel(rows)
    await call(repo.SqlAlchemyBackups(rel))  # type: ignore[arg-type]  # structural fake
    assert rel.events[0] == ("cap", "1s") and rel.events[2:] == ["commit"] * write
    compiled = rel.events[1].compile()
    return " ".join(str(compiled).split()), compiled.params


async def _raised(op: str, error: Exception, sqlstate: str | None) -> StorageError:
    """What `op` raised: logged with the call, type and SQLSTATE only, no cause, no context."""
    store = repo.SqlAlchemyBackups(_Rel([], error))  # type: ignore[arg-type]  # structural fake
    with capture_logs() as logs, pytest.raises(StorageError) as raised:
        await _CALLS[op][0](store)
    leaked = str(raised.value) + repr(raised.value) + repr(logs)
    assert "hunter2" not in leaked and _ALIAS not in leaked and "DETAIL" not in leaked
    assert raised.value.__cause__ is None and raised.value.__context__ is None
    outage = isinstance(raised.value, StorageTierUnavailable)
    fields_ = {"op": op, "outage": outage, "error": type(error).__name__, "sqlstate": sqlstate}
    assert logs == [{"event": "backups_store_failed", "log_level": "error", **fields_}]
    return raised.value


async def test_columns_never_include_encryption_ref() -> None:
    assert [c.name for c in repo.COLUMNS] == [f.name for f in fields(port.BackupRow)]
    for call, rows in _CALLS.values():
        sql, params = await _executed(call, rows)
        assert "encryption_ref" not in sql and _ALIAS not in str(params)


async def test_page_orders_by_started_at_then_id_descending() -> None:
    sql, _ = await _executed(lambda s: s.page(None, None, None, 51))
    assert sql.startswith("SELECT backups.id, backups.kind, backups.status,") and "*" not in sql
    assert sql.endswith("ORDER BY backups.started_at DESC, backups.id DESC LIMIT :param_1")


async def test_page_binds_kind_and_status() -> None:
    sql, params = await _executed(lambda s: s.page("config_bundle", "failed", None, 9))
    assert "WHERE backups.kind = :kind_1 AND backups.status = :status_1 ORDER BY" in sql
    assert params == {"kind_1": "config_bundle", "status_1": "failed", "param_1": 9}
    kind = (await _executed(lambda s: s.page("pg_dump", None, None, 9)))[1]
    status = (await _executed(lambda s: s.page(None, "ok", None, 9)))[1]
    assert (kind, status) == ({"kind_1": "pg_dump", "param_1": 9}, {"status_1": "ok", "param_1": 9})


async def test_keyset_after_is_strict() -> None:
    sql, params = await _executed(lambda s: s.page(None, None, (NOW, ID), 2))
    assert (
        "WHERE backups.started_at <= :started_at_1 AND (backups.started_at < :started_at_2"
        " OR backups.id < :id_1) ORDER BY"
    ) in sql  # strictly after the position; at its own start, only the smaller ids
    assert params == {"started_at_1": NOW, "started_at_2": NOW, "id_1": ID, "param_1": 2}


@pytest.mark.parametrize(
    ("error", "sqlstate"),
    [
        (_dbapi(sa_exc.DBAPIError, "57014"), "57014"),  # asyncpg's statement timeout
        (_dbapi(sa_exc.OperationalError, "08006"), "08006"),  # the connection failed
        (_dbapi(sa_exc.OperationalError, "53300"), "53300"),  # too many connections
        (_dbapi(sa_exc.OperationalError, "58030"), "58030"),  # an I/O error
        (_dbapi(sa_exc.InterfaceError, None), None),  # no SQLSTATE: the connection is gone
        (_dbapi(sa_exc.DBAPIError, "40001"), "40001"),  # a class nobody listed: a retry is harmless
        (_dbapi(sa_exc.DBAPIError, "hunter2 " + _ALIAS), None),  # text is not a SQLSTATE
        (sa_exc.TimeoutError(_DSN), None),  # the pool is exhausted
        (ConnectionRefusedError(_DSN), None),
    ],
    ids="timeout-57 connection-08 resources-53 io-58 none unlisted-40 text pool refused".split(),
)
@pytest.mark.parametrize("op", ["page", "get"])
async def test_outage_sqlstates_leave_as_storage_tier_unavailable_without_driver_text(
    op: str, error: Exception, sqlstate: str | None
) -> None:
    raised = await _raised(op, error, sqlstate)
    assert type(raised) is StorageTierUnavailable and str(raised) == f"backups: {op} failed"


@pytest.mark.parametrize(
    ("error", "sqlstate"),
    [
        (_dbapi(sa_exc.DBAPIError, "22P02"), "22P02"),  # asyncpg: a data error, generic type
        (_dbapi(sa_exc.DataError, "22012"), "22012"),
        (_dbapi(sa_exc.IntegrityError, "23505", "backups_pkey"), "23505"),
        (_dbapi(sa_exc.IntegrityError, "23503", "backups_deleted_by_fkey"), "23503"),
        (_dbapi(sa_exc.ProgrammingError, "42703"), "42703"),
        (_dbapi(sa_exc.InternalError, "XX000"), "XX000"),
        (sa_exc.ArgumentError(_DSN), None),  # not the database's at all
    ],
    ids="data-22P02 data-22012 unique-23505 fk-23503 column-42 internal-XX argument".split(),
)
async def test_bug_sqlstates_keep_their_type(error: Exception, sqlstate: str | None) -> None:
    # a bug, never an outage (no 503 inviting a retry): its SQLSTATE alone (BK-2 question 4)
    raised = await _raised("get", error, sqlstate)
    assert type(raised) is StorageQueryFailed and raised.sqlstate == sqlstate


@pytest.mark.parametrize("pg3", [False, True], ids=["asyncpg", "psycopg"])
@pytest.mark.parametrize(
    ("constraint", "refused"),
    [
        (None, BackupWriteOnceViolation),  # `trg_backups_write_once` names no constraint
        ("bk_trigger", BackupCheckViolation),
        ("bk_verify", BackupCheckViolation),
        ("bk_deleted", BackupCheckViolation),
        ("sha256_hex_check", StorageQueryFailed),  # a 23514 nobody mapped: a bug, still typed
    ],
)
async def test_a_23514_is_typed_by_the_constraint_it_names_and_never_carries_the_row(
    constraint: str | None, refused: type[StorageError], pg3: bool
) -> None:
    """F3 of BK-2's security review: the row (class S alias too) reaches no log or exception."""
    error = _dbapi(sa_exc.IntegrityError, "23514", constraint, pg3)
    raised = await _raised("page", error, "23514")
    assert type(raised) is refused
    if isinstance(raised, BackupCheckViolation):  # by name only
        assert raised.constraint == constraint == str(raised).split()[1]


def test_the_literal_sets_are_the_tables() -> None:
    checks = [c for c in backups.constraints if isinstance(c, sa.CheckConstraint)]
    lists = {  # the model's naming convention prefixes `ck_backups_`; the table's DDL does not
        str(c.name).removeprefix("ck_backups_"): re.findall(r"'(\w+)'", str(c.sqltext))
        for c in checks
    }
    assert (
        get_args(port.BackupKind) == BACKUP_KINDS and get_args(port.BackupStatus) == BACKUP_STATUSES
    )
    assert [*get_args(port.TriggeredBy)] == lists["bk_trigger"]
    assert [*get_args(port.VerifyMethod)] == lists["bk_verify"]
    assert set(get_args(port.BackupCheck)) == set(lists)  # every CHECK has its typed refusal
    assert port.BACKUP_ERROR_CODES == {
        "checksum_mismatch", "checksum_unbound", "artefact_missing", "verify_failed",
        "audit_unavailable", "store_unavailable", "internal_error",
    }  # fmt: skip


def test_counts_as_usable_is_a_verified_status_with_verified_at_and_no_deleted_at() -> None:
    usable = {
        (status, at, gone)
        for status in get_args(port.BackupStatus)
        for at in (None, NOW)
        for gone in (None, NOW)
        if port.counts_as_usable(replace(_ROW, status=status, verified_at=at, deleted_at=gone))
    }
    assert usable == {("verified", NOW, None), ("restored", NOW, None)}  # `usable_count`'s rule


async def test_writes_bind_the_alias_once_and_never_return_it() -> None:
    assert _ALIAS not in repr(_NEW)  # nor in a logged `NewBackup`
    for op, call in _WRITES.items():
        sql, params = await _executed(call, write=True)
        written, _, returned = sql.partition(" RETURNING ")
        assert "encryption_ref" not in returned and _ALIAS not in sql  # bound, never inlined
        assert (
            ("encryption_ref" in written) is (_ALIAS in params.values()) is (op == "insert_running")
        )


@pytest.mark.parametrize("code", ["checksum mismatch", "CHECKSUM_MISMATCH", "", "boom " + _DSN])
async def test_error_writes_accept_only_the_closed_code_set(code: Any) -> None:
    rel = _Rel(_ONE)
    store = repo.SqlAlchemyBackups(rel)  # type: ignore[arg-type]  # structural fake
    with pytest.raises(ValueError) as run:
        await store.record_run_finished(ID, port.RunFinished(NOW, code))
    with pytest.raises(ValueError) as verify:
        await store.record_verify_outcome(ID, method="checksum", at=NOW, error=code)
    assert rel.events == [] and "hunter2" not in str(run.value) + str(verify.value)


@pytest.mark.parametrize(
    "path",
    ["b/x", "", "/b/x@host", "/b/file://x", "s3://" + "key:" + "pw" + "@host/b"],
    ids=["relative", "empty", "userinfo", "scheme-inside", "url"],
)
async def test_insert_refuses_a_target_path_that_is_not_an_absolute_filesystem_path(
    path: str,
) -> None:
    rel = _Rel(_ONE)
    new = port.NewBackup(ID, "pg_dump", path, True, "manual", USER, NOW, encryption_ref=_ALIAS)
    with pytest.raises(ValueError) as refused:
        await repo.SqlAlchemyBackups(rel).insert_running(new)  # type: ignore[arg-type]  # fake
    assert rel.events == [] and str(refused.value) == (
        "backups: target_path must be an absolute filesystem path"
    )  # fixed: a URL's userinfo is never echoed


async def test_naive_datetimes_are_refused_before_any_sql() -> None:
    for build in (
        lambda: port.NewBackup(ID, "pg_dump", "/b/7", True, "manual", USER, NAIVE),
        lambda: port.RunFinished(NAIVE, None),
        lambda: port.RunFinished(NOW, None, covers_from=NAIVE),
        lambda: port.RunFinished(NOW, None, covers_to=NAIVE),
        lambda: port.RunFinished(NOW, None, retention_until=NAIVE),
    ):
        with pytest.raises(ValueError, match="timezone-aware"):
            build()
    rel = _Rel(_ONE)
    store = repo.SqlAlchemyBackups(rel)  # type: ignore[arg-type]  # structural fake
    with pytest.raises(ValueError, match="timezone-aware"):
        await store.mark_deleted(ID, by=USER, at=NAIVE)
    with pytest.raises(ValueError, match="timezone-aware"):
        await store.record_verify_outcome(ID, method="checksum", at=NAIVE, error=None)
    assert rel.events == []


def test_the_run_report_is_keyword_only() -> None:
    with pytest.raises(TypeError):  # its datetimes cannot be swapped by position
        port.RunFinished(NOW, None, 3)  # type: ignore[call-arg]  # a positional report, refused
