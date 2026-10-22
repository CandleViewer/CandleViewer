"""The export download's reader (#889 S9-1a), driven directly with no route: `find` (the requester
rule and the job's state), the expiry and its TTL bound, `open` (a planted link, a resized file),
`remove`, and the stream's guards and closure; and (S9-2) the sweep, its loop and the boot probe. A
job store seeded with a succeeded `audit_export` job and a file that `write_export` wrote under
`tmp_path`: no database, no network, no sleeps."""

from __future__ import annotations

import asyncio
import errno
import os
import uuid
from collections.abc import AsyncIterator, Awaitable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from starlette.requests import ClientDisconnect
from structlog.testing import capture_logs

from candleviewer.admin.backups import limits
from candleviewer.api import audit_exports
from candleviewer.api._generated import openapi_models as api
from candleviewer.api.admin_backup_download import DownloadAborted
from candleviewer.api.audit_exports import AuditExports, Export, ExportFileResponse
from candleviewer.api.recorder_admin import AdminJobStore, Job
from candleviewer.audit.access import AuditPrincipal
from candleviewer.audit.export import EXPORT_DIR, ExportPlan, remove_exports, write_export
from candleviewer.settings import Environment
from candleviewer.storage.backup_artefacts import ArtefactUnreadable, ResolvedArtefact
from tests.unit.audit.audit_fakes import FakeAuditRepository

NOW, DAY = datetime(2026, 10, 22, 12, tzinfo=UTC), timedelta(days=1)
JOB = "19000000-0000-4000-8000-000000000001"
OWNER = AuditPrincipal(
    uuid.UUID(int=1), "owner", frozenset({"audit:export"}), uuid.UUID(int=101), is_owner=True
)
_KEY, _PUBLIC = "cv-audit-export-v1:66687aadf862bd77", "A" * 43 + "="  # a test key's, all zero


def manifest(sha256: str, size: int, compressed: bool = True, expires: datetime = NOW) -> Any:
    """An `AuditExportResult`, as S10's job result holds it, of a file of `sha256` and `size`."""
    return {
        "download_url": f"/api/v1/admin/audit/exports/{JOB}", "sha256": sha256,
        "signature": "A" * 86 + "==", "signature_alg": "ed25519", "key_id": _KEY,
        "public_key": _PUBLIC, "compressed": compressed, "size_bytes": size, "row_count": 0,
        "from": "2026-10-22T11:00:00Z", "to": "2026-10-22T12:00:00Z",
        "expires_at": expires.isoformat(),
    }  # fmt: skip


async def seed(
    jobs: AdminJobStore, root: Path, compressed: bool = True, ttl: timedelta = DAY
) -> Path:
    """`OWNER`'s succeeded export, its file written by `write_export` (an empty span) under `root`,
    and its job, as S10 leaves it, in `jobs`."""
    plan = ExportPlan(
        from_ts=NOW - timedelta(hours=1), to_ts=NOW, first_id=None, last_id=None,
        anchor_hash=None, head_id=1, head_hash="0" * 64, environment=Environment.DEMO,
        key_id=_KEY, public_key=_PUBLIC, compressed=compressed,
    )  # fmt: skip
    done = await write_export(plan, FakeAuditRepository(), data_dir=root, job_id=uuid.UUID(JOB))
    result = manifest(done.sha256, done.size_bytes, compressed, NOW + ttl)
    jobs._jobs[JOB] = Job(
        JOB, "audit_export", "succeeded", 100.0, NOW, NOW, result, requester=str(OWNER.user_id)
    )
    return root / EXPORT_DIR / done.name


class _Reader:
    def __init__(self, root: Path, **sweep: Any) -> None:
        self.root, self.now, self.jobs = root, NOW, AdminJobStore()
        self.exports = AuditExports(self.jobs, root, ttl_s=86_400, clock=lambda: self.now, **sweep)


@pytest.fixture
def reader(tmp_path: Path) -> _Reader:
    return _Reader(tmp_path.resolve())


async def test_find_answers_its_requester_with_the_file_and_the_manifest(reader: _Reader) -> None:
    file = await seed(reader.jobs, reader.root)
    export = reader.exports.find(JOB, OWNER)
    assert export is not None and (export.name, export.expires_at) == (file.name, NOW + DAY)
    assert export.manifest.size_bytes == file.stat().st_size


async def test_find_hides_an_export_from_another_owner(reader: _Reader) -> None:
    await seed(reader.jobs, reader.root)
    assert reader.exports.find(JOB, replace(OWNER, user_id=uuid.UUID(int=2))) is None


@pytest.mark.parametrize(
    "change",
    [{"status": "running"}, {"status": "failed"}, {"result": None}, {"result": {"sha256": "x"}}],
    ids=["running", "failed", "no-manifest", "bad-manifest"],
)
async def test_find_has_nothing_for_an_export_with_no_file_to_serve(
    reader: _Reader, change: dict[str, Any]
) -> None:
    await seed(reader.jobs, reader.root)
    reader.jobs._jobs[JOB] = replace(reader.jobs._jobs[JOB], **change)
    assert reader.exports.find(JOB, OWNER) is None


async def test_the_name_is_the_jobs_id_never_text_that_could_leave_the_directory(
    reader: _Reader,
) -> None:
    await seed(reader.jobs, reader.root)
    reader.jobs._jobs["../escape"] = replace(reader.jobs._jobs.pop(JOB), id="../escape")
    assert reader.exports.find("../escape", OWNER) is None  # its requester's, and unserved


async def test_an_export_expires_at_its_expires_at(reader: _Reader) -> None:
    """22 says "after" it: the boundary fails closed."""
    await seed(reader.jobs, reader.root)
    export = reader.exports.find(JOB, OWNER)
    assert export is not None and not reader.exports.expired(export)
    reader.now += DAY
    assert reader.exports.expired(export)


async def test_the_ttl_bounds_an_expires_at_set_later(reader: _Reader) -> None:
    """`audit_export_ttl_s` after the job finished, whatever later instant its manifest names."""
    await seed(reader.jobs, reader.root, ttl=30 * DAY)
    export = reader.exports.find(JOB, OWNER)
    assert export is not None and export.expires_at == NOW + DAY


async def test_open_reads_the_file_its_manifest_describes(reader: _Reader) -> None:
    file = await seed(reader.jobs, reader.root)
    export = reader.exports.find(JOB, OWNER)
    assert export is not None
    opened = await reader.exports.open(export)
    assert isinstance(opened, ResolvedArtefact) and opened.size == file.stat().st_size
    opened.close()


async def _unservable(reader: _Reader, reason: str) -> None:
    export = reader.exports.find(JOB, OWNER)
    assert export is not None
    with capture_logs() as logs:
        assert await reader.exports.open(export) == reason
    assert [e["error"] for e in logs if e["event"] == "audit.export.unservable"] == [reason]


async def test_open_refuses_a_link_planted_at_the_files_name(
    reader: _Reader, tmp_path: Path
) -> None:
    file = await seed(reader.jobs, reader.root)
    outside = tmp_path / "outside.ndjson.gz"
    file.rename(outside)
    file.symlink_to(outside)
    await _unservable(reader, "artefact_missing")
    assert outside.exists()


async def test_open_refuses_a_file_of_another_size_than_its_manifests(reader: _Reader) -> None:
    with (await seed(reader.jobs, reader.root)).open("ab") as file:
        file.write(b"\n")
    await _unservable(reader, "size_changed")


async def test_remove_deletes_an_exports_file(reader: _Reader) -> None:
    file = await seed(reader.jobs, reader.root)
    export = reader.exports.find(JOB, OWNER)
    assert export is not None
    await reader.exports.remove(export)
    assert not file.exists()


async def test_a_removal_that_fails_is_logged_and_never_raises(reader: _Reader) -> None:
    file = await seed(reader.jobs, reader.root)
    export = reader.exports.find(JOB, OWNER)
    assert export is not None
    file.unlink()
    file.mkdir()  # unlink(2) refuses a directory
    with capture_logs() as logs:
        await reader.exports.remove(export)
    failed = [e["errno"] for e in logs if e["event"] == "audit.export.file_step_failed"]
    assert failed == ["EISDIR"] and file.is_dir()


def test_remove_exports_tries_every_name_then_raises_the_first_failure(tmp_path: Path) -> None:
    exports = tmp_path / EXPORT_DIR
    (exports / f"{JOB}.ndjson").mkdir(parents=True)
    stale = exports / f".{uuid.UUID(int=3)}.ndjson.tmp"
    stale.write_bytes(b"x")
    with pytest.raises(IsADirectoryError):
        remove_exports(exports, [f"{JOB}.ndjson", stale.name])
    assert not stale.exists()


def test_a_removal_never_leaves_the_directory(tmp_path: Path) -> None:
    beside = tmp_path / f"{JOB}.ndjson"
    beside.write_bytes(b"not ours")
    (tmp_path / EXPORT_DIR).mkdir()
    remove_exports(tmp_path / EXPORT_DIR, [f"../{beside.name}"])
    assert beside.read_bytes() == b"not ours"


class _File:
    """The reader's descriptor as `ExportFileResponse` uses it: each chunk in turn, `None` one that
    never comes and an exception one that fails; `close()` counted."""

    def __init__(self, size: int, *chunks: bytes | Exception | None) -> None:
        self.size, self.chunks, self.closed = size, chunks, 0

    async def stream(self) -> AsyncIterator[bytes]:
        for chunk in self.chunks:
            if chunk is None:
                await asyncio.Event().wait()
            if isinstance(chunk, Exception):
                raise chunk
            if isinstance(chunk, bytes):
                yield chunk

    def close(self) -> None:
        self.closed += 1


async def _respond(file: _File, send: Any = None) -> None:
    export = Export("x.ndjson", api.AuditExportResult.model_validate(manifest("0" * 64, 4)), NOW)

    async def sent(message: Any) -> None:
        return None

    async def never() -> Any:
        await asyncio.Event().wait()

    scope = {"type": "http", "asgi": {"spec_version": "2.4"}}
    await ExportFileResponse(export, file)(scope, never, send or sent)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("chunks", "error"),
    [((None,), "TimeoutError"), ((ValueError("closed under a read"),), "ValueError"),
     ((ArtefactUnreadable(),), "ArtefactUnreadable"), ((b"abc",), "size_changed"),
     ((b"abcd", b"e"), "size_changed")],
    ids=["stalls", "closed", "unreadable", "short", "long"],
)  # fmt: skip
async def test_a_stream_that_stalls_fails_or_changes_size_is_cut_and_closed(
    monkeypatch: pytest.MonkeyPatch, chunks: tuple[bytes | Exception | None, ...], error: str
) -> None:
    monkeypatch.setattr(audit_exports, "STREAM_READ_BUDGET_S", 0.01)
    file = _File(4, *chunks)
    with capture_logs() as logs, pytest.raises(DownloadAborted):
        await _respond(file)
    aborted = [e["error"] for e in logs if e["event"] == "audit.export.download_aborted"]
    assert (file.closed, aborted) == (1, [error])


class _Budgets:  # `asyncio` as the reader's module sees it, counting each read's budget
    def __init__(self) -> None:
        self.delays: list[float | None] = []

    def timeout(self, delay: float | None) -> Any:
        self.delays.append(delay)
        return asyncio.timeout(delay)

    def __getattr__(self, name: str) -> Any:
        return getattr(asyncio, name)


async def test_each_read_of_the_stream_has_its_own_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    """Not one budget for the whole download: a large file streams for as long as its reads keep
    coming, each within `STREAM_READ_BUDGET_S`, as a backup's does."""
    budgets = _Budgets()
    monkeypatch.setattr(audit_exports, "asyncio", budgets)
    await _respond(_File(4, b"a", b"bc", b"d"))
    assert budgets.delays == [limits.STREAM_READ_BUDGET_S] * 4  # three chunks, then the end


@pytest.mark.parametrize("gone_at", ["http.response.start", "http.response.body"])
async def test_the_file_is_closed_when_the_client_goes(gone_at: str) -> None:
    """Before the stream starts, or during it."""
    file = _File(4, b"ab", b"cd")

    async def send(message: Any) -> None:
        if message["type"] == gone_at:
            raise OSError("client gone")

    with pytest.raises(ClientDisconnect):
        await _respond(file, send)
    assert file.closed == 1


async def test_the_boot_sweep_removes_stale_temporaries_and_unreferenced_files(
    reader: _Reader, tmp_path: Path
) -> None:
    exports, other = reader.root / EXPORT_DIR, tmp_path / "other"
    exports.mkdir()
    other.write_bytes(b"not ours")
    for name in (f"{JOB}.ndjson.gz", f".{uuid.UUID(int=3)}.ndjson.tmp", "notes.txt"):
        (exports / name).write_bytes(b"x")
    (exports / f"{uuid.UUID(int=4)}.ndjson").symlink_to(other)
    await reader.exports.start()
    await reader.exports.stop()
    assert reader.exports.links_ok and sorted(os.listdir(exports)) == ["notes.txt"]
    assert other.read_bytes() == b"not ours"  # a link is removed, never what it points to


async def test_a_sweep_before_any_export_finds_nothing_and_makes_nothing(reader: _Reader) -> None:
    await reader.exports.sweep()
    assert not (reader.root / EXPORT_DIR).exists()


async def test_the_sweep_keeps_what_live_jobs_need(reader: _Reader) -> None:
    file = await seed(reader.jobs, reader.root)
    running = uuid.UUID(int=5)
    reader.jobs._jobs[str(running)] = Job(str(running), "audit_export", "running")
    temporary = file.with_name(f".{running}.ndjson.gz.tmp")
    temporary.write_bytes(b"in progress")
    await reader.exports.sweep()
    assert file.exists() and temporary.exists()


async def test_the_sweep_deletes_a_succeeded_exports_leftover_temporary_name(
    reader: _Reader,
) -> None:
    file = await seed(reader.jobs, reader.root)
    leftover = file.with_name(f".{file.name}.tmp")
    leftover.write_bytes(b"x")
    await reader.exports.sweep()
    assert file.exists() and not leftover.exists()


def _ticking(root: Path, park_at: int = 2) -> tuple[_Reader, list[float], asyncio.Event]:
    """A reader whose sweep loop parks on its `park_at`th sleep and says so, a tick before."""
    calls, parked = list[float](), asyncio.Event()

    async def sleep(seconds: float) -> None:
        calls.append(seconds)
        if len(calls) == park_at:
            parked.set()
            await asyncio.Event().wait()

    return _Reader(root, sleep=sleep), calls, parked


async def _within[T](step: Awaitable[T]) -> T:
    """A wait that fails the test, rather than hanging it, when what it waits for never comes."""
    async with asyncio.timeout(5):
        return await step


async def test_each_tick_sweeps_and_deletes_a_file_once_it_expires(reader: _Reader) -> None:
    ticking, calls, parked = _ticking(reader.root)
    file = await seed(ticking.jobs, ticking.root)
    await ticking.exports.start()
    assert file.exists()  # the boot sweep keeps an export that has not expired
    ticking.now += DAY  # it expires before the loop's first tick
    await _within(parked.wait())
    await ticking.exports.stop()
    assert calls == [60.0, 60.0] and not file.exists()


@pytest.mark.parametrize("failing", [{0}, {1}, {0, 1}], ids=["boot", "first_tick", "both"])
async def test_a_sweep_that_fails_is_logged_and_the_next_one_runs(
    reader: _Reader, monkeypatch: pytest.MonkeyPatch, failing: set[int]
) -> None:
    """The boot's sweep (0) and each tick's go through the guarded `run_once`: a failure is
    logged, the boot goes on, and the next tick runs."""
    ticking, calls, parked = _ticking(reader.root, park_at=3)
    sweeps = list[int]()

    async def flaky() -> None:
        sweeps.append(len(sweeps))
        if sweeps[-1] in failing:
            raise RuntimeError("boom")

    monkeypatch.setattr(ticking.exports, "sweep", flaky)
    with capture_logs() as logs:
        await ticking.exports.start()  # never raises, even when the boot's sweep fails
        await _within(parked.wait())
    await ticking.exports.stop()
    failed = [e["error"] for e in logs if e["event"] == "audit.export.sweep_failed"]
    assert (sweeps, failed, calls) == ([0, 1, 2], ["RuntimeError"] * len(failing), [60.0] * 3)


async def test_a_sweep_that_never_returns_is_cut_at_its_budget(
    reader: _Reader, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(audit_exports, "SWEEP_BUDGET_S", 0.01)

    async def stuck() -> None:
        await asyncio.Event().wait()

    monkeypatch.setattr(reader.exports, "sweep", stuck)
    with capture_logs() as logs:
        await _within(reader.exports.run_once())
    failed = [e["error"] for e in logs if e["event"] == "audit.export.sweep_failed"]
    assert failed == ["TimeoutError"]


async def test_a_boot_on_a_wedged_volume_is_cut_at_its_budgets(
    reader: _Reader, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The probe and the boot's sweep each stop at `SWEEP_BUDGET_S`: export alone degrades, and
    the boot goes on (ADR-0039 driver 4)."""
    monkeypatch.setattr(audit_exports, "SWEEP_BUDGET_S", 0.01)

    async def never(*args: Any, **kwargs: Any) -> None:
        await asyncio.Event().wait()

    monkeypatch.setattr(audit_exports, "run_in_thread", never)
    with capture_logs() as logs:
        await _within(reader.exports.start())
    await reader.exports.stop()
    probe = [
        (e["log_level"], e["error"]) for e in logs if e["event"] == "audit.export.link_probe_failed"
    ]
    swept = [e["error"] for e in logs if e["event"] == "audit.export.sweep_failed"]
    assert (probe, swept, reader.exports.links_ok) == (
        [("critical", "TimeoutError")],
        ["TimeoutError"],
        False,
    )


async def test_a_second_start_keeps_one_task_and_stop_is_idempotent(reader: _Reader) -> None:
    await reader.exports.start()
    task = reader.exports._task
    await reader.exports.start()
    assert task is not None and reader.exports._task is task
    await reader.exports.stop()
    await reader.exports.stop()
    assert task.done() and reader.exports._task is None


@pytest.mark.parametrize(
    ("error", "code"), [(OSError(errno.EPERM, "no hard links"), "EPERM"), (RuntimeError("x"), None)]
)
async def test_a_failing_probe_degrades_export_alone(
    reader: _Reader, monkeypatch: pytest.MonkeyPatch, error: Exception, code: str | None
) -> None:
    def no_links(*args: Any, **kwargs: Any) -> None:
        raise error

    monkeypatch.setattr(os, "link", no_links)
    with capture_logs() as logs:
        await reader.exports.start()  # never raises: the boot goes on
    await reader.exports.stop()
    failed = [e for e in logs if e["event"] == "audit.export.link_probe_failed"]
    assert [(e["log_level"], e["errno"]) for e in failed] == [("critical", code)]
    assert not reader.exports.links_ok and os.listdir(reader.root / EXPORT_DIR) == []


async def test_one_unlink_that_fails_leaves_the_rest_of_the_batch(reader: _Reader) -> None:
    exports = reader.root / EXPORT_DIR
    (exports / f"{JOB}.ndjson").mkdir(parents=True)  # unlink(2) refuses a directory
    stale = exports / f".{uuid.UUID(int=3)}.ndjson.tmp"
    stale.write_bytes(b"x")
    with capture_logs() as logs:
        await reader.exports.sweep()
    failed = [e["errno"] for e in logs if e["event"] == "audit.export.file_step_failed"]
    assert not stale.exists() and failed == ["EISDIR"]
