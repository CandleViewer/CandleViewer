"""E40 #3349 (E42-X01 UL-F8): the alerts of a disabled owner neither fire nor deliver. The evaluator
skips an alert whose condition holds, or whose source is lost, when its owner is not active, leaves
all of its state alone, and counts the skip."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from candleviewer.alerts.evaluator import AlertTick
from candleviewer.alerts.owners import OwnerGate
from tests.alerts._evaluator_env import T0, ir, make, row
from tests.alerts._owners_env import Directory, Time

SKIPPED = "cv_alert_owner_skipped_total"


def _tick(trigger: str = "on_price_update") -> AlertTick:
    return AlertTick(trigger, T0, "BTCUSDT")


@pytest.mark.parametrize("lost", [False, True], ids=["condition_holds", "source_lost"])
async def test_evaluator_inactive_owner_alert_commits_nothing_and_is_counted(lost: bool) -> None:
    audit, charts = AsyncMock(), AsyncMock()
    owners = OwnerGate(Directory())
    ev, store, src, _, m = make(row("a1"), owners=owners, audit=audit, charts=charts)
    await ev.warm_up()
    src.set("price", None if lost else 65500, T0, "source_unavailable" if lost else None)
    await ev.process(_tick())  # a firing, or a loud disarm, would commit a row
    assert store.deliveries == [] and store.outbox == [] and store.rows["a1"] == row("a1")
    assert audit.mock_calls == [] and charts.mock_calls == []  # no audit record, no B10 event
    assert "a1" in ev.alerts  # still armed
    assert m.get(SKIPPED, "evaluate", "inactive") == 1
    assert m.get("cv_alert_fires_total", "every_time") == 0


@pytest.mark.parametrize("mode", ["every_time", "once", "once_per_bar"])
async def test_evaluator_skip_spends_no_trigger_memory_and_a_reenable_fires(mode: str) -> None:
    cond = ir(trigger="on_bar_close", timeframe="5m") if mode == "once_per_bar" else ir()
    trigger, directory, clock = cond["trigger"]["type"], Directory(), Time()
    r = row("a1", trigger_mode=mode, cooldown_seconds=60, condition_ir=cond)
    ev, store, src, *_ = make(r, owners=OwnerGate(directory, clock=clock))
    await ev.warm_up()
    src.set("price", 65500, T0)
    await ev.process(_tick(trigger))
    state = ev.alerts["a1"]  # a skip is not a firing: no cooldown, `once` or bar memory is used
    assert store.deliveries == [] and state.last_fired_ms is None and state.fired_bars == {}
    directory.active.add("u1")  # the owner is enabled again
    clock.now = 1.0
    await ev.process(_tick(trigger))
    assert len(store.deliveries) == 1


async def test_evaluator_unreadable_owner_status_fails_closed_and_is_counted() -> None:
    directory, clock = Directory(fail=ConnectionError("down")), Time()
    ev, store, src, _, m = make(row("a1"), owners=OwnerGate(directory, clock=clock))
    await ev.warm_up()
    src.set("price", 65500, T0)
    await ev.process(_tick())
    assert store.deliveries == [] and "a1" in ev.alerts
    assert m.get(SKIPPED, "evaluate", "unreadable") == 1
    directory.fail, directory.everyone, clock.now = None, True, 1.0  # the store is back
    await ev.process(_tick())
    assert len(store.deliveries) == 1


async def test_evaluator_shared_subscription_skips_only_the_inactive_member() -> None:
    rows = [row("a1", owner_user_id="u1"), row("a2", owner_user_id="u2")]
    ev, store, src, _, m = make(*rows, owners=OwnerGate(Directory({"u1"})))
    await ev.warm_up()
    src.set("price", 65500, T0)
    await ev.process(_tick())
    assert len(ev.subscriptions) == 1  # one condition, two owners
    assert [d.alert_id for d in store.deliveries] == ["a1"]
    assert m.get(SKIPPED, "evaluate", "inactive") == 1


async def test_evaluator_reads_the_owner_only_for_a_due_alert_and_once_per_ttl() -> None:
    directory, clock = Directory({"u1"}), Time()
    ev, store, src, *_ = make(row("a1"), owners=OwnerGate(directory, clock=clock))
    await ev.warm_up()
    src.set("price", 60000, T0)  # not due
    await ev.process(_tick())
    assert directory.reads == []
    src.set("price", 65500, T0)
    for _ in range(3):
        await ev.process(_tick())
    assert directory.reads == [{"u1"}] and len(store.deliveries) == 3  # one read serves the ttl
    clock.now = 1.0
    await ev.process(_tick())
    assert len(directory.reads) == 2
