"""Download-link test fakes (E42-T05 #966 BK-10): artefacts that count their closes, a reader, and
`BackupDownloads` over BK-4's catalogue fakes."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from typing import Any

from candleviewer.admin.backups.catalogue import BackupCatalogue
from candleviewer.admin.backups.downloads import BackupDownloads, LinkRecord
from candleviewer.admin.backups.gate import BackupJobGate
from candleviewer.admin.backups.links import DownloadLinks
from candleviewer.audit.access import AuditPrincipal
from candleviewer.storage.repositories.backups import BackupRow
from tests.unit.admin._admin_fakes import AuditSpy
from tests.unit.admin._backup_fakes import NOW, Store


class Artefact:  # what a link issue opens: never hashed or read, closed once
    size = 7

    def __init__(self) -> None:
        self.closed = 0

    async def digest(self) -> str:
        raise AssertionError("a link issue never hashes the artefact")

    def stream(self) -> AsyncIterator[bytes]:
        raise AssertionError("a link issue never reads the artefact")

    def close(self) -> None:
        self.closed += 1


class Reader:  # `ArtefactReader`: each location asked for, each artefact opened
    def __init__(self, *, error: Exception | None = None, hang: bool = False) -> None:
        self.error, self.hang = error, hang
        self.locations: list[str] = []
        self.opened: list[Artefact] = []

    async def resolve(self, location: str) -> Artefact:
        self.locations.append(location)
        if self.hang:
            await asyncio.Event().wait()
        if self.error is not None:
            raise self.error
        self.opened.append(Artefact())
        return self.opened[-1]


@dataclass
class World:
    downloads: BackupDownloads
    store: Store
    reader: Reader
    links: DownloadLinks
    gate: BackupJobGate
    audit: AuditSpy
    locked: list[bool] = field(default_factory=list)  # the admission lock, at each record

    def write_ahead(self, who: AuditPrincipal) -> Any:
        """What the route passes: each record through `audit_issue`."""

        async def record(entry: LinkRecord) -> None:
            self.locked.append(self.gate._lock.locked())
            await self.downloads.audit_issue(who, entry)

        return record


def world(
    rows: Sequence[BackupRow] = (),
    *,
    store: Store | None = None,
    reader: Reader | None = None,
    gate: BackupJobGate | None = None,
    links: DownloadLinks | None = None,
    read_budget_s: float = 2.0,
    **budgets: float,
) -> World:
    store = Store(rows) if store is None else store
    reader = Reader() if reader is None else reader
    links = DownloadLinks(now=lambda: NOW) if links is None else links
    gate, audit = BackupJobGate() if gate is None else gate, AuditSpy()
    catalogue = BackupCatalogue(store, now=lambda: NOW, budget_s=read_budget_s)
    service = BackupDownloads(catalogue, reader, links, gate=gate, audit=audit, **budgets)
    return World(service, store, reader, links, gate, audit)
