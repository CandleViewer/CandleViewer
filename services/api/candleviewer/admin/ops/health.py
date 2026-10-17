"""`AdminHealthService` (E42-T05): the `GET /admin/health` read model.

It reads the E04 registry's cached snapshot and adds the build facts; it never runs a probe and
does no I/O, so the page that diagnoses an outage cannot deepen it. A registry that is not wired
is `OpsNotWired`; one with no snapshot yet is `OpsUnavailable`: an empty report would read as a
healthy system. `alerts_active` is not served (no alert source exists), and `clock_offset_ms` is
`None` until exchange time sync lands (E08), as the contract says: never a fabricated `0`.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from candleviewer.admin.errors import OpsNotWired, OpsUnavailable
from candleviewer.observability.health_probes import HealthSnapshot


class HealthSource(Protocol):
    """The E04 `HealthRegistry` satisfies this as it is."""

    def snapshot(self) -> HealthSnapshot | None: ...


@dataclass(frozen=True, slots=True)
class HealthReading:
    snapshot: HealthSnapshot
    version: str
    git_sha: str
    environment: str
    uptime_seconds: int


class AdminHealthService:
    def __init__(
        self,
        source: HealthSource | None,
        *,
        version: str,
        git_sha: str,
        environment: str,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._source, self._build = source, (version, git_sha, environment)
        self._monotonic, self._started = monotonic, monotonic()

    def report(self) -> HealthReading:
        if self._source is None:
            raise OpsNotWired("health: no registry wired")
        snapshot = self._source.snapshot()
        if snapshot is None:
            raise OpsUnavailable("health: no probe snapshot yet")
        uptime = int(self._monotonic() - self._started)
        return HealthReading(snapshot, *self._build, uptime)
