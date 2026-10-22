"""`GET /admin/audit/exports/{jobId}` (#889 S9-1b; 22 `exportAuditLog`, **Download**): each refusal
in the contract's order, each ordering pinned, another Owner's `404`, the records and the budget,
the record before the first byte, the headers and the digest, the hourly limit, expiry, an
unservable file, and a cancel while the record is pending. The reader itself is
`test_audit_exports.py`'s. A job store seeded with a succeeded `audit_export` job and a file that
`write_export` wrote under `tmp_path`, behind fake session, step-up and audit seams: no database,
no network, no sleeps."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import uuid
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI, Request

from candleviewer.api.audit import make_audit_router
from candleviewer.api.audit_budget import AuditRecordBudget
from candleviewer.api.audit_exports import AuditExports
from candleviewer.api.audit_limiter import AuditVerifyLimiter
from candleviewer.api.recorder_admin import AdminJobStore
from candleviewer.audit.access import AuditPrincipal
from candleviewer.auth.errors import StepUpRequired
from candleviewer.auth.step_up import CHALLENGE_WINDOW, StepUpChallenge
from candleviewer.storage import backup_artefacts
from candleviewer.storage.backup_artefacts import ResolvedArtefact
from tests.unit.api.test_audit_exports import DAY, JOB, NOW, OWNER, seed

_OWNER_ID = str(OWNER.user_id)  # its `requester_key`
_WHO = {
    "owner": OWNER,
    "owner2": replace(OWNER, user_id=uuid.UUID(int=2), username="owner2"),  # another Owner
    "manager": AuditPrincipal(uuid.UUID(int=3), "manager", frozenset({"audit:read"})),
}


class _World:
    """The app over one store and `root`; it is also the session resolver, the step-up service
    and the audit writer, and `log` holds their calls (and, patched, each file read) in order."""

    step_up_is_active = sessions_is_active = is_active = True

    def __init__(self, root: Path, budget: AuditRecordBudget | None = None) -> None:
        self.root, self.now, self.log = root, NOW, list[str]()
        self.elevated, self.fail = True, ""  # `fail`: the action the writer refuses
        self.records: list[tuple[str, dict[str, Any]]] = []
        self.jobs, self.step_up, self.writer = AdminJobStore(), self, self
        self.exports = AuditExports(self.jobs, root, ttl_s=86_400, clock=lambda: self.now)
        self.limiter = AuditVerifyLimiter(rate_per_hour=2, clock=lambda: 0.0)
        self.app = FastAPI()
        self.app.include_router(
            make_audit_router(
                self, self, budget=budget, exports=self.exports, step_up=self,
                download_limiter=self.limiter,
            )
        )  # fmt: skip

    async def resolve(self, request: Request) -> AuditPrincipal | None:
        return _WHO.get(request.headers.get("x-who", ""))

    async def require_elevation(self, session_id: str, action_class: str) -> None:
        self.log.append(f"step_up:{action_class}")
        if not self.elevated:
            raise StepUpRequired(action_class)

    async def record_pending(self, session_id: str, action_class: str) -> StepUpChallenge:
        return StepUpChallenge(uuid.UUID(int=7), action_class, self.now + CHALLENGE_WINDOW)

    async def emit(self, action: str, **fields: Any) -> None:
        if action == self.fail:
            raise OSError("audit WAL unavailable")
        self.log.append(action)
        self.records.append((action, fields))

    async def seed(self, compressed: bool = True, ttl: timedelta = DAY) -> Path:
        return await seed(self.jobs, self.root, compressed, ttl)

    async def get(self, who: str = "owner", job: str = JOB) -> httpx.Response:
        transport = httpx.ASGITransport(app=self.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            return await client.get(f"/admin/audit/exports/{job}", headers={"x-who": who})


@pytest.fixture
def world(tmp_path: Path) -> _World:
    return _World(tmp_path.resolve())


def _reads(world: _World, monkeypatch: pytest.MonkeyPatch) -> None:
    """Each read of a file being served joins `world.log` as `read`."""
    pread = backup_artefacts._pread

    def logged(fd: int, size: int, offset: int) -> bytes:
        world.log.append("read")
        return pread(fd, size, offset)

    monkeypatch.setattr(backup_artefacts, "_pread", logged)


def _full(world: _World) -> None:
    for _ in range(2):
        world.limiter.record_start(_OWNER_ID)


@pytest.mark.parametrize(
    ("who", "job", "passed", "status", "code"),
    [
        ("", JOB, 0, 401, "unauthenticated"),
        ("manager", JOB, 0, 403, "forbidden"),  # the forbidden role
        ("owner2", JOB, 0, 404, "not_found"),  # another Owner (IDOR): before the step-up
        ("owner", str(uuid.UUID(int=9)), 0, 404, "not_found"),  # an unknown job
        ("owner", JOB, 0, 403, "step_up_required"),  # after the requester, before the limit
        ("owner", JOB, 1, 429, "rate_limited"),  # before the expiry
        ("owner", JOB, 2, 410, "gone"),
    ],
)
async def test_each_refusal_comes_in_the_contracts_order(
    world: _World, who: str, job: str, passed: int, status: int, code: str
) -> None:
    """Every later check would refuse too (no step-up, the hour full, the export expired); the
    first `passed` of those three are lifted, so each answer pins its check before the rest."""
    await world.seed(ttl=-timedelta(seconds=1))
    world.elevated = passed >= 1
    if passed < 2:
        _full(world)
    refused = await world.get(who, job)
    assert (refused.status_code, refused.json()["code"]) == (status, code)
    stepped_up = code in ("step_up_required", "rate_limited", "gone")
    assert ("step_up:audit" in world.log) is stepped_up  # never a challenge before the requester


async def test_another_owner_gets_the_404_of_an_unknown_job(world: _World) -> None:
    await world.seed()
    other, unknown = await world.get("owner2"), await world.get("owner2", str(uuid.UUID(int=9)))
    assert (other.status_code, other.json()) == (unknown.status_code, unknown.json())


async def test_a_404_is_recorded_under_the_budget_naming_only_a_job_id(world: _World) -> None:
    await world.seed()
    await world.get("owner2")
    await world.get(job="not-a-job")
    assert [(a, f["reason"], f["object_id"]) for a, f in world.records] == [
        ("admin.audit_denied", "export_not_found", JOB),
        ("admin.audit_denied", "export_not_found", None),  # no request text is recorded
    ]


async def test_an_export_that_names_no_requester_is_no_ones(world: _World) -> None:
    await world.seed()
    world.jobs._jobs[JOB].requester = None
    assert (await world.get()).status_code == 404 and "step_up:audit" not in world.log


async def test_an_export_that_has_not_succeeded_is_the_404_of_an_unknown_job(world: _World) -> None:
    await world.seed()
    world.jobs._jobs[JOB].status = "running"  # or queued, failed, cancelled: no file to serve
    assert (await world.get()).status_code == 404 and "step_up:audit" not in world.log


async def test_a_refusal_whose_record_cannot_be_written_is_503(world: _World) -> None:
    world.fail = "admin.audit_denied"
    refused = await world.get(job="not-a-job")
    assert (refused.status_code, refused.json()["code"]) == (503, "store_unavailable")


async def test_a_refusal_over_the_budget_is_counted_and_answered_with_retry_after(
    world: _World,
) -> None:
    world = _World(world.root, AuditRecordBudget(owner_per_hour=1))
    first, second = await world.get(job="not-a-job"), await world.get(job="not-a-job")
    assert [r.status_code for r in (first, second)] == [404, 404]
    assert "retry-after" not in first.headers and int(second.headers["retry-after"]) >= 1
    assert len(world.records) == 1


async def test_a_429_is_counted_and_never_recorded(world: _World) -> None:
    await world.seed()
    _full(world)
    assert (await world.get()).status_code == 429 and world.records == []
    await world.get(job="not-a-job")  # the next record carries the count
    assert world.records[0][1]["after_state"] == {"suppressed": 1}


async def test_a_step_up_refusal_writes_no_route_record(world: _World) -> None:
    await world.seed()
    world.elevated = False
    assert (await world.get()).status_code == 403 and world.records == []


@pytest.mark.parametrize(("compressed", "media"), [(True, "gzip"), (False, "x-ndjson")])
async def test_the_file_is_served_with_its_headers_and_its_digest(
    world: _World, compressed: bool, media: str
) -> None:
    data = (await world.seed(compressed)).read_bytes()
    served = await world.get()
    digest = hashlib.sha256(data).digest()
    assert (served.status_code, served.content) == (200, data)
    assert served.headers["content-type"] == f"application/{media}"
    assert served.headers["repr-digest"] == f"sha-256=:{base64.b64encode(digest).decode()}:"
    export = world.exports.find(JOB, OWNER)
    assert export is not None and export.manifest.sha256 == digest.hex()
    assert served.headers["cache-control"] == "no-store"
    assert served.headers["x-content-type-options"] == "nosniff"
    assert served.headers["content-disposition"].startswith("attachment;")
    assert served.headers["content-length"] == str(len(data))
    assert "content-encoding" not in served.headers  # the gzip is the file, never an encoding


async def test_the_download_is_recorded_before_its_first_byte(
    world: _World, monkeypatch: pytest.MonkeyPatch
) -> None:
    _reads(world, monkeypatch)
    file = await world.seed()
    assert (await world.get()).status_code == 200
    assert world.log[:3] == ["step_up:audit", "admin.audit_export", "read"]
    [(_, record)] = world.records
    assert (record["reason"], record["object_kind"], record["object_id"]) == (
        "downloaded", "audit_export", JOB
    )  # fmt: skip
    digest = hashlib.sha256(file.read_bytes()).hexdigest()
    assert record["after_state"] == {"sha256": digest, "size_bytes": file.stat().st_size}


async def test_the_downloaded_record_never_passes_through_the_budget(world: _World) -> None:
    world = _World(world.root, AuditRecordBudget(owner_per_hour=1))
    await world.seed()
    await world.get(job="not-a-job")  # the hour's one budgeted record
    assert (await world.get()).status_code == 200
    assert [a for a, _ in world.records] == ["admin.audit_denied", "admin.audit_export"]


async def test_an_unwritten_record_is_503_with_no_byte(
    world: _World, monkeypatch: pytest.MonkeyPatch
) -> None:
    _reads(world, monkeypatch)
    released: list[bool] = []
    close = ResolvedArtefact.close

    def closed(self: ResolvedArtefact) -> None:
        close(self)
        released.append(not self._release.alive)

    monkeypatch.setattr(ResolvedArtefact, "close", closed)
    await world.seed()
    world.fail = "admin.audit_export"
    refused = await world.get()
    assert (refused.status_code, refused.json()["code"]) == (503, "store_unavailable")
    assert refused.headers["retry-after"] == "1" and "read" not in world.log
    assert released == [True]  # the unwritten record closes the file, never the collector


async def test_a_download_cancelled_while_its_record_is_pending_releases_the_file(
    world: _World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The re-check's finding: a cancel never leaves the descriptor to the collector."""
    await world.seed()
    released, entered = list[bool](), asyncio.Event()
    close = ResolvedArtefact.close

    def closed(self: ResolvedArtefact) -> None:
        close(self)
        released.append(not self._release.alive)

    async def pending(action: str, **fields: Any) -> None:
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(ResolvedArtefact, "close", closed)
    world.emit = pending  # type: ignore[method-assign]
    request = asyncio.create_task(world.get())
    async with asyncio.timeout(5):  # a route that answered before its record would fail here
        await entered.wait()
    request.cancel()
    with pytest.raises(asyncio.CancelledError):
        await request
    assert released == [True]


async def test_a_refusal_after_the_check_frees_its_place(world: _World) -> None:
    await world.seed()
    world.fail = "admin.audit_export"
    world.limiter.record_start(_OWNER_ID)
    assert (await world.get()).status_code == 503
    assert world.limiter.retry_after(_OWNER_ID) is None  # one place left of two: its own freed


async def test_a_place_is_taken_at_the_check_so_downloads_in_flight_count(world: _World) -> None:
    await world.seed()
    world.limiter.record_start(_OWNER_ID)  # one place of two left
    entered, go = asyncio.Event(), asyncio.Event()

    async def held(action: str, **fields: Any) -> None:  # the first download's record waits
        entered.set()
        await go.wait()
        await _World.emit(world, action, **fields)

    world.emit = held  # type: ignore[method-assign]
    async with asyncio.TaskGroup() as group:
        first = group.create_task(world.get())
        await entered.wait()
        second = await world.get()
        go.set()
    assert (first.result().status_code, second.status_code) == (200, 429)


async def test_served_downloads_count_against_the_hour(world: _World) -> None:
    await world.seed()
    answers = [await world.get() for _ in range(3)]
    assert [a.status_code for a in answers] == [200, 200, 429]
    assert int(answers[2].headers["retry-after"]) >= 1


async def test_an_expired_export_is_gone_and_its_file_deleted(world: _World) -> None:
    file = await world.seed()
    world.now += DAY  # its `expires_at`
    assert (await world.get()).status_code == 410
    assert not file.exists()
    assert [(a, f["reason"]) for a, f in world.records] == [
        ("admin.audit_denied", "export_expired")
    ]


async def _unservable(world: _World, artefact: str, retry_after: str | None = None) -> None:
    refused = await world.get()
    assert (refused.status_code, refused.json()["code"]) == (503, "store_unavailable")
    assert refused.headers.get("retry-after") == retry_after
    assert [(a, f["reason"], f["after_state"]) for a, f in world.records] == [
        ("admin.audit_denied", "export_unservable", {"artefact": artefact})
    ]  # recorded under the budget, and never `admin.audit_export`


async def test_a_link_planted_at_the_files_name_is_refused(world: _World, tmp_path: Path) -> None:
    file = await world.seed()
    outside = tmp_path / "outside.ndjson.gz"
    file.rename(outside)
    file.symlink_to(outside)
    await _unservable(world, "artefact_missing")
    assert outside.exists()


async def test_a_file_of_another_size_than_its_manifest_is_never_served(world: _World) -> None:
    with (await world.seed()).open("ab") as file:
        file.write(b"\n")
    await _unservable(world, "size_changed")


async def test_a_file_the_store_cannot_read_now_is_retried_after_a_second(
    world: _World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only the reader's transient cause, `store_unavailable`, carries `Retry-After`."""
    await world.seed()

    async def unreadable(export: Any) -> str:
        return "store_unavailable"

    monkeypatch.setattr(world.exports, "open", unreadable)
    await _unservable(world, "store_unavailable", "1")
