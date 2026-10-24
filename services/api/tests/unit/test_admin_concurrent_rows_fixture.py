"""E42-Q01 (#962): AUDIT-CONCURRENT: each round races one insert through the app's path against one
raw insert, the two end up alternating in pairs, a part-loaded set is refused, a database not named
for tests is refused on the pool and on the psycopg connection, and the check names a spoiled world.
The pool is an in-memory `audit_log` and the raw connection a fake (no Docker); the app's verify is
a stand-in. The Postgres half is `tests/integration/admin/test_admin_fixture_b4b_pg.py`.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Sequence
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import psycopg
import pytest

from candleviewer.audit.actions import AUDIT_ACTIONS
from tests.fixtures.admin import concurrent_rows
from tests.fixtures.admin.concurrent_rows import (
    ACTION,
    APP_ACTOR,
    RAW_ACTOR,
    ROUNDS,
    check_concurrent_rows,
    seed_concurrent_rows,
)
from tests.fixtures.admin.seed import FixtureCheckError, FixtureRefused
from tests.unit._admin_fake_db import FakeAuditRows, FakeDb, patch_audit_session

_DSN = "postgresql+asyncpg://fixture@127.0.0.1:1/test"  # nothing connects: the fakes answer
_NOW = datetime(2026, 10, 23, 19, 0, tzinfo=UTC)
_OK = SimpleNamespace(verified=True, entries_checked=2 * ROUNDS, first_bad_id=None)


class _Raw:
    """A psycopg connection in autocommit mode to the fake database `name`: a raw insert adds its
    row to the fake `audit_log`. With a `meet`, each insert first waits for the app's insert of
    its round, which waits for this one: concurrent inserts meet, sequential ones time out."""

    def __init__(self, name: str, db: FakeDb, meet: threading.Barrier | None = None) -> None:
        self.statements: list[str] = []
        self.closed = False
        self._name, self._db, self._meet = name, db, meet

    def execute(self, sql: str, params: Sequence[Any] = ()) -> SimpleNamespace:
        self.statements.append(sql)
        if "current_database" in sql:
            return SimpleNamespace(fetchone=lambda: (self._name,))
        assert sql.startswith("INSERT INTO audit_log"), sql
        if self._meet is not None:
            self._meet.wait()
        rows = self._db.tables.setdefault("audit_log", [])
        rows.append({"id": len(rows) + 1, "actor_label": params[1], "action": params[2]})
        return SimpleNamespace(fetchone=lambda: None)

    def close(self) -> None:
        self.closed = True


class _Meeting(FakeAuditRows):
    """The app's path: each insert waits for the raw insert of its round, which waits for it."""

    def __init__(self, db: FakeDb, meet: threading.Barrier) -> None:
        super().__init__(db)
        self._meet = meet

    async def insert(self, record: dict[str, Any]) -> None:
        await asyncio.to_thread(self._meet.wait)
        await super().insert(record)


class _Verify:
    """The app's `AuditQueryService.verify`, answering `answer` and keeping the ranges asked."""

    def __init__(self, answer: Any, asked: list[tuple[int, int]]) -> None:
        self._answer, self._asked = answer, asked

    async def verify(self, *, from_id: int, to_id: int) -> Any:
        self._asked.append((from_id, to_id))
        return self._answer

    def close(self) -> None:
        return None


def _world(
    monkeypatch: pytest.MonkeyPatch, db: FakeDb, raw: _Raw, verify: Any = _OK
) -> list[tuple[int, int]]:
    """The seed's pool, rows, raw connection and verify are fakes; the ranges verify is asked."""
    asked: list[tuple[int, int]] = []
    patch_audit_session(monkeypatch, db)
    monkeypatch.setattr(concurrent_rows, "SqlAlchemyAuditRepository", FakeAuditRows)
    monkeypatch.setattr(concurrent_rows, "AuditQueryService", lambda _r: _Verify(verify, asked))
    monkeypatch.setattr(psycopg, "connect", lambda *_a, **_k: raw)
    return asked


def test_the_rounds_write_a_thousand_rows_for_two_registered_connections() -> None:
    assert 2 * ROUNDS == 1000
    assert len({APP_ACTOR, RAW_ACTOR}) == 2
    assert ACTION in AUDIT_ACTIONS


async def test_each_round_races_the_apps_insert_against_the_raw_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A barrier of two, which each side reaches inside its own insert: if a round ran one insert
    and then the other, the first would wait in vain and the barrier would break."""
    db, meet = FakeDb(), threading.Barrier(2, timeout=10)
    _world(monkeypatch, db, _Raw("test", db, meet))
    monkeypatch.setattr(concurrent_rows, "SqlAlchemyAuditRepository", lambda _r: _Meeting(db, meet))
    await seed_concurrent_rows(_DSN, now=_NOW)
    assert len(db.tables["audit_log"]) == 2 * ROUNDS


async def test_the_seed_writes_500_rows_from_each_connection_and_answers_their_range(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = FakeDb()
    raw = _Raw("test", db)
    asked = _world(monkeypatch, db, raw)
    assert await seed_concurrent_rows(_DSN, now=_NOW) == (1, 2 * ROUNDS)
    actors = [row["actor_label"] for row in db.tables["audit_log"]]
    assert (actors.count(APP_ACTOR), actors.count(RAW_ACTOR)) == (ROUNDS, ROUNDS)
    assert [set(actors[i : i + 2]) for i in range(0, 2 * ROUNDS, 2)] == [
        {APP_ACTOR, RAW_ACTOR}
    ] * ROUNDS
    assert raw.closed
    await check_concurrent_rows(_DSN)
    assert asked == [(1, 2 * ROUNDS)]


async def test_a_second_seed_writes_nothing_and_answers_the_same_range(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = FakeDb()
    raw = _Raw("test", db)
    _world(monkeypatch, db, raw)
    first = await seed_concurrent_rows(_DSN, now=_NOW)
    assert await seed_concurrent_rows(_DSN, now=_NOW) == first
    assert len(db.tables["audit_log"]) == 2 * ROUNDS


async def test_a_naive_now_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    db = FakeDb()
    _world(monkeypatch, db, _Raw("test", db))
    with pytest.raises(ValueError, match="timezone-aware"):
        await seed_concurrent_rows(_DSN, now=_NOW.replace(tzinfo=None))


async def test_a_part_of_the_rows_is_refused_and_nothing_more_is_written(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    present = [{"id": i, "actor_label": a} for i, a in enumerate([APP_ACTOR] * 3 + [RAW_ACTOR] * 2)]
    db = FakeDb(audit_log=present)
    _world(monkeypatch, db, _Raw("test", db))
    with pytest.raises(FixtureCheckError, match="3 app and 2 raw rows are present, not 500 each"):
        await seed_concurrent_rows(_DSN, now=_NOW)
    assert len(db.tables["audit_log"]) == 5


@pytest.mark.parametrize(
    ("database", "pool"),
    [("candleviewer", "test"), ("test", "candleviewer")],
    ids=["the-psycopg-connection", "the-pool"],
)
async def test_a_database_not_named_for_tests_is_refused_on_each_connection_before_a_row(
    monkeypatch: pytest.MonkeyPatch, database: str, pool: str
) -> None:
    db = FakeDb(pool)
    raw = _Raw(database, db)
    _world(monkeypatch, db, raw)
    with pytest.raises(FixtureRefused):
        await seed_concurrent_rows(_DSN, now=_NOW)
    assert db.tables.get("audit_log", []) == []  # no row, from either connection
    if pool == "candleviewer":  # the pool is refused first: its one statement is the name's
        assert (db.shapes, raw.statements) == (["SELECT current_database()"], [])
    else:
        assert raw.closed and len(raw.statements) == 1  # the name read, then closed


def _rows(*actors: str) -> list[dict[str, Any]]:
    return [{"id": 10 + i, "actor_label": who} for i, who in enumerate(actors)]


_PAIR = (APP_ACTOR, RAW_ACTOR)
_ALTERNATING = [who for _ in range(ROUNDS) for who in _PAIR]
_SPOILS: list[tuple[str, list[dict[str, Any]], Any, str]] = [
    ("a row missing", _rows(*_ALTERNATING[1:]), _OK, "the rows are not 500 from each connection"),
    ("an extra app row", _rows(*_ALTERNATING, APP_ACTOR), _OK, "not 500 from each connection"),
    (
        "all the app rows first",
        _rows(*[APP_ACTOR] * ROUNDS, *[RAW_ACTOR] * ROUNDS),
        _OK,
        "the two connections' rows do not alternate in pairs",
    ),
    (
        "a break found",
        _rows(*_ALTERNATING),
        SimpleNamespace(verified=False, entries_checked=7, first_bad_id=17),
        "verified False, checked 7, first bad id 17",
    ),
    (
        "fewer entries checked",
        _rows(*_ALTERNATING),
        SimpleNamespace(verified=True, entries_checked=999, first_bad_id=None),
        "verified True, checked 999",
    ),
]


async def test_the_check_passes_the_world_and_verifies_from_its_first_id_to_its_last(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = FakeDb(audit_log=_rows(*_ALTERNATING))
    asked = _world(monkeypatch, db, _Raw("test", db))
    await check_concurrent_rows(_DSN)
    assert asked == [(10, 10 + 2 * ROUNDS - 1)]


@pytest.mark.parametrize(
    ("rows", "verify", "named"), [c[1:] for c in _SPOILS], ids=[c[0] for c in _SPOILS]
)
async def test_the_check_names_a_spoiled_world(
    monkeypatch: pytest.MonkeyPatch, rows: list[dict[str, Any]], verify: Any, named: str
) -> None:
    db = FakeDb(audit_log=rows)
    _world(monkeypatch, db, _Raw("test", db), verify)
    with pytest.raises(FixtureCheckError, match=named):
        await check_concurrent_rows(_DSN)


async def test_the_check_refuses_a_database_not_named_for_tests_before_a_verify(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = FakeDb("candleviewer", audit_log=_rows(*_ALTERNATING))
    asked = _world(monkeypatch, db, _Raw("test", db))
    with pytest.raises(FixtureRefused):
        await check_concurrent_rows(_DSN)
    assert (db.shapes, asked) == (["SELECT current_database()"], [])
