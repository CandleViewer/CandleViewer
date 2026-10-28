"""Performance budget of the exit routes (E29-T04 #913 S4-G3, CG8; the orchestrator's ruling Q5):
`DELETE /orders/{orderId}` and `PATCH /orders/{orderId}`, each one request through the exit
routes' router over the real OMS runtime and a zero-latency `FakeTradingPort`, mounted with
`POST /orders` by `test_place_order_perf.serving()`: the route's steps, the exit service, B1's step
and the venue's answer, within 50 ms at p95, the ruled target inside 06's write budget (#13).

`perf`-marked: the unit lane deselects it and CI's `py-perf` job runs it without coverage. As the
submit's perf tests are calibrated (#1943), GC is off around the timed rounds, each round times
`REQUESTS` requests after a warm-up round, and the fastest round's p95 is the measure. Every
round's orders are placed first, untimed, before any exit: a cancelled entry's stop request waits
for its complete read, which would refuse the next entry on the position. Each sample is then one
exit of one of them under a new `Idempotency-Key`, from the client's send to its `202`: a cancel,
or an amend that moves the price of a resting entry, the gated path (the flag, the switches and
the arm, 24 Sec.8.10). The facade's turns after each are settled untimed."""

from __future__ import annotations

import asyncio
import gc
import json
import time
from collections.abc import Awaitable, Callable
from uuid import uuid4

import httpx
import pytest

from candleviewer.oms_wiring import OmsRuntime
from tests.unit.api.test_place_order_perf import RAW, serving
from tests.unit.oms.test_submit_perf import BUDGET_NS, REQUESTS, ROUNDS, _p95

pytestmark = pytest.mark.perf

#: The amend each sample sends: the resting entry's price moved half a dollar, inside the band.
MOVE = json.dumps({"price": "60000.5"}).encode()

type Exit = Callable[[httpx.AsyncClient, str], Awaitable[httpx.Response]]


def _headers() -> dict[str, str]:
    return {"content-type": "application/json", "idempotency-key": str(uuid4())}


async def _settle(runtime: OmsRuntime) -> None:
    """Untimed: the facade's turns settle, as `test_place_order_perf._round` lets them."""
    machines = runtime._composed().machines
    for _ in range(4):
        for _ in range(32):
            await asyncio.sleep(0)
        await machines.idle()


async def _resting(client: httpx.AsyncClient, runtime: OmsRuntime) -> list[str]:
    """`REQUESTS` entries placed and resting `submitted`, untimed: their order ids."""
    placed: list[str] = []
    for _ in range(REQUESTS):
        answer = await client.post("/orders", content=RAW, headers=_headers())
        assert answer.status_code == 202, answer.text
        [leg] = answer.json()["trade_group"]["legs"]
        placed.append(leg["order_details"][0]["id"])
        await _settle(runtime)
    return placed


async def _cancel(client: httpx.AsyncClient, order_id: str) -> httpx.Response:
    return await client.delete(f"/orders/{order_id}", headers=_headers())


async def _amend(client: httpx.AsyncClient, order_id: str) -> httpx.Response:
    return await client.patch(f"/orders/{order_id}", content=MOVE, headers=_headers())


async def _round(
    client: httpx.AsyncClient, runtime: OmsRuntime, send: Exit, orders: list[str]
) -> list[int]:
    samples: list[int] = []
    for order_id in orders:
        sent = time.perf_counter_ns()
        answer = await send(client, order_id)
        samples.append(time.perf_counter_ns() - sent)
        assert answer.status_code == 202, answer.text
        await _settle(runtime)
    return samples


async def _best_p95(send: Exit) -> int:
    best = 0
    async with serving() as (client, runtime):
        placed = [await _resting(client, runtime) for _ in range(ROUNDS + 1)]
        gc.collect()
        gc.disable()  # a collection inside one timed request would skew the sample
        try:
            await _round(client, runtime, send, placed[0])  # warm-up: the exit paths' first runs
            for orders in placed[1:]:
                p95 = _p95(await _round(client, runtime, send, orders))
                best = p95 if best == 0 else min(best, p95)
        finally:
            gc.enable()
    return best


async def test_a_cancel_request_fits_50_ms_at_p95() -> None:
    best = await _best_p95(_cancel)
    assert best <= BUDGET_NS, f"p95 {best / 1e6:.2f} ms > {BUDGET_NS / 1e6:.0f} ms"


async def test_an_amend_request_fits_50_ms_at_p95() -> None:
    best = await _best_p95(_amend)
    assert best <= BUDGET_NS, f"p95 {best / 1e6:.2f} ms > {BUDGET_NS / 1e6:.0f} ms"
