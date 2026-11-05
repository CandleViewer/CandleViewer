"""Integration: the day boundary's column on Postgres 16 (E29-S06 #981 slice 4; 21 Sec.3.11, 24
Sec.8.13). The resolver reads `risk_policy.day_boundary_utc_offset_minutes` through its store: the
seeded singleton's 0, then a changed +180, which takes effect at the day's `next_start`, never
inside the day. The Postgres fixture and helpers are `test_closed_pnl_records_migration.py`'s."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from candleviewer.risk.day_boundary import DayBoundary
from candleviewer.storage.repositories.relational_sqlalchemy import SqlAlchemyRelationalRepository
from candleviewer.storage.repositories.risk_policy_sqlalchemy import SqlAlchemyRiskPolicyReads
from tests.integration.storage.test_closed_pnl_records_migration import _conn, pg_dsn

pytestmark = pytest.mark.integration
__all__ = ["pg_dsn"]  # the shared module-scoped fixture

T = datetime(2026, 10, 26, 10, tzinfo=UTC)
_SET = "UPDATE risk_policy SET day_boundary_utc_offset_minutes = %s"


async def test_the_resolver_reads_the_column_and_a_change_waits_for_next_start(pg_dsn: str) -> None:
    rel = SqlAlchemyRelationalRepository(pg_dsn, "risk-policy-it")
    reads = SqlAlchemyRiskPolicyReads(rel)
    try:
        assert await reads.day_boundary_utc_offset_minutes() == 0  # 0038's seed
        days = DayBoundary(reads)
        first = await days.resolve(T)
        assert (first.day_start, first.utc_offset_minutes) == (
            datetime(2026, 10, 26, tzinfo=UTC),
            0,
        )
        with _conn(pg_dsn) as c:
            c.execute(_SET, (180,))
        assert await reads.day_boundary_utc_offset_minutes() == 180
        assert await days.resolve(T + timedelta(hours=2)) == first  # the day in progress keeps 0
        change = await days.resolve(first.next_start)
        assert (change.day_start, change.next_start, change.utc_offset_minutes) == (
            first.next_start, datetime(2026, 10, 27, 21, tzinfo=UTC), 180,
        )  # fmt: skip
    finally:
        with _conn(pg_dsn) as c:
            c.execute(_SET, (0,))
        await rel.dispose()
