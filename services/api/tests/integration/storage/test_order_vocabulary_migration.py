"""Integration: `0034_order_vocabulary` on real Postgres 16 (E29-T03 #847, slice 2): the head and
its `ord_lifecycle` CHECK, a rerun after the committed `ADD VALUE`s, the round trip on an empty and
a seeded database, and the refused downgrade. `testcontainers` in CI; run before the PR on a
scratch PostgreSQL 16.2 (no docker on the laptop)."""

from __future__ import annotations

import os
import re
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

from candleviewer.db import models
from candleviewer.storage.repositories.orders import OPEN_STATES, ORDER_STATE_OF

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
_PREV = "0033_machine_persistence"
_TEMPLATE = "vocabulary_head_template"
_LABELS = (
    "SELECT t.typname, e.enumlabel FROM pg_type t JOIN pg_enum e ON e.enumtypid = t.oid "
    "WHERE t.typname LIKE 'order%' ORDER BY t.typname, e.enumsortorder"
)
_SHAPE = (
    "SELECT attname, format_type(atttypid, atttypmod) FROM pg_attribute "
    "WHERE attrelid = 'orders'::regclass AND attnum > 0 AND NOT attisdropped ORDER BY attnum"
)
_INDEXES = "SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'orders'"

Conn = psycopg.Connection[tuple[Any, ...]]


def _alembic(dsn: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 -- fixed argv, literal alembic subcommands, no shell (#847)
        [sys.executable, "-m", "alembic", *args],
        cwd=_ROOT, env={**os.environ, "CV_PG_DSN": dsn}, capture_output=True, text=True,
        check=False, timeout=120,
    )  # fmt: skip


def _conn(dsn: str) -> Conn:
    return psycopg.connect(dsn.replace("postgresql+psycopg", "postgresql"), autocommit=True)


def _clone(dsn: str, template: str) -> str:
    name = f"vocab_{uuid.uuid4().hex[:12]}" if template == _TEMPLATE else _TEMPLATE
    with _conn(f"{dsn.rsplit('/', 1)[0]}/postgres") as c:
        stmt = sql.SQL("CREATE DATABASE {} TEMPLATE {}")
        c.execute(stmt.format(sql.Identifier(name), sql.Identifier(template)))
    return f"{dsn.rsplit('/', 1)[0]}/{name}"


@pytest.fixture(scope="module")
def pg_dsn() -> Iterator[str]:
    """Head, plus an untouched copy of it that each test clones."""
    with PostgresContainer("postgres:16-alpine") as container:
        dsn = container.get_connection_url().replace("postgresql+psycopg2", "postgresql+psycopg")
        assert _alembic(dsn, "upgrade", "head").returncode == 0
        _clone(dsn, dsn.rsplit("/", 1)[1])
        yield dsn


def _order(c: Conn, state: str = "accepted", lifecycle: str | None = None, **event: str) -> None:
    """An order of a new account with its first event; `event` overrides the event's columns."""
    acct, oid = uuid.uuid4(), uuid.uuid4()
    row = {"kind": "ack", "from_state": None, "to_state": "accepted"} | event
    c.execute(
        "INSERT INTO exchange_accounts (id, exchange, env, kind, exchange_uid, label) VALUES "
        "(%s, 'bybit', 'demo', 'main', %s, %s)", (acct, str(acct.int % 10**15), f"L{acct.hex[:8]}"),
    )  # fmt: skip
    c.execute(
        "INSERT INTO orders (id, exchange_account_id, order_link_id, symbol, side, intent, "
        "order_type, qty, state, lifecycle_state) VALUES (%s, %s, %s, 'BTCUSDT', 'Buy', 'entry', "
        "'Market', 1, %s, %s)", (oid, acct, f"ext-{oid.hex}", state, lifecycle),
    )  # fmt: skip
    c.execute(
        "INSERT INTO order_events (order_id, seq, kind, source, from_state, to_state, event_ts) "
        "VALUES (%s, 0, %s, 'rest', %s, %s, now())", (oid, *row.values()),
    )  # fmt: skip


def _catalog(c: Conn) -> tuple[dict[str, tuple[str, ...]], list[Any], dict[str, str]]:
    labels: dict[str, tuple[str, ...]] = {}
    for typname, label in c.execute(_LABELS):
        labels[typname] = (*labels.get(typname, ()), label)
    return labels, c.execute(_SHAPE).fetchall(), dict(c.execute(_INDEXES).fetchall())


def _predicate(indexdef: str) -> set[str]:
    return set(re.findall(r"'(\w+)'::order_state", indexdef))


def test_head_holds_the_vocabulary_and_rows_take_every_added_value(pg_dsn: str) -> None:
    with _conn(_clone(pg_dsn, _TEMPLATE)) as c:
        labels, shape, indexes = _catalog(c)
        for state in models.ORDER_STATES[12:]:  # usable at once: committed before the index
            _order(c, state, state, kind="adopt", from_state=state, to_state=state)
        _order(c, "accepted", "submitted", kind="kill")
        for lifecycle, state in ORDER_STATE_OF.items():  # `ord_lifecycle` admits every mapped pair
            _order(c, state, lifecycle)
    assert labels == {
        "order_event_kind": models.ORDER_EVENT_KINDS,
        "order_intent": models.ORDER_INTENTS,
        "order_lifecycle_state": models.ORDER_LIFECYCLE_STATES,
        "order_state": models.ORDER_STATES,
    }
    assert shape[-1] == ("lifecycle_state", "order_lifecycle_state")
    assert _predicate(indexes["ix_orders_open"]) == OPEN_STATES


@pytest.mark.parametrize(
    ("state", "lifecycle"), [("filled", "draft"), ("submitted", "submitted"), ("held", "untracked")]
)
def test_ord_lifecycle_refuses_a_pair_the_mapping_does_not_name(
    pg_dsn: str, state: str, lifecycle: str
) -> None:
    """The two columns never disagree; (`submitted`, `submitted`) is the trap itself."""
    with _conn(_clone(pg_dsn, _TEMPLATE)) as c, pytest.raises(pgerr.CheckViolation) as refused:
        _order(c, state, lifecycle)
    assert refused.value.sqlstate == "23514"
    assert refused.value.diag.constraint_name == "ord_lifecycle"


@pytest.mark.parametrize("n", [2, 7], ids=["cut-off", "all-seven"])
def test_a_rerun_completes_after_the_autocommit_block_committed(pg_dsn: str, n: int) -> None:
    """A failure after the `ADD VALUE`s leaves them at 0033_machine_persistence (none can be
    dropped); the rerun skips those, adds the rest and builds the head a clean run builds."""
    dsn = _clone(pg_dsn, _TEMPLATE)
    with _conn(dsn) as c:
        head = _catalog(c)
    assert _alembic(dsn, "downgrade", _PREV).returncode == 0
    added = [("order_state", v) for v in models.ORDER_STATES[12:]]
    added += [("order_event_kind", v) for v in models.ORDER_EVENT_KINDS[14:]]
    with _conn(dsn) as c:
        for kind, value in added[:n]:  # the first n, committed in the block's order
            add = sql.SQL("ALTER TYPE {} ADD VALUE {}")
            c.execute(add.format(sql.Identifier(kind), sql.Literal(value)))
    rerun = _alembic(dsn, "upgrade", "head")
    assert rerun.returncode == 0, rerun.stderr
    with _conn(dsn) as c:
        assert _catalog(c) == head


@pytest.mark.parametrize("seeded", [False, True], ids=["empty", "seeded"])
def test_round_trip_restores_0029s_types_and_indexes(pg_dsn: str, seeded: bool) -> None:
    dsn = _clone(pg_dsn, _TEMPLATE)
    with _conn(dsn) as c:
        if seeded:
            _order(c)
        head = _catalog(c)
    assert _alembic(dsn, "downgrade", _PREV).returncode == 0
    with _conn(dsn) as c:
        labels, shape, indexes = _catalog(c)
        kept = c.execute("SELECT state::text, count(*) FROM orders GROUP BY 1").fetchall()
        events = c.execute("SELECT kind::text, to_state::text FROM order_events").fetchall()
    assert labels["order_state"] == models.ORDER_STATES[:12]
    assert labels["order_event_kind"] == models.ORDER_EVENT_KINDS[:14]
    assert "order_lifecycle_state" not in labels and len(labels) == 3  # nothing renamed is left
    assert shape == head[1][:-1]
    assert _predicate(indexes["ix_orders_open"]) == OPEN_STATES - set(models.ORDER_STATES[12:])
    assert _predicate(indexes["ix_orders_untracked"]) == {"untracked"}
    assert (kept, events) == (([("accepted", 1)], [("ack", "accepted")]) if seeded else ([], []))
    assert _alembic(dsn, "upgrade", "head").returncode == 0
    with _conn(dsn) as c:
        assert _catalog(c) == head


@pytest.mark.parametrize(
    "row",
    [*({"state": state} for state in models.ORDER_STATES[12:]), {"lifecycle": "submitted"},
     {"kind": "kill"}, {"kind": "adopt"}, {"from_state": "unknown"}, {"to_state": "held"}],
    ids=lambda row: "-".join(f"{k}={v}" for k, v in row.items()),
)  # fmt: skip
def test_downgrade_refuses_while_a_row_holds_what_the_revision_added(
    pg_dsn: str, row: dict[str, str]
) -> None:
    dsn = _clone(pg_dsn, _TEMPLATE)
    with _conn(dsn) as c:
        _order(c, **row)
        before = c.execute("SELECT version_num FROM alembic_version").fetchone(), _catalog(c)
    refused = _alembic(dsn, "downgrade", _PREV)
    assert refused.returncode != 0
    assert "0034_order_vocabulary downgrade refused: a row holds" in refused.stderr
    with _conn(dsn) as c:
        after = c.execute("SELECT version_num FROM alembic_version").fetchone(), _catalog(c)
    assert after == before
