"""`cv_incidents_open` (E42-T05, #966 BK-15): the unresolved incidents of the read model.

The value is the count the overview shows as `incidents_open`: the `open` and `acknowledged` rows
of the materialised `incidents` table (`CountsPort.open_incidents`, `21-database-schema.md`
3.10.2a). A scrape runs in a thread of its own and reads memory only, so a refresher the lifespan
starts reads the count every `REFRESH_INTERVAL_S`, each read bounded by `READ_TIMEOUT_S`, and keeps
the last good one with the time it was read.

The series has no sample while there is nothing true to say: before the first read has succeeded,
after a read has failed or run out of time (the last value is dropped, never kept), and once the
last good read is more than `MAX_AGE_INTERVALS` intervals old (a refresher that stopped). A count
of 0 is a sample: it means a read found no unresolved incident. A plain `Gauge` with no label
always exports a sample (0 until it is set, and never unset), so the series is served by a scrape
collector, which can serve none. Name, kind, labels and HELP are the catalogue's; the series has
no label.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any, Final, Protocol

import structlog

from candleviewer.observability.context import spawn
from candleviewer.observability.metrics import CollectorRegistry, ScrapeCollector, ScrapedFamily
from candleviewer.observability.metrics_catalogue import CATALOGUE

NAME: Final = "cv_incidents_open"
EXPORTED_NAMES: Final = frozenset({NAME})
REFRESH_INTERVAL_S: Final = 30.0
READ_TIMEOUT_S: Final = 5.0
#: A reading older than this many intervals is not served: its refresher is stuck or dead.
MAX_AGE_INTERVALS: Final = 3
_SPEC = next(s for s in CATALOGUE if s.name == NAME)


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


class OpenIncidentSource(Protocol):
    async def open_incidents(self) -> int:
        """Unresolved (`open` or `acknowledged`) incidents: the overview's `CountsPort` count."""


class OpenIncidentsGauge:
    """The cached count behind `cv_incidents_open`; `source` is `None` on the fake backend (no
    `incidents` table to read), where the series never has a sample."""

    def __init__(
        self,
        source: OpenIncidentSource | None,
        *,
        clock: Callable[[], float] = time.monotonic,
        interval_s: float = REFRESH_INTERVAL_S,
        timeout_s: float = READ_TIMEOUT_S,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._source, self._clock, self._sleep = source, clock, sleep
        self._interval_s, self._timeout_s = interval_s, timeout_s
        self._max_age_s = MAX_AGE_INTERVALS * interval_s
        #: The last good read, (count, when): one tuple, replaced whole, so a scrape in another
        #: thread never pairs a count with the time of another read.
        self._reading: tuple[int, float] | None = None
        self._task: asyncio.Task[None] | None = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def families(self) -> list[ScrapedFamily]:
        """What a scrape serves: memory and the clock only, no I/O (the scrape's own thread)."""
        reading = self._reading  # one read: the refresher may replace it meanwhile
        samples: tuple[tuple[tuple[str, ...], float], ...] = ()
        if reading is not None and self._clock() - reading[1] <= self._max_age_s:
            samples = (((), float(reading[0])),)
        return [ScrapedFamily(NAME, _SPEC.kind, _SPEC.help, _SPEC.labels, samples)]

    async def refresh(self) -> None:
        """One bounded read. A good one replaces the reading; any failure, a timeout included,
        drops it, so the series has no sample until a read succeeds again. The log line has the
        error's class only, never the driver's text. Raises only on cancellation."""
        if self._source is None:
            return
        try:
            async with asyncio.timeout(self._timeout_s):
                count = await self._source.open_incidents()
        except Exception as exc:  # TimeoutError included; CancelledError propagates
            self._reading = None
            _log().warning("incidents.open_gauge_read_failed", error=type(exc).__name__)
            return
        self._reading = (count, self._clock())

    async def _loop(self) -> None:
        while True:
            await self.refresh()
            await self._sleep(self._interval_s)

    def start(self) -> None:
        """Read now, then every interval, on a tracked task (idempotent); no store, no loop."""
        if self._source is not None and self._task is None:
            self._task = spawn(self._loop(), name="incidents-open-gauge")

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            await asyncio.wait({task})  # unlike `await task`, an outer cancellation still raises


def export_incident_metrics(
    registry: CollectorRegistry, *, env: str, gauge: OpenIncidentsGauge
) -> ScrapeCollector:
    """Serve the series on `registry` (the scraped one) with `env`: the composition root's call."""
    return ScrapeCollector(registry, env=env, read=gauge.families)
