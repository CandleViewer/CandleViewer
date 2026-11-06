"""E40-Q02 alert chaos 1, kill mid-fire: SIGKILL the API between the delivery insert and the
outbox poller run, and mid-dispatch; on restart every delivery is settled exactly once and no
firing is lost. CI-only (`chaos and integration`, the compose Postgres, migrated).

A child (`_child`) commits one firing through the production transaction and parks in the
dispatcher wake that follows the commit (or, second case, runs one poll and parks inside the email
relay after `in_app` settled); the parent SIGKILLs it. After the "restart" (fresh objects):

- the firing is whole: `fire_count` 1, one delivery per channel, one outbox row each;
- a fresh dispatcher settles every row `sent`, each by exactly one winning settle; a second poll
  and a duplicate outbox insert change nothing (`ux_outbox_dedup`, `ON CONFLICT DO NOTHING`);
- the email relay receives the delivery's stable idempotency key: once after a kill before the
  poll, and again (the same key, the relay dedupes on it) after a kill inside the send, the
  documented at-least-once window of the external effect.

Every wait is bounded and polls a condition (`st.until`), never a bare sleep.
"""

from __future__ import annotations

import signal

import pytest

from candleviewer.alerts.dispatcher import idempotency_key
from candleviewer.alerts.outbox import TOPIC_ALERT_DELIVER
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from tests.chaos.alerts._pg import (
    WAIT_S,
    Child,
    depth,
    dispatcher,
    fetch,
    fire,
    firing_store,
    ledger,
    seeded,
)
from tests.chaos.alerts._rig import Relay, Wins
from tests.chaos.storage import _stack as st

pytestmark = [pytest.mark.chaos, pytest.mark.integration]


@pytest.fixture(autouse=True)
async def _postgres_up() -> None:
    await st.ensure_up("postgres", st.pg_up)


async def _killed(order: dict[str, str], point: str) -> list[str]:
    child = await Child.spawn(order)
    try:
        await child.until(f"parked {point}")
    finally:
        code = await child.kill()
    assert code == -signal.SIGKILL
    return [s.removeprefix("@@ ").strip() for s in child.seen if s.startswith("@@ send ")]


async def _restart_and_drain(alert: str) -> tuple[Relay, Wins]:
    repo = SqlAlchemyRelationalRepository(st.pg_dsn(), "alert-chaos-restart")
    relay, wins = Relay(), Wins()
    d = dispatcher(repo, relay, worker="restart", metric=wins)
    try:

        async def settled() -> bool:
            await d.run_once()  # a row the dead worker leased is claimed once its lease ran out
            return all(r["status"] == "sent" for r in (await ledger(alert))["rows"])

        await st.until(settled, "every delivery settled after the restart", timeout_s=WAIT_S)
        await d.run_once()  # a replay of settled rows is a no-op
    finally:
        await repo.dispose()
    return relay, wins


async def _assert_exactly_once(alert: str) -> list[int]:
    led = await ledger(alert)
    rows = led["rows"]
    assert led["fire_count"] == 1 and [r["channel"] for r in rows] == ["in_app", "email"]
    assert all(r["ob"] == 1 and r["done"] and r["status"] == "sent" for r in rows), rows
    for r in rows:  # the producer side: a re-insert of the outbox row is refused
        await fetch(
            "INSERT INTO outbox (topic, dedup_key, payload) VALUES ($1, $2, '{}'::jsonb) "
            "ON CONFLICT (topic, dedup_key) DO NOTHING", TOPIC_ALERT_DELIVER, str(r["id"]),
        )  # fmt: skip
    assert [r["ob"] for r in (await ledger(alert))["rows"]] == [1, 1]
    return [int(r["id"]) for r in rows]


async def test_kill_between_the_delivery_insert_and_the_poll_delivers_once_on_restart() -> None:
    user, alert = await seeded()
    await _killed({"mode": "fire", "user": user, "alert": alert}, "fire")
    pending = (await ledger(alert))["rows"]
    assert [(r["status"], r["ob"]) for r in pending] == [("queued", 1), ("queued", 1)]
    assert await depth(alert) == 2  # the committed firing waits in the outbox: nothing lost
    relay, wins = await _restart_and_drain(alert)
    _, email = await _assert_exactly_once(alert)
    assert wins.sent == 2 and relay.keys == [idempotency_key(email)]


async def test_kill_inside_the_email_send_settles_once_and_resends_the_same_key() -> None:
    user, alert = await seeded()
    repo = SqlAlchemyRelationalRepository(st.pg_dsn(), "alert-chaos-seed")
    try:
        assert await fire(firing_store(repo), user, alert, ("in_app", "email")) is not None
    finally:
        await repo.dispose()
    sent_by_child = await _killed(
        {"mode": "send", "user": user, "alert": alert, "lease_s": "1"}, "send"
    )
    rows = (await ledger(alert))["rows"]
    assert [r["status"] for r in rows] == ["sent", "queued"]  # in_app settled before the kill
    relay, wins = await _restart_and_drain(alert)
    _, email = await _assert_exactly_once(alert)
    assert sent_by_child == [f"send {idempotency_key(email)}"]
    assert wins.sent == 1 and relay.keys == [idempotency_key(email)]  # the same key, once more
