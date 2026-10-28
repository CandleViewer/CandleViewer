"""Bybit v5 `tickers.{symbol}` frame parsing (E08-S03, C-2.2: venue vocabulary
stays in `exchange/bybit/`).

Mapping per `docs/plan/24-internal-schemas.md` §2.3. The linear stream is
delta-encoded: only changed keys are present. Empty-string values are treated
as absent (Bybit uses them for "no value", e.g. an empty book side) so they can
never null out a previously known field. An explicit `"0"` is a real value,
except as the 24 h high or low (E08-T08): no price, so absent too, and a known
range is kept.

Numeric values are bounded in length and scale before they are stored
(`MAX_NUMBER_CHARS`, `MAX_NUMBER_SCALE`), and the next funding time in length and to the
event-time bound (`MAX_TS_MS`): past any, `out_of_bounds`.
"""

from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation
from typing import Final

from candleviewer.exchange.base.frame_guard import (
    MAX_PRICE,
    MAX_QTY,
    MAX_TS_MS,
    FrameRejectedError,
    check_event_ts,
)
from candleviewer.exchange.base.ticker_delta import TickerDelta

TOPIC_PREFIX = "tickers."
_SYMBOL_RE = re.compile(r"^[A-Z0-9]{4,20}$")

_WIRE_TO_FIELD: dict[str, str] = {
    "lastPrice": "last_price",
    "markPrice": "mark_price",
    "indexPrice": "index_price",
    "bid1Price": "bid1_price",
    "bid1Size": "bid1_qty",
    "ask1Price": "ask1_price",
    "ask1Size": "ask1_qty",
    "openInterest": "open_interest",
    "openInterestValue": "open_interest_value",
    "turnover24h": "turnover_24h",
    "volume24h": "volume_24h",
    "price24hPcnt": "price_24h_pcnt",
    "highPrice24h": "high_24h",
    "lowPrice24h": "low_24h",
    "fundingRate": "funding_rate",
}
#: Fields that are prices: must be `> 0` and `<= MAX_PRICE` when present.
_PRICES = frozenset(
    {"last_price", "mark_price", "index_price", "bid1_price", "ask1_price", "high_24h", "low_24h"}
)
#: The 24 h range: a zero is no price, absent like an empty string (E08-T08).
_RANGE = frozenset({"high_24h", "low_24h"})
#: Fields that are sizes/aggregates: must be `>= 0` (an empty side is `"0"`).
_NON_NEGATIVE = frozenset(
    {"bid1_qty", "ask1_qty", "open_interest", "open_interest_value", "turnover_24h", "volume_24h"}
)
_ZERO = Decimal(0)
_MAX_AGG = MAX_QTY * MAX_PRICE
_HUGE = Decimal("1e30")  # signed rates/percentages: finite is the only constraint
#: Numeric fields are bounded in length and scale before they are stored (E08-T08): at most
#: `MAX_NUMBER_CHARS` characters of text, checked before the text is parsed, and at most
#: `MAX_NUMBER_SCALE` decimal places; past either, `out_of_bounds`. The recorded values have at
#: most 15 characters and 8 places (`packages/fixtures/bybit`); an aggregate up to `_MAX_AGG`
#: with the 4 places the recorded ones carry has at most 30 characters.
MAX_NUMBER_CHARS: Final = 32
MAX_NUMBER_SCALE: Final = 20
#: Hot path (C-2.20): wire key -> (field, lo, hi), inclusive; one chained compare.
_BOUNDS: dict[str, tuple[str, Decimal, Decimal]] = {
    wire: (
        name,
        _ZERO if name in _PRICES or name in _NON_NEGATIVE else -_HUGE,
        MAX_PRICE if name in _PRICES else (_MAX_AGG if name in _NON_NEGATIVE else _HUGE),
    )
    for wire, name in _WIRE_TO_FIELD.items()
}


def ticker_topic(symbol: str) -> str:
    return f"{TOPIC_PREFIX}{symbol}"


def parse_ticker_frame(frame: str) -> TickerDelta | None:
    """Parse one raw WS frame. `None` for non-ticker frames (acks, pongs, other
    topics); `ValueError` (`FrameRejectedError` for plausibility) for a ticker
    frame that is malformed or implausible."""
    try:
        msg = json.loads(frame)
    except ValueError:
        return None
    except RecursionError as exc:  # backstop; the pump scans depth before fan-out (#1889)
        raise FrameRejectedError("depth_limit", "frame nests too deep") from exc
    if not isinstance(msg, dict):
        return None
    topic = msg.get("topic")
    if not isinstance(topic, str) or not topic.startswith(TOPIC_PREFIX):
        return None
    symbol = topic[len(TOPIC_PREFIX) :]
    if not _SYMBOL_RE.fullmatch(symbol):
        raise ValueError("ticker frame carries an invalid symbol")
    kind, data, ts = msg.get("type"), msg.get("data"), msg.get("ts")
    if kind not in ("snapshot", "delta") or not isinstance(data, dict):
        raise ValueError("ticker frame missing type/data")
    if not isinstance(ts, int) or isinstance(ts, bool) or ts <= 0:
        raise ValueError("ticker frame missing envelope ts")
    check_event_ts(ts, None, symbol=symbol)
    fields: dict[str, Decimal | int] = {}
    try:
        for wire, name in _WIRE_TO_FIELD.items():
            raw = data.get(wire)
            if raw is None or raw == "":
                continue
            text = str(raw)
            if len(text) > MAX_NUMBER_CHARS:  # bounded before it is parsed
                raise FrameRejectedError("out_of_bounds", name, symbol=symbol)
            value = Decimal(text)
            _, lo, hi = _BOUNDS[wire]
            if not (value.is_finite() and lo <= value <= hi):
                _plausible(name, value, symbol)
            if _finer(value):
                raise FrameRejectedError("out_of_bounds", name, symbol=symbol)
            if name in _RANGE and value.is_zero():
                continue
            fields[name] = value
        nft = data.get("nextFundingTime")
        if nft not in (None, ""):
            text = str(nft)
            if len(text) > MAX_NUMBER_CHARS:  # bounded before it is parsed
                raise FrameRejectedError("out_of_bounds", "next_funding_time", symbol=symbol)
            ms = int(text)
            if not 0 <= ms <= MAX_TS_MS:  # the event-time bound, as for `ts`
                raise FrameRejectedError("out_of_bounds", "next_funding_time", symbol=symbol)
            fields["next_funding_time"] = ms * 1000  # ms -> µs
    except InvalidOperation as exc:
        raise ValueError("unparseable ticker value") from exc
    bid, ask = fields.get("bid1_price"), fields.get("ask1_price")
    if bid is not None and ask is not None and bid > ask:  # crossed top of book (#1892)
        raise FrameRejectedError("crossed", "bid1 above ask1", symbol=symbol)
    return TickerDelta(symbol, kind == "snapshot", ts * 1000, fields)


def _plausible(name: str, value: Decimal, symbol: str) -> None:
    """Slow path: the precise rejection reason for a value outside its bounds."""
    if not value.is_finite():
        raise FrameRejectedError("non_finite", name, symbol=symbol)
    if name in _PRICES:
        if value <= 0:
            raise FrameRejectedError("non_positive", name, symbol=symbol)
        if value > MAX_PRICE:
            raise FrameRejectedError("out_of_bounds", name, symbol=symbol)
    elif name in _NON_NEGATIVE:
        if value < 0:
            raise FrameRejectedError("non_positive", name, symbol=symbol)
        if value > _MAX_AGG:
            raise FrameRejectedError("out_of_bounds", name, symbol=symbol)
    elif not -_HUGE <= value <= _HUGE:
        raise FrameRejectedError("out_of_bounds", name, symbol=symbol)


def _finer(value: Decimal) -> bool:
    """More decimal places than `MAX_NUMBER_SCALE`; a non-finite value, refused before it gets
    here, counts as finer too."""
    exponent = value.as_tuple().exponent
    return not isinstance(exponent, int) or exponent < -MAX_NUMBER_SCALE
