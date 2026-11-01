"""E12-X02 deadlines (#452; SR-E12-01: "every storage read behind a bars/klines request is bounded
by `QUERY_TIMEOUT_S`"): a store that never answers, or answers with a raw driver error, ends the
request as 503 `store_unavailable`, never a hang and never a 500.

Every test runs on a `VirtualTimeLoop` (`@virtual`, `tests/unit/audit/audit_waits.py`, as the
deadline tests of `tests/unit/ws/` and `tests/contract/` do, C-13.7): the route's real 2 s
deadline and the test's `GUARD_S` both run on fake seconds, which move only when nothing else can
happen, so a deadline passes on the clock, never because the host is slow. A hung call waits on
an `asyncio.Event` nobody sets (no sleep). The deadline is not lowered: a request still running at
`GUARD_S` has none. The app runs in process over `httpx.ASGITransport` (no socket).

A known gap is a strict xfail on how it fails: a hang hits the guard (`pytest.fail`), a driver
error is a 500 (`AssertionError` on the status). The findings register on #452 holds the analysis
(F2; the /market/bars half is #3287).
"""

from __future__ import annotations

import asyncio
from typing import Final

import asyncpg
import httpx
import pytest

from candleviewer.bars import limits
from tests.contract._market_world import KLINES_NOW_US, NOW, READER, T0, operation
from tests.contract.test_market_bars_contract import _iso
from tests.security.bars.conftest import BAR_READ, HOT_READ, RECORDING, TOTALS, Fault, Stores, hang
from tests.unit.audit.audit_waits import virtual

#: Fake seconds past SR-E12-01's deadline at which a request still running is a hang.
GUARD_S: Final = limits.QUERY_TIMEOUT_S * 5
F2_BARS: Final = "#452 findings row F2 (bars half: #3287): a hung recording-start read"
F2_BARS_DRIVER: Final = "#452 findings row F2 (bars half: #3287): a driver error from the bar read"
F2_KLINES: Final = "#452 findings row F2: a hung /market/klines store read"
F2_KLINES_DRIVER: Final = "#452 findings row F2: a driver error from the klines hot read"
BARS: Final = {"symbol": "BTCUSDT", "from": _iso(T0), "to": _iso(NOW), "limit": 10}
_HOUR_US: Final = 3_600_000_000
_KLINES: Final = {"symbol": "BTCUSDT", "interval": "1", "limit": 10,
                  "from": _iso(KLINES_NOW_US - _HOUR_US), "to": _iso(KLINES_NOW_US)}  # fmt: skip


def _hangs(reason: str) -> pytest.MarkDecorator:
    return pytest.mark.xfail(strict=True, raises=pytest.fail.Exception, reason=reason)


def _is_500(reason: str) -> pytest.MarkDecorator:
    return pytest.mark.xfail(strict=True, raises=AssertionError, reason=reason)


async def _driver_error() -> None:
    raise asyncpg.InterfaceError("connection is closed")


async def answer(stores: Stores, op: str, query: dict[str, object]) -> httpx.Response:
    params = {k: str(v) for k, v in query.items()}
    async with stores.asgi() as client:  # the guard below: the route's deadline must win
        try:
            async with asyncio.timeout(GUARD_S):
                return await client.get(operation(op)[0], params=params, headers=dict(READER))
        except TimeoutError:
            pytest.fail(f"{op} still running after the {GUARD_S} s guard")


async def assert_unavailable(stores: Stores, op: str, query: dict[str, object], call: str) -> None:
    resp = await answer(stores, op, query)
    assert (resp.status_code, resp.json().get("code")) == (503, "store_unavailable"), resp.text
    assert stores.calls[call] >= 1  # the faulted call was reached: the case is not vacuous
    assert "connection is closed" not in resp.text


@pytest.mark.parametrize(
    ("bar_type", "param", "call"),
    [("time", "1", BAR_READ), ("tick", "100", BAR_READ), ("tick", "100", TOTALS)],
)
@virtual
async def test_deadline_bars_hung_read_or_count_is_503(
    stores: Stores, bar_type: str, param: str, call: str
) -> None:
    stores.faults[call] = hang
    await assert_unavailable(
        stores, "getBars", {**BARS, "bar_type": bar_type, "param": param}, call
    )


@pytest.mark.parametrize(
    ("op", "call", "fault"),
    [
        pytest.param("getBars", RECORDING, hang, marks=_hangs(F2_BARS)),
        pytest.param("getBars", BAR_READ, _driver_error, marks=_is_500(F2_BARS_DRIVER)),
        pytest.param("getKlines", HOT_READ, hang, marks=_hangs(F2_KLINES)),
        pytest.param("getKlines", RECORDING, hang, marks=_hangs(F2_KLINES)),
        pytest.param("getKlines", HOT_READ, _driver_error, marks=_is_500(F2_KLINES_DRIVER)),
    ],
)
@virtual
async def test_deadline_faulted_store_call_is_503(
    stores: Stores, op: str, call: str, fault: Fault
) -> None:
    stores.faults[call] = fault
    query = {**BARS, "bar_type": "tick", "param": "100"} if op == "getBars" else _KLINES
    await assert_unavailable(stores, op, query, call)
