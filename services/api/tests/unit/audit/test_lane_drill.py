"""ADR-0037 S4b-2a (#3009): the audit lane's drill, in process (AC-LANE-01, -04 and -09). The real
`AuditService` runs over the in-memory chain: an outage is `writer.stop()` (as
`test_lane_chaos.py`), a restart a stop and a boot on one directory, a backup a copy of `lane/`,
damage an edit of its files between two boots; metrics come from the real exposition, the
journals' clock is a fake. Every test runs on a `VirtualTimeLoop` (`audit_waits`): the drain's
retries and polls are a fake millisecond, never zero; a wait for the drain is `lane.flush()` bounded
by `WAIT_S`, and a stop is bounded by its grace. AC-LANE-04's HTTP half is S3's; AC-LANE-01's
Postgres twin is `tests/chaos/audit/test_lane_chaos.py`."""

from __future__ import annotations

import hashlib
import json
import shutil
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from audit_fakes import FakeAuditRepository
from audit_waits import virtual
from prometheus_client import CollectorRegistry, generate_latest
from prometheus_client.parser import text_string_to_metric_families

from candleviewer.audit import lane_journal as lj
from candleviewer.audit import service
from candleviewer.audit.lane import AuditLane, lane_dir
from candleviewer.audit.metrics import export_audit_lane_metrics
from candleviewer.audit.models import AuditOutcome
from candleviewer.audit.writer import AuditUnavailable, AuditWriter, AuditWriterStopped

KEY = (bytes(range(32)), None)  # a test vector, never a key
WAIT_S, FLOOD = 30.0, 64  # fake seconds: a boot's drain takes a few fake milliseconds
#: A fake millisecond, never zero: the drain parks between its retries and polls, never spins.
FAST: dict[str, Any] = {"retry_s": (0.001, 0.001), "poll_s": 0.001}
SMALL: dict[str, Any] = {"shared_max_bytes": 4096, "lane_max_bytes": 8192}  # a flood fills these
Series = dict[str, dict[tuple[str, ...], float]]  # the exposition: family, label values, value


class Drill:
    """cv-api's audit module on one directory and one chain, restarted as often as a test says.
    `caps` are the lane's byte limits (§15.6 Limits); `now` is its journals' monotonic clock."""

    svc: service.AuditService

    def __init__(self, tmp_path: Path, mp: pytest.MonkeyPatch, **caps: Any) -> None:
        self.repo, self.dir = FakeAuditRepository(), tmp_path / "audit"
        self.lane_dir, self.backup = self.dir / "lane", tmp_path / "backup"
        self.now, self.names = 0.0, dict[str, tuple[str, ...]]()

        def build(wal: str, keys: tuple[bytes, bytes | None], writer: AuditWriter) -> AuditLane:
            files = lj.LaneFiles(lane_dir(wal))
            journal = lj.LaneJournal(files, lj.LaneKeys(*keys), clock=lambda: self.now, **caps)
            return AuditLane(journal, writer, **FAST)

        mp.setattr(service, "build_lane", build)  # the lane `AuditService.start()` builds

    async def boot(self) -> None:
        """Start the audit module: the lane scans, writes its boot row and drains."""
        self.svc = service.AuditService(self.repo, lane_keys=lambda: KEY)
        wal = {"audit_wal_path": str(self.dir / "audit.wal"), "audit_page_structure_budget": 50_000}
        await self.svc.start(cast(Any, SimpleNamespace(settings=SimpleNamespace(**wal))))
        await self.svc.lane.flush(WAIT_S)

    async def stop(self) -> None:
        await self.svc.stop(5)

    async def outage(self, *labels: str) -> None:
        """The sink refuses from here; sign-outs `labels` go to the lane, whose drain retries."""
        await self.svc.writer.stop(5)
        for label in labels:
            await self.put("auth.logout", label)

    async def put(self, action: str, label: str, **kw: Any) -> bool:
        """One record through the façade; False when the lane and the sink both refused it."""
        try:
            await self.svc.lane.emit(action, actor_label="drill", object_id=label, **kw)
        except (AuditUnavailable, AuditWriterStopped):
            return False
        return True

    async def flood(self) -> list[str]:
        """`FLOOD` failed logins, each from an address of its own; the labels the lane kept."""
        kept = list[str]()
        for n in range(FLOOD):
            login = {"actor_ip": f"198.51.100.{n}", "outcome": AuditOutcome.FAILURE}
            if await self.put("auth.login_failed", f"ip-{n}", **login):
                kept.append(f"ip-{n}")
        return kept

    def rows(self, action: str) -> list[dict[str, Any]]:
        return [row for row in self.repo.rows if row["action"] == action]

    def chain(self) -> list[str]:
        """The auth records in `audit_log`, in chain order, by their labels."""
        return [row["object_id"] for row in self.repo.rows if row["action"].startswith("auth.")]

    def scrape(self) -> Series:
        """The lane's families as the real exposition serves them; their label names to `names`."""
        registry, got = CollectorRegistry(), Series()
        export_audit_lane_metrics(registry, env="demo", audit=self.svc)
        for family in text_string_to_metric_families(generate_latest(registry).decode()):
            for s in family.samples:
                labels = {k: v for k, v in s.labels.items() if k != "env"}
                self.names[s.name] = tuple(labels)
                got.setdefault(s.name, {})[tuple(labels.values())] = s.value
        return got

    def save(self) -> None:
        shutil.copytree(self.lane_dir, self.backup)

    def restore(self) -> None:
        shutil.rmtree(self.lane_dir)
        shutil.copytree(self.backup, self.lane_dir)


def after(row: dict[str, Any]) -> Any:
    return json.loads(row["after_state"])


def lit(series: Series, name: str) -> dict[tuple[str, ...], float]:
    """The samples of family `name` that are not zero."""
    return {labels: value for labels, value in series[name].items() if value}


def one(series: Series, name: str) -> float:
    """The value of `cv_audit_lane_<name>`, a family without labels."""
    return series[f"cv_audit_lane_{name}"][()]


def flip(lane: Path, label: str) -> None:
    """Change one bit of a waiting record's label: its frame still parses, its MAC fails."""
    needle = f'"object_id":"{label}"'.encode()
    for segment in sorted(lane.glob("seg-*.lane")):
        data = segment.read_bytes()
        if (at := data.find(needle)) >= 0:
            at += len(needle) - 2  # the label's last character
            segment.write_bytes(data[:at] + bytes([data[at] ^ 0x20]) + data[at + 1 :])
            return
    raise AssertionError(f"no waiting frame holds {label}")


def tear(lane: Path) -> None:
    """Make the newest frame's `len` one more than its body: the frame reads as torn. The frame
    ends with 66 bytes: its body's closing newline and its MAC's line, 65 bytes."""
    segment = sorted(lane.glob("seg-*.lane"))[-1]
    data = segment.read_bytes()
    end = data.rindex(b"\n", 0, len(data) - 66)  # the end of `len`, the last newline before them
    start = data.rfind(b"\n", 0, end) + 1  # the start of `len`
    segment.write_bytes(data[:start] + b"%d" % (int(data[start:end]) + 1) + data[end:])


async def adr_order(d: Drill) -> tuple[list[str], list[Series]]:
    """ADR-0037's drill: an outage with sign-outs around a login flood, a restart, a tampered
    frame, a restart, and an older copy of `lane/`. It returns the logins the lane kept and the
    expositions after the first boot, the flood, the tamper, the restart and the older copy."""
    await d.boot()  # a new lane: frames 1 and 2
    created = d.scrape()
    await d.outage()
    await d.put("auth.logout", "out-1")
    kept = await d.flood()
    await d.put("auth.logout", "out-2")
    d.now = 601.0  # the journals' clock, past AuditLaneBacklogAged's 600 s
    flooded = d.scrape()
    await d.stop()
    d.save()  # the volume's backup, with every journaled frame still waiting
    await d.boot()  # the sink is back: the lane drains
    await d.outage("t-a", "t-b", "t-c")
    await d.stop()
    flip(d.lane_dir, "t-b")
    await d.boot()  # the tampered frame is one anomaly, the rest drain
    tampered = d.scrape()
    await d.stop()
    await d.boot()  # a second restart finds nothing to record
    before = d.scrape()
    await d.stop()
    d.restore()
    await d.boot()  # the lane is the older copy
    d.now = 1202.0  # a frame still waiting would read 601 here: the drained lane reads 0
    return kept, [created, flooded, tampered, before, d.scrape()]


@virtual
async def test_the_drill_in_the_adr_order(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every journaled row reaches `audit_log` once and in order; no refused or altered one does."""
    d = Drill(tmp_path, monkeypatch, **SMALL)
    kept, _ = await adr_order(d)
    await d.stop()
    own = Counter(r["action"] for r in d.repo.rows if r["action"].startswith("audit."))

    assert 0 < len(kept) < FLOOD  # the flood filled its share and no more
    assert d.chain() == ["out-1", *kept, "out-2", "t-a", "t-c"]
    assert own == {"audit.lane_started": 1, "audit.lane_resumed": 5, "audit.lane_anomaly": 1}


@virtual
async def test_ac_lane_04_a_flood_from_many_addresses_leaves_room_for_the_sign_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    d = Drill(tmp_path, monkeypatch, **SMALL)
    await d.boot()
    await d.outage()
    kept = await d.flood()
    signed_out = [await d.put("auth.logout", f"out-{n}") for n in (1, 2)]
    got, lost = d.scrape(), FLOOD - len(kept)
    await d.stop()
    await d.boot()  # the sink is back
    await d.stop()

    assert len(kept) == 6  # six 639-byte frames fill the 4 096-byte share; the docs' figure
    assert signed_out == [True, True]
    assert lit(got, "cv_audit_lane_refused_total") == {("shared", "full"): lost}
    assert lit(got, "cv_audit_writer_refused_total") == {("auth",): lost}  # no reserved row lost
    assert d.chain() == [*kept, "out-1", "out-2"]  # each journaled row once, in order


@virtual
async def test_ac_lane_01_a_tampered_frame_is_one_anomaly_and_the_rest_drain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    d = Drill(tmp_path, monkeypatch)
    await d.boot()
    await d.outage("t-a", "t-b", "t-c")
    await d.stop()
    flip(d.lane_dir, "t-b")
    await d.boot()
    got = d.scrape()
    await d.stop()
    await d.boot()  # a second restart
    await d.stop()
    (row,) = d.rows("audit.lane_anomaly")  # one row after both boots
    (copy,) = (d.lane_dir / "quarantine").iterdir()
    run, digest = after(row), hashlib.sha256(copy.read_bytes()).hexdigest()

    assert (row["reason"], row["severity"]) == ("frame_rejected", "critical")
    assert (copy.name, digest) == (run["quarantined"], run["digest"])  # the run's bytes
    assert got["cv_audit_lane_anomalies_total"][("frame_rejected",)] == 1
    assert one(got, "quarantine_bytes") == copy.stat().st_size
    assert copy.stat().st_size > 0
    assert d.chain() == ["t-a", "t-c"]  # the altered record never reached the chain


@pytest.mark.parametrize(
    ("newer", "head", "restored"), [(["new-1"], 6, 5), ([], 5, 5)], ids=["two_frames", "one_frame"]
)
@virtual
async def test_ac_lane_09_an_older_copy_lowers_the_resumed_head(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, newer: list[str], head: int, restored: int
) -> None:
    """The backup is `len(newer) + 1` frames behind. The resumed row follows its head, lower than
    the lane's either way, but the boot's own frame takes a `seq`: `last_seq` falls from two."""
    d = Drill(tmp_path, monkeypatch)
    await d.boot()
    await d.outage("old-1", "old-2")
    await d.stop()
    d.save()  # the backup's head is frame 4, and both sign-outs still wait in it
    await d.boot()
    for label in newer:
        await d.put("auth.logout", label)
    await d.svc.lane.flush(WAIT_S)
    last_seq = [one(d.scrape(), "last_seq")]  # the lane's head: frame 5, or 6 with `newer`
    rows, tries = len(d.repo.rows), d.repo.insert_attempts
    await d.stop()
    d.restore()
    await d.boot()
    last_seq.append(one(d.scrape(), "last_seq"))
    await d.stop()
    resumed = [after(row)["head_seq"] for row in d.rows("audit.lane_resumed")]

    assert resumed == [1, 4, 4]  # the backup's head, below the lane's, though not below the last
    assert last_seq == [head, restored]  # SeqRegressed's input, as AC-LANE-09 gives it
    assert d.rows("audit.lane_anomaly") == []  # an older copy is authentic: nothing records it
    assert len(d.rows("audit.lane_started")) == 1  # and it is not a new lane
    assert d.chain() == ["old-1", "old-2", *newer]  # the backup's frames drained again, once
    assert (len(d.repo.rows) - rows, d.repo.insert_attempts - tries) == (1, 3)  # +the resumed row


@virtual
async def test_ac_lane_09_a_len_edit_reads_as_torn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The finding: the boot's own frame reuses the torn frame's `seq`, so a one-frame tear leaves
    `last_seq` where it was and `AuditLaneSeqRegressed` silent; `torn_tail` and the lower head in
    the resumed row show it. Only a waiting frame is read: the marker is past a drained one."""
    d = Drill(tmp_path, monkeypatch)
    await d.boot()
    await d.outage("w-1", "w-2", "w-3")
    before = d.scrape()
    await d.stop()
    tear(d.lane_dir)
    await d.boot()
    got = d.scrape()
    await d.stop()
    (row,) = d.rows("audit.lane_anomaly")
    resumed = [after(r)["head_seq"] for r in d.rows("audit.lane_resumed")]

    assert (row["reason"], row["severity"]) == ("torn_tail", "warning")
    assert lit(got, "cv_audit_lane_anomalies_total") == {("torn_tail",): 1}
    assert resumed[-1] < one(before, "last_seq")  # a lower head in the resumed row
    assert d.chain() == ["w-1", "w-2"]  # the torn frame's record never reaches the chain
    assert one(got, "quarantine_bytes") > 0  # its bytes are kept: AuditLaneQuarantineGrowing
    assert one(got, "last_seq") == one(before, "last_seq") == 5


@virtual
async def test_the_series_the_s4a_rules_read_come_out_of_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each lane series the rules of `infra/prometheus/alerts/system_ticket.yml` select comes out of
    the ADR's drill, under the label names they select by. Not drilled: promtool, which stays
    synthetic, and the default registry's `process_start_time_seconds` (the young-process arms)."""
    d = Drill(tmp_path, monkeypatch, **SMALL)
    kept, (new, flooded, tampered, before, rolled) = await adr_order(d)
    await d.stop()
    lost = FLOOD - len(kept)
    names = [d.names[f"cv_audit_lane_{n}"] for n in ("state", "anomalies_total", "refused_total")]

    # AuditSinkRefusing, and AuditLaneRefusing for any reason but `held`: the flood's refusals.
    assert lit(flooded, "cv_audit_writer_refused_total") == {("auth",): lost}
    assert lit(flooded, "cv_audit_lane_refused_total") == {("shared", "full"): lost}
    # AuditLaneRefusing and AuditLaneDrainHeld read `state`; AuditLaneBacklogAged the oldest wait.
    assert flooded["cv_audit_lane_state"] == {("open",): 1, ("held",): 0, ("stopped",): 0}
    assert one(new, "oldest_age_seconds") == 0
    assert one(flooded, "oldest_age_seconds") == 601  # over the rule's 600: the flood waits
    assert one(rolled, "oldest_age_seconds") == 0  # drained, though the clock moved on
    # AuditLaneAnomaly (any reason but `torn_tail`), AuditLaneTornTail, AuditLaneQuarantineGrowing.
    assert lit(tampered, "cv_audit_lane_anomalies_total") == {("frame_rejected",): 1}
    assert ("torn_tail",) in tampered["cv_audit_lane_anomalies_total"]
    assert one(new, "quarantine_bytes") == 0
    assert one(tampered, "quarantine_bytes") > 0
    # AuditLaneCreated: frame 1, once. AuditLaneSeqRegressed: the head falls across the restore.
    assert (one(new, "created_total"), one(rolled, "created_total")) == (1, 0)
    assert one(rolled, "last_seq") < one(before, "last_seq")
    # AuditLaneBootOvershoot: the boot rows fit the cap. The labels the rules select by, by name.
    assert one(rolled, "boot_overshoot_frames_total") == 0
    assert names == [("state",), ("reason",), ("class", "reason")]
