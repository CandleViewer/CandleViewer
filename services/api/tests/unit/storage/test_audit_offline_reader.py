"""`SqlAlchemyAuditOfflineReader` (E43-T10): read-only sessions, the catalogue reads' shapes and
their error mapping, on a fake unit of work. Constructing it opens no connection. No database."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import pytest
import sqlalchemy as sa

from candleviewer.storage.repositories import audit_offline_sqlalchemy as mod
from candleviewer.storage.repositories.audit_sqlalchemy import AuditReadFailed

FAKE_DSN = "postgresql+asyncpg://verifier@audit-db.invalid/candleviewer"


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


def _reader_with(monkeypatch: pytest.MonkeyPatch, outcome: Any) -> tuple[Any, list[Any]]:
    reader = mod.SqlAlchemyAuditOfflineReader(FAKE_DSN)
    calls: list[Any] = []

    async def execute(statement: Any, params: dict[str, Any]) -> _Result:
        calls.append((statement, params))
        if isinstance(outcome, Exception):
            raise outcome
        return _Result(outcome)

    @asynccontextmanager
    async def unit_of_work() -> AsyncIterator[Any]:
        yield SimpleNamespace(session=SimpleNamespace(execute=execute))

    monkeypatch.setattr(reader._relational, "unit_of_work", unit_of_work)
    return reader, calls


def test_read_only_listener_sets_the_session_default_and_keeps_other_settings() -> None:
    cparams: dict[str, Any] = {"server_settings": {"application_name": "x"}}
    mod._read_only(None, None, None, cparams)
    assert cparams["server_settings"] == {
        "application_name": "x",
        "default_transaction_read_only": "on",
    }


def test_statements_only_read_the_catalogue() -> None:
    for statement in (mod._HELD, mod._TRIGGERS):
        text = str(statement).upper()
        assert text.startswith("SELECT ")
        assert not any(w in text for w in ("INSERT ", "UPDATE ", "DELETE ", "GRANT ", "SET "))


async def test_held_privileges_groups_rows_by_role_and_table(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [
        {"role": "cv_app", "table_name": "audit_log", "privilege": "INSERT", "held": True},
        {"role": "cv_app", "table_name": "audit_log", "privilege": "UPDATE", "held": False},
        {"role": "cv_ro", "table_name": "audit_log", "privilege": "INSERT", "held": False},
    ]
    reader, calls = _reader_with(monkeypatch, rows)
    held = await reader.held_privileges(["cv_app", "cv_ro"], ["audit_log"], ["INSERT", "UPDATE"])
    assert held == {("cv_app", "audit_log"): {"INSERT"}, ("cv_ro", "audit_log"): frozenset()}
    assert calls[0][1] == {
        "roles": ["cv_app", "cv_ro"],
        "tables": ["audit_log"],
        "privileges": ["INSERT", "UPDATE"],
    }
    await reader.close()


async def test_triggers_maps_name_to_table_and_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [{"name": "trg_audit_append", "table_name": "audit_log", "enabled": False}]
    reader, _ = _reader_with(monkeypatch, rows)
    assert await reader.triggers(["audit_log"]) == {"trg_audit_append": ("audit_log", False)}
    await reader.close()


async def test_a_database_error_becomes_a_sqlstate_only_read_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    error = sa.exc.DBAPIError("SELECT ...", {}, _Orig("42501"))
    reader, _ = _reader_with(monkeypatch, error)
    with pytest.raises(AuditReadFailed) as raised:
        await reader.triggers(["audit_log"])
    assert raised.value.sqlstate == "42501"
    assert "audit-db" not in str(raised.value)
    assert raised.value.__cause__ is None and raised.value.__context__ is None
    await reader.close()
