"""E40-T04 dispatcher: per-channel rows, retry/backoff, terminal failure, exactly-once."""

from __future__ import annotations

from typing import Any

import pytest
from _dispatch_env import Clock, MemStore

from candleviewer.alerts.dispatcher import (
    AlertDispatcher,
    EmailError,
    IllegalTransition,
    backoff_seconds,
    check_transition,
    default_adapters,
)
from tests.alerts._owners_env import allow


class FailingRelay:
    def __init__(self, fail: int = 10**6, status: int | None = 500) -> None:
        self.fail, self.status, self.sent = fail, status, 0
        self.keys: list[str] = []

    async def send(self, *, user_id: str, subject: str, body: str, idempotency_key: str) -> None:
        self.keys.append(idempotency_key)
        self.sent += 1
        if self.sent <= self.fail:
            raise EmailError("relay returned 500", self.status)


class Metrics:
    def __init__(self) -> None:
        self.seen: list[tuple[str, tuple[str, ...], float]] = []

    def __call__(self, name: str, labels: tuple[str, ...]) -> Any:
        m = self

        class _C:
            def inc(self, amount: float = 1) -> None:
                m.seen.append((name, labels, amount))

            def observe(self, amount: float) -> None:
                m.seen.append((name, labels, amount))

            def set(self, value: float) -> None:
                m.seen.append((name, labels, value))

        return _C()

    def names(self) -> list[tuple[str, tuple[str, ...]]]:
        return [(n, lab) for n, lab, _ in self.seen]


def _disp(store: MemStore, clock: Clock, relay: Any = None, **kw: Any) -> AlertDispatcher:
    return AlertDispatcher(store, default_adapters(relay), worker="w1", now=clock,
                           rng=lambda: 1.0, owners=allow(), **kw)  # fmt: skip


async def _drain(d: AlertDispatcher, clock: Clock, rounds: int = 20) -> None:
    for _ in range(rounds):
        await d.run_once()
        clock.advance(301)


def test_legal_transitions_and_illegal_raises() -> None:
    for old, new in [("queued", "sent"), ("queued", "failed"), ("queued", "suppressed"),
                     ("sent", "acked")]:  # fmt: skip
        check_transition(old, new)
    for old, new in [("sent", "queued"), ("failed", "sent"), ("acked", "sent"),
                     ("suppressed", "sent"), ("queued", "acked")]:  # fmt: skip
        with pytest.raises(IllegalTransition):
            check_transition(old, new)


def test_backoff_is_exponential_capped_and_jittered() -> None:
    assert [backoff_seconds(n, lambda: 1.0) for n in range(4)] == [1, 2, 4, 8]
    assert backoff_seconds(20, lambda: 1.0) == 300
    assert backoff_seconds(3, lambda: 0.0) == 4  # jitter floor = half
    assert backoff_seconds(-1, lambda: 1.0) == 1


async def test_firing_in_app_and_desktop_two_rows_in_app_sent_desktop_awaits_shell() -> None:
    clock = Clock()
    store = MemStore(clock)
    changed: list[list[int]] = []

    async def on_change(ids: Any) -> None:
        changed.append(list(ids))

    ids = store.fire(["in_app", "desktop"])
    await _disp(store, clock, on_change=on_change).run_once()
    assert len(ids) == 2
    assert store.rows[1].status == "sent" and store.rows[1].attempt == 1
    assert store.rows[2].status == "queued"  # sent only once the shell confirms
    assert all(o.processed for o in store.outbox.values())
    assert changed == [[1, 2]]  # both pushed on the alerts topic


async def test_email_500_every_attempt_fails_once_record_untouched() -> None:
    clock, metrics = Clock(), Metrics()
    store = MemStore(clock)
    store.fire(["in_app", "email"])
    relay = FailingRelay()
    await _drain(_disp(store, clock, relay, metric=metrics), clock)
    email = store.rows[2]
    assert email.status == "failed" and email.error_message == "relay returned 500"
    assert email.http_status == 500 and email.attempt == 8 and relay.sent == 8
    assert store.rows[1].status == "sent" and store.rows[1].error_message is None
    notices = [r for r in store.rows.values() if dict(r.context).get("channel_failure")]
    assert len(notices) == 1 and notices[0].channel == "in_app"
    assert notices[0].title.startswith("email delivery failed")
    assert store.outbox[2].dead and not store.outbox[2].processed
    assert store.calls.count("failed") == 1
    assert ("cv_outbox_dead_total", ("alert.deliver",)) in metrics.names()
    assert ("cv_alert_delivery_total", ("email", "failed")) in metrics.names()


async def test_retry_mirrors_attempt_and_backs_off_until_success() -> None:
    clock = Clock()
    store = MemStore(clock)
    store.fire(["email"])
    d = _disp(store, clock, FailingRelay(fail=2))
    await d.run_once()
    assert store.rows[1].status == "queued" and store.rows[1].attempt == 1
    assert store.calls[-1] == "retry:1.000"
    await d.run_once()  # not yet available: backoff respected
    assert store.calls == ["retry:1.000"]
    clock.advance(1)
    await d.run_once()
    assert store.calls[-1] == "retry:2.000" and store.rows[1].attempt == 2
    clock.advance(2)
    await d.run_once()
    assert store.rows[1].status == "sent" and store.rows[1].attempt == 3


async def test_max_attempts_comes_from_outbox_row() -> None:
    clock = Clock()
    store = MemStore(clock)
    store.fire(["email"], max_attempts=2)
    await _drain(_disp(store, clock, FailingRelay()), clock)
    assert store.rows[1].status == "failed" and store.rows[1].attempt == 2
