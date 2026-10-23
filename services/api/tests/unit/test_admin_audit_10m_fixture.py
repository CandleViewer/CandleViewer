"""E42-Q01 (#962): the 10 M-row audit dataset's loader (AUDIT-10M): its batches, its SQL and its
guards, over a fake Postgres. No test loads 10 M rows. The SQL is E42-K01's; the loader runs it, in
both modes, on a real server in `tests/integration/admin/test_admin_audit_10m_pg.py`.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

import psycopg
import pytest

from bench.audit_index.ci_spike import USERS, generate_rows_sql, seed_users_sql
from candleviewer.observability.redaction import redact_text
from tests.fixtures.admin.audit_10m import (
    BATCH,
    OWN_LABEL,
    ROWS,
    batches,
    load_audit_10m,
    statements,
)
from tests.fixtures.admin.seed import FixtureCheckError, FixtureRefused

_DSN = "postgresql://unit.invalid/test"  # unroutable: nothing connects, the fake answers
_NAME = "SELECT current_database()"
_DISABLE = "ALTER TABLE audit_log DISABLE TRIGGER trg_audit_chain"
_ENABLE = "ALTER TABLE audit_log ENABLE TRIGGER trg_audit_chain"
_QUIET = ("SELECT pg_advisory_lock", "SELECT setseed", "INSERT INTO users", "ANALYZE")
_BOUNDS = re.compile(r"generate_series\((\d+)::bigint, (\d+)::bigint\)")
#: A statement's kind is the first of these whose mark it holds; the name read, the lock and the
#: counts hold none.
_KINDS = (
    ("guard", "tgenabled"),
    ("disable", "DISABLE"),
    ("enable", "ENABLE"),
    ("seed", "setseed"),
    ("users", "INSERT INTO users"),
    ("insert", "INSERT INTO audit_log"),
    ("analyze", "ANALYZE"),
    *((mark, mark) for mark in ("BEGIN", "COMMIT", "ROLLBACK")),
)
_MODES = pytest.mark.parametrize("chained", [True, False], ids=["chained", "bulk"])


def test_the_batches_cover_every_row_once_in_order_from_zero_as_k01_numbers_them() -> None:
    assert batches(10, 4) == [(0, 3), (4, 7), (8, 9)]


def test_the_default_dataset_is_ten_million_rows_numbered_zero_to_the_last() -> None:
    assert sum(last - first + 1 for first, last in batches()) == ROWS == 10_000_000
    assert (batches()[0][0], batches()[-1][1]) == (0, ROWS - 1)


@pytest.mark.parametrize(("rows", "size"), [(0, BATCH), (ROWS, 0)])
def test_an_empty_dataset_or_batch_is_refused(rows: int, size: int) -> None:
    with pytest.raises(ValueError, match="at least 1"):
        batches(rows, size)


def test_the_load_adds_its_users_then_inserts_once_per_batch() -> None:
    sql = statements(10, 4)
    assert sql[0] == seed_users_sql()
    assert [s.startswith("INSERT INTO audit_log") for s in sql[1:]] == [True] * 3


def test_a_chained_load_leaves_the_hashes_to_the_trigger() -> None:
    assert not any("entry_hash" in s for s in statements(10, 4))
    assert all("entry_hash" in s for s in statements(10, 4, chained=False)[1:])


@pytest.mark.parametrize("seed", [-1.5, 1.01, float("nan")])
def test_a_seed_outside_setseeds_range_is_refused_before_any_connection(seed: float) -> None:
    with pytest.raises(ValueError, match=r"\[-1, 1\]"):
        load_audit_10m(_DSN, 4, 4, seed=seed)


@_MODES
def test_no_load_statement_is_secret_shaped(chained: bool) -> None:
    assert [s for s in statements(10, 4, chained=chained) if redact_text(s) != s] == []


@pytest.mark.parametrize(
    ("sql", "fragment"),
    [
        (generate_rows_sql(0, 3, 4, True), "'user_' || lpad(u::text, 2, '0')"),
        (generate_rows_sql(0, 3, 4, True), f"(g * 7919) % {USERS} AS u"),
        (seed_users_sql(), "'user_' || lpad(g::text, 2, '0')"),
        (seed_users_sql(), f"generate_series(0, {USERS - 1})"),
    ],
)
def test_k01s_sql_still_writes_the_labels_the_own_rows_predicate_counts(
    sql: str, fragment: str
) -> None:
    assert fragment in sql


def test_the_own_rows_predicate_counts_k01s_labels_and_no_other_seeds() -> None:
    two_digit = {f"user_{n:02d}" for n in range(100)}
    assert {label for label in two_digit if re.search(OWN_LABEL, label)} == {
        f"user_{n:02d}" for n in range(USERS)
    }
    others = ["user_5", "user_100", "xuser_01", "user_01x", "fx-owner", "fixture-chain"]
    assert [label for label in others if re.search(OWN_LABEL, label)] == []


@dataclass
class _Db:
    """What the fake database holds: the dataset's rows, how many of them carry the genesis
    `prev_hash`, and the chain trigger's `tgenabled`."""

    present: int = 0
    genesis: int = 0
    tgenabled: str = "O"


class _Cursor:
    def __init__(self, *row: Any) -> None:
        self._row = row

    def fetchone(self) -> tuple[Any, ...]:
        return self._row


class _Conn:
    """A psycopg connection in autocommit mode to the fake database `name`; every statement sent is
    kept, with its parameters, and so is each `transaction()`'s `BEGIN` and its `COMMIT` or
    `ROLLBACK`: the block commits when it ends and is rolled back when it raises. A statement
    holding `dies_on` raises `error`. By default that is a lost connection: it and every later
    statement raise, and the server rolls the open transaction back. Another error, a cancellation
    say, leaves the connection alive. An insert whose first bound is in `drops` adds no rows. When
    `stuck`, the first insert turns the chain trigger off behind the loader's back, and
    `ENABLE TRIGGER` cannot turn it on."""

    def __init__(
        self,
        name: str,
        db: _Db,
        *,
        dies_on: str | None = None,
        error: BaseException | None = None,
        drops: frozenset[int] = frozenset(),
        stuck: bool = False,
    ) -> None:
        self.sent: list[str] = []
        self.params: list[Sequence[Any] | None] = []
        self.closed = False
        self._name, self._db, self._dies_on = name, db, dies_on
        self._error, self._drops, self._stuck = error, drops, stuck
        self._open: _Db | None = None
        self._dead = False

    def __enter__(self) -> _Conn:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def close(self) -> None:
        self.closed = True

    def _log(self, sql: str, params: Sequence[Any] | None = None) -> None:
        self.sent.append(sql)
        self.params.append(params)

    def execute(self, sql: str, params: Sequence[Any] | None = None) -> _Cursor:
        self._log(sql, params)
        if self._dead or (self._dies_on is not None and self._dies_on in sql):
            self._dead = self._error is None  # only a lost connection stays lost
            raise self._error or psycopg.OperationalError("the connection was lost")
        db = self._db if self._open is None else self._open
        if sql == _NAME:
            return _Cursor(self._name)
        if sql.startswith("SELECT count(*)"):
            return _Cursor(db.present, db.genesis)
        if "tgenabled" in sql:
            return _Cursor(db.tgenabled)
        if sql == _DISABLE:
            db.tgenabled = "D"
        elif sql == _ENABLE:
            db.tgenabled = "D" if self._stuck else "O"
        elif sql.startswith("INSERT INTO audit_log"):
            bounds = _BOUNDS.search(sql)
            assert bounds is not None, "an insert whose batch the fake cannot read"
            first, last = (int(n) for n in bounds.groups())
            if first not in self._drops:
                db.present += last - first + 1
                db.genesis += last - first + 1 if "entry_hash" in sql else 0  # bulk: placeholders
                db.tgenabled = "D" if self._stuck else db.tgenabled
        elif not sql.startswith(_QUIET):
            raise AssertionError(f"a statement the fake does not know: {sql}")
        return _Cursor()

    @contextmanager
    def transaction(self) -> Iterator[None]:
        opened = self._open = _Db(**vars(self._db))
        self._log("BEGIN")
        try:
            yield
        except BaseException:
            self._log("ROLLBACK")
            raise
        else:
            vars(self._db).update(vars(opened))
            self._log("COMMIT")
        finally:
            self._open = None


def _script(
    monkeypatch: pytest.MonkeyPatch, db: _Db | None = None, database: str = "test", **faults: Any
) -> _Conn:
    conn = _Conn(database, _Db() if db is None else db, **faults)
    monkeypatch.setattr(psycopg, "connect", lambda dsn, autocommit: conn)
    return conn


def _writes(conn: _Conn) -> list[str]:
    reads = ("SELECT", "BEGIN", "ROLLBACK")
    return [s for s in conn.sent if not s.startswith(reads)]


def _order(conn: _Conn) -> list[str]:
    """The kinds of the statements sent, in order, the transaction's boundaries among them."""
    kinds = [next((kind for kind, mark in _KINDS if mark in s), "") for s in conn.sent]
    return [kind for kind in kinds if kind]


def test_a_database_not_named_for_tests_is_refused_before_anything_else(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _script(monkeypatch, database="candleviewer")
    with pytest.raises(FixtureRefused):
        load_audit_10m(_DSN, 4, 4)
    assert (conn.sent, conn.closed) == ([_NAME], True)


def test_the_advisory_lock_comes_after_the_name_read_and_before_the_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent = _script(monkeypatch).sent
    load_audit_10m(_DSN, 4, 4)
    lock = sent.index("SELECT pg_advisory_lock(%s)")
    assert sent.index(_NAME) < lock < next(i for i, s in enumerate(sent) if "count(*)" in s)


def test_the_seed_is_bound_and_never_formatted_into_the_sql(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _script(monkeypatch)
    load_audit_10m(_DSN, 4, 4, seed=0.123456)  # a value K01's own literals never hold
    assert conn.params[conn.sent.index("SELECT setseed(%s)")] == (0.123456,)
    assert not any("0.123456" in s for s in conn.sent)


@pytest.mark.parametrize(
    ("chained", "genesis"),
    [(True, 0), (True, 1), (False, 4)],
    ids=["chained", "chained-first", "bulk"],
)
def test_a_second_load_in_the_same_mode_finds_the_dataset_and_writes_nothing(
    monkeypatch: pytest.MonkeyPatch, chained: bool, genesis: int
) -> None:
    conn = _script(monkeypatch, _Db(present=4, genesis=genesis))
    assert load_audit_10m(_DSN, 4, 4, chained=chained) == 4
    assert _writes(conn) == []


@pytest.mark.parametrize(
    ("chained", "genesis", "loaded"),
    [(True, 4, "bulk"), (False, 0, "chained"), (False, 1, "chained")],
    ids=["bulk-then-chained", "chained-then-bulk", "chained-first-then-bulk"],
)
def test_a_second_load_in_the_other_mode_is_refused_naming_both_and_writes_nothing(
    monkeypatch: pytest.MonkeyPatch, chained: bool, genesis: int, loaded: str
) -> None:
    conn = _script(monkeypatch, _Db(present=4, genesis=genesis))
    asked = "chained" if chained else "bulk"
    with pytest.raises(FixtureCheckError, match=f"loaded {loaded}, and this call asks for {asked}"):
        load_audit_10m(_DSN, 4, 4, chained=chained)
    assert _writes(conn) == []


def test_a_partly_loaded_dataset_is_refused_and_named(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = _script(monkeypatch, _Db(present=3))
    with pytest.raises(FixtureCheckError, match="3 of its 4 rows are present"):
        load_audit_10m(_DSN, 4, 4)
    assert _writes(conn) == []


_ORDER = {
    True: ["guard", "seed", "users", "insert", "insert", "guard", "analyze"],
    False: [
        *["BEGIN", "guard", "disable", "seed", "users", "insert", "insert", "enable", "guard"],
        *["COMMIT", "analyze"],
    ],
}


@_MODES
def test_the_statements_run_in_order_and_only_a_bulk_load_toggles_the_trigger_in_a_transaction(
    monkeypatch: pytest.MonkeyPatch, chained: bool
) -> None:
    conn = _script(monkeypatch)
    assert load_audit_10m(_DSN, 8, 4, chained=chained) == 8
    assert _order(conn) == _ORDER[chained]


@pytest.mark.parametrize(
    "dies_on", ["generate_series(4::bigint", _ENABLE], ids=["an-insert", "the-enable"]
)
def test_a_bulk_load_that_fails_leaves_no_row_and_the_trigger_on_and_the_error_propagates(
    monkeypatch: pytest.MonkeyPatch, dies_on: str
) -> None:
    db = _Db()
    _script(monkeypatch, db, dies_on=dies_on)
    with pytest.raises(psycopg.OperationalError, match="connection was lost"):
        load_audit_10m(_DSN, 8, 4, chained=False)
    assert db == _Db()


def test_a_cancelled_bulk_load_rolls_back_never_commits_and_propagates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _Db()
    conn = _script(monkeypatch, db, dies_on="generate_series(4::bigint", error=KeyboardInterrupt())
    with pytest.raises(KeyboardInterrupt):
        load_audit_10m(_DSN, 8, 4, chained=False)
    assert (db, "COMMIT" in conn.sent, "ROLLBACK" in conn.sent) == (_Db(), False, True)


@pytest.mark.parametrize(
    ("chained", "present"),
    [(True, 0), (False, 0), (False, 4)],
    ids=["chained-load", "bulk-load", "second-run"],
)
def test_a_trigger_found_off_is_a_check_error_with_its_recovery_and_writes_nothing(
    monkeypatch: pytest.MonkeyPatch, chained: bool, present: int
) -> None:
    conn = _script(monkeypatch, _Db(present, present, "D"))
    with pytest.raises(FixtureCheckError, match=f"enable it with: {_ENABLE}"):
        load_audit_10m(_DSN, 4, 4, chained=chained)
    assert _writes(conn) == []


@_MODES
def test_a_trigger_a_load_leaves_off_is_a_check_error(
    monkeypatch: pytest.MonkeyPatch, chained: bool
) -> None:
    _script(monkeypatch, stuck=True)
    with pytest.raises(FixtureCheckError, match="trg_audit_chain is not enabled"):
        load_audit_10m(_DSN, 4, 4, chained=chained)


def test_a_bulk_load_that_finds_the_trigger_off_before_its_commit_commits_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _Db()
    conn = _script(monkeypatch, db, stuck=True)
    with pytest.raises(FixtureCheckError):
        load_audit_10m(_DSN, 4, 4, chained=False)
    assert (db, "COMMIT" in conn.sent) == (_Db(), False)


def test_a_load_that_leaves_another_count_is_named(monkeypatch: pytest.MonkeyPatch) -> None:
    _script(monkeypatch, drops=frozenset({4}))  # the second batch is dropped
    with pytest.raises(FixtureCheckError, match="holds 4 of its rows, not 8"):
        load_audit_10m(_DSN, 8, 4)
