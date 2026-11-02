"""Exchange-side truth kept by the stub exchange (E08-Q03).

The oracle applies every frame the exchange *emits* (before any fault), so it
is the REST-snapshot oracle the resync assertions compare against, and the
source of the recent-trade backfill page. Payload shapes mirror the recorded
corpus (the 2026-10-05 fixture set): book snapshot frames
and the recent-trade REST row shape - nothing invented.
"""

from __future__ import annotations

import json
from collections import deque
from decimal import Decimal
from typing import Any

RECENT_TRADE_LIMIT = 1000


class BookOracle:
    def __init__(self, symbol: str, depth: int) -> None:
        self.symbol, self.depth = symbol, depth
        self.bids: dict[str, str] = {}
        self.asks: dict[str, str] = {}
        self.u = 0
        self.seq = 0
        self.ts_ms = 0

    def apply(self, msg: dict[str, Any]) -> None:
        data = msg["data"]
        if msg.get("type") == "snapshot":
            self.bids, self.asks = {}, {}
        for side, key in ((self.bids, "b"), (self.asks, "a")):
            for price, qty in data.get(key, []):
                if Decimal(qty) == 0:
                    side.pop(price, None)
                else:
                    side[price] = qty
        self.u, self.seq, self.ts_ms = int(data["u"]), int(data.get("seq", 0)), int(msg["ts"])

    def snapshot_frame(self) -> str:
        """What the exchange sends on (re)subscribe: the full current book."""
        bids = sorted(self.bids.items(), key=lambda kv: Decimal(kv[0]), reverse=True)
        asks = sorted(self.asks.items(), key=lambda kv: Decimal(kv[0]))
        body = {
            "topic": f"orderbook.{self.depth}.{self.symbol}",
            "type": "snapshot",
            "ts": self.ts_ms,
            "data": {
                "s": self.symbol,
                "b": [list(x) for x in bids[: self.depth]],
                "a": [list(x) for x in asks[: self.depth]],
                "u": self.u,
                "seq": self.seq,
            },
            "cts": self.ts_ms,
        }
        return json.dumps(body, separators=(",", ":"))

    def levels(self) -> tuple[dict[Decimal, Decimal], dict[Decimal, Decimal]]:
        def conv(side: dict[str, str]) -> dict[Decimal, Decimal]:
            return {Decimal(p): Decimal(q) for p, q in side.items()}

        return conv(self.bids), conv(self.asks)


class TradeOracle:
    """Every print the exchange emitted, newest last (bounded like the endpoint)."""

    def __init__(self, limit: int = RECENT_TRADE_LIMIT) -> None:
        self.limit = limit  # #1944: a small page lets a lost run fall off it
        self.prints: dict[str, deque[dict[str, Any]]] = {}

    def apply(self, msg: dict[str, Any]) -> None:
        for rec in msg.get("data", []):
            sym = rec["s"]
            ring = self.prints.setdefault(sym, deque(maxlen=self.limit))
            ring.append(rec)

    def recent_trade_body(self, symbol: str, limit: int) -> dict[str, Any]:
        rows = list(self.prints.get(symbol, ()))[-limit:]
        rows.reverse()  # the endpoint returns newest first
        return {
            # nosemgrep: cv-adapter-isolation,cv-bybit-vocabulary-leak reason=B5-b-harness owner=@CandleViewer/security review=2026-12-31  # noqa: E501
            "retCode": 0,
            # nosemgrep: cv-adapter-isolation,cv-bybit-vocabulary-leak reason=B5-b-harness owner=@CandleViewer/security review=2026-12-31  # noqa: E501
            "retMsg": "OK",
            "result": {
                "category": "linear",
                "list": [
                    {
                        "execId": r["i"],
                        "symbol": r["s"],
                        "price": r["p"],
                        "size": r["v"],
                        "side": r["S"],
                        "time": str(r["T"]),
                        "isBlockTrade": bool(r.get("BT", False)),
                    }
                    for r in rows
                ],
            },
            # nosemgrep: cv-adapter-isolation,cv-bybit-vocabulary-leak reason=B5-b-harness owner=@CandleViewer/security review=2026-12-31  # noqa: E501
            "retExtInfo": {},
            "time": 0,
        }
