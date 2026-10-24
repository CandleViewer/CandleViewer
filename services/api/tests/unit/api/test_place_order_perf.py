"""Performance budget of `POST /orders` (E29-T04 #913 slice 3G): one request through F's mounted
router over the real OMS runtime (`OmsRuntime` on E's in-memory stores, `test_oms_runtime.World`)
and a zero-latency `FakeTradingPort`: the route's twelve steps (24 Sec.8.4), the submission behind
them and the rendered `202`, within 50 ms at p95, the backend-added share of budget #4 (06
Sec.5.2, C-13.9) before any network or database time. The pipeline's own share is C5's
`tests/unit/oms/test_submit_perf.py`, whose calibration this reuses.

`perf`-marked: the unit lane deselects it and CI's `py-perf` job runs it without coverage. GC is off
around the timed rounds, each round times `REQUESTS` requests after a warm-up, and the fastest
round's p95 is the measure (host load only ever adds time, #1943). Each sample is one request under
a new `Idempotency-Key`, from the client's send to its `202` through the in-process ASGI transport;
the facade's turns after it are settled untimed."""

from __future__ import annotations

import asyncio
import gc
import json
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from types import SimpleNamespace
from typing import cast
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI, Request

from candleviewer.api.order_principal import TradingPrincipal
from candleviewer.api.orders import make_orders_router
from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.scopes import PrincipalSnapshot
from candleviewer.oms_wiring import GroupStores, OmsAudit, OmsRuntime, OmsStores
from candleviewer.storage.repositories.trading_accounts import TradingAccountRow
from tests.unit.api.test_orders_route import BODY
from tests.unit.oms import command_rig as cr
from tests.unit.oms.submit_rig import SESSION, SYMBOL, USER, Groups, instrument
from tests.unit.oms.test_oms_runtime import World, started
from tests.unit.oms.test_submit_perf import BUDGET_NS, REQUESTS, ROUNDS, _p95

pytestmark = pytest.mark.perf

#: The entry each sample places, on the account the runtime trades.
RAW = json.dumps(BODY | {"exchange_account_id": str(cr.ACCOUNT)}).encode()
#: A bound on the startup sweep over the in-memory stores, not a time the test waits.
READY_BOUND_S = 10.0


class Owner:
    """The route's principal source: every request is the Owner's, in one session."""

    def resolve(self, request: Request) -> TradingPrincipal:
        snapshot = PrincipalSnapshot(USER, frozenset({"owner"}), frozenset(Permission))
        return TradingPrincipal(SESSION, snapshot)


@asynccontextmanager
async def serving() -> AsyncIterator[tuple[httpx.AsyncClient, OmsRuntime]]:
    """`POST /orders` over a ready runtime that trades `cr.ACCOUNT` on demo: the instrument
    catalogue composed, the account and its key read, both flag views read."""
    key = UUID(cr.KEYS["demo"])
    world = World(accounts=[TradingAccountRow(cr.ACCOUNT, "demo", "1000001", False, key)])
    world.store.submissions.seed_account(cr.ref())  # its environment, as Postgres holds it
    listed = {SYMBOL: instrument()}  # the catalogue's snapshot, built once as the refresh does
    world.ingestion.instruments = SimpleNamespace(snapshot=lambda: listed)
    for flag in world.flags:
        flag.read()

    def stores() -> OmsStores:  # the leg's compare-and-set on the store's own groups
        return replace(world.stores(), groups=cast(GroupStores, Groups(world.store)))

    runtime = world.runtime(stores=stores)
    app = FastAPI()
    records = OmsAudit(world.writer, environment="demo")
    app.include_router(
        make_orders_router(
            Owner(), lambda: runtime, audit=world.writer, records=records,
            oms_enabled=lambda: True, metrics=world.metrics,
        )
    )  # fmt: skip
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://cv")
    async with started(runtime), client:
        async with asyncio.timeout(READY_BOUND_S):
            await runtime.wait_ready()
        yield client, runtime


async def _round(client: httpx.AsyncClient, runtime: OmsRuntime) -> list[int]:
    samples: list[int] = []
    for _ in range(REQUESTS):
        headers = {"content-type": "application/json", "idempotency-key": str(uuid4())}
        sent = time.perf_counter_ns()
        answer = await client.post("/orders", content=RAW, headers=headers)
        samples.append(time.perf_counter_ns() - sent)
        assert answer.status_code == 202, answer.text
        machines = runtime._composed().machines  # untimed: the facade's turns settle
        for _ in range(4):
            for _ in range(32):
                await asyncio.sleep(0)
            await machines.idle()
    return samples


async def test_a_place_order_request_fits_50_ms_at_p95() -> None:
    best = 0
    async with serving() as (client, runtime):
        gc.collect()
        gc.disable()  # a collection inside one timed request would skew the sample
        try:
            await _round(client, runtime)  # warm-up: imports, compiled schemas, the first machines
            for _ in range(ROUNDS):
                p95 = _p95(await _round(client, runtime))
                best = p95 if best == 0 else min(best, p95)
        finally:
            gc.enable()
    assert best <= BUDGET_NS, f"p95 {best / 1e6:.2f} ms > {BUDGET_NS / 1e6:.0f} ms"
