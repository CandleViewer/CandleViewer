"""`OwnerGate` (#3349, E42-X01 UL-F8): a bounded, short-lived, fail-closed view of which alert
owners are active."""

from __future__ import annotations

import asyncio

import pytest
import structlog

from candleviewer.alerts.owners import OwnerGate
from tests.alerts._owners_env import Directory, Time


async def test_owner_gate_serves_a_repeat_from_the_cache_until_the_ttl_ends() -> None:
    directory, clock = Directory({"a"}), Time()
    gate = OwnerGate(directory, clock=clock)
    await gate.skipped(["a", "b"])
    clock.now = 0.9
    assert await gate.skipped(["a", "b", "c"]) == {"b": "inactive", "c": "inactive"}
    assert directory.reads == [{"a", "b"}, {"c"}]  # only what the cache lacks is asked
    clock.now = 1.0  # "a" is 1 s old: a verdict lives for less than the ttl
    await gate.skipped(["a"])
    assert directory.reads[-1] == {"a"}


async def test_owner_gate_fresh_read_bypasses_the_cache_and_refreshes_it() -> None:
    directory = Directory({"a"})
    gate = OwnerGate(directory, clock=Time())
    await gate.skipped(["a"])
    directory.active.clear()  # the owner is disabled
    assert await gate.skipped(["a"]) == {}  # inside its ttl, the cached verdict stands
    assert await gate.skipped(["a"], fresh=True) == {"a": "inactive"}
    assert await gate.skipped(["a"]) == {"a": "inactive"} and len(directory.reads) == 2


async def test_owner_gate_evicts_the_least_recently_used_owner_past_its_bound() -> None:
    directory = Directory({"a", "b", "c"})
    gate = OwnerGate(directory, max_owners=2, clock=Time())
    for owner in ("a", "b", "a", "c"):  # "a" is used again, so "c" evicts "b"
        await gate.skipped([owner])
    directory.reads.clear()
    await gate.skipped(["a", "c"])
    assert directory.reads == []
    await gate.skipped(["b"])
    assert directory.reads == [{"b"}]


async def test_owner_gate_fails_closed_when_the_read_raises_and_warns_once_a_ttl() -> None:
    directory, clock = Directory(fail=RuntimeError("connection to db-host-17 refused")), Time()
    gate = OwnerGate(directory, clock=clock)
    with structlog.testing.capture_logs() as logs:
        assert await gate.skipped(["a", "b"]) == {"a": "unreadable", "b": "unreadable"}
        await gate.skipped(["a"], fresh=True)  # the dispatcher reads fresh, row after row
    assert logs == [{"event": "alert_owner_status_unreadable", "log_level": "warning",
                     "error": "RuntimeError", "owners": 2}]  # fmt: skip
    assert "db-host-17" not in repr(logs)
    await gate.skipped(["a"])
    assert len(directory.reads) == 2  # a failed read is cached too: no hammering
    clock.now = 1.0
    await gate.skipped(["a"])
    assert len(directory.reads) == 3  # and asked again once the ttl is over


async def test_owner_gate_holds_a_slow_failure_for_a_whole_ttl_from_when_it_ended() -> None:
    directory, clock = Directory(fail=RuntimeError("down")), Time()
    directory.on_read = lambda: setattr(clock, "now", 5.0)  # the read outlasts the ttl, then raises
    gate = OwnerGate(directory, clock=clock)
    assert await gate.skipped(["a"]) == {"a": "unreadable"}
    clock.now = 5.9  # the ttl of the failure, which ended at 5.0, is not over
    assert await gate.skipped(["a"]) == {"a": "unreadable"} and len(directory.reads) == 1


async def test_owner_gate_fails_closed_when_the_read_times_out() -> None:
    gate = OwnerGate(Directory(hang=True), timeout_s=0)
    async with asyncio.timeout(5):  # a gate with no bound of its own would hang here: fail instead
        assert await gate.skipped(["a"]) == {"a": "unreadable"}


async def test_owner_gate_propagates_a_cancellation_and_remembers_nothing() -> None:
    directory = Directory({"a"}, fail=asyncio.CancelledError())
    gate = OwnerGate(directory, clock=Time())
    with pytest.raises(asyncio.CancelledError):
        await gate.skipped(["a"])
    directory.fail = None
    assert await gate.skipped(["a"]) == {} and len(directory.reads) == 2
