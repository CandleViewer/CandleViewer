"""Unit (E42-T05 #966 BK-10): `BackupDownloads.issue`, once the step-up grant is spent. Under the
admission lock: the row read again, a usable backup with one regular file in the backup root (the
artefact closed at once), else a `backup.downloaded` failure record and the refusal; a link only
with its `issued` record written ahead, naming the spent challenge and the link, never the token.
Every wait is bounded."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from dataclasses import replace
from typing import Any, Final
from uuid import UUID, uuid4

import pytest
from structlog.testing import capture_logs

from candleviewer.admin.backups import limits
from candleviewer.admin.backups.downloads import USABLE_STATUSES, LinkNotUsable, LinkRecord
from candleviewer.admin.backups.gate import BackupJobGate
from candleviewer.admin.backups.links import LINK_TTL, DownloadLinks, LinksFull, LinkSpent
from candleviewer.admin.errors import OpsAuditUnavailable, OpsUnavailable
from candleviewer.audit.actions import validate_action
from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.storage.backup_artefacts import ArtefactMissing, ArtefactUnreadable
from candleviewer.storage.errors import StorageTierUnavailable
from tests.unit.admin._admin_fakes import principal
from tests.unit.admin._backup_fakes import NOW, Store, row
from tests.unit.admin._link_fakes import Reader, World, world

WHO, GRANT, BID = principal("owner"), UUID(int=0xC0FFEE), UUID(int=1)
_BOUND: Final = 2.0  # seconds, a safety net only: no test waits on it when the service is right


async def _issue(w: World) -> tuple[str, Any]:
    async with asyncio.timeout(_BOUND):
        return await w.downloads.issue(BID, WHO, GRANT, w.write_ahead(WHO))


def _record(reason: str | None = None, **link: str) -> dict[str, Any]:
    """The whole `backup.downloaded` record of an issue of backup 1 by the owner."""
    outcome = AuditOutcome.SUCCESS if reason is None else AuditOutcome.FAILURE
    return {
        "action": "backup.downloaded", "actor_label": "owner", "actor_user_id": WHO.user_id,
        "actor_ip": WHO.ip, "session_id": WHO.session_id, "object_kind": "backup",
        "object_id": str(BID), "outcome": outcome, "severity": Severity.ERROR, "reason": reason,
        "after_state": {"stage": "issued", "challenge_id": str(GRANT), **link},
        "request_id": WHO.request_id,
    }  # fmt: skip


@pytest.mark.parametrize("status", ["ok", "verified", "restored"])
async def test_a_usable_backup_gets_a_link_recorded_before_it_leaves(status: str) -> None:
    assert USABLE_STATUSES == {"ok", "verified", "restored"}
    w = world([row(1, status=status)])
    with capture_logs() as logs:
        token, link = await _issue(w)
    assert (link.user_id, link.session_id, link.backup_id) == (WHO.user_id, WHO.session_id, BID)
    assert (link.issued_at, link.expires_at) == (NOW, NOW + LINK_TTL)
    expires = link.expires_at.isoformat()
    assert w.audit.records == [_record(link_id=str(link.link_id), expires_at=expires)]
    assert token not in f"{w.audit.records}" and logs == []
    assert w.reader.locations == [row(1).target_path] and w.reader.opened[0].closed == 1
    assert w.locked == [True]  # written under the admission lock
    spent = w.links.consume(token, backup_id=BID, user_id=WHO.user_id)
    assert isinstance(spent, LinkSpent) and spent.link.link_id == link.link_id


@pytest.mark.parametrize(
    ("over", "error", "resolved"),
    [({"status": "running"}, None, 0), ({"status": "failed"}, None, 0),
     ({"deleted_at": NOW}, None, 0), ({"encrypted": False}, None, 0),
     ({}, ArtefactMissing(), 1), (None, None, 0)],
    ids=["running", "failed", "deleted", "plaintext", "not-one-regular-file", "row-gone"],
)  # fmt: skip
async def test_an_unusable_backup_is_409_with_a_failure_record(
    over: dict[str, Any] | None, error: Exception | None, resolved: int
) -> None:
    w = world([] if over is None else [row(1, **over)], reader=Reader(error=error))
    with pytest.raises(LinkNotUsable):
        await _issue(w)
    assert (w.audit.records, w.locked) == ([_record("backup_not_usable")], [True])
    assert w.links._held == {} and w.store.calls == [
        ("get", BID)
    ]  # read again under the lock, once
    assert len(w.reader.locations) == resolved  # the row decides first


@pytest.mark.parametrize(
    ("store", "reader"),
    [(Store([row(1)], error=StorageTierUnavailable("down")), None),
     (Store([row(1)], hang=True), None), (None, Reader(error=ArtefactUnreadable())),
     (None, Reader(hang=True))],
    ids=["catalogue-down", "catalogue-slow", "volume-unreadable", "resolve-slow"],
)  # fmt: skip
async def test_a_store_that_fails_or_stalls_after_the_spend_is_503_with_a_failure_record(
    store: Store | None, reader: Reader | None
) -> None:
    w = world([row(1)], store=store, reader=reader, read_budget_s=0.05, resolve_budget_s=0.05)
    with capture_logs() as logs:
        with pytest.raises(OpsUnavailable, match=r"^backups: store unavailable$"):
            await _issue(w)
    assert w.audit.records == [_record("store_unavailable")] and w.links._held == {}
    assert row(1).target_path not in f"{logs}"  # only the class is logged


async def test_a_full_link_store_is_503_with_a_failure_record() -> None:
    links = DownloadLinks(now=lambda: NOW, live_max=1)
    links.issue(user_id=uuid4(), session_id=uuid4(), backup_id=BID)
    w = world([row(1)], links=links)
    with pytest.raises(LinksFull):
        await _issue(w)
    assert w.audit.records == [_record("links_full")] and len(links._held) == 1
    assert w.reader.opened[0].closed == 1


@pytest.mark.parametrize(
    ("status", "fails"), [("ok", "raises"), ("ok", "stalls"), ("failed", "raises")]
)
async def test_an_unwritten_record_is_503_and_no_link_survives_it(status: str, fails: str) -> None:
    w = world([row(1, status=status)], record_budget_s=0.05)
    attempts: list[LinkRecord] = []

    async def unwritable(entry: LinkRecord) -> None:
        attempts.append(entry)
        if fails == "stalls":
            await asyncio.Event().wait()
        raise RuntimeError("WAL unwritable")

    with capture_logs() as logs, pytest.raises(OpsAuditUnavailable):  # never the 409
        async with asyncio.timeout(_BOUND):
            await w.downloads.issue(BID, WHO, GRANT, unwritable)
    (attempt,), error = attempts, "TimeoutError" if fails == "stalls" else "RuntimeError"
    assert (attempt.link is None) == (status == "failed") and w.links._held == {}  # forgotten
    assert [(e["event"], e["error"]) for e in logs] == [("admin_backups.link_audit_failed", error)]


@contextlib.asynccontextmanager
async def _deleting(w: World, release: asyncio.Event) -> AsyncIterator[None]:
    """A delete holding the admission lock until `release` (or the end of the block)."""
    holding = asyncio.Event()

    async def delete() -> None:
        async with w.gate.admit_delete(BID):
            holding.set()
            await release.wait()

    task = asyncio.create_task(delete())
    await holding.wait()
    try:
        yield
    finally:
        release.set()
        await task


async def test_the_decision_waits_for_a_delete_holding_the_admission_lock() -> None:
    w, release = world([row(1)]), asyncio.Event()
    async with asyncio.timeout(_BOUND), _deleting(w, release):
        issuing = asyncio.create_task(_issue(w))
        for _ in range(5):
            await asyncio.sleep(0)  # the issue runs as far as it can: up to the lock
        assert (w.store.calls, w.audit.records) == ([], [])
        release.set()
        await issuing
    assert [r["outcome"] for r in w.audit.records] == [AuditOutcome.SUCCESS]


async def test_a_lock_wait_past_its_bound_is_503_and_recorded() -> None:
    w = world([row(1)], gate=BackupJobGate(admit_wait_s=0.05))
    async with asyncio.timeout(_BOUND), _deleting(w, asyncio.Event()):
        with pytest.raises(OpsUnavailable, match="busy"):
            await _issue(w)
    assert (w.audit.records, w.store.calls) == ([_record("store_unavailable")], [])


async def test_a_session_less_caller_is_refused_before_anything() -> None:
    w = world([row(1)])
    with pytest.raises(TypeError, match="session"):
        await w.downloads.issue(BID, replace(WHO, session_id=None), GRANT, w.write_ahead(WHO))
    assert (w.store.calls, w.audit.records) == ([], [])


def test_each_wait_defaults_to_its_limits_budget() -> None:
    downloads = world([row(1)]).downloads
    budgets = (limits.RESOLVE_BUDGET_S, limits.LINK_RECORD_BUDGET_S)
    assert (downloads._resolve_budget_s, downloads._record_budget_s) == budgets == (2.0, 2.0)


def test_backup_downloaded_is_a_registered_action() -> None:
    assert validate_action("backup.downloaded") == "backup.downloaded"  # SR-E42-11
