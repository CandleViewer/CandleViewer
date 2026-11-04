"""`SqlAlchemyAuditVerifyDatabase` (E43-T10, #1238) without a database: every session is
read-only and named for the run, the chain reads carry the given budget, the catalogue reads
have their shapes, and a database error leaves as a SQLSTATE-only `AuditReadFailed`. The live
read-only refusal runs on Postgres in `tests/integration/audit/test_audit_chain_verify_pg.py`."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import pytest
import sqlalchemy as sa

from candleviewer.storage.repositories import break_glass_cli_sqlalchemy as mod
from candleviewer.storage.repositories.audit_sqlalchemy import AuditReadFailed

_DSN = "postgresql+asyncpg://ro@127.0.0.1:1/candleviewer"  # never connected to


class _Orig(Exception):
    def __init__(self, sqlstate: str) -> None:
        super().__init__("driver error naming audit-db.invalid")
        self.sqlstate = sqlstate


class _Result:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def mappings(self) -> _Result:
        return self

    def all(self) -> list[dict[str, Any]]:
        return self._rows


def _database(monkeypatch: pytest.MonkeyPatch, outcome: Any) -> tuple[Any, list[Any]]:
    database = mod.SqlAlchemyAuditVerifyDatabase(
        _DSN, statement_timeout_ms=7_000, max_entry_bytes=65_536
    )
    calls: list[Any] = []

    async def execute(statement: Any, params: dict[str, Any]) -> _Result:
        calls.append((statement, params))
        if isinstance(outcome, Exception):
            raise outcome
        return _Result(outcome)

    @asynccontextmanager
    async def unit_of_work() -> AsyncIterator[Any]:
        yield SimpleNamespace(session=SimpleNamespace(execute=execute))

    monkeypatch.setattr(database._relational, "unit_of_work", unit_of_work)
    return database, calls


async def test_every_session_is_read_only_and_named_for_the_run() -> None:
    database = mod.SqlAlchemyAuditVerifyDatabase(
        _DSN, statement_timeout_ms=7_000, max_entry_bytes=65_536
    )
    ack = mod.SqlAlchemyAuditAckDatabase(_DSN)
    try:
        cparams: dict[str, Any] = {"server_settings": {"timezone": "UTC"}}
        database._name_session(None, None, [], cparams)
        assert cparams["server_settings"] == {
            "timezone": "UTC",
            "application_name": database.application_name,
            "default_transaction_read_only": "on",
        }
        assert database.application_name.startswith("candleviewer:audit-verify:")
        assert (database.audit_log._verify_timeout_ms, database.audit_log._entry_bytes) == (
            7_000,
            65_536,
        )
        plain: dict[str, Any] = {}
        ack._name_session(None, None, [], plain)  # the acknowledgement still writes its record
        assert "default_transaction_read_only" not in plain["server_settings"]
    finally:
        await database.dispose()
        await ack.dispose()


def test_the_catalogue_statements_only_read() -> None:
    for statement in (mod._HELD, mod._TRIGGERS):
        text = str(statement).upper()
        assert text.startswith("SELECT ") and "NSPNAME = 'PUBLIC'" in text
        assert not any(w in text for w in ("INSERT ", "UPDATE ", "DELETE ", "GRANT ", "SET "))


async def test_held_privileges_groups_rows_by_role_and_table(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [
        {"role": "cv_app", "table_name": "audit_log", "privilege": "INSERT", "held": True},
        {"role": "cv_app", "table_name": "audit_log", "privilege": "UPDATE", "held": False},
        {"role": "cv_ro", "table_name": "audit_log", "privilege": "INSERT", "held": False},
    ]
    database, calls = _database(monkeypatch, rows)
    held = await database.held_privileges(["cv_app", "cv_ro"], ["audit_log"], ["INSERT"])
    assert held == {("cv_app", "audit_log"): {"INSERT"}, ("cv_ro", "audit_log"): frozenset()}
    assert calls[0][1] == {
        "roles": ["cv_app", "cv_ro"],
        "tables": ["audit_log"],
        "privileges": ["INSERT"],
    }
    await database.dispose()


def test_a_privilege_counts_through_columns_and_every_role_the_login_can_become() -> None:
    text = str(mod._HELD)
    assert "has_any_column_privilege(m.oid, c.oid, p.priv)" in text
    assert "has_table_privilege(m.oid, c.oid, p.priv)" in text
    assert "pg_has_role(r.oid, m.oid, 'MEMBER')" in text
    assert "ARRAY['SELECT', 'INSERT', 'UPDATE', 'REFERENCES']" in text


@pytest.mark.parametrize("enabled", [False, None, "t"])
async def test_a_trigger_is_enabled_only_when_the_catalogue_says_true(
    monkeypatch: pytest.MonkeyPatch, enabled: Any
) -> None:
    rows = [{"name": "trg_audit_append", "table_name": "audit_log", "enabled": enabled}]
    database, _ = _database(monkeypatch, rows)
    assert await database.triggers(["audit_log"]) == {"trg_audit_append": ("audit_log", False)}
    await database.dispose()


async def test_a_database_error_becomes_a_sqlstate_only_read_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database, _ = _database(monkeypatch, sa.exc.DBAPIError("SELECT ...", {}, _Orig("42501")))
    with pytest.raises(AuditReadFailed) as raised:
        await database.triggers(["audit_log"])
    assert raised.value.sqlstate == "42501" and "audit-db" not in str(raised.value)
    assert raised.value.__cause__ is None and raised.value.__context__ is None
    await database.dispose()
