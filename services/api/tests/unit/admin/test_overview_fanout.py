"""Unit (E42-T01): the admin read-model fan-out core. Every source has its own budget, a
failure only degrades its own slice (the response is never all-or-nothing), slices are cached
for their TTL on an injected clock, live slices bypass the cache, and every degraded slice is
logged and counted. No sleeps: hung sources await an event that never fires."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from prometheus_client import REGISTRY
from structlog.testing import capture_logs

from candleviewer.admin.overview.fanout import Degraded, SliceFanOut, SourceUnavailable
from candleviewer.admin.overview.metrics import export_overview_metrics, source_errors_total
from candleviewer.observability.context import bind_context
from candleviewer.observability.metrics import CollectorRegistry

SLICES = ("users", "accounts", "recorder", "storage", "trading", "incidents")
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
        self, value: int = 1, *, hang: bool = False, raises: Exception | None = None
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
    result = await _fan(clock).read("users", Source(4))
    assert (result.status, result.value, result.detail) == ("ok", 4, None)
    assert result.generated_at == clock.now()
    assert (await SliceFanOut().read("users", Source(4))).generated_at.tzinfo is UTC


async def test_timeout_yields_an_error_slice_naming_the_budget() -> None:
    result = await _fan(Clock(), budget_s=0.01).read("recorder", Source(hang=True))
    assert (result.status, result.value, result.detail) == ("error", None, "timed out after 10 ms")


async def test_exception_yields_an_error_slice_and_its_message_never_leaves() -> None:
    secret = RuntimeError("postgresql://cv:hunter2@db/candleviewer")
    with capture_logs() as logs:
        result = await _fan(Clock()).read("users", Source(raises=secret))
    assert (result.status, result.value, result.detail) == ("error", None, "source failed")
    assert "hunter2" not in repr(result) + repr(logs)
    assert logs[0]["reason"] == "RuntimeError"


async def test_unwired_source_yields_an_unavailable_slice() -> None:
    unwired = SourceUnavailable("open_positions: no provider wired")
    result = await _fan(Clock()).read("trading", Source(raises=unwired))
    assert (result.status, result.value) == ("unavailable", None)
    assert result.detail == "open_positions: no provider wired"


async def test_partial_source_keeps_what_it_read() -> None:
    async def partial() -> int | Degraded[int]:
        return Degraded(7, "unavailable", "open_positions: no provider wired")

    result = await _fan(Clock()).read("trading", partial)
    assert (result.status, result.value) == ("unavailable", 7)


@pytest.mark.parametrize("failing", SLICES)
@pytest.mark.parametrize("hang", [True, False], ids=["timeout", "exception"])
async def test_each_source_failing_in_turn_degrades_only_its_slice(
    failing: str, hang: bool
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
        fan.read("users", meets_the_other), fan.read("accounts", meets_the_other)
    )
    assert (first.status, second.status) == ("ok", "ok")


async def test_cancelling_the_request_cancels_the_read() -> None:
    entered = asyncio.Event()

    async def hangs() -> int:
        entered.set()
        await asyncio.Event().wait()
        return 0

    task = asyncio.create_task(_fan(Clock(), budget_s=5.0).read("users", hangs))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_a_slice_is_served_from_the_cache_for_its_ttl_then_read_again() -> None:
    clock, source = Clock(), Source(4)
    fan = _fan(clock)
    first = await fan.read("users", source)
    clock.advance(4.9)
    assert await fan.read("users", source) is first
    clock.advance(0.1)
    again = await fan.read("users", source)
    assert source.calls == 2
    assert again.generated_at == first.generated_at + timedelta(seconds=5)


async def test_live_slices_bypass_the_cache() -> None:
    source = Source(1)
    fan = _fan(Clock())
    for _ in range(3):
        await fan.read("trading", source, cached=False)
    assert source.calls == 3


async def test_an_error_is_cached_too_so_reloads_never_hammer_the_source() -> None:
    source = Source(raises=OSError("down"))
    fan = _fan(Clock())
    first = await fan.read("recorder", source)
    assert await fan.read("recorder", source) is first
    assert source.calls == 1


async def test_a_degraded_slice_logs_one_line_with_source_reason_and_request_id() -> None:
    with bind_context(request_id="req-42"), capture_logs() as logs:
        await _fan(Clock(), budget_s=0.01).read("recorder", Source(hang=True))
        await _fan(Clock()).read("users", Source(1))
    assert logs == [
        {
            "event": "admin_overview.slice_degraded",
            "source": "recorder",
            "status": "error",
            "reason": "timeout",
            "request_id": "req-42",
            "log_level": "warning",
        }
    ]


async def test_every_source_run_is_timed_and_only_errors_are_counted() -> None:
    errors_before, timed_before = _sample(_ERRORS, "probe_a"), _sample(_TIMED, "probe_a")
    unavailable_before = _sample(_ERRORS, "probe_b")
    fan = _fan(Clock())
    await fan.read("probe_a", Source(raises=OSError("down")), cached=False)
    await fan.read("probe_a", Source(1), cached=False)
    await fan.read("probe_b", Source(raises=SourceUnavailable("no provider wired")))
    assert _sample(_ERRORS, "probe_a") - errors_before == 1
    assert _sample(_TIMED, "probe_a") - timed_before == 2
    assert _sample(_ERRORS, "probe_b") == unavailable_before


def test_export_serves_the_series_with_the_env_label() -> None:
    registry = CollectorRegistry()
    collector = export_overview_metrics(registry, env="demo")
    source_errors_total.labels("probe_export").inc()
    labels = {"source": "probe_export", "env": "demo"}
    assert (registry.get_sample_value(_ERRORS, labels) or 0.0) >= 1.0
    collector.close()
