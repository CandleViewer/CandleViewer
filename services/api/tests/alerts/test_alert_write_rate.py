"""E40-X01 Part B (#5696): the five `/alerts` writes take a token from their caller's bucket.

Gherkin "an alert write is bounded before any work": "its 61st write within a minute" is the
declared 429 with `Retry-After`, before the body is parsed, and writes no record. The bucket (the
drawings one of #2727, an instance of its own) holds a burst and refills at the minute's rate,
read as the steady rate once the burst is spent (BQ-2); its token comes after the permission check
and before any read. The clock is a fake monotonic one: no test sleeps.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest

from candleviewer.api import alerts as alerts_module
from candleviewer.api.alert_body import MAX_ALERT_BODY_BYTES
from candleviewer.api.alerts import ALERT_WRITE_BURST, ALERT_WRITES_PER_MINUTE
from candleviewer.api.drawings_limiter import DrawingsWriteLimiter
from tests.alerts._alert_api_env import USER_B
from tests.alerts._alert_api_env import Env as AlertsEnv
from tests.alerts._alert_write_env import NO_ALERT, Clock, asgi, bucket, limited, spend
from tests.alerts._deliveries_env import Env as DeliveriesEnv

WRITES = pytest.mark.parametrize("op", ["create", "update", "delete", "enabled", "snooze"])


@WRITES
def test_alert_write_past_the_burst_is_429_and_changes_nothing(op: str) -> None:
    """Gherkin: a write past the bucket is the declared 429 with `Retry-After`, and "no record is
    written for the refused write"; nothing changes, and the refusal is counted (SR-E40-16)."""
    t = limited(op, Clock())
    spend(t)
    before = t.snapshot()
    r = t.write()
    assert (r.status_code, r.json()["code"]) == (429, "rate_limited")
    assert int(r.headers["Retry-After"]) == r.json()["retry_after_seconds"] >= 1
    assert (t.snapshot(), t.env.refused) == (before, ["rate_limited"])


def test_alert_writes_after_the_burst_are_sixty_a_minute() -> None:
    """Gherkin: "its 61st write within a minute" is a 429: once the burst is spent, 60 writes a
    second apart are taken and one more, sent with the 60th, is refused (SR-E40-16, BQ-2)."""
    clock = Clock()
    t = limited("enabled", clock)
    spend(t)
    for _ in range(ALERT_WRITES_PER_MINUTE):
        clock.t += 60.0 / ALERT_WRITES_PER_MINUTE
        assert t.write().status_code == 200
    assert t.write().status_code == 429


def test_the_bucket_the_router_builds_for_itself_takes_the_burst_then_one_a_second(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The bucket the app runs: `create_app` hands the CRUD router no limiter, so it builds its own
    (here on a stopped clock). Twenty writes across three routes are taken, and the 21st is the
    429 with a token due in one second (a burst of 20, 60 a minute; SR-E40-16)."""
    built: list[DrawingsWriteLimiter] = []

    class Stopped(DrawingsWriteLimiter):
        def __init__(self, **kwargs: Any) -> None:
            super().__init__(**kwargs, clock=lambda: 1000.0)
            built.append(self)

    monkeypatch.setattr(alerts_module, "DrawingsWriteLimiter", Stopped)
    env = AlertsEnv()  # no `limiter`: the router's own bucket
    aid = env.create()["id"]  # the first write
    writes = [("PUT", f"/alerts/{aid}/enabled", {"enabled": False}),
              ("PUT", f"/alerts/{aid}/snooze", {"until": None})]  # fmt: skip
    for i in range(ALERT_WRITE_BURST - 1):
        method, path, body = writes[i % 2]
        assert env.c.request(method, path, json=body).status_code == 200
    r = env.c.delete(f"/alerts/{aid}")
    assert (r.status_code, r.headers["Retry-After"], len(built)) == (429, "1", 1)


def test_alert_write_without_the_permission_takes_no_token() -> None:
    """C-12.4 first: a caller refused for its role spends no token (SR-E40-16)."""
    t = limited("enabled", Clock())
    t.env.perms = frozenset({"alerts:read"})
    assert {t.write().status_code for _ in range(ALERT_WRITE_BURST + 5)} == {403}
    t.env.perms = frozenset({"alerts:read", "alerts:write"})
    assert all(t.write().status_code == 200 for _ in range(ALERT_WRITE_BURST))
    assert t.write().status_code == 429


def test_alert_write_on_a_foreign_id_takes_a_token_before_the_lookup() -> None:
    """A write aimed at another user's alert spends a token before the alert is read: past the
    burst the probe is a 429 and reads nothing, so no `alert.denied` is due (SR-E40-16)."""
    t = limited("enabled", Clock())
    t.env.user = USER_B
    assert {t.write().status_code for _ in range(ALERT_WRITE_BURST)} == {404}
    assert t.write().status_code == 429
    assert t.env.audit.actions().count("alert.denied") == ALERT_WRITE_BURST and t.env.held == []


def test_alert_reads_and_inbox_writes_take_no_token() -> None:
    """Only the five `/alerts` writes take a token: the reads and the inbox's writes (bounded by
    their rows) leave the bucket full (SR-E40-16)."""
    clock = Clock()
    t = limited("enabled", clock)
    one = t.path.removesuffix("/enabled")
    for _ in range(ALERT_WRITE_BURST + 5):
        assert (t.env.c.get("/alerts").status_code, t.env.c.get(one).status_code) == (200, 200)
    inbox = DeliveriesEnv(limiter=bucket(clock))
    sent, shown = inbox.store.add(), inbox.store.add(channel="desktop", status="queued")
    for _ in range(ALERT_WRITE_BURST + 5):
        inbox.c.post(f"/alerts/deliveries/{sent.id}/ack")
        inbox.c.post("/alerts/deliveries/ack-all")
        inbox.c.post(f"/alerts/deliveries/{shown.id}/desktop-outcome",
                     json={"outcome": "shown", "permission": "granted"})  # fmt: skip
    probe = f"/alerts/{NO_ALERT}/enabled"  # the inbox app's CRUD router: no such alert, a 404
    assert {inbox.c.put(probe, json=t.body).status_code for _ in range(ALERT_WRITE_BURST)} == {404}
    assert inbox.c.put(probe, json=t.body).status_code == 429
    spend(t)
    assert t.write().status_code == 429


def test_each_user_has_their_own_alert_write_bucket() -> None:
    """The bucket is per acting user: one user's spent burst refuses no one else (SR-E40-16)."""
    t = limited("create", Clock())
    spend(t)
    assert t.write().status_code == 429
    t.env.user = USER_B
    assert t.write().status_code == 201


async def test_alert_write_429_reads_none_of_an_oversized_body() -> None:
    """Gherkin: the 429 comes "before parsing the body": past the burst no chunk of a body, even
    one over the byte cap, is read, and only the rate refusal is counted (SR-E40-16)."""
    t, pulled = limited("enabled", Clock()), []
    spend(t)

    async def chunks() -> AsyncIterator[bytes]:
        for _ in range(32):
            pulled.append(1)
            yield b" " * (MAX_ALERT_BODY_BYTES // 16)

    r = await asgi(t, chunks())
    assert r.status_code == 429 and pulled == [] and t.env.refused == ["rate_limited"]
