"""Exact `from`/`to` parsing for `/market/bars` and `/market/klines` (#452).

One conversion for both routes, in integers: a float (`timestamp() * 1e6`) cannot hold every
microsecond of the supported range, so it is never used for a window bound.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Final

_EPOCH: Final = datetime(1970, 1, 1, tzinfo=UTC)
_ONE_US: Final = timedelta(microseconds=1)
#: The instants a storage bind can hold (`domain.sql_names.ts_param` is `EPOCH + timedelta`): from
#: 0001-01-01T00:00:00Z to 9999-12-31T23:59:59.999999Z, in whole microseconds.
MIN_TS_US: Final = (datetime.min.replace(tzinfo=UTC) - _EPOCH) // _ONE_US
MAX_TS_US: Final = (datetime.max.replace(tzinfo=UTC) - _EPOCH) // _ONE_US


def ts_us(value: str | None) -> int | None:
    """An RFC 3339 `from`/`to` as exact integer microseconds since the epoch (`None` stays
    `None`). `ValueError` when it does not parse or lies outside the range a bind can hold."""
    if value is None:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    micros = (parsed - _EPOCH) // _ONE_US
    if not MIN_TS_US <= micros <= MAX_TS_US:
        raise ValueError("timestamp outside the supported range")
    return micros


__all__ = ["MAX_TS_US", "MIN_TS_US", "ts_us"]
