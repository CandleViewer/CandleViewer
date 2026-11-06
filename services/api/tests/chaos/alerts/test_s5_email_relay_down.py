"""E40-Q02 alert chaos 5, email relay down: per-channel failure isolation. In-process: the real
dispatcher over the in-memory dispatch store (`tests.alerts._dispatch_env`, the Postgres settle
semantics), a relay stand-in that refuses every message while it is down, fake clock.

A burst of firings on `in_app` + `email` meets a relay outage. Every in-app record is `sent` on
the first poll, untouched by the email retries behind it. Each email delivery that exhausts its
attempts is `failed` with ONE channel-failure notice (not one per attempt, and a replay of its dead
outbox row raises none), and an email queued while the relay was down but retried after it came
back is sent with no notice at all.
"""

from __future__ import annotations

from typing import Any

import pytest

from candleviewer.alerts.dispatcher import EmailError
from tests.alerts._dispatch_env import Clock, MemStore
from tests.chaos.alerts._rig import dispatch

pytestmark = pytest.mark.chaos
FIRINGS, MAX_ATTEMPTS = 6, 4


class Relay:
    """Refuses every message while `down`; counts what it was asked to send."""

    def __init__(self) -> None:
        self.down, self.attempts, self.delivered = True, 0, list[str]()

    async def send(self, *, user_id: str, subject: str, body: str, idempotency_key: str) -> None:
        self.attempts += 1
        if self.down:
            raise EmailError("relay connection refused", 503)
        self.delivered.append(idempotency_key)


def _notices(store: MemStore) -> list[Any]:
    return [r for r in store.rows.values() if dict(r.context).get("channel_failure")]


async def test_a_relay_outage_fails_email_alone_with_one_notice_per_failed_delivery() -> None:
    clock, relay = Clock(), Relay()
    store = MemStore(clock)
    early = [store.fire(["in_app", "email"], max_attempts=MAX_ATTEMPTS) for _ in range(FIRINGS)]
    d = dispatch(store, relay, worker="w", rng=lambda: 1.0)
    await d.run_once()
    in_app = [ids[0] for ids in early]
    assert [store.rows[i].status for i in in_app] == ["sent"] * FIRINGS  # first poll, unaffected
    for _ in range(MAX_ATTEMPTS + 2):  # the outage outlasts every early email's attempts
        clock.advance(301)
        await d.run_once()
    emails = [ids[1] for ids in early]
    assert all(store.rows[i].status == "failed" for i in emails)
    assert relay.attempts == FIRINGS * MAX_ATTEMPTS
    notices = _notices(store)
    assert len(notices) == FIRINGS  # one per failed delivery, never one per attempt
    assert all(n.channel == "in_app" and n.status == "sent" for n in notices)
    assert all(store.rows[i].status == "sent" and store.rows[i].attempt == 1 for i in in_app)

    late = store.fire(["in_app", "email"], max_attempts=MAX_ATTEMPTS)  # queued during the outage
    await d.run_once()
    assert store.rows[late[1]].status == "queued" and store.rows[late[1]].attempt == 1
    relay.down = False  # the relay is back before its attempts run out
    clock.advance(301)
    await d.run_once()
    assert store.rows[late[1]].status == "sent" and relay.delivered == [f"alert-delivery-{late[1]}"]
    assert len(_notices(store)) == FIRINGS  # recovered in time: no notice

    attempts = relay.attempts
    for o in store.outbox.values():  # a replay of every dead row (a restart re-reading them)
        o.dead, o.locked_until = False, None
    await d.run_once()
    assert len(_notices(store)) == FIRINGS and store.calls.count("failed") == FIRINGS
    assert relay.attempts == attempts  # a settled delivery is never sent again
