"""Recorded venue-wide ticker replies and ticker frames for the E08-T08 tests (#4707).

Every key comes from a recording (C-13.5); this module only selects, joins and re-keys them,
and varies a price only where it says so:

- `recorded(symbol)`: one of the three recorded `GET /v5/market/tickers` replies (`category=linear`,
  one symbol each: `rest/recorded_tickers_{BTCUSDT,ETHUSDT,SOLUSDT}.json`), as received.
- `row(symbol)`: the one item of `symbol`'s recorded reply; for any other symbol, the BTCUSDT item
  with only `symbol` changed. `last_price`, when given, replaces `lastPrice`.
- `reply(rows)`: the recorded BTCUSDT reply with `rows` as its `result.list`; every other key of
  the recorded envelope (its status fields, `result.category` and `time`) as recorded. The
  venue-wide reply is that envelope with a longer list; the full one is over the recorder's 512 KB
  cap, so it was not recorded (see the fixtures README).
- `priced(count)`: `count` items expanded from the three recorded ones in turn, varying only
  `symbol` (`S000USDT`, `S001USDT`, ...) and `lastPrice` (the recorded one plus the item's index).
- `FRAMES` and `DATA`: the recorded BTCUSDT ticker frames (`ws/recorded_tickers_BTCUSDT.jsonl`) and
  the `data` of the first, a full snapshot. `rekeyed(symbol)` is those frames with only `topic` and
  `data.symbol` changed: no ETHUSDT or SOLUSDT ticker frame is recorded.
- `widened(text, bound, past)`: a recorded value's text with zeros added, its value unchanged, up
  to `past` beyond the length (`CHARS`) or scale (`SCALE`) bound every numeric field is held to.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Iterable
from decimal import Decimal
from typing import Any

from tests._corpus import frames, rest

#: The symbols with a recorded reply.
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
_REPLIES: dict[str, dict[str, Any]] = {
    symbol: rest(f"rest/recorded_tickers_{symbol}.json") for symbol in SYMBOLS
}
#: The recorded ticker frames: a full snapshot, then 19 deltas, 100 ms apart.
FRAMES: list[str] = frames("ws/recorded_tickers_BTCUSDT.jsonl")
#: The snapshot frame's `data`: every ticker field the stream sends, as recorded.
DATA: dict[str, Any] = json.loads(FRAMES[0])["data"]
#: Numeric fields are bounded in length and scale before they are stored (E08-T08): a value has
#: at most 32 characters of text and 20 decimal places, on the stream and the venue-wide read.
CHARS, SCALE = 32, 20


def recorded(symbol: str) -> dict[str, Any]:
    """`symbol`'s recorded reply, as received (a copy: a test may change it)."""
    return copy.deepcopy(_REPLIES[symbol])


def row(symbol: str = "BTCUSDT", last_price: str | None = None) -> dict[str, Any]:
    """The recorded item of `symbol`, else BTCUSDT's re-keyed to it; `lastPrice` replaced when
    given."""
    (item,) = _REPLIES.get(symbol, _REPLIES["BTCUSDT"])["result"]["list"]
    out = {**item, "symbol": symbol}
    if last_price is not None:
        out["lastPrice"] = last_price
    return out


def reply(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """The recorded BTCUSDT reply holding `rows` as its list."""
    out = recorded("BTCUSDT")
    out["result"]["list"] = [dict(r) for r in rows]
    return out


def priced(count: int) -> list[dict[str, Any]]:
    """`count` items `S000USDT`, `S001USDT`, ... expanded from the recorded items in turn, each
    one's `lastPrice` its recorded one plus its index."""
    out: list[dict[str, Any]] = []
    for i in range(count):
        base = row(SYMBOLS[i % len(SYMBOLS)])
        price = str(Decimal(base["lastPrice"]) + i)
        out.append({**base, "symbol": f"S{i:03d}USDT", "lastPrice": price})
    return out


def rekeyed(symbol: str) -> list[str]:
    """The recorded BTCUSDT frames as `symbol`'s: only `topic` and `data.symbol` re-keyed."""
    out: list[str] = []
    for raw in FRAMES:
        msg = json.loads(raw)
        msg["topic"] = f"tickers.{symbol}"
        msg["data"]["symbol"] = symbol
        out.append(json.dumps(msg, separators=(",", ":")))
    return out


def widened(text: str, bound: str, past: int) -> str:
    """A recorded value's `text` with zeros added, its value unchanged: in front, to `past`
    characters beyond the length bound (`"length"`), else after the point, to `past` places
    beyond the scale bound."""
    if bound == "length":
        return text.rjust(CHARS + past, "0")
    whole, _, places = text.partition(".")
    return f"{whole}.{places.ljust(SCALE + past, '0')}"
