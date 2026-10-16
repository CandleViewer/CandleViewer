"""E17-T02 part B: CVWB decode benchmarks vs the 23 section 16.3 budgets (C-13.9).

Fastest-of-N ``perf_counter_ns`` with GC disabled; the sanity bounds are the section 16.3 *hard
fail* figures (0.5 ms book delta / 3 ms footprint), far above the measured cost, plus a
linear-scaling ratio so a quadratic regression cannot hide behind a generous absolute bound.
"""

from __future__ import annotations

import gc
import time
from collections.abc import Callable

import pytest

from candleviewer.ws.binary import Frame, decode, encode

BOOK_DELTA, FOOTPRINT = 2, 5
HARD_FAIL_DELTA_NS = 500_000
HARD_FAIL_FOOTPRINT_NS = 3_000_000


def _best_ns(fn: Callable[[], object], rounds: int = 15, inner: int = 20) -> float:
    gc.collect()
    gc.disable()
    try:
        best = float("inf")
        for _ in range(rounds):
            t0 = time.perf_counter_ns()
            for _ in range(inner):
                fn()
            best = min(best, (time.perf_counter_ns() - t0) / inner)
    finally:
        gc.enable()
    return best


def _delta(n: int) -> bytes:
    rec = tuple((i % 2, 6_500_000 + i, 1_000 + i) for i in range(n))
    return encode(Frame(BOOK_DELTA, rec, 0, 2, 3, 1_700_000_000_000))


def _footprint(cells: int) -> bytes:
    rec = tuple((6_500_000 + i, 10 + i, 20 + i, 1, 2) for i in range(cells))
    return encode(Frame(FOOTPRINT, (), 0, 2, 3, 1_700_000_000_000, groups=(((0, 0, 0, 0), rec),)))


@pytest.mark.perf
def test_decode_book_delta_50_levels_is_far_inside_the_hard_fail() -> None:
    data = _delta(50)
    got = _best_ns(lambda: decode(data))
    assert 0 < got < HARD_FAIL_DELTA_NS


@pytest.mark.perf
def test_decode_footprint_400_cells_is_far_inside_the_hard_fail() -> None:
    data = _footprint(400)
    got = _best_ns(lambda: decode(data))
    assert 0 < got < HARD_FAIL_FOOTPRINT_NS


@pytest.mark.perf
def test_decode_scales_linearly_with_record_count() -> None:
    d_small, d_large = _delta(100), _delta(800)
    small = _best_ns(lambda: decode(d_small))
    large = _best_ns(lambda: decode(d_large))
    assert small > 0
    assert large / small < 8 * 2.5, f"x8 records cost x{large / small:.1f}"
