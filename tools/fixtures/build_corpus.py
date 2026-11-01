"""Deterministic builder for the E08-T05 Bybit fixture corpus.

NO network: every file is assembled from the Bybit v5 documented shapes already
recorded in this corpus (`publicTrade`, `tickers`, `orderbook`, `recent-trade`)
and the field names parsed by `candleviewer.exchange.bybit` (24-internal-schemas
§2.1-§2.3, §8.6, §14.3). Owner exception #1778 group A: replace with
`capture_fixture.py` captures when a refresh is recorded; the `recorded_*` files
are the first such captures (#3447), listed here, never rewritten. The
`rest/trading-*.json` files are transcribed from the Bybit v5 documentation
(#2877 ruling R2), listed here and never rewritten either: the builder emits only
their manifest entries. The `rest/risk_limit_*.json` files (S-RL, #913) are replies recorded
by `capture_fixture.py --rest-path`, listed here and never rewritten either. So is
`rest/docs-open-interest.json` (E24-T01, #665), the open-interest page's Response Example,
and `ws/docs-all-liquidation.jsonl` (E24-T03, #667), the all-liquidation page's Response Example.
Re-running is byte-identical (seeded RNG, fixed epoch).
Run: python tools/fixtures/build_corpus.py
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


#: E24-T01 (#665): `GET /v5/market/open-interest`, the docs page's row and envelope shape
#: (`rest/docs-open-interest.json`, transcribed), values generated: 260 BTCUSDT 5min rows,
#: newest first, over two cursor pages (limit 200), the last with an empty cursor.
OI_ROWS = 260
OI_T0 = KLINE_T0 - KLINE_T0 % 300_000  # on the 5min grid, like the venue's own timestamps
OI_NOTE = ("documented-shape, not docs-transcribed and not a live capture: the row and envelope"
           " shape follow the docs page retrieved 2026-10-31 (rest/docs-open-interest.json, the"
           " transcription); every value is generated (seeded)")  # fmt: skip


def oi_pages(symbol: str) -> list[dict[str, Any]]:
    rng = random.Random(6650)  # noqa: S311 - deterministic fixture, not crypto
    oi, rows = Decimal("52000"), []
    for k in range(OI_ROWS):
        oi += Decimal(rng.randint(-400, 400)) / 4
        rows.append({"openInterest": f"{oi:.8f}", "singleOpenInterest": f"{oi / 2:.8f}",
                     "timestamp": str(OI_T0 + k * 300_000)})  # fmt: skip
    rows.reverse()
    oldest_s = (OI_T0 + (OI_ROWS - 200) * 300_000) // 1000  # page 0's last row, as the docs'
    cursor = f"lastid%3D{OI_ROWS - 200}%26lasttime%3D{oldest_s}"
    return [_rest_ok({"symbol": symbol, "category": "linear", "list": part,
                      "nextPageCursor": nxt}, OI_T0 + OI_ROWS * 300_000)
            for part, nxt in ((rows[:200], cursor), (rows[200:], ""))]  # fmt: skip


#: E24-T03 (#667): `allLiquidation.{symbol}` pushes in the docs page's frame shape
#: (`ws/docs-all-liquidation.jsonl`, transcribed), values generated: a cascade of 8 pushes 500 ms
#: apart, push 2 holding two identical prints (only `batch_index` tells them apart), push 4 five
#: prints inside one second, and push 2 replayed after a reconnect as the last frame.
LIQ_T0 = T0 + 600_000
LIQ_SRC = "venue docs example @19518b90 (shape; values generated, seeded)"
LIQ_NOTE = ("frame shape transcribed from the docs page (ws/docs-all-liquidation.jsonl); "
            "values generated (seeded)")  # fmt: skip


def liquidation_burst(symbol: str) -> list[str]:
    rng = random.Random(6670)  # noqa: S311 - deterministic fixture, not crypto
    px, pushes = Decimal("63000.0"), []
    for k in range(8):
        ts, n = LIQ_T0 + k * 500, (1, 3, 2, 5, 1, 2, 4, 1)[k]
        rows = []
        for j in range(n):
            px += Decimal(rng.randint(-20, 20)) / 10
            qty = Decimal(rng.randint(1, 900)) / 1000
            rows.append({"T": ts - 400 + j * 90, "s": symbol, "S": rng.choice(("Buy", "Sell")),
                         "v": f"{qty:.3f}", "p": f"{px:.1f}"})  # fmt: skip
        if k == 1:
            rows[1] = dict(rows[0])  # two prints alike in one push: kept apart by batch_index
        pushes.append({"topic": f"allLiquidation.{symbol}", "type": "snapshot", "ts": ts,
                       "data": rows})  # fmt: skip
    pushes.append(pushes[1] | {"ts": LIQ_T0 + 9_000})  # replayed after the reconnect
    return [_dump(p) for p in pushes]


_SRC = "documented-shape (exception #1778 A)"
_RECORDED = {"capture_date": "2026-10-19",
             "source": "capture_fixture.py, fixture-drift run 39210373369 (redacted)"}  # fmt: skip
#: S-RL (#913): `GET /v5/market/risk-limit` replies recorded by `capture_fixture.py --rest-path`
#: from the public `api.bybit.com` endpoint, no key; the redactor found nothing to redact.
_RECORDED_RISK = {"capture_date": "2026-10-25",
                  "source": "capture_fixture.py --rest-path (redacted)"}  # fmt: skip
#: E08-T08 (#4707): one `GET /v5/market/tickers` reply per symbol (`category=linear`), recorded by
#: `capture_fixture.py --rest-path` from the public endpoint, no key; the full venue-wide reply is
#: over the tool's 512 KB cap, so it is not recorded.
_RECORDED_TICKERS = {"capture_date": "2026-10-28",
                     "source": "capture_fixture.py --rest-path (redacted)"}  # fmt: skip
#: #2877 ruling R2 (the #1778 group A pattern): order-path shapes no recording holds yet. Each
#: file is its documentation page's Response Example, keys and values unchanged (for an error,
#: its error-table row). E29-K01's recordings replace them;
#: `tests/contract/bybit/test_contract_trading_drift.py` fails the moment one disagrees. No page
#: shows the HTTP status of its example, so none is stated (`http_status` null).
_DOCS_URL = "https://bybit-exchange.github.io/docs/v5/"
_DOCS_REF = "github.com/bybit-exchange/docs@19518b90fb36e1527eaf99ff692076487a977921"
_TRANSCRIBED = {"capture_date": "2026-10-21", "source": "docs-transcribed",
                "retrieved": "2026-10-21", "http_status": None}  # fmt: skip
#: name -> (stream, documentation page, symbol, what it shows)
_DOCS_SHAPES: dict[str, tuple[str, str, str, str]] = {
    "trading-account-info": ("GET /v5/account/info", "account/account-info", "*",
                             "account info: regular margin, unified status 4"),
    "trading-amend-reply": ("POST /v5/order/amend", "order/amend-order", "*",
                            "amend accepted: orderId and a foreign orderLinkId"),
    "trading-cancel-all-reply": ("POST /v5/order/cancel-all", "order/cancel-all", "*",
                                 "cancel-all: two cancelled orders, success 1"),
    "trading-cancel-reply": ("POST /v5/order/cancel", "order/cancel-order", "*",
                             "cancel accepted: orderId and a foreign orderLinkId"),
    "trading-closed-pnl": ("GET /v5/position/closed-pnl", "position/close-pnl", "ETHPERP",
                           "one closed-PnL row, a next-page cursor"),
    "trading-create-batch-reply": ("POST /v5/order/create-batch", "order/batch-place", "*",
                                   "batch: two spot items, every item code 0"),
    "trading-create-reply": ("POST /v5/order/create", "order/create-order", "*",
                             "create accepted: orderId and the caller's orderLinkId"),
    "trading-error-110001": ("POST /v5/order/cancel", "error", "*",
                             "error-table row 110001 (UTA): code and text only"),
    "trading-error-110072": ("POST /v5/order/create", "error", "*",
                             "error-table row 110072 (UTA): code and text only"),
    "trading-execution-list": ("GET /v5/execution/list", "order/execution", "ETHPERP",
                               "one Trade fill, an empty orderLinkId, a next-page cursor"),
    "trading-fee-rate": ("GET /v5/account/fee-rate", "account/fee-rate", "BTCUSDT",
                         "a spot fee-rate row (category spot)"),
    "trading-order-history": ("GET /v5/order/history", "order/order-list", "BTCUSDT",
                              "one cancelled PostOnly order, a next-page cursor"),
    "trading-order-realtime": ("GET /v5/order/realtime", "order/open-order", "ETHUSDT",
                               "one open limit order with TP/SL, a next-page cursor"),
    "trading-position-list": ("GET /v5/position/list", "position/position", "BTCUSD",
                              "an inverse position (category inverse)"),
    "trading-set-leverage-reply": ("POST /v5/position/set-leverage", "position/leverage", "*",
                                   "set-leverage accepted: empty result"),
    "trading-trading-stop-reply": ("POST /v5/position/trading-stop", "position/trading-stop",
                                   "*", "trading-stop accepted: empty result"),
    "trading-wallet-balance": ("GET /v5/account/wallet-balance", "account/wallet-balance", "*",
                               "a unified wallet with one BTC coin row"),
}  # fmt: skip
#: G-8b (#3963, ruling 11; the #1778 group A pattern, as R2): the private stream's documented
#: frames, one per `ws/private-*.jsonl` file, each its page's sample as written (keys and values
#: unchanged, whitespace compacted): a reply on the Connect page or a topic's Stream Example. No
#: page shows a refused `auth` or `subscribe` reply, so none is transcribed (tests derive them):
#: each is "no public example — K01" in the fixtures README.
#: Each `stream` is the topic as the adapter subscribes it, or `op <name>` for a reply; the samples
#: themselves use the all-in-one topics, and the order sample is an option's (ruling 11: kept
#: verbatim, linear rows derived in-test). E29-K01's recordings replace them;
#: `tests/contract/bybit/test_contract_trading_drift.py` fails the moment one disagrees.
#: name -> (stream, published page, source page, symbol, what it shows)
_DOCS_FRAMES: dict[str, tuple[str, str, str, str, str]] = {
    "private-auth-ok": ("op auth", "ws/connect", "websocket/wss-authentication", "*",
                        "private auth granted: success, ret_msg, op, conn_id"),
    "private-subscribe-ok": ("op subscribe", "ws/connect", "websocket/wss-authentication", "*",
                             "private subscribe acknowledged, no req_id"),
    "private-pong": ("op pong", "ws/connect", "websocket/wss-authentication", "*",
                     "private pong: op pong with args and req_id"),
    "private-order": ("order.linear", "websocket/private/order", "websocket/private/order",
                      "ETH-30DEC22-1400-C", "one option order push (all-in-one topic)"),
    "private-execution": ("execution.linear", "websocket/private/execution",
                          "websocket/private/execution", "BTCUSDT",
                          "one linear Trade fill push, an empty orderLinkId"),
    "private-execution-fast": ("execution.fast.linear", "websocket/private/fast-execution",
                               "websocket/private/fast-execution", "ICPUSDT",
                               "one linear fast fill push, a foreign orderLinkId"),
    "private-position": ("position.linear", "websocket/private/position",
                         "websocket/private/position", "BTCUSDT",
                         "one empty linear position push, positionIdx 2"),
    "private-wallet": ("wallet", "websocket/private/wallet", "websocket/private/wallet", "*",
                       "one unified wallet push with one BTC coin row"),
}  # fmt: skip
_MAX = 1_500_000  # bytes; the E08-S05 3 h depth-200 book is the only file near it


def _docs_url(page: str) -> str:
    """The page's address: a page named as its folder is served as the folder (Docusaurus'
    category index, so `position/position` is `/docs/v5/position`)."""
    folder, _, name = page.rpartition("/")
    return _DOCS_URL + (folder if folder.rpartition("/")[2] == name else page)


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
    oi_docs = {"source_url": _DOCS_URL + "market/open-interest",
               "source_ref": f"{_DOCS_REF}:docs/v5/market/open-interest.mdx"}  # fmt: skip
    for i, page in enumerate(oi_pages("BTCUSDT")):
        rel = f"rest/open_interest_BTCUSDT_5min_page{i}.json"
        _write_json(rel, page)
        m.append(_entry(rel, "BTCUSDT", "GET /v5/market/open-interest",
                        f"cursor paging: page {i} of 2 (limit 200, 260 rows)",
                        host=PUBLIC_REST_HOST, cap=32_000)
                 | oi_docs | {"retrieved": "2026-10-31", "note": OI_NOTE})  # fmt: skip
    m.append(_entry("rest/docs-open-interest.json", "BTCUSD", "GET /v5/market/open-interest",
                    "docs Response Example: 5 inverse rows, a nextPageCursor",
                    host="bybit-exchange.github.io", cap=4_000)
             | _TRANSCRIBED | {"capture_date": "2026-10-31", "retrieved": "2026-10-31"}
             | oi_docs)  # fmt: skip
    liq_page = "websocket/public/all-liquidation"
    liq_docs = {"source_url": _DOCS_URL + liq_page,
                "source_ref": f"{_DOCS_REF}:docs/v5/{liq_page}.mdx"}  # fmt: skip
    _write_lines("ws/allLiquidation_BTCUSDT_burst.jsonl", liquidation_burst("BTCUSDT"))
    m.append(_entry("ws/allLiquidation_BTCUSDT_burst.jsonl", "BTCUSDT", "allLiquidation.BTCUSDT",
                    "cascade: 8 pushes @500 ms, twin prints in push 2, push 2 replayed last",
                    cap=8_000) | liq_docs | {"note": LIQ_NOTE, "source": LIQ_SRC})  # fmt: skip
    m.append(_entry("ws/docs-all-liquidation.jsonl", "ROSEUSDT", "allLiquidation.ROSEUSDT",
                    "docs Response Example: one Sell print (a short was liquidated)",
                    host="bybit-exchange.github.io", cap=4_000)
             | _TRANSCRIBED | {"capture_date": "2026-10-31", "retrieved": "2026-10-31",
                               "source": "venue docs example @19518b90"}
             | liq_docs)  # fmt: skip
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
    m += [
        _entry(f"rest/risk_limit_{sym}.json", sym, "GET /v5/market/risk-limit",
               "recorded: one page of 35 linear tiers, empty nextPageCursor",
               host=PUBLIC_REST_HOST, cap=16_000) | _RECORDED_RISK
        for sym in ("BTCUSDT", "ETHUSDT")
    ]  # fmt: skip
    m += [
        _entry(f"rest/recorded_tickers_{sym}.json", sym, "GET /v5/market/tickers",
               f"recorded: one linear tickers reply for {sym} (highPrice24h / lowPrice24h "
               "present), E08-T08 (#4707)", host=PUBLIC_REST_HOST, cap=4_000) | _RECORDED_TICKERS
        for sym in ("BTCUSDT", "ETHUSDT", "SOLUSDT")
    ]  # fmt: skip
    m += [
        _entry(f"rest/{name}.json", symbol, stream, event, host="bybit-exchange.github.io",
               cap=4_000) | _TRANSCRIBED
        | {"source_url": _docs_url(page), "source_ref": f"{_DOCS_REF}:docs/v5/{page}.mdx"}
        for name, (stream, page, symbol, event) in _DOCS_SHAPES.items()
    ]  # fmt: skip
    m += [
        _entry(f"ws/{name}.jsonl", symbol, stream, event, host="bybit-exchange.github.io",
               cap=4_000) | _TRANSCRIBED
        | {"source_url": _DOCS_URL + page, "source_ref": f"{_DOCS_REF}:docs/v5/{source}.mdx"}
        for name, (stream, page, source, symbol, event) in _DOCS_FRAMES.items()
    ]  # fmt: skip
    return sorted(m, key=lambda e: str(e["path"]))


def main() -> None:
    manifest = {"capture_date": CAPTURE_DATE, "fixtures": build()}
    (ROOT / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n"
    )


if __name__ == "__main__":
    main()
