"""E16-Q04 (#481): the load mix, the harness on a virtual clock, and the scripts' exit codes.

The soak smoke runs the real `StreamWriter` on a virtual clock (no sleeps, a few hundred
messages); the wall-time ingest smoke is `harness`-marked (nightly), as the E08 smokes are.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from pathlib import Path

import pytest

from bench.ingestion.budgets import Check, Verdict
from bench.recorder import HARNESS_VERSION, harness, ingest_load, soak
from bench.recorder.budgets import RunResult, check_reconciliation
from bench.recorder.generator import Delta, Liquidation, Mix, Trade, reference_phase
from bench.recorder.harness import CountingSink, LoadConfig, TimingSink, assert_loopback, finish
from bench.storage_measure import REFERENCE_ROWS_DAY
from candleviewer.recorder.writer import DiskGate

SYMBOLS = ("BTCUSDT", "ETHUSDT")


def _rss() -> int:
    return 100 * 2**20


def test_mix_is_seeded_and_counts_rows_as_the_writer_maps_them() -> None:
    a, b = Mix(SYMBOLS, seed=3), Mix(SYMBOLS, seed=3)
    seq_a = [a.next(i) for i in range(2_000)]
    assert seq_a == [b.next(i) for i in range(2_000)]
    rows = {"trades": 0, "orderbook_deltas": 0, "liquidations": 0}
    for kind, ev in seq_a:
        rows[kind] += len(ev.bids) + len(ev.asks) if isinstance(ev, Delta) else 1
    assert a.produced_msgs == 2_000 and a.produced_rows == {k: n for k, n in rows.items() if n}
    assert {ev.symbol for _, ev in seq_a} == set(SYMBOLS)


def test_mix_runs_bursts_cascades_and_unbroken_delta_chains() -> None:
    mix = Mix(SYMBOLS, seed=11)
    events = [mix.next(i) for i in range(60_000)]
    assert set(mix.phases_seen) == {"steady", "burst", "cascade"}
    assert any(isinstance(ev, Liquidation) for _, ev in events)
    last: dict[str, int] = {}
    for _, ev in events:
        if isinstance(ev, Delta):
            assert ev.prev_update_id == last.get(ev.symbol, 0) and ev.depth == 200
            last[ev.symbol] = ev.update_id
        if isinstance(ev, Trade):
            assert len(ev.trade_id) == 36 and ev.notional == ev.price * ev.qty


def test_mix_refuses_bad_phases() -> None:
    with pytest.raises(ValueError, match="at least one symbol"):
        Mix(())
    with pytest.raises(ValueError, match="sum to 1"):
        Mix(SYMBOLS, odds=(("steady", 0.5),))
    with pytest.raises(ValueError, match="non-negative"):
        Mix(SYMBOLS, phases={"x": (0.0, 0.0, 0.0)}, odds=(("x", 1.0),))


def test_reference_phase_is_the_e16_k01_rows_per_day() -> None:
    weights, per_symbol = reference_phase(REFERENCE_ROWS_DAY)
    assert weights["trades"] == pytest.approx(2_500_000 / 86_400)
    assert per_symbol == pytest.approx(weights["trades"] + weights["orderbook_deltas"])
    assert 300 < weights["orderbook_deltas"] < 600  # 190 M level rows/day at ~5 levels a delta


async def test_timing_sink_times_each_write_flush_pair_and_models_bytes() -> None:
    ticks = iter([1.0, 1.004])
    sink = TimingSink(CountingSink(), perf=lambda: next(ticks))
    row: dict[str, object] = {"ts": 1, "symbol": "BTCUSDT", "price": "1", "size": "1"}
    await sink.write_rows("orderbook_deltas", [row, row], "ts")
    await sink.flush("orderbook_deltas")
    await sink.flush(None)  # an unscoped flush times nothing
    assert sink.flush_ms == [pytest.approx(4.0)] and sink.rows == {"orderbook_deltas": 2}
    assert sink.hot_bytes == 2 * 72  # E16-K01 note section 2: a delta row is 72 B hot


def test_ilp_target_must_be_loopback() -> None:
    assert_loopback("127.0.0.1")
    with pytest.raises(RuntimeError, match="not loopback"):
        assert_loopback("10.0.0.5")


async def test_run_refuses_an_unknown_clock_and_a_mix_for_other_symbols(tmp_path: Path) -> None:
    cfg = LoadConfig("smoke", 10, 1, SYMBOLS, tmp_path / "wal", clock="sundial", rss=_rss)
    with pytest.raises(ValueError, match="real or virtual"):
        await harness.run(cfg)
    cfg.clock = "virtual"
    with pytest.raises(ValueError, match="symbols"):
        await harness.run(cfg, mix=Mix(("SOLUSDT",)))


async def test_soak_smoke_two_symbols_reconciles(tmp_path: Path) -> None:
    r = await soak.soak("smoke", 0.0, 7, tmp_path / "wal")
    assert r.symbols == SYMBOLS and r.duration_s == pytest.approx(soak.SMOKE_S)
    assert r.produced_msgs == int(soak.SMOKE_MSGS_PER_S * soak.SMOKE_S)
    assert r.produced_rows == {"all": r.written_rows["all"]} and r.dropped_rows == {"all": 0}
    assert set(r.backlog_rows) == {0} and set(r.spill_bytes) == {0}  # sampled at flush bounds
    assert r.flush_ms and r.hot_bytes > 0 and r.critical_events == 0


async def test_reconciliation_counts_gated_drops_in_rows_and_balances(tmp_path: Path) -> None:
    """The writer's `messages_dropped` is a row count (the disk gate adds one per row it drops),
    so produced == written + dropped holds with drops, not only at zero (r1 review)."""
    gate = DiskGate(halted=lambda: True, position_open=lambda s: s == "BTCUSDT")
    cfg = LoadConfig("smoke", 200, 1, SYMBOLS, tmp_path / "wal", clock="virtual", rss=_rss,
                     disk_gate=gate)  # fmt: skip
    r = await harness.run(cfg)
    assert 0 < r.dropped_rows["all"] < r.produced_rows["all"]
    assert r.produced_rows["all"] == r.written_rows["all"] + r.dropped_rows["all"]
    assert check_reconciliation(r.produced_rows, r.written_rows, r.dropped_rows).passed


def _verdict(passed: bool) -> Verdict:
    v = Verdict("recorder_ingest")
    v.add(Check("flush_p95", "x", 1.0 if passed else 60.0, 50.0, "ms", passed))
    return v


def test_finish_writes_the_report_and_exits_1_on_a_failed_budget(tmp_path: Path) -> None:
    lines: list[str] = []
    r = RunResult("smoke", 10.0, 1.0, SYMBOLS, produced_msgs=10)
    out = tmp_path / "r" / "report.json"
    assert finish(_verdict(True), r, out=out, baseline=None, machine_profile="m",
                  print_=lines.append) == 0  # fmt: skip
    assert json.loads(out.read_text())["run"]["achieved_msgs_per_s"] == 10.0
    assert finish(_verdict(False), r, out=None, baseline=None, machine_profile="m",
                  print_=lines.append) == 1  # fmt: skip
    assert any(line.startswith("FAIL flush_p95") for line in lines)


def test_finish_exits_1_when_the_regression_gate_fails() -> None:
    baseline = {
        "harness_version": HARNESS_VERSION, "run_profile": "full", "machine_profile": "m",
        "metrics": {"flush_ms": {"p95": 10.0}},
    }  # fmt: skip
    v = _verdict(True)
    v.metrics = {"flush_ms": {"p95": 20.0}}
    r = RunResult("full", 10.0, 1.0, SYMBOLS)
    assert finish(v, r, out=None, baseline=baseline, machine_profile="m", print_=print) == 1


def _fake_run(flush_ms: float) -> Callable[..., Awaitable[RunResult]]:
    async def fake(cfg: LoadConfig, *, mix: Mix | None = None) -> RunResult:
        r = RunResult(cfg.profile, cfg.msgs_per_s, cfg.duration_s, cfg.symbols)
        r.produced_msgs = int(cfg.msgs_per_s * cfg.duration_s)
        r.produced_rows = r.written_rows = {"all": 10}
        r.flush_ms, r.rss_bytes = [flush_ms] * 20, [_rss()]
        return r

    return fake


def test_ingest_gate_exits_nonzero_when_p95_flush_over_50ms(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ingest_load, "run", _fake_run(51.0))
    out = tmp_path / "ingest.json"
    assert ingest_load.main(["--profile", "smoke", "--out", str(out)]) == 1
    report = json.loads(out.read_text())
    assert [c["name"] for c in report["checks"] if not c["passed"]] == ["flush_p95"]
    monkeypatch.setattr(ingest_load, "run", _fake_run(1.0))
    assert ingest_load.main(["--msgs-per-s", "5", "--duration-s", "1"]) == 0


def test_soak_cli_judges_the_smoke_and_refuses_non_positive_hours(tmp_path: Path) -> None:
    out = tmp_path / "soak.json"
    assert soak.main(["--profile", "smoke", "--out", str(out)]) == 0
    checks = {c["name"]: c for c in json.loads(out.read_text())["checks"]}
    assert checks["gb_per_day_per_symbol"]["hard"] is False  # a scaled run reports it
    with pytest.raises(SystemExit, match="positive"):
        soak.main(["--profile", "full", "--hours", "0"])


def test_record_baseline_keeps_the_committed_provenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CI", raising=False)
    committed = {"gb_per_day_per_symbol": {"value": 14.04}, "metrics": {"old": {"p95": 1.0}}}
    v = _verdict(True)
    v.metrics = {"flush_ms": {"p95": 2.0}}
    path = harness.record_baseline(v, committed, "full", root=tmp_path)
    saved = json.loads(path.read_text())
    assert saved["gb_per_day_per_symbol"] == {"value": 14.04}
    assert saved["metrics"] == {"flush_ms": {"p95": 2.0}} and saved["gate"] == "warn-only"
    monkeypatch.setenv("CI", "true")
    with pytest.raises(RuntimeError, match="never rewritten by CI"):
        harness.record_baseline(v, committed, "full", root=tmp_path)


@pytest.mark.harness
def test_ingest_load_smoke_passes_at_tiny_scale(tmp_path: Path) -> None:
    out = tmp_path / "ingest.json"
    assert ingest_load.main(["--profile", "smoke", "--out", str(out)]) == 0
    run = json.loads(out.read_text())["run"]
    assert run["produced_rows"] == run["written_rows"] and run["dropped_rows"] == {"all": 0}
