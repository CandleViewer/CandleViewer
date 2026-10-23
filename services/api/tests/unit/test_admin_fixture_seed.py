"""E42-Q01 (#962): the admin seed and its check over an in-memory connection (no Docker). A test
spoils one row the seed made and shows that the check names it; the Postgres half is
`tests/integration/admin/test_admin_fixture_seed_pg.py`.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, cast

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import IteratorResult
from sqlalchemy.engine.result import SimpleResultMetaData
from sqlalchemy.ext.asyncio import AsyncConnection

from candleviewer.db import models as m
from candleviewer.observability.redaction import redact_text
from tests.fixtures.admin.handles import KEY_RESTRICTION, OWNER, account, user
from tests.fixtures.admin.seed import (
    FixtureCheckError,
    FixtureRefused,
    check_admin_world,
    seed_admin_world,
)

_NOW = datetime(2026, 10, 22, 12, 0, tzinfo=UTC)
_GATE = "trading.live_enabled"
_INVITED, _LOCKED, _MGR_M = (user(h).id for h in ("INVITED-I", "LOCKED-L", "MGR-M"))
_SUB_K, _SUB_S, _SUB_T = (account(h).id for h in ("SUB-K", "SUB-S", "SUB-T"))
_RUN = Callable[..., Awaitable[None]]


class FakeDb:
    """An insert leaves its row, a select answers with its table's rows, and every statement sent
    is kept. Conflicts (`DO NOTHING`, a flag's `DO UPDATE`) are Postgres's: integration test."""

    def __init__(self, database: str = "test") -> None:
        self.database = database
        self.statements: list[Any] = []
        roles = [{"id": uuid.uuid5(uuid.NAMESPACE_DNS, n), "name": n} for n in m.role_name.enums]
        self.tables: dict[str, list[dict[str, Any]]] = {"roles": roles}

    @property
    def conn(self) -> AsyncConnection:
        return cast("AsyncConnection", self)

    def row(self, table: str, **where: Any) -> dict[str, Any]:
        return next(r for r in self.tables[table] if all(r.get(k) == v for k, v in where.items()))

    async def execute(self, stmt: Any) -> IteratorResult[Any]:
        self.statements.append(stmt)
        keys: list[str] = ["name"]
        rows: list[tuple[Any, ...]] = [(self.database,)]  # `SELECT current_database()`
        if isinstance(stmt, sa.Insert):
            self.tables.setdefault(stmt.table.name, []).append(dict(stmt.compile().params))
            keys, rows = [], []
        elif isinstance(stmt, sa.Select):
            keys = [str(c.key) for c in stmt.selected_columns]
            held = self.tables[cast(sa.Table, stmt.get_final_froms()[0]).name]
            rows = [tuple(r.get(k) for k in keys) for r in held]
        return IteratorResult(SimpleResultMetaData(keys), iter(rows))


@pytest.fixture
async def seeded() -> FakeDb:
    db = FakeDb()
    await seed_admin_world(db.conn, now=_NOW)
    return db


async def _refuses(db: FakeDb, named: str) -> None:
    """The check raises `FixtureCheckError`, its message naming `named` (a regex)."""
    with pytest.raises(FixtureCheckError, match=named):
        await check_admin_world(db.conn, now=_NOW)


async def test_the_check_passes_the_world_the_seed_made(seeded: FakeDb) -> None:
    await check_admin_world(seeded.conn, now=_NOW)


#: One seeded value spoiled per case: its table and key, its column, the new value, what is named.
_SPOILS = [
    ("feature_flags", {"key": _GATE}, "default_value", True, "live_enabled: is True"),
    ("exchange_accounts", {"id": _SUB_K}, "created_at", _NOW - KEY_RESTRICTION, "SUB-K: inside"),
    ("exchange_accounts", {"id": _SUB_S}, "env", "live", "SUB-S: env is live"),
    ("users", {"id": _LOCKED}, "status", "active", "LOCKED-L: status is active"),
    ("users", {"id": _LOCKED}, "locked_until", _NOW - KEY_RESTRICTION, "LOCKED-L: locked_until"),
    ("user_invites", {"user_id": _INVITED}, "role", "manager", "INVITED-I: invite role is manager"),
    ("user_invites", {"user_id": _INVITED}, "revoked_at", _NOW, "INVITED-I: 0 open invites"),
    ("user_invites", {"user_id": _INVITED}, "consumed_at", _NOW, "INVITED-I: 0 open invites"),
    ("user_invites", {"user_id": _INVITED}, "expires_at", _NOW, "INVITED-I: 0 open invites"),
    ("user_invites", {"user_id": _INVITED}, "token_hash", "short", "INVITED-I: token_hash"),
    ("user_account_access", {"user_id": _MGR_M}, "frozen", True, "MGR-M: a grant is frozen"),
    ("user_account_access", {"user_id": _MGR_M}, "can_view", False, "MGR-M: a grant is .* not"),
    ("user_account_access", {"user_id": _MGR_M}, "can_trade", False, "MGR-M: a grant is .* not"),
]


@pytest.mark.parametrize(
    ("table", "where", "column", "value", "named"), _SPOILS, ids=[c[4] for c in _SPOILS]
)
async def test_the_check_names_a_spoiled_value(
    seeded: FakeDb, table: str, where: dict[str, Any], column: str, value: Any, named: str
) -> None:
    seeded.row(table, **where)[column] = value
    await _refuses(seeded, named)


@pytest.mark.parametrize(
    ("table", "where", "named"),
    [
        ("user_account_access", {"user_id": _MGR_M}, "MGR-M: grants are not SUB-S"),
        ("exchange_accounts", {"id": _SUB_T}, "SUB-T: env is None"),
    ],
)
async def test_the_check_names_a_missing_row(
    seeded: FakeDb, table: str, where: dict[str, Any], named: str
) -> None:
    seeded.tables[table].remove(seeded.row(table, **where))
    await _refuses(seeded, named)


async def test_the_check_names_a_stray_second_role(seeded: FakeDb) -> None:
    viewer = seeded.row("roles", name="viewer")["id"]
    seeded.tables["user_roles"].append({"user_id": _MGR_M, "role_id": viewer})
    await _refuses(seeded, r"MGR-M: roles are \['manager', 'viewer'\], not manager")


@pytest.mark.parametrize("run", [seed_admin_world, check_admin_world])
async def test_a_database_not_named_for_tests_is_refused_before_anything_else(run: _RUN) -> None:
    db = FakeDb("candleviewer")
    with pytest.raises(FixtureRefused):
        await run(db.conn, now=_NOW)
    assert [str(s) for s in db.statements] == ["SELECT current_database()"]


@pytest.mark.parametrize("run", [seed_admin_world, check_admin_world])
async def test_a_naive_now_is_refused(run: _RUN) -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        await run(FakeDb().conn, now=datetime(2026, 10, 22, 12, 0))


async def test_each_run_draws_its_own_invite_token(seeded: FakeDb) -> None:
    other = FakeDb()
    await seed_admin_world(other.conn, now=_NOW)
    assert other.row("user_invites")["token_hash"] != seeded.row("user_invites")["token_hash"]


async def test_the_invited_user_names_the_owner_as_inviter(seeded: FakeDb) -> None:
    inviters = [
        seeded.row("users", id=_INVITED).get("invited_by"),
        seeded.row("user_roles", user_id=_INVITED).get("granted_by"),
    ]
    assert inviters == [OWNER.id, OWNER.id]


async def test_the_seeded_exchange_is_the_enums_one_value(seeded: FakeDb) -> None:
    seen = [r["exchange"] for r in seeded.tables["exchange_accounts"]]
    assert seen == [*m.exchange_code.enums] * len(seen)  # the enum's values, once per account


async def test_no_value_the_seed_writes_is_secret_shaped(seeded: FakeDb) -> None:
    written = [v for rows in seeded.tables.values() for r in rows for v in r.values()]
    assert [v for v in written if isinstance(v, str) and redact_text(v) != v] == []
