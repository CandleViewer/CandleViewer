"""Unit (E42-T01): the admin read-model fan-out core. Every source has its own budget, a
failure only degrades its own slice (the response is never all-or-nothing), slices are cached
for their TTL on an injected clock, live slices bypass the cache, and every degraded slice is
logged and counted. No sleeps: hung sources await an event that never fires."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import cast

import pytest
from prometheus_client import REGISTRY
from structlog.testing import capture_logs

from candleviewer.admin.overview.fanout import (
    _REASON_MAX,
    DEFAULT_BUDGET_S,
    Degraded,
    PartFailed,
    Problem,
    SliceFanOut,
    SourceUnavailable,
    combine,
    read_part,
)
from candleviewer.admin.overview.metrics import export_overview_metrics, source_errors_total
from candleviewer.admin.overview.slices import CAPACITY_SLICES, OVERVIEW_SLICES, AdminSlice
from candleviewer.observability.context import bind_context
from candleviewer.observability.metrics import CollectorRegistry

SLICES = sorted(OVERVIEW_SLICES)
_ERRORS = "cv_admin_overview_source_errors_total"
_TIMED = "cv_admin_overview_source_duration_seconds_count"


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0
        self.base = datetime(2026, 10, 15, 18, 0, tzinfo=UTC)

    def monotonic(self) -> float:
        return self.t

    def now(self) -> datetime:
        return self.base + timedelta(seconds=self.t - 1000.0)

    def advance(self, seconds: float) -> None:
        self.t += seconds


class Source:
    """A fake source: answers `value`, raises `raises`, or hangs forever; counts its calls."""

    def __init__(
        self, value: int = 1, *, hang: bool = False, raises: BaseException | None = None
    ) -> None:
        self.value, self.hang, self.raises, self.calls = value, hang, raises, 0

    async def __call__(self) -> int:
        self.calls += 1
        if self.raises is not None:
            raise self.raises
        if self.hang:
            await asyncio.Event().wait()
        return self.value


def _fan(clock: Clock, budget_s: float = 0.3) -> SliceFanOut:
    return SliceFanOut(budget_s=budget_s, monotonic=clock.monotonic, now=clock.now)


def _sample(name: str, source: str) -> float:
    return REGISTRY.get_sample_value(name, {"source": source}) or 0.0


async def test_ok_slice_carries_its_value_and_generated_at() -> None:
    clock = Clock()
    result = await _fan(clock).read(AdminSlice.USERS, Source(4))
    assert (result.status, result.value, result.detail) == ("ok", 4, None)
    assert result.generated_at == clock.now()
    assert (await SliceFanOut().read(AdminSlice.USERS, Source(4))).generated_at.tzinfo is UTC


async def test_timeout_yields_an_error_slice_naming_the_budget() -> None:
    result = await _fan(Clock(), budget_s=0.01).read(AdminSlice.RECORDER, Source(hang=True))
    assert (result.status, result.value, result.detail) == ("error", None, "timed out after 10 ms")


async def test_exception_yields_an_error_slice_and_its_message_never_leaves() -> None:
    secret = RuntimeError("postgresql://cv:hunter2@db/candleviewer")
    with capture_logs() as logs:
        result = await _fan(Clock()).read(AdminSlice.USERS, Source(raises=secret))
    assert (result.status, result.value, result.detail) == ("error", None, "source failed")
    assert "hunter2" not in repr(result) + repr(logs)
    assert logs[0]["reason"] == "RuntimeError"


async def test_unwired_source_yields_an_unavailable_slice() -> None:
    unwired = SourceUnavailable("open_positions: no provider wired")
    result = await _fan(Clock()).read(AdminSlice.TRADING, Source(raises=unwired))
    assert (result.status, result.value) == ("unavailable", None)
    assert result.detail == "open_positions: no provider wired"


async def test_partial_source_keeps_what_it_read() -> None:
    async def partial() -> int | Degraded[int]:
        return Degraded(7, "unavailable", "open_positions: no provider wired")

    result = await _fan(Clock()).read(AdminSlice.TRADING, partial)
    assert (result.status, result.value) == ("unavailable", 7)


@pytest.mark.parametrize("failing", SLICES)
@pytest.mark.parametrize("hang", [True, False], ids=["timeout", "exception"])
async def test_each_source_failing_in_turn_degrades_only_its_slice(
    failing: AdminSlice, hang: bool
) -> None:
    def source(name: str) -> Source:
        if name != failing:
            return Source(1)
        return Source(hang=True) if hang else Source(raises=OSError("down"))

    fan = _fan(Clock(), budget_s=0.01)
    results = await asyncio.gather(*(fan.read(name, source(name)) for name in SLICES))
    by_name = dict(zip(SLICES, results, strict=True))
    assert by_name.pop(failing).status == "error"
    assert {(r.status, r.value) for r in by_name.values()} == {("ok", 1)}


async def test_sources_are_read_concurrently() -> None:
    both = asyncio.Barrier(2)

    async def meets_the_other() -> int:
        await both.wait()  # read one after the other, the first would time out here
        return 1

    fan = _fan(Clock(), budget_s=1.0)
    first, second = await asyncio.gather(
        fan.read(AdminSlice.USERS, meets_the_other), fan.read(AdminSlice.ACCOUNTS, meets_the_other)
    )
    assert (first.status, second.status) == ("ok", "ok")


async def test_cancelling_the_request_cancels_the_read() -> None:
    entered = asyncio.Event()

    async def hangs() -> int:
        entered.set()
        await asyncio.Event().wait()
        return 0

    task = asyncio.create_task(_fan(Clock(), budget_s=5.0).read(AdminSlice.USERS, hangs))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_a_slice_is_served_from_the_cache_for_its_ttl_then_read_again() -> None:
    clock, source = Clock(), Source(4)
    fan = _fan(clock)
    first = await fan.read(AdminSlice.USERS, source)
    clock.advance(4.9)
    assert await fan.read(AdminSlice.USERS, source) is first
    clock.advance(0.1)
    again = await fan.read(AdminSlice.USERS, source)
    assert source.calls == 2
    assert again.generated_at == first.generated_at + timedelta(seconds=5)


async def test_live_slices_bypass_the_cache() -> None:
    source = Source(1)
    fan = _fan(Clock())
    for _ in range(3):
        await fan.read(AdminSlice.TRADING, source, cached=False)
    assert source.calls == 3


async def test_an_error_is_cached_too_so_reloads_never_hammer_the_source() -> None:
    source = Source(raises=OSError("down"))
    fan = _fan(Clock())
    first = await fan.read(AdminSlice.RECORDER, source)
    assert await fan.read(AdminSlice.RECORDER, source) is first
    assert source.calls == 1


async def test_a_degraded_slice_logs_one_line_with_source_reason_and_request_id() -> None:
    with bind_context(request_id="req-42"), capture_logs() as logs:
        await _fan(Clock(), budget_s=0.01).read(AdminSlice.RECORDER, Source(hang=True))
        await _fan(Clock()).read(AdminSlice.USERS, Source(1))
    assert logs == [
        {
            "event": "admin_overview.slice_degraded",
            "source": AdminSlice.RECORDER,
            "status": "error",
            "reason": "timeout",
            "request_id": "req-42",
            "log_level": "warning",
        }
    ]


async def test_every_source_run_is_timed_and_only_errors_are_counted() -> None:
    errors_before = _sample(_ERRORS, AdminSlice.INGESTION)
    timed_before = _sample(_TIMED, AdminSlice.INGESTION)
    unavailable_before = _sample(_ERRORS, AdminSlice.RATE_BUDGET)
    fan = _fan(Clock())
    await fan.read(AdminSlice.INGESTION, Source(raises=OSError("down")), cached=False)
    await fan.read(AdminSlice.INGESTION, Source(1), cached=False)
    await fan.read(AdminSlice.RATE_BUDGET, Source(raises=SourceUnavailable("no provider wired")))
    assert _sample(_ERRORS, AdminSlice.INGESTION) - errors_before == 1
    assert _sample(_TIMED, AdminSlice.INGESTION) - timed_before == 2
    assert _sample(_ERRORS, AdminSlice.RATE_BUDGET) == unavailable_before


def test_export_serves_the_series_with_the_env_label() -> None:
    registry = CollectorRegistry()
    collector = export_overview_metrics(registry, env="demo")
    source_errors_total.labels(AdminSlice.SUBACCOUNTS).inc()
    labels = {"source": "subaccounts", "env": "demo"}
    assert (registry.get_sample_value(_ERRORS, labels) or 0.0) >= 1.0
    collector.close()


async def test_the_default_budget_is_the_tickets_300_ms() -> None:
    assert DEFAULT_BUDGET_S == 0.3 and SliceFanOut().budget_s == DEFAULT_BUDGET_S
    result = await SliceFanOut().read(AdminSlice.RECORDER, Source(hang=True))
    assert result.detail == f"timed out after {round(DEFAULT_BUDGET_S * 1000)} ms"


@pytest.mark.parametrize(
    "raised", [TimeoutError(), asyncio.CancelledError()], ids=["own-timeout", "stray-cancel"]
)
async def test_a_source_raising_timeout_or_cancel_itself_only_fails_its_slice(
    raised: BaseException,
) -> None:
    result = await _fan(Clock()).read(AdminSlice.USERS, Source(raises=raised))
    assert (result.status, result.detail) == ("error", "source failed")


async def test_concurrent_cold_reads_share_one_source_call() -> None:
    entered, gate, source = asyncio.Event(), asyncio.Event(), Source(7)

    async def slow() -> int:
        entered.set()
        await gate.wait()
        return await source()

    async def release() -> None:
        await entered.wait()
        gate.set()

    fan = _fan(Clock(), budget_s=5.0)
    *results, _ = await asyncio.gather(
        *(fan.read(AdminSlice.USERS, slow) for _ in range(50)), release()
    )
    assert source.calls == 1 and {r.value for r in results if r is not None} == {7}


async def test_followers_rerun_the_source_when_the_leader_is_cancelled() -> None:
    entered, calls = asyncio.Event(), [0]

    async def slow() -> int:
        calls[0] += 1
        if calls[0] == 1:
            entered.set()
            await asyncio.Event().wait()
        return calls[0]

    fan = _fan(Clock(), budget_s=5.0)
    leader = asyncio.create_task(fan.read(AdminSlice.USERS, slow))
    await entered.wait()
    follower = asyncio.create_task(fan.read(AdminSlice.USERS, slow))
    quitter = asyncio.create_task(fan.read(AdminSlice.USERS, slow))
    joined = asyncio.Event()
    asyncio.get_running_loop().call_soon(joined.set)  # runs once both followers have joined
    await joined.wait()
    quitter.cancel()  # a follower's own cancellation propagates and leaves the leader running
    leader.cancel()
    for cancelled in (quitter, leader):
        with pytest.raises(asyncio.CancelledError):
            await cancelled
    assert (await follower).value == 2


@pytest.mark.parametrize("detail", ["", "x" * 201, "dsn://user@host"], ids=["empty", "long", "dsn"])
async def test_an_invalid_detail_fails_the_slice_instead_of_leaking(detail: str) -> None:
    async def unavailable() -> int:
        raise SourceUnavailable(detail)

    async def partial() -> int | Degraded[int]:
        return Degraded(1, "unavailable", detail)

    fan = _fan(Clock())
    first, second = await asyncio.gather(
        fan.read(AdminSlice.USERS, unavailable), fan.read(AdminSlice.ACCOUNTS, partial)
    )
    assert {(r.status, r.detail) for r in (first, second)} == {("error", "source failed")}


async def test_invalidate_refetches_and_never_caches_a_read_that_predates_it() -> None:
    entered, gate, source = asyncio.Event(), asyncio.Event(), Source(1)

    async def slow() -> int:
        entered.set()
        await gate.wait()
        return await source()

    fan = _fan(Clock(), budget_s=5.0)

    async def invalidate_then_release() -> None:
        await entered.wait()
        fan.invalidate(AdminSlice.SUBACCOUNTS)
        gate.set()

    await asyncio.gather(fan.read(AdminSlice.SUBACCOUNTS, slow), invalidate_then_release())
    await fan.read(AdminSlice.SUBACCOUNTS, slow)  # the first result was not cached
    fan.invalidate(AdminSlice.SUBACCOUNTS)
    await fan.read(AdminSlice.SUBACCOUNTS, slow)
    assert source.calls == 3


async def test_a_live_read_never_joins_a_read_in_flight() -> None:
    state, entered, gate, seen = {"killed": False}, asyncio.Event(), asyncio.Event(), []

    async def kill_switch() -> bool:
        seen.append(value := state["killed"])
        if len(seen) == 1:  # the first read is still in flight when the switch flips
            entered.set()
            await gate.wait()
        return value

    fan = _fan(Clock(), budget_s=5.0)
    first = asyncio.create_task(fan.read(AdminSlice.TRADING, kill_switch, cached=False))
    await entered.wait()
    state["killed"] = True
    later = await fan.read(AdminSlice.TRADING, kill_switch, cached=False)
    gate.set()
    assert ((await first).value, later.value) == (False, True)


async def test_an_unknown_slice_name_is_refused_at_runtime() -> None:
    with pytest.raises(ValueError):
        await _fan(Clock()).read(cast(AdminSlice, "bogus"), Source(1))


def test_slice_sets_are_explicit_disjoint_and_cover_the_enum() -> None:
    assert OVERVIEW_SLICES.isdisjoint(CAPACITY_SLICES)
    assert OVERVIEW_SLICES | CAPACITY_SLICES == set(AdminSlice)


async def test_a_partial_slice_logs_its_reason_never_a_message() -> None:
    async def partial() -> int | Degraded[int]:
        return Degraded(1, "error", "open_positions: source failed", "open_positions:OSError")

    with capture_logs() as logs:
        await _fan(Clock()).read(AdminSlice.TRADING, partial)
    assert [(e["source"], e["reason"]) for e in logs] == [
        (AdminSlice.TRADING, "open_positions:OSError")
    ]


async def test_a_dsn_shaped_reason_is_refused_and_fails_the_slice() -> None:
    async def leaky() -> int | Degraded[int]:
        return Degraded(1, "error", "part: source failed", "part:dsn://u:pw@db/x")

    result = await _fan(Clock()).read(AdminSlice.TRADING, leaky)
    assert (result.status, result.value, result.detail) == ("error", None, "source failed")


class Corrupt(PartFailed):
    detail = "unrecognised value"


@pytest.mark.parametrize(
    ("raised", "problem"),
    [
        (
            SourceUnavailable("part: no provider wired"),
            ("unavailable", "part: no provider wired", "part:unwired"),
        ),
        (Corrupt(), ("error", "part: unrecognised value", "part:Corrupt")),
        (OSError("postgresql://u:hunter2@db/x"), ("error", "part: source failed", "part:OSError")),
        (asyncio.CancelledError(), ("error", "part: source failed", "part:CancelledError")),
        (TimeoutError(), ("error", "part: source failed", "part:TimeoutError")),
    ],
    ids=["unavailable", "fixed-detail", "class-only-reason", "stray-cancel", "own-timeout"],
)
async def test_read_part_maps_a_failure_to_a_fixed_problem(
    raised: BaseException, problem: tuple[str, str, str]
) -> None:
    assert await read_part("part", Source(raises=raised), 1.0) == (None, problem)


async def test_read_part_returns_the_value_or_times_out_on_its_own_budget() -> None:
    assert await read_part("part", Source(4), 1.0) == (4, None)
    timed_out = ("error", "part: timed out", "part:TimeoutError")
    assert await read_part("part", Source(hang=True), 0.01) == (None, timed_out)


def test_combine_prefers_the_error_and_joins_every_reason() -> None:
    assert combine(1, [None, None]) == 1
    down: Problem = ("unavailable", "a: no provider wired", "a:unwired")
    failed: Problem = ("error", "b: source failed", "b:OSError")
    assert combine(1, [down, failed]) == Degraded(
        1, "error", "b: source failed", "a:unwired--b:OSError"
    )
    long: Problem = ("error", "x: source failed", "x:" + "E" * 70)
    assert len(combine(1, [long, long]).reason) == _REASON_MAX  # type: ignore[union-attr]  # Degraded here


async def test_read_part_lets_a_real_cancellation_through() -> None:
    entered = asyncio.Event()

    async def hangs() -> int:
        entered.set()
        await asyncio.Event().wait()
        return 0

    task = asyncio.create_task(read_part("part", hangs, 5.0))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
