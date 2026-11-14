"""E40-Q02 alert chaos 2, Postgres failover during a firing burst: no duplicate deliveries and no
lost outbox rows. CI-only (`chaos and integration`, the compose Postgres, migrated).

The compose topology has one Postgres, so the failover is its stop and start under load (the
nearest C-13.6 categories are the dependency outage of the storage scenarios): a burst of firings
runs through the production transaction while the dispatcher's poll loop runs; Postgres stops
mid-burst and comes back; the burst finishes. A firing whose commit failed is the caller's to
re-evaluate (never a partial row); one whose commit landed but whose answer was lost still counts.
So the invariants are read from the rows alone, once the backlog is drained:

- every firing is whole: `fire_count` x 2 channels = delivery rows, each with exactly one outbox
  row (`ux_outbox_dedup`) and no outbox row without its delivery;
- every delivery ends `sent`, and no delivery is won by two settles (none twice, none lost);
- every email delivery's idempotency key reached the relay (a re-send after a settle lost in the
  outage carries the same key, the relay dedupes on it).
"""

from __future__ import annotations

import asyncio
import contextlib

import asyncpg
import pytest
from sqlalchemy.exc import DBAPIError

from candleviewer.alerts.dispatcher import idempotency_key
from candleviewer.alerts.outbox import TOPIC_ALERT_DELIVER
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from tests.chaos.alerts._pg import WAIT_S, depth, dispatcher, fetch, fire, firing_store, ledger
from tests.chaos.alerts._pg import seeded as seed
from tests.chaos.alerts._rig import Relay, Wins
from tests.chaos.storage import _stack as st

# what an outage raises through the pool (SQLAlchemy wraps the driver's errors); anything else is a
# real bug in `fire` and propagates at once, failing the test with its cause
OUTAGE = (
    DBAPIError,
    asyncpg.PostgresConnectionError,
    asyncpg.InterfaceError,
    OSError,
    TimeoutError,
)
pytestmark = [pytest.mark.chaos, pytest.mark.integration]
BEFORE, AFTER = 20, 20  # firings committed before the stop, and after the recovery


@pytest.fixture(autouse=True)
async def _postgres_up() -> None:
    await st.ensure_up("postgres", st.pg_up)


async def test_a_postgres_restart_mid_burst_loses_and_duplicates_nothing() -> None:
    user, alert = await seed()
    repo = SqlAlchemyRelationalRepository(st.pg_dsn(), "alert-chaos-failover")
    relay, wins = Relay(), Wins()
    d = dispatcher(repo, relay, worker="failover", metric=wins, interval_s=0.1)
    store = firing_store(repo)
    committed, failed, back = [0], [0], asyncio.Event()

    async def burst() -> None:
        """Fire until AFTER firings committed after the recovery; a failed one waits for it."""
        after = 0
        while after < AFTER:
            try:
                await fire(store, user, alert, ("in_app", "email"))
            except OUTAGE:  # the outage: this firing never committed (or its answer is lost)
                failed[0] += 1
                await back.wait()
                continue
            committed[0] += 1
            after += back.is_set()
            await asyncio.sleep(0)  # a yield: the dispatcher's loop runs between firings

    d.start()
    task = asyncio.ensure_future(burst())
    try:

        async def warmed() -> bool:
            if task.done():
                task.result()  # a real bug in `fire` fails here with its cause
            return committed[0] >= BEFORE

        await st.until(warmed, "the burst is under way", timeout_s=WAIT_S)
        async with st.stopped("postgres", st.pg_up):

            async def hit() -> bool:
                if task.done():
                    task.result()
                return failed[0] > 0

            await st.until(hit, "a firing met the outage", timeout_s=WAIT_S)
        back.set()
        async with asyncio.timeout(WAIT_S):
            await task

        async def drained() -> bool:
            return await depth(alert) == 0

        await st.until(drained, "the dispatcher caught up", timeout_s=WAIT_S)
    finally:
        back.set()
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task
        await d.stop()
        await repo.dispose()
    led = await ledger(alert)
    rows = led["rows"]
    assert led["fire_count"] >= BEFORE + AFTER and len(rows) == 2 * led["fire_count"]
    assert all(r["ob"] == 1 and r["done"] and r["status"] == "sent" for r in rows)
    # never twice (a settle whose commit landed but whose answer was lost is not counted here; its
    # replay finds the row settled and only marks the outbox row processed)
    assert wins.sent <= len(rows)
    # a failed firing may still have committed (its answer lost), none else is missing or extra
    assert committed[0] <= led["fire_count"] <= committed[0] + failed[0]
    orphans = await fetch(
        "SELECT count(*) FROM outbox o WHERE o.topic = $1 AND NOT EXISTS "
        "(SELECT 1 FROM alert_deliveries d WHERE d.id::text = o.dedup_key)", TOPIC_ALERT_DELIVER,
    )  # fmt: skip
    assert orphans[0][0] == 0
    emails = {idempotency_key(int(r["id"])) for r in rows if r["channel"] == "email"}
    assert {k for k in relay.keys if k in emails} == emails  # this alert's deliveries
