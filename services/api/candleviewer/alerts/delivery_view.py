"""What a delivery row shows a client beyond its columns (E40-D02 CC-7, CC-9).

- `delivery_kind`: the row's class (D-39), derived from the `context` flags the server itself
  wrote (`evaluator.py` writes `storm_summary` and `disarmed`; the channel-failure notice
  `channel_failure`), so no column and no migration: a firing is everything else.
- `storm_summary`: a summary's held count, symbols and window (D01 G13); the window is None on a
  summary written before CC-7.
- `silenced`: why a mute or quiet hours held the firing's optional channels (CC-9), else None.
- A summary's `symbols` are bounded (ticket Security notes): at most `CONTEXT_SYMBOLS_MAX`,
  each cut at `CONTEXT_TEXT_MAX` characters.

Shared by the REST inbox (`api/alert_deliveries.py`) and the `alerts` WS topic, so the two
transports can never class a row differently. Pure.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final, Literal

DeliveryKind = Literal["firing", "disarm_notice", "failure_notice", "storm_summary"]
SilenceReason = Literal["muted_symbol", "quiet_hours"]
#: A storm summary's `symbols` bounds (22 / 23 `summary.symbols`).
CONTEXT_SYMBOLS_MAX: Final = 100
CONTEXT_TEXT_MAX: Final = 1000


def _flag(context: Mapping[str, Any], key: str) -> bool:
    return context.get(key) is True


def delivery_kind(context: Mapping[str, Any] | None) -> DeliveryKind:
    """D-39's class of a row, from the flags the server wrote into its `context`."""
    ctx = context if isinstance(context, Mapping) else {}
    if _flag(ctx, "storm_summary"):
        return "storm_summary"
    if _flag(ctx, "channel_failure"):
        return "failure_notice"
    if _flag(ctx, "disarmed"):
        return "disarm_notice"
    return "firing"


@dataclass(frozen=True, slots=True)
class StormSummary:
    count: int
    symbols: tuple[str, ...]
    window_start_ms: int | None
    window_end_ms: int | None


def _int(v: Any) -> int | None:
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def storm_summary(context: Mapping[str, Any] | None) -> StormSummary | None:
    """A `storm_summary` row's count, symbols and window; None for every other kind."""
    if not isinstance(context, Mapping) or delivery_kind(context) != "storm_summary":
        return None
    raw = context.get("symbols")
    items = raw if isinstance(raw, list) else []
    listed = [s[:CONTEXT_TEXT_MAX] for s in items if isinstance(s, str)]
    symbols = tuple(listed[:CONTEXT_SYMBOLS_MAX])  # 22 / 23 `summary.symbols` bounds
    return StormSummary(
        count=max(_int(context.get("suppressed")) or 0, 0), symbols=symbols,
        window_start_ms=_int(context.get("window_start_ms")),
        window_end_ms=_int(context.get("window_end_ms")),
    )  # fmt: skip


def silenced(context: Mapping[str, Any] | None) -> SilenceReason | None:
    """CC-9: the reason a mute or quiet hours held this firing's optional channels."""
    v = context.get("silenced") if isinstance(context, Mapping) else None
    if v == "muted_symbol":
        return "muted_symbol"
    return "quiet_hours" if v == "quiet_hours" else None


__all__ = [
    "CONTEXT_SYMBOLS_MAX",
    "CONTEXT_TEXT_MAX",
    "DeliveryKind",
    "StormSummary",
    "delivery_kind",
    "silenced",
    "storm_summary",
]
