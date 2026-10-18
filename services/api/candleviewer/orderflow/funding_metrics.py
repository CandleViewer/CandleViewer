"""Funding-rate metrics (E24-T02). Labels are bounded: `symbol` values come only
from the instruments cache (validated against `_SYMBOL_RE` and capped), `result`
and `endpoint` are closed enums. Registry-descriptor registration is E24-T04."""

from __future__ import annotations

import re
from typing import Final

from candleviewer.observability.metrics import Counter, Gauge

MAX_SYMBOL_LABELS: Final = 64
OTHER_SYMBOL: Final = "other"
_SYMBOL_RE: Final = re.compile(r"^[A-Z0-9]{2,24}$")
_seen: set[str] = set()


def symbol_label(symbol: str) -> str:
    """Bounded `symbol` label: well-formed and within the cap, else `other`."""
    if symbol in _seen:
        return symbol
    if not _SYMBOL_RE.fullmatch(symbol) or len(_seen) >= MAX_SYMBOL_LABELS:
        return OTHER_SYMBOL
    _seen.add(symbol)
    return symbol


deriv_funding_refresh_total = Counter(
    "deriv_funding_refresh_total",
    "Funding history backfill/refresh runs, by symbol and result.",
    ["symbol", "result"],
)
deriv_funding_backfill_pages_total = Counter(
    "deriv_funding_backfill_pages_total",
    "Funding history pages fetched by the backfill.",
)
deriv_funding_interval_minutes = Gauge(
    "deriv_funding_interval_minutes",
    "Resolved funding interval (minutes) per symbol, so a wrong interval is visible.",
    ["symbol"],
)
deriv_range_rejected_total = Counter(
    "deriv_range_rejected_total",
    "History requests rejected for an out-of-bounds range/limit/cursor, by endpoint.",
    ["endpoint"],
)
deriv_upstream_schema_rejected_total = Counter(
    "deriv_upstream_schema_rejected_total",
    "Upstream derivatives payloads rejected by strict validation, by topic and bounded reason.",
    ["topic", "reason"],
)
