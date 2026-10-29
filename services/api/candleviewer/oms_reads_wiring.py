"""The OMS read routes' composition (E29-T07 #915, PR 1): the read store on a pool of its own, at
the OMS stores' statement cap (`CV_OMS_STATEMENT_TIMEOUT_MS`), as the trade-group definitions' is,
and an order's version for `getOrder`'s `ETag`. The reads hold the caller's scope in every
statement, so they need neither the order lane nor the OMS to be ready: the blotters stay readable
while the OMS starts or is degraded (20 Sec.6.2). None on the fake backend (503 after RBAC).
"""

from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

from candleviewer.oms.errors import OmsNotReady
from candleviewer.oms.reads import OmsReads
from candleviewer.oms_wiring import OmsRuntime
from candleviewer.settings import Settings
from candleviewer.storage.repositories.oms_reads_sqlalchemy import SqlAlchemyOmsReads
from candleviewer.storage.repositories.relational_sqlalchemy import SqlAlchemyRelationalRepository

__all__ = ["oms_reads", "order_versions"]


def oms_reads(settings: Settings) -> OmsReads | None:
    """The reads of this process's environment (C-2.11); None unless the backend is real."""
    if settings.storage_backend != "real":
        return None
    pool = SqlAlchemyRelationalRepository(settings.pg_dsn.get_secret_value(), "oms-reads")
    store = SqlAlchemyOmsReads(pool, statement_timeout_ms=settings.oms_statement_timeout_ms)
    return OmsReads(store, settings.environment.value)


def order_versions(runtime: Callable[[], OmsRuntime | None]) -> Callable[[UUID], int | None]:
    """An order's version as B1's facade holds it (`OrderRoute.versions`, read in place as the
    exit routes read it), None while no OMS is composed or it knows none."""

    def version(order_id: UUID) -> int | None:
        oms = runtime()
        if oms is None:
            return None
        try:
            return oms.route.versions.version(order_id)
        except OmsNotReady:
            return None

    return version
