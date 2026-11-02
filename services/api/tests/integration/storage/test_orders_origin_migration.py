"""Integration: `orders.origin` and `origin_ref` on real Postgres 16 (E35-T11 #5003 slice 3a; 21
Sec.3.3.4 "Origin").

`ord_origin` refuses by name a value outside 24 Sec.8.1's seven; `ord_origin_ref` holds a NULL
origin to a NULL ref, a `rule` origin to its rule's canonical lower-case UUID, and leaves any other
origin's ref free, NULL-safe in every arm; rows stored before the revision keep both columns NULL;
and the round trip runs on an empty database and on a seeded one (C-5.5). `testcontainers` in CI;
run on the VPS when its load allows.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import psycopg
import pytest
from psycopg import errors as pgerr
from psycopg import sql
from testcontainers.postgres import PostgresContainer

from candleviewer.domain.primitives import AccountId, GroupId
from candleviewer.oms.order_link import OrderLinkIdParts

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
_FILE = next(  # the revision that adds the columns: its id is read from it, never repeated
    path
    for path in sorted((_ROOT / "candleviewer" / "migrations" / "versions").glob("*.py"))
    if "ADD COLUMN origin_ref text" in path.read_text(encoding="utf-8")
)
_RULE = "3f2b8c1e-5d4a-4e6f-9a0b-1c2d3e4f5a6b"
Conn = psycopg.Connection[tuple[Any, ...]]


def _down_revision() -> str:
    """Read from the file, so a re-parent edits the migration and the lockfile only."""
    spec = importlib.util.spec_from_file_location("rev_orders_origin_it", _FILE)
    assert spec is not None and spec.loader is not None
    revision = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(revision)
    return str(revision.down_revision)


def _alembic(dsn: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 -- fixed argv, literal alembic subcommands, no shell (#5003)
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


def _order(c: Conn, account: str, **origin: str | None) -> str:
    """One validated groupless order of `account`, with `origin` and `origin_ref` as given (none
    named: the columns left out, as a row written before the revision)."""
    link = OrderLinkIdParts.generate(
        mode="exchange", environment="demo", group_id=GroupId(uuid.uuid4()),
        account_id=AccountId(uuid.UUID(account)), seq=0, purpose="entry",
    ).value  # fmt: skip
    row: dict[str, Any] = {
        "id": str(uuid.uuid4()), "exchange_account_id": account, "order_link_id": link,
        "symbol": "BTCUSDT", "side": "Buy", "intent": "entry", "order_type": "Market",
        "qty": "0.010", "stop_loss": "58000", "state": "pending_submit",
        "lifecycle_state": "validated",
    } | origin  # fmt: skip
    stmt = sql.SQL("INSERT INTO orders ({}) VALUES ({})").format(
        sql.SQL(", ").join(sql.Identifier(k) for k in row),
        sql.SQL(", ").join([sql.Placeholder()] * len(row)),
    )
    c.execute(stmt, tuple(row.values()))
    return str(row["id"])


def _refused_by(c: Conn, account: str, constraint: str, **origin: str | None) -> None:
    with pytest.raises(pgerr.CheckViolation) as refused:
        _order(c, account, **origin)
    assert refused.value.diag.constraint_name == constraint


def test_ord_origin_refuses_a_value_outside_the_seven(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c:
        account = _account(c)
        for value in ("ticket", "chart", "dom", "hotkey", "algo_child", "api"):
            _order(c, account, origin=value)
        _order(c, account, origin="rule", origin_ref=_RULE)
        for outside in ("manual", "Rule", "", "rule "):
            _refused_by(c, account, "ord_origin", origin=outside, origin_ref=_RULE)


_REFS: list[tuple[str | None, str | None]] = [
    (None, "x"),  # a ref with no origin
    (None, _RULE),  # NULL-safe: a NULL origin never passes on a UUID
    ("rule", None),  # NULL-safe: a rule's order names its rule
    ("rule", "not-a-uuid"),
    ("rule", _RULE.upper()),  # canonical lower-case only
    ("rule", "{" + _RULE + "}"),
    ("rule", _RULE.replace("-", "")),
]


@pytest.mark.parametrize(("origin", "ref"), _REFS)
def test_ord_origin_ref_refuses_what_its_arms_do_not_admit(
    pg_dsn: str, origin: str | None, ref: str | None
) -> None:
    with _conn(pg_dsn) as c:
        _refused_by(c, _account(c), "ord_origin_ref", origin=origin, origin_ref=ref)


def test_ord_origin_ref_needs_a_canonical_uuid_for_rule_and_is_free_for_other_origins(
    pg_dsn: str,
) -> None:
    """The three arms: no origin, no ref; `rule`, its rule's id; any other origin, any ref or
    none (24 Sec.8.1: a parent order's id, a hotkey's name)."""
    admitted: list[tuple[str | None, str | None]] = [
        (None, None), ("rule", _RULE), ("hotkey", "F5"), ("ticket", None),
        ("algo_child", str(uuid.uuid4())), ("api", "not-a-uuid"),
    ]  # fmt: skip
    with _conn(pg_dsn) as c:
        account = _account(c)
        ids = [_order(c, account, origin=o, origin_ref=r) for o, r in admitted]
        rows = c.execute(
            "SELECT origin, origin_ref FROM orders WHERE id = ANY(%s::uuid[]) "
            "ORDER BY array_position(%s::uuid[], id)",
            (ids, ids),
        ).fetchall()
        assert rows == admitted


def test_rows_stored_before_the_revision_keep_a_null_origin(pg_dsn: str) -> None:
    """No default and no backfill: a row written before the revision reads NULL in both after it,
    and both CHECKs, validated, admit it."""
    prev = _down_revision()
    with _conn(pg_dsn) as c:
        assert _alembic(pg_dsn, "downgrade", prev).returncode == 0
        try:
            order = _order(c, _account(c))
        finally:
            assert _alembic(pg_dsn, "upgrade", "head").returncode == 0
        got = c.execute("SELECT origin, origin_ref FROM orders WHERE id = %s", (order,))
        assert got.fetchone() == (None, None)
        validated = c.execute(
            "SELECT conname, convalidated FROM pg_constraint WHERE conrelid = 'orders'::regclass "
            "AND conname IN ('ord_origin', 'ord_origin_ref') ORDER BY conname"
        ).fetchall()
        assert validated == [("ord_origin", True), ("ord_origin_ref", True)]


def test_alembic_check_finds_the_models_and_head_in_step(pg_dsn: str) -> None:
    """CI-MIG-002 on the VPS: `db.models` mirrors the revision."""
    checked = _alembic(pg_dsn, "check")
    assert checked.returncode == 0, checked.stderr[-2000:]


def test_upgrade_downgrade_upgrade_on_an_empty_and_a_seeded_database(pg_dsn: str) -> None:
    """C-5.5: a database with nothing in it goes up, down past the revision and up again; so does
    one holding orders with and without an origin (C-5.2: the downgrade drops both columns, which
    the code it rolls back to never reads), the seeded rows kept with NULL in both after it."""
    name = f"oo_{uuid.uuid4().hex[:12]}"
    with _conn(_database(pg_dsn, "postgres")) as c:
        c.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    empty = _database(pg_dsn, name)
    for step in (("upgrade", "head"), ("downgrade", _down_revision()), ("upgrade", "head")):
        done = _alembic(empty, *step)
        assert done.returncode == 0, (step, done.stderr[-2000:])
    with _conn(pg_dsn) as c:
        account = _account(c)
        seeded = [_order(c, account, origin="rule", origin_ref=_RULE), _order(c, account)]
        for step in (("downgrade", _down_revision()), ("upgrade", "head")):
            done = _alembic(pg_dsn, *step)
            assert done.returncode == 0, (step, done.stderr[-2000:])
        rows = c.execute(
            "SELECT origin, origin_ref FROM orders WHERE id = ANY(%s::uuid[])", (seeded,)
        ).fetchall()
        assert rows == [(None, None), (None, None)]
