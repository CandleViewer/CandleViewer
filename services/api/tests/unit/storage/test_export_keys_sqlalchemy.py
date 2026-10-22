"""`SqlAlchemyExportKeyStore` (#889 S4b): its statements, its copies of M2's rules, the refusals it
shares with M2's fake, made before any I/O, and each write's steps over a unit of work that logs
them. The SQL runs on Postgres 16 in `tests/integration/storage/test_export_key_store_pg.py`."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast

import pytest
import sqlalchemy as sa
import structlog
from sqlalchemy.exc import DBAPIError

from candleviewer.secrets import store as m2
from candleviewer.storage.errors import (
    ExportKeyAuditNotWritten,
    ExportKeyRequestTaken,
    StorageQueryFailed,
)
from candleviewer.storage.repositories import export_keys_sqlalchemy as m
from tests.unit.credentials_m2 import test_export_key_store as m1
from tests.unit.storage.test_credentials_rewrap_tx import RECORD

# Self-discovering: a statement added later cannot dodge the guards.
_STATEMENTS = {n: v for n, v in vars(m).items() if isinstance(v, sa.TextClause)}


def _port(store: m.SqlAlchemyExportKeyStore) -> m2.ExportKeyStore:
    return store  # mypy holds the adapter to the Protocol M2 is typed against


def test_statements_name_their_columns_and_environment_and_never_delete() -> None:
    assert set(_STATEMENTS) == {
        "_ACTIVE", "_LIST", "_ROTATION", "_INSERT", "_RETIRE", "_TOP", "_REWRAP", "_COUNT",
        "_RETAINED", "_DESTROY",
    }  # fmt: skip
    for name, stmt in _STATEMENTS.items():
        text = str(stmt)
        # 21 Sec.12 forbids `SELECT *` on audit_signing_keys; for this module, this is the guard.
        assert not re.search(r"(?i)(select|returning)\s+(distinct\s+)?\*|\w\.\*", text), name
        assert "DELETE" not in text.upper() and "TRUNCATE" not in text.upper(), name  # 0046
        assert "CAST(:env AS exchange_env)" in text, name  # the process environment's (C-2.11)


def test_a_public_record_is_read_without_the_seed_or_its_wrap() -> None:
    public = [str(m._LIST), str(m._ROTATION)]
    public += [str(stmt).split("RETURNING", 1)[1] for stmt in (m._INSERT, m._RETIRE)]
    assert not [sql for sql in public if "sealed_seed" in sql or "dek_ref" in sql]


def test_the_adapters_copies_of_m2s_rules_have_not_drifted() -> None:
    assert [m._DEK_REF.pattern, m._KEY_ID.pattern] == [m2._DEK_REF.pattern, m2._KEY_ID.pattern]
    assert (m._REASONS, m._REQUEST, m._AS_MADE) == (m2.RETIRED_REASONS, m2._REQUEST, m2._AS_MADE)
    keys = (*m2.EXPORT_KEY_PUBLIC, "client_body_sha256")  # no `secrets` import here (C-3.2)
    new, old = ({k: f"{v} {k}" for k in keys} for v in ("new", "old"))
    assert m._rotation(dict(new), dict(old)) == m2._rotation(new, old)


def _no_record(action: str, fields: dict[str, str]) -> dict[str, Any]:
    raise AssertionError("a refused call builds no record")


@pytest.mark.parametrize("call", m1.REFUSED.values(), ids=list(m1.REFUSED))
async def test_a_refused_call_reaches_no_database(call: m1.Call) -> None:
    """What M2's fake refuses, the adapter refuses before any I/O: with no database at all, a call
    that reached one would fail on `None`, not refuse. Nor does it build a record."""
    adapter = m.SqlAlchemyExportKeyStore(cast(Any, None), env="demo", audit_row=_no_record)
    with pytest.raises(ValueError):  # `ExportKeyEnvironmentError` is one
        await call(adapter)


T = datetime.fromisoformat(RECORD["event_ts"])  # the time of the record `build` returns
#: v1 as the retire's UPDATE returns it, active since the day before T.
V1 = dict(version=1, key_id=m1.key_id(1), valid_from=T - timedelta(1), client_body_sha256=None)
FIRST, ROTATE = m1._first(m1.export_key(1)), m1._rotating(m1.export_key(2, **m1.rotation_request()))
#: Each write's steps: the record built first, the key's statements, the record's, chain lock last.
FIRST_LOG = ["BUILD", "INSERT", "LOCK", "INSERT"]
ROTATE_LOG = ["BUILD", "UPDATE", "SELECT", "INSERT", "LOCK", "INSERT"]


class _Tx:
    """`test_credentials_rewrap_tx.py`'s logging unit of work (`LOCK`: the chain lock) and record
    builder for `store`. The retire returns `old`; the key's INSERT violates `refused` or returns
    its row; the record's writes `recorded` rows. `at` keeps the time each key statement writes."""

    def __init__(self, old: Any = V1, refused: str = "", recorded: int = 1) -> None:
        self.old, self.refused, self.recorded = old, refused, recorded
        self.log: list[str] = []
        self.at: list[datetime] = []
        self.store = m.SqlAlchemyExportKeyStore(cast(Any, self), env="demo", audit_row=self.build)

    def build(self, action: str, fields: dict[str, str]) -> dict[str, Any]:
        self.log.append("BUILD")
        return RECORD

    @asynccontextmanager
    async def unit_of_work(self) -> AsyncIterator[Any]:
        async def execute(stmt: sa.TextClause, params: Any = None) -> Any:
            self.log.append("LOCK" if "advisory" in stmt.text else stmt.text.split()[0])
            if stmt is m._INSERT and self.refused:  # as asyncpg reports one: no value
                orig = SimpleNamespace(sqlstate="23505", constraint_name=self.refused)
                raise DBAPIError("INSERT", None, cast(Any, orig))
            self.at += [params["at"]] if stmt is m._RETIRE or stmt is m._INSERT else []
            row = self.old if stmt is m._RETIRE else params
            res = SimpleNamespace(rowcount=self.recorded, one=lambda: row, one_or_none=lambda: row)
            res.mappings, res.scalar_one = lambda: res, lambda: self.old["version"]
            return res

        async def commit() -> None:
            self.log.append("COMMIT")

        try:
            yield SimpleNamespace(session=SimpleNamespace(execute=execute), commit=commit)
        except BaseException:
            self.log.append("ROLLBACK")
            raise


@pytest.mark.parametrize(
    ("call", "log", "days"),
    [(FIRST, FIRST_LOG, -1), (ROTATE, ROTATE_LOG, -1), (ROTATE, ROTATE_LOG, 1)],
    ids=["first", "rotate", "clock_stepped_back"],
)
async def test_a_write_locks_its_rows_then_the_chain_and_commits_at_its_records_time(
    call: m1.Call, log: list[str], days: int
) -> None:
    """T, the record's `event_ts`, ends the retired key and starts the new one even before its
    `valid_from` (a clock stepped back; 21 Sec.3.1.5b): never refused or clamped, but a warning."""
    tx = _Tx(old=V1 | {"valid_from": T + timedelta(days)})
    with structlog.testing.capture_logs() as logs:
        assert await call(tx.store)
    assert tx.log == [*log, "COMMIT"] and set(tx.at) == {T}
    ids = {"retired_key_id": m1.key_id(1), "active_key_id": m1.key_id(2)}
    warned = {"event": "audit.export_key.clock_anomaly", "log_level": "warning", "env": "demo"}
    assert logs == ([warned | ids] if days > 0 else [])


UNDONE = {  # a write that cannot finish: its call, the unit of work, outcome, steps
    "stale": (ROTATE, {"old": None}, None, ROTATE_LOG[:2]),  # `retire` is not the active key
    "boot_won": (FIRST, {"refused": "ux_ask_active"}, False, FIRST_LOG[:2]),
    "reused_id": (FIRST, {"refused": "audit_signing_keys_pkey"}, StorageQueryFailed, FIRST_LOG[:2]),
    "retried": (ROTATE, {"refused": "ask_env_request"}, ExportKeyRequestTaken, ROTATE_LOG[:4]),
    "other_23505": (ROTATE, {"refused": "ask_env_fingerprint"}, StorageQueryFailed, ROTATE_LOG[:4]),
    "first_record": (FIRST, {"recorded": 0}, ExportKeyAuditNotWritten, FIRST_LOG),
    "rotate_record": (ROTATE, {"recorded": 0}, ExportKeyAuditNotWritten, ROTATE_LOG),
}


@pytest.mark.parametrize(("call", "uow", "outcome", "log"), UNDONE.values(), ids=list(UNDONE))
async def test_a_write_that_cannot_finish_commits_nothing(
    call: m1.Call, uow: dict[str, Any], outcome: type[Exception] | bool | None, log: list[str]
) -> None:
    """Only another boot's key reads as False and only `ask_env_request` as a retry: any other
    23505, a reused `id` included, raises `StorageQueryFailed`, nothing chained (C-12.6)."""
    tx = _Tx(**uow)
    if isinstance(outcome, type):
        with pytest.raises(outcome) as raised:
            await call(tx.store)
        assert type(raised.value) is outcome and raised.value.__context__ is None
    else:
        assert await call(tx.store) is outcome
    assert tx.log == (log if outcome is None else [*log, "ROLLBACK"])
