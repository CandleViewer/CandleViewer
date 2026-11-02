"""E35-T12 slice 3e: the circuit breaker's cancels of the tripped rule's resting entries, started
after the trip's B9 move as a task the rules service tracks (24 §11.7; BQ-10 of #5004).

The breaker starts them once per trip, its move landed or not, never again when it sends a move
that has not landed; the service runs them as tasks it tracks, at most `BREAKER_CANCELS_MAX` at
once, pages a trip whose cancels it cannot start, and drains them within its stop's grace, the
rest cancelled. No sleeps: each port waits on an event the test sets.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from structlog.testing import capture_logs

from candleviewer.rules import service as service_module
from candleviewer.rules.executor.budget import CircuitBreaker
from candleviewer.rules.executor.gates import Halts
from candleviewer.rules.scope import ActionRequest
from candleviewer.rules.service import RulesService
from tests.rules.executor.test_reduce_only_handlers import exit_request

RUN = uuid.UUID(int=0xB1)


class Moves:
    """The breaker's B9 move: answers `landed` in turn, each move recorded."""

    def __init__(self, *landed: bool) -> None:
        self.landed, self.asked = list(landed), list[str]()

    async def __call__(self, rule_id: str) -> bool:
        self.asked.append(rule_id)
        return self.landed.pop(0)


async def test_the_breaker_starts_its_cancels_once_per_trip_after_the_move() -> None:
    """The cancels start after the move, landed or not, once per trip: a move sent again for a
    rule whose move has not landed is no new trip, and starts none; a trip with no action named
    starts none."""
    started: list[tuple[str, ActionRequest]] = []
    moves = Moves(False, True)

    def cancels(req: ActionRequest) -> None:
        started.append((req.rule_id, req))

    breaker = CircuitBreaker(Halts(), move=moves, cancels=cancels)
    req = exit_request("scale_out", node="x1")
    await breaker.trip(req.rule_id, RUN, "x1", req=req)
    assert [r for r, _ in started] == [req.rule_id] and moves.asked == [req.rule_id]
    await breaker.trip(req.rule_id, RUN, "x1", req=req)  # the move again: no new trip
    assert len(started) == 1 and len(moves.asked) == 2
    await CircuitBreaker(Halts(), move=Moves(True), cancels=cancels).trip("r2", RUN, "x2")
    assert len(started) == 1


class Held:
    """`BreakerCancels` whose cancels wait on `release`; each start and end recorded."""

    def __init__(self) -> None:
        self.release = asyncio.Event()
        self.started, self.ended = list[str](), list[str]()

    async def cancel_resting(self, req: ActionRequest) -> None:
        self.started.append(req.payload.node_id)
        await self.release.wait()
        self.ended.append(req.payload.node_id)


async def test_the_service_tracks_the_cancels_bounded_and_drains_them_at_stop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The service runs each trip's cancels as a task it tracks, at most `BREAKER_CANCELS_MAX`
    at once: one more is logged and not started, as is a trip with no port bound; at its stop the
    running ones are drained within the grace, then the rest are cancelled."""
    monkeypatch.setattr(service_module, "BREAKER_CANCELS_MAX", 2)
    service = RulesService()
    with capture_logs() as logs:
        service._start_breaker_cancels(exit_request("scale_out", node="u1"))
    assert [e["reason"] for e in logs if e["event"] == "rules.breaker_cancels_not_started"] == [
        "unbound"
    ]
    port = Held()
    service.bind(breaker_cancels=port)
    with capture_logs() as logs:
        for node in ("a1", "a2", "a3"):
            service._start_breaker_cancels(exit_request("scale_out", node=node))
        await asyncio.sleep(0)
    assert port.started == ["a1", "a2"] and len(service._breaker_tasks) == 2
    assert [e["reason"] for e in logs if e["event"] == "rules.breaker_cancels_not_started"] == [
        "full"
    ]
    port.release.set()
    await service._drain_breaker_cancels(5.0)
    assert port.ended == ["a1", "a2"] and service._breaker_tasks == set()
    hung = Held()
    service.bind(breaker_cancels=hung)
    service._start_breaker_cancels(exit_request("scale_out", node="b1"))
    await asyncio.sleep(0)
    await service.stop(0.0)  # nothing ran: the grace is spent at once, the task cancelled
    assert hung.started == ["b1"] and hung.ended == [] and service._breaker_tasks == set()


async def test_a_trip_whose_cancels_cannot_start_pages_once_naming_the_rule(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """24 §11.7: a trip whose cancels cannot start, as no port is bound or `BREAKER_CANCELS_MAX`
    are running, pages P1 once (`cv_page`, CRITICAL), naming the rule; the running ones go on."""
    monkeypatch.setattr(service_module, "BREAKER_CANCELS_MAX", 1)
    service = RulesService()
    port = Held()
    with capture_logs() as logs:
        service._start_breaker_cancels(exit_request("scale_out", node="u1"))  # no port bound
        service.bind(breaker_cancels=port)
        service._start_breaker_cancels(exit_request("scale_out", node="a1"))
        service._start_breaker_cancels(exit_request("scale_out", node="a2"))  # the cap reached
        await asyncio.sleep(0)
    rule = exit_request("scale_out").rule_id
    pages = [
        (e["reason"], e["log_level"], e.get("cv_page"), e["rule_id"])
        for e in logs if e["event"] == "rules.breaker_cancels_not_started"
    ]  # fmt: skip
    assert pages == [("unbound", "critical", True, rule), ("full", "critical", True, rule)]
    assert port.started == ["a1"]
    port.release.set()
    await service._drain_breaker_cancels(5.0)
    assert port.ended == ["a1"] and service._breaker_tasks == set()


async def test_a_raising_cancels_port_is_logged_by_its_class() -> None:
    """A port that raises ends its task logged by its class, never re-raised into the loop."""

    class Raises:
        async def cancel_resting(self, req: ActionRequest) -> None:
            raise ConnectionError("the exit service is gone")

    service = RulesService()
    service.bind(breaker_cancels=Raises())
    with capture_logs() as logs:
        service._start_breaker_cancels(exit_request("scale_out"))
        await service._drain_breaker_cancels(5.0)
    [failed] = [e for e in logs if e["event"] == "rules.breaker_cancels_failed"]
    assert failed["kind"] == "ConnectionError" and "gone" not in str(failed)
