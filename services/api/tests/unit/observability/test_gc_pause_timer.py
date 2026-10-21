"""#3641: `GcPauseTimer` times each garbage collection into `cv_gc_pause_seconds{generation}` and,
after a full one, reads the heap into `cv_gc_heap_blocks` (C-2.17: a full collection blocks the
loop of the thread that runs it)."""

from __future__ import annotations

import gc
from collections.abc import Iterator

import pytest

from candleviewer.observability.metrics import Metrics
from candleviewer.observability.metrics_catalogue import register_r0
from candleviewer.observability.metrics_runtime import GcPauseTimer


def _stop(generation: int) -> dict[str, int]:
    return {"generation": generation, "collected": 0, "uncollectable": 0}


@pytest.fixture
def metrics() -> Metrics:
    return Metrics("demo")


def _timer(m: Metrics, clock: Iterator[float], reads: list[int]) -> GcPauseTimer:
    r = register_r0(m)

    def blocks() -> int:
        reads.append(4096)
        return 4096

    return GcPauseTimer(
        r["cv_gc_pause_seconds"], r["cv_gc_heap_blocks"], clock=lambda: next(clock), blocks=blocks
    )


def _sample(m: Metrics, name: str, **labels: str) -> float | None:
    return m.registry.get_sample_value(name, {"env": "demo", **labels})


def test_gc_pause_timer_observes_each_pause_under_its_generation(metrics: Metrics) -> None:
    timer = _timer(metrics, iter([1.0, 1.25, 2.0, 2.01]), [])
    for generation in (2, 0):
        timer("start", {"generation": generation})
        timer("stop", _stop(generation))
    pauses = {g: _sample(metrics, "cv_gc_pause_seconds_sum", generation=g) for g in "012"}
    assert pauses == {"0": pytest.approx(0.01), "1": 0.0, "2": 0.25}
    assert _sample(metrics, "cv_gc_pause_seconds_count", generation="2") == 1


def test_gc_pause_timer_reads_the_heap_after_a_full_collection_only(metrics: Metrics) -> None:
    reads: list[int] = []
    timer = _timer(metrics, iter([0.0, 0.1, 0.2, 0.3, 0.4, 0.5]), reads)
    for generation in (0, 1, 2):
        timer("start", {"generation": generation})
        timer("stop", _stop(generation))
    assert reads == [4096] and _sample(metrics, "cv_gc_heap_blocks") == 4096


def test_gc_pause_timer_times_a_real_full_collection_until_removed(metrics: Metrics) -> None:
    r = register_r0(metrics)
    timer = GcPauseTimer(r["cv_gc_pause_seconds"], r["cv_gc_heap_blocks"])
    timer.install()
    timer.install()  # once
    try:
        assert gc.callbacks.count(timer) == 1
        gc.collect(2)
        assert (_sample(metrics, "cv_gc_pause_seconds_count", generation="2") or 0) >= 1
        assert (_sample(metrics, "cv_gc_heap_blocks") or 0) > 0
    finally:
        timer.remove()
    before = _sample(metrics, "cv_gc_pause_seconds_count", generation="2")
    gc.collect(2)  # an automatic collection may run anywhere above; none is timed from here on
    assert timer not in gc.callbacks
    assert _sample(metrics, "cv_gc_pause_seconds_count", generation="2") == before
