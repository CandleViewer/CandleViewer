"""Single-use backup download links (E42-T05 #966 BK-10; `issueBackupDownload`, `downloadBackup`).

The links of the one API process (ADR-0004): a restart forgets them (Q10), and a lost link is one
whose `issued` record no `served` record follows. A token is 256 bits from a CSPRNG
(`secrets.token_urlsafe(32)`, 43 base64url characters); only its SHA-256 is kept, beside the link's
id, user, issuing session, backup, issue time and expiry (`LINK_TTL`, on the server clock). The
token leaves only in the `200` body. `consume()` is synchronous, so a lookup and its spend are one
step of the event loop: another backup's token, or another user's when the caller names one (a
bearer), is `LinkUnknown` and unspent; the caller's own spent or expired link `LinkGone`; a live
one is spent once (`LinkSpent`). The hash is compared with `hmac.compare_digest` against every link.
BK-11: a match is a lookup, not a spend (10a code F1). `lookup()` finds as `consume()` does but a
live link is `LinkLive`, unspent; `spend()` spends it, both synchronous, so the fetch checks its
user's hour between them with no await. A spent link's one `link_reused` record (SR-BK10A-02 (b))
is claimed by `claim_reuse()` while it is written and taken by `settle_reuse()` once written.

Bounds (C-2.18) and the retention horizon (SR-3456-01): `LIVE_LINKS_MAX` live links, past which
`issue()` refuses (`LinksFull`). An ended link is kept `ENDED_KEPT` (1 hour) after its spend or,
unspent, its expiry, and an issue keeps at most `ENDED_LINKS_MAX` of them (the oldest issued goes
first). Past that its token is unknown: a fetch is `404`, never `410`, and writes no record.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Final, Literal
from uuid import UUID, uuid4

from candleviewer.admin.audited import audit_exempt
from candleviewer.admin.errors import AdminError
from candleviewer.admin.overview.fanout import utc_now

LINK_TTL: Final = timedelta(minutes=5)  # a link works once, for 5 minutes (contract)
LIVE_LINKS_MAX: Final = 1024  # every user's together
ENDED_KEPT: Final = timedelta(hours=1)
ENDED_LINKS_MAX: Final = 1024
#: The one `link_reused` record of a spent link: none yet, one being written, or written.
Reuse = Literal["unrecorded", "writing", "recorded"]


class LinksFull(AdminError):
    """`LIVE_LINKS_MAX` links are live: nothing was minted (503, retryable)."""


@dataclass(frozen=True, slots=True)
class DownloadLink:
    """A link, without its token or the token's hash."""

    link_id: UUID
    user_id: UUID
    session_id: UUID
    backup_id: UUID
    issued_at: datetime
    expires_at: datetime
    spent_at: datetime | None = None
    reuse: Reuse = "unrecorded"

    @audit_exempt("read")
    def ended(self, now: datetime) -> bool:
        return self.spent_at is not None or now >= self.expires_at


@dataclass(frozen=True, slots=True)
class LinkUnknown:  # never issued, forgotten, or another backup's or user's: nothing spent
    pass


@dataclass(frozen=True, slots=True)
class LinkGone:  # the caller's own link, spent or expired
    link: DownloadLink


@dataclass(frozen=True, slots=True)
class LinkSpent:  # the caller's live link, spent by this call and no other
    link: DownloadLink


@dataclass(frozen=True, slots=True)
class LinkLive:  # the caller's live link, found and not spent
    link: DownloadLink


Consumed = LinkUnknown | LinkGone | LinkSpent
Found = LinkUnknown | LinkGone | LinkLive


def _digest(token: str) -> bytes:
    return hashlib.sha256(token.encode("utf-8", "surrogatepass")).digest()


class DownloadLinks:
    def __init__(
        self,
        *,
        now: Callable[[], datetime] = utc_now,
        live_max: int = LIVE_LINKS_MAX,
        ended_max: int = ENDED_LINKS_MAX,
    ) -> None:
        self._now, self._live_max, self._ended_max = now, live_max, ended_max
        #: By link id, in issue order: the token's SHA-256 and the link.
        self._held: dict[UUID, tuple[bytes, DownloadLink]] = {}

    @audit_exempt("caller_audits")
    def issue(
        self, *, user_id: UUID, session_id: UUID, backup_id: UUID
    ) -> tuple[str, DownloadLink]:
        """A live link and its token, which only the caller holds; else `LinksFull`."""
        now = self._now()
        ended = self._sweep(now)
        if len(self._held) - len(ended) >= self._live_max:
            raise LinksFull("backups: too many download links are live")
        for link_id in ended[: max(0, len(ended) - self._ended_max)]:
            del self._held[link_id]  # the oldest issued first
        token = secrets.token_urlsafe(32)
        link = DownloadLink(uuid4(), user_id, session_id, backup_id, now, now + LINK_TTL)
        self._held[link.link_id] = (_digest(token), link)
        return token, link

    @audit_exempt("caller_audits")
    def discard(self, link_id: UUID) -> None:
        """Forget a link whose `issued` record could not be written: its token was never sent."""
        self._held.pop(link_id, None)

    @audit_exempt("caller_audits")
    def consume(self, token: str, *, backup_id: UUID, user_id: UUID | None) -> Consumed:
        """`lookup`, then `spend` the live link it finds."""
        found = self.lookup(token, backup_id=backup_id, user_id=user_id)
        return self.spend(found.link.link_id) if isinstance(found, LinkLive) else found

    @audit_exempt("read")
    def lookup(self, token: str, *, backup_id: UUID, user_id: UUID | None) -> Found:
        """The link `token` names for `backup_id`, spending nothing; `user_id` is the bearer's
        user, or None without a bearer (the token alone then names its user)."""
        now = self._now()
        self._sweep(now)
        digest, found = _digest(token), None
        for held, link in self._held.values():  # every link: the time names none of them
            if hmac.compare_digest(held, digest):
                found = link
        if found is None or found.backup_id != backup_id:
            return LinkUnknown()
        if user_id is not None and found.user_id != user_id:
            return LinkUnknown()
        return LinkGone(found) if found.ended(now) else LinkLive(found)

    @audit_exempt("caller_audits")
    def spend(self, link_id: UUID) -> Consumed:
        """Spend the live link `link_id` once (`LinkSpent`); else what is held of it now."""
        now, held = self._now(), self._held.get(link_id)
        if held is None:
            return LinkUnknown()
        digest, link = held
        if link.ended(now):
            return LinkGone(link)
        spent = replace(link, spent_at=now)
        self._held[link_id] = (digest, spent)
        return LinkSpent(spent)

    @audit_exempt("caller_audits")
    def claim_reuse(self, link_id: UUID) -> bool:
        """Whether this presentation of the spent link writes its `link_reused` record: once,
        until `settle_reuse`; a link never spent, or forgotten, has none."""
        held = self._held.get(link_id)
        if held is None or held[1].spent_at is None or held[1].reuse != "unrecorded":
            return False
        self._held[link_id] = (held[0], replace(held[1], reuse="writing"))
        return True

    @audit_exempt("caller_audits")
    def settle_reuse(self, link_id: UUID, *, written: bool) -> None:
        """The claimed record written (its place taken), or not (left to the next)."""
        held = self._held.get(link_id)
        if held is not None:
            reuse: Reuse = "recorded" if written else "unrecorded"
            self._held[link_id] = (held[0], replace(held[1], reuse=reuse))

    def _sweep(self, now: datetime) -> list[UUID]:
        """Forget each link ended `ENDED_KEPT` ago; the ended ones kept, oldest issued first."""
        ended: list[UUID] = []
        for link_id, (_, link) in list(self._held.items()):
            if not link.ended(now):
                continue
            if now >= (link.spent_at or link.expires_at) + ENDED_KEPT:
                del self._held[link_id]
            else:
                ended.append(link_id)
        return ended
