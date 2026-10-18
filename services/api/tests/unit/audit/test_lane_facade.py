"""ADR-0037 S2b-2a (#3009): the façade (decisions 1, 2 and 12) and the `AuditService` wiring
(start: writer, fold-in, lane; stop: the lane first). A silent lane or sink is an event that never
fires, and a deadline is ordered against the loop's own timers. Files only in `tmp_path`."""

from __future__ import annotations

import asyncio
import errno
import inspect
import threading
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from audit_fakes import FakeAuditRepository, FakeClock
from structlog.testing import capture_logs

from candleviewer.audit import lane_journal as lj
from candleviewer.audit.journal import hold_run_lock, journal_dir
from candleviewer.audit.lane import AuditLane, LaneBootRefused, LaneFacade, lock_lane
from candleviewer.audit.models import AuditEmission, AuditOutcome
from candleviewer.audit.redact import REDACTION_MARKER
from candleviewer.audit.service import AuditService
from candleviewer.audit.writer import AuditUnavailable, AuditWriter

KEYS, WAIT_S = (bytes(range(32)), None), 5.0
LOGOUT: dict[str, Any] = {"actor_label": "owner", "object_id": "s1"}


def on() -> bool:
    return True


def off() -> bool:
    return False


class Lane:
    """An `AuditLane` stand-in: it keeps each record, then raises `error`, stalls or takes it."""

    def __init__(self, error: Exception | None = None, *, stall: bool = False) -> None:
        self.records: list[AuditEmission] = []
        self.error, self.stall = error, stall

    async def append(self, record: AuditEmission) -> int:
        self.records.append(record)
        if self.stall:
            await asyncio.Event().wait()
        if self.error is not None:
            raise self.error
        return len(self.records)


async def sink(path: Path, repo: FakeAuditRepository) -> AuditWriter:
    writer = AuditWriter(repo, str(path / "audit.wal"), clock=FakeClock(), sleep=repo.retry_sleep)
    await writer.start()
    return writer


def facade(writer: AuditWriter, lane: Lane, flag: Any = on, **kw: Any) -> LaneFacade:
    return LaneFacade(writer, cast(AuditLane, lane), flag, **kw)


async def ids(writer: AuditWriter, repo: FakeAuditRepository) -> list[uuid.UUID]:
    await writer.flush(WAIT_S)
    return [uuid.UUID(row["record_id"]) for row in repo.rows]


def ctx(wal: Path | str) -> Any:
    return SimpleNamespace(
        settings=SimpleNamespace(audit_wal_path=str(wal), audit_page_structure_budget=50_000)
    )


@pytest.mark.parametrize("reason", ["full", "too_large", "busy", "io_error", "stopped", "held"])
async def test_facade_hands_the_same_record_to_ingest_when_the_lane_refuses(
    tmp_path: Path, repo: FakeAuditRepository, reason: lj.LaneReason
) -> None:
    writer, lane = await sink(tmp_path, repo), Lane(lj.LaneRefused(reason))
    await facade(writer, lane).emit("auth.logout", **LOGOUT)
    assert await ids(writer, repo) == [lane.records[0].record_id]


async def test_facade_hands_the_same_record_to_ingest_when_the_lane_is_silent_past_its_wait(
    tmp_path: Path, repo: FakeAuditRepository
) -> None:
    writer, lane = await sink(tmp_path, repo), Lane(stall=True)
    await facade(writer, lane, wait_s=0).emit("auth.logout", **LOGOUT)
    assert await ids(writer, repo) == [lane.records[0].record_id]
    assert inspect.signature(LaneFacade).parameters["wait_s"].default == lj.APPEND_WAIT_S == 1.0


async def test_facade_lane_wait_and_fallback_share_the_callers_deadline(
    tmp_path: Path, repo: FakeAuditRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A wait past the deadline ends at it. Then a 0.2 s wait uses part of a 0.3 s deadline, and
    the sink is released at 0.4 s: after the shared deadline, before a fresh one could end."""
    writer, lane = await sink(tmp_path, repo), Lane(stall=True)
    async with asyncio.timeout(WAIT_S):  # a wait that ignored the deadline would stall here
        with pytest.raises(AuditUnavailable, match="deadline"):
            await facade(writer, lane, wait_s=3600).emit("auth.logout", **LOGOUT, deadline_s=0)
    release, loop, ingest = asyncio.Event(), asyncio.get_running_loop(), writer.ingest

    async def held(record: AuditEmission | dict[str, Any]) -> int:  # a sink slower than 0.1 s
        await release.wait()
        return await ingest(record)

    monkeypatch.setattr(writer, "ingest", held)
    timer = loop.call_at(loop.time() + 0.4, release.set)
    with pytest.raises(AuditUnavailable, match="deadline"):
        await facade(writer, lane, wait_s=0.2).emit("auth.logout", **LOGOUT, deadline_s=0.3)
    timer.cancel()
    assert len(lane.records) == 2 and await ids(writer, repo) == []


async def test_facade_never_hands_a_lane_not_admitted_to_the_sink(
    tmp_path: Path, repo: FakeAuditRepository
) -> None:
    writer, lane = await sink(tmp_path, repo), Lane(lj.LaneNotAdmitted("frame 1 is due"))
    with pytest.raises(lj.LaneNotAdmitted):
        await facade(writer, lane).emit("auth.logout", **LOGOUT)
    assert await ids(writer, repo) == []


@pytest.mark.parametrize("flag", [on, off], ids=["on", "off"])
@pytest.mark.parametrize(
    "action", ["audit.lane_started", "audit.lane_resumed", "audit.lane_anomaly"]
)
async def test_facade_refuses_the_lanes_own_records_in_both_flag_positions(
    tmp_path: Path, repo: FakeAuditRepository, flag: Any, action: str
) -> None:
    writer, lane = await sink(tmp_path, repo), Lane()
    with pytest.raises(lj.LaneNotAdmitted):
        await facade(writer, lane, flag).emit(action, actor_label="system:audit-lane")
    assert lane.records == [] and await ids(writer, repo) == []


@pytest.mark.parametrize("action", ["auth.mfa_verified", "auth.session_refreshed"])
async def test_facade_hands_what_the_registry_does_not_admit_straight_to_ingest(
    tmp_path: Path, repo: FakeAuditRepository, action: str
) -> None:
    writer, lane = await sink(tmp_path, repo), Lane()
    await facade(writer, lane).emit(action, actor_label="owner", outcome=AuditOutcome.SUCCESS)
    assert lane.records == [] and len(await ids(writer, repo)) == 1


@pytest.mark.parametrize("refusal", [None, lj.LaneRefused("held")], ids=["lane", "fallback"])
async def test_facade_builds_through_build_so_either_path_is_redacted(
    tmp_path: Path, repo: FakeAuditRepository, refusal: Exception | None
) -> None:
    writer, lane = await sink(tmp_path, repo), Lane(refusal)
    await facade(writer, lane).emit("auth.logout", **LOGOUT, after_state={"token": "s3cret"})
    assert lane.records[0].after_state == {"token": REDACTION_MARKER}
    assert len(await ids(writer, repo)) == (refusal is not None)
    assert "s3cret" not in str(repo.rows)


async def test_facade_with_the_flag_off_is_todays_path_byte_for_byte(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Off, every record goes straight to `ingest()`: the WAL frame and the row are `emit()`'s."""
    monkeypatch.setattr(uuid, "uuid4", lambda: uuid.UUID(int=1))
    repos = FakeAuditRepository(), FakeAuditRepository()
    for name, repo in zip("ab", repos, strict=True):
        (tmp_path / name).mkdir()
        repo.down = True  # each WAL keeps its frame
    today, writer = [await sink(tmp_path / name, r) for name, r in zip("ab", repos, strict=True)]
    lane, fields = Lane(), LOGOUT | {"after_state": {"token": "s3cret"}}
    await today.emit("auth.logout", **fields)
    await facade(writer, lane, off).emit("auth.logout", **fields)
    wal = [(tmp_path / name / "audit.wal").read_bytes() for name in "ab"]
    assert lane.records == [] and wal[0] == wal[1] and b'"auth.logout"' in wal[0]
    for repo in repos:
        repo.down = False
    assert await ids(today, repos[0]) == await ids(writer, repos[1]) == [uuid.UUID(int=1)]
    assert repos[0].rows == repos[1].rows


async def test_service_loads_its_keys_off_the_loop_and_reads_the_flag_off_until_it_is_wired(
    tmp_path: Path, repo: FakeAuditRepository
) -> None:
    threads: list[int] = []

    def loader() -> tuple[bytes, bytes | None]:
        threads.append(threading.get_ident())
        return KEYS

    svc = AuditService(repo, lane_keys=loader)
    await svc.start(ctx(tmp_path / "audit" / "a.wal"))
    assert len(threads) == 1 and threads[0] != threading.get_ident() and svc._lane is not None
    end = svc._lane.journal.end
    await svc.lane.emit("auth.logout", **LOGOUT)
    await svc.writer.flush(WAIT_S)
    assert svc._lane.journal.end == end and "auth.logout" in [row["action"] for row in repo.rows]
    await svc.stop(1)


async def test_service_boots_the_lane_and_stops_it_first_and_its_lock_last(
    tmp_path: Path, repo: FakeAuditRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    wal, order = tmp_path / "audit" / "a.wal", list[str]()
    svc = AuditService(repo, lane_keys=lambda: KEYS)
    svc.use_lane_flag(on)
    await svc.start(ctx(wal))
    await svc.lane.emit("auth.logout", **LOGOUT)
    await svc.lane.flush(WAIT_S)
    actions = ["audit.lane_started", "audit.lane_resumed", "auth.logout"]
    assert [row["action"] for row in repo.rows] == actions
    close, stop = AuditLane.close, AuditWriter.stop

    async def closing(lane: AuditLane) -> None:
        order.append("lane")
        await close(lane)

    async def stopping(writer: AuditWriter, grace_s: float = 5.0) -> None:
        with pytest.raises(LaneBootRefused, match="held"):  # `lane.lock` outlives the writer
            lock_lane(str(wal))
        order.append("writer")
        await stop(writer, grace_s)

    monkeypatch.setattr(AuditLane, "close", closing)
    monkeypatch.setattr(AuditWriter, "stop", stopping)
    lock = svc._lane_lock
    await svc.stop(1)
    assert order == ["lane", "writer"] and lock is not None and lock.closed
    lock_lane(str(wal)).close()  # released by stop()
    with pytest.raises(RuntimeError):
        _ = svc.lane


@pytest.mark.parametrize(
    ("wal", "link"),
    [
        ("audit/a.wal", None),
        ("{tmp}/x/../audit/a.wal", None),
        ("{tmp}/audit/a.wal", "audit"),
        ("{tmp}/audit/a.wal", "audit/lane"),
        ("{tmp}/audit/a.wal", "audit/lane/lane.lock"),
    ],
    ids=["relative", "dot-dot", "audit-dir", "lane-dir", "lane-lock"],
)
async def test_service_refuses_boot_when_the_lane_directory_is_not_anchored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, wal: str, link: str | None
) -> None:
    monkeypatch.chdir(tmp_path)  # the relative WAL path resolves here
    target = tmp_path / "elsewhere"
    (target / "lane").mkdir(parents=True)  # a later boot: `lane/` exists behind the audit dir
    if link is not None:  # a directory, or for the lock a file that an open would create
        (tmp_path / link).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / link).symlink_to(target / "lock" if link.endswith(".lock") else target)
    path = wal.format(tmp=tmp_path)
    svc = AuditService(FakeAuditRepository(), lane_keys=lambda: KEYS)
    with pytest.raises(LaneBootRefused):
        await svc.start(ctx(path))
    assert not svc.is_active
    hold_run_lock(journal_dir(path), exclusive=True).close()  # its shared run lock is gone


async def test_service_refuses_boot_while_another_holder_has_lane_lock(tmp_path: Path) -> None:
    wal = tmp_path / "audit" / "a.wal"
    wal.parent.mkdir()
    other = lock_lane(str(wal))  # flock: a second open file description conflicts
    svc = AuditService(FakeAuditRepository(), lane_keys=lambda: KEYS)
    with pytest.raises(LaneBootRefused, match="held by another process"):
        await svc.start(ctx(wal))
    assert not svc.is_active
    hold_run_lock(journal_dir(str(wal)), exclusive=True).close()
    other.close()
    await svc.start(ctx(wal))  # boots once the holder has gone
    await svc.stop(1)


@pytest.mark.parametrize("damage", ["over-long", "symlink"])
async def test_service_holds_a_lane_it_cannot_open_and_boots_on(
    tmp_path: Path, repo: FakeAuditRepository, damage: str
) -> None:
    """S2a2 Q4: a failed `open()` (`LaneError`, `ELOOP`) holds the lane; the façade falls back."""
    directory, wal = tmp_path / "audit" / "lane", tmp_path / "audit" / "a.wal"
    directory.mkdir(parents=True)
    if damage == "over-long":
        size = lj.SEGMENT_MAX_BYTES + lj.MAX_FRAME_BYTES + 1  # longer than any file it writes
        (directory / "confirmed").write_bytes(b"x" * size)
    else:
        (directory / "confirmed").symlink_to(tmp_path / "elsewhere")
    svc = AuditService(repo, lane_keys=lambda: KEYS)
    svc.use_lane_flag(on)
    await svc.start(ctx(wal))
    assert svc._lane is not None and svc._lane.journal.refusal == "held"
    await svc.lane.emit("auth.logout", **LOGOUT)
    await svc.writer.flush(WAIT_S)
    assert [row["action"] for row in repo.rows] == ["auth.logout"]
    await svc.stop(1)


async def test_service_holds_the_lane_when_its_lock_fails_otherwise_and_then_fails_closed(
    tmp_path: Path, repo: FakeAuditRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    """READY-21: a lock error but another holder (`EACCES`) holds the lane, logged and counted.
    With the flag on the façade falls back, and the action fails closed only if the sink refuses."""
    real = lj._open

    def denied(path: Path | str, flags: int, dir_fd: int | None = None) -> int:
        if str(path).endswith("lane.lock"):
            raise PermissionError(errno.EACCES, "denied")
        return real(path, flags, dir_fd)

    async def refusing(record: AuditEmission | dict[str, Any]) -> int:
        raise AuditUnavailable("the sink refuses")

    monkeypatch.setattr(lj, "_open", denied)
    svc = AuditService(repo, lane_keys=lambda: KEYS)
    svc.use_lane_flag(on)
    with capture_logs() as logs:
        await svc.start(ctx(tmp_path / "audit" / "a.wal"))
    assert svc.lane_lock_failures == 1 and svc._lane is not None
    assert svc._lane.journal.refusal == "held"
    assert ("critical", "PermissionError") in [(e["log_level"], e.get("error")) for e in logs]
    monkeypatch.setattr(svc.writer, "ingest", refusing)
    with pytest.raises(AuditUnavailable, match="the sink refuses"):
        await svc.lane.emit("auth.logout", **LOGOUT)
    monkeypatch.delattr(svc.writer, "ingest")
    await svc.lane.emit("auth.logout", **LOGOUT)
    await svc.writer.flush(WAIT_S)
    assert [row["action"] for row in repo.rows] == ["auth.logout"]
    await svc.stop(1)
