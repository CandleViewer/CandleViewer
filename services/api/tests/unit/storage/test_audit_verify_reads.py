"""`SqlAlchemyAuditRepository` reads for verify (head, anchor, keyset batch): statements,
time budget and error mapping, on a fake unit of work. The statements against the real
trigger are covered by `tests/integration/audit/` (CI, docker)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import pytest
import sqlalchemy as sa
from structlog.testing import capture_logs

from candleviewer.storage.errors import StorageTierUnavailable
from candleviewer.storage.repositories.audit_sqlalchemy import (
    VERIFY_BATCH_MAX_BYTES,
    AuditReadFailed,
    SqlAlchemyAuditRepository,
)


class _Orig(Exception):
    def __init__(self, sqlstate: str) -> None:
        super().__init__("driver error")
        self.sqlstate = sqlstate


def _db_error(sqlstate: str) -> sa.exc.DBAPIError:
    return sa.exc.DBAPIError("SELECT ... WHERE id > :after_id", {"after_id": 7}, _Orig(sqlstate))


class _Rel:
    """`unit_of_work()` answering `rows`, or failing at checkout (`on_enter`, `"hang"` never
    returns) or on the read (`on_read`). Records every statement and its parameters."""

    def __init__(self, rows: list[Any] | None = None, on_enter: Any = None, on_read: Any = None):
        self.rows, self.on_enter, self.on_read = rows or [], on_enter, on_read
        self.calls: list[tuple[str, dict[str, Any] | None]] = []

    @asynccontextmanager
    async def unit_of_work(self) -> AsyncIterator[Any]:
        if self.on_enter == "hang":
            await asyncio.Event().wait()
        elif self.on_enter is not None:
            raise self.on_enter

        async def execute(stmt: Any, params: dict[str, Any] | None = None) -> list[Any]:
            self.calls.append((str(stmt), params))
            if "set_config" in str(stmt):
                return []
            if self.on_read is not None:
                raise self.on_read
            return list(self.rows)

        yield SimpleNamespace(session=SimpleNamespace(execute=execute))


def _repo(rel: _Rel) -> SqlAlchemyAuditRepository:
    return SqlAlchemyAuditRepository(rel)  # type: ignore[arg-type]  # structural fake


async def test_batch_is_a_keyset_walk_on_the_id_returned_as_tuples() -> None:
    rel = _Rel(rows=[[3, "p", "e", "x"]])
    rows = await _repo(rel).fetch_verify_batch(after_id=2, to_id=9, limit=10_000)
    assert rows == [(3, "p", "e", "x")] and isinstance(rows[0], tuple)
    (budget, budget_params), (read, params) = rel.calls
    assert "statement_timeout" in budget and budget_params == {"v": "10000ms"}
    assert "WHERE id > :after_id AND id <= :to_id ORDER BY id ASC LIMIT :limit" in read
    assert "IS NULL" not in read and params == {
        "after_id": 2,
        "to_id": 9,
        "limit": 10_000,
        "max_bytes": VERIFY_BATCH_MAX_BYTES,
    }
    # The byte budget: bytes rendered before a row, so the first row is always admitted.
    assert "sum(r.n) OVER (ORDER BY r.id) - r.n AS before" in read
    assert "WHERE w.before < :max_bytes ORDER BY w.id" in read


async def test_anchor_is_the_greatest_id_below_the_range() -> None:
    rel = _Rel(rows=[["a" * 64]])
    assert await _repo(rel).fetch_anchor_hash(5) == "a" * 64
    read, params = rel.calls[1]
    assert "WHERE id < :before_id ORDER BY id DESC LIMIT 1" in read and params == {"before_id": 5}
    assert await _repo(_Rel()).fetch_anchor_hash(1) is None  # nothing below: genesis


async def test_head_is_the_newest_entry_or_none() -> None:
    assert await _repo(_Rel(rows=[[41, "h" * 64]])).read_head() == (41, "h" * 64)
    assert await _repo(_Rel()).read_head() is None


async def test_bounds_are_the_first_and_the_head_id_in_one_statement() -> None:
    rel = _Rel(rows=[[3, 41]])
    assert await _repo(rel).read_bounds() == (3, 41)
    assert "SELECT min(id), max(id) FROM audit_log" in rel.calls[1][0]
    assert await _repo(_Rel(rows=[[None, None]])).read_bounds() is None  # an empty log


async def test_checkpoint_above_is_the_smallest_head_id_past_the_head() -> None:
    rel = _Rel(rows=[[57]])
    assert await _repo(rel).fetch_checkpoint_above(41) == 57
    read, params = rel.calls[1]
    assert "LEFT JOIN audit_log a ON a.id = c.head_id WHERE c.head_id > :head_id" in read
    assert "a.entry_hash IS DISTINCT FROM c.head_hash" in read  # missing, or another hash
    assert params == {"head_id": 41}
    assert await _repo(_Rel(rows=[[None]])).fetch_checkpoint_above(41) is None


async def test_checkpoints_carry_the_stored_hash_of_the_id_they_name() -> None:
    rel = _Rel(rows=[[2, "a" * 64, "a" * 64], [4, "b" * 64, None]])
    found = await _repo(rel).fetch_checkpoints(9)
    assert found == [(2, "a" * 64, "a" * 64), (4, "b" * 64, None)]  # None: no entry has id 4
    read, params = rel.calls[1]
    assert "LEFT JOIN audit_log a ON a.id = c.head_id" in read and params == {"to_id": 9}
    assert "WHERE c.head_id <= :to_id ORDER BY c.head_id" in read


def _assert_no_db_error_in_chain(err: BaseException) -> None:
    assert err.__cause__ is None and err.__context__ is None and err.__suppress_context__


@pytest.mark.parametrize(
    ("on_enter", "on_read"),
    [
        ("hang", None),  # a pool wait is bounded by the call's budget
        (sa.exc.TimeoutError("QueuePool limit"), None),
        (None, _db_error("57014")),  # `statement_timeout` fired
    ],
)
async def test_overrun_raises_builtin_timeout_error(on_enter: Any, on_read: Any) -> None:
    rel = _Rel(on_enter=on_enter, on_read=on_read)
    repo = SqlAlchemyAuditRepository(rel, verify_read_timeout_ms=10)  # type: ignore[arg-type]
    with capture_logs() as logs, pytest.raises(TimeoutError) as err:
        await repo.fetch_anchor_hash(5)
    _assert_no_db_error_in_chain(err.value)
    assert [e["event"] for e in logs] == ["audit.verify_read.timeout"]


@pytest.mark.parametrize(
    ("on_enter", "on_read", "sqlstate"),
    [(None, _db_error("42501"), "42501"), (OSError("connection refused"), None, None)],
)
async def test_store_error_carries_only_the_sqlstate(
    on_enter: Any, on_read: Any, sqlstate: str | None
) -> None:
    with capture_logs() as logs, pytest.raises(AuditReadFailed) as err:
        await _repo(_Rel(on_enter=on_enter, on_read=on_read)).read_head()
    assert isinstance(err.value, StorageTierUnavailable) and err.value.sqlstate == sqlstate
    _assert_no_db_error_in_chain(err.value)
    assert [(e["event"], e["sqlstate"]) for e in logs] == [("audit.verify_read.failed", sqlstate)]
    assert "after_id" not in repr(logs) and "SELECT" not in str(err.value)


async def test_page_read_that_fails_before_its_try_takes_no_slot() -> None:
    """3b review NIT: nothing runs between taking a read slot and the `try` that gives it
    back, so a failure building the time budget cannot leak a slot."""
    repo = _repo(_Rel())
    kw: dict[str, Any] = dict.fromkeys(
        ("actor_user_id", "actions", "subject_type", "subject_id", "severity", "outcome", "ip")
    )
    # A budget that cannot be built (`timeout_ms` not a number): it fails before the `try`.
    kw |= {"q": None, "from_ts": None, "to_ts": None, "after": None, "timeout_ms": "soon"}
    # The budget's own error: a missing argument would be a `TypeError` too, before any slot.
    with pytest.raises(TypeError, match="unsupported operand"):
        await repo.query_page(restrict_to_actor=None, raw=False, limit=1, **kw)
    assert (repo._reads, repo._shared_reads) == (0, 0)
