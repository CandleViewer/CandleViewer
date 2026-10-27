"""Integration: `0053_tg_frozen_after_draft` against real Postgres 16 (E28-T05 #909, SEC-2-04).

Once a trade group leaves `draft`, `trg_tg_write_once` refuses a change of the seven create-only
columns (SQLSTATE 23514, the column named, never a value); a draft still takes them, the OMS's
updates of `status` and the times pass, and a rule's delete still clears `origin_rule_id`. The round
trip holds on an empty and on the E28-seeded database (C-5.5). `testcontainers` in CI; the offline
render is `tests/unit/migrations/test_0053_tg_frozen_after_draft.py`.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg
import pytest
from psycopg import errors as pgerr
from psycopg import sql
from psycopg.types.json import Jsonb

from tests.integration import _refused

pytestmark = pytest.mark.integration

pg_dsn = _refused.pg_dsn  # the module-scoped Postgres 16 at head; its database is named `test`
_ROOT = Path(__file__).resolve().parents[3]  # services/api, where `alembic.ini` lives
_REPO, _PREV = _ROOT.parents[1], "0052_ia_purge_anchor"
_USER, _RULE_A, _RULE_B = (uuid.UUID(int=n) for n in (0xA1, 0xB1, 0xB2))
_SEEDED = uuid.UUID("e28f0000-0000-4000-8000-0000000000b1")  # G-CORE3: `cancelled`, so fired
Conn = psycopg.Connection[tuple[Any, ...]]
#: Per column, the value a group is written with and the value a later write tries.
_CASES: dict[str, tuple[Any, Any]] = {
    "symbol": ("BTCUSDT", "ETHUSDT"),
    "side": ("Buy", "Sell"),
    "entry_type": ("Limit", "Market"),
    "origin": ("manual", "hotkey"),
    "is_paper": (False, True),
    "algo_params": (Jsonb({"k": "a"}), Jsonb({"k": "b"})),
    "origin_rule_id": (_RULE_A, _RULE_B),
}
_STATUSES = ("submitting", "partially_open", "open", "closing", "closed", "failed", "cancelled")
_CATALOG = (
    "SELECT prosrc, proconfig, prosecdef FROM pg_proc WHERE proname = 'tg_write_once'",
    "SELECT tgname, tgenabled::text, pg_get_triggerdef(oid) FROM pg_trigger "
    "WHERE tgrelid = 'trade_groups'::regclass AND NOT tgisinternal ORDER BY tgname",
    "SELECT (SELECT count(*) FROM trade_groups), (SELECT count(*) FROM trade_group_legs)",
)


def _alembic(dsn: str, *args: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "CV_PG_DSN": dsn.replace("postgresql+asyncpg", "postgresql+psycopg")}
    return subprocess.run(  # noqa: S603 -- fixed argv, literal alembic subcommands, no shell (#909)
        [sys.executable, "-m", "alembic", *args],
        cwd=_ROOT, env=env, capture_output=True, text=True, check=False, timeout=120,
    )  # fmt: skip


def _conn(dsn: str) -> Conn:
    return psycopg.connect(dsn.replace("postgresql+asyncpg", "postgresql"), autocommit=True)


@pytest.fixture
def db(pg_dsn: str) -> str:
    """A fresh clone of the head database; the E28 seed's guard wants a name ending `_test`."""
    name, server = f"tgfz_{uuid.uuid4().hex[:12]}_test", pg_dsn.rsplit("/", 1)[0]
    with _conn(f"{server}/postgres") as c:
        c.execute(sql.SQL("CREATE DATABASE {} TEMPLATE test").format(sql.Identifier(name)))
    return f"{server}/{name}"


def _world(c: Conn) -> None:
    """The user the groups belong to and two rules they can name."""
    c.execute(
        "INSERT INTO users (id, email, username, password_hash, status) "
        "VALUES (%s, 'u@example.test', 'user_one', '$argon2id$x', 'active')",
        (_USER,),
    )
    stmt = "INSERT INTO rules (id, name, owner_user_id) VALUES (%s, %s, %s)"
    for rule in (_RULE_A, _RULE_B):
        c.execute(stmt, (rule, str(rule), _USER))


def _group(c: Conn, **cols: Any) -> uuid.UUID:
    """A valid demo `draft` (unless `status` says otherwise) holding `_CASES`'s first values."""
    row: dict[str, Any] = {"id": uuid.uuid4(), "client_group_ref": str(uuid.uuid4())}
    row |= {"client_body_sha256": "ab" * 32, "created_by": _USER, "env": "demo"}
    row |= {column: first for column, (first, _) in _CASES.items()} | {"entry_price": 64000}
    row |= cols
    names = sql.SQL(", ").join(map(sql.Identifier, row))
    marks = sql.SQL(", ").join(sql.Placeholder() for _ in row)
    insert = sql.SQL("INSERT INTO trade_groups ({}) VALUES ({})").format(names, marks)
    c.execute(insert, [*row.values()])
    return uuid.UUID(str(row["id"]))


def _write(c: Conn, group: uuid.UUID, **values: Any) -> None:
    sets = sql.SQL(", ").join(sql.SQL("{} = %s").format(sql.Identifier(k)) for k in values)
    stmt = sql.SQL("UPDATE trade_groups SET {} WHERE id = %s").format(sets)
    c.execute(stmt, [*values.values(), group])


def _frozen(c: Conn, group: uuid.UUID, column: str, value: Any) -> None:
    """`trg_tg_write_once` refuses the write and names the column, nothing else."""
    with pytest.raises(pgerr.CheckViolation) as exc, c.transaction():
        _write(c, group, **{column: value})
    diag = exc.value.diag
    assert exc.value.sqlstate == "23514" and diag.constraint_name == "trg_tg_write_once"
    assert diag.message_primary == f"trg_tg_write_once: trade_groups.{column} is write-once"
    assert diag.message_detail is None and diag.message_hint is None


@pytest.mark.parametrize(("column", "status"), list(zip(_CASES, _STATUSES, strict=True)))
def test_each_create_only_column_freezes_once_a_group_leaves_draft(
    db: str, column: str, status: str
) -> None:
    """A draft takes the write, and so does the statement that fires it (the freeze reads the row as
    it was, `OLD.status`); the next one is refused, whichever status the group fired into."""
    first, second = _CASES[column]
    with _conn(db) as c:
        _world(c)
        group = _group(c)
        _write(c, group, **{column: second})
        _write(c, group, status=status, **{column: first})
        _frozen(c, group, column, second)


def test_a_rule_delete_still_clears_origin_rule_id(db: str) -> None:
    """The FK's `ON DELETE SET NULL` is an UPDATE of a fired group that this trigger sees."""
    with _conn(db) as c:
        _world(c)
        group = _group(c, status="submitting", origin="rule")
        c.execute("DELETE FROM rules WHERE id = %s", (_RULE_A,))
        row = c.execute("SELECT origin_rule_id, origin FROM trade_groups WHERE id = %s", (group,))
        assert row.fetchone() == (None, "rule")  # cleared, and nothing else moved


def test_origin_rule_id_is_never_cleared_swapped_or_given_while_its_rule_stands(db: str) -> None:
    with _conn(db) as c:
        _world(c)
        named = _group(c, status="submitting")
        _frozen(c, named, "origin_rule_id", None)  # only the rule's delete may clear it
        _frozen(c, named, "origin_rule_id", _RULE_B)
        _frozen(c, _group(c, status="submitting", origin_rule_id=None), "origin_rule_id", _RULE_A)


def test_status_and_times_still_update_after_draft(db: str) -> None:
    """The OMS's updates pass; so does a frozen column written over its own value, NULL over NULL
    included."""
    now = datetime(2026, 10, 27, tzinfo=UTC)
    with _conn(db) as c:
        _world(c)
        group = _group(c, status="submitting")
        bare = _group(c, status="open", algo_params=None, origin_rule_id=None)
        for status, time in (("partially_open", "submitted_at"), ("open", "opened_at")):
            _write(c, group, status=status, **{time: now})
        _write(c, group, status="closed", closed_at=now)
        same = sql.SQL(", ").join(sql.SQL("{0} = {0}").format(sql.Identifier(k)) for k in _CASES)
        for fired in (group, bare):
            c.execute(sql.SQL("UPDATE trade_groups SET {} WHERE id = %s").format(same), (fired,))
        row = c.execute("SELECT status::text FROM trade_groups WHERE id = %s", (group,)).fetchone()
        assert row == ("closed",)


def _body_0039() -> str:
    text = (_ROOT / "candleviewer" / "migrations" / "versions" / "0039_trade_groups.py").read_text()
    found = re.search(r"CREATE FUNCTION tg_write_once\(\).*?AS \$BODY\$(.*?)\$BODY\$;", text, re.S)
    assert found is not None
    return found.group(1)


def _catalog(c: Conn) -> list[list[tuple[Any, ...]]]:
    return [list(c.execute(query).fetchall()) for query in _CATALOG]


@pytest.mark.parametrize("seeded", [False, True], ids=["empty", "seeded"])
def test_the_revision_round_trips(db: str, seeded: bool) -> None:
    """C-5.5 on an empty and on the E28 seed (its groups are `cancelled`, so fired): head holds the
    freeze, the downgrade puts 0039's function back byte for byte and a fired group's symbol is
    writable again, and the upgrade restores the catalogue at head; no row moves."""
    with _conn(db) as c:
        if seeded:
            c.execute((_REPO / "tests" / "fixtures" / "e28" / "seed.sql").read_bytes())
            _frozen(c, _SEEDED, "symbol", "ETHUSDT")
        head = _catalog(c)
        assert "OLD.status <> 'draft'" in head[0][0][0]  # head holds the freeze, not 0039's body
        assert head[0][0][1:] == (["search_path=pg_catalog, pg_temp"], False)  # pinned, as caller
        assert {name: when for name, when, _ in head[1]}["trg_tg_write_once"] == "A"  # ALWAYS
    assert _alembic(db, "downgrade", _PREV).returncode == 0
    with _conn(db) as c:
        back = _catalog(c)
        assert back[0][0][0] == _body_0039() and back[1:] == head[1:]
        if seeded:
            _write(c, _SEEDED, symbol="ETHUSDT")  # 0039's list never froze it
            _write(c, _SEEDED, symbol="BTCUSDT")
    assert _alembic(db, "upgrade", "head").returncode == 0
    with _conn(db) as c:
        assert _catalog(c) == head
        if seeded:
            _frozen(c, _SEEDED, "symbol", "ETHUSDT")
