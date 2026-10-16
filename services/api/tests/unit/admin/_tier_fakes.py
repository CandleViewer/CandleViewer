"""Fakes for the tier write route tests (E42-T01): an audit spy that also keeps `before_state`, and
the app under test, with the read routes and the PUT sharing one fan-out (so the 5 s slice cache
is the real one) over the in-memory settings store."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from fastapi import FastAPI

from candleviewer.admin.http import AdminAreaRefused, admin_area_refused_handler
from candleviewer.admin.overview.capacity import AdminCapacityService
from candleviewer.admin.overview.fanout import SliceFanOut, utc_now
from candleviewer.admin.overview.service import AdminOverviewService
from candleviewer.admin_wiring import SettingsTierReader
from candleviewer.api.admin_capacity import make_admin_capacity_router
from candleviewer.api.admin_overview import make_admin_overview_router
from tests.unit.admin._admin_fakes import AuditSpy, Resolver
from tests.unit.admin._route_fakes import Ports
from tests.unit.storage.fakes_system_settings import FakeSystemSettings


class TierAuditSpy(AuditSpy):
    """`AuditSpy` that also keeps `before_state` (`None` when not sent, as the writer defaults it);
    `refuse` makes the named action fail like a full WAL, with a message that must never leak."""

    def __init__(self, refuse: str | None = None) -> None:
        super().__init__()
        self.refuse = refuse

    async def emit(self, action: str, **fields: Any) -> None:
        if action == self.refuse:
            raise RuntimeError("audit WAL full at /var/lib/cv")
        self.records.append({"action": action, "before_state": None, **fields})


def make_tier_app(
    store: FakeSystemSettings | None,
    *,
    ports: Ports | None = None,
    spy: Any = None,
    now: Callable[[], datetime] = utc_now,
) -> tuple[FastAPI, Any]:
    """Overview + capacity (GET, `admin:read`) and the tier PUT (`admin:write`) on one fan-out;
    `spy` is the audit emitter: a `TierAuditSpy` (the default) or the real writer."""
    f, spy = ports or Ports(), spy or TierAuditSpy()
    fan = SliceFanOut(now=now, monotonic=lambda: 0.0)  # the clock never reaches the 5 s TTL
    reader = None if store is None else SettingsTierReader(store)
    overview = AdminOverviewService(fan, counts=f, recorder=f, oms=f, now=now)
    capacity = AdminCapacityService(
        fan, recorder=f, ingestion=f, rate_limit=f, subaccounts=f, tier=reader, now=now
    )
    app = FastAPI()
    app.add_exception_handler(AdminAreaRefused, admin_area_refused_handler)
    app.include_router(
        make_admin_overview_router(overview, capacity, resolver=Resolver(), audit=spy)
    )
    app.include_router(make_admin_capacity_router(capacity, store, resolver=Resolver(), audit=spy))
    return app, spy
