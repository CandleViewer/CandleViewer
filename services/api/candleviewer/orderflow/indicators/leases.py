"""Server indicator instance leases: reference counts, the release grace and the SR-E13-03 caps
(E13-T02, #426; E13 threat model SR-E13-03, IR-31, IR-36).

A lease is one consumer's claim on one instance, keyed `(symbol, spec_hash)`: a WS subscription
holds one per instance it names, a system consumer (S08 rules, E35, E40) one per metric it reads.
An instance lives while it has a lease; after the last release it is kept `grace_us` (US-MKT-005,
30 s), then `expired` removes it, unless someone acquired it again first.

Caps (`limits.py`), checked by `check` before anything is held: a NEW distinct instance is refused
past `per_symbol` instances on its symbol or `process` instances in all, counting those in their
grace; a user is refused past `per_user` distinct instances held. Joining a running instance counts
toward the user's cap only. `user=None` (a system consumer) is exempt from the user cap only. A
refusal is counted (`indicator_cap_rejected_total{cap}`) and changes nothing. Pure bookkeeping:
no I/O and no task; the engine acts on what it returns. Every instance of the process is one entry
here, so the caps also bound the engine's memo (IR-36).
"""

from __future__ import annotations

from collections import Counter as Tally
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Final

from candleviewer.orderflow.errors import IndicatorError, InstanceCapError
from candleviewer.orderflow.indicators.limits import (
    INSTANCE_CAP_PER_SYMBOL,
    INSTANCE_CAP_PER_USER,
    INSTANCE_CAP_PROCESS,
    INSTANCE_GRACE_US,
)
from candleviewer.orderflow.indicators.metrics import CAP_REJECTED, Cap, set_subscriptions

Key = tuple[str, str]  # (symbol, spec_hash)


@dataclass(frozen=True, slots=True)
class InstanceCaps:
    per_user: int = INSTANCE_CAP_PER_USER
    per_symbol: int = INSTANCE_CAP_PER_SYMBOL
    process: int = INSTANCE_CAP_PROCESS


DEFAULT_CAPS: Final = InstanceCaps()


@dataclass(slots=True)
class _Instance:
    holders: dict[str, str | None] = field(default_factory=dict)  # consumer -> user
    expires_at: int | None = None  # set while in grace


class InstanceLeases:
    """The bookkeeping described in the module docstring."""

    def __init__(
        self, caps: InstanceCaps = DEFAULT_CAPS, grace_us: int = INSTANCE_GRACE_US
    ) -> None:
        self._caps, self._grace = caps, grace_us
        self._held: dict[Key, _Instance] = {}

    def __contains__(self, key: Key) -> bool:
        return key in self._held

    def __len__(self) -> int:
        return len(self._held)

    def holders(self, key: Key) -> int:
        entry = self._held.get(key)
        return 0 if entry is None else len(entry.holders)

    def held_by(self, key: Key, consumer: str) -> bool:
        entry = self._held.get(key)
        return entry is not None and consumer in entry.holders

    def _mine(self, user: str, consumer: str | None) -> set[Key]:
        """The keys `user` holds through a consumer other than `consumer`."""
        return {
            key
            for key, entry in self._held.items()
            if any(u == user and c != consumer for c, u in entry.holders.items())
        }

    def check(
        self, symbol: str, keys: Iterable[str], user: str | None, consumer: str | None = None
    ) -> None:
        """Raise the `InstanceCapError` (counted) that holding every key of `keys` on `symbol`
        would meet; change nothing. `consumer`'s own leases are left out of the user's count: a
        consumer that replaces its instances (a WS `ctl`) is checked as holding the new set alone.
        """
        wanted = {(symbol, k) for k in keys}
        if user is not None and len(self._mine(user, consumer) | wanted) > self._caps.per_user:
            raise self._refuse("user", self._caps.per_user)
        new = wanted - self._held.keys()
        if not new:
            return
        on_symbol = sum(1 for s, _ in self._held if s == symbol)
        if on_symbol + len(new) > self._caps.per_symbol:
            raise self._refuse("symbol", self._caps.per_symbol)
        if len(self._held) + len(new) > self._caps.process:
            raise self._refuse("process", self._caps.process)

    def acquire(self, key: Key, consumer: str, user: str | None) -> bool:
        """Add a lease (after `check`); True when `key` is a new instance the caller must build."""
        entry = self._held.get(key)
        new = entry is None
        if entry is None:
            entry = self._held[key] = _Instance()
        entry.holders[consumer] = user
        entry.expires_at = None
        self._observe()
        return new

    def release(self, key: Key, consumer: str, now_us: int) -> None:
        """Drop a lease; the last release starts the grace. Releasing a lease never held raises."""
        entry = self._held.get(key)
        if entry is None or consumer not in entry.holders:
            raise IndicatorError("That consumer holds no lease on that indicator instance.")
        del entry.holders[consumer]
        if not entry.holders:
            entry.expires_at = now_us + self._grace
        self._observe()

    def expired(self, now_us: int) -> tuple[Key, ...]:
        """Remove and return every instance whose grace has elapsed."""
        out = tuple(
            k for k, e in self._held.items() if e.expires_at is not None and now_us >= e.expires_at
        )
        for k in out:
            del self._held[k]
        return out

    def _refuse(self, cap: Cap, limit: int) -> InstanceCapError:
        CAP_REJECTED[cap].inc()
        return InstanceCapError(cap, limit)

    def _observe(self) -> None:
        """`indicator_subscriptions{bucket}`: users by the instances they hold (IR-21, IR-31)."""
        held: Tally[str] = Tally()
        for entry in self._held.values():
            for user in set(entry.holders.values()):
                if user is not None:
                    held[user] += 1
        set_subscriptions(held.values())
