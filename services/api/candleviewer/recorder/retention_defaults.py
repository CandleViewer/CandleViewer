"""§7 per-stream retention defaults, shipped inside the package (E16-T06 review H1/H3).

`21-database-schema.md` §7 "Retention policy matrix". This is the in-image source of truth for
the reaper: it needs no repo path and no file I/O, so it cannot fail at boot (the repo seed
`backend/db/seeds/retention_defaults.yaml` is not in the API image). A unit test asserts this
table equals that seed, so the two cannot drift.

`(hot_days, total_days)`; `None` total = keep forever. A stream that is NOT listed here resolves
to keep-forever (fail toward retaining, never toward the 30-day hard default).
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

STREAM_DEFAULTS: Final[Mapping[str, tuple[int, int | None]]] = MappingProxyType(
    {
        "trades": (30, 730),
        "orderbook_delta": (7, 730),
        "orderbook_snapshot": (30, 730),
        "tickers": (30, 730),
        "klines": (90, None),
        "liquidations": (90, None),
        "open_interest": (90, None),
        "funding_rates": (365, None),
        "bars": (90, 730),
        "footprint_cells": (30, 365),
        "profiles": (90, 730),
        "orderflow_metrics": (90, 730),
        "heatmap_cells": (7, 90),
    }
)

#: Postgres `stream_kind` enum value -> recorder stream name (the DB enum predates the split).
DB_STREAM_ALIASES: Final[Mapping[str, str]] = MappingProxyType({"funding": "funding_rates"})


def canonical_stream(db_value: str) -> str:
    return DB_STREAM_ALIASES.get(db_value, db_value)
