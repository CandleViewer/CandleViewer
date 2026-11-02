"""#5331: an admin-area read is recorded once per session, route and window
(`candleviewer.admin.area_coalescer`, the guard in `candleviewer.admin.http`). Fake monotonic
clock, no sleeps."""

from __future__ import annotations

import asyncio
import dataclasses
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY

from candleviewer.admin.area_coalescer import (
    SUMMARY_REASON,
    AreaCoalescerFlushTask,
    AreaEntryCoalescer,
)
from candleviewer.admin.http import (
    AREA_ENTERED,
    AdminAreaRefused,
    admin_area,
    admin_area_refused_handler,
    admin_router,
)
from candleviewer.audit.access import AuditPrincipal
from candleviewer.audit.writer import AuditWriter
from candleviewer.auth.generated_permissions import Permission
from tests.unit.admin._admin_fakes import AuditSpy, principal
from tests.unit.audit.audit_fakes import FakeAuditRepository

READ = Permission.ADMIN_READ
_T0 = datetime(2026, 10, 16, 9, 30, 0, tzinfo=UTC)


class Clock:
    """One fake for both clocks: `mono` is the monotonic reading, the wall time follows it."""

    def __init__(self) -> None:
        self.mono = 1000.0

    def monotonic(self) -> float:
        return self.mono

    def wall(self) -> datetime:
        return _T0 + timedelta(seconds=self.mono - 1000.0)


class Resolver:
    """The `owner` principal, varied per request by headers: `x-ip`, `x-step`, `x-session`,
    `x-subject` (a viewed-as user: the owner then acts for it), `x-actor` (another user),
    `x-deny` (no `admin:read`)."""

    async def resolve(self, request: Request) -> AuditPrincipal | None:
        who = principal("owner")
        h = request.headers
        changes: dict[str, Any] = {}
        if "x-ip" in h:
            changes["ip"] = h["x-ip"]
        if "x-step" in h:
            changes["last_step_up_at"] = _T0 - timedelta(seconds=int(h["x-step"]))
        if "x-session" in h:
            changes["session_id"] = (
                None if h["x-session"] == "none" else UUID(int=int(h["x-session"]))
            )
        if "x-subject" in h:
            changes |= {"actor_user_id": who.user_id, "actor_username": "owner"}
            changes |= {"user_id": UUID(int=int(h["x-subject"])), "username": "subject"}
        if "x-actor" in h:
            n = int(h["x-actor"])
            changes |= {"user_id": UUID(int=900 + n), "username": f"user{n}"}
        if "x-deny" in h:
            changes["permissions"] = frozenset({"audit:read"})
        return dataclasses.replace(who, **changes)


class World:
    def __init__(self, window_s: int = 300, tracked_keys: int = 4096) -> None:
        self.clock, self.spy, self.ready = Clock(), AuditSpy(), True
        self.coalescer = AreaEntryCoalescer(
            window_s,
            self.spy,
            ready=lambda: self.ready,
            tracked_keys=tracked_keys,
            monotonic=self.clock.monotonic,
            wall=self.clock.wall,
        )
        self.router = admin_router(
            READ, resolver=Resolver(), audit=self.spy, clock=self.clock.wall,
            coalescer=self.coalescer,
        )  # fmt: skip

        @self.router.api_route("/probe", methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"])
        @self.router.get("/other")
        async def probe() -> dict[str, str]:
            return {"served": "yes"}

        app = FastAPI()
        app.add_exception_handler(AdminAreaRefused, admin_area_refused_handler)
        app.include_router(self.router)
        self.client = TestClient(app)

    def call(self, path: str = "/admin/probe", method: str = "GET", **headers: str) -> int:
        h = {k.replace("_", "-"): v for k, v in headers.items()}
        return self.client.request(method, path, headers=h).status_code

    def rows(self, reason: str | None = "any") -> list[dict[str, Any]]:
        return [r for r in self.spy.records if reason == "any" or r["reason"] == reason]


def _denied() -> float:
    labels = {"permission": READ.value}
    return float(REGISTRY.get_sample_value("authz_denied_total", labels) or 0.0)


async def test_twenty_polls_over_two_windows_write_two_rows_and_count_the_first_window() -> None:
    w = World()
    statuses = []
    for _ in range(20):
        statuses.append(w.call())
        w.clock.mono += 30
    assert statuses == [200] * 20
    assert len(w.spy.records) == 2
    first, second = w.spy.records
    assert "prior_window" not in first["after_state"]
    assert first["after_state"]["window_s"] == 300
    assert second["after_state"]["prior_window"] == {
        "reads": 10,
        "first_at": _T0.isoformat(),
        "last_at": (_T0 + timedelta(seconds=270)).isoformat(),
    }
    assert all(r["reason"] is None and r["request_id"] for r in w.spy.records)
    # the clock stopped at 600 s, before the second window (opened at 300 s) is window + grace over
    assert await w.coalescer.flush_due() == 0
    w.clock.mono += 30
    assert await w.coalescer.flush_due() == 1  # now its closing summary is written
    (summary,) = w.rows(SUMMARY_REASON)
    assert summary["after_state"]["reads"] == 10
    assert _served(w) == 20


def _served(w: World) -> int:
    """Reads the rows account for: one per opening row, plus the coalesced reads each prior-window
    count and summary carries (their `reads` include the opening read, whose row is counted)."""
    total = 0
    for r in w.spy.records:
        state = r["after_state"]
        if r["reason"] == SUMMARY_REASON:
            total += state["reads"] - 1
        else:
            total += 1 + state.get("prior_window", {}).get("reads", 1) - 1
    return total


def _enter(w: World) -> Any:
    return admin_area(READ, Resolver(), w.spy, coalescer=w.coalescer)


def _request(path: str = "/admin/p", **headers: str) -> Request:
    raw = [(k.replace("_", "-").encode(), v.encode()) for k, v in headers.items()]
    return Request({"type": "http", "method": "GET", "path": path, "headers": raw})


def test_each_route_and_session_gets_its_own_first_row() -> None:
    w = World()
    for session in ("1", "2"):
        for path in ("/admin/probe", "/admin/other"):
            w.call(path, x_session=session)
            w.call(path, x_session=session)  # coalesced
    assert len(w.spy.records) == 4
    w.call(x_session="3")  # a new session on a known route
    assert len(w.spy.records) == 5


def test_a_zero_window_records_every_request_as_before() -> None:
    w = World(window_s=0)
    for _ in range(5):
        w.call()
    assert len(w.spy.records) == 5
    assert all("window_s" not in r["after_state"] for r in w.spy.records)


def test_a_session_less_request_is_never_coalesced() -> None:
    w = World()
    for _ in range(3):
        w.call(x_session="none")
    assert len(w.spy.records) == 3


@pytest.mark.parametrize(
    ("breaker", "method"),
    [
        ({"x_ip": "10.9.9.9"}, "GET"),
        ({"x_step": "5"}, "GET"),
        ({"x_subject": "77"}, "GET"),
        ({}, "HEAD"),
    ],
    ids=["ip", "step-up", "view-as", "head"],
)
def test_a_changed_ip_step_up_subject_or_method_opens_a_fresh_row(
    breaker: dict[str, str], method: str
) -> None:
    w = World()
    w.call()
    w.call()
    assert len(w.spy.records) == 1
    assert w.call(method=method, **breaker) == 200
    assert len(w.spy.records) == 2
    assert w.call(method=method, **breaker) == 200  # and that key coalesces from now on
    assert len(w.spy.records) == 2


def test_a_denial_is_its_own_row_and_closes_the_window_for_the_next_allowed_read() -> None:
    w = World()
    before = _denied()
    w.call()
    w.clock.mono += 10
    w.call()  # coalesced
    assert (w.call(x_deny="1"), w.call(x_deny="1")) == (403, 403)
    assert w.call() == 200
    outcomes = [r["outcome"].value for r in w.spy.records]
    assert outcomes == ["success", "denied", "denied", "success"]
    assert w.spy.records[3]["after_state"]["prior_window"]["reads"] == 2
    assert "prior_window" not in w.spy.records[1]["after_state"]
    assert "window_s" not in w.spy.records[1]["after_state"]
    assert _denied() - before == 2


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_a_mutation_is_written_ahead_even_inside_an_open_read_window(method: str) -> None:
    w = World()
    w.call()
    w.call()
    assert len(w.spy.records) == 1
    assert (w.call(method=method), w.call(method=method)) == (200, 200)
    assert len(w.spy.records) == 3
    assert all("window_s" not in r["after_state"] for r in w.spy.records[1:])


async def test_a_polling_stop_is_summarised_once_after_the_window_and_a_single_read_is_not() -> (
    None
):
    w = World()
    for _ in range(4):
        w.call()
        w.clock.mono += 20
    w.call("/admin/other")  # one read only: no summary owed
    assert await w.coalescer.flush_due() == 0  # window still open
    w.clock.mono += 340  # past window + grace for both
    assert await w.coalescer.flush_due() == 1
    assert await w.coalescer.flush_due() == 0
    (summary,) = w.rows(SUMMARY_REASON)
    assert (summary["action"], summary["outcome"].value) == (AREA_ENTERED, "success")
    assert (summary["actor_label"], summary["request_id"]) == ("owner", None)
    assert summary["actor_user_id"] == principal("owner").user_id
    assert summary["after_state"] == {
        "route": "/admin/probe",
        "reads": 4,
        "window_started_at": _T0.isoformat(),
        "last_read_at": (_T0 + timedelta(seconds=60)).isoformat(),
        "window_s": 300,
    }
    assert len(w.coalescer) == 0  # nothing left to grow


async def test_drain_writes_pending_summaries_and_the_flush_task_stop_drains() -> None:
    w = World()
    w.call()
    w.call()
    task = AreaCoalescerFlushTask(w.coalescer)
    assert await task.stop() == 0
    assert [r["after_state"]["reads"] for r in w.rows(SUMMARY_REASON)] == [2]


async def test_drain_is_bounded_when_the_writer_hangs() -> None:
    w = World()
    w.call()
    w.call()
    never = asyncio.Event()

    async def hang(action: str, **kw: Any) -> None:
        await never.wait()

    w.spy.emit = hang  # type: ignore[method-assign]
    assert await w.coalescer.drain(timeout_s=0.05) == 1
    for t in list(w.coalescer._tasks):
        t.cancel()


def test_audit_not_ready_mid_window_sends_the_read_down_the_write_path() -> None:
    w = World()
    w.call()
    w.call()
    w.ready = False
    assert w.call() == 200  # the spy still writes; the read had to try
    assert len(w.spy.records) == 2
    assert w.spy.records[1]["after_state"]["prior_window"]["reads"] == 2


def test_a_dead_writer_makes_the_coalesced_read_a_503() -> None:
    w = World()
    w.call()
    w.ready = False

    async def broken(action: str, **kw: Any) -> None:
        raise RuntimeError("wal full")

    w.spy.emit = broken  # type: ignore[method-assign]
    assert w.call() == 503


def test_a_failed_opening_write_opens_no_window_and_gives_the_count_back() -> None:
    w = World()
    w.call()
    w.call()
    w.clock.mono += 300  # the window is over; the next read opens a new one
    good = w.spy.emit

    async def broken(action: str, **kw: Any) -> None:
        raise RuntimeError("wal full")

    w.spy.emit = broken  # type: ignore[method-assign]
    assert w.call() == 503
    w.spy.emit = good  # type: ignore[method-assign]
    assert w.call() == 200  # no window was opened: this read writes
    assert w.spy.records[-1]["after_state"]["prior_window"]["reads"] == 2  # carried, not lost
    assert len(w.spy.records) == 2


async def test_a_cancelled_write_propagates() -> None:
    w = World()

    async def cancelled(action: str, **kw: Any) -> None:
        raise asyncio.CancelledError

    w.spy.emit = cancelled  # type: ignore[method-assign]
    enter = admin_area(READ, Resolver(), w.spy, coalescer=w.coalescer)
    request = Request({"type": "http", "method": "GET", "path": "/admin/p", "headers": []})
    with pytest.raises(asyncio.CancelledError):
        await enter(request)
    assert len(w.coalescer) == 0  # a cancelled opening write opens no window


def test_at_the_key_cap_the_oldest_window_is_summarised_first() -> None:
    w = World(tracked_keys=2)
    for session in ("1", "2"):
        w.call(x_session=session)
        w.call(x_session=session)
    assert w.rows(SUMMARY_REASON) == []
    w.call(x_session="3")
    kinds = [r["reason"] for r in w.spy.records]
    # the row is written ahead; opening its window then writes the evicted window's summary
    assert kinds == [None, None, None, SUMMARY_REASON]
    assert w.spy.records[3]["after_state"]["reads"] == 2
    assert len(w.coalescer) == 2


def test_when_nothing_can_be_evicted_every_request_is_recorded() -> None:
    w = World(tracked_keys=1)
    w.call(x_session="1")
    w.call(x_session="1")
    good = w.spy.emit

    async def only_rows(action: str, **kw: Any) -> None:
        if kw["reason"] == SUMMARY_REASON:
            raise RuntimeError("full")
        await good(action, **kw)

    w.spy.emit = only_rows  # type: ignore[method-assign]
    for _ in range(3):
        assert w.call(x_session="2") == 200
    assert len(w.spy.records) == 1 + 3  # the first row, then one row per request
    assert len(w.coalescer) == 1


def test_two_racing_first_reads_each_write_a_row() -> None:
    w = World()
    gate = asyncio.Event()
    entered = 0
    good = w.spy.emit

    async def slow(action: str, **kw: Any) -> None:
        nonlocal entered
        entered += 1
        if entered == 2:
            gate.set()
        await gate.wait()  # both writes are in flight before either returns
        await good(action, **kw)

    w.spy.emit = slow  # type: ignore[method-assign]
    enter = admin_area(READ, Resolver(), w.spy, coalescer=w.coalescer)

    async def read() -> None:
        scope = {"type": "http", "method": "GET", "path": "/p", "headers": []}
        await enter(Request(scope))

    async def both() -> None:
        await asyncio.gather(read(), read())

    asyncio.run(both())
    assert len(w.spy.records) == 2


async def test_the_new_keys_survive_the_real_writer_and_its_redactor(tmp_path: Path) -> None:
    repo = FakeAuditRepository()
    writer = AuditWriter(repo, str(tmp_path / "audit.wal"), sleep=repo.retry_sleep)
    await writer.start()
    clock = Clock()
    coalescer = AreaEntryCoalescer(
        300, writer, ready=lambda: True, monotonic=clock.monotonic, wall=clock.wall
    )
    enter = admin_area(READ, Resolver(), writer, coalescer=coalescer)
    scope = {"type": "http", "method": "GET", "path": "/admin/p", "headers": []}
    for _ in range(3):
        await enter(Request(scope))
    clock.mono += 400
    await enter(Request(scope))
    clock.mono += 400
    await coalescer.flush_due()
    await writer.flush(5)
    await writer.stop(1)
    states = [json.loads(r["after_state"]) for r in repo.rows]
    assert states[0]["window_s"] == 300 and isinstance(states[0]["window_s"], int)
    assert states[1]["prior_window"] == {
        "reads": 3,
        "first_at": _T0.isoformat(),
        "last_at": _T0.isoformat(),
    }
    assert len(states) == 2  # the second window held one read: no summary owed


def test_two_users_interleaved_on_one_route_keep_their_own_rows_and_counts() -> None:
    w = World()
    for user in ("1", "2", "1", "2", "1"):
        assert w.call(x_actor=user) == 200
    assert len(w.spy.records) == 2  # one opening row each
    w.clock.mono += 301
    w.call(x_actor="1")
    w.call(x_actor="2")
    by_actor = {r["actor_label"]: r for r in w.spy.records[2:]}
    assert by_actor["user1"]["after_state"]["prior_window"]["reads"] == 3
    assert by_actor["user2"]["after_state"]["prior_window"]["reads"] == 2
    assert _served(w) == 7


async def test_a_failed_summary_write_gives_its_count_back_and_the_next_tick_retries() -> None:
    w = World()
    for _ in range(3):
        w.call()
    w.clock.mono += 400  # past window + grace
    good = w.spy.emit

    async def broken(action: str, **kw: Any) -> None:
        raise RuntimeError("wal full")

    w.spy.emit = broken  # type: ignore[method-assign]
    assert await w.coalescer.flush_due() == 0
    assert len(w.coalescer) == 1  # the count is still held
    w.spy.emit = good  # type: ignore[method-assign]
    assert await w.coalescer.flush_due() == 1
    assert await w.coalescer.flush_due() == 0
    (summary,) = w.rows(SUMMARY_REASON)
    assert summary["after_state"]["reads"] == 3
    assert _served(w) == 3
    assert len(w.coalescer) == 0


async def test_a_flush_racing_a_new_opening_row_loses_no_count() -> None:
    w = World()
    enter = _enter(w)
    for _ in range(3):
        await enter(_request())
    w.clock.mono += 400
    gate, in_flight = asyncio.Event(), asyncio.Event()
    good = w.spy.emit

    async def slow_failing_summary(action: str, **kw: Any) -> None:
        if kw["reason"] == SUMMARY_REASON:
            in_flight.set()
            await gate.wait()
            raise RuntimeError("wal full")
        await good(action, **kw)

    w.spy.emit = slow_failing_summary  # type: ignore[method-assign]
    flush = asyncio.create_task(w.coalescer.flush_due())
    await in_flight.wait()
    await enter(_request())  # the key was taken by the flush: this read opens a new window
    gate.set()
    assert await flush == 0  # its summary failed: the count folds into the live window
    assert len(w.coalescer) == 1
    w.spy.emit = good  # type: ignore[method-assign]
    w.clock.mono += 400
    assert await w.coalescer.flush_due() == 1
    (summary,) = w.rows(SUMMARY_REASON)
    assert summary["after_state"]["reads"] == 3  # opener + the two coalesced reads of the first
    assert _served(w) == 4


async def test_a_racing_first_read_opening_a_known_window_merges_its_count() -> None:
    w = World()
    c, key = w.coalescer, ("k",)
    mk = lambda: c.new_window(  # noqa: E731
        actor_label="a", actor_user_id=UUID(int=1), ip=None, session_id=UUID(int=2), route="/r"
    )
    await c.open(key, mk())
    assert c.coalesce(key) and c.coalesce(key)
    await c.open(key, mk())  # a second racing first read finishes its write
    assert len(c) == 1
    assert c._windows[key].reads == 3  # not overwritten back to one


async def test_restoring_a_window_whose_key_was_reopened_folds_its_reads_into_the_live_one() -> (
    None
):
    w = World()
    c, key = w.coalescer, ("k",)
    mk = lambda: c.new_window(  # noqa: E731
        actor_label="a", actor_user_id=UUID(int=1), ip=None, session_id=UUID(int=2), route="/r"
    )
    await c.open(key, mk())
    assert c.coalesce(key) and c.coalesce(key)
    taken = c.take_prior(key)
    await c.open(key, mk())  # the key was reopened while the first write was in flight
    c.restore(key, taken)  # that write failed
    assert len(c) == 1
    assert c._windows[key].reads == 3  # 1 live opener + the 2 coalesced reads, none dropped
    assert not c._windows[key].closed


def _served_all(w: World, reads_made: int) -> None:
    assert _served(w) == reads_made


async def test_eviction_counts_every_read_once_while_its_summary_is_written() -> None:
    w = World(tracked_keys=1)
    enter = _enter(w)
    for _ in range(4):
        await enter(_request(x_session="1"))
    gate, in_flight = asyncio.Event(), asyncio.Event()
    good = w.spy.emit

    async def held_summary(action: str, **kw: Any) -> None:
        if kw["reason"] == SUMMARY_REASON:
            in_flight.set()
            await gate.wait()
        await good(action, **kw)

    w.spy.emit = held_summary  # type: ignore[method-assign]
    other = asyncio.create_task(enter(_request(x_session="2")))
    await in_flight.wait()
    await enter(_request(x_session="1"))  # served while the summary write is held open
    gate.set()
    await other
    await w.coalescer.drain()
    _served_all(w, 6)


async def test_eviction_with_a_concurrent_flush_counts_every_read_once() -> None:
    w = World(tracked_keys=1)
    enter = _enter(w)
    for _ in range(3):
        await enter(_request(x_session="1"))
    w.clock.mono += 400  # the window is past its grace: flush_due would take it too
    gate, in_flight = asyncio.Event(), asyncio.Event()
    good = w.spy.emit
    first = True

    async def held_first_summary(action: str, **kw: Any) -> None:
        nonlocal first
        if kw["reason"] == SUMMARY_REASON and first:
            first = False
            in_flight.set()
            await gate.wait()
        await good(action, **kw)

    w.spy.emit = held_first_summary  # type: ignore[method-assign]
    other = asyncio.create_task(enter(_request(x_session="2")))
    await in_flight.wait()
    await w.coalescer.flush_due()
    gate.set()
    await other
    await w.coalescer.drain()
    assert len(w.rows(SUMMARY_REASON)) == 1
    _served_all(w, 4)


async def test_a_cancel_after_the_row_was_written_does_not_count_the_window_twice() -> None:
    w = World()
    enter = _enter(w)
    for _ in range(3):
        await enter(_request())
    w.clock.mono += 301

    async def cancelled_open(*a: Any, **kw: Any) -> bool:
        raise asyncio.CancelledError

    w.coalescer.open = cancelled_open  # type: ignore[method-assign]
    with pytest.raises(asyncio.CancelledError):
        await enter(_request())
    assert len(w.coalescer) == 0  # the row already carried the count
    assert await w.coalescer.drain() == 0
    assert not w.rows(SUMMARY_REASON)
    _served_all(w, 4)


async def test_a_stop_cancelling_a_flush_mid_write_loses_no_count() -> None:
    w = World()
    enter = _enter(w)
    for _ in range(3):
        await enter(_request())
    w.clock.mono += 400
    in_flight = asyncio.Event()
    good = w.spy.emit

    async def hanging_summary(action: str, **kw: Any) -> None:
        if kw["reason"] == SUMMARY_REASON:
            in_flight.set()
            await asyncio.Event().wait()
        await good(action, **kw)

    w.spy.emit = hanging_summary  # type: ignore[method-assign]
    flush = asyncio.create_task(w.coalescer.flush_due())
    await in_flight.wait()
    flush.cancel()
    with pytest.raises(asyncio.CancelledError):
        await flush
    assert len(w.coalescer) == 1  # given back, so the drain at stop still sees it
    w.spy.emit = good  # type: ignore[method-assign]
    assert await w.coalescer.drain() == 0
    _served_all(w, 3)
