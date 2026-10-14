"""`SqlAlchemyAuditRepository.query_page` time budget and error mapping (fake unit of work).

The real `statement_timeout` firing is covered by
`tests/integration/audit/test_audit_query_timeout.py` (CI, docker).
"""

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
    AuditReadFailed,
    SqlAlchemyAuditRepository,
)

_IP = "203.0.113.77"


class _Orig(Exception):
    def __init__(self, sqlstate: str) -> None:
        super().__init__("driver error")
        self.sqlstate = sqlstate


def _db_error(sqlstate: str) -> sa.exc.DBAPIError:
    return sa.exc.DBAPIError("SELECT ... actor_ip = :ip", {"ip": _IP}, _Orig(sqlstate))


class _Rel:
    """`unit_of_work()` that fails at checkout (`on_enter`) or on the page query (`on_query`)."""

    def __init__(self, on_enter: Any = None, on_query: Any = None) -> None:
        self.on_enter, self.on_query = on_enter, on_query
        self.statements: list[str] = []

    @asynccontextmanager
    async def unit_of_work(self) -> AsyncIterator[Any]:
        if self.on_enter == "hang":
            await asyncio.Event().wait()
        elif self.on_enter is not None:
            raise self.on_enter

        async def execute(stmt: Any, params: dict[str, Any] | None = None) -> list[Any]:
            self.statements.append(str(stmt))
            if "set_config" not in str(stmt) and self.on_query is not None:
                raise self.on_query
            return [SimpleNamespace(_mapping={"id": 1})]

        yield SimpleNamespace(session=SimpleNamespace(execute=execute))


async def _page(rel: _Rel, timeout_ms: int | None = 50) -> list[dict[str, Any]]:
    repo = SqlAlchemyAuditRepository(rel)  # type: ignore[arg-type]  # structural fake
    return await repo.query_page(
        actor_user_id=None,
        actions=None,
        subject_type=None,
        severity=None,
        outcome=None,
        from_ts=None,
        to_ts=None,
        cursor=None,
        limit=10,
        ip=_IP,
        timeout_ms=timeout_ms,
    )


async def test_query_page_sets_the_statement_timeout_then_reads() -> None:
    rel = _Rel()
    assert await _page(rel) == [{"id": 1}]
    assert "set_config" in rel.statements[0]
    unbounded = _Rel()
    assert await _page(unbounded, timeout_ms=None) == [{"id": 1}]
    assert len(unbounded.statements) == 1 and "set_config" not in unbounded.statements[0]


@pytest.mark.parametrize(
    ("on_enter", "on_query", "cause"),
    [
        ("hang", None, "budget"),  # a pool wait is bounded by the call's budget
        (sa.exc.TimeoutError("QueuePool limit"), None, "pool"),
        (None, _db_error("57014"), "statement_timeout"),
    ],
)
async def test_query_page_overrun_raises_builtin_timeout_error(
    on_enter: Any, on_query: Any, cause: str
) -> None:
    with capture_logs() as logs, pytest.raises(TimeoutError) as err:
        await _page(_Rel(on_enter, on_query), timeout_ms=10)
    assert err.value.__cause__ is None and err.value.__context__ is None
    assert [(e["event"], e["cause"]) for e in logs] == [("audit.read.timeout", cause)]


@pytest.mark.parametrize(
    ("on_enter", "on_query", "sqlstate"),
    [
        (None, _db_error("42501"), "42501"),
        (OSError("connection refused"), None, None),
    ],
)
async def test_query_page_store_error_carries_only_the_sqlstate(
    on_enter: Any, on_query: Any, sqlstate: str | None
) -> None:
    with capture_logs() as logs, pytest.raises(AuditReadFailed) as err:
        await _page(_Rel(on_enter, on_query))
    assert isinstance(err.value, StorageTierUnavailable)
    assert err.value.sqlstate == sqlstate and err.value.__suppress_context__
    error = type(on_query or on_enter).__name__
    assert [(e["event"], e["error"], e["sqlstate"]) for e in logs] == [
        ("audit.read.failed", error, sqlstate)
    ]
    assert set(logs[0]) == {"event", "error", "sqlstate", "log_level"}
    assert _IP not in str(err.value) and _IP not in repr(logs)
