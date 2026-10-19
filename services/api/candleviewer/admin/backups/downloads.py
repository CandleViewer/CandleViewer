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

`downloadBackup` (BK-11), in the contract's order, under no lock. A token matching no link, or a
malformed one, is `LinkMissed` (404). A spent or expired link is `LinkEnded` (410), counted
nowhere; a spent one's first presentation again is recorded once (`link_reused`). A live link
meets its user's hour (`FetchLimited`, 429: nothing spent or recorded) and is spent, with no await
since the lookup; the spend counts in that hour. Then, each refusal recorded first: an event that
ended the grant that minted it (`grant_ended`, `LinkEnded`), its user without `backups:read`
(`LinkForbidden`, 403), the backup as for an issue. Last the `served` record; the open artefact
goes to the route, which streams it. Its records go through `audit_serve` the same way; an
unwritten one leaves a spent link spent.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Final, Protocol, TypeVar
from uuid import UUID

import structlog

from candleviewer.admin.backups.artefact_port import ArtefactReader, OpenArtefact
from candleviewer.admin.backups.catalogue import BackupCatalogue
from candleviewer.admin.backups.gate import BackupJobGate
from candleviewer.admin.backups.limits import (
    FETCH_READ_BUDGET_S,
    LINK_RECORD_BUDGET_S,
    RESOLVE_BUDGET_S,
)
from candleviewer.admin.backups.links import (
    DownloadLink,
    DownloadLinks,
    LinkGone,
    LinkLive,
    LinksFull,
    LinkSpent,
)
from candleviewer.admin.errors import AdminError, OpsAuditUnavailable, OpsNotWired, OpsUnavailable
from candleviewer.admin.http import AuditEmitter
from candleviewer.admin.overview.fanout import utc_now
from candleviewer.audit.access import AuditPrincipal
from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.models import SessionRecord, UserStatus
from candleviewer.observability.context import current_request_id
from candleviewer.storage.backup_artefacts import ArtefactMissing, ArtefactUnreadable
from candleviewer.storage.repositories.backups import BackupRow

USABLE_STATUSES: Final = frozenset({"ok", "verified", "restored"})


class LinkNotUsable(AdminError):
    """`409 conflict`, rule `backup_not_usable`: nothing was minted."""


class LinkMissed(AdminError):
    """`404 not_found`: no link matches, or the token or `backupId` is malformed; nothing spent."""


class LinkEnded(AdminError):
    """`410 gone`, one body whatever the cause; after the spend `reason` names it in the record."""

    def __init__(self, reason: str = "gone") -> None:
        super().__init__("backups: the link ended")
        self.reason = reason


class LinkForbidden(AdminError):
    """`403 forbidden`: the link's user no longer holds `backups:read`; the link is spent."""


class FetchLimited(AdminError):
    """`429 rate_limited` for `retry_after_s`: nothing was spent."""

    def __init__(self, retry_after_s: int) -> None:
        super().__init__("backups: rate limited")
        self.retry_after_s = retry_after_s


class FamilyRows(Protocol):  # `auth.session_repository.SessionRepository`'s two reads
    async def walk_rotation_family(self, session_id: str) -> tuple[str, ...]: ...

    async def find_by_id(self, session_id: str) -> SessionRecord | None: ...


class UserPermissions(Protocol):  # the identity read: a user who is not active holds none
    async def session_info(self, user_id: str) -> dict[str, Any]: ...


class HourlyLimit(Protocol):  # `api.audit_limiter.AuditVerifyLimiter`, out of M21's reach
    def retry_after(self, user: str) -> int | None: ...

    def record_start(self, user: str) -> None: ...


@dataclass(frozen=True, slots=True)
class FetchPorts:
    """A fetch's reads past the catalogue and the links, its user's hour and the server clock."""

    sessions: FamilyRows
    identity: UserPermissions
    hourly: HourlyLimit
    now: Callable[[], datetime] = utc_now


@dataclass(frozen=True, slots=True)
class Fetch:
    """The path's `backup_id` and `token` (None: malformed), the bearer's verified principal if
    one was sent, the address MeshOnly admitted and the request id. The token, a credential, is
    in no `repr` (C-12.6), so neither is it in a `ServeRecord`'s."""

    backup_id: UUID | None
    token: str | None = field(repr=False)
    bearer: AuditPrincipal | None
    source: str | None
    request_id: UUID | None


@dataclass(frozen=True, slots=True)
class ServeRecord:
    """One `backup.downloaded` record of a fetch with a matching token (`stage: served`)."""

    ask: Fetch
    link: DownloadLink
    outcome: AuditOutcome
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class Fetched:
    """A served fetch: its backup, and the open artefact that the route streams and closes."""

    backup_id: UUID
    kind: str
    artefact: OpenArtefact


@dataclass(frozen=True, slots=True)
class LinkRecord:
    """One `backup.downloaded` record of an issue: the link it issued, or the refusal's rule."""

    backup_id: UUID
    challenge_id: UUID
    link: DownloadLink | None = None
    reason: str | None = None


WriteAhead = Callable[[LinkRecord], Awaitable[None]]
ServeWriteAhead = Callable[[ServeRecord], Awaitable[None]]
_Record = TypeVar("_Record", LinkRecord, ServeRecord)


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


def _reason(refused: AdminError) -> str:
    if isinstance(refused, LinkNotUsable):
        return "backup_not_usable"
    if isinstance(refused, LinkEnded):
        return refused.reason
    if isinstance(refused, LinkForbidden):
        return "forbidden"
    return "links_full" if isinstance(refused, LinksFull) else "store_unavailable"


def grant_ended(link: DownloadLink, family: Sequence[SessionRecord], now: datetime) -> str | None:
    """`user_disabled` or `session_ended` once an event ended the grant that minted `link`, else
    None (SR-BK10A-02 (a)), from the rows of its family: the issuing session and the successors
    its rotations made (`issued_at` from its own on), as a rotation does not end the link. The
    user disabled or gone; none of those sessions live (logged out, revoked other than by a
    rotation, expired); a live one past its lifetime or idle-locked; or one with `readonly_until`
    set: the step-up that minted the grant cleared it, a successor starts without, and a
    downgrade keeps it set after its window until a write lifts it. Two events can leave the rows
    clean (delta: the issue's touch to its mint, seconds): a read-only turn begun within delta
    and lifted by a write after its `READONLY_WINDOW`, and an idle lock, which needs
    `MIN_IDLE_TIMEOUT_S` of idleness after the touch, begun and unlocked in the link's last delta
    (both at least `LINK_TTL`)."""
    issuing = next((row for row in family if row.id == link.session_id), None)
    if issuing is None:
        return "session_ended"
    if issuing.user_status in (UserStatus.DISABLED, None):
        return "user_disabled"
    chain = [row for row in family if row.issued_at >= issuing.issued_at]
    live = [row for row in chain if not row.is_revoked]
    if not live or any(row.readonly_until is not None for row in chain):
        return "session_ended"
    if any(row.is_absolute_expired(now=now) or row.is_idle_locked(now=now) for row in live):
        return "session_ended"
    return None


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
        fetch: FetchPorts | None = None,
        fetch_budget_s: float = FETCH_READ_BUDGET_S,
    ) -> None:
        self._catalogue, self._reader, self._links = catalogue, reader, links
        self._gate, self._audit = gate, audit
        self._resolve_budget_s, self._record_budget_s = resolve_budget_s, record_budget_s
        self._fetch, self._fetch_budget_s = fetch, fetch_budget_s

    def with_fetch(self, fetch: FetchPorts) -> BackupDownloads:
        """This service with the fetch's ports: the links, catalogue and artefacts shared."""
        return BackupDownloads(
            self._catalogue, self._reader, self._links, gate=self._gate, audit=self._audit,
            resolve_budget_s=self._resolve_budget_s, record_budget_s=self._record_budget_s,
            fetch=fetch, fetch_budget_s=self._fetch_budget_s,
        )  # fmt: skip

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

    async def fetch(self, ask: Fetch, write_ahead: ServeWriteAhead) -> Fetched:
        """`downloadBackup` for `ask`, in the contract's order (the module docstring)."""
        ports = self._fetch
        if ports is None:
            raise OpsNotWired("backups: the fetch is not wired")
        if ask.backup_id is None or ask.token is None:
            raise LinkMissed("backups: no such link")
        bearer = None if ask.bearer is None else ask.bearer.user_id
        found = self._links.lookup(ask.token, backup_id=ask.backup_id, user_id=bearer)
        if isinstance(found, LinkGone):
            raise await self._gone(ask, found.link, write_ahead)
        if not isinstance(found, LinkLive):
            raise LinkMissed("backups: no such link")
        user = str(found.link.user_id)
        if (wait := ports.hourly.retry_after(user)) is not None:
            raise FetchLimited(wait)  # nothing spent, nothing recorded
        spent = self._links.spend(found.link.link_id)  # no await since the lookup
        if not isinstance(spent, LinkSpent):
            raise LinkEnded()  # it expired between the two readings of the clock, unspent
        ports.hourly.record_start(user)  # every spend counts, a refused fetch's too
        return await self._serve(ports, ask, spent.link, write_ahead)

    async def audit_serve(self, record: ServeRecord) -> None:
        """`backup.downloaded` at `stage: served`, severity `error`: the `link_id`, and `bearer`
        `matched` (the issuing user's bearer came: its session and name) or `absent`."""
        ask, link, who = record.ask, record.link, record.ask.bearer
        bearer = "absent" if who is None else "matched"
        state: dict[str, Any] = {"stage": "served", "link_id": str(link.link_id), "bearer": bearer}
        await self._audit.emit(
            "backup.downloaded", actor_label=str(link.user_id) if who is None else who.username,
            actor_user_id=link.user_id, actor_ip=ask.source,
            session_id=link.session_id if who is None else who.session_id, object_kind="backup",
            object_id=str(link.backup_id), outcome=record.outcome, severity=Severity.ERROR,
            reason=record.reason, after_state=state, request_id=ask.request_id,
        )  # fmt: skip

    async def _gone(
        self, ask: Fetch, link: DownloadLink, write_ahead: ServeWriteAhead
    ) -> LinkEnded:
        """A spent link's first presentation again writes `link_reused`; only a written record
        takes its place (SR-BK10A-02 (b)). An expired link never spent writes nothing."""
        if self._links.claim_reuse(link.link_id):
            written = False
            try:
                reused = ServeRecord(ask, link, AuditOutcome.FAILURE, "link_reused")
                await self._record(write_ahead, reused)
                written = True
            finally:
                self._links.settle_reuse(link.link_id, written=written)
        return LinkEnded()

    async def _serve(
        self, ports: FetchPorts, ask: Fetch, link: DownloadLink, write_ahead: ServeWriteAhead
    ) -> Fetched:
        try:
            await self._still_granted(ports, link)
            row, artefact = await self._open(link.backup_id)
        except (LinkEnded, LinkForbidden, LinkNotUsable, OpsUnavailable) as refused:
            failed = ServeRecord(ask, link, AuditOutcome.FAILURE, _reason(refused))
            await self._record(write_ahead, failed)
            raise
        try:
            await self._record(write_ahead, ServeRecord(ask, link, AuditOutcome.SUCCESS))
        except BaseException:
            artefact.close()  # never handed to the route
            raise
        return Fetched(row.id, row.kind, artefact)

    async def _still_granted(self, ports: FetchPorts, link: DownloadLink) -> None:
        try:
            async with asyncio.timeout(self._fetch_budget_s):
                ids = await ports.sessions.walk_rotation_family(str(link.session_id))
                family = [await ports.sessions.find_by_id(sid) for sid in ids]
                info = await ports.identity.session_info(str(link.user_id))
        except Exception as exc:  # an outage or a stall: fail closed, the class alone logged
            _log().warning("admin_backups.fetch_read_failed", error=type(exc).__name__,
                           request_id=current_request_id())  # fmt: skip
            raise OpsUnavailable("backups: store unavailable") from None
        ended = grant_ended(link, [row for row in family if row is not None], ports.now())
        if ended is not None:
            raise LinkEnded(ended)
        held = frozenset(str(code) for code in info.get("permissions", ()))
        if not AuditPrincipal(link.user_id, str(link.user_id), held).has(Permission.BACKUPS_READ):
            raise LinkForbidden("backups: the link's user may not read backups")

    async def _issue(
        self, bid: UUID, who: AuditPrincipal, sid: UUID, grant: UUID, write_ahead: WriteAhead
    ) -> tuple[str, DownloadLink]:
        try:
            (await self._open(bid))[1].close()  # only the fetch reads it
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

    async def _open(self, backup_id: UUID) -> tuple[BackupRow, OpenArtefact]:
        """The usable row and its artefact, open: the caller closes it."""
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
        return row, artefact

    async def _record(
        self, write_ahead: Callable[[_Record], Awaitable[None]], record: _Record
    ) -> None:
        try:
            async with asyncio.timeout(self._record_budget_s):
                await write_ahead(record)
        except Exception as exc:  # a record that is not durable refuses the answer (C-2.9)
            _log().error("admin_backups.link_audit_failed", error=type(exc).__name__,
                         request_id=current_request_id())  # fmt: skip
            raise OpsAuditUnavailable("backups: the record could not be written") from None
