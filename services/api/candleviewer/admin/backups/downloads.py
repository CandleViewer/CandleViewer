"""`issueBackupDownload` once its grant is spent (E42-T05 #966 BK-10), under the backups admission
lock (`admit_link`), so it never interleaves with a delete. The row is read again: a usable backup
is `ok`, `verified` or `restored`, not deleted, `encrypted`, and its `location` resolves to one
regular file in the backup root (`resolve` within `RESOLVE_BUDGET_S`, the artefact closed at once:
only the fetch reads it); else `LinkNotUsable` (409 `backup_not_usable`). A failing or slow store,
or a lock wait past `ADMIT_WAIT_S`, is `OpsUnavailable` (503); `LIVE_LINKS_MAX` live links,
`LinksFull` (503). Each refusal is a `backup.downloaded` failure record (`reason` its rule) before
it is raised; a link is minted, then recorded with the spent `challenge_id` and its `link_id`,
never the token or its hash, or forgotten unsent. Records go through the handler's `write_ahead`
(it calls `audit_issue`) within `LINK_RECORD_BUDGET_S`; unwritten, `OpsAuditUnavailable` (503).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Final
from uuid import UUID

import structlog

from candleviewer.admin.backups.artefact_port import ArtefactReader
from candleviewer.admin.backups.catalogue import BackupCatalogue
from candleviewer.admin.backups.gate import BackupJobGate
from candleviewer.admin.backups.limits import LINK_RECORD_BUDGET_S, RESOLVE_BUDGET_S
from candleviewer.admin.backups.links import DownloadLink, DownloadLinks, LinksFull
from candleviewer.admin.errors import AdminError, OpsAuditUnavailable, OpsUnavailable
from candleviewer.admin.http import AuditEmitter
from candleviewer.audit.access import AuditPrincipal
from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.observability.context import current_request_id
from candleviewer.storage.backup_artefacts import ArtefactMissing, ArtefactUnreadable

USABLE_STATUSES: Final = frozenset({"ok", "verified", "restored"})


class LinkNotUsable(AdminError):
    """`409 conflict`, rule `backup_not_usable`: nothing was minted."""


@dataclass(frozen=True, slots=True)
class LinkRecord:
    """One `backup.downloaded` record of an issue: the link it issued, or the refusal's rule."""

    backup_id: UUID
    challenge_id: UUID
    link: DownloadLink | None = None
    reason: str | None = None


WriteAhead = Callable[[LinkRecord], Awaitable[None]]


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


def _reason(refused: AdminError) -> str:
    if isinstance(refused, LinkNotUsable):
        return "backup_not_usable"
    return "links_full" if isinstance(refused, LinksFull) else "store_unavailable"


class BackupDownloads:
    def __init__(
        self,
        catalogue: BackupCatalogue,
        reader: ArtefactReader,
        links: DownloadLinks,
        *,
        gate: BackupJobGate,
        audit: AuditEmitter,
        resolve_budget_s: float = RESOLVE_BUDGET_S,
        record_budget_s: float = LINK_RECORD_BUDGET_S,
    ) -> None:
        self._catalogue, self._reader, self._links = catalogue, reader, links
        self._gate, self._audit = gate, audit
        self._resolve_budget_s, self._record_budget_s = resolve_budget_s, record_budget_s

    async def issue(
        self, backup_id: UUID, who: AuditPrincipal, challenge_id: UUID, write_ahead: WriteAhead
    ) -> tuple[str, DownloadLink]:
        """The token and the link to `backup_id` for `who`'s session, once its grant is spent."""
        session_id = who.session_id
        if session_id is None:  # the step-up gate answers 401 first: nothing was spent
            raise TypeError("a download link is bound to the session that issued it")
        held = False
        try:
            async with self._gate.admit_link(backup_id):
                held = True
                return await self._issue(backup_id, who, session_id, challenge_id, write_ahead)
        except OpsUnavailable as refused:
            if not held:  # the lock's wait outlasted its bound: recorded without it
                failed = LinkRecord(backup_id, challenge_id, None, _reason(refused))
                await self._record(write_ahead, failed)
            raise

    async def audit_issue(self, who: AuditPrincipal, record: LinkRecord) -> None:
        """`backup.downloaded` at `stage: issued`, severity `error`: the spent grant's
        `challenge_id`, then the link (`link_id`, expiry) or the refusal (`reason`)."""
        state: dict[str, Any] = {"stage": "issued", "challenge_id": str(record.challenge_id)}
        if record.link is not None:
            expires = record.link.expires_at.isoformat()
            state |= {"link_id": str(record.link.link_id), "expires_at": expires}
        outcome = AuditOutcome.FAILURE if record.link is None else AuditOutcome.SUCCESS
        await self._audit.emit(
            "backup.downloaded", actor_label=who.username, actor_user_id=who.user_id,
            actor_ip=who.ip, session_id=who.session_id, object_kind="backup",
            object_id=str(record.backup_id), outcome=outcome, severity=Severity.ERROR,
            reason=record.reason, after_state=state, request_id=who.request_id,
        )  # fmt: skip

    async def _issue(
        self, bid: UUID, who: AuditPrincipal, sid: UUID, grant: UUID, write_ahead: WriteAhead
    ) -> tuple[str, DownloadLink]:
        try:
            await self._usable(bid)
            token, link = self._links.issue(user_id=who.user_id, session_id=sid, backup_id=bid)
        except (LinkNotUsable, OpsUnavailable, LinksFull) as refused:
            await self._record(write_ahead, LinkRecord(bid, grant, None, _reason(refused)))
            raise
        try:
            await self._record(write_ahead, LinkRecord(bid, grant, link))
        except BaseException:
            self._links.discard(link.link_id)  # never sent: no link without its record
            raise
        return token, link

    async def _usable(self, backup_id: UUID) -> None:
        row = await self._catalogue.get(backup_id)  # within the catalogue's own read budget
        if row is None or row.status not in USABLE_STATUSES or row.deleted_at or not row.encrypted:
            raise LinkNotUsable("backups: the backup is not usable")
        try:
            async with asyncio.timeout(self._resolve_budget_s):
                artefact = await self._reader.resolve(row.target_path)
        except ArtefactMissing:
            raise LinkNotUsable("backups: the backup is not usable") from None
        except (ArtefactUnreadable, TimeoutError) as exc:  # a cancelled walk closes its file
            _log().warning("admin_backups.link_resolve_failed", error=type(exc).__name__,
                           request_id=current_request_id())  # fmt: skip
            raise OpsUnavailable("backups: store unavailable") from None
        artefact.close()

    async def _record(self, write_ahead: WriteAhead, record: LinkRecord) -> None:
        try:
            async with asyncio.timeout(self._record_budget_s):
                await write_ahead(record)
        except Exception as exc:  # a record that is not durable refuses the answer (C-2.9)
            _log().error("admin_backups.link_audit_failed", error=type(exc).__name__,
                         request_id=current_request_id())  # fmt: skip
            raise OpsAuditUnavailable("backups: the record could not be written") from None
