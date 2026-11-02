"""E21-X02 (#652; 22 `getHeatmap` "Bounds"): the bench at the cap. One page of `MAX_COLUMNS` time
columns x `ROWS` price rows (2 000 x 512, every cell its own value, as `normalize=window` leaves
them) served by the real router, the read replaced by that page: the subject is the response, its
conversion and encoding, since the folds run on the bounded executor either way. As E21-T03 times
a read and build (`heatmap_backfill_duration_ms`: `perf_counter` around the work, in ms), each
loop step is timed around its run, here with `time.thread_time`, the loop thread's own CPU time,
so the host's scheduling and the fold workers' turns do not count. The measure: the longest step
the loop ran while the page was served stays under budget #6's 20 ms (`06` §2); the body arrives
in more than one part and parses to the page.

`perf`-marked: the unit lane deselects it and CI's `py-perf` job runs it without coverage. As the
submit's perf tests are calibrated (#1943), GC is off around the timed rounds, a first round warms
up, and the median of `ROUNDS` rounds is the measure."""

from __future__ import annotations

import asyncio
import gc
import json
import statistics
import time
import uuid
from collections.abc import Callable, MutableMapping
from decimal import Decimal
from typing import Any, Final, cast

import numpy as np
import pytest
from fastapi import FastAPI, Request

from candleviewer.api import market_heatmap
from candleviewer.api.market_heatmap import make_market_heatmap_router
from candleviewer.orderflow.heatmap import ROWS
from candleviewer.orderflow.heatmap_history import (
    MAX_COLUMNS,
    HeatmapHistory,
    HeatmapHistoryReader,
    HeatmapQuery,
    Segment,
)

pytestmark = pytest.mark.perf

ROUNDS: Final = 5
#: `06` budget #6: a backend frame within 20 ms; no loop step of the response may take that long.
STEP_BUDGET_S: Final = 0.020
T0: Final = 1_790_812_800_000_000  # 2026-10-01 00:00 UTC
BUCKET_US: Final = 100_000
END: Final = T0 + MAX_COLUMNS * BUCKET_US


def _capped_page() -> HeatmapHistory:
    """2 000 columns x 512 rows at 100 ms, every cell a distinct fraction (seeded)."""
    rng = np.random.default_rng(652)
    bid, ask = rng.random((ROWS, MAX_COLUMNS)), rng.random((ROWS, MAX_COLUMNS))
    tick = Decimal("0.1")
    q = HeatmapQuery("BTCUSDT", T0, END, 100, 1, 200, "window", tick)
    prices = tuple((Decimal(600_000 + i) * tick).quantize(tick) for i in range(ROWS))
    return HeatmapHistory(
        q, T0, END, 100, tuple(range(T0, END, BUCKET_US)), prices, bid, ask, 1.0,
        (1,) * MAX_COLUMNS, (False,) * MAX_COLUMNS, T0, "full", (Segment(T0, END, "hot", 100),),
        False, None, 0, frozenset({"hot"}),
    )  # fmt: skip


class _Principal:
    def __init__(self) -> None:
        self.user_id = self.actor_id = uuid.uuid4()

    def has(self, permission: str) -> bool:
        return permission == "marketdata:read"


class _Resolver:
    async def resolve(self, request: Request) -> Any:
        return _Principal()


def _app(page: HeatmapHistory, monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    async def read(reader: object, query: HeatmapQuery, **_: object) -> HeatmapHistory:
        return page

    monkeypatch.setattr(market_heatmap, "read_heatmap_history", read)
    reader = cast(HeatmapHistoryReader, object())  # never read: the read is replaced
    app = FastAPI()
    app.include_router(
        make_market_heatmap_router(
            lambda: reader,
            principal_resolver=_Resolver(),
            symbol_listed=lambda symbol: True,
            tick_size=lambda symbol: Decimal("0.1"),
            now_us=lambda: END,
        )
    )
    return app


class _Steps:
    """The loop thread's CPU time for every handle it runs while `on`."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.on, self.seen = False, list[float]()
        run: Callable[[asyncio.Handle], None] = asyncio.Handle._run

        def timed(handle: asyncio.Handle) -> None:
            if not self.on:
                run(handle)
                return
            began = time.thread_time()
            try:
                run(handle)
            finally:
                self.seen.append(time.thread_time() - began)

        monkeypatch.setattr(asyncio.Handle, "_run", timed)


async def _serve(app: FastAPI, steps: _Steps) -> tuple[float, list[bytes]]:
    """One capped page by a direct ASGI call: the longest loop step, and the body's parts."""
    query = (
        b"symbol=BTCUSDT&from=2026-10-01T00:00:00Z&to=2026-10-01T00:03:20Z"
        b"&time_bucket_ms=100&normalize=window"
    )
    path = "/market/heatmap"
    scope = {
        "type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"}, "http_version": "1.1",
        "method": "GET", "scheme": "http", "path": path, "raw_path": path.encode(),
        "query_string": query, "root_path": "", "headers": [(b"host", b"t")],
        "client": ("127.0.0.1", 1), "server": ("t", 80),
    }  # fmt: skip
    parts: list[bytes] = []
    sent = asyncio.Event()

    async def receive() -> dict[str, Any]:
        await sent.wait()
        return {"type": "http.disconnect"}

    async def send(message: MutableMapping[str, Any]) -> None:
        if message["type"] == "http.response.start":
            assert message["status"] == 200
        elif message.get("body"):
            parts.append(message["body"])

    steps.on = True
    await asyncio.sleep(0)  # a step of its own: the round's set-up is not timed
    steps.seen.clear()
    await app(scope, receive, send)
    sent.set()
    steps.on = False
    return max(steps.seen), parts


async def test_a_capped_page_is_served_without_holding_the_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = _capped_page()
    app, steps = _app(page, monkeypatch), _Steps(monkeypatch)
    await _serve(app, steps)  # warm-up
    longest: list[float] = []
    for _ in range(ROUNDS):
        gc.collect()
        gc.disable()
        try:
            step, parts = await _serve(app, steps)
        finally:
            gc.enable()
        longest.append(step)
    measured = statistics.median(longest)
    assert measured < STEP_BUDGET_S, f"the longest loop step at the cap: {measured * 1000:.1f} ms"
    assert len(parts) > 2  # streamed: the head, blocks of rows, the tail
    body = json.loads(b"".join(parts))
    assert (len(body["times"]), len(body["prices"])) == (MAX_COLUMNS, ROWS)
    assert len(body["bid_matrix"]) == len(body["ask_matrix"]) == ROWS
    for i in (0, ROWS // 2, ROWS - 1):  # each a float that round-trips the page's own value
        assert body["bid_matrix"][i] == page.bid[i].tolist()
        assert body["ask_matrix"][i] == page.ask[i].tolist()
