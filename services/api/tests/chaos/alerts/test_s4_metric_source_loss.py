"""E40-Q02 alert chaos 4, metric source loss: the referenced source goes away mid-stream; the
alerts on it auto-disarm with one explanatory delivery each, alerts on other sources keep firing,
and recovery is correct when the source returns. In-process: the real evaluator over the
in-memory firing store (`tests.alerts._evaluator_env`, the one-transaction semantics), fake clock.

Recovery means: a returning source never silently re-arms a disarmed alert (the user saw it go);
an evaluator restart during the loss announces nothing twice; and an alert the owner re-enables
fires again on the next qualifying tick, while one left disarmed stays silent.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from candleviewer.alerts.evaluator import AlertEvaluator, AlertMetrics, AlertTick
from tests.alerts._evaluator_env import T0, ir, make, row
from tests.alerts._owners_env import allow

pytestmark = pytest.mark.chaos


def _tick(ts: int) -> AlertTick:
    return AlertTick("on_price_update", ts, "BTCUSDT")


async def test_source_loss_disarms_once_with_a_reason_and_recovers_on_re_enable() -> None:
    ev, store, src, clock, m = make(
        row("a1"), row("a2"), row("b1", condition_ir=ir(metric="open_interest", const=0))
    )
    await ev.warm_up()
    src.set("price", 65500, T0)
    src.set("open_interest", 10, T0)
    await ev.process(_tick(T0))
    assert sorted(d.alert_id for d in store.deliveries) == ["a1", "a2", "b1"]

    clock.now = T0 + 1_000  # the price source is lost mid-stream
    src.set("price", None, clock.now, reason="source_unavailable")
    src.set("open_interest", 11, clock.now)
    for k in range(3):  # ticks during the loss: every alert on it disarms on the first one,
        clock.now += 1_000  # and only once
        src.set("open_interest", 12 + k, clock.now)
        await ev.process(_tick(clock.now))
        disarms = [d for d in store.deliveries if d.context.get("disarmed")]
        assert sorted(d.alert_id for d in disarms) == ["a1", "a2"], k
    for d in disarms:
        assert d.status == "queued" and d.id in store.outbox  # dispatched like any firing
        assert d.title == "Alert disarmed: price data source unavailable"
        assert d.context == {"disarmed": True, "reason": "source_unavailable", "metric": "price"}
    assert not store.rows["a1"].enabled and not store.rows["a2"].enabled
    assert sum(d.alert_id == "b1" for d in store.deliveries) == 4  # the other source unaffected
    assert m.get("cv_alert_autodisarmed_total", "source_unavailable") == 2

    restarted = AlertEvaluator(store, src, owners=allow(), metrics=AlertMetrics(m), clock=clock)
    await restarted.warm_up()  # a restart during the loss: the disarmed alerts are not loaded
    clock.now += 1_000
    await restarted.process(_tick(clock.now))
    assert len([d for d in store.deliveries if d.context.get("disarmed")]) == 2

    clock.now += 1_000  # the source returns: nothing re-arms behind the user's back
    src.set("price", 65500, clock.now)
    before = len(store.deliveries)
    await restarted.process(_tick(clock.now))
    assert {d.alert_id for d in store.deliveries[before:]} == {"b1"}

    store.rows["a1"] = replace(store.rows["a1"], enabled=True)  # the owner re-enables a1
    await restarted.on_alert_changed("a1")
    clock.now += 1_000
    src.set("price", 65600, clock.now)
    before = len(store.deliveries)
    await restarted.process(_tick(clock.now))
    fired = store.deliveries[before:]
    assert sorted(d.alert_id for d in fired) == ["a1", "b1"]
    assert all(d.status == "queued" and not d.context.get("disarmed") for d in fired)
    assert not store.rows["a2"].enabled and "a2" not in restarted.alerts
