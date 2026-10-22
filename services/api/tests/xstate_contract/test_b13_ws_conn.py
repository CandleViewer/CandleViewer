"""B13 `ws_conn` transitions through the factory with a fake runtime (E08-T04)."""

from __future__ import annotations

import pytest
from xstate_statemachine import SimulatedClock

from candleviewer.statechart import build
from candleviewer.statechart.bindings import b13_ws_conn as b13


class _Rt:
    attempt = 0

    def __init__(self, *, fail_open: bool = False, budget: bool = False) -> None:
        self.fail_open, self.budget = fail_open, budget
        self.health: list[str] = []
        self.calls: list[str] = []

    def is_private(self) -> bool:
        return False

    def budget_exhausted(self) -> bool:
        return self.budget

    async def open_socket(self) -> None:
        self.calls.append("open")
        if self.fail_open:
            raise OSError("dial")

    async def authenticate(self) -> None: ...
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


async def _drive(rt: _Rt, key: str, *events: str) -> tuple[set[str], list[str]]:
    b13.register_runtime(key, rt)
    try:
        r = await build("ws_conn", ctx={"conn_key": key}, clock=SimulatedClock(), lane="platform")
        for ev in events:
            await r.interpreter.send(ev, wait=True)
        for _ in range(50):
            await __import__("asyncio").sleep(0)
        ids = {s.rsplit(".", 1)[-1] for s in r.interpreter.current_state_ids}
        await r.interpreter.stop()
        return ids, rt.health
    finally:
        b13.unregister_runtime(key)


async def test_connect_reaches_live_and_emits_healthy() -> None:
    ids, health = await _drive(_Rt(), "t1", "CONNECT")
    assert "live" in ids and health == ["healthy"]


async def test_dial_failure_backs_off_and_emits_degraded() -> None:
    ids, health = await _drive(_Rt(fail_open=True), "t2", "CONNECT")
    assert "backing_off" in ids and health == ["degraded"]


async def test_budget_exhausted_blocks() -> None:
    ids, _ = await _drive(_Rt(budget=True), "t3", "CONNECT")
    assert "budget_blocked" in ids


async def test_live_socket_closed_then_backoff_due_reconnects() -> None:
    ids, health = await _drive(_Rt(), "t4", "CONNECT", "SOCKET_CLOSED", "BACKOFF_DUE")
    assert "live" in ids and health == ["healthy", "degraded", "healthy"]


@pytest.mark.parametrize("ev", ["SHUTDOWN", "KILL"])
async def test_shutdown_and_kill_terminate(ev: str) -> None:
    ids, _ = await _drive(_Rt(), f"t5{ev}", "CONNECT", ev)
    assert "closed" in ids


@pytest.mark.parametrize("ev", ["PONG_DEADLINE", "SOCKET_CLOSED", "TOPIC_STALE"])
async def test_live_failure_events_back_off(ev: str) -> None:
    ids, health = await _drive(_Rt(), f"t6{ev}", "CONNECT", ev)
    assert "backing_off" in ids and health == ["healthy", "degraded"]


async def test_live_pong_is_internal() -> None:
    ids, health = await _drive(_Rt(), "t7", "CONNECT", "PONG")
    assert "live" in ids and health == ["healthy"]


async def test_live_topics_changed_resubscribes() -> None:
    rt = _Rt()
    ids, _ = await _drive(rt, "t8", "CONNECT", "TOPICS_CHANGED")
    assert "live" in ids and rt.calls.count("subscribe") == 2


async def test_backing_off_shutdown_closes() -> None:
    rt = _Rt()
    ids, _ = await _drive(rt, "t9", "CONNECT", "SOCKET_CLOSED", "SHUTDOWN")
    assert "closed" in ids and "close" in rt.calls


async def test_budget_recheck_returns_to_disconnected() -> None:
    ids, health = await _drive(_Rt(budget=True), "t10", "CONNECT", "BUDGET_RECHECK")
    assert "disconnected" in ids and health == ["degraded"]


async def test_inv_b13_a_budget_checked_before_open() -> None:
    rt = _Rt(budget=True)
    await _drive(rt, "t11", "CONNECT")
    assert "open" not in rt.calls


def test_inv_b13_b_backoff_jitter_bounded_by_monotonic_ceiling() -> None:
    import random

    from candleviewer.ingestion.reconnect import ReconnectPolicy

    p = ReconnectPolicy(rng=random.Random(5))  # noqa: S311
    ceilings = [max(p.next_delay(a) for _ in range(200)) for a in range(12)]
    assert all(c <= 30.0 for c in ceilings)
    assert ceilings[0] < ceilings[4] <= 30.0


async def test_inv_b13_c_subscribe_before_live_and_once_per_entry() -> None:
    rt = _Rt()
    await _drive(rt, "t12", "CONNECT")
    assert rt.calls == ["open", "subscribe"]


def test_inv_b13_d_hot_path_reads_plain_phase_not_interpreter() -> None:
    import inspect

    from candleviewer.ingestion.connection import ConnectionManager

    src = inspect.getsource(ConnectionManager.state)
    assert "_interp" not in src and "current_state" not in src


# §B13.7 ledger (E50-T31 membership): pinned to 28-statechart-catalogue.md.
INVARIANTS: dict[str, str] = {
    "INV-B13-a": "test_inv_b13_a_budget_checked_before_open",
    "INV-B13-b": "test_inv_b13_b_backoff_jitter_bounded_by_monotonic_ceiling",
    "INV-B13-c": "test_inv_b13_c_subscribe_before_live_and_once_per_entry",
    "INV-B13-d": "test_inv_b13_d_hot_path_reads_plain_phase_not_interpreter",
    "INV-B13-e": "test_b13_ws_conn_private.py::test_inv_b13_e_deadline_absolute_outside_chart",
}


def test_b13_invariant_ledger_matches_catalogue() -> None:
    from tests.xstate_contract.membership import check_ledger

    check_ledger(13, INVARIANTS, globals())
