"""B13 `ws_conn` on its private path (`is_private`) through the factory (G-8b, #3963).

A fake private runtime, as `test_b13_ws_conn.py`'s public one: `connecting` goes to
`authenticating` (`ws_auth`) before `subscribing`; an `auth` failure backs off; `SHUTDOWN` from
`backing_off` closes, which is how the stream ends after three refused `auth`s (ruling 10); and
`KILL` while `ws_auth` is in flight cancels it, which a revoke relies on (SR-E27-17). A real
runtime proves INV-B13-e: the pong deadline is an absolute time held outside the chart, armed on
each `live` entry and re-armed by every frame; the chart is never sent `PONG`. B13 arms no timer
of its own, so the factory's default clock serves.
"""

from __future__ import annotations

import asyncio
from typing import Any

from candleviewer.exchange.bybit.private_stream import WATCHDOG_S
from candleviewer.statechart import build
from candleviewer.statechart.bindings import b13_ws_conn as b13
from candleviewer.statechart.factory import default_clock
from tests.chaos.ingestion._clock import VirtualClock
from tests.unit.exchange.bybit._private_venue import Consumer, PrivateVenue, make_streams, until
from tests.unit.exchange.bybit._trading import account


class _Rt:
    """The private runtime's hooks, recorded; `auth` fails or hangs as a case asks."""

    attempt = 0

    def __init__(self, *, auth_fails: bool = False, auth_hangs: bool = False) -> None:
        self.auth_fails, self.auth_hangs = auth_fails, auth_hangs
        self.health: list[str] = []
        self.calls: list[str] = []
        self.auth_cancelled = False

    def is_private(self) -> bool:
        return True

    def budget_exhausted(self) -> bool:
        return False

    async def open_socket(self) -> None:
        self.calls.append("open")

    async def authenticate(self) -> None:
        self.calls.append("auth")
        if self.auth_hangs:
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.auth_cancelled = True
                raise
        if self.auth_fails:
            raise ConnectionError("the private stream's auth was not granted")

    async def subscribe(self) -> None:
        self.calls.append("subscribe")

    async def close_socket(self) -> None:
        self.calls.append("close")

    async def teardown_session(self) -> None: ...
    def start_session(self, interp: object) -> None: ...
    def schedule_backoff(self, interp: object) -> None: ...
    def schedule_budget_recheck(self, interp: object) -> None: ...

    async def emit_health(self, state: str) -> None:
        self.health.append(state)

    def reset_attempt(self) -> None: ...
    def bump_attempt(self) -> None: ...


async def _drive(rt: _Rt, key: str, *events: str, after_auth: bool = False) -> set[str]:
    """Send each event and let the chart settle; with `after_auth`, the events after `CONNECT`
    wait until `ws_auth` is in flight."""
    b13.register_runtime(key, rt)
    try:
        r = await build(
            "ws_conn",
            ctx={"conn_key": key, "kind": "private"},
            clock=default_clock(),
            lane="platform",
        )
        for ev in events:
            await r.interpreter.send(ev, wait=True)
            for _ in range(50):
                if not after_auth or "auth" in rt.calls:
                    break
                await asyncio.sleep(0)
        for _ in range(50):
            await asyncio.sleep(0)
        ids = {s.rsplit(".", 1)[-1] for s in r.interpreter.current_state_ids}
        await r.interpreter.stop()
        return ids
    finally:
        b13.unregister_runtime(key)


async def test_a_private_connection_authenticates_before_it_subscribes() -> None:
    rt = _Rt()
    ids = await _drive(rt, "p1", "CONNECT")
    assert "live" in ids and rt.calls == ["open", "auth", "subscribe"] and rt.health == ["healthy"]


async def test_an_auth_failure_backs_off_and_never_subscribes() -> None:
    rt = _Rt(auth_fails=True)
    ids = await _drive(rt, "p2", "CONNECT")
    assert "backing_off" in ids and rt.calls == ["open", "auth"] and rt.health == ["degraded"]


async def test_shutdown_from_backing_off_closes_the_private_connection() -> None:
    """Ruling 10's terminal path: the runtime sends `SHUTDOWN` instead of `BACKOFF_DUE`."""
    rt = _Rt(auth_fails=True)
    ids = await _drive(rt, "p3", "CONNECT", "SHUTDOWN")
    assert "closed" in ids and rt.calls == ["open", "auth", "close"]


async def test_kill_while_auth_is_in_flight_cancels_it() -> None:
    """SR-E27-17: a revoke stops B13 with `KILL` in `authenticating`; the library cancels the
    `ws_auth` service on leaving the state, so a signed `auth` is never awaited further."""
    rt = _Rt(auth_hangs=True)
    ids = await _drive(rt, "p4", "CONNECT", "KILL", after_auth=True)
    assert "closed" in ids and rt.calls == ["open", "auth"] and rt.auth_cancelled


async def test_inv_b13_e_deadline_absolute_outside_chart() -> None:
    """INV-B13-e on the real runtime: the deadline is an absolute time on the runtime's
    monotonic clock, armed when the socket goes live (a reconnect re-arms it, as a restore
    would) and re-armed by every frame; B13 is sent no `PONG`, only `PONG_DEADLINE` once."""
    clock = VirtualClock()
    venue = PrivateVenue(clock)
    streams = make_streams(venue)
    consumer = Consumer(await streams.open(account()))
    await until(clock, lambda: len(consumer.statuses()) == 2, within_s=5, what="live")
    [conn] = streams._conns.values()
    assert conn._deadline == clock.now + WATCHDOG_S  # armed on `live`
    sent: list[str] = []
    real = conn._interp.send

    def recording(event: str, *args: Any, **kwargs: Any) -> Any:
        sent.append(event)
        return real(event, *args, **kwargs)

    conn._interp.send = recording
    await clock.advance(7)
    assert conn._deadline == clock.now - 2 + WATCHDOG_S  # re-armed by the pong at +5 s
    venue.pongs = False
    await until(clock, lambda: "down:pong_timeout:1" in consumer.statuses(), within_s=15, what="d")
    assert sent == ["PONG_DEADLINE"]
    venue.pongs = True
    conn._interp.send = real
    live = "resyncing:reconnected:2"
    await until(clock, lambda: live in consumer.statuses(), within_s=30, what="relive")
    assert conn._deadline == clock.now + WATCHDOG_S  # armed again on the new socket's `live`
    await consumer.stop()
    await streams.aclose()
