"""Deterministic builder for the E08-T05 Bybit fixture corpus.

NO network: every file is assembled from the Bybit v5 documented shapes already
recorded in this corpus (`publicTrade`, `tickers`, `orderbook`, `recent-trade`)
and the field names parsed by `candleviewer.exchange.bybit` (24-internal-schemas
§2.1-§2.3, §8.6, §14.3). Owner exception #1778 group A: replace with
`capture_fixture.py` captures when a refresh is recorded; the `recorded_*` files
are the first such captures (#3447), listed here, never rewritten. Re-running is
byte-identical (seeded RNG, fixed epoch). Run: python tools/fixtures/build_corpus.py
"""

from __future__ import annotations

import json
import random
from decimal import Decimal
from pathlib import Path
from typing import Any

CAPTURE_DATE = "2026-10-05"
ROOT = Path(__file__).resolve().parents[2] / "packages" / "fixtures" / "bybit" / CAPTURE_DATE
T0 = 1_700_000_000_000
#: Kline open times sit on the interval grid on Bybit (multiples of 60 000 ms for `1`). `T0` is
#: 20 s past a minute, so klines anchor on the minute below it (#2044 review F2).
KLINE_T0 = T0 - T0 % 60_000
KLINE_NOTE = ("open times realigned -20000 ms onto the 1-minute epoch grid (#2044 review F2);"
              " real Bybit kline open times are interval multiples (W from Monday 00:00 UTC);"
              " row count and OHLCV unchanged; documented-shape, not a live capture")  # fmt: skip
WS_HOST = "stream.bybit.com"
REST_HOST = "api-demo.bybit.com"
PUBLIC_REST_HOST = "api.bybit.com"  # public market data has no demo feed (C-2.11)


def _dump(obj: Any) -> str:
    return json.dumps(obj, separators=(",", ":"))


def _write_lines(rel: str, lines: list[str]) -> None:
    path = ROOT / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def _write_json(rel: str, obj: Any) -> None:
    _write_lines(rel, [_dump(obj)])


def trades_window(symbol: str, mid: Decimal, tick: Decimal, seed: int) -> list[str]:
    """3 h of `publicTrade.{symbol}` frames (one every 30 s, 1-2 prints)."""
    rng = random.Random(seed)  # noqa: S311 - deterministic fixture, not crypto
    out: list[str] = []
    n = 0
    for i in range(360):
        ts = T0 + i * 30_000
        data = []
        for _ in range(rng.randint(1, 2)):
            n += 1
            mid += tick * rng.randint(-3, 3)
            side = rng.choice(("Buy", "Sell"))
            data.append(
                {
                    "T": ts - 5,
                    "s": symbol,
                    "S": side,
                    "v": f"{rng.randint(1, 500) / 1000:.3f}",
                    "p": str(mid),
                    "L": "PlusTick" if side == "Buy" else "MinusTick",
                    "i": f"{seed:08x}-0000-4000-8000-{n:012d}",
                    "BT": False,
                }
            )
        out.append(_dump({"topic": f"publicTrade.{symbol}", "type": "snapshot", "ts": ts,
                          "data": data}))  # fmt: skip
    return out


def ticker_burst(symbol: str) -> list[str]:
    """One snapshot then 600 delta-only frames @100 ms (no intervening snapshot)."""
    rng = random.Random(8051)  # noqa: S311 - deterministic fixture, not crypto
    snap = {"symbol": symbol, "lastPrice": "63120.50", "markPrice": "63118.90",
            "indexPrice": "63125.10", "bid1Price": "63120.40", "bid1Size": "12.501",
            "ask1Price": "63120.60", "ask1Size": "9.870", "price24hPcnt": "0.0182",
            "volume24h": "48122.331", "turnover24h": "3041228811.42",
            "openInterest": "61204.113", "openInterestValue": "3862500000.00",
            "fundingRate": "0.0001", "nextFundingTime": "1700006400000"}  # fmt: skip
    out = [_dump({"topic": f"tickers.{symbol}", "type": "snapshot", "ts": T0, "cs": 1,
                  "data": snap})]  # fmt: skip
    last = Decimal("63120.50")
    for i in range(1, 601):
        last += Decimal("0.10") * rng.randint(-2, 2)
        data: dict[str, str] = {"symbol": symbol, "lastPrice": str(last)}
        if i % 7 == 0:
            data["bid1Size"] = f"{rng.randint(1, 9000) / 1000:.3f}"
        out.append(_dump({"topic": f"tickers.{symbol}", "type": "delta", "ts": T0 + i * 100,
                          "cs": i + 1, "data": data}))  # fmt: skip
    return out


def book_gap_window() -> list[str]:
    """Short `orderbook.50.ETHUSDT` window: snapshot, deltas, `u` jump (+3) at frame 30."""
    out: list[str] = []
    u = 1
    for i in range(60):
        if i == 30:
            u += 3
        typ = "snapshot" if i == 0 else "delta"
        px = Decimal("2050.00") + Decimal("0.01") * (i % 5)
        data = {"s": "ETHUSDT", "b": [[str(px), f"{1 + i % 4}.00"]],
                "a": [[str(px + Decimal("0.02")), f"{2 + i % 3}.00"]],
                "u": u, "seq": 9_000 + u}  # fmt: skip
        out.append(_dump({"topic": "orderbook.50.ETHUSDT", "type": typ, "ts": T0 + i * 20,
                          "data": data, "cts": T0 + i * 20 - 3}))  # fmt: skip
        u += 1
    return out


def reconnect_window() -> list[str]:
    """`publicTrade.ETHUSDT`: 20 frames, a 15 s silence (socket drop), then the
    re-subscribed stream replays the last 2 pre-drop prints (dedupe) and continues."""
    frames = []
    for i in range(30):
        n = i if i < 20 else i - 2  # frames 20-21 replay ids 18-19 (overlap after reconnect)
        ts = T0 + (i * 1_000 if i < 20 else 15_000 + i * 1_000)
        frames.append(_dump({"topic": "publicTrade.ETHUSDT", "type": "snapshot", "ts": ts,
                             "data": [{"T": ts - 5, "s": "ETHUSDT",
                                       "S": "Buy" if n % 2 else "Sell", "v": "0.100",
                                       "p": str(Decimal("2050.00") + n), "L": "ZeroPlusTick",
                                       "i": f"e0000001-0000-4000-8000-{n:012d}",
                                       "BT": False}]}))  # fmt: skip
    return frames


def _rest_ok(result: Any, time_ms: int) -> dict[str, Any]:
    return {"retCode": 0, "retMsg": "OK", "result": result, "retExtInfo": {}, "time": time_ms}


def kline_pages(symbol: str) -> list[dict[str, Any]]:
    """`GET /v5/market/kline` interval=1 limit=200: two full pages + a partial one,
    descending list-of-lists `[start, o, h, l, c, volume, turnover]` (§2 kline mapping)."""
    rng = random.Random(8052)  # noqa: S311 - deterministic fixture, not crypto
    rows: list[list[str]] = []
    px = Decimal("63000.0")
    for k in range(450):
        o = px
        c = o + Decimal("0.5") * rng.randint(-20, 20)
        h, lo = max(o, c) + Decimal("1.5"), min(o, c) - Decimal("1.5")
        vol = Decimal(rng.randint(1, 9000)) / 100
        rows.append([str(KLINE_T0 + k * 60_000), str(o), str(h), str(lo), str(c), str(vol),
                     str((vol * c).quantize(Decimal("0.01")))])  # fmt: skip
        px = c
    rows.reverse()  # newest first, like the exchange
    pages = [rows[0:200], rows[200:400], rows[400:]]
    return [_rest_ok({"category": "linear", "symbol": symbol, "list": p}, T0 + 27_000_000)
            for p in pages]  # fmt: skip


def _instrument(symbol: str, base: str, status: str, tick: str, scale: str) -> dict[str, Any]:
    return {
        "symbol": symbol, "contractType": "LinearPerpetual", "status": status,
        "baseCoin": base, "quoteCoin": "USDT", "settleCoin": "USDT",
        "launchTime": "1585699200000", "priceScale": scale,
        "priceFilter": {"tickSize": tick, "minPrice": tick, "maxPrice": "999999.00"},
        "lotSizeFilter": {"qtyStep": "0.001", "minOrderQty": "0.001", "maxOrderQty": "100.000",
                          "maxMktOrderQty": "50.000", "minNotionalValue": "5"},
        "leverageFilter": {"minLeverage": "1", "maxLeverage": "100.00", "leverageStep": "0.01"},
        "fundingInterval": 480, "upperFundingRate": "0.00375", "lowerFundingRate": "-0.00375",
        "copyTrading": "utaOnly",
    }  # fmt: skip


def instruments(after: bool) -> dict[str, Any]:
    """Before/after catalogue pages: SOLUSDT tick 0.010 -> 0.005, LUNAUSDT delisted."""
    rows = [
        _instrument("BTCUSDT", "BTC", "Trading", "0.10", "2"),
        _instrument("ETHUSDT", "ETH", "Trading", "0.01", "2"),
        _instrument("SOLUSDT", "SOL", "Trading", "0.005" if after else "0.010", "3"),
        _instrument("LUNAUSDT", "LUNA", "Closed" if after else "Trading", "0.0001", "4"),
    ]
    return _rest_ok({"category": "linear", "list": rows, "nextPageCursor": ""}, T0)


#: §8.6 error envelopes. 5xx: Bybit's gateway body is not a v5 envelope.
ERRORS: dict[str, tuple[int, Any]] = {
    "error_10018": (200, {"retCode": 10018, "retMsg": "too many visits", "result": {},
                          "retExtInfo": {}, "time": T0}),
    "error_10002": (200, {"retCode": 10002, "retMsg": "invalid request, please check your "
                          "server timestamp or recv_window param", "result": {},
                          "retExtInfo": {}, "time": T0}),
    "error_503": (503, {}),
}  # fmt: skip

SERVER_TIME = _rest_ok({"timeSecond": "1700000000", "timeNano": "1700000000123456789"}, T0)

def funding_history(symbol: str, step_h: int) -> dict[str, Any]:
    """`GET /v5/market/funding/history`: `fundingRate` + `fundingRateTimestamp`
    strings, newest first, `step_h` hours apart (24-internal-schemas §2.7). The
    exchange sends no interval; the cadence is only visible from the spacing."""
    rates = ("0.0001", "0.00008", "-0.00004", "0.00012")
    rows = [{"symbol": symbol, "fundingRate": r,
             "fundingRateTimestamp": str(T0 + 6_400_000 - i * step_h * 3_600_000)}
            for i, r in enumerate(rates)]  # fmt: skip
    return _rest_ok({"category": "linear", "list": rows}, T0 + 30_000_000)


_SRC = "documented-shape (exception #1778 A)"
_RECORDED = {"capture_date": "2026-10-19",
             "source": "capture_fixture.py, fixture-drift run 39210373369 (redacted)"}  # fmt: skip
_MAX = 1_500_000  # bytes; the E08-S05 3 h depth-200 book is the only file near it


def _entry(path: str, symbol: str, stream: str, event: str, host: str = WS_HOST,
           status: int = 200, cap: int = 64_000) -> dict[str, Any]:  # fmt: skip
    return {"path": path, "symbol": symbol, "stream": stream, "host": host,
            "capture_date": CAPTURE_DATE, "source": _SRC, "notable_event": event,
            "http_status": status, "size_cap_bytes": cap}  # fmt: skip


def build() -> list[dict[str, Any]]:
    """Write every generated file and return the manifest entries (all files)."""
    m: list[dict[str, Any]] = []
    for sym, mid, tick, seed in (("BTCUSDT", "63120.50", "0.10", 1),
                                 ("ETHUSDT", "2050.00", "0.01", 2),
                                 ("SOLUSDT", "145.250", "0.010", 3)):  # fmt: skip
        rel = f"ws/clean_publicTrade_{sym}.jsonl"
        _write_lines(rel, trades_window(sym, Decimal(mid), Decimal(tick), seed))
        m.append(_entry(rel, sym, f"publicTrade.{sym}", "clean 3 h window", cap=128_000))
    _write_lines("ws/gap_orderbook_ETHUSDT.jsonl", book_gap_window())
    m.append(_entry("ws/gap_orderbook_ETHUSDT.jsonl", "ETHUSDT", "orderbook.50.ETHUSDT",
                    "sequence gap: u jumps +3 at frame 30"))  # fmt: skip
    _write_lines("ws/reconnect_publicTrade_ETHUSDT.jsonl", reconnect_window())
    m.append(_entry("ws/reconnect_publicTrade_ETHUSDT.jsonl", "ETHUSDT", "publicTrade.ETHUSDT",
                    "reconnect: 15 s silence after frame 20, 2 replayed prints"))  # fmt: skip
    _write_lines("ws/burst_tickers_BTCUSDT.jsonl", ticker_burst("BTCUSDT"))
    m.append(_entry("ws/burst_tickers_BTCUSDT.jsonl", "BTCUSDT", "tickers.BTCUSDT",
                    "delta-only burst: 600 deltas @100 ms after one snapshot",
                    cap=96_000))  # fmt: skip
    for i, page in enumerate(kline_pages("BTCUSDT")):
        rel = f"rest/kline_BTCUSDT_1_page{i}.json"
        _write_json(rel, page)
        m.append(_entry(rel, "BTCUSDT", "GET /v5/market/kline", f"page boundary: page {i} of 3"
                        " (limit 200, 450 rows)", host=REST_HOST, cap=32_000)
                 | {"note": KLINE_NOTE})  # fmt: skip
    for sym, step_h in (("BTCUSDT", 8), ("ETHUSDT", 4)):
        rel = f"rest/funding_history_{sym}_{step_h}h.json"
        _write_json(rel, funding_history(sym, step_h))
        m.append(_entry(rel, sym, "GET /v5/market/funding/history",
                        f"{step_h} h interval symbol, 4 settlements newest-first",
                        host=PUBLIC_REST_HOST, cap=4_000))  # fmt: skip
    for name, after in (("instruments_before", False), ("instruments_after", True)):
        _write_json(f"rest/{name}.json", instruments(after))
        m.append(_entry(f"rest/{name}.json", "*", "GET /v5/market/instruments-info",
                        "LUNAUSDT delisted (Closed), SOLUSDT tickSize 0.010->0.005" if after
                        else "baseline catalogue", host=REST_HOST))  # fmt: skip
    for name, (status, body) in ERRORS.items():
        _write_json(f"rest/{name}.json", body)
        m.append(_entry(f"rest/{name}.json", "*", "GET /v5/market/kline", f"{name} response",
                        host=REST_HOST, status=status, cap=4_000))  # fmt: skip
    _write_json("rest/server_time.json", SERVER_TIME)
    m.append(_entry("rest/server_time.json", "*", "GET /v5/market/time", "server time",
                    host=REST_HOST, cap=4_000))  # fmt: skip
    # Pre-existing E08-S03/S04/S05 fixtures, moved here unchanged.
    m += [
        _entry("ws/orderbook_BTCUSDT.jsonl", "BTCUSDT", "orderbook.200.BTCUSDT",
               "3 h; u hole at frame 2700, u==1 reset at 4000", cap=_MAX),
        _entry("ws/publicTrade_BTCUSDT.jsonl", "BTCUSDT", "publicTrade.BTCUSDT",
               "reconnect between frames 2 and 3", cap=4_000),
        _entry("ws/tickers_BTCUSDT.jsonl", "BTCUSDT", "tickers.BTCUSDT",
               "snapshot + deltas incl. explicit 0", cap=4_000),
        _entry("rest/recent_trade_BTCUSDT.json", "BTCUSDT", "GET /v5/market/recent-trade",
               "gap backfill page", host=REST_HOST, cap=4_000),
    ]  # fmt: skip
    # #3447: frames recorded by capture_fixture.py (redacted) in fixture-drift run 39210373369,
    # copied here unchanged: the live feed's fields that the documented shapes above lack.
    m += [
        _entry("ws/recorded_publicTrade_BTCUSDT.jsonl", "BTCUSDT", "publicTrade.BTCUSDT",
               "recorded: 20 frames with RPI and seq on each print", cap=16_000) | _RECORDED
        | {"window_ms": [1_792_391_736_832, 1_792_391_746_173]},
        _entry("ws/recorded_tickers_BTCUSDT.jsonl", "BTCUSDT", "tickers.BTCUSDT",
               "recorded: snapshot + 19 deltas, incl. tickDirection, prevPrice1h/24h, "
               "fundingCap, singleOpenInterest", cap=8_000) | _RECORDED
        | {"window_ms": [1_792_391_746_229, 1_792_391_748_529]},
    ]  # fmt: skip
    return sorted(m, key=lambda e: str(e["path"]))


def main() -> None:
    manifest = {"capture_date": CAPTURE_DATE, "fixtures": build()}
    (ROOT / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n"
    )


if __name__ == "__main__":
    main()
