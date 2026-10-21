"""E40-T04 dispatcher: exactly-once under restart, disabled channels, loop robustness."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from _dispatch_env import Clock, MemStore
from test_alert_dispatcher import FailingRelay, Metrics, _disp

from candleviewer.alerts.dispatcher import (
    CHANNELS,
    AlertDispatcher,
    EmailAdapter,
    Outcome,
    default_adapters,
)
from tests.alerts._owners_env import allow


async def test_restart_with_pending_outbox_delivers_exactly_once() -> None:
    """Crash after the adapter ran but before settle: the lease expires, the row is replayed,
    the delivery ends `sent` once; replaying an already-settled row is a no-op."""
    clock = Clock()
    store = MemStore(clock)
    store.fire(["in_app", "email"])
    relay = FailingRelay(fail=0)
    real = store.settle_sent

    async def crash(job: Any, **kw: Any) -> bool:
        raise ConnectionError("process died before commit")

    store.settle_sent = crash  # type: ignore[method-assign]  # fault injection
    await _disp(store, clock, relay).run_once()
    assert {r.status for r in store.rows.values()} == {"queued"}
    store.settle_sent = real  # type: ignore[method-assign]  # "restart"
    d2 = AlertDispatcher(store, default_adapters(relay), worker="w2", now=clock, owners=allow())
    await d2.run_once()  # lease still held by the dead worker
    assert {r.status for r in store.rows.values()} == {"queued"}
    clock.advance(61)
    await d2.run_once()
    sent_after_restart = relay.sent
    assert [r.status for r in store.rows.values()] == ["sent", "sent"]
    # a duplicate outbox insert is refused by the unique (topic, dedup_key) index
    assert store.add_outbox(1) is False and store.add_outbox(2) is False
    # a replay of an already-settled row never re-invokes the adapter
    for o in store.outbox.values():
        o.processed = False
    await d2.run_once()
    assert relay.sent == sent_after_restart
    assert [r.status for r in store.rows.values()] == ["sent", "sent"]
    assert store.calls.count("sent") == 2


async def test_webhook_and_push_registered_but_disabled_suppressed() -> None:
    clock = Clock()
    store = MemStore(clock)
    store.fire(["webhook", "push", "email"])
    await _disp(store, clock, None).run_once()
    assert [r.status for r in store.rows.values()] == ["suppressed"] * 3
    assert store.rows[2].error_message == "push_unavailable"
    assert dict(store.rows[2].context)["suppression_reason"] == "push_unavailable"
    assert set(default_adapters(None)) == set(CHANNELS)
    with pytest.raises(ValueError, match="E40-S03"):
        default_adapters(None, webhook_enabled=True)


def test_unregistered_channel_refused_at_construction() -> None:
    clock = Clock()
    with pytest.raises(ValueError, match="unregistered"):
        AlertDispatcher(MemStore(clock), {}, worker="w", now=clock, owners=allow())


async def test_one_bad_row_does_not_stall_the_batch() -> None:
    clock = Clock()
    store = MemStore(clock)
    store.fire(["in_app", "in_app"])
    real = store.load

    async def flaky(did: int) -> Any:
        if did == 1:
            raise RuntimeError("boom")
        return await real(did)

    store.load = flaky  # type: ignore[method-assign]  # fault injection
    assert await _disp(store, clock).run_once() == 2
    assert store.rows[1].status == "queued" and store.rows[2].status == "sent"


async def test_email_timeout_and_deleted_recipient() -> None:
    class Hang:
        async def send(self, **_: Any) -> None:
            await asyncio.Event().wait()

    clock = Clock()
    store = MemStore(clock)
    store.fire(["email"])
    out = await EmailAdapter(Hang(), timeout_s=0.01).deliver(store.rows[1])
    assert out == Outcome("retry", "email relay timeout")
    store.fire(["email"], user=None)  # type: ignore[arg-type]  # ON DELETE SET NULL
    out = await EmailAdapter(FailingRelay(0)).deliver(store.rows[2])
    assert out.kind == "disabled"


async def test_latency_and_attempt_metrics_on_sent() -> None:
    clock, metrics = Clock(), Metrics()
    store = MemStore(clock)
    store.fire(["in_app"])
    clock.advance(0.25)
    await _disp(store, clock, metric=metrics).run_once()
    assert ("cv_alert_delivery_latency_seconds", ("in_app",), 0.25) in metrics.seen
    assert ("cv_alert_delivery_attempts", (), 1) in metrics.seen


async def test_start_notify_stop_runs_in_tracked_task() -> None:
    clock = Clock()
    store = MemStore(clock)
    done = asyncio.Event()

    async def on_change(_ids: Any) -> None:
        done.set()

    d = _disp(store, clock, on_change=on_change, interval_s=3600)
    d.start()
    d.start()  # idempotent
    store.fire(["in_app"])
    d.notify()
    async with asyncio.timeout(5):
        await done.wait()
    await d.stop()
    await d.stop()
    assert store.rows[1].status == "sent"


async def test_poll_loop_survives_store_outage() -> None:
    clock = Clock()
    store = MemStore(clock)
    hit = asyncio.Event()
    calls = 0

    async def broken(**_: Any) -> list[Any]:
        nonlocal calls
        calls += 1
        if calls >= 2:
            hit.set()
        raise OSError("db down")

    store.claim = broken  # type: ignore[method-assign]  # fault injection
    d = _disp(store, clock, interval_s=0.001)
    d.start()
    async with asyncio.timeout(5):
        await hit.wait()
    await d.stop()
