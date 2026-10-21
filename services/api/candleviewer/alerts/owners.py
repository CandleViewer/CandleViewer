"""`OwnerGate`: may an alert's owner still have it evaluated and delivered? (#3349, UL-F8)

A disabled user's alerts must neither fire nor deliver (E42-T04, #965). The status is in `users`,
which this module may not import (CONSTITUTION §3), so an injected `OwnerDirectory` is asked, ids
only. The gate answers with the owners to skip and why: `inactive` (not listed: disabled, locked,
invited, deleted or unknown) or `unreadable` (the read raised or outlasted `timeout_s`). It FAILS
CLOSED, the caller counts each skip, a cancellation propagates, and no flag turns it off (C-4.14).

Answers are cached per owner for `ttl_s` in a bounded LRU (`max_owners`, C-2.18), a failed read too,
so a struggling store is asked once a second, not once a tick. The evaluator accepts that
staleness; the dispatcher asks `fresh`: once a disable has committed, nothing leaves on a channel.
"""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from collections.abc import Callable, Collection
from typing import Any, Final, Literal

import structlog

from candleviewer.alerts.ports import OwnerDirectory

OWNER_TTL_S: Final = 1.0
OWNER_CACHE_MAX: Final = 4096
OWNER_READ_TIMEOUT_S: Final = 2.0

#: The `reason` label of `cv_alert_owner_skipped_total`.
SkipReason = Literal["inactive", "unreadable"]


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


class OwnerGate:
    def __init__(
        self,
        directory: OwnerDirectory,
        *,
        ttl_s: float = OWNER_TTL_S,
        max_owners: int = OWNER_CACHE_MAX,
        timeout_s: float = OWNER_READ_TIMEOUT_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._directory, self._ttl, self._max = directory, ttl_s, max_owners
        self._timeout, self._clock = timeout_s, clock
        #: owner id -> (clock of its read, why to skip it; None: active), least recently used first
        self._seen: OrderedDict[str, tuple[float, SkipReason | None]] = OrderedDict()

    async def skipped(
        self, owner_ids: Collection[str], *, fresh: bool = False
    ) -> dict[str, SkipReason]:
        """The owners among *owner_ids* to skip, each with why; an active owner is absent. *fresh*
        reads every one from the directory, and the answer refreshes the cache."""
        now = self._clock()  # before the read: a verdict is never younger than it looks
        verdicts: dict[str, SkipReason | None] = {}
        for owner in owner_ids:
            seen = None if fresh else self._seen.get(owner)
            if seen is not None and now - seen[0] < self._ttl:
                self._seen.move_to_end(owner)
                verdicts[owner] = seen[1]
        if asked := [o for o in dict.fromkeys(owner_ids) if o not in verdicts]:
            read = await self._read(asked)
            for owner, why in read.items():
                self._seen[owner] = (now, why)
                self._seen.move_to_end(owner)
            while len(self._seen) > self._max:
                self._seen.popitem(last=False)
            verdicts |= read
        return {o: why for o, why in verdicts.items() if why is not None}

    async def _read(self, owners: list[str]) -> dict[str, SkipReason | None]:
        try:
            async with asyncio.timeout(self._timeout):
                active = await self._directory.active_users(owners)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # fail closed, whatever it was; the type only, never its text
            _log().warning(
                "alert_owner_status_unreadable", error=type(exc).__name__, owners=len(owners)
            )
            return {o: "unreadable" for o in owners}
        return {o: None if o in active else "inactive" for o in owners}
