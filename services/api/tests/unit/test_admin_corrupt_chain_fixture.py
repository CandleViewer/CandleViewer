"""E42-Q01 (#962): the corrupted-chain fixture's constants are synthetic and its victim is its own;
a refusal writes nothing, and the alteration leaves the append-only trigger on.

A fake connection, a fake pool and a fake writer stand in for Postgres, so that each guard of the
fixture is shown to fail without its code. The database half, through `POST /admin/audit/verify`, is
`tests/integration/admin/test_admin_corrupt_chain_pg.py`.
"""

from __future__ import annotations

import copy
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import psycopg
import pytest

from candleviewer.audit.actions import AUDIT_ACTIONS
from candleviewer.observability.redaction import redact_text
from tests.fixtures.admin import corrupt_chain
from tests.fixtures.admin.corrupt_chain import (
    ACTION,
    ACTOR,
    ENTRIES,
    FORGED,
    VICTIM_POSITION,
    seed_corrupted_chain,
)
from tests.fixtures.admin.seed import FixtureCheckError, FixtureRefused

_DSN = "postgresql+asyncpg://fixture@127.0.0.1:1/test"  # nothing connects: the fakes answer


@dataclass
class _Data:
    """What the fake database holds: the fixture's entries (id to reason) and `tgenabled`."""

    entries: dict[int, str | None]
    tgenabled: str = "O"


def _data(*reasons: str | None) -> _Data:
    """Entries whose ids are not consecutive, as the chain's are (0045)."""
    return _Data({100 + 2 * i: reason for i, reason in enumerate(reasons)})


def _chain(altered: bool = False) -> _Data:
    return _data(*[FORGED if altered and i == VICTIM_POSITION else None for i in range(ENTRIES)])


class _Cursor:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self._rows = rows

    def fetchone(self) -> tuple[Any, ...] | None:
        return self._rows[0] if self._rows else None

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self._rows


class _Conn:
    """A psycopg connection in autocommit mode to the fake database `name`. A statement outside
    `transaction()` commits at once; one inside commits with its block, and is rolled back when
    the block raises. A statement holding `dies_on` kills the connection: it and every later one
    raise, as on a lost connection, whose open transaction the server rolls back."""

    def __init__(self, name: str, data: _Data, dies_on: str | None = None) -> None:
        self.statements: list[str] = []
        self._name, self._data, self._dies_on = name, data, dies_on
        self._open: _Data | None = None
        self._dead = False

    def __enter__(self) -> _Conn:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def close(self) -> None:
        return None

    def execute(self, sql: str, params: Sequence[Any] = ()) -> _Cursor:
        self.statements.append(sql)
        if self._dead or (self._dies_on is not None and self._dies_on in sql):
            self._dead = True
            raise psycopg.OperationalError("the connection was lost")
        data = self._data if self._open is None else self._open
        if "current_database" in sql:
            return _Cursor([(self._name,)])
        if "actor_label" in sql:
            return _Cursor(sorted(data.entries.items()))
        if "tgenabled" in sql:
            return _Cursor([(data.tgenabled,)])
        if "DISABLE TRIGGER" in sql:
            data.tgenabled = "D"
        elif "ENABLE TRIGGER" in sql:
            data.tgenabled = "O"
        elif sql.startswith("UPDATE audit_log SET reason"):
            data.entries[params[1]] = params[0]
        else:
            raise AssertionError(f"a statement the fake does not know: {sql}")
        return _Cursor([])

    @contextmanager
    def transaction(self) -> Iterator[None]:
        opened = self._open = copy.deepcopy(self._data)
        try:
            yield
            self._data.entries, self._data.tgenabled = opened.entries, opened.tgenabled
        finally:
            self._open = None


class _Pool:
    """The writer's relational repository, its engine and one connection from it in one object:
    all the fixture asks of them is `current_database()`, which answers `database`."""

    def __init__(self, database: str) -> None:
        self.engine = self
        self._database = database

    def connect(self) -> _Pool:
        return self

    async def __aenter__(self) -> _Pool:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None

    async def execute(self, _statement: object) -> SimpleNamespace:
        return SimpleNamespace(scalar_one=lambda: self._database)

    async def dispose(self) -> None:
        return None


class _Writer:
    """`AuditWriter` as the fixture uses it: an emitted entry lands in the fake database at once."""

    def __init__(self, world: _World) -> None:
        self._world = world

    async def start(self) -> None:
        return None

    async def emit(self, action: str, *, actor_label: str, object_id: str | None = None) -> None:
        entries = self._world.data.entries
        entries[max(entries, default=98) + 2] = None
        self._world.emitted.append((action, actor_label, object_id))

    async def flush(self, timeout_s: float) -> None:
        return None

    async def stop(self, grace_s: float = 5.0) -> None:
        return None


class _World:
    """The fake Postgres a seed meets: psycopg connections to the database `database`, the
    writer's pool to the database `pool`, `present` of the fixture's entries already in the chain,
    and what the seed built and emitted."""

    def __init__(
        self,
        monkeypatch: pytest.MonkeyPatch,
        *,
        database: str = "test",
        pool: str = "test",
        present: int = 0,
    ) -> None:
        self.data = _data(*[None] * present)
        self.built = 0
        self.emitted: list[tuple[str, str, str | None]] = []

        def writer(_repository: object, _wal_path: str) -> _Writer:
            self.built += 1
            return _Writer(self)

        monkeypatch.setattr(psycopg, "connect", lambda *_a, **_k: _Conn(database, self.data))
        monkeypatch.setattr(corrupt_chain, "SqlAlchemyRelationalRepository", lambda _d: _Pool(pool))
        monkeypatch.setattr(
            corrupt_chain, "SqlAlchemyAuditRepository", lambda relational: relational
        )
        monkeypatch.setattr(corrupt_chain, "AuditWriter", writer)


def _alter(conn: Any) -> int:
    return corrupt_chain._alter(conn)


@pytest.mark.parametrize("value", [ACTOR, ACTION, FORGED])
def test_no_corrupted_chain_value_is_secret_shaped(value: str) -> None:
    assert redact_text(value) == value


def test_the_victim_is_one_of_the_fixtures_own_entries() -> None:
    assert 0 <= VICTIM_POSITION < ENTRIES


def test_the_fixtures_entries_use_a_registered_action() -> None:
    assert ACTION in AUDIT_ACTIONS


_ELSEWHERE = pytest.mark.parametrize(
    ("database", "pool"),
    [("candleviewer", "test"), ("test", "candleviewer")],
    ids=["the-alteration-connection", "the-writers-pool"],
)


@_ELSEWHERE
async def test_a_seed_into_a_database_not_named_for_tests_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, database: str, pool: str
) -> None:
    _World(monkeypatch, database=database, pool=pool)
    with pytest.raises(FixtureRefused):
        await seed_corrupted_chain(_DSN, tmp_path)


@_ELSEWHERE
async def test_a_refused_seed_builds_no_writer_and_writes_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, database: str, pool: str
) -> None:
    world = _World(monkeypatch, database=database, pool=pool)
    with pytest.raises(FixtureRefused):
        await seed_corrupted_chain(_DSN, tmp_path)
    assert (world.built, world.emitted, world.data.entries) == (0, [], {})


@pytest.mark.parametrize("dies_on", ["UPDATE", "ENABLE TRIGGER"])
def test_an_alteration_that_fails_leaves_the_chain_and_its_trigger_as_they_were(
    dies_on: str,
) -> None:
    data = _chain()
    before = copy.deepcopy(data)
    with pytest.raises(psycopg.OperationalError):
        _alter(_Conn("test", data, dies_on))
    assert data == before


def test_an_alteration_leaves_the_append_only_trigger_enabled() -> None:
    data = _chain()
    _alter(_Conn("test", data))
    assert data.tgenabled == "O"


def test_a_trigger_found_disabled_is_a_fixture_check_error() -> None:
    data = _chain(altered=True)  # a second run: nothing to alter, so nothing re-enables the trigger
    data.tgenabled = "D"
    with pytest.raises(FixtureCheckError):
        _alter(_Conn("test", data))


def test_a_second_run_issues_no_statement_that_alters() -> None:
    conn = _Conn("test", _chain(altered=True))
    _alter(conn)
    assert [s for s in conn.statements if "TRIGGER" in s or s.startswith("UPDATE")] == []


def test_the_victim_is_the_fourth_entry() -> None:
    data = _chain()
    ids = sorted(data.entries)
    victim = _alter(_Conn("test", data))
    assert [i for i, reason in data.entries.items() if reason == FORGED] == [victim] == [ids[3]]


@pytest.mark.parametrize("present", [0, 3, ENTRIES])
async def test_only_the_missing_entries_are_written(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, present: int
) -> None:
    world = _World(monkeypatch, present=present)
    await seed_corrupted_chain(_DSN, tmp_path)
    written = [object_id for _action, _actor, object_id in world.emitted]
    assert written == [f"fixture-{i}" for i in range(present, ENTRIES)]
