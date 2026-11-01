"""E12-X02 deadlines (#452; SR-E12-01: "every storage read behind a bars/klines request is bounded
by `QUERY_TIMEOUT_S`"): a store that never answers, or answers with a raw driver error, ends the
request as 503 `store_unavailable`, never a hang and never a 500.

A hung call waits on an `asyncio.Event` nobody sets (no sleep). The deadline is lowered to 50 ms
in each module that may read it, and the test cuts the request at `GUARD_S`: a request still
running then has no deadline. The app runs in process over `httpx.ASGITransport` (no socket).

Findings (#452 F2): `/market/klines` has no deadline on the hot read or the recording-start read,
and a raw driver error from the hot read is a 500; `/market/bars` has neither for its
recording-start read, and its bar read maps only timeouts and socket errors (#3287 owns that half).
"""

from __future__ import annotations

import asyncio
from typing import Final

import asyncpg
import httpx
import pytest

from candleviewer.api import market, market_bars
from candleviewer.bars import limits
from candleviewer.ingestion import kline_read
from tests.contract._market_world import KLINES_NOW_US, NOW, READER, T0, operation
from tests.contract.test_market_bars_contract import _iso
from tests.security.bars.conftest import BAR_READ, HOT_READ, RECORDING, TOTALS, Fault, Stores, hang

DEADLINE_S: Final = 0.05
GUARD_S: Final = 1.0
F2_BARS: Final = "#452 findings row F2 (bars half: #3287): the recording-start read has no deadline"
F2_BARS_DRIVER: Final = "#452 findings row F2 (bars half: #3287): a raw driver error is a 500"
F2_KLINES: Final = "#452 findings row F2: /market/klines reads have no SR-E12-01 deadline"
F2_KLINES_DRIVER: Final = "#452 findings row F2: a raw driver error on the klines hot read is a 500"
_BARS: Final = {"symbol": "BTCUSDT", "from": _iso(T0), "to": _iso(NOW), "limit": 10}
_HOUR_US: Final = 3_600_000_000
_KLINES: Final = {"symbol": "BTCUSDT", "interval": "1", "limit": 10,
                  "from": _iso(KLINES_NOW_US - _HOUR_US), "to": _iso(KLINES_NOW_US)}  # fmt: skip


def _known(reason: str) -> pytest.MarkDecorator:
    return pytest.mark.xfail(strict=True, reason=reason)


async def _driver_error() -> None:
    raise asyncpg.InterfaceError("connection is closed")


@pytest.fixture(autouse=True)
def _short_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    for module in (limits, market_bars, market, kline_read):
        monkeypatch.setattr(module, "QUERY_TIMEOUT_S", DEADLINE_S, raising=False)


async def _answer(stores: Stores, op: str, query: dict[str, object]) -> httpx.Response:
    params = {k: str(v) for k, v in query.items()}
    async with stores.asgi() as client:
        try:
            async with asyncio.timeout(GUARD_S):
                return await client.get(operation(op)[0], params=params, headers=dict(READER))
        except TimeoutError:
            pytest.fail(f"{op} still running {GUARD_S} s after a {DEADLINE_S} s deadline")


async def _unavailable(stores: Stores, op: str, query: dict[str, object], call: str) -> None:
    resp = await _answer(stores, op, query)
    assert (resp.status_code, resp.json().get("code")) == (503, "store_unavailable"), resp.text
    assert stores.calls[call] >= 1  # the faulted call was reached: the case is not vacuous
    assert "connection is closed" not in resp.text


@pytest.mark.parametrize(
    ("bar_type", "param", "call"),
    [("time", "1", BAR_READ), ("tick", "100", BAR_READ), ("tick", "100", TOTALS)],
)
async def test_deadline_bars_hung_read_or_count_is_503(
    stores: Stores, bar_type: str, param: str, call: str
) -> None:
    stores.faults[call] = hang
    await _unavailable(stores, "getBars", {**_BARS, "bar_type": bar_type, "param": param}, call)


@pytest.mark.parametrize(
    ("op", "call", "fault"),
    [
        pytest.param("getBars", RECORDING, hang, marks=_known(F2_BARS)),
        pytest.param("getBars", BAR_READ, _driver_error, marks=_known(F2_BARS_DRIVER)),
        pytest.param("getKlines", HOT_READ, hang, marks=_known(F2_KLINES)),
        pytest.param("getKlines", RECORDING, hang, marks=_known(F2_KLINES)),
        pytest.param("getKlines", HOT_READ, _driver_error, marks=_known(F2_KLINES_DRIVER)),
    ],
)
async def test_deadline_unbounded_or_unmapped_store_call_is_503(
    stores: Stores, op: str, call: str, fault: Fault
) -> None:
    stores.faults[call] = fault
    query = {**_BARS, "bar_type": "tick", "param": "100"} if op == "getBars" else _KLINES
    await _unavailable(stores, op, query, call)
