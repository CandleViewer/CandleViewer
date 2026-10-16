"""`ReplaySessionService` on the B12 `replay` chart (E26-T01 slice 3/3, #624).

Fakes only (no database, no network, no timed sleeps): the slice-2 in-memory repository with a
settable clock, a fake coverage reader, a recording audit sink and a handle factory that counts
releases. The chart is the real committed B12 contract built through `statechart.factory`.
"""

from __future__ import annotations

import asyncio
import uuid
from collections import Counter
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, cast

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

import candleviewer.statechart.bindings.b12_replay as b12
from candleviewer.replay.sessions_service import (
    ReplayChartError,
    ReplayLimits,
    ReplayQuotaExceededError,
    ReplaySessionService,
    ReplaySessionValidationError,
    ReplayUnavailableError,
    ReplayWindowUncoveredError,
    WindowCoverage,
    to_us,
)
from candleviewer.statechart.gateway import Gateway, GatewayError
from candleviewer.storage.repositories.replay_sessions import (
    ReplaySessionCreate,
    ReplaySessionIllegalUpdateError,
    ReplaySessionNotFoundError,
    ReplaySessionRow,
    ReplayState,
)
from tests.unit.storage.fakes_replay_sessions import FakeClock, FakeReplaySessionRepository

USER_A = "0b6a4b7e-6f0e-4c1a-9a51-6a7b1c2d3e4f"
USER_B = "5d1f8e2a-3b4c-4d5e-8f60-718293a4b5c6"
T0 = datetime(2026, 9, 1, tzinfo=UTC)
T1 = T0 + timedelta(hours=1)
GAP = [to_us(T0) + 60_000_000, to_us(T0) + 61_000_000]  # one recorder gap inside the window


class FakeCoverage:
    def __init__(self) -> None:
        self.covered: tuple[tuple[int, int], ...] = ((to_us(T0), GAP[0]), (GAP[1], to_us(T1)))
        self.calls: list[tuple[str, int, int]] = []
        self.fail: BaseException | None = None

    async def window(self, symbol: str, lo_us: int, hi_us: int) -> WindowCoverage:
        self.calls.append((symbol, lo_us, hi_us))
        await asyncio.sleep(0)  # a real read suspends: lets concurrent creates interleave here
        if self.fail is not None:
            raise self.fail
        return WindowCoverage(covered=self.covered)


class FakeAudit:
    def __init__(self) -> None:
        self.rows: list[tuple[str, dict[str, Any]]] = []
        self.fail = False

    async def emit(self, action: str, **kwargs: Any) -> None:
        if self.fail:
            raise RuntimeError("audit unavailable")
        self.rows.append((action, kwargs))

    def actions(self) -> list[str]:
        return [a for a, _ in self.rows]


class FakeHandles:
    def __init__(self) -> None:
        self.acquired: list[str] = []
        self.released: Counter[str] = Counter()

    async def acquire(self, row: ReplaySessionRow) -> Sequence[Callable[[], Awaitable[None]]]:
        self.acquired.append(row.id)

        async def release() -> None:
            self.released[row.id] += 1

        return (release,)


@dataclass
class Env:
    clock: FakeClock
    repo: FakeReplaySessionRepository
    coverage: FakeCoverage = field(default_factory=FakeCoverage)
    audit: FakeAudit = field(default_factory=FakeAudit)
    handles: FakeHandles = field(default_factory=FakeHandles)
    svc: ReplaySessionService | None = None

    @property
    def s(self) -> ReplaySessionService:
        assert self.svc is not None
        return self.svc


def make_env(*, cap: int = 2, repo: FakeReplaySessionRepository | None = None, **kw: Any) -> Env:
    clock = FakeClock(datetime(2026, 10, 1, tzinfo=UTC))
    env = Env(clock=clock, repo=repo or FakeReplaySessionRepository(clock))
    limits = ReplayLimits(
        idle_ttl=timedelta(hours=2), max_sessions_per_user=cap, max_window=timedelta(hours=24)
    )
    env.svc = ReplaySessionService(
        env.repo, coverage=env.coverage, audit=env.audit, handles=env.handles,
        limits=limits, clock=clock, **kw,
    )  # fmt: skip
    return env


def request(**changes: Any) -> ReplaySessionCreate:
    base = ReplaySessionCreate(id="", user_id="", symbol="BTCUSDT", range_start=T0, range_end=T1)
    return replace(base, **changes)


async def state_in_db(env: Env, user: str, sid: str) -> ReplayState:
    row = await env.repo.get(user, sid)
    assert row is not None
    return row.state


async def until(pred: Callable[[], Awaitable[bool]]) -> None:
    """Bounded cooperative yields (no timed sleep): the chart's invoke hand-offs settle."""
    for _ in range(200):
        if await pred():
            return
        await asyncio.sleep(0)
    raise AssertionError("condition not reached")


# --- create ---------------------------------------------------------------------------------


async def test_create_forces_principal_mints_id_audits_and_seeds_gaps() -> None:
    env = make_env()
    row = await env.s.create(USER_A, request(id="client-id", user_id=USER_B))
    assert row.user_id == USER_A and row.id == str(uuid.UUID(row.id)) and row.cursor_ts == T0
    assert (row.state, env.s.state_of(row.id)) == (ReplayState.CREATED, "created")
    assert env.handles.acquired == [row.id] and env.audit.actions() == ["replay.session.created"]
    facts = env.s.facts_of(row.id)
    assert facts is not None and facts["coverage_gaps"] == [GAP]


async def test_create_partly_covered_window_seeds_every_uncovered_span_as_a_gap() -> None:
    env = make_env()
    start = to_us(T0) + 30_000_000  # nothing recorded in the first 30 s
    env.coverage.covered = ((start, GAP[0]), (GAP[1], to_us(T1)))
    facts = env.s.facts_of((await env.s.create(USER_A, request())).id)
    assert facts is not None and facts["coverage_gaps"] == [[to_us(T0), start], GAP]


async def test_create_dependency_failures_are_typed_and_allocate_nothing() -> None:
    env = make_env()
    env.coverage.fail = TimeoutError()
    with pytest.raises(ReplayUnavailableError):
        await env.s.create(USER_A, request())
    env.coverage.fail, env.audit.fail = None, True
    with pytest.raises(ReplayUnavailableError):
        await env.s.create(USER_A, request())
    assert env.handles.acquired == [] and (await env.repo.list_page(USER_A)).rows == ()


class _BrokenGateway(Gateway):
    def register(self, *args: Any, **kwargs: Any) -> None:
        raise GatewayError("registry broken")


async def test_create_rolls_back_handles_chart_and_row_when_registration_fails() -> None:
    env = make_env(gateway=_BrokenGateway())
    with pytest.raises(GatewayError):
        await env.s.create(USER_A, request())
    sid = env.handles.acquired[0]
    assert env.handles.released[sid] == 1 and env.s.state_of(sid) is None
    assert (await env.repo.list_page(USER_A)).rows == ()


async def test_create_uncovered_window_refused_before_any_row_audit_or_handle() -> None:
    env = make_env()
    env.coverage.covered = ()
    with pytest.raises(ReplayWindowUncoveredError):
        await env.s.create(USER_A, request())
    assert env.handles.acquired == [] and env.audit.rows == []
    assert (await env.repo.list_page(USER_A)).rows == ()


async def test_create_at_quota_refused_before_coverage_or_handles() -> None:
    env = make_env(cap=1)
    await env.s.create(USER_A, request())
    env.coverage.calls.clear()
    with pytest.raises(ReplayQuotaExceededError):
        await env.s.create(USER_A, request())
    assert env.coverage.calls == [] and len(env.handles.acquired) == 1
    await env.s.create(USER_B, request())  # the quota is per user


async def test_concurrent_creates_cannot_both_pass_the_quota() -> None:
    env = make_env(cap=1)
    results = await asyncio.gather(
        env.s.create(USER_A, request(), prepare=True),
        env.s.create(USER_A, request(), prepare=True),
        return_exceptions=True,
    )
    assert sorted(type(r).__name__ for r in results) == [
        "ReplayQuotaExceededError", "ReplaySessionRow",
    ]  # fmt: skip
    assert len(env.handles.acquired) == 1


async def test_seek_out_of_finished_rechecks_the_quota_rp_d03() -> None:
    env = make_env(cap=1)
    sid = (await env.s.create(USER_A, request(), prepare=True)).id
    await env.s.transition(USER_A, sid, "PLAY")
    await env.s.transition(USER_A, sid, "RANGE_END")  # `finished` holds no buffer
    other = await env.repo.create(replace(request(), id=str(uuid.uuid4()), user_id=USER_A))
    await env.repo.update_state(USER_A, other.id, state=ReplayState.PAUSED)  # live elsewhere
    with pytest.raises(ReplayQuotaExceededError):
        await env.s.transition(USER_A, sid, "SEEK", SEEK_T0)
    assert env.s.state_of(sid) == "finished"


@pytest.mark.parametrize(
    "changes",
    [
        {"range_end": T0},  # rps_range
        {"range_end": T0 + timedelta(hours=25)},  # CV_REPLAY_MAX_WINDOW_HOURS
        {"speed": Decimal(0)},  # rps_speed
        {"speed": Decimal(101)},
        {"cursor_ts": T1 + timedelta(seconds=1)},  # rps_cursor
        {"paper_trading": True},  # rps_paper
        {"symbol": "btc/usdt"},
    ],
)
async def test_create_invalid_request_is_a_readable_validation_error(
    changes: dict[str, Any],
) -> None:
    env = make_env()
    with pytest.raises(ReplaySessionValidationError, match=r"\w+"):
        await env.s.create(USER_A, request(**changes))
    assert env.coverage.calls == [] and env.handles.acquired == [] and env.audit.rows == []


async def test_create_paper_account_only_through_the_grant_gate() -> None:
    account = str(uuid.uuid4())
    paper = request(paper_trading=True, paper_account_id=account)
    with pytest.raises(ReplaySessionValidationError):  # no gate wired: fail closed
        await make_env().s.create(USER_A, paper)

    async def gate(user: str, acct: str) -> bool:
        return (user, acct) == (USER_A, account)

    env = make_env(paper_gate=gate)
    with pytest.raises(ReplaySessionValidationError):
        await env.s.create(USER_B, paper)
    assert (await env.s.create(USER_A, paper)).paper_account_id == account


# --- transition -----------------------------------------------------------------------------

SEEK_T0 = {"cursor": to_us(T0)}
_PAYLOADS: dict[str, dict[str, Any]] = {
    "SEEK": SEEK_T0, "SET_SPEED": {"speed": 2}, "SOURCE_ERROR": {"error": "Boom"},
}  # fmt: skip


async def test_control_events_follow_b12_and_the_row_mirrors_every_state() -> None:
    env = make_env()
    row = await env.s.create(USER_A, request(), prepare=True)  # created -> buffering -> paused
    assert (row.state, env.s.state_of(row.id)) == (ReplayState.PAUSED, "paused")
    steps = [
        ("PLAY", {}, "playing"), ("SET_SPEED", {"speed": 4}, "playing"),
        ("CONSUMER_SLOW", {}, "playing"), ("PAUSE", {}, "paused"), ("STEP", {}, "paused"),
        ("SEEK", SEEK_T0, "paused"), ("PLAY", {}, "playing"), ("RANGE_END", {}, "finished"),
        ("SEEK", SEEK_T0, "paused"),
    ]  # fmt: skip
    for event, payload, want in steps:
        row = await env.s.transition(USER_A, row.id, event, payload)
        assert (row.state.value, env.s.state_of(row.id)) == (want, want), event
    assert row.speed == Decimal(4) and row.finished_at is None


async def test_range_end_with_loop_rewinds_the_cursor_to_range_start() -> None:
    env = make_env()
    start = request(loop_enabled=True, cursor_ts=T0 + timedelta(minutes=30))
    sid = (await env.s.create(USER_A, start, prepare=True)).id
    await env.s.transition(USER_A, sid, "PLAY")
    row = await env.s.transition(USER_A, sid, "RANGE_END")
    assert (row.state, row.cursor_ts) == (ReplayState.PAUSED, T0)


async def test_source_error_enters_error_with_a_token_audited_and_seek_recovers() -> None:
    env = make_env()
    sid = (await env.s.create(USER_A, request(), prepare=True)).id
    await env.s.transition(USER_A, sid, "PLAY")
    failure = {"error": "ParquetReadError: /data/parquet/x.parquet"}
    row = await env.s.transition(USER_A, sid, "SOURCE_ERROR", failure)
    assert (row.state, row.error_message) == (ReplayState.ERROR, "ParquetReadError")
    assert ("replay.session.error", "ParquetReadError", "system:replay-chart") in [
        (a, kw["reason"], kw["actor_label"]) for a, kw in env.audit.rows
    ]
    row = await env.s.transition(USER_A, sid, "SEEK", SEEK_T0)
    assert (row.state, row.error_message) == (ReplayState.PAUSED, None)


ERRORED = ("PREPARE", "PLAY", "SOURCE_ERROR")


@pytest.mark.parametrize(
    ("setup", "event"),
    [
        ((), "PLAY"), ((), "PAUSE"), ((), "SEEK"), (("PREPARE",), "PREPARE"),
        (("PREPARE",), "CANCEL"), (("PREPARE",), "RANGE_END"), (("PREPARE", "PLAY"), "STEP"),
        (("PREPARE", "PLAY"), "PLAY"), (("PREPARE", "PLAY", "RANGE_END"), "PLAY"),
        (ERRORED, "PLAY"), (ERRORED, "STEP"), (ERRORED, "CANCEL"), (ERRORED, "RANGE_END"),
    ],
)  # fmt: skip
async def test_illegal_event_refused_by_the_chart_and_the_row_is_unchanged(
    setup: tuple[str, ...], event: str
) -> None:
    env = make_env()
    sid = (await env.s.create(USER_A, request())).id
    for ev in setup:
        await env.s.transition(USER_A, sid, ev, _PAYLOADS.get(ev))
    before, leaf = await env.repo.get(USER_A, sid), env.s.state_of(sid)
    env.clock.advance(minutes=1)
    with pytest.raises(ReplaySessionIllegalUpdateError):
        await env.s.transition(USER_A, sid, event, SEEK_T0 if event == "SEEK" else None)
    assert await env.repo.get(USER_A, sid) == before and env.s.state_of(sid) == leaf


@pytest.mark.parametrize(
    ("event", "payload"),
    [
        ("KILL", {}), ("DESTROY", {}), ("NOPE", {}), ("SET_SPEED", {"speed": 0}),
        ("SET_SPEED", {"speed": True}), ("SEEK", {"cursor": to_us(T1) + 1}), ("SEEK", {}),
        ("PLAY", {"type": "DESTROY"}), ("SOURCE_ERROR", {"error": 7}),
    ],
)  # fmt: skip
async def test_unknown_event_or_payload_rejected_before_the_chart(
    event: str, payload: dict[str, Any]
) -> None:
    env = make_env()
    sid = (await env.s.create(USER_A, request(), prepare=True)).id
    with pytest.raises(ReplaySessionValidationError):
        await env.s.transition(USER_A, sid, event, payload)
    assert env.s.state_of(sid) == "paused"


async def test_another_users_session_is_not_found_never_forbidden() -> None:
    env = make_env()
    sid = (await env.s.create(USER_A, request())).id
    with pytest.raises(ReplaySessionNotFoundError):
        await env.s.transition(USER_B, sid, "PREPARE")
    with pytest.raises(ReplaySessionNotFoundError):
        await env.s.destroy(USER_B, sid)
    with pytest.raises(ReplaySessionNotFoundError):
        await env.s.transition(USER_A, str(uuid.uuid4()), "PREPARE")
    assert env.s.state_of(sid) == "created" and env.handles.released[sid] == 0


def _gated(gate: asyncio.Event) -> Callable[..., Awaitable[None]]:
    async def service(*_args: object) -> None:
        await gate.wait()

    return service


async def test_events_during_a_running_step_are_refused_until_it_completes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gate = asyncio.Event()
    monkeypatch.setitem(b12.SERVICES, "emit_one_step", _gated(gate))
    env = make_env()
    sid = (await env.s.create(USER_A, request(), prepare=True)).id
    assert (await env.s.transition(USER_A, sid, "STEP")).state is ReplayState.STEPPING
    for event in ("PLAY", "PAUSE", "STEP", "SEEK", "CANCEL"):
        with pytest.raises(ReplaySessionIllegalUpdateError):
            await env.s.transition(USER_A, sid, event, _PAYLOADS.get(event))
    gate.set()
    assert (await env.s.transition(USER_A, sid, "PLAY")).state is ReplayState.PLAYING


class _CompletionFirst(Gateway):
    """Lets the gated seek finish between the service's `can()` and its send (the race)."""

    def __init__(self, gate: asyncio.Event) -> None:
        super().__init__()
        self.gate = gate

    async def send(self, key: str, event: Any, *, wait: bool = False) -> Any:
        if isinstance(event, dict) and event.get("type") == "CANCEL":
            self.gate.set()
            for _ in range(100):
                await asyncio.sleep(0)
        return await super().send(key, event, wait=wait)


async def test_a_send_held_by_the_chart_after_a_racing_completion_is_refused_and_counted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gate = asyncio.Event()
    monkeypatch.setitem(b12.SERVICES, "seek_and_prime", _gated(gate))
    env = make_env(gateway=_CompletionFirst(gate))
    sid = (await env.s.create(USER_A, request(), prepare=True)).id  # held in `buffering`
    with pytest.raises(ReplaySessionIllegalUpdateError):
        await env.s.transition(USER_A, sid, "CANCEL")  # the seek lands first: CANCEL is held
    assert env.s.refusals.counts == {"deferred": 1}
    row = await env.repo.get(USER_A, sid)
    assert row is not None and row.state is ReplayState.PAUSED and env.s.state_of(sid) == "paused"


async def test_an_audit_outage_on_a_chart_error_still_records_the_error_state() -> None:
    env = make_env()
    sid = (await env.s.create(USER_A, request(), prepare=True)).id
    await env.s.transition(USER_A, sid, "PLAY")
    env.audit.fail = True
    row = await env.s.transition(USER_A, sid, "SOURCE_ERROR", {"error": "Boom"})
    assert (row.state, row.error_message) == (ReplayState.ERROR, "Boom")
    assert "replay.session.error" not in env.audit.actions()


async def test_a_raising_binding_action_surfaces_as_a_chart_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def broken(*_args: object) -> None:
        raise RuntimeError("binding bug")

    monkeypatch.setitem(b12.ACTIONS, "set_speed", broken)
    env = make_env()
    sid = (await env.s.create(USER_A, request(), prepare=True)).id
    await env.s.transition(USER_A, sid, "PLAY")
    with pytest.raises(ReplayChartError):
        await env.s.transition(USER_A, sid, "SET_SPEED", {"speed": 2})
    assert env.s.state_of(sid) == "playing"


# --- destroy and idle reclaim (INV-B12-e) ---------------------------------------------------


async def test_destroy_winds_down_releases_once_audits_and_is_idempotent() -> None:
    env = make_env()
    sid = (await env.s.create(USER_A, request(), prepare=True)).id
    await env.s.transition(USER_A, sid, "PLAY")  # B12.3: DESTROY is not handled in `playing`
    racing = await asyncio.gather(env.s.destroy(USER_A, sid), env.s.destroy(USER_A, sid))
    assert sorted(racing) == [False, True]
    assert await env.s.destroy(USER_A, sid) is False
    assert env.handles.released[sid] == 1 and env.s.state_of(sid) is None
    row = await env.repo.get(USER_A, sid)
    assert row is not None and row.state is ReplayState.DESTROYED and row.finished_at is not None
    destroyed = [kw for a, kw in env.audit.rows if a == "replay.session.destroyed"]
    assert [kw["reason"] for kw in destroyed] == ["client"]
    with pytest.raises(ReplaySessionIllegalUpdateError):
        await env.s.transition(USER_A, sid, "SEEK", SEEK_T0)


async def test_destroy_is_refused_when_the_audit_record_cannot_be_written() -> None:
    env = make_env()
    sid = (await env.s.create(USER_A, request())).id
    env.audit.fail = True
    with pytest.raises(ReplayUnavailableError):
        await env.s.destroy(USER_A, sid)
    assert env.handles.released[sid] == 0 and env.s.state_of(sid) == "created"


async def test_reclaim_idle_destroys_exactly_the_idle_set_once() -> None:
    env = make_env(cap=3)
    playing = (await env.s.create(USER_A, request(), prepare=True)).id
    await env.s.transition(USER_A, playing, "PLAY")  # idle while playing: PAUSE, then DESTROY
    created = (await env.s.create(USER_A, request())).id  # not in `ix_rps_live`: held in memory
    env.clock.advance(hours=3)
    fresh = (await env.s.create(USER_B, request(), prepare=True)).id
    assert await env.s.reclaim_idle(env.clock()) == 2
    assert await env.s.reclaim_idle(env.clock()) == 0  # a second pass is a no-op
    assert env.handles.released == Counter({playing: 1, created: 1})
    assert await state_in_db(env, USER_B, fresh) is ReplayState.PAUSED
    reasons = [kw["reason"] for a, kw in env.audit.rows if a == "replay.session.destroyed"]
    assert reasons == ["idle_reclaim", "idle_reclaim"]


async def test_the_reclaimer_runs_as_a_tracked_task_until_stopped() -> None:
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        await asyncio.sleep(0)

    env = make_env(sleep=fake_sleep)
    sid = (await env.s.create(USER_A, request())).id
    env.clock.advance(hours=3)
    await env.s.start()

    async def reclaimed() -> bool:
        return env.handles.released[sid] == 1

    await until(reclaimed)
    await env.s.stop()
    assert sleeps and set(sleeps) == {60.0}
    n = len(sleeps)
    await asyncio.sleep(0)
    assert len(sleeps) == n  # cancelled: nothing keeps sleeping after stop()


class _DownRepository(FakeReplaySessionRepository):
    async def list_idle_since(self, before: datetime, limit: int) -> Any:
        raise ConnectionError("database down")


async def test_the_module_lifecycle_owns_the_service_and_survives_a_boot_outage() -> None:
    from candleviewer.observability.health import HealthStatus
    from candleviewer.replay.service import ReplayService

    module, env = ReplayService(), make_env(repo=_DownRepository())
    assert module.health().detail == "replay sessions off"
    module.attach_sessions(env.s)
    await module.start(cast(Any, None))  # the outage is logged; the sessions revive on next use
    assert module.health().status is HealthStatus.OK
    assert (await env.s.create(USER_A, request(), prepare=True)).state is ReplayState.PAUSED
    await module.stop(1.0)
    assert module.health().status is HealthStatus.STOPPED


# --- restart survival (US-RPL-009) and async completions ------------------------------------


async def test_restart_without_a_snapshot_rebuilds_the_row_in_created() -> None:
    env = make_env()
    cursor = T0 + timedelta(minutes=5)
    sid = (await env.s.create(USER_A, request(cursor_ts=cursor), prepare=True)).id
    await env.s.transition(USER_A, sid, "PLAY")
    await env.s.stop()
    again = make_env(repo=env.repo)
    await again.s.start()
    assert again.s.state_of(sid) == "created" and again.handles.acquired == [sid]
    assert await state_in_db(again, USER_A, sid) is ReplayState.CREATED
    row = await again.s.transition(USER_A, sid, "PREPARE")
    assert (row.state, row.cursor_ts) == (ReplayState.PAUSED, cursor)
    await again.s.stop()


class _Sealed:
    """Snapshot store + HMAC keys + restore/persist audit fakes in one (test only)."""

    def __init__(self) -> None:
        self.saved: dict[Any, Any] = {}
        self.quarantined: list[str] = []

    async def write_snapshot(self, key: Any, envelope: Any) -> None:
        self.saved[key] = envelope

    async def load(self, key: Any) -> Any:
        return self.saved.get(key)

    def current(self) -> str:
        return "k1"

    def key(self, key_id: str) -> bytes:
        return b"\x07" * 32

    async def quarantine(self, key: Any, envelope: Any, reason: str) -> None:
        self.quarantined.append(reason)

    async def page(self, key: Any, severity: str, message: str) -> None:
        return None

    async def drain_error(self, key: Any, error: str) -> None:
        return None

    async def persist_refused(self, key: Any, reason: str) -> None:
        return None


async def test_restart_restores_a_sealed_snapshot_through_statechart_persistence() -> None:
    from candleviewer.statechart.factory import default_clock
    from candleviewer.statechart.persistence import (
        ChainTripLatch,
        InMemoryDrainJournal,
        Persister,
        Restorer,
        hmac_sealer,
    )  # fmt: skip
    from candleviewer.statechart.registry import Registry

    reg, sealed, journal = Registry(), _Sealed(), InMemoryDrainJournal()
    persist = Persister(
        repo=sealed, journal=journal, audit=sealed, seal=hmac_sealer(sealed, reg.get("replay")),
        machine_hash_of=reg.hash,
    )  # fmt: skip
    restore = Restorer(
        registry=reg, keys=sealed, journal=journal, audit=sealed, pager=sealed,
        latch=ChainTripLatch(), plugins=tuple, clock=default_clock(), lane="control",
    )  # fmt: skip
    kw: dict[str, Any] = {"persister": persist, "snapshots": sealed, "restorer": restore}
    env = make_env(**kw)
    sid = (await env.s.create(USER_A, request(), prepare=True)).id
    await env.s.stop()  # drain -> journal -> sealed snapshot -> stop (CV-C65')
    again = make_env(repo=env.repo, **kw)
    await again.s.start()
    assert again.s.state_of(sid) == "paused" and sealed.quarantined == []
    assert await state_in_db(again, USER_A, sid) is ReplayState.PAUSED
    assert (await again.s.transition(USER_A, sid, "PLAY")).state is ReplayState.PLAYING
    await again.s.stop()


async def test_a_slow_seek_can_be_cancelled_or_completes_later_and_is_mirrored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gate = asyncio.Event()
    primed = to_us(T0) + 7

    async def slow_seek(*_args: object) -> dict[str, Any]:
        await gate.wait()
        return {"cursor": primed, "coverage_gaps": [[to_us(T0), to_us(T0) + 1]]}

    monkeypatch.setitem(b12.SERVICES, "seek_and_prime", slow_seek)
    env = make_env()
    await env.s.start()
    cancelled = (await env.s.create(USER_A, request(), prepare=True)).id
    assert await state_in_db(env, USER_A, cancelled) is ReplayState.BUFFERING
    row = await env.s.transition(USER_A, cancelled, "CANCEL")
    assert row.state is ReplayState.PAUSED
    late = (await env.s.create(USER_A, request(), prepare=True)).id
    gate.set()

    async def mirrored() -> bool:
        row = await env.repo.get(USER_A, late)
        return row is not None and row.state is ReplayState.PAUSED

    await until(mirrored)
    late_row = await env.repo.get(USER_A, late)
    assert late_row is not None and to_us(late_row.cursor_ts or T1) == primed
    facts = env.s.facts_of(late)
    assert facts is not None and facts["coverage_gaps"] == [[to_us(T0), to_us(T0) + 1]]
    await env.s.stop()


# --- properties and audit -------------------------------------------------------------------

_EVENTS = ["PREPARE", "PLAY", "PAUSE", "STEP", "SEEK", "SET_SPEED", "CANCEL", "RANGE_END"]
_EVENTS += ["SOURCE_ERROR", "CONSUMER_SLOW", "DESTROY"]


async def _mirror_scenario(events: list[str]) -> None:
    env = make_env()
    sid = (await env.s.create(USER_A, request())).id
    for event in events:
        try:
            if event == "DESTROY":
                await env.s.destroy(USER_A, sid)
            else:
                await env.s.transition(USER_A, sid, event, _PAYLOADS.get(event))
        except ReplaySessionIllegalUpdateError:
            pass
        leaf = env.s.state_of(sid)
        assert (await state_in_db(env, USER_A, sid)).value == (leaf or "destroyed"), events
        assert env.handles.released[sid] == (0 if leaf else 1), events
    await env.s.stop()


@settings(max_examples=40, deadline=None)
@given(st.lists(st.sampled_from(_EVENTS), max_size=12))
def test_row_status_mirrors_the_machine_and_handles_release_exactly_once(
    events: list[str],
) -> None:
    asyncio.run(_mirror_scenario(events))


async def test_audit_rows_are_registered_attributed_and_carry_only_session_facts() -> None:
    from candleviewer.audit.actions import AUDIT_ACTIONS  # POSIX-only package (audit.journal)

    env = make_env()
    sid = (await env.s.create(USER_A, request(), prepare=True)).id
    await env.s.destroy(USER_A, sid)
    assert env.audit.actions() == ["replay.session.created", "replay.session.destroyed"]
    assert set(env.audit.actions()) <= AUDIT_ACTIONS  # the real writer refuses unregistered ones
    for _action, kw in env.audit.rows:
        assert (kw["actor_user_id"], kw["object_kind"], kw["object_id"]) == (
            USER_A, "replay_session", sid,
        )  # fmt: skip
        allowed = {"symbol", "state", "range_start", "range_end", "reason", "paper_account_id"}
        assert set(kw["after_state"]) <= allowed
