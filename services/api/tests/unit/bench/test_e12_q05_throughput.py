"""E12-Q05 slice 2 (#528): the throughput harness mechanics, with injected probes.
No real speed is asserted. Built on the BQ defaults; rulings pending."""

from __future__ import annotations

import pytest

from bench.bars import throughput as tp
from bench.bars.throughput import Probes, RunResult


class FakeClock:
    def __init__(self, step_ns: int) -> None:
        self.t, self.step = 0, step_ns

    def __call__(self) -> int:
        self.t += self.step
        return self.t


def _probes(step_ns: int = 1_000) -> Probes:
    return Probes(now_ns=FakeClock(step_ns), rss_kib=lambda: 2048, gc_collections=lambda: 7)


def test_six_families_in_production_set() -> None:
    kinds = [b.spec.kind for b in tp.make_builders()]
    assert kinds == ["time", "tick", "volume", "delta", "range", "renko"]


def test_tape_is_seeded_and_exact_length() -> None:
    a = [(t.trade_id, t.price, t.qty) for t in tp.tape(500)]
    b = [(t.trade_id, t.price, t.qty) for t in tp.tape(500)]
    assert len(a) == 500 and a == b


def test_run_counts_prints_and_closed_bars_per_kind() -> None:
    r = tp.run_once(tp.tape(3_000), tp.make_builders(), probes=_probes())
    assert r.prints == 3_000
    assert set(r.bars_by_kind) == {"time", "tick", "volume", "delta", "range", "renko"}
    assert r.bars_by_kind["tick"] == 3_000 // 100 or r.bars_by_kind["tick"] >= 29
    assert r.bars_by_kind["delta"] >= 1  # the buy skew makes the delta series active (BQ-03)


def test_run_is_deterministic_for_a_seed() -> None:
    a = tp.run_once(tp.tape(2_000), tp.make_builders(), probes=_probes())
    b = tp.run_once(tp.tape(2_000), tp.make_builders(), probes=_probes())
    assert a.bars_by_kind == b.bars_by_kind


def test_timing_uses_injected_clock_and_sampling_stride() -> None:
    r = tp.run_once(tp.tape(1_000), tp.make_builders(), probes=_probes(), sample_every=100)
    assert r.latency_us.n == 10
    assert r.latency_us.p50 == 1.0  # one clock step (1 000 ns) around each timed step
    assert r.elapsed_s > 0 and r.prints_per_s == pytest.approx(1_000 / r.elapsed_s)
    assert r.peak_rss_mib == 2.0 and r.gc_collections == 0


def test_warmup_prints_are_not_sampled() -> None:
    r = tp.run_once(
        tp.tape(1_000), tp.make_builders(), probes=_probes(), sample_every=100, warmup=500
    )
    assert r.latency_us.n == 5


@pytest.mark.parametrize("kw", [{"sample_every": 0}, {"warmup": -1}])
def test_bad_arguments_are_refused(kw: dict[str, int]) -> None:
    with pytest.raises(ValueError):
        tp.run_once(tp.tape(10), tp.make_builders(), probes=_probes(), **kw)


def test_median_of_runs_needs_three_and_picks_middle_rate() -> None:
    def res(rate: float) -> RunResult:
        base = tp.run_once(tp.tape(10), tp.make_builders(), probes=_probes())
        base.prints_per_s = rate
        return base

    runs = [res(300.0), res(100.0), res(200.0)]
    med, spread = tp.median_of_runs(runs)
    assert med.prints_per_s == 200.0 and spread == pytest.approx(1.0)
    with pytest.raises(ValueError):
        tp.median_of_runs(runs[:2])


def test_render_names_budget_and_carries_no_secret_shaped_text() -> None:
    r = tp.run_once(tp.tape(500), tp.make_builders(), probes=_probes())
    out = tp.render(500, r, 0.0)
    assert "budget #5" in out and "prints/s" in out and "[REDACTED]" not in out


def test_main_prints_a_report(capsys: pytest.CaptureFixture[str]) -> None:
    assert tp.main(["--prints", "300", "--sample-every", "10"]) == 0
    assert "builder throughput, 300 prints" in capsys.readouterr().out
