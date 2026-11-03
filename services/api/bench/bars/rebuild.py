"""Offline parameter-change rebuild check (E12-Q05 slice 3, #528; US-CHART-003 NFR <= 10 s).

A rebuild is a cold builder for the new spec replayed over the whole tape; this measures that
wall time for `renko:30 -> renko:45` and `volume:50 -> volume:200` over seeded synthetic prints
(Decimal, no network) and judges it against the 10 s budget. It needs no #535: the cancel latency
and "previous series stayed served throughout" legs are rendered as `pending #535` rows, to be
activated when the rebuild path and `bars_rebuild_duration_seconds` land. As in `throughput`, only
the builder loop is timed (the tape is generated in chunks outside the window), and the clock is
injected so the unit tests check mechanics, not speed.
The figure is a LOWER BOUND on the real rebuild: it excludes the store reads of the tape, row
decoding and persistence of the new generation (#535).
Run by hand: `python -m bench.bars.rebuild --prints 1000000` (3 runs; exit 1 over budget).
"""

from __future__ import annotations

import argparse
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from itertools import islice

import structlog

from bench.bar_determinism.generator import TICK
from bench.bars import throughput
from bench.bars.scrub import scrub
from bench.bars.stats import RUNS_PER_CONFIG, median_run, relative_spread
from bench.bars.throughput import Probes
from candleviewer.bars.builder_set import production_factory
from candleviewer.bars.spec import from_wire
from candleviewer.exchange.base.models import TradeEvent

BUDGET_S = 10.0  # US-CHART-003 NFR: a 1 M-print rebuild completes in <= 10 s
#: (bar_type, old param, new param): the two changes the ticket names.
CHANGES: tuple[tuple[str, str, str], ...] = (("renko", "30", "45"), ("volume", "50", "200"))
PENDING = (
    "cancel-to-released latency: pending #535",
    "previous series served throughout the rebuild: pending #535",
    "bars_rebuild_duration_seconds correlation: pending #535",
)


@dataclass(frozen=True, slots=True)
class RebuildResult:
    change: str
    prints: int
    bars: int
    elapsed_s: float

    @property
    def within_budget(self) -> bool:
        return self.elapsed_s <= BUDGET_S


def rebuild_once(
    bar_type: str,
    new_param: str,
    trades: Iterable[TradeEvent],
    *,
    probes: Probes | None = None,
    chunk: int = 4_096,
    old_param: str = "",
) -> RebuildResult:
    """Replay `trades` through a cold builder of `bar_type:new_param`; count closed bars."""
    if chunk < 1:
        raise ValueError("chunk must be >= 1")
    p = probes or Probes()
    factory = production_factory(lambda _s: TICK, renko_enabled=True)
    builder = factory(from_wire(bar_type, new_param), throughput.SYMBOL)
    n = bars = timed_ns = 0
    it = iter(trades)
    while batch := list(islice(it, chunk)):  # generation stays outside the timed window
        t0 = p.now_ns()
        for trade in batch:
            for upd in builder.on_trade(trade):
                bars += upd.kind == "close"
        timed_ns += p.now_ns() - t0
        n += len(batch)
    label = f"{bar_type}:{old_param} -> {bar_type}:{new_param}" if old_param else new_param
    return RebuildResult(label, n, bars, max(timed_ns, 1) / 1e9)


def median_rebuild(runs: list[RebuildResult]) -> tuple[RebuildResult, float]:
    """The median run by wall time and the relative spread across the three."""
    if len(runs) != RUNS_PER_CONFIG:
        raise ValueError(f"expected {RUNS_PER_CONFIG} runs, got {len(runs)}")
    secs = [r.elapsed_s for r in runs]
    mid = median_run(secs)
    return next(r for r in runs if r.elapsed_s == mid), relative_spread(secs)


def render(rows: list[tuple[RebuildResult, float]]) -> str:
    out = [
        f"## parameter-change rebuild, offline (US-CHART-003: <= {BUDGET_S:.0f} s, median of 3)",
        "",
        "Lower bound on the real rebuild: builder loop only; no tape store reads, row decoding "
        "or persistence of the new generation (#535).",
        "",
        "| change | prints | bars | wall s | spread | result |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for r, spread in rows:
        res = "pass" if r.within_budget else "FAIL"
        out.append(
            f"| {r.change} | {r.prints} | {r.bars} | {r.elapsed_s:.2f} | {spread * 100:.1f} % "
            f"| {res} |"
        )
    out += ["", *(f"- pending: {row}" for row in PENDING)]
    return scrub("\n".join(out))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--prints", type=int, default=1_000_000)
    a = ap.parse_args(argv)
    structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(logging.ERROR))
    rows = []
    for bar_type, old, new in CHANGES:
        runs = [
            rebuild_once(bar_type, new, throughput.tape(a.prints), old_param=old)
            for _ in range(RUNS_PER_CONFIG)
        ]
        rows.append(median_rebuild(runs))
    print(render(rows))
    return 0 if all(r.within_budget for r, _ in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
