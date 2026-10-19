"""Harness guards (E08-Q03 security notes; C-13.5, SR-140).

* The suite cannot reach live Bybit: the REST client runs on the stub's
  in-process transport, and a raw dial to the live host is refused by the
  session network guard.
* Same seed => same fault trace (determinism AC).
"""

from __future__ import annotations

import socket
from typing import Any

import pytest

from tests._ci_network_guard import NetworkGuardViolation, Refusal, expected_refusals
from tests._corpus import frames
from tests.chaos.ingestion._faults import Fault, FaultKind
from tests.chaos.ingestion._feed import Feeder
from tests.chaos.ingestion._rig import Rig, metric

pytestmark = pytest.mark.chaos

BOOK = frames("ws/orderbook_BTCUSDT.jsonl")


def test_live_exchange_host_is_unreachable_from_the_suite() -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with expected_refusals() as refused, pytest.raises(NetworkGuardViolation):
            sock.connect(("api.bybit.com", 443))
    finally:
        sock.close()
    assert refused == [Refusal("connect", "api.bybit.com")]  # claimed (#3826)


async def test_rest_traffic_is_answered_by_the_stub_transport(rig: Rig) -> None:
    body = await rig.rest.get_public("/v5/market/time")
    assert body["retCode"] == 0
    assert rig.ex.rest_calls[-1][1] == "/v5/market/time"


async def _scripted_run(seed: int) -> list[tuple[float, str, str]]:
    r = Rig(seed=seed)
    await r.start()
    try:
        await r.clock.run_until(lambda: r.ws.state() == "open", within_s=5, what="open")
        await r.ex.replay(BOOK[:20])
        r.ex.inject(Fault(FaultKind.REFUSE, count=3))
        r.ex.inject(Fault(FaultKind.RESET))
        await r.clock.run_until(lambda: r.ws.state() == "open", within_s=60, what="reopen")
        await r.ex.replay(BOOK[20:40])
        return list(r.ex.trace.events)
    finally:
        await r.stop()


async def test_same_seed_gives_an_identical_fault_trace() -> None:
    first, second = await _scripted_run(7), await _scripted_run(7)
    assert first == second
    assert any(kind == "ws.refused" for _, kind, _ in first)


async def test_drop_duplicate_and_reorder_faults_act_on_the_wire_only(rig: Rig) -> None:
    await rig.clock.run_until(lambda: rig.ws.state() == "open", within_s=5, what="open")
    topic = "orderbook.200.BTCUSDT"
    rig.ex.inject(Fault(FaultKind.DUPLICATE, topic=topic))
    rig.ex.inject(Fault(FaultKind.REORDER, topic=topic))
    await rig.ex.replay(BOOK[:4])
    kinds = [k for _, k, _ in rig.ex.trace.events if k.startswith("fault.")]
    assert kinds == ["fault.reorder", "fault.duplicate"]  # reorder holds frame 1 first
    assert rig.ex.books[topic].u == 4  # the venue's truth is untouched by wire faults


async def _scenario_signature(seed: int) -> dict[str, Any]:
    """Run a reset-and-recover scenario end to end; return everything observable."""
    from candleviewer.ingestion.metrics import ingest_ws_up

    r = Rig(seed=seed)
    await r.start()
    try:
        feed = Feeder(r.ex)
        await r.clock.run_until(lambda: r.ws.state() == "open", within_s=5, what="open")
        await feed.run(2.0)
        r.ex.inject(Fault(FaultKind.RESET))
        await feed.run(8.0)
        seen = r.observe()
        return {
            "order": list(seen.order),
            "feed": [(f.topic, f.state) for f in seen.feed],
            "trade_ids": [t.trade_id for t in seen.trades if hasattr(t, "trade_id")],
            "trace": list(r.ex.trace.events),
            "sockets": len(r.ex.sockets),
            "ws_up": metric(ingest_ws_up, socket="public"),
            "book": r.book_levels(),
        }
    finally:
        await r.stop()


async def test_same_seed_gives_identical_event_and_metric_sequences() -> None:
    first, second = await _scenario_signature(11), await _scenario_signature(11)
    assert first["sockets"] >= 2 and first["order"]  # the scenario actually exercised recovery
    assert first == second
