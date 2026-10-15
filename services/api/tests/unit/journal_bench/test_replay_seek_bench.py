"""E26-K01: the replay-seek harness runs on a tiny synthetic input and emits the JSON schema."""

from __future__ import annotations

from pathlib import Path

from bench.replay_seek import run as rs
from bench.replay_seek import synth


def test_run_tiny_thin_input_produces_the_report_schema(tmp_path: Path) -> None:
    r = rs.run(1_000, 50, [30], "thin", 1, 7, tmp_path, probe_rss=False)
    assert r["schema_version"] == rs.SCHEMA_VERSION
    assert "SYNTHETIC" in r["label"]
    assert set(r) >= {
        "machine",
        "params",
        "corpus",
        "seek",
        "snapshot_disk",
        "throughput",
        "busiest_minute",
        "buffer_100x",
        "read_ahead_rss",
    }
    for rows in r["seek"].values():
        busy = rows[0]["busy_window"]
        assert set(busy["stage_ms"]) == set(
            ("anchor_load", "delta_apply", "builder_restore", "warmup")
        )
        assert busy["book_matches_next_snapshot"] is True
        assert busy["total_ms"]["p50"] > 0
    assert r["throughput"]["merge"]["events"] == r["corpus"]["delta_rows"] + r["corpus"]["trades"]
    assert len(r["seek"]) == 3  # cold, hot stand-in, cold + collapsed-delta mitigation
    # 4 header lines + one row per (source, interval, window)
    assert rs.to_markdown(r).count("\n") == 4 + 2 * len(r["seek"])


def test_generator_is_deterministic_and_bursts_in_the_busiest_minute() -> None:
    a = synth.generate(synth.THIN, 50, 660, 3)
    b = synth.generate(synth.THIN, 50, 660, 3)
    assert a.deltas.equals(b.deltas) and a.trades.equals(b.trades)
    busy = rs.busiest_minute(a)
    assert busy["delta_rows"] > a.deltas.num_rows / 11  # busiest minute > the average minute


def test_buffer_needed_is_zero_when_the_reader_outpaces_100x() -> None:
    busy = {"events": 1_000}
    assert rs.buffer_needed(busy, 1e9, 50.0)["stalls_without_buffer"] is False
    slow = rs.buffer_needed(busy, 100.0, 50.0)
    assert slow["deficit_events"] == 940 and slow["stalls_without_buffer"] is True


def test_min_span_covers_the_busy_window_for_every_interval() -> None:
    assert rs.min_span_s([300, 60, 30]) == 900
    assert rs.min_span_s([30]) == 660
