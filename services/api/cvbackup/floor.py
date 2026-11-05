"""The sidecar's floor (ADR-0041 section 1; e42-admin.md §6a AD-SC02, AD-SC07): three rules no
request can lift, each judged from the sidecar's own record (`ledger.py`) and configuration, never
from a request or the API's catalogue.

1. `remove` never takes the newest finished artefact of a kind (`newest_artefact`); "newest" is
   the record's order of `finished` entries.
2. Runs are capped per rolling window (`runs_capped`), counted from the record's `started`
   entries, so a restart does not reset the count.
3. A removal is a delayed purge: renamed into the quarantine at once, deleted only once
   `purge_after` (the removal plus the configured grace) has passed, by `sweep`.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

from cvbackup.ledger import Artefact, Ledger
from cvbackup.paths import PathFault, Root


class FloorRefusal(Exception):
    """`code`: `newest_artefact` or `runs_capped`."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class Floor:
    def __init__(
        self, root: Root, ledger: Ledger, *, run_cap: int, run_window: timedelta,
        grace: timedelta,
    ) -> None:  # fmt: skip
        self._root, self._ledger = root, ledger
        self._run_cap, self._run_window, self._grace = run_cap, run_window, grace
        self.failures = 0  # purges the volume refused, over this process's life

    def check_remove(self, artefact: Artefact) -> None:
        if self._ledger.newest(artefact.kind) == artefact.backup_id:
            raise FloorRefusal("newest_artefact")

    def check_run(self, now: datetime) -> None:
        if self._ledger.started_since(now - self._run_window) >= self._run_cap:
            raise FloorRefusal("runs_capped")

    async def admit(self, backup_id: str, kind: str, now: datetime) -> None:
        """The cap's check and the run's `started` entry as one step under the record's lock,
        so two concurrent admissions never both pass the cap."""
        await self._ledger.append(
            "started", backup_id, kind=kind, guard=lambda: self.check_run(now)
        )

    def purge_after(self, now: datetime) -> datetime:
        return now + self._grace

    async def sweep(self, now: datetime) -> int:
        """Purge every quarantined artefact whose grace is over; how many it purged. A file the
        volume cannot delete stays for the next sweep."""
        purged = 0
        for artefact in self._ledger.due(now):
            name = artefact.name or ""  # every quarantined entry names its file (`ledger`)
            try:
                await asyncio.to_thread(self._root.purge, name)
            except PathFault:  # one entry never stops the sweep; it is tried again next time
                self.failures += 1
                continue
            await self._ledger.append("purged", artefact.backup_id)
            purged += 1
        return purged
