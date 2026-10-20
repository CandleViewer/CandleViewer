"""Integration: the `machine_persistence_json` revision on real Postgres 16 (#3857).

At head the four seal- and digest-bearing columns are `json` (24 Sec.17.6), and the values `jsonb`
re-rendered come back as written through the real tables, over the production path (SQLAlchemy
over asyncpg, `db.models`): a float of magnitude 1e16 or more stays that float and `-0.0` keeps
its sign, so `canonical_json`, which the seal and `row_hash` cover, is unchanged. The journal's
stamp-once guard still stamps once and refuses a change to `payload`, now by its text. An empty
database round-trips with an identical schema dump; a populated one refuses the downgrade, naming
the table, as 0033's does, because the cast back would re-render sealed numbers. `testcontainers`,
CI-only; run before the PR on a scratch Postgres 16.4 through a local stand-in.
"""

from __future__ import annotations

import asyncio
import math
import os
import re
import subprocess
import sys
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from functools import cache
from pathlib import Path
from typing import Any

import psycopg
import pytest
import sqlalchemy as sa
from psycopg import errors as pgerr
from psycopg import sql
from sqlalchemy.ext.asyncio import create_async_engine
from testcontainers.postgres import PostgresContainer

from candleviewer.db import models
from candleviewer.statechart.schema import canonical_json

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
_VERSIONS = _ROOT / "candleviewer" / "migrations" / "versions"
(_FILE,) = _VERSIONS.glob("[0-9][0-9][0-9][0-9]_machine_persistence_json.py")
_REV = _FILE.stem  # the revision id is the file's stem (the unit test pins the two equal)
_TEMPLATE = "mjson_head"
_COLUMNS = [
    ("machine_snapshots", "snapshot"),
    ("machine_drain_journal", "payload"),
    ("machine_events", "payload"),
    ("machine_events", "fault"),
]
#: What `jsonb` re-rendered (#3857), beside values it always kept.
_PROBE: dict[str, Any] = {
    "big": 1e16, "bigger": 1.5e17, "huge": 1e300, "negative_zero": -0.0,
    "nested": [[-0.0, 1e16], {"f": 0.1}], "small": 1e-07, "int": 2**63, "text": "é✓😀",
    "null": None,
}  # fmt: skip
_NOW = datetime(2026, 10, 20, 0, 0, tzinfo=UTC)
_STAMP = "UPDATE machine_drain_journal SET replayed_at = %s WHERE send_id = %s"

Conn = psycopg.Connection[tuple[Any, ...]]


@cache
def _prev() -> str:
    """The parent, read from the revision itself, so re-parenting never touches this module."""
    found = re.search(r'^down_revision: str \| None = "(\w+)"$', _FILE.read_text("utf-8"), re.M)
    assert found is not None
    return found[1]


def _alembic(dsn: str, *args: str) -> subprocess.CompletedProcess[str]:
    """Bounded, so a lost `lock_timeout` fails the test instead of hanging it."""
    return subprocess.run(  # noqa: S603 -- fixed argv, literal alembic subcommands, no shell (#3857)
        [sys.executable, "-m", "alembic", *args],
        cwd=_ROOT, env={**os.environ, "CV_PG_DSN": dsn}, capture_output=True, text=True,
        check=False, timeout=120,
    )  # fmt: skip


def _migrate(dsn: str, *args: str) -> None:
    done = _alembic(dsn, *args)
    assert done.returncode == 0, done.stderr


def _url(container: PostgresContainer) -> str:
    return container.get_connection_url().replace("postgresql+psycopg2", "postgresql+psycopg")


def _conn(dsn: str) -> Conn:
    return psycopg.connect(dsn.replace("postgresql+psycopg", "postgresql"), autocommit=True)


def _database(dsn: str, name: str) -> str:
    return f"{dsn.rsplit('/', 1)[0]}/{name}"


def _create(dsn: str, template: str | None = None) -> tuple[str, str]:
    """A new database on the same server, empty or a copy of `template`: its DSN and its name."""
    name = f"mjson_{uuid.uuid4().hex[:12]}"
    statement = sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name))
    if template is not None:
        statement += sql.SQL(" TEMPLATE {}").format(sql.Identifier(template))
    with _conn(_database(dsn, "postgres")) as c:
        c.execute(statement)
    return _database(dsn, name), name


@pytest.fixture(scope="module")
def pg() -> Iterator[PostgresContainer]:
    """Head, plus an untouched copy of it that `_create` clones for tests needing empty tables."""
    with PostgresContainer("postgres:16-alpine") as container:
        dsn = _url(container)
        _migrate(dsn, "upgrade", "head")
        with _conn(_database(dsn, "postgres")) as c:
            c.execute(
                sql.SQL("CREATE DATABASE {} TEMPLATE {}").format(
                    sql.Identifier(_TEMPLATE), sql.Identifier(dsn.rsplit("/", 1)[1])
                )
            )
        yield container


def _one(c: Conn, query: str, *args: object) -> Any:
    row = c.execute(query, args).fetchone()
    assert row is not None, query
    return row[0]


def _types(c: Conn) -> list[tuple[str, str, str]]:
    type_of = (
        "SELECT format_type(atttypid, atttypmod) FROM pg_attribute "
        "WHERE attrelid = %s::regclass AND attname = %s"
    )
    return [(table, column, str(_one(c, type_of, table, column))) for table, column in _COLUMNS]


def _rows(entity: str) -> dict[str, dict[str, Any]]:
    """One valid row per table, every seal- or digest-bearing column holding `_PROBE`."""
    key = {"machine_kind": "order", "entity_id": entity, "env": "demo"}
    return {
        "machine_snapshots": key | {
            "cv_schema_version": 2, "lib_snapshot_ver": 3, "machine_hash": "a" * 64,
            "snapshot": _PROBE, "hmac_key_id": "k1", "hmac_tag": bytes(32),
            "state_ids": ["idle"], "chain_trips": 0, "updated_at": _NOW,
        },
        "machine_drain_journal": key | {
            "send_id": uuid.uuid4().hex, "lane": "inbox", "ordinal": 0, "event_type": "PING",
            "payload": _PROBE,
        },
        "machine_events": key | {
            "event_type": "PING", "payload": _PROBE, "from_states": ["idle"],
            "to_states": ["idle"], "actions_run": [], "fault": _PROBE, "occurred_at": _NOW,
            "phase": "fault", "prev_hash": "0" * 64, "row_hash": uuid.uuid4().hex * 2,
        },
    }  # fmt: skip


async def _write_and_read(dsn: str, entity: str) -> dict[tuple[str, str], Any]:
    """Each row inserted, then each probed column read back, through `db.models` over asyncpg."""
    engine = create_async_engine(dsn.replace("postgresql+psycopg", "postgresql+asyncpg"))
    try:
        async with engine.begin() as conn:
            for name, row in _rows(entity).items():
                await conn.execute(sa.insert(getattr(models, name)), [row])
            back: dict[tuple[str, str], Any] = {}
            for name, column in _COLUMNS:
                table = getattr(models, name)
                stmt = sa.select(table.c[column]).where(table.c.entity_id == entity)
                back[(name, column)] = (await conn.execute(stmt)).scalar_one()
            return back
    finally:
        await engine.dispose()


def test_the_four_columns_are_json_at_head(pg: PostgresContainer) -> None:
    with _conn(_url(pg)) as c:
        assert _types(c) == [(table, column, "json") for table, column in _COLUMNS]


def test_floats_jsonb_re_rendered_come_back_byte_for_byte(pg: PostgresContainer) -> None:
    """#3857: 1e16 stays a float and -0.0 keeps its sign, so the bytes `canonical_json` gives for
    the read-back value, the bytes the seal and `row_hash` cover, are those written."""
    back = asyncio.run(_write_and_read(_url(pg), str(uuid.uuid4())))
    for column, value in back.items():
        assert canonical_json(value) == canonical_json(_PROBE), column
        assert type(value["big"]) is float and value["big"] == 1e16, column
        assert math.copysign(1.0, value["negative_zero"]) == -1.0, column
        assert math.copysign(1.0, value["nested"][0][0]) == -1.0, column


def test_the_journal_guard_stamps_once_and_compares_payload_by_its_text(
    pg: PostgresContainer,
) -> None:
    """`json` has no equality operator: the guard compares the stored text, so the same text over
    itself passes, while a change of spacing alone is a change and is refused."""
    with _conn(_url(pg)) as c:
        send_id = uuid.uuid4().hex
        c.execute(
            "INSERT INTO machine_drain_journal (machine_kind, entity_id, env, send_id, lane, "
            "ordinal, event_type, payload) VALUES ('order', %s, 'demo', %s, 'inbox', 0, 'PING', "
            "%s::json)",
            (str(uuid.uuid4()), send_id, '{"n": 1e16}'),
        )
        update = "UPDATE machine_drain_journal SET payload = %s::json WHERE send_id = %s"
        c.execute(update, ('{"n": 1e16}', send_id))
        c.execute(_STAMP, (_NOW, send_id))
        for changed in ('{"n":1e16}', '{"n": 10000000000000000}'):
            with pytest.raises(pgerr.CheckViolation) as refused:
                c.execute(update, (changed, send_id))
            assert refused.value.diag.message_primary == (
                "trg_mdj_stamp_once: machine_drain_journal.payload is write-once"
            )
        with pytest.raises(pgerr.CheckViolation):
            c.execute(_STAMP, (None, send_id))
        stored = c.execute(
            "SELECT payload::text, replayed_at FROM machine_drain_journal WHERE send_id = %s",
            (send_id,),
        ).fetchone()
    assert stored == ('{"n": 1e16}', _NOW)


def _dump(pg: PostgresContainer, name: str) -> list[str]:
    """`pg_dump --schema-only` inside the container (the server's own client); a newer client's
    `\\restrict` key lines are random per dump."""
    code, out = pg.exec(["pg_dump", "-U", pg.username, "-d", name, "--schema-only"])
    assert code == 0, out.decode(errors="replace")[-2000:]
    return [
        line
        for line in out.decode().splitlines()
        if not line.startswith(("\\restrict ", "\\unrestrict "))
    ]


def test_round_trip_on_an_empty_database_restores_the_parent_schema(pg: PostgresContainer) -> None:
    """C-5.5 (named revisions): up, down and up again; the dump after the downgrade equals the
    dump before the upgrade, 0033's function included, and the columns are `json` again."""
    dsn, name = _create(_url(pg))
    _migrate(dsn, "upgrade", _prev())
    before = _dump(pg, name)
    _migrate(dsn, "upgrade", _REV)
    _migrate(dsn, "downgrade", _prev())
    assert _dump(pg, name) == before
    assert any("snapshot jsonb NOT NULL" in line for line in before)
    assert any("NEW.payload IS DISTINCT FROM OLD.payload" in line for line in before)
    _migrate(dsn, "upgrade", _REV)
    with _conn(dsn) as c:
        assert _types(c) == [(table, column, "json") for table, column in _COLUMNS]


async def _insert(dsn: str, name: str, rows: list[dict[str, Any]]) -> None:
    """`rows` into `name` in one executemany, through `db.models` over asyncpg."""
    engine = create_async_engine(dsn.replace("postgresql+psycopg", "postgresql+asyncpg"))
    try:
        async with engine.begin() as conn:
            await conn.execute(sa.insert(getattr(models, name)), rows)
    finally:
        await engine.dispose()


def test_a_row_with_no_fault_binds_sql_null_beside_a_fault_row(pg: PostgresContainer) -> None:
    """`fault = None` through `db.models` binds SQL NULL (`none_as_null`), so `me_fault_phase`
    accepts a commit row, in one executemany with a fault row: a store needs no `sa.null()`."""
    entity = str(uuid.uuid4())
    fault_row = _rows(entity)["machine_events"]
    commit_row = fault_row | {"phase": "commit", "fault": None, "row_hash": uuid.uuid4().hex * 2}
    asyncio.run(_insert(_url(pg), "machine_events", [commit_row, fault_row]))
    with _conn(_url(pg)) as c:
        got = c.execute(
            "SELECT phase, fault IS NULL FROM machine_events WHERE entity_id = %s ORDER BY phase",
            (entity,),
        ).fetchall()
    assert got == [("commit", True), ("fault", False)]


@pytest.mark.parametrize("name", list(dict.fromkeys(table for table, _ in _COLUMNS)))
def test_a_populated_database_refuses_the_downgrade(pg: PostgresContainer, name: str) -> None:
    """0033's guard (C-5.2): one row in any of the three tables refuses the downgrade, naming the
    table and never a value, because the cast back to `jsonb` would re-render its sealed numbers
    for good. Nothing moves: the version, the `json` types and the row's text stay."""
    dsn, _ = _create(_url(pg), _TEMPLATE)
    entity = str(uuid.uuid4())
    asyncio.run(_insert(dsn, name, [_rows(entity)[name]]))
    column = next(column for table, column in _COLUMNS if table == name)
    stored = sql.SQL("SELECT {}::text FROM {} WHERE entity_id = %s").format(
        sql.Identifier(column), sql.Identifier(name)
    )
    with _conn(dsn) as c:
        before = _one(c, stored.as_string(c), entity)
        head = _one(c, "SELECT version_num FROM alembic_version")  # not always this revision
        refused = _alembic(dsn, "downgrade", _prev())
        assert refused.returncode != 0
        assert f"machine_persistence_json downgrade refused: {name} holds rows;" in refused.stderr
        assert "1e+16" in before and "1e+16" not in refused.stderr
        assert _one(c, "SELECT version_num FROM alembic_version") == head
        assert _types(c) == [(table, column, "json") for table, column in _COLUMNS]
        assert _one(c, stored.as_string(c), entity) == before
