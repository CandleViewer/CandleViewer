"""E40 #3349 (E42-X01 UL-F8): the dispatcher is the one choke point. A delivery whose owner is not
active reaches no channel, whichever channel it is and whenever it was queued; an owner whose
status cannot be read leaves the row for the next lease."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from typing import Any

from _dispatch_env import USER, Clock, MemStore
from test_alert_dispatcher import FailingRelay, Metrics

from candleviewer.alerts.dispatcher import (
    SUPPRESSION_REASONS,
    AlertDispatcher,
    default_adapters,
    idempotency_key,
)
from candleviewer.alerts.owners import OwnerGate
from tests.alerts._owners_env import Directory

SKIPPED = "cv_alert_owner_skipped_total"


def _world(directory: Directory) -> Any:
    clock, changed = Clock(), list[list[int]]()
    store, relay, metrics = MemStore(clock), FailingRelay(fail=0), Metrics()  # a relay that works

    async def on_change(ids: Any) -> None:
        changed.append(list(ids))

    disp = AlertDispatcher(store, default_adapters(relay), worker="w", now=clock, rng=lambda: 1.0,
                           owners=OwnerGate(directory), metric=metrics,
                           on_change=on_change)  # fmt: skip
    return SimpleNamespace(store=store, clock=clock, relay=relay, metrics=metrics,
                           changed=changed, disp=disp)  # fmt: skip


def _outcomes(w: Any) -> list[tuple[str, str | None]]:
    return [(r.status, r.error_message) for r in w.store.rows.values()]


async def test_dispatcher_inactive_owner_delivery_is_suppressed_on_every_channel() -> None:
    w = _world(Directory())  # nobody is active
    w.store.fire(["in_app", "desktop", "email"])
    await w.disp.run_once()
    assert _outcomes(w) == [("suppressed", "owner_inactive")] * 3
    assert {why for _, why in _outcomes(w)} <= SUPPRESSION_REASONS  # a bounded reason code
    assert all(o.processed for o in w.store.outbox.values()) and w.relay.keys == []
    assert w.changed == []  # final, and not announced on the `alerts` topic
    assert w.metrics.names().count((SKIPPED, ("dispatch", "inactive"))) == 3


async def test_dispatcher_unreadable_owner_leaves_the_row_leased_for_a_retry() -> None:
    directory = Directory(fail=ConnectionError("down"))
    w = _world(directory)
    (did,) = w.store.fire(["email"])
    await w.disp.run_once()
    ob = w.store.outbox[1]
    assert w.store.rows[did].status == "queued" and w.relay.keys == [] and w.changed == []
    assert ob.attempts == 0 and ob.locked_until is not None  # leased, no attempt spent...
    assert not ob.processed and not ob.dead  # ...and never dead-lettered
    assert w.metrics.names().count((SKIPPED, ("dispatch", "unreadable"))) == 1
    directory.fail, directory.everyone = None, True  # the store is back
    await w.disp.run_once()
    assert w.store.rows[did].status == "queued"  # the lease is still held
    w.clock.advance(61)
    await w.disp.run_once()
    assert w.store.rows[did].status == "sent" and w.relay.keys == [idempotency_key(did)]


async def test_dispatcher_null_owner_delivery_is_suppressed_recipient_deleted() -> None:
    directory = Directory(everyone=True)
    w = _world(directory)
    w.store.fire(["in_app", "email"])
    w.store.rows = {i: replace(r, user_id=None) for i, r in w.store.rows.items()}
    await w.disp.run_once()
    assert _outcomes(w) == [("suppressed", "recipient_deleted")] * 2
    assert directory.reads == [] and w.relay.keys == []  # nobody to ask about
    assert w.metrics.names().count((SKIPPED, ("dispatch", "inactive"))) == 2


async def test_dispatcher_reads_the_owner_fresh_for_every_delivery() -> None:
    directory = Directory(everyone=True)
    w = _world(directory)
    w.store.fire(["in_app", "desktop"])  # two deliveries of one owner, in one poll
    await w.disp.run_once()
    assert directory.reads == [{USER}, {USER}]  # the gate's cache is not consulted


async def test_dispatcher_settled_delivery_of_a_disabled_owner_is_left_alone() -> None:
    directory = Directory()
    w = _world(directory)
    (did,) = w.store.fire(["in_app"])
    w.store.rows[did] = replace(w.store.rows[did], status="sent")  # a replay after a restart
    await w.disp.run_once()
    assert w.store.rows[did].status == "sent" and w.store.outbox[1].processed
    assert directory.reads == [] and w.metrics.names() == []


async def test_dispatcher_reenabled_owner_gets_new_deliveries_only() -> None:
    directory = Directory()
    w = _world(directory)
    w.store.fire(["email"])
    await w.disp.run_once()  # queued while the owner was disabled: dropped for good
    directory.active.add(USER)
    w.store.fire(["email"])
    await w.disp.run_once()
    assert _outcomes(w) == [("suppressed", "owner_inactive"), ("sent", None)]
    assert w.relay.keys == [idempotency_key(2)]
