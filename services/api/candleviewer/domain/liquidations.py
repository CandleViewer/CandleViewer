"""Liquidation domain primitives (E24-T03, #667; 21 §4.6 `liquidations`).

Exchange-neutral (C-2.2). A print is one row of the `liquidations` table. `side` is the side of
the liquidated position's CLOSING order, the table's and the API's reading (`sell`: a long was
liquidated); it is derived from `LiquidationEvent.liquidated_side`, never from the event's own
`side` (24 §17.4 L6). The dedup key is `(ts, symbol, side, price, size, batch_index)`.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Final, Literal

type ClosingSide = Literal["buy", "sell"]
#: One side's resume point in the dedup key's order, inclusive: `(ts, price, size, batch_index)`.
type Cut = tuple[int, Decimal, Decimal, int]

STREAM_ALL: Final = "all"


def closing_side(liquidated_side: str) -> ClosingSide:
    """A long is closed by a sell, a short by a buy."""
    return "sell" if liquidated_side == "long" else "buy"


@dataclass(frozen=True, slots=True)
class LiqPrint:
    ts_us: int
    symbol: str
    side: ClosingSide
    price: Decimal
    size: Decimal
    notional: Decimal
    batch_index: int
    recv_ts_us: int | None = None  # None when read back: the reader does not select it

    def key(self) -> tuple[int, str, Decimal, Decimal, int]:
        """The order of the table's dedup key within one symbol: total and deterministic."""
        return (self.ts_us, self.side, self.price, self.size, self.batch_index)


__all__ = ["STREAM_ALL", "ClosingSide", "Cut", "LiqPrint", "closing_side"]
