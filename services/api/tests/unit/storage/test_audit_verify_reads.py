"""`SqlAlchemyAuditRepository` reads for verify (anchor, keyset batch) and the page read's
slot handling, on a fake unit of work. The statements against the real trigger are covered
by `tests/integration/audit/` (CI, docker)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import pytest

from candleviewer.storage.repositories.audit_sqlalchemy import SqlAlchemyAuditRepository


class _Rel:
    """`unit_of_work()` answering `rows` to every statement; records each statement."""

    def __init__(self, rows: list[Any] | None = None) -> None:
        self.rows = rows or []
        self.calls: list[tuple[str, dict[str, Any] | None]] = []

    @asynccontextmanager
    async def unit_of_work(self) -> AsyncIterator[Any]:
        async def execute(stmt: Any, params: dict[str, Any] | None = None) -> list[Any]:
            self.calls.append((str(stmt), params))
            return list(self.rows)

        yield SimpleNamespace(session=SimpleNamespace(execute=execute))


def _repo(rel: _Rel) -> SqlAlchemyAuditRepository:
    return SqlAlchemyAuditRepository(rel)  # type: ignore[arg-type]  # structural fake


async def test_batch_is_a_keyset_walk_on_the_id_returned_as_tuples() -> None:
    rel = _Rel(rows=[[3, "p", "e", "x"]])
    rows = await _repo(rel).fetch_verify_batch(after_id=2, to_id=9, limit=10_000)
    assert rows == [(3, "p", "e", "x")] and isinstance(rows[0], tuple)
    [(read, params)] = rel.calls
    assert "WHERE id > :after_id AND id <= :to_id ORDER BY id ASC LIMIT :limit" in read
    assert "IS NULL" not in read and params == {"after_id": 2, "to_id": 9, "limit": 10_000}


async def test_anchor_is_the_greatest_id_below_the_range() -> None:
    rel = _Rel(rows=[["a" * 64]])
    assert await _repo(rel).fetch_anchor_hash(5) == "a" * 64
    [(read, params)] = rel.calls
    assert "WHERE id < :before_id ORDER BY id DESC LIMIT 1" in read and params == {"before_id": 5}
    assert await _repo(_Rel()).fetch_anchor_hash(1) is None  # nothing below: genesis


async def test_page_read_that_fails_before_its_try_takes_no_slot() -> None:
    """3b review NIT: nothing runs between taking a read slot and the `try` that gives it
    back, so a failure building the time budget cannot leak a slot."""
    repo = _repo(_Rel())
    kw: dict[str, Any] = dict.fromkeys(
        ("actor_user_id", "actions", "subject_type", "subject_id", "severity", "outcome", "ip")
    )
    # A budget that cannot be built (`timeout_ms` not a number): it fails before the `try`.
    kw |= {"q": None, "from_ts": None, "to_ts": None, "after": None, "timeout_ms": "soon"}
    with pytest.raises(TypeError):
        await repo.query_page(restrict_to_actor=None, limit=1, **kw)
    assert (repo._reads, repo._shared_reads) == (0, 0)
