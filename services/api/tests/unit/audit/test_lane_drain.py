"""ADR-0037 S2a2 (#3009): the audit lane's boot and drain (§15.6 Confirmation marker, Scan, Ingest).
The sink is a real `AuditWriter` over the in-memory repository; the drain's file operations run in
threads, so a test waits for a condition, bounded by `WAIT_S`. Keys are test vectors."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import tempfile
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from audit_fakes import FakeAuditRepository, FakeClock
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from candleviewer.audit import actions
from candleviewer.audit import lane_journal as lj
from candleviewer.audit.actions import UnknownAuditAction
from candleviewer.audit.lane import AuditLane
from candleviewer.audit.models import AuditEmission, AuditOutcome, Severity
from candleviewer.audit.redact import REDACTION_MARKER
from candleviewer.audit.writer import AuditUnavailable, AuditWriter, _lane_anomaly

KEYS, LANE, WAIT_S = lj.LaneKeys(bytes(range(32))), uuid.UUID(int=7), 5.0
FAST: dict[str, Any] = {"retry_s": (0.0, 0.0), "poll_s": 0.0, "new_lane": lambda: LANE}
SLOW: dict[str, Any] = {"retry_s": (3600.0, 3600.0)}  # only an append or a boot retries
OWN = ("system:audit-lane", "audit_lane", str(LANE))  # actor_label, object_kind, object_id


class Refusing(AuditWriter):
    """The sink: an `AuditWriter` that refuses its next `refuse` ingests (`AuditUnavailable`)."""

    refuse = 0

    async def ingest(self, record: AuditEmission | dict[str, Any]) -> int:
        if self.refuse:
            self.refuse -= 1
            raise AuditUnavailable("the sink refuses")
        return await super().ingest(record)


async def sink[W: AuditWriter](path: Path, repo: FakeAuditRepository, cls: type[W]) -> W:
    writer = cls(repo, str(path / "audit.wal"), clock=FakeClock(), sleep=repo.retry_sleep)
    await writer.start()
    return writer


def lane_of(path: Path, writer: AuditWriter, **kw: Any) -> AuditLane:
    return AuditLane(lj.LaneJournal(lj.LaneFiles(path / "lane"), KEYS), writer, **(FAST | kw))


async def boot(path: Path, writer: AuditWriter, **kw: Any) -> AuditLane:
    lane = lane_of(path, writer, **kw)
    await lane.start()
    return lane


async def until(check: Callable[[], bool]) -> None:
    """A condition wait, bounded by `WAIT_S`."""
    async with asyncio.timeout(WAIT_S):
        while not check():  # noqa: ASYNC110 - polls state the drain task moves; no event for it
            await asyncio.sleep(0)


async def drained(lane: AuditLane) -> None:
    """Every unit the journal counted is confirmed."""
    await until(lambda: lane.confirmed == lane.journal.end)


async def stopped(writer: AuditWriter) -> None:
    await writer.flush(WAIT_S)
    await writer.stop(1)


def logout(writer: AuditWriter, n: int) -> AuditEmission:
    return writer.build("auth.logout", actor_label="owner", object_id=str(n))


def frames(path: Path) -> list[lj.Handover]:
    """The authentic frames on disk, whatever the marker says."""
    found = lj.scan(
        KEYS, marker=None, names=os.listdir(path), read=lambda n: (path / n).read_bytes()
    )
    return [unit for unit in found.units if isinstance(unit, lj.Handover)]


def after(row: dict[str, Any]) -> Any:
    return None if row["after_state"] is None else json.loads(row["after_state"])


def segments(path: Path) -> list[str]:
    return sorted(name for name in os.listdir(path) if name.startswith("seg-"))


async def test_resumed_row_records_the_head(tmp_path: Path) -> None:
    """A new lane's frame 1 is `audit.lane_started`, and each boot appends `audit.lane_resumed`
    with the head its frame follows, so a lane restored from an older copy shows a lower head (U37,
    AC-LANE-09's chain half). The drain hands their records over and compacts what it passed."""
    repo, path, first, heads = FakeAuditRepository(), tmp_path / "lane", list[lj.Handover](), []
    writer = await sink(tmp_path, repo, AuditWriter)
    for step in ("copy", "restore", "boot"):
        lane = await boot(tmp_path, writer)
        first = first or frames(path)  # frames 1 and 2, as the first boot wrote them
        if step != "boot":
            await lane.append(logout(writer, len(heads)))
        await drained(lane)
        heads.append(lane.journal.head)
        await lane.close()
        if step == "copy":
            shutil.copytree(path, tmp_path / "copy")
        elif step == "restore":
            shutil.rmtree(path)
            shutil.copytree(tmp_path / "copy", path)
    await stopped(writer)
    own = [r for r in repo.rows if r["action"].startswith("audit.lane_")]
    one, three = (
        {"head_seq": n, "head_mac": m, "anchored": True}
        for n, m in ((1, first[0].frame.mac), (3, heads[0][1]))
    )

    assert [(r["action"], r["severity"], after(r)) for r in own] == [
        ("audit.lane_started", "warning", None),
        ("audit.lane_resumed", "info", one),
        *[("audit.lane_resumed", "info", three)] * 2,
    ]
    assert {(r["actor_label"], r["object_kind"], r["object_id"], r["outcome"]) for r in own} == {
        (*OWN, "success")
    }
    assert [r["record_id"] for r in own[:2]] == [f.frame.rec["record_id"] for f in first]
    assert heads[1][0] == 5 and segments(path) == [lj.segment_name(4)]


async def refusals(path: Path, steps: list[tuple[str, int]]) -> None:
    repo = FakeAuditRepository()
    writer = await sink(path, repo, Refusing)
    lane, ids = await boot(path, writer, **SLOW), list[str]()
    expected = ["audit.lane_started", "audit.lane_resumed"]
    for op, n in [*steps, ("", 0)]:  # the last append comes with a sink that accepts
        if op == "r":
            writer.refuse = n
        elif op == "x":
            await lane.close()
            lane = await boot(path, writer, **SLOW)
            expected.append("audit.lane_resumed")
        else:
            writer.refuse = writer.refuse if op else 0
            record = logout(writer, len(ids))
            await lane.append(record)
            ids.append(str(record.record_id))
            expected.append("auth.logout")
    await drained(lane)
    await lane.close()
    await stopped(writer)

    assert [r["action"] for r in repo.rows] == expected
    assert [r["record_id"] for r in repo.rows if r["action"] == "auth.logout"] == ids


@settings(
    max_examples=40, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(st.lists(st.tuples(st.sampled_from("aaarx"), st.integers(1, 4)), max_size=12))
def test_lane_hands_each_record_over_once_and_in_order_across_refusals_and_restarts(
    tmp_path: Path, steps: list[tuple[str, int]]
) -> None:
    """The S2a2 row: a sink that refuses N times ("r"), restarts of the lane ("x") and appends
    ("a"), in any order; once the sink accepts, it holds every frame's record once, in `seq`
    order, each boot's `audit.lane_resumed` after the records journaled before that boot."""
    asyncio.run(refusals(Path(tempfile.mkdtemp(dir=tmp_path)), steps))


@pytest.mark.parametrize("poison", ["retired_action", "invalid_record"])
async def test_poison_frame_is_quarantined_and_passed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, poison: str
) -> None:
    """U44 and AC-LANE-08: an authentic frame in sequence that `ingest()` refuses for good (its
    action retired, or a record that is not an `AuditEmission`) gets one `record_invalid` row,
    its bytes go to `quarantine/`, the next frame is handed over, and its record is not stored."""
    repo, path, secret = FakeAuditRepository(), tmp_path / "lane", "do-not-store"
    writer = await sink(tmp_path, repo, AuditWriter)
    lane = await boot(tmp_path, writer)
    if poison == "retired_action":
        record = writer.build("auth.session_revoked", actor_label=secret)  # registered when built
        monkeypatch.setattr(actions, "AUDIT_ACTIONS", actions.AUDIT_ACTIONS - {record.action})
        await lane.append(record)
    else:
        await lane.journal.append(
            {"action": "auth.logout", "outcome": "success", "password": secret}
        )
    good = logout(writer, 1)
    await lane.append(good)
    await drained(lane)
    await lane.close()
    await stopped(writer)
    run = lj.record_invalid(frames(path)[2])
    row = repo.rows[2]

    assert [r["action"] for r in repo.rows[2:]] == ["audit.lane_anomaly", "auth.logout"]
    assert (row["record_id"], row["reason"], row["severity"], row["outcome"]) == (
        str(lj.anomaly_id(KEYS, LANE, run)), "record_invalid", "critical", "failure"
    )  # fmt: skip
    assert after(row) == {
        "from_seq": 3, "to_seq": 3, "bytes": len(run.data), "quarantined": run.quarantined,
        "digest": hashlib.sha256(run.data).hexdigest(), "prev_unverified": False,
        "marker_behind": False, "marker_ahead": False,
    }  # fmt: skip
    assert (path / "quarantine" / str(run.quarantined)).read_bytes() == run.data
    assert repo.rows[3]["record_id"] == str(good.record_id) and secret not in repr(repo.rows)


async def test_lane_anomaly_rows_carry_the_run_id_and_pass_the_validation_of_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ingest step 1: each run is one `audit.lane_anomaly` row, critical but a torn tail's warning,
    under the run's keyed `record_id`. The builder is `build()` with that id: the same fields, the
    same action check and the same redaction (#3009's S2a1 security note)."""
    repo, path = FakeAuditRepository(), tmp_path / "lane"
    writer = await sink(tmp_path, repo, Refusing)
    writer.refuse = 10**6  # nothing reaches the sink, so nothing is confirmed
    lane = await boot(tmp_path, writer, **SLOW)
    for n in (1, 2, 3):
        await lane.append(logout(writer, n))
    await lane.close()
    f, seg = frames(path), path / lj.segment_name(1)
    tampered = f[2].raw.replace(b'"object_id":"1"', b'"object_id":"9"')  # frame 3's MAC fails
    seg.write_bytes(seg.read_bytes().replace(f[2].raw, tampered)[: f[4].start[1] + 40])
    writer.refuse = 0
    lane = lane_of(tmp_path, writer)
    runs = [u for u in (await lane.start()).units if isinstance(u, lj.Run)]
    await drained(lane)
    await lane.close()
    await stopped(writer)
    rows = [r for r in repo.rows if r["action"] == "audit.lane_anomaly"]

    assert [(r.reason, r.from_seq, r.to_seq, r.prev_unverified) for r in runs] == [
        ("frame_rejected", 3, 3, True),
        ("torn_tail", 5, None, False),
    ]
    assert [(r["record_id"], r["reason"], r["severity"], r["object_id"]) for r in rows] == [
        (str(lj.anomaly_id(KEYS, LANE, runs[0])), "frame_rejected", "critical", str(LANE)),
        (str(lj.anomaly_id(KEYS, LANE, runs[1])), "torn_tail", "warning", str(LANE)),
    ]
    assert [after(r)["prev_unverified"] for r in rows] == [True, False]
    fields: dict[str, Any] = {"reason": "seq_gap", "severity": Severity.CRITICAL}
    states = {"after_state": {"token": "s3cret", "n": 1}}
    row = _lane_anomaly(writer, uuid.UUID(int=9), lane=LANE, **fields, **states)
    built = writer.build(
        "audit.lane_anomaly", actor_label=OWN[0], object_kind=OWN[1], object_id=OWN[2],
        outcome=AuditOutcome.FAILURE, **fields, **states,
    )  # fmt: skip
    same = {"record_id", "event_ts"}
    assert row.record_id == uuid.UUID(int=9)
    assert row.after_state == {"token": REDACTION_MARKER, "n": 1}
    assert row.model_dump(exclude=same) == built.model_dump(exclude=same)
    monkeypatch.setattr(actions, "AUDIT_ACTIONS", actions.AUDIT_ACTIONS - {"audit.lane_anomaly"})
    with pytest.raises(UnknownAuditAction):
        _lane_anomaly(writer, uuid.UUID(int=9), lane=LANE, **fields, **states)


class Gated(FakeAuditRepository):
    """Holds each insert until the test lets one through, once `gate` is set."""

    gate: asyncio.Semaphore | None = None

    async def insert(self, record: dict[str, Any]) -> None:
        if self.gate is not None:
            await self.gate.acquire()
        await super().insert(record)


async def test_lane_busy_writer_still_confirms_per_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ingest step 3: the marker moves past each record once the writer reports its token
    committed, one record at a time and never ahead of `audit_log`, while the writer still has
    records to flush and so never goes idle."""
    repo = Gated()
    writer = await sink(tmp_path, repo, AuditWriter)
    lane = await boot(tmp_path, writer)
    await drained(lane)
    await writer.flush(WAIT_S)  # the boot's two records are in, so the writer has none waiting
    marks, confirm, repo.gate = (
        list[tuple[lj.Pos, int, bool]](),
        lane.journal.confirm,
        asyncio.Semaphore(0),
    )

    async def spy(marker: lj.LaneMarker) -> None:
        marks.append((marker.pos, len(repo.rows), writer.buffer_depth > 0))
        await confirm(marker)

    monkeypatch.setattr(lane.journal, "confirm", spy)
    await writer.ingest(writer.build("auth.login", actor_label="another"))  # not the lane's
    ends = []
    for n in range(3):
        await lane.append(logout(writer, n))
        ends.append(lane.journal.end)
    await until(lambda: writer.buffer_depth == 4)  # the drain handed the three over
    for want in [lane.confirmed, *ends]:
        repo.gate.release()
        await until(lambda want=want: lane.confirmed == want and len(repo.rows) == 3 + len(marks))
    await lane.close()
    await stopped(writer)

    assert [(pos, stored) for pos, stored, _ in marks] == [(ends[0], 4), (ends[1], 5), (ends[2], 6)]
    assert [busy for _, _, busy in marks[:2]] == [True, True]


async def test_lane_retries_after_0_5_s_doubling_to_30_s_or_when_an_append_wakes_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ingest step 2: a transient refusal ends the batch, and the drain retries after 0.5 s,
    doubling to 30 s, starting again at 0.5 s after a batch it handed over; an append wakes a
    drain that is backing off."""
    repo, delays, pause = FakeAuditRepository(), list[float | None](), AuditLane._pause
    writer = await sink(tmp_path, repo, Refusing)

    async def recorded(self: AuditLane, delay: float | None) -> None:
        delays.append(delay)
        await (pause(self, delay) if delay is None else asyncio.sleep(0))

    monkeypatch.setattr(AuditLane, "_pause", recorded)
    writer.refuse = 9
    lane = await boot(tmp_path, writer, retry_s=(0.5, 30.0), poll_s=0.001)
    await drained(lane)
    writer.refuse = 1
    await lane.append(logout(writer, 1))
    await drained(lane)
    await lane.close()
    monkeypatch.setattr(AuditLane, "_pause", pause)
    writer.refuse = 1
    lane = await boot(tmp_path, writer, **SLOW)  # its first hand-over is refused: an hour's wait
    await until(lambda: writer.refuse == 0)
    await lane.append(logout(writer, 2))
    await drained(lane)
    await lane.close()
    await stopped(writer)

    assert [d for d in delays if d not in (0.001, None)] == [0.5, 1, 2, 4, 8, 16, 30, 30, 30, 0.5]
    assert [r["object_id"] for r in repo.rows if r["action"] == "auth.logout"] == ["1", "2"]


async def test_lane_attempts_a_confirmation_after_each_batch_of_drain_batch_units(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ingest: `DRAIN_BATCH` units per batch (2 here), a confirmation attempt after each one."""
    repo, path = FakeAuditRepository(), tmp_path / "lane"
    writer = await sink(tmp_path, repo, Refusing)
    writer.refuse = 10**6
    lane = await boot(tmp_path, writer, **SLOW)
    for n in range(3):
        await lane.append(logout(writer, n))  # five frames wait: the boot's two and three more
    await lane.close()
    ends, marks, writer.refuse = [u.end for u in frames(path)], list[lj.Pos](), 0
    lane = lane_of(tmp_path, writer, batch=2)
    confirm = lane.journal.confirm

    async def spy(marker: lj.LaneMarker) -> None:
        marks.append(marker.pos)
        await confirm(marker)

    monkeypatch.setattr(lane.journal, "confirm", spy)
    monkeypatch.setattr(writer, "committed_through", lambda: 10**6)  # a batch commits at once
    await lane.start()
    await drained(lane)
    await lane.close()
    await stopped(writer)

    assert marks == [ends[1], ends[3], ends[4], lane.journal.end]


async def test_lane_running_scan_parses_nothing_before_its_origin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A running scan starts at the drain's own position, a unit end it scanned, and parses nothing
    before it, so the drain's scans grow with what it has not seen, not with the segment."""
    journal = lj.LaneJournal(lj.LaneFiles(tmp_path), KEYS)
    await journal.open(lambda: LANE)
    await journal.append({"action": "audit.lane_started", "outcome": "success"})
    origin = lj.LaneMarker(LANE, journal.end, 2, journal.head[1], True)
    await journal.append({"action": "auth.logout", "outcome": "success"})

    def reparsed(data: bytes, offset: int) -> bool:
        raise AssertionError("the running scan parsed the bytes before its origin")

    monkeypatch.setattr(lj, "_at_boundary", reparsed)
    result = await journal.rescan(origin)
    await journal.close()

    assert [(type(u), u.end) for u in result.units] == [(lj.Handover, journal.end)]
