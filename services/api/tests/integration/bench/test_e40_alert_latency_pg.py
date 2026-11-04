"""Integration (E40-Q02, budget "condition met -> `alert_deliveries` committed"): the E40-K01 load,
500 alerts over 20 symbols on the seeded K01 tick stream, through the production `AlertEvaluator`,
the real owner gate and `SqlAlchemyAlertFiringStore` on real Postgres 16.

Each committed firing is one sample (`benchmarks.alerts.latency_leg`: from the `process()` call of
the tick that met the condition to `record_firing` returning after its COMMIT, an upper bound).
The budget is asserted on the nearest-rank p95 (<= 1 s) and p99 (<= 2 s); the row is printed as
one `E40Q02_PG_LEG=` JSON line (the `-rA` PASSES section) and kept as a JUnit property, for
`docs/qa/perf/e40-alerts-baseline.md`. The rows are then counted in the database: every sample is
a committed `alert_deliveries` row, every queued one has its outbox row. Not run locally (no
docker; owner host); exercised by the CI integration lane.
"""

from __future__ import annotations

import json
from collections.abc import Callable

import pytest

from benchmarks.alerts.latency_leg import BUDGET_P95_S, BUDGET_P99_S, leg_alerts, run_leg
from candleviewer.alerts.outbox import TOPIC_ALERT_DELIVER, alert_deliver_dedup_key
from candleviewer.alerts.owners import OwnerGate
from candleviewer.storage.repositories.alert_firing_sqlalchemy import SqlAlchemyAlertFiringStore
from candleviewer.storage.repositories.identity_sqlalchemy import SqlAlchemyIdentityProvider
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from tests.integration.storage import test_alerts_migration as _mig

pytestmark = pytest.mark.integration
pg_dsn = _mig.pg_dsn  # the module-scoped Postgres 16 container, migrated to head

#: The seeded stream fires roughly 0.38 firings per tick (about 1 900 on the local sqlite leg
#: at this tick count), so 5 000 ticks leave well over the 100 samples a p99 needs; the floor
#: below is a derived bound, not a measured figure.
MIN_P99_SAMPLES = 100
FIRINGS_PER_TICK_FLOOR = 0.3
TICKS = 5_000
assert TICKS * FIRINGS_PER_TICK_FLOOR >= MIN_P99_SAMPLES


def _count(dsn: str, sql: str, *params: object) -> int:
    with _mig._conn(dsn) as c:
        row = c.execute(sql, params).fetchone()
    assert row is not None
    return int(str(row[0]))


# The suite bound is 120 s (pyproject): the container start, 500 seeded alerts and about 1 900
# firing transactions need longer on a shared runner.
@pytest.mark.timeout(600)
async def test_alert_latency_leg_postgres_meets_p95_p99_budget(
    pg_dsn: str, record_property: Callable[[str, object], None]
) -> None:
    seeded = leg_alerts()
    with _mig._conn(pg_dsn) as c:  # one active owner per alert, as `_mig._alert` seeds them
        for a in seeded:
            _mig._alert(
                c, name=a.name, symbol=a.symbol, condition_ir=json.dumps(a.condition_ir),
                condition_hash=a.condition_hash, trigger_mode="every_time", cooldown_seconds=0,
                channels="{in_app}",
            )  # fmt: skip
    rel = SqlAlchemyRelationalRepository(pg_dsn, "e40-q02-latency-leg")
    try:
        store = SqlAlchemyAlertFiringStore(
            rel, topic=TOPIC_ALERT_DELIVER, dedup_key=alert_deliver_dedup_key
        )
        owners = OwnerGate(SqlAlchemyIdentityProvider(rel))
        res = await run_leg(store, name="postgres16", ticks=TICKS, owners=owners)
    finally:
        await rel.dispose()
    row = res.row()
    print("E40Q02_PG_LEG=" + json.dumps(row, sort_keys=True))
    record_property("e40q02_pg_leg", json.dumps(row, sort_keys=True))

    assert res.alerts == 500 and res.subscriptions == len({a.condition_hash for a in seeded})
    assert len(res.samples_s) > 1_000, row  # the stream really fired
    committed = sum(res.statuses.values())
    assert committed == len(res.samples_s)  # one in_app row per firing
    assert _count(pg_dsn, "SELECT count(*) FROM alert_deliveries WHERE NOT "
                  "coalesce((context->>'storm_summary')::boolean, false)") == committed  # fmt: skip
    assert _count(pg_dsn, "SELECT count(*) FROM outbox WHERE topic = %s", TOPIC_ALERT_DELIVER) == (
        _count(pg_dsn, "SELECT count(*) FROM alert_deliveries WHERE status = 'queued'")
    )
    assert _count(pg_dsn, "SELECT coalesce(sum(fire_count), 0) FROM alerts") == committed
    assert res.eval_hist_count == res.statuses.get("queued", 0)  # the shipped histogram agrees
    assert res.pct(0.95) <= BUDGET_P95_S, row
    assert res.pct(0.99) <= BUDGET_P99_S, row
