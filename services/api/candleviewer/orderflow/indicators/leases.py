"""Server indicator instance leases: reference counts, the release grace and the SR-E13-03 caps
(E13-T02, #426; E13 threat model SR-E13-03, IR-31, IR-36).

A lease is one consumer's claim on one instance, keyed `(symbol, spec_hash)`: a WS subscription
holds one per instance it names, a system consumer (S08 rules, E35, E40) one per metric it reads.
An instance lives while it has a lease; after the last release it is kept `grace_us` (US-MKT-005,
30 s), then `expired` removes it, unless someone acquired it again first.

Caps (`limits.py`), checked by `check` before anything is held: a NEW distinct instance is refused
past `per_symbol` instances on its symbol or `process` instances in all, counting those in their
grace. A user is refused past `per_user` distinct instances held, and past `churn` instances held
and released by that user that are still in their grace (IR-31: subscribe and unsubscribe churn;
holding one again, by anyone, ends its charge), with a message of its own that says the refusal
ends with a grace. Joining a running instance counts toward the user's caps only. `user=None` (a
system consumer) is exempt from the user caps only. A refusal is counted
(`indicator_cap_rejected_total{cap}`; a churn refusal as `user`) and changes nothing. A consumer
that replaces its instances (a WS `ctl`) is checked as holding the new set alone, toward every
cap: the engine `drop`s each replaced instance it held alone (`sole`), so a retune leaves nothing
in a grace, and none of those counts toward the symbol or the process cap. Pure bookkeeping: no
I/O and no task; the engine acts on what it returns. Every instance of the process is one entry
here, so the caps also bound the engine's memo (IR-36).
"""

from __future__ import annotations

from collections import Counter as Tally
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Final

from candleviewer.orderflow.errors import IndicatorError, InstanceCapError, InstanceChurnError
from candleviewer.orderflow.indicators.limits import (
    INSTANCE_CAP_PER_SYMBOL,
    INSTANCE_CAP_PER_USER,
    INSTANCE_CAP_PROCESS,
    INSTANCE_CHURN_CAP_PER_USER,
    INSTANCE_GRACE_US,
)
from candleviewer.orderflow.indicators.metrics import CAP_REJECTED, Cap, set_subscriptions

Key = tuple[str, str]  # (symbol, spec_hash)


@dataclass(frozen=True, slots=True)
class InstanceCaps:
    per_user: int = INSTANCE_CAP_PER_USER
    per_symbol: int = INSTANCE_CAP_PER_SYMBOL
    process: int = INSTANCE_CAP_PROCESS
    churn: int = INSTANCE_CHURN_CAP_PER_USER


DEFAULT_CAPS: Final = InstanceCaps()


@dataclass(slots=True)
class _Instance:
    holders: dict[str, str | None] = field(default_factory=dict)  # consumer -> user
    expires_at: int | None = None  # set while in grace
    released_by: str | None = None  # in grace: the user whose release started it (IR-31)


class InstanceLeases:
    """The bookkeeping described in the module docstring."""

    def __init__(
        self, caps: InstanceCaps = DEFAULT_CAPS, grace_us: int = INSTANCE_GRACE_US
    ) -> None:
        self._caps, self._grace = caps, grace_us
        self._held: dict[Key, _Instance] = {}

    def held_by(self, key: Key, consumer: str) -> bool:
        entry = self._held.get(key)
        return entry is not None and consumer in entry.holders

    def sole(self, key: Key, consumer: str) -> bool:
        """True when `consumer` holds the one lease on `key`."""
        entry = self._held.get(key)
        return entry is not None and list(entry.holders) == [consumer]

    def _mine(self, user: str, consumer: str | None) -> tuple[set[Key], set[Key]]:
        """The keys `user` holds through a consumer other than `consumer`, and those in a grace
        `user`'s release started."""
        held: set[Key] = set()
        released: set[Key] = set()
        for key, entry in self._held.items():
            if any(u == user and c != consumer for c, u in entry.holders.items()):
                held.add(key)
            elif not entry.holders and entry.released_by == user:
                released.add(key)
        return held, released

    def check(
        self, symbol: str, keys: Iterable[str], user: str | None, consumer: str | None = None
    ) -> None:
        """Raise the `InstanceCapError` (counted) that holding every key of `keys` on `symbol`
        would meet; change nothing. A `consumer` replaces its instances (a WS `ctl`) and is
        checked as holding the new set alone: its own leases are left out of the user's count,
        and the instances on `symbol` it alone holds that the new set leaves out (`_dropped`) out
        of the symbol's and the process's.
        """
        wanted = {(symbol, k) for k in keys}
        if user is not None:
            held, released = self._mine(user, consumer)
            if len(held | wanted) > self._caps.per_user:
                raise self._refuse("user", self._caps.per_user)
            if len(held | released | wanted) > self._caps.churn:
                CAP_REJECTED["user"].inc()
                raise InstanceChurnError(self._caps.churn, self._grace // 1_000_000)
        new = wanted - self._held.keys()
        if not new:
            return
        dropped = self._dropped(symbol, wanted, consumer)
        on_symbol = sum(1 for s, _ in self._held if s == symbol) - dropped
        if on_symbol + len(new) > self._caps.per_symbol:
            raise self._refuse("symbol", self._caps.per_symbol)
        if len(self._held) - dropped + len(new) > self._caps.process:
            raise self._refuse("process", self._caps.process)

    def _dropped(self, symbol: str, wanted: set[Key], consumer: str | None) -> int:
        """The instances on `symbol` that a replacing `consumer` alone holds and `wanted` leaves
        out: the engine forgets them once the new set is held (`IndicatorEngine._let_go`)."""
        if consumer is None:
            return 0
        return sum(
            1
            for key in self._held
            if key[0] == symbol and key not in wanted and self.sole(key, consumer)
        )

    def acquire(self, key: Key, consumer: str, user: str | None) -> bool:
        """Add a lease (after `check`); True when `key` is a new instance the caller must build."""
        entry = self._held.get(key)
        new = entry is None
        if entry is None:
            entry = self._held[key] = _Instance()
        entry.holders[consumer] = user
        entry.expires_at = entry.released_by = None
        self._observe()
        return new

    def release(self, key: Key, consumer: str, now_us: int) -> None:
        """Drop a lease; the last release starts the grace, charged to its user. Releasing a lease
        never held raises."""
        entry = self._held.get(key)
        if entry is None or consumer not in entry.holders:
            raise IndicatorError("That consumer holds no lease on that indicator instance.")
        user = entry.holders.pop(consumer)
        if not entry.holders:
            entry.expires_at, entry.released_by = now_us + self._grace, user
        self._observe()

    def drop(self, key: Key) -> None:
        """Forget an instance that never ran (an admission undone): no grace, no charge."""
        if self._held.pop(key, None) is not None:
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
