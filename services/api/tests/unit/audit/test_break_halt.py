"""`audit/break_halt.py` (#2904; 04 §8.1 "Enforced posture"): the halt after a verified audit-chain
break, its composition into the B18 kill switch port, its read of the chain, its re-reads, the
acknowledgement and the host console's run. The chain is the in-memory `FakeAuditRepository` under
the real `AuditQueryService`. No database, no network, no sleeps."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from audit_fakes import FakeAuditRepository
from prometheus_client import REGISTRY
from structlog.testing import capture_logs

from candleviewer import audit_ack_break
from candleviewer.admin.audit_break_ack import (
    CONSOLE_ACTOR,
    ConsoleAckUnavailable,
    acknowledge_from_console,
)
from candleviewer.api import audit_verify_runner as verify_runner_module
from candleviewer.api.audit_verify_runner import ChainVerifyRunner
from candleviewer.audit import break_halt as break_halt_module
from candleviewer.audit.break_halt import (
    ACK_DENIED,
    ACKNOWLEDGED,
    HALT_REASON_BREAK,
    HALT_REASON_UNREAD,
    HALTED,
    OBJECT_KIND,
    REFRESH_INTERVAL_S,
    SYSTEM_ACTOR,
    AckOutcome,
    AckRequest,
    AuditBreakHalt,
    AuditBreakHaltService,
    BreakIdentity,
    ChainHaltView,
    HaltViewTooLarge,
    acknowledge_break,
    read_halt_view,
)
from candleviewer.audit.hashing import ChainHasher
from candleviewer.audit.models import AuditEmission, ChainBreakKind, VerifyResult, storable
from candleviewer.audit.query import AuditQueryService, VerifyPlan
from candleviewer.audit.service import AuditService
from candleviewer.audit.verify_runner import VerifyOutcomeKind, VerifyRunRequest, VerifyTrigger
from candleviewer.domain.order_entry import OrderEntryRefusal
from candleviewer.domain.primitives import AccountId
from candleviewer.observability.health_probes import SystemEvent
from candleviewer.oms.errors import OmsNotReady, OrderEntryRefused, TradingDisabled
from candleviewer.oms_wiring import HaltingKillSwitch, InterimKillSwitch, TradingSwitchesBinding

T0 = datetime(2026, 10, 31, 4, 0, tzinfo=UTC)
ACCOUNT = AccountId(uuid.UUID("00000000-0000-0000-0000-0000000000a1"))
OWNER = uuid.UUID("00000000-0000-0000-0000-00000000000f")
BREAK = BreakIdentity(3, "entry_hash_mismatch")
OTHER = BreakIdentity(2, "prev_hash_mismatch")


@pytest.fixture(autouse=True)
def _restore_gauge() -> Iterator[None]:
    yield
    AuditBreakHalt(unread=False)  # a process-wide series: leave it clear


def _gauge() -> float | None:
    return REGISTRY.get_sample_value("cv_audit_break_halt_state")


def _result(*, verified: bool = False, bad: int = 3) -> VerifyResult:
    kind = None if verified else ChainBreakKind.ENTRY_HASH_MISMATCH
    return VerifyResult(
        verified=verified,
        entries_checked=bad,
        first_bad_id=None if verified else bad,
        checked_at=T0,
        from_id=1,
        to_id=5,
        anchor_hash="0" * 64,
        last_hash=None,
        kind=kind,
        full_chain=True,
    )


async def _append(repo: FakeAuditRepository, action: str, identity: BreakIdentity) -> None:
    """A record in the chain as an appended one is (the console's direct path)."""
    emission = AuditEmission(
        record_id=uuid.uuid4(),
        action=action,
        actor_label=SYSTEM_ACTOR,
        object_kind=OBJECT_KIND,
        object_id=identity.object_id,
        event_ts=datetime.now(UTC),
    )
    await repo.insert(storable(json.loads(emission.model_dump_json())))


class _Writer:
    def __init__(self, *, down: bool = False) -> None:
        self.records: list[dict[str, Any]] = []
        self.down = down

    async def emit(self, action: str, **fields: Any) -> None:
        if self.down:
            raise RuntimeError("audit down")
        self.records.append({"action": action, **fields})


class _Query:
    """`query` answering a scripted view, or raising."""

    def __init__(self, repo: FakeAuditRepository | None = None) -> None:
        self.service = AuditQueryService(repo or FakeAuditRepository())
        self.fail: Exception | None = None

    async def query(self, **filters: Any) -> Any:
        if self.fail is not None:
            raise self.fail
        return await self.service.query(**filters)


def _service(
    *, unread: bool = True, repo: FakeAuditRepository | None = None, writer: _Writer | None = None
) -> tuple[AuditBreakHaltService, _Query, _Writer, list[str | None]]:
    query, writer = _Query(repo), writer or _Writer()
    shown: list[str | None] = []

    async def on_change(reason: str | None) -> None:
        shown.append(reason)

    audit = SimpleNamespace(query=query, writer=writer)
    service = AuditBreakHaltService(AuditBreakHalt(unread=unread), audit, on_change=on_change)
    return service, query, writer, shown


# ---- the flag ---------------------------------------------------------------------------------


def test_halt_unread_is_engaged_until_a_read_applies_and_a_failed_read_engages_it_again() -> None:
    halt = AuditBreakHalt(unread=True)
    assert halt.engaged and _gauge() == 1
    halt.apply(ChainHaltView())
    assert not halt.engaged and _gauge() == 0
    halt.read_failed()
    assert halt.engaged and halt.unread


def test_halt_reason_names_a_break_over_an_unread_chain_and_is_none_when_clear() -> None:
    halt = AuditBreakHalt(unread=True)
    assert halt.reason == HALT_REASON_UNREAD == "audit_halt_unread"
    halt.trip(BREAK)
    assert halt.reason == HALT_REASON_BREAK == "audit_chain_break"
    halt.apply(ChainHaltView(acknowledged=frozenset({BREAK})))
    assert not halt.engaged and halt.reason is None


def test_halt_fake_backend_starts_clear() -> None:
    assert not AuditBreakHalt(unread=False).engaged


def test_halt_trip_engages_once_per_identity_and_logs_it_critical() -> None:
    halt = AuditBreakHalt(unread=False)
    with capture_logs() as logs:
        assert halt.trip(BREAK) is True
        assert halt.trip(BREAK) is False  # held: no second record owed
    assert halt.engaged and halt.breaks == (BREAK,) and halt.owed() == (BREAK,)
    assert [e["log_level"] for e in logs if e["event"] == "audit.break_halt.engaged"] == [
        "critical"
    ]


def test_halt_acknowledged_identity_never_trips_again_and_another_identity_does() -> None:
    halt = AuditBreakHalt(unread=False)
    halt.trip(BREAK)
    halt.acknowledged(BREAK)
    assert not halt.engaged and halt.owed() == ()
    assert halt.trip(BREAK) is False and not halt.engaged  # the same break re-found nightly
    assert halt.trip(OTHER) is True and halt.breaks == (OTHER,)


def test_halt_chain_view_engages_a_halted_identity_and_clears_an_acknowledged_local_trip() -> None:
    halt = AuditBreakHalt(unread=True)
    halt.apply(ChainHaltView(halted=frozenset({OTHER})))
    assert halt.engaged and halt.breaks == (OTHER,)
    halt.trip(BREAK)
    halt.apply(ChainHaltView(acknowledged=frozenset({OTHER, BREAK})))
    assert not halt.engaged and halt.owed() == ()


def test_halt_local_trip_survives_a_read_that_does_not_hold_its_record_yet() -> None:
    halt = AuditBreakHalt(unread=False)
    halt.trip(BREAK)
    halt.recorded(BREAK)
    halt.apply(ChainHaltView())  # the record is still in the writer's WAL
    assert halt.engaged and halt.owed() == ()


def test_break_identity_round_trips_its_object_id_and_refuses_malformed_ones() -> None:
    assert BreakIdentity.parse(BREAK.object_id) == BREAK
    assert BreakIdentity.of(_result()) == BREAK
    for text in (None, "", "3", "x:kind", "3:", "-1:kind"):
        assert BreakIdentity.parse(text) is None


# ---- the B18 port and the switches -------------------------------------------------------------


class _Switch:
    def __init__(self, refusal: TradingDisabled | None = None) -> None:
        self.refused = refusal

    def refusal(self, account_id: AccountId) -> TradingDisabled | None:
        return self.refused


class _Gate:
    def refusal(self, account_id: Any) -> OrderEntryRefusal:
        return OrderEntryRefusal("maintenance", "Order entry is paused for maintenance.")


def test_halting_kill_switch_refuses_while_engaged_and_otherwise_answers_as_the_switch() -> None:
    halt = AuditBreakHalt(unread=False)
    port = HaltingKillSwitch(InterimKillSwitch(), halt)
    assert port.refusal(ACCOUNT) is None
    halt.trip(BREAK)
    assert type(port.refusal(ACCOUNT)) is TradingDisabled  # no `reason`: 403 trading_disabled


def test_releasing_the_switch_never_clears_the_halt_and_acknowledging_never_releases_it() -> None:
    halt, switch = AuditBreakHalt(unread=False), _Switch(TradingDisabled())
    port = HaltingKillSwitch(switch, halt)
    halt.trip(BREAK)
    switch.refused = None  # the Owner releases B18
    assert isinstance(port.refusal(ACCOUNT), TradingDisabled)
    switch.refused = TradingDisabled()
    halt.acknowledged(BREAK)
    assert isinstance(port.refusal(ACCOUNT), TradingDisabled)


def test_switches_ask_the_fence_first_then_the_halt_before_the_gate() -> None:
    halt, fenced = AuditBreakHalt(unread=False), [True]
    binding = TradingSwitchesBinding(
        live_enabled=True,
        live_flag=lambda: True,
        kill_switch=HaltingKillSwitch(InterimKillSwitch(), halt),
        gate=_Gate(),
        fenced=lambda: fenced[0],
    )
    halt.trip(BREAK)
    assert isinstance(binding.refusal(ACCOUNT, "demo"), OmsNotReady)
    fenced[0] = False
    for environment in ("demo", "live", "testnet"):  # global: every environment (BQ-243)
        assert isinstance(binding.refusal(ACCOUNT, environment), TradingDisabled)
    halt.acknowledged(BREAK)
    assert isinstance(binding.refusal(ACCOUNT, "demo"), OrderEntryRefused)


def test_switches_announce_the_interim_the_halt_wraps() -> None:
    gauge = SimpleNamespace(value=None)

    class _G:
        def labels(self, *_: Any) -> Any:
            return SimpleNamespace(set=lambda v: setattr(gauge, "value", v))

    metrics = SimpleNamespace(gauge=lambda *a, **k: _G())
    binding = TradingSwitchesBinding(
        live_enabled=True,
        live_flag=lambda: True,
        kill_switch=HaltingKillSwitch(InterimKillSwitch(), AuditBreakHalt(unread=False)),
        gate=_Gate(),
        fenced=lambda: False,
    )
    binding.announce(metrics=metrics)  # type: ignore[arg-type]  # a recording stand-in
    assert gauge.value == 1


# ---- the chain read ---------------------------------------------------------------------------


async def test_read_halt_view_folds_each_identity_by_its_latest_record() -> None:
    repo = FakeAuditRepository()
    await _append(repo, HALTED, BREAK)
    await _append(repo, HALTED, OTHER)
    await _append(repo, ACKNOWLEDGED, OTHER)
    await _append(repo, "admin.audit_verify", BREAK)  # another action is never read
    view = await read_halt_view(AuditQueryService(repo))
    assert view == ChainHaltView(halted=frozenset({BREAK}), acknowledged=frozenset({OTHER}))


async def test_read_halt_view_pages_through_and_refuses_more_than_it_can_hold() -> None:
    page = SimpleNamespace(
        items=[SimpleNamespace(id=1, ts=T0, subject_id=BREAK.object_id, action=HALTED)],
        meta=SimpleNamespace(has_more=True),
    )

    class _Endless:
        calls = 0

        async def query(self, **_: Any) -> Any:
            self.calls += 1
            return page

    endless = _Endless()
    with pytest.raises(HaltViewTooLarge):
        await read_halt_view(endless)
    assert endless.calls == 20


async def test_read_halt_view_skips_a_record_with_no_break_named_and_logs_it() -> None:
    repo = FakeAuditRepository()
    await _append(repo, HALTED, BREAK)
    repo.rows[0]["object_id"] = "garbled"
    with capture_logs() as logs:
        assert await read_halt_view(AuditQueryService(repo)) == ChainHaltView()
    assert [e["event"] for e in logs] == ["audit.break_halt.unnamed_record"]


# ---- the service: trip, record, re-read, publish ----------------------------------------------


async def test_service_boot_read_clears_an_empty_chain_and_publishes_nothing() -> None:
    service, _, _, shown = _service()
    await service.refresh()
    assert not service.halt.engaged and shown == []


async def test_service_boot_rehydrates_an_unacknowledged_halt_before_traffic() -> None:
    repo = FakeAuditRepository()
    await _append(repo, HALTED, BREAK)
    service, _, _, shown = _service(repo=repo)
    await service.refresh()
    assert service.halt.engaged and service.halt.breaks == (BREAK,)
    assert shown == [HALT_REASON_BREAK]


async def test_service_read_failure_fails_closed_and_logs_its_class_only() -> None:
    service, query, _, shown = _service(unread=False)
    query.fail = ConnectionError("postgres://user:" + "pw" + "@host")
    with capture_logs() as logs:
        await service.refresh()
    assert service.halt.engaged and shown == [HALT_REASON_UNREAD]
    [failed] = [e for e in logs if e["event"] == "audit.break_halt.read_failed"]
    assert failed["error"] == "ConnectionError" and "pw" not in json.dumps(failed)


async def test_service_trip_is_synchronous_then_records_with_the_system_actor() -> None:
    service, _, writer, shown = _service(unread=False)
    owed = service.trip(_result())
    assert owed == BREAK and service.halt.engaged and writer.records == []  # before any await
    assert await service.record_trip(BREAK, _result(), trigger="startup") is True
    [record] = writer.records
    assert (record["action"], record["actor_label"]) == (HALTED, SYSTEM_ACTOR)
    assert (record["object_kind"], record["object_id"]) == (OBJECT_KIND, "3:entry_hash_mismatch")
    assert (record["outcome"].value, record["severity"].value) == ("success", "critical")
    assert record["after_state"]["trigger"] == "startup"
    assert not {"actor_user_id", "session_id", "actor_ip"} & set(record)
    assert service.halt.owed() == () and shown == [HALT_REASON_BREAK]


async def test_service_never_trips_on_a_verified_run() -> None:
    service, _, _, _ = _service(unread=False)
    assert service.trip(_result(verified=True)) is None and not service.halt.engaged


async def test_service_trip_whose_record_fails_stays_engaged_and_the_next_read_writes_it() -> None:
    writer = _Writer(down=True)
    service, _, _, _ = _service(unread=False, writer=writer)
    service.trip(_result())
    assert await service.record_trip(BREAK, _result(), trigger="scheduled") is False
    await service.refresh()  # the chain does not hold it, and the writer is still down
    assert service.halt.engaged and service.halt.owed() == (BREAK,)
    writer.down = False
    await service.refresh()
    assert [r["after_state"]["trigger"] for r in writer.records] == ["rewrite"]
    assert service.halt.engaged and service.halt.owed() == ()


async def test_service_acknowledgement_elsewhere_clears_this_process_at_its_next_read() -> None:
    repo = FakeAuditRepository()
    service, _, _, shown = _service(unread=False, repo=repo)
    service.trip(_result())
    await _append(repo, HALTED, BREAK)
    await service.refresh()
    assert service.halt.engaged
    await _append(repo, ACKNOWLEDGED, BREAK)  # the console, or another process's route
    await service.refresh()
    assert not service.halt.engaged and shown == [HALT_REASON_BREAK, None]


async def test_service_polls_every_interval_until_stopped() -> None:
    waits: list[float] = []
    reads = asyncio.Event()

    async def sleep(seconds: float) -> None:
        waits.append(seconds)
        if len(waits) == 3:
            reads.set()
            await asyncio.Event().wait()  # held here until the stop cancels it

    halt = AuditBreakHalt(unread=True)
    audit = SimpleNamespace(query=_Query(), writer=_Writer())
    service = AuditBreakHaltService(halt, audit, sleep=sleep)
    await service.start()
    await reads.wait()
    await service.stop()
    assert waits == [REFRESH_INTERVAL_S] * 3 and REFRESH_INTERVAL_S <= 5
    assert not halt.engaged


async def test_service_republishes_when_an_unread_halt_finds_a_break() -> None:
    """The gateway's reason follows the cause: unread, then a break the next read finds."""
    repo = FakeAuditRepository()
    service, query, _, shown = _service(unread=False, repo=repo)
    query.fail = TimeoutError()
    await service.refresh()
    query.fail = None
    await _append(repo, HALTED, BREAK)
    await service.refresh()
    assert shown == [HALT_REASON_UNREAD, HALT_REASON_BREAK]


async def test_service_poll_fails_closed_on_a_busy_hasher_or_a_timed_out_read_then_clears(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The 5 s poll reads through `AuditQueryService.query`, whose page check runs on the audit
    `ChainHasher` it shares with the page reads and verify's batches (never the `VerifySlot`):
    a full hasher, or a read past `READ_TIMEOUT_S`, engages the halt; the next good read clears
    it. The read before each wait is the one the wait observes."""
    default_timeout = break_halt_module.READ_TIMEOUT_S
    repo = FakeAuditRepository()
    good = AuditQueryService(repo)
    busy = AuditQueryService(repo, hasher=ChainHasher(max_pending=0))  # every slot taken
    script = ["good", "busy", "good", "hang", "good"]  # the boot read, then four polls

    class _Scripted:
        async def query(self, **filters: Any) -> Any:
            step = script.pop(0)
            if step == "hang":
                await asyncio.Event().wait()  # the read's timeout ends it
            return await (busy if step == "busy" else good).query(**filters)

    seen: list[bool] = []
    held = asyncio.Event()
    halt = AuditBreakHalt(unread=True)

    async def sleep(seconds: float) -> None:
        seen.append(halt.engaged)
        if not script:
            held.set()
            await asyncio.Event().wait()  # held here until the stop cancels it
        # a timed-out read without a real wait: the next read's deadline is now
        timeout = 0.0 if script[0] == "hang" else default_timeout
        monkeypatch.setattr(break_halt_module, "READ_TIMEOUT_S", timeout)

    shown: list[str | None] = []

    async def on_change(reason: str | None) -> None:
        shown.append(reason)

    audit = SimpleNamespace(query=_Scripted(), writer=_Writer())
    service = AuditBreakHaltService(halt, audit, on_change=on_change, sleep=sleep)
    with capture_logs() as logs:
        await service.start()
        await held.wait()
        await service.stop()
    assert seen == [False, True, False, True, False]
    assert shown == [HALT_REASON_UNREAD, None, HALT_REASON_UNREAD, None]
    failed = [e["error"] for e in logs if e["event"] == "audit.break_halt.read_failed"]
    assert failed == ["ChainHasherBusy", "TimeoutError"]
    good.close()
    busy.close()


async def test_service_publish_fault_is_logged_and_the_halt_still_enforces() -> None:
    async def broken(reason: str | None) -> None:
        raise RuntimeError("hub down")

    audit = SimpleNamespace(query=_Query(), writer=_Writer())
    service = AuditBreakHaltService(AuditBreakHalt(unread=False), audit, on_change=broken)
    service.trip(_result())
    with capture_logs() as logs:
        await service.record_trip(BREAK, _result(), trigger="on_demand")
    assert service.halt.engaged
    assert [e["event"] for e in logs if e["event"].endswith("publish_failed")] != []


# ---- the verifiers trip it --------------------------------------------------------------------


class _VerifyQuery:
    def __init__(self, result: VerifyResult | Exception) -> None:
        self.result = result

    async def plan_verify(self, **_: Any) -> VerifyPlan:
        return VerifyPlan(1, 5, 5, full_chain=True)

    async def run_verify(self, plan: VerifyPlan, **_: Any) -> VerifyResult:
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class _OrderedWriter(_Writer):
    """Records whether the halt was engaged when each record was written."""

    def __init__(self, halt: AuditBreakHalt) -> None:
        super().__init__()
        self.halt = halt
        self.engaged_at: list[tuple[str, bool]] = []

    async def emit(self, action: str, **fields: Any) -> None:
        self.engaged_at.append((action, self.halt.engaged))
        await super().emit(action, **fields)


async def test_scheduled_run_break_halts_before_its_result_record_then_records_the_halt() -> None:
    halt = AuditBreakHalt(unread=False)
    writer = _OrderedWriter(halt)
    audit = SimpleNamespace(query=_VerifyQuery(_result()), writer=writer)
    service = AuditBreakHaltService(halt, audit)
    runner = ChainVerifyRunner(audit, None, halt=service)
    request = VerifyRunRequest(trigger=VerifyTrigger.SCHEDULED, deadline_s=60)
    outcome = await runner.run(request)
    assert outcome.outcome is VerifyOutcomeKind.MISMATCH
    assert writer.engaged_at == [
        ("admin.audit_verify", False),  # `started`
        ("admin.audit_verify", True),  # the break's record: already halted
        (HALTED, True),
    ]
    assert writer.records[-1]["after_state"]["trigger"] == "scheduled"


async def test_a_stopped_run_never_trips_the_halt() -> None:
    halt = AuditBreakHalt(unread=False)
    audit = SimpleNamespace(query=_VerifyQuery(TimeoutError()), writer=_Writer())
    service = AuditBreakHaltService(halt, audit)
    runner = ChainVerifyRunner(audit, None, halt=service)
    request = VerifyRunRequest(trigger=VerifyTrigger.STARTUP, deadline_s=60)
    assert (await runner.run(request)).outcome is VerifyOutcomeKind.STOPPED
    assert not halt.engaged


# ---- a later break past an acknowledged one re-engages ----------------------------------------


async def _chain(tmp_path: Path, rows: int = 8) -> tuple[AuditService, FakeAuditRepository]:
    """The audit service started on the in-memory store with `rows` entries."""
    repo = FakeAuditRepository()
    audit = AuditService(repo)
    settings = SimpleNamespace(
        audit_wal_path=str(tmp_path / "a.wal"), audit_page_structure_budget=50_000
    )
    ctx: Any = SimpleNamespace(settings=settings)
    await audit.start(ctx)
    for i in range(rows):
        await audit.writer.emit("auth.login", actor_label="it", object_id=str(i))
    await audit.writer.flush(5)
    return audit, repo


async def _scheduled(runner: ChainVerifyRunner, audit: AuditService) -> VerifyOutcomeKind:
    outcome = await runner.run(VerifyRunRequest(trigger=VerifyTrigger.SCHEDULED, deadline_s=60))
    await audit.writer.flush(5)
    return outcome.outcome


async def _acknowledged(
    tmp_path: Path, *, checkpoint: bool = False
) -> tuple[AuditService, FakeAuditRepository, AuditBreakHaltService, ChainVerifyRunner, int]:
    """A chain whose first break A (an altered entry, or a checkpoint that names another hash)
    tripped the halt and was then acknowledged; the halt is clear. Returns A's id."""
    audit, repo = await _chain(tmp_path)
    first = repo.rows[1]
    if checkpoint:
        repo.checkpoints[first["id"]] = {"head_id": first["id"], "head_hash": "f" * 64}
    else:
        first["reason"] = "forged"
    service = AuditBreakHaltService(AuditBreakHalt(unread=False), audit)
    runner = ChainVerifyRunner(audit, None, halt=service)
    assert await _scheduled(runner, audit) is VerifyOutcomeKind.MISMATCH
    [found] = service.halt.breaks
    assert found.first_bad_id == first["id"]
    await _append(repo, ACKNOWLEDGED, found)
    await service.refresh()
    assert not service.halt.engaged
    return audit, repo, service, runner, first["id"]


async def test_scheduled_run_the_same_acknowledged_break_again_stays_clear(tmp_path: Path) -> None:
    audit, _, service, runner, _ = await _acknowledged(tmp_path)
    try:
        assert await _scheduled(runner, audit) is VerifyOutcomeKind.MISMATCH  # A is still a break
        await service.refresh()
        assert not service.halt.engaged and service.halt.breaks == ()
    finally:
        await audit.stop(1)


@pytest.mark.parametrize("checkpoint", [False, True], ids=["altered_entry", "checkpoint"])
async def test_scheduled_run_a_later_break_past_an_acknowledged_one_re_engages(
    tmp_path: Path, checkpoint: bool
) -> None:
    """#2904 (coordinator read of PR #5289, item 2): the verifier names only the first break, so
    the run resumes past the acknowledged A and trips on the later B, and records B's halt."""
    audit, repo, service, runner, first = await _acknowledged(tmp_path, checkpoint=checkpoint)
    later = repo.rows[5]
    later["reason"] = "forged later"
    try:
        assert await _scheduled(runner, audit) is VerifyOutcomeKind.MISMATCH
        assert service.halt.engaged
        assert service.halt.breaks == (BreakIdentity(later["id"], "entry_hash_mismatch"),)
        await service.refresh()  # B's record is in the chain: every process re-engages
        assert service.halt.breaks == (BreakIdentity(later["id"], "entry_hash_mismatch"),)
        halted = [r for r in repo.rows if r["action"] == HALTED]
        assert [r["object_id"] for r in halted][-1] == f"{later['id']}:entry_hash_mismatch"
        assert first < later["id"]
    finally:
        await audit.stop(1)


class _ResumeQuery:
    """A scripted verifier: `plan_verify` and `run_verify` answer in turn, each call recorded."""

    def __init__(self, *answers: VerifyResult | Exception) -> None:
        self.answers = list(answers)
        self.plans: list[VerifyPlan] = []

    async def plan_verify(self, *, from_id: int | None, **_: Any) -> VerifyPlan:
        return VerifyPlan(from_id, 9, 9, full_chain=from_id is None)

    async def run_verify(self, plan: VerifyPlan, **_: Any) -> VerifyResult:
        self.plans.append(plan)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


def _acked_service(
    query: _ResumeQuery,
    *acked: BreakIdentity,
    events: _Events | None = None,
    writer: _Writer | None = None,
) -> tuple[AuditBreakHaltService, ChainVerifyRunner]:
    halt = AuditBreakHalt(unread=False)
    halt.apply(ChainHaltView(acknowledged=frozenset({BREAK, *acked})))
    audit = SimpleNamespace(query=query, writer=writer or _Writer())
    service = AuditBreakHaltService(halt, audit)
    return service, ChainVerifyRunner(audit, events, halt=service)


class _Events:
    """The system event writer: each event kept."""

    def __init__(self) -> None:
        self.written: list[SystemEvent] = []

    async def write(self, event: SystemEvent) -> None:
        self.written.append(event)


def _failures() -> float:
    return REGISTRY.get_sample_value("audit_chain_verification_failures_total") or 0.0


def _chain_state() -> float | None:
    return REGISTRY.get_sample_value("cv_audit_chain_verified_state")


async def test_scheduled_run_resumes_from_the_id_after_each_acknowledged_break() -> None:
    query = _ResumeQuery(_result(), _result(bad=7))
    service, runner = _acked_service(query)
    await runner.run(VerifyRunRequest(trigger=VerifyTrigger.SCHEDULED, deadline_s=60))
    assert [(p.from_id, p.resumed) for p in query.plans] == [(None, False), (4, True)]
    assert service.halt.breaks == (BreakIdentity(7, "entry_hash_mismatch"),)


@pytest.mark.parametrize(
    "resumed",
    [TimeoutError(), _result(verified=True), _result()],
    ids=["stopped", "clean_to_the_head", "no_way_past_it"],
)
async def test_scheduled_run_whose_resume_finds_no_new_break_stays_clear(
    resumed: VerifyResult | Exception,
) -> None:
    """A resume that stops trips nothing, as a stopped run (logged by class); one that passes to
    the head, or names the acknowledged break again, ends the search."""
    query = _ResumeQuery(_result(), resumed)
    service, runner = _acked_service(query)
    with capture_logs() as logs:
        await runner.run(VerifyRunRequest(trigger=VerifyTrigger.SCHEDULED, deadline_s=60))
    assert not service.halt.engaged and len(query.plans) == 2
    stopped = [e for e in logs if e["event"] == "audit.verify.resume_stopped"]
    assert [e["error"] for e in stopped] == (
        ["TimeoutError"] if isinstance(resumed, Exception) else []
    )


async def test_scheduled_run_a_resumed_break_is_counted_and_raised_as_a_first_walk_break() -> None:
    """#2904 (coordinator, PR 2 row c): the break B past the acknowledged A raises its own
    critical `audit_chain_break` event and counts in the failures series, as A's walk did."""
    events = _Events()
    service, runner = _acked_service(_ResumeQuery(_result(), _result(bad=7)), events=events)
    before = _failures()
    await runner.run(VerifyRunRequest(trigger=VerifyTrigger.SCHEDULED, deadline_s=60))
    assert _failures() - before == 2 and _chain_state() == 0
    assert [(e.kind, e.severity, e.details["first_bad_id"]) for e in events.written] == [
        ("audit_chain_break", "critical", "3"),
        ("audit_chain_break", "critical", "7"),
    ]
    assert events.written[1].details["kind"] == "entry_hash_mismatch"
    assert service.halt.breaks == (BreakIdentity(7, "entry_hash_mismatch"),)


async def test_scheduled_run_at_the_resume_bound_halts_on_the_first_entry_not_walked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#2904 (coordinator, PR 2 row b; 04 §8.1 fail closed): past more acknowledged breaks than
    one run resumes, the run halts on the first entry it has not walked, kind `unknown`, and
    records that halt; the bound is no break, so it raises no event and counts no failure."""
    monkeypatch.setattr(verify_runner_module, "_MAX_RESUMES", 2)
    query = _ResumeQuery(_result(), _result(bad=4), _result(bad=5))
    acked = (BreakIdentity(4, "entry_hash_mismatch"), BreakIdentity(5, "entry_hash_mismatch"))
    events, writer = _Events(), _Writer()
    service, runner = _acked_service(query, *acked, events=events, writer=writer)
    before = _failures()
    with capture_logs() as logs:
        await runner.run(VerifyRunRequest(trigger=VerifyTrigger.SCHEDULED, deadline_s=60))
    assert service.halt.engaged and service.halt.breaks == (BreakIdentity(6, "unknown"),)
    assert [p.from_id for p in query.plans] == [None, 4, 5]
    [capped] = [e for e in logs if e["event"] == "audit.verify.resume_capped"]
    assert (capped["resumes"], capped["at"], capped["log_level"]) == (2, 6, "error")
    halted = [r for r in writer.records if r["action"] == HALTED]
    assert [r["object_id"] for r in halted] == ["6:unknown"]
    assert _failures() - before == 1 and len(events.written) == 1  # the first walk's only


async def test_scheduled_run_past_an_acknowledged_resume_bound_walks_on_to_a_later_break(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Acknowledging the bound lets the run walk past it, so the bound never hides a later
    break: B at 9, past the bound at 6, trips."""
    monkeypatch.setattr(verify_runner_module, "_MAX_RESUMES", 2)
    query = _ResumeQuery(_result(), _result(bad=4), _result(bad=5), _result(bad=9))
    acked = (
        BreakIdentity(4, "entry_hash_mismatch"),
        BreakIdentity(5, "entry_hash_mismatch"),
        BreakIdentity(6, "unknown"),
    )
    service, runner = _acked_service(query, *acked)
    await runner.run(VerifyRunRequest(trigger=VerifyTrigger.SCHEDULED, deadline_s=60))
    assert [p.from_id for p in query.plans] == [None, 4, 5, 6]
    assert service.halt.breaks == (BreakIdentity(9, "entry_hash_mismatch"),)


# ---- the acknowledgement ----------------------------------------------------------------------


def _ack(identity: BreakIdentity = BREAK) -> AckRequest:
    return AckRequest(identity, "restored from backup", OWNER, CONSOLE_ACTOR)


async def test_acknowledgement_by_the_owner_of_the_engaged_break_is_written_ahead() -> None:
    writer = _Writer()
    got = await acknowledge_break(_ack(), is_owner=True, engaged=[BREAK], emit=writer.emit)
    assert got is AckOutcome.ACKNOWLEDGED
    [record] = writer.records
    assert (record["action"], record["actor_user_id"], record["object_id"]) == (
        ACKNOWLEDGED,
        OWNER,
        BREAK.object_id,
    )
    assert record["severity"].value == "critical" and record["reason"] == "restored from backup"


@pytest.mark.parametrize(
    ("owner", "engaged", "outcome"),
    [(False, [BREAK], AckOutcome.NOT_OWNER), (True, [OTHER], AckOutcome.NOT_ENGAGED)],
)
async def test_acknowledgement_refused_is_recorded_denied_and_acknowledges_nothing(
    owner: bool, engaged: list[BreakIdentity], outcome: AckOutcome
) -> None:
    writer = _Writer()
    got = await acknowledge_break(_ack(), is_owner=owner, engaged=engaged, emit=writer.emit)
    assert got is outcome
    [record] = writer.records
    assert (record["action"], record["outcome"].value, record["reason"]) == (
        ACK_DENIED,
        "denied",
        outcome.value,
    )


async def test_acknowledgement_whose_record_fails_changes_nothing() -> None:
    writer = _Writer(down=True)
    got = await acknowledge_break(_ack(), is_owner=True, engaged=[BREAK], emit=writer.emit)
    assert got is AckOutcome.RECORD_FAILED


# ---- the host console -------------------------------------------------------------------------


class _Owners:
    def __init__(self, known: dict[str, str]) -> None:
        self.known = known

    async def find_active_owner(self, identifier: str) -> str | None:
        return self.known.get(identifier)


class _Stores:
    def __init__(self, repo: FakeAuditRepository, *, up: bool = True) -> None:
        self.audit_log, self.up = repo, up
        self.owners = _Owners({"basil": str(OWNER)})

    async def reachable(self) -> bool:
        return self.up


async def test_console_acknowledges_the_engaged_break_and_a_process_clears_at_its_read() -> None:
    repo = FakeAuditRepository()
    await _append(repo, HALTED, BREAK)
    service, _, _, _ = _service(repo=repo)
    await service.refresh()
    assert service.halt.engaged
    got = await acknowledge_from_console(
        _Stores(repo), owner="basil", identity=BREAK, reason="restored"
    )
    assert got is AckOutcome.ACKNOWLEDGED
    row = repo.rows[-1]
    assert (row["action"], row["actor_label"], str(row["actor_user_id"])) == (
        ACKNOWLEDGED,
        CONSOLE_ACTOR,
        str(OWNER),
    )
    await service.refresh()
    assert not service.halt.engaged


async def test_console_refuses_a_name_that_is_no_active_owner_recorded_denied() -> None:
    repo = FakeAuditRepository()
    await _append(repo, HALTED, BREAK)
    got = await acknowledge_from_console(
        _Stores(repo), owner="mallory", identity=BREAK, reason="nope"
    )
    assert got is AckOutcome.NOT_OWNER
    assert (repo.rows[-1]["action"], repo.rows[-1]["actor_user_id"]) == (ACK_DENIED, None)


async def test_console_with_postgres_unreachable_writes_nothing() -> None:
    repo = FakeAuditRepository()
    with pytest.raises(ConsoleAckUnavailable):
        await acknowledge_from_console(
            _Stores(repo, up=False), owner="basil", identity=BREAK, reason="x" * 3
        )
    assert repo.rows == []


_ARGV = ["--owner", "basil", "--first-bad-id", "3", "--kind", "entry_hash_mismatch", "--reason"]


@pytest.mark.parametrize("argv", [[*_ARGV, ""], [*_ARGV, "a\x07b"], [*_ARGV, "x" * 281]])
def test_console_refuses_a_reason_out_of_bounds_before_reading_any_setting(
    argv: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    assert audit_ack_break.main(argv) == audit_ack_break.EXIT_INVALID
    assert "nothing ran" in capsys.readouterr().err


def test_console_kind_is_a_closed_set() -> None:
    argv = ["--owner", "b", "--first-bad-id", "3", "--kind", "made_up", "--reason", "abc"]
    with pytest.raises(SystemExit) as exc:
        audit_ack_break.main(argv)
    assert exc.value.code == audit_ack_break.EXIT_INVALID
    assert set(audit_ack_break.KINDS) == {k.value for k in ChainBreakKind} | {"unknown"}


async def test_console_run_exit_status_follows_the_outcome() -> None:
    repo = FakeAuditRepository()
    await _append(repo, HALTED, BREAK)
    settings: Any = SimpleNamespace()
    stores = _Stores(repo)
    assert await audit_ack_break.run(settings, "basil", OTHER, "abc", stores=stores) == 1
    assert await audit_ack_break.run(settings, "basil", BREAK, "abc", stores=stores) == 0
    stores.up = False
    assert await audit_ack_break.run(settings, "basil", BREAK, "abc", stores=stores) == 1


class _Settings:
    def __init__(self, env: str) -> None:
        self.environment = SimpleNamespace(value=env)
        self.log_level, self.log_format = "INFO", "console"


_ARGS = ["--owner", "basil", "--first-bad-id", "3", "--kind", "entry_hash_mismatch"]


@pytest.mark.parametrize(
    ("env", "live", "status"), [("live", False, 2), ("live", True, 0), ("demo", False, 0)]
)
def test_console_main_asks_live_to_confirm_then_runs_the_named_break(
    monkeypatch: pytest.MonkeyPatch, env: str, live: bool, status: int
) -> None:
    ran: list[tuple[str, BreakIdentity, str]] = []

    async def run(settings: Any, owner: str, identity: BreakIdentity, reason: str) -> int:
        ran.append((owner, identity, reason))
        return 0

    monkeypatch.setattr(audit_ack_break, "Settings", lambda: _Settings(env))
    monkeypatch.setattr(audit_ack_break, "configure_logging", lambda **_: None)
    monkeypatch.setattr(audit_ack_break, "run", run)
    argv = [*_ARGS, "--reason", " restored "] + (["--live"] if live else [])
    assert audit_ack_break.main(argv) == status
    assert ran == ([] if status else [("basil", BREAK, "restored")])


def test_console_main_with_settings_it_cannot_read_runs_nothing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def broken() -> Any:
        raise ValueError("CV_PG_DSN=postgres://user:" + "secret" + "@host")

    monkeypatch.setattr(audit_ack_break, "Settings", broken)
    assert audit_ack_break.main([*_ARGS, "--reason", "abc"]) == audit_ack_break.EXIT_INVALID
    err = capsys.readouterr().err
    assert "invalid settings (ValueError)" in err and "secret" not in err


async def test_console_run_releases_its_pool_and_a_failing_release_is_logged() -> None:
    class _Database:
        disposed = 0

        async def dispose(self) -> None:
            self.disposed += 1
            raise ConnectionError("gone")

    database = _Database()
    with capture_logs() as logs:
        await audit_ack_break._dispose(database)  # type: ignore[arg-type]  # a stand-in pool
    assert database.disposed == 1
    assert [e["event"] for e in logs] == ["audit.break_ack.pool_not_released"]
