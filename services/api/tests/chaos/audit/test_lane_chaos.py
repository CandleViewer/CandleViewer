"""ADR-0037 (#3009) chaos for the journal-first audit lane: C-13.6 scenarios 10 and 12, 13's
disk-full fault on the audit volume, and a frame tampered between restarts (AC-LANE-01's restart
half).

The CI `integration` job's chaos step runs it (`-m "chaos and integration"`) against the compose
Postgres, migrated, and the fixed-size loopback image it mounts. Each scenario boots the real
`AuditService` as cv-api does: the lane key, `lane.lock`, the hard-link probe, the lane and its
drain, and the façade with the flag on. Keys are generated per test; scenario 12's child process
gets its key on stdin. Every wait is bounded and polls a condition; nothing sleeps.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import shutil
import signal
import sys
import uuid
from collections import Counter
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import asyncpg
import pytest

from candleviewer.audit import writer as aw
from candleviewer.audit.query import AuditQueryService
from candleviewer.audit.repository import AuditRepository
from candleviewer.audit.service import AuditService
from candleviewer.storage.repositories.audit_sqlalchemy import SqlAlchemyAuditRepository
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from tests.chaos.storage import _stack as st

pytestmark = [pytest.mark.chaos, pytest.mark.integration]

API_DIR = Path(__file__).resolve().parents[3]  # services/api, the child's working directory
WAIT_S = 120.0  # the bound on every wait for the drain, the writer or the child
WAL_CAP = 16 * 1024  # scenario 10's small `max_wal_bytes`
BOOT = ("audit.lane_started", "audit.lane_resumed")


class SmallWal(aw.AuditWriter):
    """The production writer with scenario 10's small WAL cap and test-sized insert retries."""

    def __init__(self, repository: AuditRepository, wal_path: str) -> None:
        super().__init__(
            repository, wal_path, max_wal_bytes=WAL_CAP, retry_initial_delay_s=0.1,
            retry_max_delay_s=1.0,
        )  # fmt: skip


@pytest.fixture(autouse=True)
async def _postgres_up() -> None:
    await st.ensure_up("postgres", st.pg_up)


def tag_for(scenario: str) -> str:
    return f"{scenario}-{uuid.uuid4().hex[:12]}"


@contextlib.asynccontextmanager
async def running(audit: Path, key: bytes) -> AsyncIterator[AuditService]:
    """`AuditService` on `audit/`, started and stopped as the supervisor does, the flag on."""
    relational = SqlAlchemyRelationalRepository(st.pg_dsn(), "lane-chaos")
    svc = AuditService(SqlAlchemyAuditRepository(relational), lane_keys=lambda: (key, None))
    svc.use_lane_flag(lambda: True)
    settings = SimpleNamespace(
        audit_wal_path=str(audit / "audit.wal"), audit_page_structure_budget=50_000
    )
    try:
        try:  # a start() that fails part-way is stopped too, and the engine goes either way
            await svc.start(cast(Any, SimpleNamespace(settings=settings)))
            yield svc
        finally:
            await svc.stop(15)
    finally:
        await relational.dispose()


async def logouts(svc: AuditService, tag: str, numbers: range) -> list[str]:
    """Sign-out intents through the façade; each is durable when `emit()` returns."""
    ids = [f"{tag}-{n}" for n in numbers]
    for object_id in ids:
        await svc.lane.emit("auth.logout", actor_label="owner", object_id=object_id)
    return ids


async def drained(svc: AuditService) -> str:
    """Every frame confirmed and the WAL in Postgres; the lane's id."""
    await svc.lane.flush(WAIT_S)
    await svc.writer.flush(WAIT_S)
    assert svc._lane is not None
    return str(svc._lane.journal.lane)


async def fetch(query: str, *args: object) -> list[asyncpg.Record]:
    conn = await asyncpg.connect(st.pg_dsn().replace("+asyncpg", "", 1), timeout=10)
    try:
        rows: list[asyncpg.Record] = await conn.fetch(query, *args, timeout=30)
        return rows
    finally:
        await conn.close()


async def counts(tag: str) -> dict[str, int]:
    """Rows per sign-out of the scenario; each must be 1: nothing lost, nothing repeated."""
    rows = await fetch(
        "SELECT object_id, count(*) FROM audit_log WHERE action = 'auth.logout' "
        "AND starts_with(object_id, $1) GROUP BY object_id",
        f"{tag}-",
    )
    return {str(r[0]): int(r[1]) for r in rows}


async def lane_rows(lane: str) -> Counter[tuple[str, str | None, str]]:
    """The lane's own rows: action, reason and severity."""
    rows = await fetch(
        "SELECT action, reason, severity::text FROM audit_log "
        "WHERE object_kind = 'audit_lane' AND object_id = $1",
        lane,
    )
    return Counter((str(r[0]), r[1], str(r[2])) for r in rows)


def boot_rows(boots: int) -> Counter[tuple[str, str | None, str]]:
    return Counter({(BOOT[0], None, "warning"): 1, (BOOT[1], None, "info"): boots})


async def verified() -> bool:
    relational = SqlAlchemyRelationalRepository(st.pg_dsn(), "lane-chaos-verify")
    try:
        return (await AuditQueryService(SqlAlchemyAuditRepository(relational)).verify()).verified
    finally:
        await relational.dispose()


# --- C-13.6 scenario 10: Postgres stopped until the WAL fills ---------------------------------


async def test_s10_postgres_down_till_the_wal_fills_loses_no_journaled_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The lane keeps journaling sign-outs while the drain fills the writer's small WAL, which then
    refuses an `emit()` caller (fail closed, C-2.9) and never lands its record. Postgres comes
    back, and every journaled record reaches `audit_log` once and the chain verifies."""
    monkeypatch.setattr(aw, "AuditWriter", SmallWal)  # what `AuditService.start()` builds
    tag = tag_for("s10")
    async with running(tmp_path / "audit", os.urandom(32)) as svc:
        ids = await logouts(svc, tag, range(3))
        await drained(svc)

        async def full() -> bool:
            return svc.writer.refused_total > 0

        async with st.stopped("postgres", st.pg_up):
            ids += await logouts(svc, tag, range(3, 63))
            await st.until(full, "the writer's WAL refuses the drain", timeout_s=WAIT_S)
            # As large as the two-digit sign-outs the WAL refuses, and one `counts()` would show.
            with pytest.raises(aw.AuditUnavailable):
                await svc.writer.emit("auth.logout", actor_label="owner", object_id=f"{tag}-xx")
        ids += await logouts(svc, tag, range(63, 64))  # an append cuts the drain's backoff
        lane = await drained(svc)
    assert await counts(tag) == dict.fromkeys(ids, 1)
    assert await lane_rows(lane) == boot_rows(1)
    assert await verified()


# --- C-13.6 scenario 12: SIGKILL during an append and during a drain --------------------------


async def killed(audit: Path, key: bytes, tag: str, point: str) -> list[str]:
    """Run `_lane_child` until it parks at `point`, then SIGKILL it; the ids it saw acknowledged."""
    child = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "tests.chaos.audit._lane_child", cwd=API_DIR,
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )  # fmt: skip
    assert child.stdin is not None and child.stdout is not None
    order = {"key": key.hex(), "tag": tag, "point": point, "dsn": st.pg_dsn(), "wal": str(audit)}
    child.stdin.write(json.dumps(order).encode() + b"\n")
    acked, seen = list[str](), list[str]()
    try:
        async with asyncio.timeout(WAIT_S):
            await child.stdin.drain()
            while (line := (await child.stdout.readline()).decode()) != f"@@ parked {point}\n":
                assert line, "the child ended before it parked:\n" + "".join(seen[-40:])
                seen.append(line)
                acked += [line.split()[-1]] if line.startswith("@@ acked ") else []
    except TimeoutError:
        raise AssertionError("the child never parked:\n" + "".join(seen[-40:])) from None
    finally:
        with contextlib.suppress(ProcessLookupError):
            child.kill()
        await child.wait()
    assert child.returncode == -signal.SIGKILL
    return acked


@pytest.mark.parametrize("point", ["append-torn", "append-unsynced", "drain-marker"])
async def test_s12_sigkill_during_an_append_or_a_drain_loses_and_repeats_nothing(
    tmp_path: Path, point: str
) -> None:
    """The restart drains every acknowledged sign-out once. The record the kill landed in was
    never acknowledged: written whole it is drained like any other (once), torn it is one
    `torn_tail` row and never a record. A kill in the drain's marker write leaves the old marker
    and a stray `confirmed.tmp`: the re-ingested records are no-ops, and no stray outlives it."""
    tag, key, audit = tag_for("s12"), os.urandom(32), tmp_path / "audit"
    acked = await killed(audit, key, tag, point)
    assert len(acked) == 4
    async with running(audit, key) as svc:
        lane = await drained(svc)
    assert not (audit / "lane" / "confirmed.tmp").exists()
    whole = {f"{tag}-victim": 1} if point == "append-unsynced" else {}
    assert await counts(tag) == dict.fromkeys(acked, 1) | whole
    torn = Counter({("audit.lane_anomaly", "torn_tail", "warning"): int(point == "append-torn")})
    assert await lane_rows(lane) == boot_rows(2) + torn
    assert await verified()


# --- C-13.6 scenario 13: the audit volume full --------------------------------------------------


def loopback() -> Path:
    """The CI step's fixed-size loopback image: never fill a real disk (#275)."""
    mount = st.LOOP_DIR
    assert mount.is_mount(), f"{mount} is not a mount point; refusing to fill it"
    assert shutil.disk_usage(mount).total <= st.LOOP_MAX_BYTES, f"{mount} is not the chaos image"
    return mount


def fill(path: Path) -> None:
    """Write until ENOSPC: 1 MiB chunks, then 1 KiB ones for what is left."""
    with path.open("wb", buffering=0) as f:
        for size in (1 << 20, 1 << 10):
            with contextlib.suppress(OSError):
                while True:
                    f.write(bytes(size))


async def refused_one(svc: AuditService, tag: str, ids: list[str]) -> str:
    """Sign-outs until one is refused; every one before it was acknowledged, so it is in `ids`."""
    for n in range(len(ids), len(ids) + 2_000):
        object_id = f"{tag}-{n}"
        try:
            await svc.lane.emit("auth.logout", actor_label="owner", object_id=object_id)
        except aw.AuditUnavailable:
            return object_id
        ids.append(object_id)
    raise AssertionError("no sign-out was refused on the full volume")


async def test_s13_full_audit_volume_fails_closed_and_loses_no_acknowledged_record() -> None:
    """The volume fills under the lane and the WAL, so a sign-out is refused by both and its
    caller gets `AuditUnavailable` (fail closed, C-2.9). With room again and a restart, every
    acknowledged one reaches `audit_log` once; the refused one at most once, since its bytes may
    have landed before a failed fsync (an intent without an outcome, §15.6 Crash consistency)."""
    mount, tag, key = loopback(), tag_for("s13"), os.urandom(32)
    audit, ballast = mount / tag, mount / f"{tag}.ballast"
    try:
        async with running(audit, key) as svc:
            ids = await logouts(svc, tag, range(5))
            await drained(svc)
            await asyncio.to_thread(fill, ballast)
            refused = await refused_one(svc, tag, ids)
            ballast.unlink()
        async with running(audit, key) as svc:
            await drained(svc)
        rows = await counts(tag)
        assert {i: rows.get(i) for i in ids} == dict.fromkeys(ids, 1)
        assert set(rows) <= {*ids, refused} and set(rows.values()) == {1}
        assert await verified()
    finally:
        ballast.unlink(missing_ok=True)
        await asyncio.to_thread(shutil.rmtree, audit, True)


# --- AC-LANE-01: a frame tampered between restarts ----------------------------------------------


def alter(lane: Path, object_id: str) -> None:
    """Change one byte of the record `object_id` in its waiting frame; the framing still parses."""
    needle = f'"object_id":"{object_id}"'.encode()
    for segment in sorted(lane.glob("seg-*.lane")):
        data = segment.read_bytes()
        if (at := data.find(needle)) >= 0:
            at += len(needle) - 2  # the id's last character
            segment.write_bytes(data[:at] + bytes([data[at] ^ 0x02]) + data[at + 1 :])
            return
    raise AssertionError(f"no waiting frame holds {object_id}")


async def test_tampered_frame_becomes_one_anomaly_row(tmp_path: Path) -> None:
    """One `frame_rejected` row, the run's bytes in `quarantine/`, the altered record never in
    `audit_log`, the frames after it drained; a second restart writes no second row."""
    tag, key, audit = tag_for("ac01"), os.urandom(32), tmp_path / "audit"
    async with running(audit, key) as svc:
        lane = await drained(svc)
        await svc.writer.stop(5)  # the sink refuses from here, so the frames wait in the lane
        ids = await logouts(svc, tag, range(3))
    alter(audit / "lane", ids[1])
    for _ in range(2):  # the restart, then a second one
        async with running(audit, key) as svc:
            await drained(svc)
    assert await counts(tag) == {ids[0]: 1, ids[2]: 1}
    anomaly = ("audit.lane_anomaly", "frame_rejected", "critical")
    assert await lane_rows(lane) == boot_rows(3) + Counter({anomaly: 1})
    assert len(os.listdir(audit / "lane" / "quarantine")) == 1
    assert await verified()
