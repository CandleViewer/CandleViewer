"""E21-X02 (#652; 22 `getHeatmap` "Bounds"): the backfill's streamed body. A page leaves as its
head, each matrix `BODY_BLOCK_ROWS` rows at a time and its tail, every part encoded on the bounded
fold executor (`run_fold`), never on the loop; the parts join to the contract's `HeatmapResponse`,
every number the page's own; and a cell that is not finite is refused before any byte. The read is
replaced by the page; the router is the real one, called as the ASGI server calls it."""

from __future__ import annotations

import asyncio
import json
import threading
import uuid
from collections.abc import Callable, MutableMapping
from decimal import Decimal
from typing import Any, cast

import numpy as np
import numpy.typing as npt
import pytest
from fastapi import FastAPI, Request

from candleviewer.api import market_heatmap
from candleviewer.api._generated.openapi_models import HeatmapResponse
from candleviewer.api.market_heatmap import (
    BODY_BLOCK_ROWS,
    make_market_heatmap_router,
    serialize_heatmap,
)
from candleviewer.orderflow.heatmap_history import (
    FOLD_THREAD_PREFIX,
    HeatmapHistory,
    HeatmapHistoryReader,
    HeatmapQuery,
    Segment,
)

T0 = 1_790_812_800_000_000  # 2026-10-01 00:00 UTC
COLUMNS, ROWS = 30, 2 * BODY_BLOCK_ROWS + 3  # three blocks a matrix, the last a short one
END = T0 + COLUMNS * 1_000_000
QUERY = b"symbol=BTCUSDT&from=2026-10-01T00:00:00Z&to=2026-10-01T00:00:30Z"


def _page(bid: npt.NDArray[np.float64] | None = None) -> HeatmapHistory:
    rng = np.random.default_rng(652)
    bids = rng.random((ROWS, COLUMNS)) if bid is None else bid
    tick = Decimal("0.1")
    q = HeatmapQuery("BTCUSDT", T0, END, 1000, 1, 200, "window", tick)
    return HeatmapHistory(
        q, T0, END, 1000, tuple(range(T0, END, 1_000_000)),
        tuple((Decimal(600_000 + i) * tick).quantize(tick) for i in range(ROWS)),
        bids, rng.random((ROWS, COLUMNS)), 1.0, (10,) * COLUMNS, (False,) * COLUMNS, T0, "full",
        (Segment(T0, END, "hot", 1000),), False, None, 0, frozenset({"hot"}),
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


async def _get(app: FastAPI, statuses: list[int] | None = None) -> tuple[list[int], list[bytes]]:
    """One request, as the ASGI server makes it: the statuses started (into `statuses` too, kept
    if the app raises), and the body's parts."""
    path = "/market/heatmap"
    scope = {
        "type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"}, "http_version": "1.1",
        "method": "GET", "scheme": "http", "path": path, "raw_path": path.encode(),
        "query_string": QUERY, "root_path": "", "headers": [(b"host", b"t")],
        "client": ("127.0.0.1", 1), "server": ("t", 80),
    }  # fmt: skip
    statuses = [] if statuses is None else statuses
    parts: list[bytes] = []
    done = asyncio.Event()

    async def receive() -> dict[str, Any]:
        await done.wait()
        return {"type": "http.disconnect"}

    async def send(message: MutableMapping[str, Any]) -> None:
        if message["type"] == "http.response.start":
            statuses.append(message["status"])
        elif message.get("body"):
            parts.append(message["body"])

    try:
        await app(scope, receive, send)
    finally:
        done.set()
    return statuses, parts


async def test_the_body_streams_in_blocks_and_parses_to_the_contract_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = _page()
    statuses, parts = await _get(_app(page, monkeypatch))
    blocks = -(-ROWS // BODY_BLOCK_ROWS)
    assert statuses == [200]
    assert len(parts) == 1 + blocks + 1 + blocks + 1  # head, blocks, the join, blocks, tail
    body = json.loads(b"".join(parts))
    HeatmapResponse.model_validate(body)
    # the same object the whole-body form serialises: each float the page's own, exactly
    assert body == json.loads(json.dumps(serialize_heatmap(page, None)))
    assert body["bid_matrix"] == page.bid.tolist() and body["ask_matrix"] == page.ask.tolist()


async def test_the_encoding_runs_on_the_fold_executor_not_the_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    threads: dict[str, list[str]] = {"_ends": [], "_block": []}

    def spied(name: str) -> Callable[..., Any]:
        real: Callable[..., Any] = getattr(market_heatmap, name)

        def run(*args: Any) -> Any:
            threads[name].append(threading.current_thread().name)
            return real(*args)

        return run

    for name in threads:
        monkeypatch.setattr(market_heatmap, name, spied(name))
    statuses, _ = await _get(_app(_page(), monkeypatch))
    assert statuses == [200]
    assert (len(threads["_ends"]), len(threads["_block"])) == (1, 2 * -(-ROWS // BODY_BLOCK_ROWS))
    on = {name for names in threads.values() for name in names}
    assert all(name.startswith(FOLD_THREAD_PREFIX) for name in on), on


async def test_a_cell_that_is_not_finite_is_refused_before_any_byte(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bid = np.zeros((ROWS, COLUMNS))
    bid[ROWS - 1, COLUMNS - 1] = np.nan  # in the last block: a check per block would send first
    started: list[int] = []
    with pytest.raises(ValueError, match="not finite"):
        await _get(_app(_page(bid), monkeypatch), started)
    assert 200 not in started  # the error answer only (500): no byte of the page was sent
