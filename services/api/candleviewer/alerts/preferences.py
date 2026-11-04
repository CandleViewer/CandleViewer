"""Dispatch-time suppression by symbol mute, quiet hours and the desktop master (E40-D02 CC-9).

Mute and quiet hours are per-channel suppression at dispatch, not an evaluator gate (24 §19.106
CC-9, the #1130 ruling's BQ-3; the evaluator's `muted` / `critical_override` predicates stay
false). A firing is always recorded:

- its `in_app` row is sent, never dropped: a mute or quiet hours only marks it `silenced`
  (`muted_symbol` / `quiet_hours`), so the client shows no toast and plays no sound;
- its `desktop` row is settled `suppressed` with the same reason; with neither, a desktop row of
  any kind is settled `suppressed` / `desktop_off` when the owner's `desktop_enabled` is false;
- every other channel, and every row that is no firing (a disarm notice, a storm summary, a
  failure notice), is left to its adapter.

A user alert never overrides (`USER_ALERTS_OVERRIDE` false, D01 K1-K3); the CO-1..CO-12 kinds are
risk and system events, never alert deliveries, so no row the dispatcher sees is locked. Were the
constant ever true, nothing is held (the safe direction: a delivery). The settings are the
delivery owner's stored `Settings.notifications` leaves (`scope: self`, never the actor's): a
value that does not have its contract shape is ignored, and a zone the tz database lacks keeps no
quiet hours (SR-E40-12: an unknown zone delivers). `decide` is pure; `StoredPrefs` is the bounded
read seam over the settings store.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, time
from functools import lru_cache
from typing import Any, Final, Literal, Protocol
from uuid import UUID
from zoneinfo import ZoneInfo, available_timezones

from candleviewer.alerts._generated.notification_overrides import USER_ALERTS_OVERRIDE
from candleviewer.alerts.delivery_view import delivery_kind

HeldReason = Literal["muted_symbol", "quiet_hours"]
#: The settings leaves the dispatcher reads (22 `Settings.notifications`).
MUTED_SYMBOLS: Final = "notifications.muted_symbols"
QUIET_HOURS: Final = "notifications.quiet_hours"
DESKTOP_ENABLED: Final = "notifications.desktop_enabled"
_HHMM: Final = re.compile(r"([01][0-9]|2[0-3]):([0-5][0-9])")
#: A settings read past this delivers unsuppressed rather than hold the poll loop.
READ_TIMEOUT_S: Final = 2.0


@lru_cache(maxsize=1)
def _zones() -> frozenset[str]:
    return frozenset(available_timezones())


def zone(name: str) -> ZoneInfo | None:
    """The IANA zone `name`, or None when the server's tz database lacks it. Only a listed key
    reaches `ZoneInfo`, so no path the pattern lets through is ever opened."""
    return ZoneInfo(name) if name in _zones() else None


@dataclass(frozen=True, slots=True)
class QuietHours:
    """An enabled window `[start, end)` in `tz`'s wall clock; `start > end` spans midnight and
    `start == end` holds nothing."""

    start: time
    end: time
    tz: ZoneInfo

    def holds(self, now: datetime) -> bool:
        """`now` (tz-aware) falls inside the window, read on `tz`'s wall clock (DST-correct)."""
        local = now.astimezone(self.tz).time().replace(tzinfo=None)
        if self.start < self.end:
            return self.start <= local < self.end
        if self.start > self.end:
            return local >= self.start or local < self.end
        return False


@dataclass(frozen=True, slots=True)
class DeliveryPrefs:
    """What the dispatcher honours of one owner's settings; the defaults hold nothing."""

    muted_symbols: frozenset[str] = frozenset()
    quiet_hours: QuietHours | None = None
    desktop_enabled: bool = True


NO_PREFS: Final = DeliveryPrefs()


@dataclass(frozen=True, slots=True)
class Decision:
    """`deliver` (the adapter runs as before), `silence` (an `in_app` row sent with `silenced`
    set to `reason`) or `suppress` (the row settled `suppressed` with `reason`)."""

    action: Literal["deliver", "silence", "suppress"]
    reason: str | None = None


DELIVER: Final = Decision("deliver")


def _clock(v: object) -> time | None:
    m = _HHMM.fullmatch(v) if isinstance(v, str) else None
    return None if m is None else time(int(m[1]), int(m[2]))


def _quiet_hours(v: object) -> QuietHours | None:
    if not isinstance(v, Mapping) or v.get("enabled") is not True:
        return None
    start, end, tz = _clock(v.get("start")), _clock(v.get("end")), v.get("tz")
    tzinfo = zone(tz) if isinstance(tz, str) else None
    if start is None or end is None or tzinfo is None:
        return None
    return QuietHours(start, end, tzinfo)


def _muted(v: object) -> frozenset[str]:
    items = v if isinstance(v, list) else []
    return frozenset(
        s for i in items if isinstance(i, Mapping) and isinstance(s := i.get("symbol"), str)
    )


def prefs_of(rows: Iterable[tuple[str, object]]) -> DeliveryPrefs:
    """The owner's stored leaves (key, JSON value) as `DeliveryPrefs`; other leaves are ignored."""
    leaves = dict(rows)
    return DeliveryPrefs(
        muted_symbols=_muted(leaves.get(MUTED_SYMBOLS)),
        quiet_hours=_quiet_hours(leaves.get(QUIET_HOURS)),
        desktop_enabled=leaves.get(DESKTOP_ENABLED) is not False,
    )


def held(*, kind: str, symbol: object, prefs: DeliveryPrefs, now: datetime) -> HeldReason | None:
    """Why a mute or quiet hours holds a row of `kind` for `symbol`; only a firing is held."""
    if USER_ALERTS_OVERRIDE or kind != "firing":
        return None
    if isinstance(symbol, str) and symbol in prefs.muted_symbols:
        return "muted_symbol"
    if prefs.quiet_hours is not None and prefs.quiet_hours.holds(now):
        return "quiet_hours"
    return None


def decide(
    *, channel: str, context: Mapping[str, Any] | None, prefs: DeliveryPrefs, now: datetime
) -> Decision:
    """CC-9's per-channel decision for one delivery row. Pure: the record is never dropped."""
    if channel not in ("in_app", "desktop") or USER_ALERTS_OVERRIDE:
        return DELIVER
    ctx = context if isinstance(context, Mapping) else {}
    why = held(kind=delivery_kind(ctx), symbol=ctx.get("symbol"), prefs=prefs, now=now)
    if channel == "in_app":
        return DELIVER if why is None else Decision("silence", why)
    if why is not None:
        return Decision("suppress", why)
    return DELIVER if prefs.desktop_enabled else Decision("suppress", "desktop_off")


class SettingRow(Protocol):
    @property
    def key(self) -> str: ...
    @property
    def value(self) -> object: ...


class SettingsReader(Protocol):
    """The per-user settings store (`UserSettings.read`), one user's rows only."""

    async def read(self, user_id: UUID) -> Sequence[SettingRow]: ...


class PrefsSource(Protocol):
    async def prefs(self, user_id: str) -> DeliveryPrefs: ...


class StoredPrefs:
    """`PrefsSource` over the settings store: the named owner's rows, bounded by `timeout_s`.
    A read that fails or times out raises, and the dispatcher delivers unsuppressed."""

    def __init__(self, settings: SettingsReader, *, timeout_s: float = READ_TIMEOUT_S) -> None:
        self._settings, self._timeout = settings, timeout_s

    async def prefs(self, user_id: str) -> DeliveryPrefs:
        async with asyncio.timeout(self._timeout):
            rows = await self._settings.read(UUID(user_id))
        return prefs_of((r.key, r.value) for r in rows if r.key.startswith("notifications."))


__all__ = [
    "DELIVER",
    "NO_PREFS",
    "Decision",
    "DeliveryPrefs",
    "PrefsSource",
    "QuietHours",
    "SettingsReader",
    "StoredPrefs",
    "decide",
    "held",
    "prefs_of",
    "zone",
]
