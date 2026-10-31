"""Open-interest domain primitives (E24-T01, #665; 21 §4.7 `open_interest`).

Exchange-neutral (C-2.2): no venue field names here. A point is one row of the
`open_interest` table: the ticker tap writes `interval='1s'`, `source='ws_ticker'`; the REST
backfill writes `5min`..`1d`, `source='rest'` with no USD value (the venue's history carries
none, and none is computed). The dedup key `(ts, symbol, interval, source)` keeps the two apart.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from typing import Final, Literal

type OiSource = Literal["ws_ticker", "rest"]

SOURCE_WS_TICKER: Final = "ws_ticker"
SOURCE_REST: Final = "rest"
INTERVAL_TICKER: Final = "1s"
#: Native spacing of each series, µs. The REST intervals are the venue's `intervalTime` enum.
INTERVAL_US: Final[dict[str, int]] = {
    "1s": 1_000_000,
    "5min": 300_000_000,
    "15min": 900_000_000,
    "30min": 1_800_000_000,
    "1h": 3_600_000_000,
    "4h": 14_400_000_000,
    "1d": 86_400_000_000,
}
REST_INTERVALS: Final = ("5min", "15min", "30min", "1h", "4h", "1d")


def source_of(interval: str) -> OiSource:
    """The one series an interval names: `1s` is the ticker tap, the rest are REST history."""
    return "ws_ticker" if interval == INTERVAL_TICKER else "rest"


@dataclass(frozen=True, slots=True)
class OiPoint:
    ts_us: int
    symbol: str
    open_interest: Decimal
    open_interest_value: Decimal | None
    interval: str
    source: str


class OiRowRejected(ValueError):
    """An open-interest row or envelope failed strict validation; `reason` is a bounded label."""

    def __init__(self, message: str, reason: str = "envelope") -> None:
        super().__init__(message)
        self.reason = reason


class OiFetchFailed(Exception):
    """An upstream page could not be fetched. `http_status` / `ret_code` are for the log only."""

    def __init__(
        self, message: str, *, retryable: bool, http_status: int | None, ret_code: int | None
    ) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.http_status = http_status
        self.ret_code = ret_code


class OiPage(list[OiPoint]):
    """Accepted rows of one upstream page (newest first), the venue's opaque next-page cursor
    (None at the end) and the bounded reasons of rows rejected (fail-closed per row)."""

    def __init__(
        self,
        rows: Iterable[OiPoint] = (),
        *,
        next_cursor: str | None = None,
        rejected_reasons: list[str] | None = None,
    ) -> None:
        super().__init__(rows)
        self.next_cursor = next_cursor
        self.rejected_reasons: list[str] = rejected_reasons or []


__all__ = [
    "INTERVAL_TICKER",
    "INTERVAL_US",
    "REST_INTERVALS",
    "SOURCE_REST",
    "SOURCE_WS_TICKER",
    "OiFetchFailed",
    "OiPage",
    "OiPoint",
    "OiRowRejected",
    "OiSource",
    "source_of",
]
