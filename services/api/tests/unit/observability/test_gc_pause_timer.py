"""#3641: `GcPauseTimer` times each garbage collection into `cv_gc_pause_seconds{generation}` and,
after a full one, reads the heap proxy into `cv_gc_blocks_in_use` (C-2.17: under the GIL a full
collection on any thread stalls the event loop)."""

from __future__ import annotations

import gc
from collections.abc import Iterator

import pytest

from candleviewer.observability.metrics import Metrics
from candleviewer.observability.metrics_catalogue import CATALOGUE, register_r0
from candleviewer.observability.metrics_runtime import GcPauseTimer


@pytest.fixture(autouse=True)
def _callbacks() -> Iterator[None]:
    """Whatever a test does, `gc.callbacks` is as it found it."""
    saved = gc.callbacks[:]
    yield
    gc.callbacks[:] = saved


@pytest.fixture
def metrics() -> Metrics:
    return Metrics("demo")


def _stop(generation: int) -> dict[str, int]:
    return {"generation": generation, "collected": 0, "uncollectable": 0}


def _timer(m: Metrics, clock: Iterator[float], blocks: Iterator[int]) -> GcPauseTimer:
    r = register_r0(m)
    return GcPauseTimer(
        r["cv_gc_pause_seconds"],
        r["cv_gc_blocks_in_use"],
        clock=lambda: next(clock),
        blocks=lambda: next(blocks),
    )


def _real(m: Metrics) -> GcPauseTimer:
    r = register_r0(m)
    return GcPauseTimer(r["cv_gc_pause_seconds"], r["cv_gc_blocks_in_use"])


def _sample(m: Metrics, name: str, **labels: str) -> float:
    return m.registry.get_sample_value(name, {"env": "demo", **labels}) or 0.0


def _full_collections(m: Metrics) -> float:
    return _sample(m, "cv_gc_pause_seconds_count", generation="2")


def test_gc_pause_timer_observes_each_pause_under_its_generation(metrics: Metrics) -> None:
    timer = _timer(metrics, iter([1.0, 1.25, 2.0, 2.01]), iter([4096]))
    for generation in (2, 0):
        timer("start", {"generation": generation})
        timer("stop", _stop(generation))
    pauses = {g: _sample(metrics, "cv_gc_pause_seconds_sum", generation=g) for g in "012"}
    assert pauses == {"0": pytest.approx(0.01), "1": 0.0, "2": 0.25}
    assert _full_collections(metrics) == 1


def test_gc_pause_timer_reads_the_heap_after_a_full_collection_only(metrics: Metrics) -> None:
    timer = _timer(metrics, iter([0.0, 0.1, 0.2, 0.3, 0.4, 0.5]), iter([4096]))
    for generation in (0, 1, 2):  # a second read would exhaust the iterator
        timer("start", {"generation": generation})
        timer("stop", _stop(generation))
    assert _sample(metrics, "cv_gc_blocks_in_use") == 4096


def test_gc_pause_timer_heap_gauge_holds_the_latest_full_collection(metrics: Metrics) -> None:
    timer = _timer(metrics, iter([0.0, 0.1, 0.2, 0.3]), iter([4096, 1024]))
    for _ in range(2):
        timer("start", {"generation": 2})
        timer("stop", _stop(2))
    assert _sample(metrics, "cv_gc_blocks_in_use") == 1024


def test_gc_pause_timer_skips_a_stop_without_its_start(metrics: Metrics) -> None:
    timer = _timer(metrics, iter([5.0, 5.5]), iter([4096, 4096]))
    timer("stop", _stop(2))  # installed mid-collection: no start was seen
    timer("start", {"generation": 2})
    timer("stop", _stop(2))
    timer("stop", _stop(2))  # a second stop for the same start
    assert _full_collections(metrics) == 1
    assert _sample(metrics, "cv_gc_pause_seconds_sum", generation="2") == 0.5


def test_gc_pause_timer_hands_each_pause_to_its_hook(metrics: Metrics) -> None:
    seen: list[tuple[int, float]] = []
    r = register_r0(metrics)
    timer = GcPauseTimer(
        r["cv_gc_pause_seconds"],
        r["cv_gc_blocks_in_use"],
        clock=iter([1.0, 1.5, 2.0, 2.25]).__next__,
        blocks=lambda: 4096,
        on_pause=lambda generation, pause: seen.append((generation, pause)),
    )
    for generation in (2, 0):
        timer("start", {"generation": generation})
        timer("stop", _stop(generation))
    assert seen == [(2, 0.5), (0, 0.25)]


def test_gc_pause_timer_installs_once_and_removes_only_itself(metrics: Metrics) -> None:
    def other(phase: str, info: dict[str, int]) -> None:
        del phase, info

    timer = _real(metrics)
    gc.callbacks.append(other)
    timer.install()
    timer.install()
    assert gc.callbacks.count(timer) == 1
    timer.remove()
    timer.remove()  # a second remove, or one never installed, is a no-op
    assert timer not in gc.callbacks and other in gc.callbacks


def test_gc_pause_timer_times_a_real_full_collection_while_installed(metrics: Metrics) -> None:
    timer = _real(metrics)
    timer.install()
    for _ in range(3):  # a collection already running on another thread makes this one a no-op
        gc.collect(2)
        if _full_collections(metrics) >= 1:
            break
    assert _full_collections(metrics) >= 1
    assert 0 < _sample(metrics, "cv_gc_pause_seconds_sum", generation="2") < 60
    assert _sample(metrics, "cv_gc_blocks_in_use") > 10_000


def test_gc_pause_timer_times_nothing_once_removed(metrics: Metrics) -> None:
    timer = _real(metrics)
    timer.install()
    timer.remove()
    gc.collect(2)
    assert _full_collections(metrics) == 0


def test_gc_pause_histogram_is_bounded_and_brackets_the_loop_budget() -> None:
    spec = next(s for s in CATALOGUE if s.name == "cv_gc_pause_seconds")
    assert (spec.labels, spec.max_series) == (("generation",), 3)
    assert spec.buckets is not None and {0.05, 0.1} <= set(spec.buckets)
