"""E40-T04 review round 2: two pollers, crash replay, drain on stop, poison rows, redaction."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from _dispatch_env import Clock, MemStore
from test_alert_dispatcher import FailingRelay, _disp

from candleviewer.alerts.dispatcher import (
    AlertDispatcher,
    DisabledAdapter,
    EmailError,
    default_adapters,
    idempotency_key,
)
from tests.alerts._owners_env import allow

#: Key-shaped (18-36 alnum) value built at runtime so no secret-shaped literal is committed.
_FAKE_TOKEN = "".join(chr(65 + i % 26) for i in range(24))


class SlowRelay:
    """Yields mid-send so two pollers interleave; counts sends per delivery key."""

    def __init__(self) -> None:
        self.keys: list[str] = []

    async def send(self, *, user_id: str, subject: str, body: str, idempotency_key: str) -> None:
        self.keys.append(idempotency_key)
        await asyncio.sleep(0)  # yield to the other poller (no wall-clock wait)


async def test_two_concurrent_pollers_send_each_row_exactly_once() -> None:
    """MemStore.claim leases each row atomically (FOR UPDATE SKIP LOCKED semantics)."""
    clock = Clock()
    store = MemStore(clock)
    ids = store.fire(["email"] * 20)
    relay = SlowRelay()
    d1 = AlertDispatcher(
        store, default_adapters(relay), worker="a", now=clock, batch=5, owners=allow()
    )
    d2 = AlertDispatcher(
        store, default_adapters(relay), worker="b", now=clock, batch=5, owners=allow()
    )
    for _ in range(6):
        await asyncio.gather(d1.run_once(), d2.run_once())
    assert sorted(relay.keys) == sorted(idempotency_key(i) for i in ids)
    assert len(relay.keys) == len(set(relay.keys)) == 20
    assert all(r.status == "sent" for r in store.rows.values())
    assert store.calls.count("sent") == 20


async def test_crash_after_final_failure_then_restart_one_notice_exactly_once() -> None:
    clock = Clock()
    store = MemStore(clock)
    store.fire(["email"], max_attempts=2)
    relay = FailingRelay()
    real = store.settle_failed

    async def crash(job: Any, **kw: Any) -> bool:
        raise ConnectionError("process died before commit")

    d = _disp(store, clock, relay)
    await d.run_once()  # attempt 1 -> retry
    clock.advance(2)
    store.settle_failed = crash  # type: ignore[method-assign]  # fault injection
    await d.run_once()  # attempt 2 fails terminally, settle never commits
    assert store.rows[1].status == "queued"
    store.settle_failed = real  # type: ignore[method-assign]  # "restart"
    d2 = AlertDispatcher(store, default_adapters(relay), worker="w2", now=clock, owners=allow())
    clock.advance(61)  # dead worker's lease expires
    for _ in range(3):
        await d2.run_once()
        clock.advance(61)
    notices = [r for r in store.rows.values() if dict(r.context).get("channel_failure")]
    assert store.rows[1].status == "failed" and len(notices) == 1
    assert store.calls.count("failed") == 1


async def test_email_send_carries_stable_idempotency_key_across_crash_replay() -> None:
    clock = Clock()
    store = MemStore(clock)
    store.fire(["email"])
    relay = FailingRelay(fail=0)
    real = store.settle_sent

    async def crash(job: Any, **kw: Any) -> bool:
        raise ConnectionError("died")

    store.settle_sent = crash  # type: ignore[method-assign]  # fault injection
    await _disp(store, clock, relay).run_once()
    store.settle_sent = real  # type: ignore[method-assign]
    clock.advance(61)
    await _disp(store, clock, relay).run_once()
    # at-least-once externally (documented); the relay dedupes on the same key
    assert relay.keys == [idempotency_key(1)] * 2 and store.rows[1].status == "sent"


async def test_stop_drains_in_flight_send_without_loss_or_duplicate() -> None:
    clock = Clock()
    store = MemStore(clock)
    store.fire(["email"])
    started, release = asyncio.Event(), asyncio.Event()
    sent: list[str] = []

    class Blocking:
        async def send(self, **kw: Any) -> None:
            started.set()
            await release.wait()
            sent.append(kw["idempotency_key"])

    d = _disp(store, clock, Blocking())
    d.start()
    await started.wait()
    stopper = asyncio.ensure_future(d.stop(grace_s=5.0))
    await asyncio.sleep(0)
    assert not stopper.done()  # waits for the send, does not cancel it
    release.set()
    await stopper
    assert sent == [idempotency_key(1)] and store.rows[1].status == "sent"


async def test_stop_cancels_after_grace_and_row_is_replayed_later() -> None:
    clock = Clock()
    store = MemStore(clock)
    store.fire(["email"])
    started = asyncio.Event()

    class Hang:
        async def send(self, **_: Any) -> None:
            started.set()
            await asyncio.Event().wait()

    d = AlertDispatcher(store, default_adapters(Hang()), worker="w", now=clock, owners=allow())
    d.start()
    await started.wait()
    await d.stop(grace_s=0.01)
    assert store.rows[1].status == "queued"
    clock.advance(61)
    await _disp(store, clock, FailingRelay(fail=0)).run_once()
    assert store.rows[1].status == "sent"


async def test_poison_row_counts_attempts_and_dead_letters() -> None:
    class Boom:
        async def send(self, **_: Any) -> None:
            raise RuntimeError("bug")

    clock = Clock()
    store = MemStore(clock)
    store.fire(["email"], max_attempts=3)
    d = _disp(store, clock, Boom())
    for _ in range(6):
        await d.run_once()
        clock.advance(301)
    assert store.rows[1].status == "failed" and store.outbox[1].dead
    assert store.outbox[1].attempts == 3
    assert store.rows[1].error_message == "adapter_error: RuntimeError"


async def test_relay_error_text_is_redacted_before_storage() -> None:
    class Leaky:
        async def send(self, **_: Any) -> None:
            raise EmailError("relay said " + _FAKE_TOKEN, 401)

    clock = Clock()
    store = MemStore(clock)
    store.fire(["email"], max_attempts=1)
    await _disp(store, clock, Leaky()).run_once()
    msg = store.rows[1].error_message or ""
    assert _FAKE_TOKEN not in msg and "redacted" in msg
    assert _FAKE_TOKEN not in (store.outbox[1].last_error or "")


def test_suppression_reason_is_a_bounded_enum() -> None:
    with pytest.raises(ValueError, match="unknown suppression reason"):
        DisabledAdapter("free text")
