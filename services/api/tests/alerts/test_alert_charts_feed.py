"""E17-T08: `AlertCharts` feeds `machines.alert:{id}.state` (23 §6.4). The entry is bound to the
alert's owner, which the evaluator names on every call; a chart dropped by the bound or `stop`
takes its entry with it, a finished firing's fresh chart takes the entry over (nobody is revoked),
and an alert whose owner the feed cannot read is fed nothing (logged, never a failed firing)."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from prometheus_client import CollectorRegistry
from structlog.testing import capture_logs

from candleviewer.alerts.lifecycle import AlertCharts
from candleviewer.app import _alert_evaluator_factory
from candleviewer.machine_state_wiring import RegistryFeed
from candleviewer.observability.metrics import Metrics
from candleviewer.ws.machines import MachineStateRegistry
from candleviewer.ws.sequencing import SequencingHub
from candleviewer.ws.topics import EntityScope
from tests.unit.ws._feed_support import Feed
from tests.unit.ws._seq_support import Conn, Source
from tests.unit.ws.test_machines import OWNER, _attach

ALERT, OTHER, USER = (str(uuid.UUID(int=n)) for n in (0xA1, 0xA2, 0xB1))


def _ch(alert_id: str) -> str:
    return f"machines.alert:{alert_id}.state"


async def test_a_firing_publishes_the_alerts_entry_bound_to_its_owner() -> None:
    feed = Feed()
    charts = AlertCharts(feed=feed.port)
    await charts.fired(ALERT, [1], ["in_app"], owner=USER)
    assert feed.registry.scope(_ch(ALERT)) == EntityScope(user=uuid.UUID(USER))
    served = feed.served(_ch(ALERT))
    assert served is not None and served["machine_kind"] == "alert"
    assert served["state"] == "delivered" and feed.scope_missing() == 0
    await charts.stop()
    assert feed.served(_ch(ALERT)) is None


async def test_each_call_the_evaluator_makes_binds_the_owner_when_it_builds_the_chart() -> None:
    feed, ids = Feed(), [str(uuid.UUID(int=n)) for n in range(0xC1, 0xC5)]
    charts = AlertCharts(feed=feed.port)
    await charts.fired(ids[0], [1], ["in_app"], owner=USER)  # the first call of an alert builds it
    await charts.suppressed(ids[1], 1_000, owner=USER)
    await charts.suppression_expired(ids[2], owner=USER)
    await charts.disabled(ids[3], owner=USER)
    scopes = {a: feed.registry.scope(_ch(a)) for a in ids}
    assert scopes == dict.fromkeys(ids, EntityScope(user=uuid.UUID(USER)))
    assert feed.scope_missing() == 0
    await charts.stop()


async def test_a_dropped_chart_leaves_no_entry() -> None:
    feed = Feed()
    charts = AlertCharts(max_charts=1, feed=feed.port)
    await charts.fired(ALERT, [1], ["in_app"], owner=USER)
    await charts.fired(OTHER, [2], ["in_app"], owner=USER)  # the bound drops ALERT's chart
    assert feed.served(_ch(ALERT)) is None and feed.served(_ch(OTHER)) is not None
    assert len(feed.registry) == 1 and feed.scope_missing() == 0
    await charts.stop()


async def test_a_finished_firings_fresh_chart_takes_its_entry_over() -> None:
    """The fresh chart is built before the old one stops, so its stop finds the new chart's entry
    and leaves it: the owner's subscription gets a `d` at each re-fire, never a `revoked`."""
    hub, conn = SequencingHub(), Conn(Source())
    registry = MachineStateRegistry(hub=hub)  # no timers: each payload leaves at once
    charts = AlertCharts(feed=RegistryFeed(registry, environment="demo", now_ms=lambda: 1))
    _attach(conn, registry, hub)
    conn.authz.principal = OWNER
    owner = str(OWNER.user_id)
    await charts.fired(ALERT, [1], ["in_app"], owner=owner)
    conn.sub(_ch(ALERT))
    assert [(f["t"], f["p"]["state"]) for f in conn.take()] == [("snap", "delivered")]
    await charts.fired(ALERT, [2], ["in_app"], owner=owner)  # the finished firing: a fresh chart
    frames = conn.take()
    assert {f["t"] for f in frames} == {"d"} and frames[-1]["p"]["state"] == "delivered"
    assert len(registry) == 1
    await charts.stop()  # the one live chart ends: now the topic is removed
    assert [(f["t"], f["p"]["reason"]) for f in conn.take()] == [("revoked", "topic_removed")]


@pytest.mark.parametrize("owner", [None, "not-a-uuid"])
async def test_an_owner_the_feed_cannot_read_gets_no_entry_and_the_alert_still_fires(
    owner: str | None,
) -> None:
    """The scope of a user kind comes from the owner alone: none, and `bind` refuses (2c), so the
    entry that would be refused to every role is never made, and `scope_missing` stays put."""
    feed = Feed()
    charts = AlertCharts(feed=feed.port)
    with capture_logs() as logs:
        await charts.fired(ALERT, [1], ["in_app"], owner=owner)
    assert charts.leaf(ALERT) == "delivered"  # the chart ran
    assert feed.served(_ch(ALERT)) is None and len(feed.registry) == 0
    assert feed.scope_missing() == 0
    assert [(e["event"], e["kind"]) for e in logs] == [("statechart_feed_unbound", "alert")]
    await charts.stop()


async def test_the_alert_factory_gives_the_evaluators_charts_the_feed() -> None:
    feed = Feed()
    ctx = SimpleNamespace(rules=SimpleNamespace(metric_source=object()), audit=None)
    metrics = Metrics("demo", registry=CollectorRegistry())
    evaluator = await _alert_evaluator_factory(ctx, object(), metrics, feed=feed.port)()
    assert evaluator is not None and evaluator._charts._feed is feed.port
