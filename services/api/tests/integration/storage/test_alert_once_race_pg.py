"""Integration (#1870, E40-T03 follow-up) on real Postgres 16: two concurrent `record_firing`
calls on separate connections can commit at most one firing of a `once` alert, and a `once` firing
racing the source-loss disarm commits exactly one of the two (no double fire, no double disarm).

The race is forced, not hoped for. A third connection holds `SELECT ... FOR UPDATE` on the alert
row; both writers are started and the test waits until the server reports both parked on that row
lock inside the conditional `UPDATE alerts SET enabled = false`. Only then is the lock released:
the first writer to be granted it commits and disarms, and the second one re-checks `enabled`
under READ COMMITTED, matches zero rows and must commit nothing. Not run locally (no docker);
exercised by the CI `integration` lane (`-m "integration and not perf and not flaky"`).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

import psycopg
import pytest
import pytest_asyncio

from candleviewer.alerts.outbox import TOPIC_ALERT_DELIVER, alert_deliver_dedup_key
from candleviewer.storage.repositories.alert_firing_sqlalchemy import SqlAlchemyAlertFiringStore
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from tests.integration.storage import test_alerts_migration as _mig

pytestmark = pytest.mark.integration
pg_dsn = _mig.pg_dsn  # the module-scoped Postgres 16 container at head

_CHANNELS = ("in_app", "email")
_WAIT_S = 20.0  # upper bound on the server reaching the parked state; never a delay


@pytest_asyncio.fixture
async def firing(pg_dsn: str) -> AsyncIterator[SqlAlchemyAlertFiringStore]:
    rel = SqlAlchemyRelationalRepository(pg_dsn, "once-race-it")
    try:
        yield SqlAlchemyAlertFiringStore(
            rel, topic=TOPIC_ALERT_DELIVER, dedup_key=alert_deliver_dedup_key
        )
    finally:
        await rel.dispose()


def _seed(dsn: str) -> tuple[str, str]:
    with _mig._conn(dsn) as c:
        alert = _mig._alert(
            c, trigger_mode="once", symbol="BTCUSDT", channels="{in_app,email}", cooldown_seconds=0
        )
        row = c.execute("SELECT owner_user_id FROM alerts WHERE id = %s", (alert,)).fetchone()
    assert row is not None
    return alert, str(row[0])


@contextmanager
def _row_lock(dsn: str, alert: str) -> Iterator[psycopg.Connection[tuple[object, ...]]]:
    """A transaction holding the alert row's lock: every writer queues behind it."""
    conn = psycopg.connect(dsn.replace("postgresql+asyncpg", "postgresql"), autocommit=False)
    try:
        conn.execute("SELECT 1 FROM alerts WHERE id = %s FOR UPDATE", (alert,))
        yield conn
    finally:
        conn.rollback()
        conn.close()


async def _wait_parked(dsn: str, writers: int) -> None:
    """Return once `writers` backends wait on a row lock in the conditional disarm UPDATE."""
    sql = (
        "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() "
        "AND wait_event_type = 'Lock' AND query LIKE 'UPDATE alerts SET enabled = false%'"
    )
    deadline = time.monotonic() + _WAIT_S
    while True:
        with _mig._conn(dsn) as c:
            row = c.execute(sql).fetchone()
        assert row is not None
        if int(str(row[0])) >= writers:
            return
        assert time.monotonic() < deadline, "writers never parked on the alert row lock"
        await asyncio.sleep(0.02)  # polls the server's lock state; there is no event to await


def _fire(store: SqlAlchemyAlertFiringStore, alert: str, owner: str, **over: Any) -> Any:
    args: dict[str, Any] = {
        "alert_id": alert, "user_id": owner, "channels": _CHANNELS, "status": "queued",
        "title": "t", "body": "b", "context": {"bar_open_ms": 1}, "fired_at": datetime.now(UTC),
        "once": True, "bump": True,
    }  # fmt: skip
    return store.record_firing(**{**args, **over})


def _state(dsn: str, alert: str) -> dict[str, Any]:
    with _mig._conn(dsn) as c:
        a = c.execute(
            "SELECT enabled, fire_count, disarm_reason FROM alerts WHERE id = %s", (alert,)
        ).fetchone()
        deliveries = c.execute(
            "SELECT id, channel::text, context FROM alert_deliveries WHERE alert_id = %s "
            "ORDER BY id",
            (alert,),
        ).fetchall()
        outbox = c.execute(
            "SELECT payload->>'delivery_id' FROM outbox WHERE topic = %s "
            "AND (payload->>'alert_id') = %s",
            (TOPIC_ALERT_DELIVER, alert),
        ).fetchall()
    assert a is not None
    return {
        "enabled": a[0], "fire_count": a[1], "reason": a[2],
        "deliveries": [(int(str(d[0])), str(d[1]), d[2]) for d in deliveries],
        "outbox": sorted(str(o[0]) for o in outbox),
    }  # fmt: skip


async def _race(dsn: str, alert: str, *calls: Any) -> list[Any]:
    """Start every call while the row is locked, release once all are parked, gather results."""
    with _row_lock(dsn, alert):
        tasks = [asyncio.create_task(c) for c in calls]
        await _wait_parked(dsn, len(tasks))
    return list(await asyncio.gather(*tasks))


async def test_two_concurrent_once_firings_commit_exactly_one_delivery_set_and_one_disarm(
    pg_dsn: str, firing: SqlAlchemyAlertFiringStore
) -> None:
    alert, owner = _seed(pg_dsn)
    results = await _race(pg_dsn, alert, _fire(firing, alert, owner), _fire(firing, alert, owner))
    winners = [r for r in results if r is not None]
    assert len(winners) == 1 and len(winners[0]) == len(_CHANNELS)  # the loser returned None
    s = _state(pg_dsn, alert)
    assert s["enabled"] is False and s["fire_count"] == 1  # one disarm, one counter bump
    assert [d[0] for d in s["deliveries"]] == sorted(winners[0])  # only the winner's rows exist
    assert [d[1] for d in s["deliveries"]] == list(_CHANNELS)
    assert s["outbox"] == sorted(str(i) for i in winners[0])  # one outbox row per delivery


async def test_three_concurrent_once_firings_still_commit_one(
    pg_dsn: str, firing: SqlAlchemyAlertFiringStore
) -> None:
    alert, owner = _seed(pg_dsn)
    results = await _race(pg_dsn, alert, *(_fire(firing, alert, owner) for _ in range(3)))
    assert sum(r is not None for r in results) == 1
    s = _state(pg_dsn, alert)
    assert (s["enabled"], s["fire_count"], len(s["deliveries"])) == (False, 1, len(_CHANNELS))


async def test_once_firing_racing_the_source_loss_disarm_commits_exactly_one_of_them(
    pg_dsn: str, firing: SqlAlchemyAlertFiringStore
) -> None:
    alert, owner = _seed(pg_dsn)
    once, disarm = await _race(
        pg_dsn, alert,
        _fire(firing, alert, owner),
        _fire(firing, alert, owner, once=False, bump=False, disarm_reason="source_unavailable",
              context={"disarmed": True, "reason": "source_unavailable"}),
    )  # fmt: skip
    assert (once is None) != (disarm is None)  # exactly one writer saw `enabled` and committed
    s = _state(pg_dsn, alert)
    assert s["enabled"] is False and len(s["deliveries"]) == len(_CHANNELS)
    assert s["outbox"] == sorted(str(d[0]) for d in s["deliveries"])
    if once is not None:  # the firing won: a bump, no stated reason, no disarm notice
        assert s["fire_count"] == 1 and s["reason"] is None
        assert all("disarmed" not in d[2] for d in s["deliveries"])
    else:  # the disarm won: a stated reason, no firing counted, and the late firing never lands
        assert s["fire_count"] == 0 and s["reason"] == "source_unavailable"
        assert all(d[2].get("disarmed") is True for d in s["deliveries"])
