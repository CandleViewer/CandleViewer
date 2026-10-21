"""Integration: two `AlertDispatcher` pollers + crash replay on real Postgres 16 (E40-T04).

Exercises the real `FOR UPDATE SKIP LOCKED` claim and the conditional settles.
Not run locally (no docker); exercised by the integration CI job.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any

import pytest

from candleviewer.alerts.dispatcher import AlertDispatcher, default_adapters
from candleviewer.alerts.outbox import TOPIC_ALERT_DELIVER, alert_deliver_dedup_key
from candleviewer.alerts.owners import OwnerGate
from candleviewer.storage.repositories.alert_dispatch_sqlalchemy import (
    SqlAlchemyAlertDispatchStore,
)
from candleviewer.storage.repositories.identity_sqlalchemy import SqlAlchemyIdentityProvider
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from tests.integration.storage import test_alerts_migration as _mig

pytestmark = pytest.mark.integration
pg_dsn = _mig.pg_dsn  # reuse the module-scoped Postgres 16 container fixture


class Relay:
    def __init__(self) -> None:
        self.keys: list[str] = []

    async def send(self, *, user_id: str, subject: str, body: str, idempotency_key: str) -> None:
        self.keys.append(idempotency_key)
        await asyncio.sleep(0)


def _seed(dsn: str, n: int) -> list[int]:
    with _mig._conn(dsn) as c:
        aid = _mig._alert(c)
        uid = c.execute("SELECT owner_user_id FROM alerts WHERE id = %s", (aid,)).fetchone()
        assert uid is not None
        ids: list[int] = []
        for _ in range(n):
            row = c.execute(
                "INSERT INTO alert_deliveries (alert_id, user_id, channel, title) "
                "VALUES (%s, %s, 'email', 't') RETURNING id",
                (aid, uid[0]),
            ).fetchone()
            assert row is not None
            did = int(str(row[0]))
            c.execute(
                "INSERT INTO outbox (topic, dedup_key, payload) VALUES (%s, %s, %s::jsonb)",
                (TOPIC_ALERT_DELIVER, alert_deliver_dedup_key(did),
                 json.dumps({"delivery_id": did})),
            )  # fmt: skip
            ids.append(did)
    return ids


def _disp(repo: SqlAlchemyRelationalRepository, relay: Any, worker: str) -> AlertDispatcher:
    return AlertDispatcher(SqlAlchemyAlertDispatchStore(repo), default_adapters(relay),
                           worker=worker, now=lambda: datetime.now(UTC), batch=8,
                           owners=OwnerGate(SqlAlchemyIdentityProvider(repo)))  # fmt: skip


async def test_two_pollers_skip_locked_send_each_row_once(pg_dsn: str) -> None:
    ids = _seed(pg_dsn, 40)
    repo = SqlAlchemyRelationalRepository(pg_dsn, "dispatch-it")
    relay = Relay()
    a, b = _disp(repo, relay, "a"), _disp(repo, relay, "b")
    for _ in range(8):
        await asyncio.gather(a.run_once(), b.run_once())
    mine = [k for k in relay.keys if int(k.rsplit("-", 1)[1]) in ids]
    assert len(mine) == len(set(mine)) == 40


async def test_crash_mid_send_then_restart_sends_once_more_and_settles(pg_dsn: str) -> None:
    (did,) = _seed(pg_dsn, 1)
    repo = SqlAlchemyRelationalRepository(pg_dsn, "dispatch-it")
    relay = Relay()
    store = SqlAlchemyAlertDispatchStore(repo)

    async def crash(job: Any, **kw: Any) -> bool:
        raise ConnectionError("died before commit")

    store.settle_sent = crash  # type: ignore[method-assign]  # fault injection
    owners = OwnerGate(SqlAlchemyIdentityProvider(repo))
    await AlertDispatcher(store, default_adapters(relay), worker="dead", lease_s=0.0,
                          now=lambda: datetime.now(UTC), owners=owners).run_once()  # fmt: skip
    await _disp(repo, relay, "restart").run_once()
    with _mig._conn(pg_dsn) as c:
        row = c.execute("SELECT status::text FROM alert_deliveries WHERE id = %s", (did,))
        assert row.fetchone() == ("sent",)
    assert relay.keys.count(f"alert-delivery-{did}") == 2  # at-least-once, same key
