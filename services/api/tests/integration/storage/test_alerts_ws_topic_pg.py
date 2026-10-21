"""Integration (E40-T04 PR-B): the `alerts` topic end to end on real Postgres 16.

A firing's queued in-app delivery is settled by the real dispatcher, whose `on_change` tells the
topic, whose worker reads the real repository and publishes through the real fan-out to a
subscriber on the real gateway parts (every frame validated against §15.7). Then an ack, then a
blocked desktop report with its channel-failure notice. Needs docker (testcontainers); in CI it runs
in the merge-group integration lane.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest

from candleviewer.alerts.dispatcher import AlertDispatcher, default_adapters
from candleviewer.alerts.outbox import TOPIC_ALERT_DELIVER, alert_deliver_dedup_key
from candleviewer.alerts.ws_topic import AlertsTopic
from candleviewer.storage.repositories.alert_deliveries_sqlalchemy import (
    SqlAlchemyAlertDeliveryRepository,
)
from candleviewer.storage.repositories.alert_dispatch_sqlalchemy import (
    SqlAlchemyAlertDispatchStore,
)
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from candleviewer.ws.sequencing import SequencingHub, SnapshotBody
from tests.alerts._alerts_ws import Conn, principal, settled
from tests.integration.storage import test_alerts_migration as _mig

pytestmark = pytest.mark.integration
pg_dsn = _mig.pg_dsn  # reuse the module-scoped Postgres 16 container fixture


def _owner_of(dsn: str, alert: str) -> str:
    with _mig._conn(dsn) as c:
        got = c.execute("SELECT owner_user_id::text FROM alerts WHERE id = %s", (alert,)).fetchone()
    assert got is not None
    return str(got[0])


def _queued(dsn: str, alert: str, user: str, channel: str = "in_app") -> int:
    """A firing's delivery as `record_firing` commits it: queued, with its outbox row."""
    with _mig._conn(dsn) as c:
        row = c.execute(
            "INSERT INTO alert_deliveries (alert_id, user_id, channel, title, body, context) "
            "VALUES (%s, %s, %s, 'BTC reclaims 64k', 'BTCUSDT crossed 64000', %s) RETURNING id",
            (alert, user, channel, json.dumps({"symbol": "BTCUSDT"})),
        ).fetchone()
        assert row is not None
        did = int(str(row[0]))
        if channel != "desktop":
            c.execute(
                "INSERT INTO outbox (topic, dedup_key, payload) VALUES (%s, %s, %s::jsonb)",
                (TOPIC_ALERT_DELIVER, alert_deliver_dedup_key(did),
                 json.dumps({"delivery_id": did})),
            )  # fmt: skip
    return did


@pytest.fixture
async def rig(pg_dsn: str) -> AsyncIterator[dict[str, Any]]:
    with _mig._conn(pg_dsn) as c:
        alert = _mig._alert(c)
    user = _owner_of(pg_dsn, alert)
    rel = SqlAlchemyRelationalRepository(pg_dsn, "topic-it")
    repo = SqlAlchemyAlertDeliveryRepository(rel)
    hub = SequencingHub()
    topic = AlertsTopic(hub.publish, hub.flush_pending, hub.resnapshot, SnapshotBody)
    topic.attach(repo)
    topic.start()
    disp = AlertDispatcher(
        SqlAlchemyAlertDispatchStore(rel), default_adapters(None), worker="topic-it",
        now=lambda: datetime.now(UTC), on_change=topic.deliveries_changed,
    )  # fmt: skip
    conn = Conn(hub, topic, principal(UUID(user)))
    yield {"alert": alert, "user": user, "repo": repo, "topic": topic, "disp": disp,
           "conn": conn, "dsn": pg_dsn}  # fmt: skip
    await topic.stop()


async def test_fire_deliver_push_ack_on_postgres(rig: dict[str, Any]) -> None:
    conn, topic = rig["conn"], rig["topic"]
    conn.sub()
    await settled(topic, 10)
    assert conn.items() == [("snap", [], 0)]  # nothing unacked yet
    did = _queued(rig["dsn"], rig["alert"], rig["user"])
    assert await rig["disp"].run_once() >= 1  # in_app: settled `sent`, the topic told
    await settled(topic, 10)
    ((kind, payload),) = conn.take()
    assert kind == "d" and payload["unacked_count"] == 1
    (item,) = payload["deliveries"]
    assert (item["id"], item["status"], item["symbol"]) == (did, "sent", "BTCUSDT")
    acked = await rig["repo"].ack(did, rig["user"])
    assert acked is not None
    await topic.deliveries_changed([did])
    await settled(topic, 10)
    ((kind, payload),) = conn.take()
    assert kind == "d" and payload["unacked_count"] == 0
    assert payload["deliveries"][0]["status"] == "acked"
    assert payload["deliveries"][0]["acked_at_ms"] is not None


async def test_a_blocked_desktop_report_brings_its_notice(rig: dict[str, Any]) -> None:
    conn, topic = rig["conn"], rig["topic"]
    conn.sub()
    await settled(topic, 10)
    conn.take()
    did = _queued(rig["dsn"], rig["alert"], rig["user"], channel="desktop")
    got = await rig["repo"].report_desktop(
        did, user_id=rig["user"], error="desktop notification blocked", notice_title="n"
    )
    assert got is not None and got.status == "failed"
    await topic.deliveries_changed([did])  # as the inbox route tells it: the failed row only
    await settled(topic, 10)
    ((kind, payload),) = conn.take()
    statuses = {d["channel"]: d["status"] for d in payload["deliveries"]}
    assert kind == "d" and statuses == {"desktop": "failed", "in_app": "sent"}
    assert payload["unacked_count"] == 1  # the notice is unacked


async def test_a_late_attach_reads_the_current_rows(rig: dict[str, Any]) -> None:
    did = _queued(rig["dsn"], rig["alert"], rig["user"])
    await rig["disp"].run_once()
    await settled(rig["topic"], 10)
    conn = rig["conn"]
    conn.sub()  # after the change: its snapshot is a fresh read, the delivery in it
    await settled(rig["topic"], 10)
    assert conn.items() == [("snap", [did], 1)]
