"""E12-Q05 slice 2 (#528): the throughput harness mechanics, with injected probes.
No real speed is asserted. BQ ruling of record: #528, 15:33Z."""

from __future__ import annotations

import pytest

from bench.bar_determinism.invariants import STANDARD_SPECS
from bench.bars import throughput as tp
from bench.bars.throughput import Probes, RunResult


class FakeClock:
    def __init__(self, step_ns: int) -> None:
        self.t, self.step = 0, step_ns

    def __call__(self) -> int:
        self.t += self.step
        return self.t


def _probes(step_ns: int = 1_000) -> Probes:
    return Probes(now_ns=FakeClock(step_ns), peak_rss_mib=lambda: 2.0, gc_collections=lambda: 7)


def test_builders_are_the_t04_standard_matrix_over_six_kinds() -> None:
    builders = tp.make_builders()
    assert [b.spec for b in builders] == list(STANDARD_SPECS.values())
    assert {b.spec.kind for b in builders} == {"time", "tick", "volume", "range", "delta", "renko"}


def test_tape_is_seeded_and_exact_length() -> None:
    a = [(t.trade_id, t.price, t.qty) for t in tp.tape(500)]
    b = [(t.trade_id, t.price, t.qty) for t in tp.tape(500)]
    assert len(a) == 500 and a == b


def test_run_counts_prints_and_closed_bars_per_kind() -> None:
    r = tp.run_once(tp.tape(3_000), tp.make_builders(), probes=_probes())
    assert r.prints == 3_000
    assert set(r.bars_by_kind) == {"time", "tick", "volume", "delta", "range", "renko"}
    assert (
        0 < r.bars_by_kind["tick"] <= 3_000 // 100 + 3_000 // 1_000
    )  # two tick specs; drops lower it
    assert r.bars_by_kind["delta"] >= 1  # the buy skew makes the delta series active (BQ-03)


def test_run_is_deterministic_for_a_seed() -> None:
    a = tp.run_once(tp.tape(2_000), tp.make_builders(), probes=_probes())
    b = tp.run_once(tp.tape(2_000), tp.make_builders(), probes=_probes())
    assert a.bars_by_kind == b.bars_by_kind


def test_timing_uses_injected_clock_and_sampling_stride() -> None:
    r = tp.run_once(tp.tape(1_000), tp.make_builders(), probes=_probes(), sample_every=100)
    assert r.latency_us.n == 10
    assert r.latency_us.p50 == 1.0  # one clock step (1 000 ns) around each timed step
    assert r.peak_rss_mib == 2.0 and r.gc_collections == 0


def test_elapsed_and_rate_come_from_the_injected_clock_over_the_timed_loop_only() -> None:
    # One chunk, no samples: the timed window is one clock step, whatever the tape cost.
    r = tp.run_once(tp.tape(1_000), tp.make_builders(), probes=_probes(), sample_every=10**9)
    assert r.elapsed_s == pytest.approx(1e-6)
    assert r.prints_per_s == pytest.approx(1_000 / 1e-6)


def test_throughput_window_excludes_warmup_prints() -> None:
    r = tp.run_once(
        tp.tape(1_000), tp.make_builders(), probes=_probes(), sample_every=10**9, warmup=400
    )
    assert (r.prints, r.measured) == (1_000, 600)
    assert r.prints_per_s == pytest.approx(600 / r.elapsed_s)


def test_chunking_sums_timed_segments_and_never_times_generation() -> None:
    r = tp.run_once(
        tp.tape(1_000), tp.make_builders(), probes=_probes(), sample_every=10**9, chunk=250
    )
    assert r.elapsed_s == pytest.approx(4e-6)  # four chunks, one step each
    assert r.prints == r.measured == 1_000


def test_warmup_prints_are_not_sampled() -> None:
    r = tp.run_once(
        tp.tape(1_000), tp.make_builders(), probes=_probes(), sample_every=100, warmup=500
    )
    assert r.latency_us.n == 5


@pytest.mark.parametrize("kw", [{"sample_every": 0}, {"warmup": -1}, {"chunk": 0}])
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
