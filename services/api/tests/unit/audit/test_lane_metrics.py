"""ADR-0037 S4a (#3009): the audit lane's and the writer's metrics. Each test pins one family's
rule: what the writer, the lane or its façade counts in memory, and what the scrape serves from it
(`env` added, every closed label value from the start, the lane's gauges only with a lane). The
sink is a real `AuditWriter` over the in-memory repository; files only in `tmp_path`; keys are test
vectors; the journal's clock is a fake. Every async test runs on a `VirtualTimeLoop` (`audit_waits`,
#3709, #3816): the drain's polls and backoffs, the lane's and the writer's budgets and `until()`'s
bound are fake seconds, which pass only when nothing else can happen, so no wait depends on how
fast the runner is."""

from __future__ import annotations

import asyncio
import errno
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from audit_fakes import FakeAuditRepository, FakeClock
from audit_waits import TaskEnded, VirtualTimeLoop, virtual
from prometheus_client import CollectorRegistry, Gauge, generate_latest
from prometheus_client.parser import text_string_to_metric_families
from structlog.testing import capture_logs

from candleviewer.app import create_app
from candleviewer.audit import lane_journal as lj
from candleviewer.audit import writer as aw
from candleviewer.audit.lane import REFUSALS, AuditLane, LaneFacade
from candleviewer.audit.metrics import EXPORTED_NAMES, export_audit_lane_metrics, lane_families
from candleviewer.audit.models import AuditEmission
from candleviewer.audit.service import AuditService
from candleviewer.audit.writer import AUDIT_DOMAINS, AuditUnavailable, AuditWriter
from candleviewer.observability.metrics import MetricsError, ScrapeCollector, ScrapedFamily
from candleviewer.observability.metrics_catalogue import CATALOGUE
from candleviewer.settings import Environment, Settings

#: WAIT_S is fake seconds: past every wait a test here makes, which takes a few fake milliseconds.
KEYS, RAW, WAIT_S = lj.LaneKeys(bytes(range(32))), (bytes(range(32)), None), 600.0
OTHER = lj.LaneKeys(bytes(range(32, 64)))  # a key the lane is not configured with
#: A fake millisecond: the drain parks between polls and retries instead of spinning.
FAST: dict[str, Any] = {"retry_s": (0.001, 0.001), "poll_s": 0.001}
WORKERS = ("audit-writer", "audit-lane-drain")  # the flusher's and the drain's task names
GAUGES = {"depth", "bytes", "oldest_age_seconds", "quarantine_bytes", "state", "last_seq"}


class Lane:  # an `AuditLane` stand-in for the façade: it raises `error`, or never answers
    def __init__(self, error: Exception | None) -> None:
        self.error = error

    async def append(self, record: AuditEmission) -> int:
        if self.error is None:
            await asyncio.Event().wait()
        raise cast(Exception, self.error)


class Broken(lj.LaneFiles):  # its marker write fails after the first (a new lane's own)
    marks = 0

    def mark(self, body: bytes, *rest: Any) -> None:
        self.marks += 1
        if self.marks > 1:
            raise OSError(errno.EIO, "marker write failed")
        super().mark(body, *rest)


class FailingAppend(lj.LaneFiles):  # once armed, a frame's write into its open segment fails
    armed = False

    def append(self, fd: int, frame: bytes, end: int) -> None:
        if self.armed:
            raise OSError(errno.EIO, "append failed")
        super().append(fd, frame, end)


class Parts:  # what `lane_families` reads of an `AuditService`: its parts and two boot counts
    lane_lock_failures = lane_link_failures = 0

    def __init__(self, writer: AuditWriter | None, lane: AuditLane) -> None:
        self.parts = (writer, lane, None)

    def lane_parts(self) -> tuple[Any, ...]:
        return self.parts


def families(parts: Parts) -> dict[str, dict[tuple[str, ...], float]]:
    """`lane_families` over `parts`, by name: each sample's label values and value."""
    read = lane_families(cast(AuditService, parts))
    return {family.name: dict(family.samples) for family in read}


async def sink(path: Path, repo: FakeAuditRepository, **kw: Any) -> AuditWriter:
    writer = AuditWriter(repo, str(path / "w.wal"), clock=FakeClock(), sleep=repo.retry_sleep, **kw)
    await writer.start()
    return writer


async def boot(path: Path, writer: AuditWriter, now: list[float] | None = None) -> AuditLane:
    """A lane whose journal reads `now[0]` as its monotonic clock; `start()`, unless `now` is []."""
    t = now or [100.0]
    journal = lj.LaneJournal(lj.LaneFiles(path / "lane"), KEYS, clock=lambda: t[0])
    lane = AuditLane(journal, writer, **FAST)
    if now != []:
        await lane.start()
    return lane


def workers() -> list[asyncio.Task[Any]]:
    """The running flushers and drains, whose death `until()` watches."""
    return [task for task in asyncio.all_tasks() if task.get_name() in WORKERS]


def failed(task: asyncio.Task[Any]) -> bool:
    return task.done() and not task.cancelled() and task.exception() is not None


async def until(check: Callable[[], bool]) -> None:
    """Wait until `check()` holds, looking again at each point where nothing is ready. A flusher
    or drain that dies meanwhile fails it at once, unless its death is what `check()` waits for.
    A stall fails it after `WAIT_S` fake seconds, naming the flushers and drains that had died by
    then, before the wait too, with the last one's error as the cause (as `test_lane_drain`'s)."""
    loop = asyncio.get_running_loop()
    assert isinstance(loop, VirtualTimeLoop), "an async test here runs on a VirtualTimeLoop"
    try:
        async with asyncio.timeout(WAIT_S):
            while not check():
                watched = workers()
                await loop.idle(*watched)
                died = [task for task in watched if failed(task)]
                if died and not check():
                    cause = died[0].exception()
                    raise TaskEnded(f"{died[0].get_name()} ended before the condition") from cause
    except TimeoutError:
        dead = [task for task in loop.made if task.get_name() in WORKERS and failed(task)]
        stalled = f"stalled: still false after {WAIT_S:g} fake seconds"
        if dead:
            names = ", ".join(task.get_name() for task in dead)
            raise TaskEnded(f"{stalled}; had died: {names}") from dead[-1].exception()
        raise AssertionError(stalled) from None


def served(registry: CollectorRegistry) -> dict[str, dict[tuple[str, ...], float]]:
    out: dict[str, dict[tuple[str, ...], float]] = {}
    for family in text_string_to_metric_families(generate_latest(registry).decode()):
        for s in family.samples:  # `env` first, then the other labels as served
            rest = (value for name, value in s.labels.items() if name != "env")
            out.setdefault(s.name, {})[(s.labels["env"], *rest)] = s.value
    return out


def one(value: float, *labels: str) -> dict[tuple[str, ...], float]:
    return {("demo", *labels): value}


@virtual
async def test_journal_counts_frames_by_class_and_its_backlog_until_the_drain_confirms(
    tmp_path: Path, repo: FakeAuditRepository
) -> None:
    now, writer = [100.0], await sink(tmp_path, repo)
    repo.down = True  # nothing commits, so nothing is confirmed
    lane = await boot(tmp_path, writer, now)  # frames 1 and 2, both `reserved`
    journal, before = lane.journal, sum(lane.journal.class_bytes)
    now[0] += 7
    await lane.append(writer.build("auth.login", actor_label="owner"))  # `shared`
    assert journal.appended == {"reserved": 2, "shared": 1}
    assert (journal.created, journal.depth) == (1, 3)
    assert journal.class_bytes == (before, sum(journal.class_bytes) - before)
    assert sum(journal.class_bytes) == (tmp_path / "lane" / lj.segment_name(1)).stat().st_size
    assert (journal.oldest_age(), lane.drained) == (7.0, 0)
    repo.down = False
    await lane.flush(WAIT_S)
    assert (journal.depth, journal.class_bytes, journal.oldest_age()) == (0, (0, 0), 0.0)
    assert lane.drained == 3
    await lane.close()
    again = await boot(tmp_path, writer)  # a restart: its resumed row, no new lane
    assert (again.journal.created, again.journal.appended) == (0, {"reserved": 1, "shared": 0})
    await again.close()


def test_quarantine_size_counts_a_replaced_copy_once_and_no_link(tmp_path: Path) -> None:
    files = lj.LaneFiles(tmp_path)
    assert files.quarantined() == 0  # no `quarantine/` yet
    assert (files.quarantine("a.0", b"abc"), files.quarantine("a.0", b"abcde")) == (3, 2)
    assert files.quarantine("b.9", b"xy") == 2
    (tmp_path / "quarantine" / "link").symlink_to(tmp_path / "quarantine" / "b.9")
    assert files.quarantined() == 7  # a link is not a copy


@virtual
async def test_a_linked_quarantine_holds_at_boot(tmp_path: Path, repo: FakeAuditRepository) -> None:
    (tmp_path / "lane").mkdir()
    (tmp_path / "elsewhere").mkdir()
    (tmp_path / "lane" / "quarantine").symlink_to(tmp_path / "elsewhere")
    lane = await boot(tmp_path, await sink(tmp_path, repo), [])
    with pytest.raises(OSError) as raised:  # `O_NOFOLLOW | O_DIRECTORY` on a link
        await lane.start()
    assert raised.value.errno in (errno.ELOOP, errno.ENOTDIR) and lane.journal.refusal == "held"


@virtual
async def test_drain_counts_anomalies_by_reason(tmp_path: Path, repo: FakeAuditRepository) -> None:
    writer = await sink(tmp_path, repo)
    lane = await boot(tmp_path, writer)
    await lane.journal.append({"action": "auth.logout", "outcome": "success"})  # no AuditEmission
    await lane.append(writer.build("auth.logout", actor_label="owner"))
    await lane.flush(WAIT_S)
    (copy,) = (tmp_path / "lane" / "quarantine").iterdir()
    assert lane.anomalies == dict.fromkeys(lj.ANOMALY_REASONS, 0) | {"record_invalid": 1}
    assert lane.journal.quarantine_bytes == copy.stat().st_size > 0
    assert lane.drained == 4  # two boot rows, the poison frame's row, the sign-out
    await lane.close()


@virtual
async def test_drain_counts_a_hold_it_meets(tmp_path: Path, repo: FakeAuditRepository) -> None:
    lane = await boot(tmp_path, await sink(tmp_path, repo))
    journal, (seq, prev) = lane.journal, lane.journal.head
    frame = lj.encode_frame(OTHER, lane=journal.lane, seq=seq + 1, prev=prev, cls="shared", rec={})
    with (tmp_path / "lane" / lj.segment_name(1)).open("ab") as segment:
        segment.write(frame)  # a frame under a key id the lane does not know: row 12
    lane._dirty = True  # as an append would: the drain scans again
    lane._wake.set()
    await until(lambda: journal.refusal == "held")
    assert lane.drain_failures == {"held": 1, "stopped": 0}
    await lane.close()


@virtual
async def test_drain_counts_its_death(tmp_path: Path, repo: FakeAuditRepository) -> None:
    journal = lj.LaneJournal(Broken(tmp_path / "lane"), KEYS)
    lane = AuditLane(journal, await sink(tmp_path, repo), **FAST)
    await lane.start()  # the drain's first marker write fails: it dies, the lane stops
    await until(lambda: lane.drain_failures["stopped"] == 1)
    assert lane.drain_failures == {"held": 0, "stopped": 1} and journal.refusal == "stopped"
    await lane.close()


@pytest.mark.parametrize(("action", "cls"), [("auth.logout", "reserved"), ("auth.login", "shared")])
@virtual
async def test_facade_counts_each_fallback_by_class_and_reason(
    tmp_path: Path, repo: FakeAuditRepository, action: str, cls: str
) -> None:
    writer = await sink(tmp_path, repo)
    for reason in REFUSALS:
        error = None if reason == "timeout" else lj.LaneRefused(cast(lj.LaneReason, reason))
        facade = LaneFacade(writer, cast(AuditLane, Lane(error)), lambda: True, wait_s=0)
        await facade.emit(action, actor_label="owner")
        assert facade.refused == {key: int(key == (cls, reason)) for key in facade.refused}


@virtual
async def test_writer_counts_the_refusals_its_callers_see_by_the_actions_domain(
    tmp_path: Path, repo: FakeAuditRepository
) -> None:
    writer = await sink(tmp_path, repo, max_wal_bytes=600)
    with pytest.raises(AuditUnavailable):  # a record the WAL's cap cannot take
        await writer.emit("users.create", actor_label="owner", after_state={"pad": "x" * 600})
    facade = LaneFacade(writer, cast(AuditLane, Lane(lj.LaneRefused("full"))), lambda: True)
    await writer.stop(1)
    for action in ("auth.logout", "no.such_action"):  # refused before the action is checked
        with pytest.raises(aw.AuditWriterStopped):
            await writer.emit(action, actor_label="owner")
    with pytest.raises(aw.AuditWriterStopped):  # the façade's fallback, refused too
        await facade.emit("auth.logout", actor_label="owner")
    counts = {"users": 1, "auth": 2, "other": 1}
    assert writer.refused_by_domain == dict.fromkeys(AUDIT_DOMAINS, 0) | counts


@virtual
async def test_writer_does_not_count_the_drains_own_refusals(
    tmp_path: Path, repo: FakeAuditRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    writer, tries = await sink(tmp_path, repo), list[str]()

    async def refusing(record: dict[str, Any]) -> int:  # the drain hands over, is refused, retries
        tries.append(record["action"])
        raise AuditUnavailable("the sink refuses")

    monkeypatch.setattr(writer, "ingest", refusing)
    lane = await boot(tmp_path, writer)
    await until(lambda: len(tries) >= 3)
    assert set(writer.refused_by_domain.values()) == {0} and lane.drained == 0
    await lane.close()


def test_catalogue_declares_every_served_family_and_bounds_it_by_its_closed_sets() -> None:
    specs = {s.name: s for s in CATALOGUE if s.name in EXPORTED_NAMES}
    families = lane_families(AuditService())  # unwired: no lane, no gauges
    names = {f.name for f in families}
    assert names == EXPORTED_NAMES - {f"cv_audit_lane_{g}" for g in GAUGES} and len(specs) == 17
    assert all(s.exported and (s.status, s.owner_epic) == ("live", "E09") for s in specs.values())
    for family in families:
        assert family.labels == specs[family.name].labels
        assert family.samples and len({v for v, _ in family.samples}) == len(family.samples)
    bounds = {"cv_audit_writer_refused_total": len(AUDIT_DOMAINS), "cv_audit_lane_state": 3}
    bounds |= {"cv_audit_lane_refused_total": 2 * len(REFUSALS), "cv_audit_lane_bytes": 2}
    bounds |= {"cv_audit_lane_anomalies_total": len(lj.ANOMALY_REASONS)}
    assert {name: specs[name].max_series for name in bounds} == bounds


@virtual
async def test_the_scrape_serves_each_family_with_env_and_the_lanes_gauges_once_it_runs(
    tmp_path: Path, repo: FakeAuditRepository
) -> None:
    registry, audit = CollectorRegistry(), AuditService(repo, lane_keys=lambda: RAW)
    col = export_audit_lane_metrics(registry, env="demo", audit=audit)
    unwired = served(registry)
    assert unwired["cv_audit_writer_refused_total"] == {("demo", d): 0.0 for d in AUDIT_DOMAINS}
    assert not {f"cv_audit_lane_{g}" for g in GAUGES} & set(unwired)
    await audit.start(cast(Any, SimpleNamespace(settings=SimpleNamespace(
        audit_wal_path=str(tmp_path / "audit" / "a.wal"), audit_page_structure_budget=50_000,
    ))))  # fmt: skip
    writer, lane, facade = audit.lane_parts()
    assert writer is not None and lane is not None and facade is not None
    await lane.flush(WAIT_S)
    lane.paused_batches, lane.journal.boot_overshoot_frames, audit.lane_lock_failures = 3, 2, 4
    audit.lane_link_failures = 6
    lane.anomalies["seq_gap"], lane.drain_failures["held"] = 5, 6
    facade.refused["shared", "busy"], lane.journal.quarantine_bytes = 7, 9
    writer._refused_by_domain["auth"], lane.journal._bytes, lane.journal._shared = 8, 12, 5
    got = await asyncio.to_thread(served, registry)  # the scrape's own thread
    assert got["cv_audit_lane_state"] == one(1.0, "open") | one(0.0, "held") | one(0.0, "stopped")
    assert got["cv_audit_lane_bytes"] == one(7.0, "reserved") | one(5.0, "shared")
    assert got["cv_audit_lane_appended_total"] == one(2.0, "reserved") | one(0.0, "shared")
    for name, value in {
        "created_total": 1, "oldest_age_seconds": 0, "paused_batches_total": 3, "depth": 0,
        "boot_overshoot_frames_total": 2, "lock_failures_total": 4, "quarantine_bytes": 9,
        "link_failures_total": 6,
        "last_seq": 2, "drained_total": 2,
    }.items():  # fmt: skip
        assert got[f"cv_audit_lane_{name}"] == one(float(value)), name
    assert got["cv_audit_lane_anomalies_total"][("demo", "seq_gap")] == 5.0
    assert got["cv_audit_lane_drain_failures_total"][("demo", "held")] == 6.0
    assert got["cv_audit_lane_refused_total"][("demo", "shared", "busy")] == 7.0
    assert got["cv_audit_writer_refused_total"][("demo", "auth")] == 8.0
    lane.journal.hold()
    held = served(registry)
    assert held["cv_audit_lane_state"][("demo", "held")] == 1.0
    assert "cv_audit_lane_last_seq" not in held  # its head is read only up to the hold
    await audit.stop(1)
    col.close()
    assert served(registry) == {}


def test_create_app_serves_the_lane_families_and_no_flag_gauge() -> None:
    scraped = served(create_app(Settings(environment=Environment.DEMO)).state.app_context.metrics)
    assert "cv_audit_lane_journal_first" not in scraped  # the flag gauge is gone (#3009 S4b)
    assert len(scraped["cv_audit_writer_refused_total"]) == len(AUDIT_DOMAINS)


def test_a_scraped_family_must_be_a_counter_or_gauge_with_allowed_labels() -> None:
    def read(labels: tuple[str, ...], kind: str) -> Any:
        return lambda: [ScrapedFamily("cv_x_total", cast(Any, kind), "h", labels, ())]

    with pytest.raises(MetricsError, match="disallowed"):
        ScrapeCollector(CollectorRegistry(), env="demo", read=read(("user_id",), "counter"))
    with pytest.raises(MetricsError, match="counter or a gauge"):
        ScrapeCollector(CollectorRegistry(), env="demo", read=read((), "histogram"))


def test_a_read_that_fails_at_the_scrape_drops_its_families_and_nothing_else() -> None:
    """SR-S4A1-01: a read that raises serves none of its families, and logs the error's class once
    until a read succeeds again; every other family on the registry is still served."""
    registry, reads = CollectorRegistry(), iter([True, False, False, True, False])
    Gauge("cv_other", "another family", ["env"], registry=registry).labels("demo").set(3)

    def read() -> list[ScrapedFamily]:  # construction's read, then one per scrape
        if not next(reads):
            raise KeyError("a read that fails")
        return [ScrapedFamily("cv_x_total", "counter", "h", (), (((), 1.0),))]

    ScrapeCollector(registry, env="demo", read=read)
    with capture_logs() as logs:
        got = [served(registry) for _ in range(4)]
    other, mine = {"cv_other": one(3.0)}, {"cv_x_total": one(1.0)}

    assert got == [other, other, other | mine, other]
    assert [entry for entry in logs if entry["event"] == "metrics.scrape_read_failed"] == [
        {"event": "metrics.scrape_read_failed", "log_level": "error", "error": "KeyError"}
    ] * 2


def test_a_scraped_sample_has_one_value_per_label() -> None:
    """S4a1-N5: prometheus_client zips a sample's values with the labels and drops the rest, so a
    family whose sample does not match its labels is refused at construction."""
    family = ScrapedFamily("cv_x_total", "counter", "h", ("class",), ((("a", "b"), 1.0),))
    with pytest.raises(MetricsError, match="one value per label"):
        ScrapeCollector(CollectorRegistry(), env="demo", read=lambda: [family])


@virtual
async def test_the_scrape_serves_a_lane_whose_drain_died_as_stopped(
    tmp_path: Path, repo: FakeAuditRepository
) -> None:
    """S4a1-M1 (X1, D2): a dead drain stops the lane; the state gauge serves `stopped` and the
    drain-failure count serves the death under `stopped`, both of which AuditLaneRefusing reads."""
    writer = await sink(tmp_path, repo)
    lane = AuditLane(lj.LaneJournal(Broken(tmp_path / "lane"), KEYS), writer, **FAST)
    await lane.start()
    await until(lambda: lane.drain_failures["stopped"] == 1)
    got = families(Parts(writer, lane))

    assert got["cv_audit_lane_state"] == {("open",): 0, ("held",): 0, ("stopped",): 1}
    assert got["cv_audit_lane_drain_failures_total"] == {("held",): 0, ("stopped",): 1}
    await lane.close()


@virtual
async def test_the_scrape_serves_no_head_before_the_lane_opens(
    tmp_path: Path, repo: FakeAuditRepository
) -> None:
    """S4a1-M1 (X2): `last_seq` is absent until `open()` has read the lane (its id nil until then),
    as its HELP says; the lane's other gauges are served."""
    lane = await boot(tmp_path, await sink(tmp_path, repo), [])  # built, never started
    got = families(Parts(None, lane))

    assert "cv_audit_lane_last_seq" not in got and got["cv_audit_lane_depth"] == {(): 0}


@virtual
async def test_journal_counts_no_frame_whose_write_failed(
    tmp_path: Path, repo: FakeAuditRepository
) -> None:
    """S4a1-M2 (X3): `appended` counts frames written and fsynced; a write that fails stops the
    lane and refuses the append, which counts nothing."""
    writer, files = await sink(tmp_path, repo), FailingAppend(tmp_path / "lane")
    lane = AuditLane(lj.LaneJournal(files, KEYS), writer, **FAST)
    await lane.start()
    before, files.armed = dict(lane.journal.appended), True
    with pytest.raises(lj.LaneRefused):
        await lane.append(writer.build("auth.login", actor_label="owner"))

    assert lane.journal.appended == before and lane.journal.refusal == "stopped"
    await lane.close()


@virtual
async def test_drain_counts_an_anomaly_once_though_the_sink_refused_its_row_first(
    tmp_path: Path, repo: FakeAuditRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S4a1-M2 (X5): the count follows the row's hand-over, so a row the sink refused, which the
    drain hands over again, is counted once."""
    writer, refused = await sink(tmp_path, repo), list[str]()
    ingest = writer.ingest

    async def once(record: Any) -> int:  # the first anomaly row is refused, then all is taken
        if not refused and AuditEmission.model_validate(record).action == "audit.lane_anomaly":
            refused.append("audit.lane_anomaly")
            raise AuditUnavailable("the sink refuses once")
        return await ingest(record)

    monkeypatch.setattr(writer, "ingest", once)
    lane = await boot(tmp_path, writer)
    await lane.journal.append({"action": "auth.logout", "outcome": "success"})  # no AuditEmission
    await lane.flush(WAIT_S)

    assert refused and lane.anomalies["record_invalid"] == 1
    await lane.close()
