"""Self-contained support for the E17-Q01 harness: nothing here imports another test module.

`SAMPLES` holds one minimal §14/§15-valid (snapshot body, delta body) pair per topic family;
transport tests never judge payload content (that belongs to the producing epics).
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from typing import Any

import msgpack
import pytest
from starlette.websockets import WebSocketDisconnect

BASE_MS = 1_789_132_262_000
ORIGIN = "http://testserver"  # §2.5: allow-listed and sent on every upgrade
_TIMEOUT_S = 5.0


class Clock:
    """Monotonic seconds, advanced only by the test."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def wall_ms(self) -> int:
        return BASE_MS + int(self.now * 1000)


def _receive(ws: Any) -> dict[str, Any]:
    """One frame in the negotiated encoding (§2.2): binary MessagePack on `cv.v1.msgpack` (a text
    frame there fails the test), else JSON text."""
    if ws.accepted_subprotocol == "cv.v1.msgpack":
        frame: dict[str, Any] = msgpack.unpackb(ws.receive_bytes())
        return frame
    text_frame: dict[str, Any] = ws.receive_json()
    return text_frame


def recv_json(ws: Any) -> dict[str, Any]:
    """Next frame, bounded so a regression fails fast instead of hanging the suite."""
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        frame: dict[str, Any] = pool.submit(_receive, ws).result(timeout=_TIMEOUT_S)
    except FutureTimeout:
        pytest.fail(f"no WS frame within {_TIMEOUT_S}s")
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    return frame


def close_code(ws: Any) -> int:
    """The close code; fails if a frame arrives instead."""
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        frame = pool.submit(_receive, ws).result(timeout=_TIMEOUT_S)
    except WebSocketDisconnect as exc:
        return int(exc.code)
    except FutureTimeout:
        pytest.fail("socket neither closed nor sent within the deadline")
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    pytest.fail(f"expected close, got {frame}")


_S = "BTCUSDT"
_U = "00000000-0000-4000-8000-0000000000aa"
_A = "00000000-0000-0000-0000-0000000000a1"
_SER = {"symbol": _S, "bar_type": "time", "param": "1"}
_BAR = {"generation": 0, "index": 1, "t_ms": 1, "o": "1", "h": "2", "l": "1", "c": "2"}
_FP_BAR = {"generation": 0, "index": 1, "t_ms": 1, "cells": []}
_TRADE = {"ts_ms": 1, "price": "100.0", "size": "1", "side": "buy"}
_ORD = {"id": _U, "exchange_account_id": _A, "symbol": _S, "state": "new", "updated_at_ms": 1}
#: A B18 `kill_switch` state (§15.10): an unscoped kind, so no registry entry is needed to `sub`.
_KS = {"machine_kind": "kill_switch", "degraded": False, "machine_hash": "0" * 64,
       "environment": "demo", "updated_at_ms": 1,
       "context_summary": {"scope": "global"}}  # fmt: skip
#: family -> (snapshot body, delta body)
SAMPLES: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {
    "book": (
        {"symbol": _S, "bids": [["100.0", "1.0"]], "asks": [["101.0", "2.0"]]},
        {"symbol": _S, "bids": [["100.0", "0"]], "asks": []},
    ),
    "trades": ({"symbol": _S, "trades": []}, {"symbol": _S, "trades": [_TRADE]}),
    "bars": ({**_SER, "bars": []}, {**_SER, "bars": [{**_BAR, "v": "3", "confirm": False}]}),
    "footprint": ({**_SER, "bars": []}, {**_SER, "bars": [_FP_BAR]}),
    "heatmap": (
        {"symbol": _S, "time_bucket_ms": 500, "columns": []},
        {
            "symbol": _S,
            "time_bucket_ms": 500,
            "columns": [{"t_ms": 1, "price_min": "1", "price_step": "1", "bids": [], "asks": []}],
        },
    ),
    "profile": (
        {"symbol": _S, "kind": "volume", "profiles": []},
        {"symbol": _S, "kind": "volume", "profiles": [{"period_start_ms": 1, "rows": []}]},
    ),
    "metrics": (
        {"symbol": _S, "series": []},
        {"symbol": _S, "series": [{"metric": "cvd", "t_ms": 1, "v": "1"}]},
    ),
    "ticker": ({"tickers": []}, {"tickers": [{"symbol": _S, "last_price": "100.0", "ts_ms": 1}]}),
    "liquidations": (
        {"liquidations": []},
        {"liquidations": [{"symbol": _S, "ts_ms": 1, "side": "buy", "price": "1", "size": "1"}]},
    ),
    "orders": ({"orders": []}, {"orders": [_ORD]}),
    "positions": (
        {"positions": []},
        {
            "positions": [
                {k: v for k, v in _ORD.items() if k != "state"} | {"side": "flat", "size": "0"}
            ]
        },
    ),
    "executions": (
        {"executions": []},
        {
            "executions": [
                {
                    "id": _U,
                    "exec_id": "e1",
                    "order_id": _U,
                    "exchange_account_id": _A,
                    "symbol": _S,
                    "side": "buy",
                    "exec_qty": "1",
                    "exec_price": "1",
                    "ts_ms": 1,
                }
            ]
        },
    ),
    "wallet": (
        {"balances": []},
        {
            "balances": [
                {"exchange_account_id": _A, "coin": "USDT", "equity": "1", "updated_at_ms": 1}
            ]
        },
    ),
    "trade_groups": (
        {"trade_groups": []},
        {"trade_groups": [{"id": _U, "status": "open", "updated_at_ms": 1}]},
    ),
    "rules": ({"rules": []}, {"rules": []}),
    "alerts": (
        {"deliveries": []},
        {
            "deliveries": [
                {
                    "id": 1,
                    "alert_id": _U,
                    "channel": "in_app",
                    "status": "queued",
                    "message": "m",
                    "fired_at_ms": 1,
                }
            ]
        },
    ),
    "recorder": ({"overall": "healthy", "symbols": []}, {"overall": "healthy", "symbols": []}),
    "system": ({"kind": "health"}, {"kind": "notice"}),
    "machines": (
        {**_KS, "state": "clear", "tags": ["trading_allowed"]},
        {**_KS, "state": "engaged", "tags": ["trading_blocked"]},
    ),
}
