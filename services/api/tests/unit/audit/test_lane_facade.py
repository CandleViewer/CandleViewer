"""ADR-0037 S2b-2a and S2b-2b (#3009): the façade (decisions 1, 2 and 12) and the `AuditService`
wiring (start: writer, fold-in, lane; stop: the lane first). A silent lane or sink is an event that
never fires, and a deadline is ordered against the loop's own timers. Files only in `tmp_path`."""

from __future__ import annotations

import asyncio
import errno
import inspect
import os
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
from candleviewer.audit.lane import (
    FALLBACK_LOG_S,
    PROBE_FILE,
    AuditLane,
    LaneBootRefused,
    LaneFacade,
    lane_dir,
    lock_lane,
)
from candleviewer.audit.models import AuditEmission, AuditOutcome, ExchangeEnv, Severity
from candleviewer.audit.redact import REDACTION_MARKER
from candleviewer.audit.service import AuditService
from candleviewer.audit.writer import AuditUnavailable, AuditWriter, AuditWriterStopped

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


def test_facade_waits_append_wait_s_for_the_lane_by_default() -> None:
    assert inspect.signature(LaneFacade).parameters["wait_s"].default == lj.APPEND_WAIT_S == 1.0


async def test_facade_ends_the_lanes_wait_at_the_callers_deadline(
    tmp_path: Path, repo: FakeAuditRepository
) -> None:
    writer, lane = await sink(tmp_path, repo), Lane(stall=True)
    async with asyncio.timeout(WAIT_S):  # a wait that ignored the deadline would stall here
        with pytest.raises(AuditUnavailable, match="deadline"):
            await facade(writer, lane, wait_s=3600).emit("auth.logout", **LOGOUT, deadline_s=0)
    assert await ids(writer, repo) == []


async def test_facade_gives_the_fallback_only_what_the_lanes_wait_left(
    tmp_path: Path, repo: FakeAuditRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A 0.2 s wait uses part of a 0.3 s deadline, and the sink is released at 0.4 s: after the
    shared deadline, before a fresh one could end."""
    writer, lane = await sink(tmp_path, repo), Lane(stall=True)
    release, loop, ingest = asyncio.Event(), asyncio.get_running_loop(), writer.ingest

    async def held(record: AuditEmission | dict[str, Any]) -> int:  # a sink slower than 0.1 s
        await release.wait()
        return await ingest(record)

    monkeypatch.setattr(writer, "ingest", held)
    timer = loop.call_at(loop.time() + 0.4, release.set)
    with pytest.raises(AuditUnavailable, match="deadline"):
        await facade(writer, lane, wait_s=0.2).emit("auth.logout", **LOGOUT, deadline_s=0.3)
    timer.cancel()
    assert len(lane.records) == 1 and await ids(writer, repo) == []


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


def test_facade_takes_emits_keywords_and_the_callers_deadline() -> None:
    """Decision 2's shape: `emit()`'s parameters and `deadline_s`, kind and default."""
    facade_params = dict(inspect.signature(LaneFacade.emit).parameters)
    deadline = facade_params.pop("deadline_s")
    assert facade_params == dict(inspect.signature(AuditWriter.emit).parameters)
    assert (deadline.kind, deadline.default) == (inspect.Parameter.KEYWORD_ONLY, None)


async def test_facade_forwards_every_keyword_to_build(
    tmp_path: Path, repo: FakeAuditRepository
) -> None:
    """A distinct value per keyword, so a dropped or swapped one shows."""
    writer, lane = await sink(tmp_path, repo), Lane()
    fields: dict[str, Any] = {
        "actor_label": "label-1", "actor_user_id": uuid.UUID(int=2), "actor_ip": "203.0.113.3",
        "session_id": uuid.UUID(int=4), "object_kind": "kind-5", "object_id": "id-6",
        "object_label": "label-7", "outcome": AuditOutcome.FAILURE, "severity": Severity.WARNING,
        "reason": "reason-8", "before_state": {"b": 9}, "after_state": {"a": 10},
        "request_id": uuid.UUID(int=11), "env": ExchangeEnv.DEMO,
    }  # fmt: skip
    assert set(fields) == set(inspect.signature(AuditWriter.emit).parameters) - {"self", "action"}
    await facade(writer, lane).emit("auth.logout", **fields)
    built, mine = writer.build("auth.logout", **fields), lane.records[0]
    assert mine.model_dump(exclude={"record_id", "event_ts"}) == built.model_dump(
        exclude={"record_id", "event_ts"}
    )


async def test_facade_logs_one_fallback_per_reason_per_interval(
    tmp_path: Path, repo: FakeAuditRepository
) -> None:
    """A held lane falls back on every record; one WARNING per reason per interval,
    with the count of those it did not log, and `timeout` is a reason of its own."""
    now, writer, lane = [0.0], await sink(tmp_path, repo), Lane(lj.LaneRefused("held"))
    held = facade(writer, lane, wait_s=0, clock=lambda: now[0])
    with capture_logs() as logs:
        for now[0] in (0.0, 1.0, 2.0):
            await held.emit("auth.logout", **LOGOUT)
        lane.error, lane.stall = None, True  # the lane stops answering: `timeout`
        await held.emit("auth.logout", **LOGOUT)
        lane.error, lane.stall, now[0] = lj.LaneRefused("held"), False, FALLBACK_LOG_S + 1
        await held.emit("auth.logout", **LOGOUT)
    lines = [(e["log_level"], e["reason"], e["skipped"]) for e in logs if "skipped" in e]
    assert lines == [("warning", "held", 0), ("warning", "timeout", 0), ("warning", "held", 2)]
    assert {e["event"] for e in logs if "skipped" in e} == {"audit.lane.fallback"}
    assert len(await ids(writer, repo)) == 5


async def test_service_loads_its_keys_once_off_the_loop(
    tmp_path: Path, repo: FakeAuditRepository
) -> None:
    threads: list[int] = []

    def loader() -> tuple[bytes, bytes | None]:
        threads.append(threading.get_ident())
        return KEYS

    svc = AuditService(repo, lane_keys=loader)
    await svc.start(ctx(tmp_path / "audit" / "a.wal"))
    assert len(threads) == 1 and threads[0] != threading.get_ident() and svc._lane is not None
    await svc.stop(1)


async def test_service_reads_the_flag_off_until_it_is_wired(
    tmp_path: Path, repo: FakeAuditRepository
) -> None:
    svc = AuditService(repo, lane_keys=lambda: KEYS)
    await svc.start(ctx(tmp_path / "audit" / "a.wal"))
    assert svc._lane is not None
    end = svc._lane.journal.end
    await svc.lane.emit("auth.logout", **LOGOUT)
    await svc.writer.flush(WAIT_S)
    assert svc._lane.journal.end == end and "auth.logout" in [row["action"] for row in repo.rows]
    await svc.stop(1)


async def started(tmp_path: Path, repo: FakeAuditRepository) -> tuple[AuditService, Path]:
    wal, svc = tmp_path / "audit" / "a.wal", AuditService(repo, lane_keys=lambda: KEYS)
    svc.use_lane_flag(on)
    await svc.start(ctx(wal))
    return svc, wal


async def test_service_boots_the_lane_with_its_two_rows(
    tmp_path: Path, repo: FakeAuditRepository
) -> None:
    svc, _ = await started(tmp_path, repo)
    await svc.lane.emit("auth.logout", **LOGOUT)
    await svc.lane.flush(WAIT_S)
    actions = ["audit.lane_started", "audit.lane_resumed", "auth.logout"]
    assert [row["action"] for row in repo.rows] == actions
    await svc.stop(1)


async def test_service_stops_the_lane_first_and_holds_lane_lock_past_the_writer(
    tmp_path: Path, repo: FakeAuditRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    (svc, wal), order = await started(tmp_path, repo), list[str]()
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
    await svc.stop(1)
    assert order == ["lane", "writer"]


async def test_service_stop_releases_lane_lock_and_the_facade(
    tmp_path: Path, repo: FakeAuditRepository
) -> None:
    svc, wal = await started(tmp_path, repo)
    lock = svc._lane_lock
    await svc.stop(1)
    assert lock is not None and lock.closed
    lock_lane(str(wal)).close()
    with pytest.raises(RuntimeError):
        _ = svc.lane


@pytest.mark.parametrize("failure", ["raises", "overruns"])
async def test_service_stop_runs_on_past_a_lane_close_that_fails(
    tmp_path: Path, repo: FakeAuditRepository, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    """The close gets half the grace, then the writer stops with the rest and the run lock is
    released; `lane.lock` stays with the process, since a lane operation may still run (#2250)."""
    (svc, wal), graces = await started(tmp_path, repo), list[float]()
    lane, close, stop = svc._lane, AuditLane.close, AuditWriter.stop

    async def closing(lane: AuditLane) -> None:
        if failure == "raises":
            raise OSError("the close failed")
        await asyncio.Event().wait()

    async def stopping(writer: AuditWriter, grace_s: float = 5.0) -> None:
        graces.append(grace_s)
        await stop(writer, grace_s)

    monkeypatch.setattr(AuditLane, "close", closing)
    monkeypatch.setattr(AuditWriter, "stop", stopping)
    lock = svc._lane_lock
    with capture_logs() as logs:
        async with asyncio.timeout(WAIT_S):
            await svc.stop(1.0)
    assert not svc.is_active and len(graces) == 1 and graces[0] <= 1.0
    assert (0.3 <= graces[0] <= 0.7) if failure == "overruns" else (graces[0] > 0.5)  # the rest
    error = "OSError" if failure == "raises" else "TimeoutError"
    assert ("critical", error) in [(e["log_level"], e.get("error")) for e in logs]
    hold_run_lock(journal_dir(str(wal)), exclusive=True).close()  # the run lock is gone
    with pytest.raises(LaneBootRefused, match="held"):
        lock_lane(str(wal))
    assert lock is not None and not lock.closed and svc._lane_lock is lock
    assert lane is not None
    await close(lane)
    lock.close()


@pytest.mark.parametrize("lane_closes", [True, False], ids=["lane-closed", "lane-close-failed"])
async def test_service_stop_keeps_both_locks_when_the_writer_stop_fails(
    tmp_path: Path, repo: FakeAuditRepository, monkeypatch: pytest.MonkeyPatch, lane_closes: bool
) -> None:
    """A second `stop()` releases the run lock once the writer stops, and `lane.lock` only if the
    first one closed the lane (SR-S2B2B1-01)."""
    svc, _ = await started(tmp_path, repo)
    locks, lane, stop = (svc._lane_lock, svc._run_lock), svc._lane, AuditWriter.stop

    async def failing(writer: AuditWriter, grace_s: float = 5.0) -> None:
        raise AuditWriterStopped()

    async def unclosed(lane: AuditLane) -> None:
        raise OSError("the close failed")

    monkeypatch.setattr(AuditWriter, "stop", failing)
    if not lane_closes:
        monkeypatch.setattr(AuditLane, "close", unclosed)
    with pytest.raises(AuditWriterStopped):
        await svc.stop(1)
    assert svc._query is None and not svc._started
    assert (svc._lane_lock, svc._run_lock) == locks
    assert all(lock is not None and not lock.closed for lock in locks)
    monkeypatch.setattr(AuditWriter, "stop", stop)
    await svc.stop(1)  # the writer stops now: the run lock goes, `lane.lock` with a closed lane
    assert [lock is not None and lock.closed for lock in locks] == [lane_closes, True]
    if not lane_closes and lane is not None and locks[0] is not None:
        monkeypatch.undo()
        await lane.close()
        locks[0].close()


async def test_service_stop_after_a_boot_cancelled_in_the_lanes_open_keeps_lane_lock(
    tmp_path: Path, repo: FakeAuditRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SR-S2B2B1-01: the shielded open runs on in its thread after `start()` is cancelled; `stop()`
    waits for it within half its grace and, past that, keeps `lane.lock` from a second holder."""
    parked, release, boot = threading.Event(), threading.Event(), lj.LaneFiles.boot

    def parking(files: lj.LaneFiles) -> tuple[list[str], bytes | None, bytes | None]:
        parked.set()
        release.wait(WAIT_S)
        return boot(files)

    monkeypatch.setattr(lj.LaneFiles, "boot", parking)
    wal, svc = tmp_path / "audit" / "a.wal", AuditService(repo, lane_keys=lambda: KEYS)
    starting = asyncio.create_task(svc.start(ctx(wal)))
    await asyncio.to_thread(parked.wait, WAIT_S)
    starting.cancel()
    with pytest.raises(asyncio.CancelledError):
        await starting
    lane, lock = svc._lane, svc._lane_lock
    await svc.stop(0.2)  # the open, still parked, overruns the lane's 0.1 s
    with pytest.raises(LaneBootRefused, match="held"):
        lock_lane(str(wal))
    assert lock is not None and not lock.closed and svc._lane_lock is lock
    release.set()
    assert lane is not None
    await lane.close()  # once the open has ended
    lock.close()


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


def denied(monkeypatch: pytest.MonkeyPatch) -> None:
    """`lane.lock` cannot be opened for a reason other than another holder (`EACCES`)."""
    real = lj._open

    def opening(path: Path | str, flags: int, dir_fd: int | None = None) -> int:
        if str(path).endswith("lane.lock"):
            raise PermissionError(errno.EACCES, "denied")
        return real(path, flags, dir_fd)

    monkeypatch.setattr(lj, "_open", opening)


async def test_service_holds_the_lane_when_its_lock_fails_otherwise(
    tmp_path: Path, repo: FakeAuditRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    """READY-21: a lock error but another holder holds the lane, logged critical and counted; the
    hard-link probe runs only under `lane.lock`, so not here."""
    probes: list[str] = []
    denied(monkeypatch)
    monkeypatch.setattr("candleviewer.audit.service.links_work", probes.append)
    with capture_logs() as logs:
        svc, _ = await started(tmp_path, repo)
    assert svc.lane_lock_failures == 1 and svc._lane is not None and probes == []
    assert svc._lane.journal.refusal == "held"
    assert ("critical", "PermissionError") in [(e["log_level"], e.get("error")) for e in logs]
    await svc.stop(1)


async def test_a_held_lane_fails_closed_when_the_sink_refuses_too(
    tmp_path: Path, repo: FakeAuditRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def refusing(record: AuditEmission | dict[str, Any]) -> int:
        raise AuditUnavailable("the sink refuses")

    denied(monkeypatch)
    svc, _ = await started(tmp_path, repo)
    monkeypatch.setattr(svc.writer, "ingest", refusing)
    with pytest.raises(AuditUnavailable, match="the sink refuses"):
        await svc.lane.emit("auth.logout", **LOGOUT)
    monkeypatch.delattr(svc.writer, "ingest")
    await svc.stop(1)


async def test_a_held_lane_falls_back_to_the_sink(
    tmp_path: Path, repo: FakeAuditRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    denied(monkeypatch)
    svc, _ = await started(tmp_path, repo)
    await svc.lane.emit("auth.logout", **LOGOUT)
    await svc.writer.flush(WAIT_S)
    assert [row["action"] for row in repo.rows] == ["auth.logout"]
    await svc.stop(1)


async def test_service_holds_the_lane_on_a_volume_without_hard_links(
    tmp_path: Path, repo: FakeAuditRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§15.6: the probe at boot finds no hard links, so the lane holds unopened (counted, logged
    critical) and keeps `lane.lock`; the probe leaves no file behind."""

    def no_links(src: Path | str, dst: Path | str, **kw: Any) -> None:
        raise OSError(errno.EPERM, "no hard links")

    monkeypatch.setattr("os.link", no_links)
    with capture_logs() as logs:
        svc, wal = await started(tmp_path, repo)
    assert svc.lane_link_failures == 1 and svc._lane is not None
    assert svc._lane.journal.refusal == "held" and svc.lane_lock_failures == 0
    lines = [(e["log_level"], e.get("error"), e.get("errno")) for e in logs]
    assert ("critical", "PermissionError", "EPERM") in lines
    assert sorted(os.listdir(lane_dir(str(wal)))) == ["lane.lock"]
    with pytest.raises(LaneBootRefused, match="held"):
        lock_lane(str(wal))
    await svc.stop(1)


async def test_the_hard_link_probe_clears_a_crashs_leftovers_and_leaves_nothing(
    tmp_path: Path, repo: FakeAuditRepository
) -> None:
    directory = lane_dir(str(tmp_path / "audit" / "a.wal"))
    directory.mkdir(parents=True)
    for name in (PROBE_FILE, f"{PROBE_FILE}.link"):
        (directory / name).write_bytes(b"")
    svc, _ = await started(tmp_path, repo)
    assert svc.lane_link_failures == 0 and svc._lane is not None
    assert svc._lane.journal.refusal is None
    assert not {PROBE_FILE, f"{PROBE_FILE}.link"} & set(os.listdir(directory))
    await svc.stop(1)
