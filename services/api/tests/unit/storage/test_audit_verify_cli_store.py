"""`SqlAlchemyAuditVerifyDatabase` (E43-T10, #1238) without a database: read-only sessions named
for the run, the chain reads' budget, the catalogue reads' shapes, and a SQLSTATE-only
`AuditReadFailed`. The live refusal runs in `tests/integration/audit/test_audit_chain_verify_pg.py`.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import pytest
import sqlalchemy as sa

from candleviewer.storage.repositories import break_glass_cli_sqlalchemy as mod
from candleviewer.storage.repositories.audit_sqlalchemy import AuditReadFailed

MP = pytest.MonkeyPatch

_DSN = "postgresql+asyncpg://ro@127.0.0.1:1/candleviewer"  # never connected to


class _Orig(Exception):
    def __init__(self, sqlstate: str) -> None:
        super().__init__("driver error naming audit-db.invalid")
        self.sqlstate = sqlstate


def _database(monkeypatch: MP, outcome: Any) -> tuple[Any, list[Any]]:
    database = mod.SqlAlchemyAuditVerifyDatabase(
        _DSN, statement_timeout_ms=7_000, max_entry_bytes=65_536
    )
    calls: list[Any] = []

    async def execute(statement: Any, params: dict[str, Any]) -> Any:
        calls.append((statement, params))
        if isinstance(outcome, Exception):
            raise outcome
        return SimpleNamespace(mappings=lambda: SimpleNamespace(all=lambda: outcome))

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
            "search_path": "pg_catalog, public",
        }
        assert database.application_name.startswith("candleviewer:audit-verify:")
        assert (database.audit_log._verify_timeout_ms, database.audit_log._entry_bytes) == (
            7_000,
            65_536,
        )
        plain: dict[str, Any] = {}
        ack._name_session(None, None, [], plain)  # the acknowledgement still writes its record
        assert plain["server_settings"] == {"application_name": ack.application_name}
    finally:
        await database.dispose()
        await ack.dispose()


def test_the_catalogue_reads_only_read_and_name_each_catalogue_object_with_its_schema() -> None:
    for statement in (mod._HELD, mod._TRIGGERS, mod._REPLICATION, mod._CHAIN_FUNCTION):
        text = str(statement)
        assert text.startswith("SELECT ") and not re.search(r"INSERT |UPDATE |DELETE |GRANT ", text)
        names = r"pg_\w+|has_\w+|unnest|substr|lower|current_\w+|concat\w*|format|cardinality"
        assert set(re.findall(rf"(?<![\w.'])({names})\b", text)) <= {"pg_catalog"}
        assert not re.search(r"(?<!pg_catalog\.)\b(text|name|int2)\[\]", text)
        assert not re.search(r"\|\||\bSET ", text)  # no operator looked up by argument type
    assert all(
        "nspname = 'public'" in str(s) for s in (mod._HELD, mod._TRIGGERS, mod._CHAIN_FUNCTION)
    )


async def test_held_privileges_groups_rows_by_role_and_table(monkeypatch: MP) -> None:
    rows = [
        {"role": "cv_app", "table_name": "audit_log", "privilege": "INSERT", "held": True},
        {"role": "cv_app", "table_name": "audit_log", "privilege": "UPDATE", "held": False},
        {"role": "cv_ro", "table_name": "audit_log", "privilege": "INSERT", "held": False},
    ]
    database, calls = _database(monkeypatch, rows)
    held = await database.held_privileges(["cv_app", "cv_ro"], ["audit_log"], ["INSERT"])
    assert held == {("cv_app", "audit_log"): {"INSERT"}, ("cv_ro", "audit_log"): frozenset()}
    params = {"roles": ["cv_app", "cv_ro"], "tables": ["audit_log"], "privileges": ["INSERT"]}
    assert calls[0][1] == params
    await database.dispose()


def test_a_privilege_counts_through_columns_and_every_role_the_login_can_become() -> None:
    text = str(mod._HELD)
    assert "has_any_column_privilege(m.oid, c.oid, p.priv)" in text
    assert "has_table_privilege(m.oid, c.oid, p.priv)" in text
    assert "pg_has_role(r.oid, m.oid, 'MEMBER')" in text
    assert "ARRAY['SELECT', 'INSERT', 'UPDATE', 'REFERENCES']" in text


def test_only_the_trigger_states_that_fire_for_an_ordinary_session_count_as_enabled() -> None:
    text = str(mod._TRIGGERS)
    assert "t.tgenabled IN ('O', 'A') AS enabled" in text
    assert "pg_catalog.format('type=%s', t.tgtype)" in text and "t.tgqual IS NOT NULL" in text
    assert "pg_catalog.format('function=%s.%s', fn.nspname, f.proname)" in text
    assert "CAST(t.tgattr AS pg_catalog.int2[])" in text


@pytest.mark.parametrize("enabled", [False, None, "t"])
async def test_a_trigger_is_enabled_only_when_the_catalogue_says_true(
    monkeypatch: MP, enabled: Any
) -> None:
    rows = [{"name": "trg_audit_append", "table_name": "audit_log", "enabled": enabled}]
    rows[0]["shape"] = "type=27 function=public.forbid_mutation"
    database, _ = _database(monkeypatch, rows)
    assert await database.triggers(["audit_log"]) == {
        ("trg_audit_append", "audit_log"): (False, "type=27 function=public.forbid_mutation")
    }
    await database.dispose()


async def test_triggers_and_the_chain_definition(monkeypatch: MP) -> None:
    rows = [
        {"name": "trg_audit_chain", "table_name": "audit_log", "enabled": True, "shape": "x when"}
    ]
    database, _ = _database(monkeypatch, rows)
    assert await database.triggers(["audit_log"]) == {
        ("trg_audit_chain", "audit_log"): (True, "x when")
    }
    await database.dispose()
    database, _ = _database(monkeypatch, [{"definition": "CREATE FUNCTION audit_chain()"}])
    assert await database.chain_definition() == "CREATE FUNCTION audit_chain()"
    await database.dispose()
    database, _ = _database(monkeypatch, [])
    assert await database.chain_definition() is None
    await database.dispose()


async def test_replication_roles_name_where_each_setting_applies(monkeypatch: MP) -> None:
    values = [(None, None, "origin"), (True, None, "replica"), (False, "cv_app", "local")]
    rows = [dict(zip(("db", "role", "value"), v, strict=True)) for v in values]
    database, calls = _database(monkeypatch, rows)
    where = ["session", "this database, role any", "all databases, role cv_app"]
    got = await database.replication_roles()
    assert got == [(w, v[2]) for w, v in zip(where, values, strict=True)]
    assert calls == [(mod._REPLICATION, {})]
    await database.dispose()


async def test_a_database_error_becomes_a_sqlstate_only_read_failure(monkeypatch: MP) -> None:
    database, _ = _database(monkeypatch, sa.exc.DBAPIError("SELECT ...", {}, _Orig("42501")))
    with pytest.raises(AuditReadFailed) as raised:
        await database.triggers(["audit_log"])
    assert raised.value.sqlstate == "42501" and "audit-db" not in str(raised.value)
    assert raised.value.__cause__ is None and raised.value.__context__ is None
    await database.dispose()
