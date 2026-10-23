"""E42-Q01 (#962): the 10 M-row audit dataset's loader (AUDIT-10M): its batches, its SQL and its
refusals, over a scripted connection. No test loads 10 M rows; the SQL itself is E42-K01's and runs
in `tests/integration/audit/test_query_plan_spike.py`.
"""

from __future__ import annotations

from typing import Any

import psycopg
import pytest

from bench.audit_index.ci_spike import seed_users_sql
from candleviewer.observability.redaction import redact_text
from tests.fixtures.admin.audit_10m import BATCH, ROWS, batches, load_audit_10m, statements
from tests.fixtures.admin.seed import FixtureCheckError, FixtureRefused


def test_the_batches_cover_every_row_once_in_order() -> None:
    assert batches(10, 4) == [(1, 4), (5, 8), (9, 10)]


def test_the_default_dataset_is_ten_million_rows() -> None:
    assert sum(last - first + 1 for first, last in batches()) == ROWS == 10_000_000


@pytest.mark.parametrize(("rows", "size"), [(0, BATCH), (ROWS, 0)])
def test_an_empty_dataset_or_batch_is_refused(rows: int, size: int) -> None:
    with pytest.raises(ValueError, match="at least 1"):
        batches(rows, size)


def test_the_load_seeds_then_adds_its_users_then_inserts_once_per_batch() -> None:
    sql = statements(10, 4, seed=0.5)
    assert sql[:2] == ["SELECT setseed(0.5)", seed_users_sql()]
    assert [s.startswith("INSERT INTO audit_log") for s in sql[2:]] == [True] * 3


def test_a_chained_load_leaves_the_hashes_to_the_trigger() -> None:
    assert not any("entry_hash" in s for s in statements(10, 4))
    assert all("entry_hash" in s for s in statements(10, 4, chained=False)[2:])


@pytest.mark.parametrize("seed", [-1.5, 1.01])
def test_a_seed_outside_setseeds_range_is_refused(seed: float) -> None:
    with pytest.raises(ValueError, match=r"\[-1, 1\]"):
        statements(10, 4, seed=seed)


def test_no_load_statement_is_secret_shaped() -> None:
    assert [s for s in statements(10, 4) if redact_text(s) != s] == []


class _Conn:
    """A psycopg connection that answers the name and the dataset's row count, and keeps every
    statement sent; an insert adds its batch's rows."""

    def __init__(self, database: str, present: int, sent: list[str]) -> None:
        self.database, self.present, self.sent = database, present, sent

    def __enter__(self) -> _Conn:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def close(self) -> None:
        return None

    def execute(self, sql: str) -> Any:
        self.sent.append(sql)
        if sql.startswith("INSERT INTO audit_log"):
            self.present += 4 if "generate_series(1::bigint" in sql else 0
        answer = self.database if sql == "SELECT current_database()" else self.present
        return _Row((answer,))


class _Row:
    def __init__(self, row: tuple[Any, ...]) -> None:
        self._row = row

    def fetchone(self) -> tuple[Any, ...]:
        return self._row


def _script(monkeypatch: pytest.MonkeyPatch, database: str = "test", present: int = 0) -> list[str]:
    sent: list[str] = []

    def connect(dsn: str, autocommit: bool) -> _Conn:
        return _Conn(database, present, sent)

    monkeypatch.setattr(psycopg, "connect", connect)
    return sent


def test_a_database_not_named_for_tests_is_refused_before_anything_else(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent = _script(monkeypatch, database="candleviewer")
    with pytest.raises(FixtureRefused):
        load_audit_10m("postgresql:///candleviewer", 4, 4)
    assert sent == ["SELECT current_database()"]


def test_a_second_load_finds_the_dataset_and_writes_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent = _script(monkeypatch, present=4)
    assert load_audit_10m("postgresql:///test", 4, 4) == 4
    assert [s for s in sent if not s.startswith("SELECT")] == []


def test_a_partly_loaded_dataset_is_refused_and_named(monkeypatch: pytest.MonkeyPatch) -> None:
    sent = _script(monkeypatch, present=3)
    with pytest.raises(FixtureCheckError, match="3 of its 4 rows are present"):
        load_audit_10m("postgresql:///test", 4, 4)
    assert [s for s in sent if not s.startswith("SELECT")] == []


def test_a_bulk_load_turns_the_chain_trigger_off_for_the_load_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent = _script(monkeypatch)
    assert load_audit_10m("postgresql:///test", 4, 4, chained=False) == 4
    toggles = [s for s in sent if s.startswith("ALTER TABLE")]
    assert toggles == [
        "ALTER TABLE audit_log DISABLE TRIGGER trg_audit_chain",
        "ALTER TABLE audit_log ENABLE TRIGGER trg_audit_chain",
    ]
    assert sent.index(toggles[1]) > max(i for i, s in enumerate(sent) if "INSERT" in s)


def test_a_load_that_leaves_another_count_is_named(monkeypatch: pytest.MonkeyPatch) -> None:
    _script(monkeypatch)
    with pytest.raises(FixtureCheckError, match="holds 4 of its rows, not 8"):
        load_audit_10m("postgresql:///test", 8, 4)
