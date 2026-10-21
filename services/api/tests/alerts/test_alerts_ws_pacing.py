"""E40-T04 PR-B (#1016 scope, "Backpressure"): the `alerts` topic behind the flag-on outbound
pipeline (`ConnectionPipeline` + `Pacer`, 23-ws-protocol.md §8.1-§8.4, §10.1), attached as
`run_auth` attaches it, with the topic itself as the snapshot source. Its deltas leave in 250 ms
windows, whole and in order (no merge rule: an `AlertUpdate` is never folded); a burst past a
window's frame bound drops the window for a `backpressure` snapshot of the owner's current set,
never a truncated one, even when the topic must first load that set."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any, cast
from uuid import UUID

import pytest
from fastapi import WebSocket

from candleviewer.alerts.ws_topic import delivery_item
from candleviewer.ws.backpressure_config import BackpressureConfig
from candleviewer.ws.coalescing import MAX_PENDING_FRAMES
from candleviewer.ws.gateway import _Connection
from candleviewer.ws.lifecycle import bye_frame
from candleviewer.ws.permissions import ConnectionAuthz, Subscription, SubscriptionServices
from candleviewer.ws.pipeline import ConnectionPipeline
from candleviewer.ws.sequencing import TopicEmitter
from tests.alerts._alerts_ws import USER_A, USER_B, World, principal
from tests.unit.ws._seq_support import Clock, validate

BASE_MS = 1_790_000_000_000
WINDOW_S = 0.25  # the family's default throttle (23 §6.2.1, topics.py)


@pytest.fixture
async def world() -> AsyncIterator[World]:
    """The topic with its worker running, as the gateway's module runs it; stopped at the end."""
    w = World()
    w.topic.start()
    yield w
    await w.topic.stop()


class Paced:
    """One `alerts` socket behind the flag-on pipeline, registered on the world's hub."""

    def __init__(self, world: World, user: UUID) -> None:
        self.clock = Clock()
        self.clock.now = 100.0
        self.closed: list[str] = []
        self.authz = ConnectionAuthz(
            principal(user), SubscriptionServices(snapshots=world.topic), clock=self.clock
        )
        self.emitter = TopicEmitter(
            lambda _frame: None, connection_id="ws_test", wall_ms=lambda: BASE_MS,
            clock=self.clock, source=world.topic,
        )  # fmt: skip
        self.pipe = ConnectionPipeline(
            encoding="cv.v1.json", config=BackpressureConfig(), close=self._close,
            wall_ms=lambda: BASE_MS, connection_id="ws_test",
        )  # fmt: skip
        shell = _Connection(
            cast(WebSocket, None), encoding="cv.v1.json", clock=self.clock,
            wall_ms=lambda: BASE_MS, auth_timeout_s=10.0,
        )  # fmt: skip
        shell.authz, shell.pipeline = self.authz, self.pipe
        self.pipe.attach(self.authz, self.emitter, shell.push_system)
        self.emitter.push = self.pipe.push
        world.hub.register(self.authz, self.pipe)

    def _close(self, reason: str, *, bye: dict[str, Any] | None = None) -> None:
        self.closed.append(reason)
        frame = bye or bye_frame(reason, now_ms=BASE_MS)
        self.pipe.close(frame, int(frame["p"]["code"]), flush=reason != "slow_consumer")

    def sub(self) -> Subscription:
        _, sub = self.authz.admit({"ch": "alerts"})
        assert sub is not None
        sub.announced = True  # the gateway's `sub_ok` is queued (#2831)
        self.pipe.flush_pending([sub])
        return sub

    def at(self, now: float) -> None:
        """A writer turn at `now`: closes the windows due, drains what the ladder holds."""
        self.clock.now = now
        self.pipe.service(now)

    def frames(self) -> list[dict[str, Any]]:
        out = []
        while (item := self.pipe.queue.pop()) is not None:
            frame = json.loads(item.payload)
            validate(frame)
            out.append(frame)
        return out


def _update(world: World, user: UUID, n: int) -> dict[str, Any]:
    """A one-delivery `AlertUpdate` for `user`, as the topic's worker publishes it."""
    row = world.reader.add(user)
    return {"deliveries": [delivery_item(row)], "unacked_count": n}


async def _subscribed(world: World, user: UUID = USER_A) -> tuple[Paced, Subscription]:
    paced = Paced(world, user)
    sub = paced.sub()
    await world.loads()  # the first build loads the owner's view, then flushes the pending snap
    [snap] = paced.frames()
    assert (snap["t"], snap["p"]["unacked_count"]) == ("snap", 0)
    return paced, sub


async def test_deltas_leave_in_250_ms_windows_whole_and_in_order(world: World) -> None:
    paced, _ = await _subscribed(world)
    first, *rest = [_update(world, USER_A, n) for n in range(1, 5)]
    assert world.hub.publish("alerts", first, user=USER_A) == 1
    [now] = paced.frames()  # the window's leading update leaves at once
    for body in rest:
        world.hub.publish("alerts", body, user=USER_A)
    assert paced.frames() == []
    paced.at(100.0 + WINDOW_S - 0.001)
    assert paced.frames() == []
    paced.at(100.0 + WINDOW_S)
    window = paced.frames()
    assert [f["p"] for f in window] == rest  # whole frames, in order: never merged or cut
    assert [f["s"] for f in window] == [now["s"] + i for i in (1, 2, 3)]
    assert all("coalesced" not in f["p"] for f in [now, *window])


async def test_another_owners_burst_never_reaches_this_socket(world: World) -> None:
    paced, _ = await _subscribed(world)
    for n in range(MAX_PENDING_FRAMES + 2):
        world.hub.publish("alerts", _update(world, USER_B, n), user=USER_B)
    paced.at(100.0 + WINDOW_S)
    assert paced.frames() == [] and paced.closed == []


async def test_a_burst_past_the_frame_bound_resyncs_with_the_owners_current_set(
    world: World,
) -> None:
    """The window's frames are dropped, never sent cut short; the `backpressure` snapshot is the
    owner's current unacked set. The burst goes straight to the hub, so the topic's view is out of
    date; a change through the topic's worker then drops it (as it does before every publish), and
    the snapshot the held subscription is owed is read again, carrying every change."""
    paced, sub = await _subscribed(world)
    rows = [world.reader.add(USER_A) for _ in range(3)]  # what the snapshot will carry
    world.hub.publish("alerts", _update(world, USER_A, 1), user=USER_A)
    [lead] = paced.frames()
    for n in range(MAX_PENDING_FRAMES + 1):
        world.hub.publish("alerts", _update(world, USER_A, n), user=USER_A)
    assert (sub.snapshot_pending, sub.pending_reason) == (True, "backpressure")
    last = world.reader.add(USER_A)  # one more change, now through the worker: its delta is held
    await world.topic.deliveries_changed([last.id])
    await world.changes()  # the worker drops the owner's view before it publishes
    paced.at(100.0 + WINDOW_S)
    assert paced.frames() == []  # held for the reload: nothing partial meanwhile
    await world.loads()  # the topic's `flush_pending` unparks it and wakes the writer (§8.4)
    assert paced.frames() == [] and sub.snapshot_pending  # only the ladder's drain sends it
    paced.at(100.0 + WINDOW_S + 0.001)  # the woken writer's turn
    [snap] = paced.frames()
    assert (snap["t"], snap["meta"]["reason"]) == ("snap", "backpressure")
    unacked = sorted(world.reader.rows.values(), key=lambda r: (r.queued_at, r.id), reverse=True)
    assert [d["id"] for d in snap["p"]["deliveries"]] == [r.id for r in unacked]
    assert snap["p"]["unacked_count"] == len(unacked) and {r.id for r in [*rows, last]} <= {
        d["id"] for d in snap["p"]["deliveries"]
    }
    assert snap["s"] > lead["s"] and paced.closed == []
    after = _update(world, USER_A, len(unacked) + 1)
    paced.at(100.0 + 2 * WINDOW_S)
    world.hub.publish("alerts", after, user=USER_A)
    paced.at(100.0 + 3 * WINDOW_S)
    assert [f["p"] for f in paced.frames()] == [after]  # deltas flow again after the resync
