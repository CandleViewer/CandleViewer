"""E40-T03: subscription sharing, live reconfiguration, bounded queue, drain, B10 recording."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import Any

from candleviewer.alerts.evaluator import AlertTick
from candleviewer.alerts.lifecycle import AlertCharts
from candleviewer.alerts.service import AlertsService
from tests.alerts._evaluator_env import T0, ir, make, row


async def test_evaluator_subscriptions_equal_distinct_condition_hashes_100_over_12() -> None:
    rows = [row(f"a{i:03}", condition_ir=ir(const=60000 + i % 12)) for i in range(100)]
    ev, *_, m = make(*rows)
    await ev.warm_up()
    assert len(ev.subscriptions) == 12 == len({r.condition_hash for r in rows})
    assert sum(len(s.members) for s in ev.subscriptions.values()) == 100
    assert m.get("cv_alert_subscriptions") == 12 and m.get("cv_alerts_armed") == 100


async def test_evaluator_shared_subscription_evaluates_once_per_tick() -> None:
    rows = [row(f"a{i}", owner_user_id=f"u{i}") for i in range(5)]
    ev, store, src, *_ = make(*rows)
    await ev.warm_up()
    src.set("price", 65500, T0)
    await ev.process(AlertTick("on_price_update", T0, "BTCUSDT"))
    assert ev._snapshots.computations == 1 and len(store.deliveries) == 5


async def test_evaluator_live_reconfig_rekeys_and_drops_old_subscription() -> None:
    ev, store, *_ = make(row("a1"), row("a2"))
    await ev.warm_up()
    old = store.rows["a1"].condition_hash
    store.rows["a1"] = row("a1", condition_ir=ir(const=1))
    await ev.on_alert_changed("a1")
    assert set(ev.subscriptions) == {old, store.rows["a1"].condition_hash}
    store.rows["a2"] = row("a2", condition_ir=ir(const=1))
    await ev.on_alert_changed("a2")
    assert set(ev.subscriptions) == {store.rows["a1"].condition_hash}  # last referent left


async def test_evaluator_live_reconfig_create_disable_delete_and_invalid() -> None:
    ev, store, *_ = make()
    await ev.warm_up()
    store.rows["n"] = row("n")
    await ev.on_alert_changed("n")
    assert "n" in ev.alerts
    store.rows["n"] = replace(store.rows["n"], enabled=False)
    await ev.on_alert_changed("n")
    assert "n" not in ev.alerts and ev.subscriptions == {}
    store.rows["n"] = replace(store.rows["n"], enabled=True)
    await ev.on_alert_changed("n")
    del store.rows["n"]  # soft-deleted: repository no longer returns it
    await ev.on_alert_changed("n")
    await ev.on_alert_changed("never")
    assert ev.alerts == {}
    store.rows["bad"] = replace(row("x"), id="bad", condition_ir={"nope": 1})
    await ev.on_alert_changed("bad")
    assert "bad" not in ev.alerts


async def test_evaluator_symbol_and_trigger_filtering() -> None:
    ev, store, src, *_ = make(row("a1"), row("e1", symbol="ETHUSDT"))
    await ev.warm_up()
    src.set("price", 65500, T0)
    await ev.process(AlertTick("on_bar_close", T0, "BTCUSDT"))  # other trigger type
    await ev.process(AlertTick("on_price_update", T0, "SOLUSDT"))  # no member
    assert store.deliveries == []
    await ev.process(AlertTick("on_price_update", T0, "BTCUSDT"))
    assert [d.alert_id for d in store.deliveries] == ["a1"]


async def test_evaluator_bounded_queue_sheds_oldest_with_metric() -> None:
    ev, *_, m = make(queue_bound=2)
    for i in range(3):
        ev.submit(AlertTick("on_price_update", T0 + i))
    assert ev.dropped == 1 and m.get("cv_alert_eval_dropped_total") == 1
    assert ev._queue.get_nowait().event_ts_ms == T0 + 1


async def test_evaluator_task_runs_ticks_survives_errors_and_drains_on_stop() -> None:
    ev, store, src, *_ = make(row("a1"))
    await ev.warm_up()
    src.set("price", 65500, T0)
    calls: list[int] = []
    real = ev.process

    async def flaky(t: AlertTick) -> None:
        calls.append(t.event_ts_ms)
        if len(calls) == 1:
            raise RuntimeError("boom")
        await real(t)

    ev.process = flaky  # type: ignore[method-assign,assignment]  # test seam: inject a failure
    ev.start()
    ev.start()  # idempotent
    ev.submit(AlertTick("on_price_update", T0, "BTCUSDT"))
    ev.submit(AlertTick("on_price_update", T0 + 1, "BTCUSDT"))
    for _ in range(50):
        if len(store.deliveries):
            break
        await asyncio.sleep(0)  # cooperative yield, not a timed wait
    await ev.stop(1.0)
    assert len(calls) == 2 and len(store.deliveries) == 1
    await ev.stop(1.0)  # second stop is a no-op


async def test_evaluator_crash_between_insert_and_poll_leaves_outbox_pending() -> None:
    """The firing commit contains the outbox row; a restart re-reads state from rows and
    does not re-fire (bar/cooldown rebuilt from last_fired_at), so delivery is exactly once."""
    ev, store, src, clock, _ = make(row("a1", cooldown_seconds=60))
    await ev.warm_up()
    src.set("price", 65500, T0)
    await ev.process(AlertTick("on_price_update", T0, "BTCUSDT"))
    assert store.outbox == [1]  # pending, not yet polled
    ev2, *_ = make()
    ev2._store = store  # "restarted" process over the same durable rows
    await ev2.warm_up()
    ev2._snapshots._source = src
    clock.now = T0 + 1000
    await ev2.process(AlertTick("on_price_update", T0 + 1000, "BTCUSDT"))
    assert store.outbox == [1] and len(store.deliveries) == 1


class Charts:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.owners: list[str | None] = []

    async def fired(self, alert_id: str, ids: Any, channels: Any, **kw: Any) -> None:
        self.calls.append(("fired", alert_id))
        self.owners.append(kw.get("owner"))

    async def suppressed(self, alert_id: str, end: int, **kw: Any) -> None:
        self.calls.append(("suppressed", alert_id))
        self.owners.append(kw.get("owner"))

    async def suppression_expired(self, alert_id: str, **kw: Any) -> None:
        self.calls.append(("expired", alert_id))
        self.owners.append(kw.get("owner"))

    async def disabled(self, alert_id: str, **kw: Any) -> None:
        self.calls.append(("disabled", alert_id))
        self.owners.append(kw.get("owner"))


class Audit:
    def __init__(self, fail: bool = False) -> None:
        self.actions: list[str] = []
        self.fail = fail

    async def emit(self, action: str, **kw: Any) -> None:
        self.actions.append(action)
        if self.fail:
            raise RuntimeError("audit down")


async def test_evaluator_records_b10_and_audits_fire_storm_disarm() -> None:
    charts, audit = Charts(), Audit()
    ev, _store, src, clock, _ = make(row("o", trigger_mode="once"), row("e"),
                                    charts=charts, audit=audit)  # fmt: skip
    await ev.warm_up()
    src.set("price", 65500, T0)
    await ev.process(AlertTick("on_price_update", T0, "BTCUSDT"))
    assert charts.calls == [("fired", "e"), ("fired", "o"), ("disabled", "o")]
    ev.storm.limit = 0
    clock.now = T0 + 1
    await ev.process(AlertTick("on_price_update", T0 + 1, "BTCUSDT"))
    clock.now = T0 + 120_000
    await ev.flush_storms()
    assert charts.calls[3:] == [("suppressed", "e"), ("expired", "e")]
    src.set("price", None, clock.now, reason="source_degraded")
    await ev.process(AlertTick("on_price_update", clock.now, "BTCUSDT"))
    assert charts.calls[-1] == ("disabled", "e")
    assert audit.actions == ["alert.fired", "alert.fired", "alert.disarmed"]
    assert charts.owners == ["u1"] * len(charts.calls)  # every call names the alert's owner (§6.4)


async def test_evaluator_audit_failure_never_loses_committed_delivery() -> None:
    ev, store, src, *_ = make(row("a1"), audit=Audit(fail=True))
    await ev.warm_up()
    src.set("price", 65500, T0)
    await ev.process(AlertTick("on_price_update", T0, "BTCUSDT"))
    assert len(store.deliveries) == 1


async def test_alerts_service_lifecycle_with_and_without_evaluator() -> None:
    svc = AlertsService()
    await svc.start(None)  # type: ignore[arg-type]  # ctx unused by this module
    assert svc.health().detail == "evaluator idle" and not svc.submit_tick(AlertTick("x", 0))
    await svc.on_alert_changed("a")
    ev, store, *_ = make(row("a1"))

    async def factory() -> Any:
        return ev

    svc.bind(factory)
    await svc.start(None)  # type: ignore[arg-type]
    assert svc.health().detail == "evaluator running" and "a1" in ev.alerts
    assert svc.submit_tick(AlertTick("on_price_update", T0))
    store.rows["a1"] = replace(store.rows["a1"], enabled=False)
    await svc.on_alert_changed("a1")
    assert ev.alerts == {}
    await svc.stop(1.0)
    assert svc.health().status.value != "ok"

    async def none_factory() -> Any:
        return None

    svc.bind(none_factory)
    await svc.start(None)  # type: ignore[arg-type]
    assert svc.evaluator is None
    await svc.stop(1.0)


async def test_alert_charts_record_b10_lifecycle_through_factory() -> None:
    hooks: list[str] = []

    async def hook(name: str, ctx: dict[str, Any]) -> None:
        hooks.append(name)

    charts = AlertCharts(hook=hook, max_charts=2)
    await charts.fired("a", [1], ["in_app"])
    assert charts.leaf("a") == "delivered"
    await charts.fired("a", [2], ["in_app"])  # finished firing -> fresh chart
    assert charts.leaf("a") == "delivered"
    await charts.suppressed("b", T0)
    assert charts.leaf("b") == "suppressed" and hooks == ["suppressed"]
    await charts.suppression_expired("b")
    assert charts.leaf("b") == "armed"
    await charts.disabled("b")
    assert charts.leaf("b") == "disabled"
    await charts.suppression_expired("b")  # unhandled: refused, never deferred
    assert charts.refusals.counts == {"unhandled": 1} and charts.leaf("b") == "disabled"
    await charts.disabled("c")  # evicts the LRU chart (bound 2)
    assert charts.leaf("a") is None and charts.leaf("zz") is None
    await charts.stop()
