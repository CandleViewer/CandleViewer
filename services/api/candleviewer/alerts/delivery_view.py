"""What a delivery row shows a client beyond its columns (E40-D02 CC-2, CC-7).

- `delivery_kind`: the row's class (D-39), derived from the `context` flags the server itself
  wrote (`evaluator.py` writes `storm_summary` and `disarmed`; the channel-failure notice
  `channel_failure`), so no column and no migration: a firing is everything else.
- `storm_summary`: a summary's held count, symbols and window (D01 G13); the window is None on a
  summary written before CC-7.
- `silenced`: why a mute or quiet hours held the firing's optional channels (CC-9), else None.
- `public_context`: the `context` `getAlertDelivery` serves, from a closed allow-list, so the
  evaluator's internal `condition_hash` and `gates` (and any key not listed) never leave. A
  `values` entry is served only where the rendered body would show it (`render.value_shown`): a
  metric of `account` or `position` scope, or one the registry does not know, is left out. Each
  value must have its declared type (a negative count or a non-finite number is left out), and
  the answer is bounded (ticket Security notes): at most `CONTEXT_VALUES_MAX` `values`,
  `CONTEXT_SYMBOLS_MAX` `symbols`, every string cut at `CONTEXT_TEXT_MAX` characters.

Shared by the REST inbox (`api/alert_deliveries.py`) and the `alerts` WS topic, so the two
transports can never class a row differently. Pure.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final, Literal

from candleviewer.alerts.render import TitleOf, default_title, value_shown

DeliveryKind = Literal["firing", "disarm_notice", "failure_notice", "storm_summary"]
SilenceReason = Literal["muted_symbol", "quiet_hours"]
_SILENCE: Final[frozenset[str]] = frozenset({"muted_symbol", "quiet_hours"})
#: `DeliverySuppressionReason` (22): the closed set served under either suppression key.
_SUPPRESSION: Final[frozenset[str]] = frozenset({
    "storm", "email_relay_off", "webhook_disabled", "push_unavailable", "recipient_deleted",
    "unknown_channel", "owner_inactive", "muted_symbol", "quiet_hours", "window_visible",
    "desktop_off",
})  # fmt: skip
_ENUMS: Final[Mapping[str, frozenset[str]]] = {
    "silenced": _SILENCE, "suppressed_reason": _SUPPRESSION, "suppression_reason": _SUPPRESSION,
}  # fmt: skip
#: The served `context`'s bounds (22 `AlertDeliveryContext`).
CONTEXT_VALUES_MAX: Final = 64
CONTEXT_SYMBOLS_MAX: Final = 100
CONTEXT_TEXT_MAX: Final = 1000
CONTEXT_KEY_MAX: Final = 64
#: Keys whose integer value is a count or an id: never negative.
_NON_NEGATIVE: Final = frozenset({"suppressed", "failed_delivery_id"})

#: `AlertDeliveryContext` (22): the keys served, with the JSON types each may hold. A key whose
#: value has another type is left out rather than served off-contract.
_SCALAR: Final = (str, int, float, bool, type(None))
PUBLIC_CONTEXT_KEYS: Final[Mapping[str, tuple[type, ...]]] = {
    "trigger_type": (str,), "symbol": (str, type(None)), "event_ts_ms": (int,),
    "evaluated_at_ms": (int,), "bar_open_ms": (int, type(None)), "values": (dict,),
    "suppressed_reason": (str,), "suppression_reason": (str,), "disarmed": (bool,),
    "reason": (str,), "metric": (str,), "channel_failure": (bool,),
    "failed_delivery_id": (int,), "storm_summary": (bool,), "suppressed": (int,),
    "symbols": (list,), "window_start_ms": (int,), "window_end_ms": (int,), "silenced": (str,),
}  # fmt: skip
#: Never served, whatever the allow-list says (CC-2; `evaluator.py` writes both).
INTERNAL_CONTEXT_KEYS: Final = frozenset({"condition_hash", "gates"})


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


def _typed(key: str, v: Any) -> bool:
    types = PUBLIC_CONTEXT_KEYS[key]
    if isinstance(v, bool) and bool not in types:
        return False  # a bool is an int to Python, never to the contract
    if not isinstance(v, types):
        return False
    if key in _NON_NEGATIVE:
        return isinstance(v, int) and v >= 0
    return key not in _ENUMS or v in _ENUMS[key]


def _scalar(x: Any) -> bool:
    """A served `values` entry: JSON scalar, finite (jsonb holds no NaN; a float might)."""
    if isinstance(x, float):
        return math.isfinite(x)
    return isinstance(x, _SCALAR)


def _cut(x: Any) -> Any:
    return x[:CONTEXT_TEXT_MAX] if isinstance(x, str) else x


def public_context(
    context: Mapping[str, Any] | None, title_of: TitleOf = default_title
) -> dict[str, Any]:
    """CC-2: the allow-listed keys of *context*, each of its declared type and bounded; `values`
    keeps finite scalar entries of metrics the body may show only (*title_of*'s scopes; none
    without a registry), and `symbols` string entries only."""
    if not isinstance(context, Mapping):
        return {}
    out: dict[str, Any] = {}
    for key, v in context.items():
        if key in INTERNAL_CONTEXT_KEYS or key not in PUBLIC_CONTEXT_KEYS or not _typed(key, v):
            continue
        if key == "values":
            kept = [
                (str(k), _cut(x))
                for k, x in v.items()
                if _scalar(x)
                and len(str(k)) <= CONTEXT_KEY_MAX  # 22: a longer name is dropped
                and value_shown(str(k), title_of)  # account data: as the renderer (D-23)
            ]
            v = dict(kept[:CONTEXT_VALUES_MAX])
        elif key == "symbols":
            v = [_cut(s) for s in v if isinstance(s, str)][:CONTEXT_SYMBOLS_MAX]
        else:
            v = _cut(v)
        out[key] = v
    return out


__all__ = [
    "CONTEXT_SYMBOLS_MAX",
    "CONTEXT_TEXT_MAX",
    "CONTEXT_VALUES_MAX",
    "INTERNAL_CONTEXT_KEYS",
    "PUBLIC_CONTEXT_KEYS",
    "DeliveryKind",
    "StormSummary",
    "delivery_kind",
    "public_context",
    "silenced",
    "storm_summary",
]
