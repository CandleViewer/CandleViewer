"""Postgres read of the day boundary (E29-S06 #981 slice 4; 21 Sec.3.11, 24 Sec.8.13).

The `risk_policy` singleton's `day_boundary_utc_offset_minutes`, under the `CappedStore` cap and
error mapping of `orders_sqlalchemy.py`. `risk.day_boundary.DayBoundary` reads it as
`RiskPolicyReads`, bounds the read and refuses a missing row or an offset outside `rp_day`.
"""

from __future__ import annotations

from typing import Final

import sqlalchemy as sa

from candleviewer.db.models import risk_policy
from candleviewer.storage.repositories.orders_sqlalchemy import CappedStore

DAY_BOUNDARY: Final = sa.select(risk_policy.c.day_boundary_utc_offset_minutes).where(
    risk_policy.c.singleton.is_(True)
)


class SqlAlchemyRiskPolicyReads(CappedStore):
    """The column over one relational repository (asyncpg); the row's absence raises."""

    async def day_boundary_utc_offset_minutes(self) -> int:
        async with self._unit_of_work() as uow:
            offset: int = (await uow.session.execute(DAY_BOUNDARY)).scalar_one()
        return offset
