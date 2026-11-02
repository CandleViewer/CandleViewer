"""The OMS stores' statement cap is a setting (#845; #913 S4-G2, the closing slice's CG14).

`CV_OMS_STATEMENT_TIMEOUT_MS` (20 Sec.7.2, 21 Sec.3.3.5, 24 Sec.8.2 S7) caps each statement of
every store the OMS runtime builds over its own pool (`oms_wiring.pg_stores`) that caps its
statements, but two: the startup sweep's reads keep their own cap (`SWEEP_STATEMENT_TIMEOUT_MS`),
and the machine-event store (`SqlAlchemyEventStore`) its own 2 s, as it reads no setting. The
stop resolver's bound on each store call, the audit's write-ahead bound plus two capped
statements and a slack, follows the setting too, so a statement at the cap still surfaces as
the store's own error, never as this bound's."""

from __future__ import annotations

from dataclasses import fields
from typing import Any

import pytest

from candleviewer import oms_wiring
from candleviewer.observability.metrics import Metrics
from candleviewer.oms.stop_resolution import STORE_TIMEOUT_S, StopResolver
from candleviewer.oms_wiring import SWEEP_STATEMENT_TIMEOUT_MS, OmsStores, pg_stores
from candleviewer.settings import Settings
from candleviewer.storage.repositories.orders_sqlalchemy import CappedStore
from candleviewer.storage.repositories.recorded_stops import STOP_AUDIT_TIMEOUT_S
from candleviewer.storage.repositories.trade_groups_sqlalchemy import SqlAlchemyTradeGroupStore
from tests.unit.oms import test_oms_runtime as rt

#: The stores `pg_stores` builds that cap their statements, by their `OmsStores` field.
_CAPPED = {"orders", "executions", "submissions", "anchors", "stops", "groups", "accounts", "sweep"}
_CAPPED |= {"handovers", "reconcile"}  # E29-T06 #914: `oms_handovers` and the pass's own store


async def test_every_capped_store_the_runtime_builds_reads_the_setting() -> None:
    """Each capped store reads the setting; the sweep alone keeps its own cap (CR-S3C1C-01)."""
    stores = pg_stores(Settings(oms_statement_timeout_ms=3000), Metrics("demo"))
    try:
        built = {f.name: getattr(stores, f.name) for f in fields(OmsStores)}
        capped = {
            name: store._timeout
            for name, store in built.items()
            if isinstance(store, CappedStore | SqlAlchemyTradeGroupStore)
        }
        assert set(capped) == _CAPPED  # none missed, none added unread
        assert capped.pop("sweep") == str(SWEEP_STATEMENT_TIMEOUT_MS)
        assert set(capped.values()) == {"3000"}
    finally:
        await stores.release()


@pytest.mark.parametrize(("cap", "bound"), [(None, STORE_TIMEOUT_S), ("5000", 16.0)])
async def test_the_stop_resolvers_store_bound_follows_the_setting(
    monkeypatch: pytest.MonkeyPatch, cap: str | None, bound: float
) -> None:
    """The bound is the audit's (5 s), the lock and the update each at the cap, and 1 s: 10 s at
    the 2 s default, 16 s at the 5 s ceiling."""
    if cap is not None:
        monkeypatch.setenv("CV_OMS_STATEMENT_TIMEOUT_MS", cap)
    built: list[dict[str, Any]] = []
    real = StopResolver  # the class `oms_wiring` builds the resolver from

    def spy(*args: Any, **kwargs: Any) -> StopResolver:
        built.append(kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr(oms_wiring, "StopResolver", spy)
    async with rt.started(rt.World().runtime()):
        pass
    assert [kwargs.get("store_timeout_s") for kwargs in built] == [bound]
    assert bound == STOP_AUDIT_TIMEOUT_S + 2 * Settings().oms_statement_timeout_ms / 1000 + 1
