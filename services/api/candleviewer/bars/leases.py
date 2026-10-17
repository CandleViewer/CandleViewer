"""Spec leases: reference counting, the 30 s release grace and the hard spec caps (E12-T03).

A *lease* is one consumer's claim on one `(symbol, spec_hash)` series. The series lives while it
has at least one lease; when the last one is released it enters a grace period (US-MKT-005,
30 s) and is torn down only if nobody re-acquires it before the deadline.

Caps (SR-E12-04 / BR-30; E12 STRIDE model): a *new* distinct series is refused with
`SpecCapExceeded` when it would exceed `per_symbol` series on its symbol, `global_` series in the
process, or `per_user` distinct series held by the requesting user. Series in grace still count
(they still cost CPU and memory). Joining an existing series never counts against the symbol or
global cap; it does count against the user's own cap. `user=None` marks system consumers (the
recorder, rules) and is exempt from the per-user cap only. Existing series are never touched by
a refused registration.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

from candleviewer.bars.errors import BarsError, SpecCapExceeded
from candleviewer.bars.metrics import bars_spec_cap_rejected_total

GRACE_US: Final = 30_000_000
CAP_PER_USER: Final = 8
CAP_PER_SYMBOL: Final = 32
CAP_GLOBAL: Final = 512

Key = tuple[str, str]  # (symbol, spec_hash)


@dataclass(frozen=True, slots=True)
class SpecCaps:
    per_user: int = CAP_PER_USER
    per_symbol: int = CAP_PER_SYMBOL
    global_: int = CAP_GLOBAL


@dataclass(slots=True)
class _Series:
    holders: dict[str, str | None] = field(default_factory=dict)  # consumer -> user
    expires_at: int | None = None  # set while in grace
    quarantined: bool = False  # its builder was removed; it ends with the series (#2195)


DEFAULT_CAPS: Final = SpecCaps()


class SpecLeases:
    """Pure bookkeeping (no I/O, no tasks); `BarBuilderSet` acts on what it returns."""

    def __init__(self, caps: SpecCaps = DEFAULT_CAPS, grace_us: int = GRACE_US) -> None:
        self._caps, self._grace = caps, grace_us
        self._series: dict[Key, _Series] = {}

    def __contains__(self, key: Key) -> bool:
        return key in self._series

    def keys(self) -> tuple[Key, ...]:
        return tuple(self._series)

    def on_symbol(self, symbol: str) -> tuple[str, ...]:
        return tuple(h for s, h in self._series if s == symbol)

    def _user_keys(self, user: str) -> set[Key]:
        return {k for k, s in self._series.items() if user in s.holders.values()}

    def _refuse(
        self, cap: str, limit: int, active: int, own: tuple[str, ...] = ()
    ) -> SpecCapExceeded:
        bars_spec_cap_rejected_total.labels(reason=cap).inc()
        return SpecCapExceeded(cap, limit, active, own)

    def check(self, key: Key, user: str | None) -> None:
        """Raise the `SpecCapExceeded` (counted) `acquire` would raise now; change nothing."""
        series = self._series.get(key)
        if user is not None:
            mine = self._user_keys(user)
            if key not in mine and len(mine) >= self._caps.per_user:
                held = tuple(sorted(h for _, h in mine))
                raise self._refuse("per-user", self._caps.per_user, len(held), held)
        if series is None:
            on_sym = self.on_symbol(key[0])
            if len(on_sym) >= self._caps.per_symbol:
                raise self._refuse("per-symbol", self._caps.per_symbol, len(on_sym))
            if len(self._series) >= self._caps.global_:
                raise self._refuse("process-wide", self._caps.global_, len(self._series))

    def acquire(self, key: Key, consumer: str, user: str | None) -> bool:
        """`check`, then add a lease; `True` when `key` is a new series the caller must build."""
        self.check(key, user)
        series = self._series.get(key)
        if series is None:
            series = self._series[key] = _Series()
            new = True
        else:
            new = False
        series.holders[consumer] = user
        series.expires_at = None
        return new

    def release(self, key: Key, consumer: str, now_us: int) -> None:
        """Drop a lease; the last release starts the grace period. Unknown leases are an error."""
        series = self._series.get(key)
        if series is None or consumer not in series.holders:
            raise BarsError(f"The consumer {consumer} holds no lease on that bar series.")
        del series.holders[consumer]
        if not series.holders:
            series.expires_at = now_us + self._grace

    def release_consumer(self, consumer: str, now_us: int) -> None:
        """Liveness sweep hook: drop every lease of a consumer that went away without releasing."""
        for key, series in self._series.items():
            if consumer in series.holders:
                self.release(key, consumer, now_us)

    def expired(self, now_us: int) -> tuple[Key, ...]:
        """Remove and return every series whose grace period has elapsed."""
        out = tuple(
            k
            for k, s in self._series.items()
            if s.expires_at is not None and now_us >= s.expires_at
        )
        for k in out:
            del self._series[k]
        return out

    def drop(self, key: Key) -> None:
        """Forget a series immediately (its build failed)."""
        self._series.pop(key, None)

    def quarantine(self, key: Key) -> None:
        """Mark a leased series as having lost its builder, until the series ends."""
        series = self._series.get(key)
        if series is not None:
            series.quarantined = True

    def quarantined(self, key: Key) -> bool:
        """O(1): True while a leased series has no builder (`quarantine`)."""
        series = self._series.get(key)
        return series is not None and series.quarantined
