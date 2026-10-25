"""What one position read shows of a recorded stop (E29-T04 #913, moved for E29-T05 #848 S5c;
21-database-schema.md Sec.3.3.11, 24-internal-schemas.md Sec.8.8 rule 6): pure predicates over a
`recorded_stops` row and a position, one definition for the complete read (`stop_resolution`,
which re-exports them under the same names) and the position projection (`positions`), so both
read a stop as shown, open or flat alike (C-2.6). Moved verbatim from `stop_resolution.py`, which
a hot-path module may not import (it imports the B1 binding, C-2.20); this module imports types
only and is on the hot-path contract."""

from __future__ import annotations

from typing import Literal

from candleviewer.exchange.base.models import Position
from candleviewer.storage.repositories.recorded_stops import RecordedStopRow

__all__ = ["PositionState", "full_shows", "position_state", "trail_unreadable"]

#: The row's position as the read shows it: `open` on the row's side, else `flat`.
type PositionState = Literal["open", "flat"]


def position_state(row: RecordedStopRow, position: Position | None) -> PositionState:
    """`open` when the position holds a size on the row's side, else `flat`: none on its side,
    the other side's included (a one-way reversal)."""
    if position is None or position.qty <= 0 or position.side != row.position_side.lower():
        return "flat"
    return "open"


def full_shows(row: RecordedStopRow, position: Position | None) -> bool:
    """A Full side the position shows: open on the row's side, its stop-loss or take-profit at
    the trigger. Never a trail: it is shown only by its distance and activation price."""
    if row.tpsl_mode != "Full" or position is None or position_state(row, position) != "open":
        return False
    if row.kind == "take_profit":
        return position.take_profit == row.trigger_price
    return row.trailing_distance is None and position.stop_loss == row.trigger_price


def trail_unreadable(row: RecordedStopRow, position: Position | None) -> bool:
    """A trail whose distance the open position shows: no read shows its activation price yet
    (`[O-4]`), so it can be neither shown nor taken for absent, and is held."""
    return (
        row.tpsl_mode == "Full"
        and row.trailing_distance is not None
        and position is not None
        and position_state(row, position) == "open"
        and position.trailing_stop_distance == row.trailing_distance
    )
