"""Rebuild throughput budget (#2022, US-CHART-003's NFR, `11-user-stories.md:935`): a rebuild
of 1M prints completes in <= 10 s. `@pytest.mark.perf`: the `py-perf` lane, never the unit project.

Scaling. A builder's cost per print is constant: it folds the print into its draft and builds a
`Bar` only for an open, a close or an amend (24 §3.2), so a rebuild's time is linear in its prints
and the NFR is a per-print budget, 10 s / 1M = 10 us. The test feeds `N_TRADES` (150 000) prints,
so its budget is `N_TRADES * 10 us` = 1.5 s of `process_time` per series (one builder, one spec).
`process_time` (CPU of this process) rather than wall time, so a busy runner's other processes do
not count against the builder; a scheduler stall cannot pass it, only fail it on a starved host.

What is timed: the builder alone over an in-memory tape, through `invariants.count`, the harness
throughput path that retains no emission (PROPOSED in 24 §3.2: measured on the CI Linux runner, no
retained output); tape generation is excluded. Every kind of the harness's standard spec matrix.
"""

from __future__ import annotations

import time

import pytest

from bench.bar_determinism import invariants
from bench.bar_determinism.generator import GenConfig, generate
from candleviewer.exchange.base.models import TradeEvent

#: Prints fed per series (100-200 k: the NFR's 1M scaled to a lane-sized run).
N_TRADES = 150_000
#: US-CHART-003 NFR: 1M prints in <= 10 s, i.e. 10 us of CPU per print.
NFR_SECONDS_PER_PRINT = 10.0 / 1_000_000
BUDGET_S = N_TRADES * NFR_SECONDS_PER_PRINT

_TAPE: list[TradeEvent] = []


def _tape() -> list[TradeEvent]:
    """The harness's seeded generator (default mix), built once per module, never at import."""
    if not _TAPE:
        _TAPE.extend(generate(GenConfig(n=N_TRADES)))
    return _TAPE


@pytest.mark.perf
@pytest.mark.parametrize("label", list(invariants.STANDARD_SPECS))
def test_rebuild_of_scaled_tape_meets_the_10s_per_million_nfr(label: str) -> None:
    tape = _tape()
    builder = invariants.make_builder(invariants.STANDARD_SPECS[label])
    t0 = time.process_time()
    emitted = invariants.count(builder, tape)
    spent = time.process_time() - t0
    assert emitted > 0  # the tape closes bars for every kind: the path was exercised
    assert spent <= BUDGET_S, (
        f"{label}: {N_TRADES:,} prints took {spent:.2f} s of CPU, budget {BUDGET_S:.2f} s "
        f"(US-CHART-003: 1M prints in 10 s, 11-user-stories.md:935)"
    )
