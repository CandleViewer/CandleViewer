"""A fetch's misses, per source address (E42-T05 #966 BK-11, `downloadBackup`).

A request whose token or `backupId` is malformed, or whose token matches no link, is a miss and
counts against the address MeshOnly admitted, refused ones included. Past `MISSES_PER_MINUTE` in
a rolling minute a further miss is refused (`429 rate_limited`, `Retry-After` until the minute
has room), and the first refusal per address and minute is recorded: `claim_record` holds its
place while the record is written, and `settle_record` takes it only once the write succeeded
(SR-3456-02), so an unwritten record leaves it to the next refusal. A token cannot be guessed, so
this bounds log and audit volume and flags a scanner; it never limits a matching token.

Bounded (C-2.18): `SOURCES_TRACKED` addresses, the least recently missing forgotten first, each
with its last `MISSES_PER_MINUTE` stamps on the injected monotonic clock.
"""

from __future__ import annotations

import math
import time
from collections import OrderedDict, deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

from candleviewer.admin.audited import audit_exempt
from candleviewer.admin.backups.limits import MISSES_PER_MINUTE

SOURCES_TRACKED: Final = 1024
_MINUTE_S: Final = 60.0


@dataclass(slots=True)
class _Source:
    stamps: deque[float]
    recorded_at: float | None = None
    writing: bool = False


class SourceMisses:
    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        per_minute: int = MISSES_PER_MINUTE,
        tracked: int = SOURCES_TRACKED,
    ) -> None:
        self._clock, self._per_minute, self._tracked = clock, per_minute, tracked
        self._sources: OrderedDict[str, _Source] = OrderedDict()

    @audit_exempt("caller_audits")
    def miss(self, source: str) -> int | None:
        """Count one miss from `source`: None within its minute's budget (`404`), else the whole
        seconds until the minute has room (`429`)."""
        now = self._clock()
        state = self._sources.pop(source, None) or _Source(deque(maxlen=self._per_minute))
        self._sources[source] = state  # the most recently missing last
        if len(self._sources) > self._tracked:
            self._sources.popitem(last=False)
        stamps = state.stamps
        full = len(stamps) == self._per_minute and now - stamps[0] < _MINUTE_S
        stamps.append(now)
        return math.ceil(stamps[0] + _MINUTE_S - now) if full else None

    @audit_exempt("caller_audits")
    def claim_record(self, source: str) -> bool:
        """Whether this refusal writes `source`'s one record of the minute: once, until settled."""
        state = self._sources.get(source)
        if state is None or state.writing:
            return False
        if state.recorded_at is not None and self._clock() - state.recorded_at < _MINUTE_S:
            return False
        state.writing = True
        return True

    @audit_exempt("caller_audits")
    def settle_record(self, source: str, *, written: bool) -> None:
        state = self._sources.get(source)
        if state is not None:
            state.writing = False
            if written:
                state.recorded_at = self._clock()
