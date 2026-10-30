"""Integration: `oms_handovers` on real Postgres 16 (E29-T06 #914 PR 1; 21 Sec.3.3.12).

Each CHECK refuses by name at its bounds, a `record` that leaves a key out included; one entry per
order and per fill in an account; the guard lets an empty read's count rise and each stamp land
once, and nothing else change; the SQLAlchemy store's statements (the account's lock, the append,
the count, the bound, the decision and the prune) hold on the engine; and the round trip runs on
an empty database and on a seeded one, and refuses while an entry exists. `testcontainers` in CI;
run on the VPS when its load allows.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, LiteralString
from uuid import UUID

import psycopg
import pytest
from psycopg import errors as pgerr
from psycopg import sql
from psycopg.types.json import Jsonb
from testcontainers.postgres import PostgresContainer

from candleviewer.storage.repositories import oms_handovers_sqlalchemy as handover_sql
from candleviewer.storage.repositories.oms_handovers import (
    HandoverKind,
    HandoverStoreFull,
    NewHandover,
)
from candleviewer.storage.repositories.oms_handovers_sqlalchemy import SqlAlchemyHandoverStore
from candleviewer.storage.repositories.relational_sqlalchemy import SqlAlchemyRelationalRepository

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
_FILE = next(  # the revision that creates the table: its id is read from it, never repeated
    path
    for path in sorted((_ROOT / "candleviewer" / "migrations" / "versions").glob("*.py"))
    if "CREATE TABLE oms_handovers (" in path.read_text(encoding="utf-8")
)
_T0 = datetime(2026, 10, 30, 9, 0, tzinfo=UTC)
Conn = psycopg.Connection[tuple[Any, ...]]
Record = dict[str, Any] | list[Any] | Callable[[str], Any]


def _down_revision() -> str:
    """Read from the file, so a re-parent edits the migration and the lockfile only."""
    spec = importlib.util.spec_from_file_location("rev_oms_handovers_it", _FILE)
    assert spec is not None and spec.loader is not None
    revision = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(revision)
    return str(revision.down_revision)


def _alembic(dsn: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 -- fixed argv, literal alembic subcommands, no shell (#914)
        [sys.executable, "-m", "alembic", *args],
        cwd=_ROOT,
        env={**os.environ, "CV_PG_DSN": dsn.replace("postgresql+asyncpg", "postgresql+psycopg")},
        capture_output=True, text=True, check=False, timeout=180,
    )  # fmt: skip


@pytest.fixture(scope="module")
def pg_dsn() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine") as container:
        dsn = container.get_connection_url().replace("postgresql+psycopg2", "postgresql+asyncpg")
        assert _alembic(dsn, "upgrade", "head").returncode == 0
        yield dsn


def _conn(dsn: str) -> Conn:
    return psycopg.connect(dsn.replace("postgresql+asyncpg", "postgresql"), autocommit=True)


def _database(dsn: str, name: str) -> str:
    return f"{dsn.rsplit('/', 1)[0]}/{name}"


def _account(c: Conn) -> str:
    aid, uid = str(uuid.uuid4()), str(uuid.uuid4().int % 10**15)
    c.execute(
        "INSERT INTO exchange_accounts (id, exchange, env, kind, exchange_uid, label) "
        "VALUES (%s, 'bybit', 'demo', 'main', %s, %s)",
        (aid, uid, f"acct {uid}"),
    )
    return aid


def _entry(
    c: Conn,
    account: str,
    *,
    kind: str = "order",
    order: str = "x1",
    fill: str | None = None,
    record: Record | None = None,
    **columns: Any,
) -> int:
    """Insert one entry; its `record` names its own account, order and fill unless given."""
    if record is None:
        record = {"account_id": account, "exchange_order_id": order}
        record |= {} if fill is None else {"exec_id": fill}
    elif callable(record):
        record = record(account)
    row: dict[str, Any] = {"exchange_account_id": account, "kind": kind}
    row |= {"exchange_order_id": order, "exec_id": fill, "source": "reconcile"}
    row |= {"record": Jsonb(record)} | columns
    if "payload" in row:
        row["payload"] = Jsonb(row["payload"])
    stmt = sql.SQL("INSERT INTO oms_handovers ({}) VALUES ({}) RETURNING id").format(
        sql.SQL(", ").join(sql.Identifier(k) for k in row),
        sql.SQL(", ").join([sql.Placeholder()] * len(row)),
    )
    got = c.execute(stmt, tuple(row.values())).fetchone()
    assert got is not None
    return int(got[0])


def test_an_order_and_a_fill_are_kept_with_their_defaults(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c:
        account = _account(c)
        ids = (_entry(c, account, order="o1"), _entry(c, account, kind="execution", fill="e1"))
        rows = c.execute(
            "SELECT kind, payload, empty_reads, first_empty_read_at, decided_at, created_at "
            "IS NOT NULL FROM oms_handovers WHERE id = ANY(%s) ORDER BY id",
            (list(ids),),
        ).fetchall()
        assert rows == [("order", {}, 0, None, None, True), ("execution", {}, 0, None, None, True)]


_FILL: dict[str, Any] = {"kind": "execution", "fill": "e1"}
_REFUSED: list[tuple[dict[str, Any], str]] = [
    ({"kind": "trade"}, "oh_kind"),
    ({"fill": "e1"}, "oh_exec"),  # an order that names a fill
    ({"kind": "execution"}, "oh_exec"),  # a fill that names none
    ({"source": "manual"}, "oh_source"),
    ({"order": ""}, "oh_ids"),
    ({"order": "x" * 65}, "oh_ids"),
    ({"kind": "execution", "fill": "e" * 65}, "oh_ids"),
    ({"record": ["x1"]}, "oh_record"),
    ({"record": {"account_id": str(uuid.uuid4()), "exchange_order_id": "x1"}}, "oh_record"),
    ({"record": {"exchange_order_id": "x1"}}, "oh_record"),  # no account: refused, never NULL
    ({"record": lambda a: {"account_id": a}}, "oh_record"),  # no order
    ({**_FILL, "record": lambda a: {"account_id": a, "exchange_order_id": "x1"}}, "oh_record"),
    ({"payload": ["raw"]}, "oh_payload"),
    ({"empty_reads": 1, "first_empty_read_at": _T0}, "oh_reads"),  # an order counts no read
    ({"decided_at": _T0}, "oh_reads"),  # nor is it decided
    ({**_FILL, "empty_reads": 1}, "oh_reads"),  # a count with no stamp
    ({**_FILL, "first_empty_read_at": _T0}, "oh_reads"),  # a stamp with no count
    ({**_FILL, "empty_reads": -1}, "oh_reads"),
]


@pytest.mark.parametrize(("over", "constraint"), _REFUSED)
def test_a_row_the_table_cannot_hold_is_refused_by_its_named_check(
    pg_dsn: str, over: dict[str, Any], constraint: str
) -> None:
    with _conn(pg_dsn) as c:
        account = _account(c)
        with pytest.raises(pgerr.CheckViolation) as err:
            _entry(c, account, **over)
        assert err.value.diag.constraint_name == constraint


def test_one_entry_per_order_and_per_fill_in_an_account(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c:
        a, b = _account(c), _account(c)
        _entry(c, a, order="o1")
        _entry(c, a, kind="execution", order="o1", fill="e1")
        for kind, fill, index in (
            ("order", None, "ux_oh_order"),
            ("execution", "e1", "ux_oh_exec"),
        ):
            with pytest.raises(pgerr.UniqueViolation) as err:
                _entry(c, a, kind=kind, order="o1", fill=fill)
            assert err.value.diag.constraint_name == index
        _entry(c, a, kind="execution", order="o1", fill="e2")  # another fill of the same order
        _entry(c, b, order="o1")  # another account's ids are another key
        _entry(c, b, kind="execution", order="o1", fill="e1")


def test_the_guard_lets_the_count_rise_and_each_stamp_land_once_and_nothing_else(
    pg_dsn: str,
) -> None:
    with _conn(pg_dsn) as c:
        eid = _entry(c, _account(c), kind="execution", fill="e1")
        c.execute(
            "UPDATE oms_handovers SET empty_reads = 1, first_empty_read_at = now() WHERE id = %s",
            (eid,),
        )
        c.execute(
            "UPDATE oms_handovers SET empty_reads = 2, decided_at = now() WHERE id = %s", (eid,)
        )
        refused: list[tuple[str, LiteralString]] = [
            ("entry", "UPDATE oms_handovers SET source = 'rest' WHERE id = %s"),
            ("entry", "UPDATE oms_handovers SET record = record || '{\"x\": 1}' WHERE id = %s"),
            ("empty_reads", "UPDATE oms_handovers SET empty_reads = 1 WHERE id = %s"),
            (
                "first_empty_read_at",
                "UPDATE oms_handovers SET first_empty_read_at = first_empty_read_at"
                " + interval '1 second' WHERE id = %s",
            ),
            ("decided_at", "UPDATE oms_handovers SET decided_at = NULL WHERE id = %s"),
        ]
        for column, change in refused:
            with pytest.raises(pgerr.CheckViolation) as err:
                c.execute(change, (eid,))
            assert err.value.diag.constraint_name == "trg_oh_guard", change
            assert f"oms_handovers.{column} may not change so" in str(err.value), change
        row = c.execute(
            "SELECT empty_reads, decided_at IS NOT NULL FROM oms_handovers WHERE id = %s", (eid,)
        ).fetchone()
        assert row == (2, True)


def _new(
    account: UUID,
    kind: HandoverKind,
    order: str,
    fill: str | None = None,
    *,
    empty_read: bool = False,
) -> NewHandover:
    record = {"account_id": str(account), "exchange_order_id": order}
    record |= {} if fill is None else {"exec_id": fill}
    return NewHandover(
        exchange_account_id=account,
        kind=kind,
        exchange_order_id=order,
        exec_id=fill,
        source="reconcile",
        record=record,
        empty_read=empty_read,
    )


async def test_the_store_appends_once_counts_reads_decides_once_and_prunes_in_scope(
    pg_dsn: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    with _conn(pg_dsn) as c:
        account, other = UUID(_account(c)), UUID(_account(c))
    rel = SqlAlchemyRelationalRepository(pg_dsn, "handovers-it")
    store = SqlAlchemyHandoverStore(rel)
    try:
        order = _new(account, "order", "o1")
        assert [await store.append(order), await store.append(order)] == ["added", "held"]
        fill = _new(account, "execution", "o1", "e1", empty_read=True)
        assert [await store.append(fill), await store.append(fill)] == ["added", "counted"]
        [row] = await store.pending(account, "execution")
        assert (row.empty_reads, row.decided_at) == (2, None) and row.first_empty_read_at
        assert row.record == {
            "account_id": str(account),
            "exchange_order_id": "o1",
            "exec_id": "e1",
        }
        assert await store.pending(other, "execution") == ()
        decisions = [await store.decide(other, "e1"), await store.decide(account, "e1")]
        assert [*decisions, await store.decide(account, "e1")] == [False, True, False]
        [kept] = await store.pending(account, "order")
        assert await store.prune(other, [kept.id, row.id]) == 0
        assert await store.prune(account, [kept.id, row.id]) == 2
        assert await store.prune(account, []) == 0
        monkeypatch.setattr(handover_sql, "MAX_HANDOVERS_PER_ACCOUNT", 1)
        assert await store.append(_new(account, "order", "o2")) == "added"
        with pytest.raises(HandoverStoreFull):
            await store.append(_new(account, "order", "o3"))
        assert await store.append(_new(account, "order", "o2")) == "held"  # held: never refused
        assert [r.exchange_order_id for r in await store.pending(account, "order")] == ["o2"]
    finally:
        await rel.dispose()


def test_alembic_check_finds_the_models_and_head_in_step(pg_dsn: str) -> None:
    """CI-MIG-002 on the VPS: `db.models` mirrors the revision, its column comments included."""
    checked = _alembic(pg_dsn, "check")
    assert checked.returncode == 0, checked.stderr[-2000:]


def test_round_trip_up_down_up_on_an_empty_database(pg_dsn: str) -> None:
    """C-5.5, the empty half: a database with nothing in it goes up, down past the revision and
    up again."""
    name = f"oh_{uuid.uuid4().hex[:12]}"
    with _conn(_database(pg_dsn, "postgres")) as c:
        c.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    dsn = _database(pg_dsn, name)
    for step in (("upgrade", "head"), ("downgrade", _down_revision()), ("upgrade", "head")):
        done = _alembic(dsn, *step)
        assert done.returncode == 0, (step, done.stderr[-2000:])
    with _conn(dsn) as c:
        assert c.execute("SELECT to_regclass('oms_handovers')").fetchone() == ("oms_handovers",)


def test_round_trip_on_a_seeded_database_and_the_refused_downgrade(pg_dsn: str) -> None:
    """C-5.2 and C-5.5, the seeded half: rows elsewhere never block the round trip, and an entry
    refuses the downgrade, as dropping the table would lose what the next pass needs."""
    prev = _down_revision()
    with _conn(pg_dsn) as c:
        c.execute("DELETE FROM oms_handovers")
        _account(c)
        assert _alembic(pg_dsn, "downgrade", prev).returncode == 0
        gone = c.execute("SELECT to_regclass('oms_handovers'), to_regprocedure('oh_guard()')")
        assert gone.fetchone() == (None, None)
        assert _alembic(pg_dsn, "upgrade", "head").returncode == 0
        _entry(c, _account(c), order="blocks")
        refused = _alembic(pg_dsn, "downgrade", prev)
        assert refused.returncode != 0 and "downgrade refused" in refused.stderr
        assert c.execute("SELECT to_regclass('oms_handovers')").fetchone() == ("oms_handovers",)
