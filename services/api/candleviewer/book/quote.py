"""`BestQuoteEvent` from the top of the live tier (E21-T01, 24 §2.8, BQ-1).

No `orderbook.1` stream feeds it: the quote is `top(1)` of the symbol's active tier, read after
each event that tier applied, and it is published only when one of its four fields changed. So an
event that leaves the top unchanged, the depth-1 keepalive resend included, publishes none, and
nothing is published while the book is not live (the caller holds no book then).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Final

from candleviewer.book.models import BestQuoteEvent
from candleviewer.book.state import BookState
from candleviewer.domain.events import uuid7
from candleviewer.domain.primitives import EventId
from candleviewer.exchange.base.models import BookDelta, BookSnapshot

_BPS: Final = Decimal(10_000)
_Top = tuple[int, Decimal, int, Decimal]


class QuoteTracker:
    """The last quote published per symbol; one entry per symbol with a live book."""

    __slots__ = ("_last",)

    def __init__(self) -> None:
        self._last: dict[str, _Top] = {}

    def update(self, book: BookState, applied: BookSnapshot | BookDelta) -> BestQuoteEvent | None:
        """The quote of `book` after `applied`, or `None` when its top did not change (or a side
        is empty). The envelope carries `applied`'s exchange and ingest stamps."""
        (bids, asks), symbol = book.top(1), applied.symbol
        if not bids or not asks:
            self._last.pop(symbol, None)
            return None
        bid, ask = bids[0], asks[0]
        top = (bid.price_ticks, bid.qty, ask.price_ticks, ask.qty)
        if self._last.get(symbol) == top:
            return None
        self._last[symbol] = top
        mid = (bid.price + ask.price) / 2
        return BestQuoteEvent(
            event_id=EventId(uuid7(applied.ts_ingest // 1000)),
            ts_event=applied.ts_event,
            ts_ingest=applied.ts_ingest,
            source=applied.source,
            symbol=symbol,
            bid=bid.price,
            bid_qty=bid.qty,
            ask=ask.price,
            ask_qty=ask.qty,
            spread_ticks=ask.price_ticks - bid.price_ticks,
            spread_bps=(ask.price - bid.price) / mid * _BPS,
            mid=mid,
        )

    def forget(self, symbol: str) -> None:
        """The symbol's book left LIVE or was dropped: its next live top is a change."""
        self._last.pop(symbol, None)


__all__ = ["QuoteTracker"]
