"""Unit (E42-T05 #966 BK-11): `BackupDownloads.fetch` (`downloadBackup`) in the contract's order.
A token matching no link, or a malformed one, is 404; a spent or expired link 410, a spent one's
first presentation again recorded once (`link_reused`); the user's hour, then the spend; then the
grant's events, `backups:read` and the backup, each refusal recorded first; the `served` record
before the artefact is handed over. With the AC-ADM-26 steps (contract-C security F2)."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any, Final
from uuid import UUID

import pytest
from structlog.testing import capture_logs

from candleviewer.admin.backups import limits
from candleviewer.admin.backups.downloads import (
    BackupDownloads,
    Fetch,
    Fetched,
    FetchLimited,
    FetchPorts,
    LinkEnded,
    LinkForbidden,
    LinkMissed,
    LinkNotUsable,
    ServeRecord,
)
from candleviewer.admin.backups.links import (
    ENDED_KEPT,
    ENDED_LINKS_MAX,
    LINK_TTL,
    DownloadLink,
    DownloadLinks,
    LinkGone,
    LinkLive,
)
from candleviewer.admin.errors import OpsAuditUnavailable, OpsNotWired, OpsUnavailable
from candleviewer.api.audit_limiter import AuditVerifyLimiter
from candleviewer.audit.access import AuditPrincipal
from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.audit.redact import redact
from candleviewer.audit.writer import AuditUnavailable
from candleviewer.auth.models import SessionRecord, UserStatus
from candleviewer.auth.session_service import MIN_IDLE_TIMEOUT_S
from candleviewer.auth.step_up import READONLY_WINDOW
from candleviewer.storage.backup_artefacts import ArtefactMissing, ArtefactUnreadable
from tests.unit.admin._admin_fakes import principal
from tests.unit.admin._backup_fakes import NOW, row
from tests.unit.admin._link_fakes import World, world
from tests.unit.auth.session_fakes import FakeSessionRepository

WHO, SID = principal("owner"), UUID(int=101)  # user 1, its session 101, request 201
GRANT, BID, SOURCE = UUID(int=0xC0FFEE), UUID(int=1), "10.0.0.9"
PREDECESSOR, SUCCESSOR = UUID(int=100), UUID(int=102)  # around the issuing session
FAILURE, SUCCESS = AuditOutcome.FAILURE, AuditOutcome.SUCCESS
_BOUND: Final = 2.0  # seconds, a safety net only: no test waits on it when the service is right
SECOND: Final = timedelta(seconds=1)


class Clock:
    def __init__(self) -> None:
        self.now, self.steps = NOW, list[datetime]()  # `steps`: the next readings, in turn

    def __call__(self) -> datetime:
        return self.steps.pop(0) if self.steps else self.now


class Identity:  # an inactive user's permissions are empty, as `_PERMS_SQL` reads them
    def __init__(self, *permissions: str) -> None:
        self.permissions = list(permissions)

    async def session_info(self, user_id: str) -> dict[str, Any]:
        return {"permissions": self.permissions, "account_scope": []}


def session(sid: UUID, **over: Any) -> SessionRecord:
    fields: dict[str, Any] = {
        "id": sid, "user_id": WHO.user_id, "refresh_token_hash": f"h{sid}",
        "access_token_jti": None, "issued_at": NOW - timedelta(hours=1), "last_seen_at": NOW,
        "expires_at": NOW + timedelta(hours=11), "revoked_at": None, "revoked_reason": None,
        "ip": None, "user_agent": None, "device_label": None, "is_electron": False,
        "mfa_satisfied_at": NOW - timedelta(hours=1),
    }  # fmt: skip
    return SessionRecord(**(fields | over))


@dataclass
class Fx:
    w: World
    sessions: FakeSessionRepository
    hourly: AuditVerifyLimiter
    clock: Clock

    async def issue(self) -> tuple[str, DownloadLink]:
        return await self.w.downloads.issue(BID, WHO, GRANT, self.w.write_ahead(WHO))

    async def fetch(
        self, token: str | None, bearer: AuditPrincipal | None = None, ahead: Any = None
    ) -> Fetched:
        ask = Fetch(BID, token, bearer, SOURCE, WHO.request_id)
        async with asyncio.timeout(_BOUND):
            return await self.w.downloads.fetch(ask, ahead or self.w.serve_ahead())

    def served(self) -> list[dict[str, Any]]:
        return [r for r in self.w.audit.records if r["after_state"]["stage"] == "served"]

    def spent(self, token: str) -> bool:
        return isinstance(self.w.links.lookup(token, backup_id=BID, user_id=None), LinkGone)

    def rewrite(self, sid: UUID, **over: Any) -> None:
        self.sessions.sessions[str(sid)] = self.sessions.sessions[str(sid)].model_copy(update=over)


async def _fx(
    *,
    permissions: tuple[str, ...] = ("backups:read",),
    fetched: int = 0,
    rows: Any = None,
    **kw: Any,
) -> Fx:
    clock, sessions = Clock(), FakeSessionRepository()
    await sessions.create_session(session(SID))
    hourly = AuditVerifyLimiter(rate_per_hour=limits.FETCHES_PER_HOUR, clock=lambda: 0.0)
    for _ in range(fetched):
        hourly.record_start(str(WHO.user_id))
    ports = FetchPorts(sessions, Identity(*permissions), hourly, now=clock)
    w = world(rows or [row(1)], links=DownloadLinks(now=clock), fetch=ports, **kw)
    return Fx(w, sessions, hourly, clock)


def _served(link: DownloadLink, outcome: AuditOutcome, reason: str | None = None) -> dict[str, Any]:
    """A bearer-less fetch's whole record: the link, its user and session, the source."""
    return {
        "action": "backup.downloaded", "actor_label": str(WHO.user_id),
        "actor_user_id": WHO.user_id, "actor_ip": SOURCE, "session_id": SID,
        "object_kind": "backup", "object_id": str(BID), "outcome": outcome,
        "severity": Severity.ERROR, "reason": reason, "request_id": WHO.request_id,
        "after_state": {"stage": "served", "link_id": str(link.link_id), "bearer": "absent"},
    }  # fmt: skip


async def _down(record: ServeRecord) -> None:
    raise AuditUnavailable("WAL unwritable")


@pytest.mark.parametrize(
    "bearer", [None, replace(WHO, session_id=SUCCESSOR)], ids=["absent", "bearer"]
)
async def test_a_link_serves_once_then_is_410_with_one_link_reused_record(
    bearer: AuditPrincipal | None,
) -> None:
    fx = await _fx()
    token, link = await fx.issue()
    with capture_logs() as logs:
        fetched = await fx.fetch(token, bearer)
        for _ in range(2):
            with pytest.raises(LinkEnded):
                await fx.fetch(token, bearer)
    opened = fx.w.reader.opened[-1]
    assert (fetched.backup_id, fetched.kind, fetched.artefact) == (BID, "pg_dump", opened)
    assert opened.closed == 0 and len(fx.w.reader.opened) == 2  # the issue's, then this one
    expected = [_served(link, SUCCESS), _served(link, FAILURE, "link_reused")]
    for record in expected if bearer is not None else ():  # its name and session, `matched`
        record |= {"actor_label": "owner", "session_id": SUCCESSOR}
        record["after_state"]["bearer"] = "matched"
    assert fx.served() == expected and token not in f"{fx.w.audit.records}{logs}"


async def test_a_spent_link_is_410_and_link_reused_once_within_its_hour_then_404() -> None:
    """AC-ADM-26: a spent link is `410` and `link_reused` once within its hour (first presented
    again after its 5 minutes, it still writes it), then `404` with no record."""
    fx = await _fx()
    token, _ = await fx.issue()
    await fx.fetch(token)
    fx.clock.now = NOW + LINK_TTL
    for _ in range(2):
        with pytest.raises(LinkEnded):
            await fx.fetch(token)
    fx.clock.now = NOW + ENDED_KEPT
    with pytest.raises(LinkMissed):
        await fx.fetch(token)
    assert [r["reason"] for r in fx.served()] == [None, "link_reused"]


async def test_an_expired_link_never_spent_is_410_with_no_record() -> None:
    fx = await _fx()
    token, _ = await fx.issue()
    fx.clock.now = NOW + LINK_TTL
    with pytest.raises(LinkEnded):
        await fx.fetch(token)
    assert fx.served() == []


async def test_a_link_issued_before_a_restart_is_404_with_its_issued_record_alone() -> None:
    """AC-ADM-26: a restart forgets every link; the lost one is an `issued` with no `served`."""
    before = await _fx()
    token, _ = await before.issue()
    after = await _fx()  # a new process: its own link store
    with pytest.raises(LinkMissed):
        await after.fetch(token)
    assert [r["after_state"]["stage"] for r in before.w.audit.records] == ["issued"]
    assert after.served() == []


async def test_the_oldest_spent_link_once_more_than_1024_ended_is_404_and_no_link_reused() -> None:
    """AC-ADM-26 as contract-D words it: issue links until more than 1024 have ended, issue one
    more, then present the oldest spent one: `404` within the hour and no `link_reused` record. An
    issue keeps the newest 1024 ended links and forgets the oldest issued first."""
    fx = await _fx()
    token, _ = await fx.issue()
    await fx.fetch(token)
    issue = {"user_id": WHO.user_id, "session_id": SID, "backup_id": BID}
    for _ in range(ENDED_LINKS_MAX):  # 1024 more issued and spent: 1025 have ended
        fx.w.links.spend(fx.w.links.issue(**issue)[1].link_id)
    fx.w.links.issue(**issue)  # the one more issue forgets the oldest; the clock has not moved
    with pytest.raises(LinkMissed):
        await fx.fetch(token)
    assert [r["reason"] for r in fx.served()] == [None]


async def test_an_unwritten_link_reused_record_is_503_and_the_next_presentation_writes_it() -> None:
    fx = await _fx()
    token, _ = await fx.issue()
    await fx.fetch(token)
    with pytest.raises(OpsAuditUnavailable):
        await fx.fetch(token, ahead=_down)
    for _ in range(2):
        with pytest.raises(LinkEnded):
            await fx.fetch(token)
    assert [r["reason"] for r in fx.served()] == [None, "link_reused"]


async def test_a_link_expiring_between_its_lookup_and_its_spend_is_410_and_never_spent() -> None:
    fx = await _fx(fetched=limits.FETCHES_PER_HOUR - 1)
    token, _ = await fx.issue()
    fx.clock.now, fx.clock.steps = NOW + LINK_TTL, [NOW + LINK_TTL - timedelta(microseconds=1)]
    with pytest.raises(LinkEnded):
        await fx.fetch(token)
    gone = fx.w.links.lookup(token, backup_id=BID, user_id=None)
    assert isinstance(gone, LinkGone) and gone.link.spent_at is None and fx.served() == []
    assert fx.hourly.retry_after(str(WHO.user_id)) is None  # not counted


async def test_another_users_or_backups_or_a_malformed_token_is_404_and_spends_nothing() -> None:
    fx = await _fx()
    token, link = await fx.issue()
    asks = [Fetch(BID, None, None, SOURCE, None), Fetch(None, token, None, SOURCE, None),
            Fetch(UUID(int=2), token, None, SOURCE, None),
            Fetch(BID, token, principal("manager"), SOURCE, None)]  # fmt: skip
    for ask in asks:
        with pytest.raises(LinkMissed):
            await fx.w.downloads.fetch(ask, _down)
    assert fx.w.links.lookup(token, backup_id=BID, user_id=None) == LinkLive(link)
    assert (await fx.fetch(token)).backup_id == BID


async def test_the_eleventh_fetch_in_an_hour_is_429_and_only_a_spend_counts() -> None:
    """A miss and a `410` count nowhere; a refused fetch's spend counts; the eleventh is refused
    before its spend, with nothing recorded."""
    fx = await _fx(permissions=(), fetched=limits.FETCHES_PER_HOUR - 2)
    expired, _ = await fx.issue()
    fx.clock.now = NOW + LINK_TTL
    (refused, _), (tenth, _), (eleventh, link) = (
        await fx.issue(),
        await fx.issue(),
        await fx.issue(),
    )
    for token, refusal in (("A" * 43, LinkMissed), (expired, LinkEnded), (refused, LinkForbidden)):
        with pytest.raises(refusal):
            await fx.fetch(token)
    with pytest.raises(LinkForbidden):
        await fx.fetch(tenth)
    with pytest.raises(FetchLimited) as limited:
        await fx.fetch(eleventh)
    assert limited.value.retry_after_s == 3600 and limits.FETCHES_PER_HOUR == 10
    assert fx.w.links.lookup(eleventh, backup_id=BID, user_id=None) == LinkLive(link)
    assert [r["reason"] for r in fx.served()] == ["forbidden", "forbidden"]


async def _rotate(fx: Fx) -> None:
    """A refresh: the issuing session rotated into its successor, in its family."""
    await fx.sessions.revoke(str(SID), reason="rotated", now=NOW)
    await fx.sessions.create_session(session(SUCCESSOR, issued_at=NOW))
    await fx.sessions.link_rotation(prev_session_id=str(SID), next_session_id=str(SUCCESSOR))


async def _end(fx: Fx, event: str) -> None:
    sid, user = SID, str(WHO.user_id)
    if event in ("user_disabled", "user_gone", "disabled_and_revoked"):
        fx.sessions.user_statuses[user] = None if event == "user_gone" else UserStatus.DISABLED
        if event == "disabled_and_revoked":  # as the real disable does (its session sweep)
            await fx.sessions.revoke(str(sid), reason="user_disabled", now=NOW)
    elif event in ("logged_out", "row_gone"):
        await fx.sessions.revoke(str(sid), reason="logout", now=NOW)
        if event == "row_gone":
            del fx.sessions.sessions[str(sid)]
    elif event == "expired":
        fx.rewrite(sid, expires_at=NOW)
    elif event == "idle_locked":
        fx.rewrite(sid, last_seen_at=NOW - timedelta(seconds=900))
    elif event in ("read_only", "read_only_stale"):  # a window past is still a downgrade
        fx.rewrite(sid, readonly_until=NOW + (READONLY_WINDOW if event == "read_only" else -SECOND))
    else:  # a rotation does not end the link; what ends its successor does
        await _rotate(fx)
        if event == "rotated_then_revoked":
            await fx.sessions.revoke(str(SUCCESSOR), reason="rotation_reuse", now=NOW)
        else:
            fx.rewrite(SUCCESSOR, readonly_until=NOW + READONLY_WINDOW)


@pytest.mark.parametrize(
    ("event", "reason"),
    [("user_disabled", "user_disabled"), ("user_gone", "user_disabled"),
     ("disabled_and_revoked", "user_disabled"), ("logged_out", "session_ended"),
     ("row_gone", "session_ended"), ("expired", "session_ended"), ("idle_locked", "session_ended"),
     ("read_only", "session_ended"), ("read_only_stale", "session_ended"),
     ("rotated_then_revoked", "session_ended"), ("rotated_then_read_only", "session_ended")],
)  # fmt: skip
async def test_the_events_that_end_the_grant_end_the_link_after_its_spend(
    event: str, reason: str
) -> None:
    fx = await _fx()
    token, link = await fx.issue()
    await _end(fx, event)
    with pytest.raises(LinkEnded) as ended:
        await fx.fetch(token)
    assert ended.value.reason == reason and fx.served() == [_served(link, FAILURE, reason)]
    assert fx.spent(token) and fx.w.reader.locations == [row(1).target_path]  # the issue's own


@pytest.mark.parametrize("before", ["rotated", "a_predecessor_read_only"])
async def test_a_rotation_or_an_event_before_the_issue_does_not_end_the_link(before: str) -> None:
    fx = await _fx()
    if before == "a_predecessor_read_only":  # downgraded, then refreshed into the issuer
        older = session(PREDECESSOR, issued_at=NOW - timedelta(hours=2), revoked_at=NOW,
                        revoked_reason="rotated", readonly_until=NOW + READONLY_WINDOW)  # fmt: skip
        await fx.sessions.create_session(older)
        await fx.sessions.link_rotation(prev_session_id=str(PREDECESSOR), next_session_id=str(SID))
    token, _ = await fx.issue()
    if before == "rotated":
        await _rotate(fx)
    assert (await fx.fetch(token)).backup_id == BID
    assert [r["outcome"] for r in fx.served()] == [SUCCESS]


def test_no_lifted_grant_event_hides_inside_a_live_link() -> None:
    """SR-BK10A-02 (a) from the rows: a lock comes `MIN_IDLE_TIMEOUT_S` after the issue's touch
    and a read-only window lasts `READONLY_WINDOW`; a link lives `LINK_TTL`, no longer, so at its
    fetch the rows still show either, unless it began during the issue itself."""
    assert LINK_TTL <= timedelta(seconds=MIN_IDLE_TIMEOUT_S) and LINK_TTL <= READONLY_WINDOW


@pytest.mark.parametrize(
    ("change", "refusal", "reason"),
    [("permission", LinkForbidden, "forbidden"),
     ({"deleted_at": NOW}, LinkNotUsable, "backup_not_usable"),
     ({"status": "failed"}, LinkNotUsable, "backup_not_usable"),
     ({"encrypted": False}, LinkNotUsable, "backup_not_usable"),
     (ArtefactMissing(), LinkNotUsable, "backup_not_usable"),
     (ArtefactUnreadable(), OpsUnavailable, "store_unavailable"),
     ("down", OpsUnavailable, "store_unavailable"), ("hang", OpsUnavailable, "store_unavailable")],
    ids=["forbidden", "deleted", "failed", "plaintext", "missing", "unreadable", "down", "hang"],
)  # fmt: skip
async def test_a_refusal_after_the_spend_is_recorded_first_and_the_link_stays_spent(
    change: Any, refusal: type[Exception], reason: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    held = ("accounts:read",) if change == "permission" else ("backups:read",)
    fx = await _fx(permissions=held, fetch_budget_s=0.05)
    token, link = await fx.issue()
    if isinstance(change, dict):
        fx.w.store.rows = [row(1, **change)]
    elif isinstance(change, Exception):
        fx.w.reader.error = change
    elif change in ("down", "hang"):

        async def walk(session_id: str) -> tuple[str, ...]:
            if change == "hang":
                await asyncio.Event().wait()
            raise ConnectionError("the session store is down")

        monkeypatch.setattr(fx.sessions, "walk_rotation_family", walk)
    with capture_logs() as logs:
        with pytest.raises(refusal):
            await fx.fetch(token)
    assert fx.served() == [_served(link, FAILURE, reason)] and fx.spent(token)
    assert "is down" not in f"{logs}"


@pytest.mark.parametrize("held", [("backups:read",), ()], ids=["served", "forbidden"])
async def test_an_unwritten_record_after_the_spend_is_503_and_the_link_stays_spent(
    held: tuple[str, ...],
) -> None:
    fx = await _fx(permissions=held)
    token, _ = await fx.issue()
    with pytest.raises(OpsAuditUnavailable):
        await fx.fetch(token, ahead=_down)
    assert fx.spent(token) and [a.closed for a in fx.w.reader.opened[1:]] == ([1] if held else [])


async def test_two_concurrent_fetches_serve_once() -> None:
    fx = await _fx()
    token, _ = await fx.issue()

    async def slow(record: ServeRecord) -> None:
        await asyncio.sleep(0)  # the first suspends after its spend
        await fx.w.downloads.audit_serve(record)

    fetches = (fx.fetch(token, ahead=slow), fx.fetch(token, ahead=slow))
    results = await asyncio.gather(*fetches, return_exceptions=True)
    assert sorted(type(r).__name__ for r in results) == ["Fetched", "LinkEnded"]
    assert sorted(str(r["reason"]) for r in fx.served()) == ["None", "link_reused"]


def test_the_fetch_waits_the_limits_read_budget_by_default() -> None:
    budget = inspect.signature(BackupDownloads).parameters["fetch_budget_s"].default
    assert budget == limits.FETCH_READ_BUDGET_S == 2.0


async def test_an_unwired_fetch_is_refused_first() -> None:
    with pytest.raises(OpsNotWired):
        await world([row(1)]).downloads.fetch(Fetch(BID, "A" * 43, None, SOURCE, None), _down)


@pytest.mark.parametrize("bearer", [None, WHO], ids=["absent", "matched"])
async def test_the_served_records_bearer_flag_survives_the_audit_redactor(
    bearer: AuditPrincipal | None,
) -> None:
    """Review F1: `AuditWriter.build` stores `redact(after_state)`; the flag is kept."""
    fx = await _fx()
    token, _ = await fx.issue()
    await fx.fetch(token, bearer)
    (record,) = fx.served()
    assert redact(record["after_state"]) == record["after_state"]


def test_the_token_is_in_no_repr_of_its_fetch_or_its_record() -> None:
    token, link = DownloadLinks().issue(user_id=WHO.user_id, session_id=SID, backup_id=BID)
    ask = Fetch(BID, token, WHO, SOURCE, WHO.request_id)
    assert token not in repr(ask) and token not in repr(ServeRecord(ask, link, SUCCESS))


def _hang(started: asyncio.Event) -> Callable[..., Awaitable[Any]]:
    async def hang(*_args: Any) -> Any:
        started.set()
        await asyncio.Event().wait()

    return hang


async def _cancel_when_started(fetch: Awaitable[Fetched], started: asyncio.Event) -> None:
    """Cancel `fetch` once it waits where `started` is set: the cancellation must propagate."""
    task = asyncio.ensure_future(fetch)
    async with asyncio.timeout(_BOUND):
        await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_a_cancelled_link_reused_write_leaves_the_record_to_the_next_presentation() -> None:
    fx = await _fx()
    token, _ = await fx.issue()
    await fx.fetch(token)
    started = asyncio.Event()
    await _cancel_when_started(fx.fetch(token, ahead=_hang(started)), started)
    with pytest.raises(LinkEnded):
        await fx.fetch(token)
    assert [r["reason"] for r in fx.served()] == [None, "link_reused"]


async def test_a_cancelled_served_write_closes_the_artefact_and_the_link_stays_spent() -> None:
    fx = await _fx()
    token, _ = await fx.issue()
    started = asyncio.Event()
    await _cancel_when_started(fx.fetch(token, ahead=_hang(started)), started)
    assert fx.spent(token) and [a.closed for a in fx.w.reader.opened[1:]] == [1]


async def test_a_cancelled_family_read_is_a_cancellation_not_a_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fx = await _fx()
    token, _ = await fx.issue()
    started = asyncio.Event()
    monkeypatch.setattr(fx.sessions, "walk_rotation_family", _hang(started))
    await _cancel_when_started(fx.fetch(token), started)
    assert fx.spent(token) and fx.served() == []
