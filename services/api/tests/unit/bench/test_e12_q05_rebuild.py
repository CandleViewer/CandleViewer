"""E12-Q05 slice 3 (#528): rebuild check mechanics with an injected clock; no real speed is
asserted. Built on the BQ defaults; rulings pending."""

from __future__ import annotations

import pytest

from bench.bars import rebuild as rb
from bench.bars import throughput as tp
from bench.bars.rebuild import RebuildResult
from bench.bars.throughput import Probes


def _probes(step_ns: int) -> Probes:
    t = [0]

    def now() -> int:
        t[0] += step_ns
        return t[0]

    return Probes(now_ns=now, peak_rss_mib=lambda: 0.0, gc_collections=lambda: 0)


def test_changes_are_the_two_named_in_the_ticket() -> None:
    assert [(t, o, n) for t, o, n in rb.CHANGES] == [("renko", "30", "45"), ("volume", "50", "200")]
    assert rb.BUDGET_S == 10.0


def test_rebuild_counts_prints_and_bars_and_is_seeded() -> None:
    a = rb.rebuild_once("renko", "45", tp.tape(3_000), probes=_probes(1_000))
    b = rb.rebuild_once("renko", "45", tp.tape(3_000), probes=_probes(1_000))
    assert a.prints == 3_000 and a.bars > 0 and (a.bars, a.prints) == (b.bars, b.prints)


def test_rebuild_wall_time_is_the_sum_of_timed_chunks_only() -> None:
    r = rb.rebuild_once("volume", "200", tp.tape(1_000), probes=_probes(1_000), chunk=250)
    assert r.elapsed_s == pytest.approx(4e-6)  # four chunks, one injected step each
    assert r.within_budget


def test_budget_boundary_is_inclusive() -> None:
    assert RebuildResult("x", 1, 1, 10.0).within_budget
    assert not RebuildResult("x", 1, 1, 10.001).within_budget


def test_over_budget_clock_is_recorded_as_over() -> None:
    r = rb.rebuild_once("renko", "45", tp.tape(10), probes=_probes(11_000_000_000))
    assert not r.within_budget


def test_label_names_the_change() -> None:
    r = rb.rebuild_once("renko", "45", tp.tape(10), probes=_probes(1), old_param="30")
    assert r.change == "renko:30 -> renko:45"


def test_bad_chunk_is_refused() -> None:
    with pytest.raises(ValueError):
        rb.rebuild_once("renko", "45", tp.tape(10), chunk=0)


def test_median_rebuild_by_wall_time_needs_three() -> None:
    runs = [RebuildResult("x", 1, 1, s) for s in (3.0, 1.0, 2.0)]
    med, spread = rb.median_rebuild(runs)
    assert med.elapsed_s == 2.0 and spread == pytest.approx(1.0)
    with pytest.raises(ValueError):
        rb.median_rebuild(runs[:2])


def test_render_lists_results_and_the_pending_535_rows() -> None:
    ok, bad = RebuildResult("a", 10, 2, 1.0), RebuildResult("b", 10, 2, 11.0)
    out = rb.render([(ok, 0.0), (bad, 0.1)])
    assert "| within NFR |" in out and "over: known miss #2167" in out and "FAIL" not in out
    assert out.count("pending #535") == 4 and "ADR-0033" in out
    assert "Lower bound on the real rebuild" in out


def test_main_records_and_never_fails_even_over_the_nfr(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert rb.main(["--prints", "300"]) == 0
    assert "parameter-change rebuild" in capsys.readouterr().out
    monkeypatch.setattr(rb, "BUDGET_S", 0.0)
    assert rb.main(["--prints", "300"]) == 0
    assert "known miss #2167" in capsys.readouterr().out
