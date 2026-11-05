"""E24-Q03 (#773) slice 1: the cascade generator and judge, offline and seeded."""

from __future__ import annotations

import json
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from bench.ws import budgets, cascade, profiles

TABLE = profiles.load()
PROFILE_NAMES = ("ramp", "sustained", "burst")
GOOD = cascade.Run(
    profile="sustained",
    frame_script_ms=[1.2] * 90 + [1.8] * 10,
    frame_gaps_ms=[16.7] * 100,
    tick_p95_ms=60.0,
    tick_p99_ms=120.0,
    fanout_p95_ms=8.0,
    rest_p95_ms=90.0,
    summaries=1,
    emphasis_starts_per_s=0.5,
)


def test_profiles_json_cascade_section_has_the_three_profiles() -> None:
    assert set(TABLE["cascade"]["profiles"]) == set(PROFILE_NAMES)
    assert cascade.profile(TABLE, "sustained").total == 5000
    assert cascade.profile(TABLE, "burst").total == 2000
    assert cascade.profile(TABLE, "ramp").total == 2500


def test_profiles_json_cascade_does_not_disturb_the_e17_table() -> None:
    assert "cascade" not in TABLE["profiles"]
    assert profiles.resolve(TABLE, "A")["users"] == 5


def test_cascade_thresholds_mirror_the_constants() -> None:
    t = TABLE["cascade"]["thresholds"]
    assert t["script_p95_ms"] == cascade.SCR054_SCRIPT_MS
    assert t["dropped_frames"] == cascade.SCR054_DROPPED_FRAMES
    assert (t["tick_p95_ms"], t["tick_p99_ms"]) == (cascade.B3_P95_MS, cascade.B3_P99_MS)
    assert t["fanout_p95_ms"] == cascade.B6_FANOUT_P95_MS
    assert t["rest_p95_ms"] == cascade.B13_REST_P95_MS
    assert t["summaries"] == cascade.Q3_SUMMARIES
    assert t["emphasis_per_s"] == cascade.Q3_EMPHASIS_PER_S


def test_cascade_budget3_and_budget6_match_the_e17_judge() -> None:
    assert (cascade.B3_P95_MS, cascade.B3_P99_MS) == (budgets.B3_P95_MS, budgets.B3_P99_MS)
    assert cascade.B6_FANOUT_P95_MS == budgets.B6_FANOUT_S * 1000.0
    assert TABLE["thresholds"]["tick_p95_ms"] == cascade.B3_P95_MS


def test_profile_unknown_shape_is_refused() -> None:
    table = {"cascade": {"profiles": {"x": {"shape": "spike", "rate_per_s": 1, "duration_s": 1}}}}
    with pytest.raises(ValueError, match="unknown shape"):
        cascade.profile(table, "x")


@pytest.mark.parametrize("name", PROFILE_NAMES)
def test_frames_same_seed_same_frames(name: str) -> None:
    prof = cascade.profile(TABLE, name)
    assert cascade.frames(prof, seed=7) == cascade.frames(prof, seed=7)


def test_frames_different_seed_changes_the_template_choice() -> None:
    prof = cascade.profile(TABLE, "sustained")
    assert cascade.frames(prof, seed=1) != cascade.frames(prof, seed=2)


@pytest.mark.parametrize("name", PROFILE_NAMES)
def test_frames_carry_exactly_the_profiles_prints(name: str) -> None:
    prof = cascade.profile(TABLE, name)
    got = sum(len(f["data"]) for f in cascade.frames(prof, seed=1))
    assert got == prof.total


def test_frames_sustained_rate_is_flat_per_push() -> None:
    fs = cascade.frames(cascade.profile(TABLE, "sustained"), seed=1)
    assert len(fs) == 20  # 10 s in 500 ms pushes
    assert {len(f["data"]) for f in fs} == {250}


def test_frames_burst_rate_is_1000_per_s() -> None:
    fs = cascade.frames(cascade.profile(TABLE, "burst"), seed=1)
    assert len(fs) == 4
    assert {len(f["data"]) for f in fs} == {500}


def test_frames_ramp_rises_every_push() -> None:
    sizes = [len(f["data"]) for f in cascade.frames(cascade.profile(TABLE, "ramp"), seed=1)]
    assert sizes == sorted(sizes)
    assert sizes[0] < sizes[-1]


def test_frames_one_push_per_500ms_window_with_ordered_ts() -> None:
    fs = cascade.frames(cascade.profile(TABLE, "sustained"), seed=1, start_ms=0)
    assert [f["ts"] for f in fs] == [500 * (i + 1) for i in range(len(fs))]
    for f in fs:
        assert all(f["ts"] - cascade.PUSH_MS <= d["T"] <= f["ts"] for d in f["data"])
        stamps = [d["T"] for d in f["data"]]
        assert stamps == sorted(stamps)


def test_frames_have_the_upstream_allliquidation_shape() -> None:
    f = cascade.frames(cascade.profile(TABLE, "burst"), seed=1, symbol="ETHUSDT")[0]
    assert set(f) == {"topic", "type", "ts", "data"}
    assert f["topic"] == "allLiquidation.ETHUSDT"
    assert f["type"] == "snapshot"
    for d in f["data"]:
        assert set(d) == {"T", "s", "S", "v", "p"}
        assert d["s"] == "ETHUSDT"
        assert d["S"] in ("Buy", "Sell")
        assert Decimal(d["p"]) > 0 and Decimal(d["v"]) > 0


def test_frames_json_roundtrip() -> None:
    fs = cascade.frames(cascade.profile(TABLE, "burst"), seed=3)
    assert json.loads(json.dumps(fs)) == fs


def test_frames_without_templates_is_refused() -> None:
    with pytest.raises(ValueError, match="no templates"):
        cascade.frames(cascade.profile(TABLE, "burst"), seed=1, templates=())


def test_notional_is_price_times_size() -> None:
    assert cascade.notional_usd({"p": "63120.60", "v": "0.131"}) == Decimal("8268.7986")


def test_load_templates_falls_back_when_the_fixture_is_absent(tmp_path: Path) -> None:
    assert cascade.load_templates(None) == cascade.FALLBACK_TEMPLATES
    assert cascade.load_templates(tmp_path / "missing.jsonl") == cascade.FALLBACK_TEMPLATES


def test_load_templates_reads_a_recorded_file(tmp_path: Path) -> None:
    f = tmp_path / "a.jsonl"
    frame = {
        "topic": "allLiquidation.BTCUSDT",
        "type": "snapshot",
        "ts": 1,
        "data": [{"T": 1, "s": "BTCUSDT", "S": "Sell", "v": "0.5", "p": "60000.1"}],
    }
    f.write_text(json.dumps(frame) + "\n", encoding="utf-8")
    assert cascade.load_templates(f) == (("Sell", "60000.1", "0.5"),)


def test_load_templates_empty_file_falls_back(tmp_path: Path) -> None:
    f = tmp_path / "a.jsonl"
    f.write_text("", encoding="utf-8")
    assert cascade.load_templates(f) == cascade.FALLBACK_TEMPLATES


@settings(max_examples=40, deadline=None)
@given(
    rate=st.integers(1, 400),
    dur=st.integers(1, 6),
    shape=st.sampled_from(["ramp", "sustained", "burst"]),
    seed=st.integers(0, 10_000),
)
def test_frames_property_count_matches_total_and_time_is_monotonic(
    rate: int, dur: int, shape: str, seed: int
) -> None:
    prof = cascade.CascadeProfile("p", shape, rate, float(dur))
    offs = cascade.offsets_ms(prof)
    assert len(offs) == prof.total
    assert offs == sorted(offs)
    assert not offs or offs[-1] <= dur * 1000
    cum = 0
    for f in cascade.frames(prof, seed=seed):
        cum += len(f["data"])
        t_s = (f["ts"] - 1_700_000_000_000) / 1000.0
        want = rate * t_s if shape != "ramp" else rate * t_s * t_s / (2 * dur)
        assert abs(cum - min(want, prof.total)) <= 1.0 + 1e-6
    assert sum(len(f["data"]) for f in cascade.frames(prof, seed=seed)) == prof.total


def test_evaluate_good_run_passes_and_names_what_it_skipped() -> None:
    v, skipped = cascade.evaluate(GOOD)
    assert v.passed
    assert any(s.startswith("budget1") for s in skipped)
    assert {c.budget for c in v.checks} >= {"SCR-054", "#3", "#6", "#13", "E24-D04 Q-3"}


def test_evaluate_injected_5ms_regression_fails_scr054_script_budget() -> None:
    v, _ = cascade.evaluate(GOOD)
    assert v.passed
    bad, _ = cascade.evaluate(_with(GOOD, inject_ms=cascade.SELFCHECK_INJECT_MS))
    assert not bad.passed
    failed = [c.name for c in bad.checks if not c.passed]
    assert failed == [TABLE["cascade"]["selfcheck"]["expect_fail"]]


def _with(run: cascade.Run, **over: Any) -> cascade.Run:
    return replace(run, **over)


def test_evaluate_selfcheck_inject_matches_profiles_json() -> None:
    assert TABLE["cascade"]["selfcheck"]["inject_ms"] == cascade.SELFCHECK_INJECT_MS


def test_evaluate_script_at_the_limit_passes_and_above_fails() -> None:
    ok, _ = cascade.evaluate(_with(GOOD, frame_script_ms=[2.0] * 10))
    over, _ = cascade.evaluate(_with(GOOD, frame_script_ms=[2.01] * 10))
    assert ok.passed and not over.passed


def test_evaluate_dropped_frame_fails() -> None:
    v, _ = cascade.evaluate(_with(GOOD, frame_gaps_ms=[16.7] * 99 + [34.0]))
    assert [c.name for c in v.checks if not c.passed] == ["scr054.dropped_frames"]


def test_dropped_frames_counts_gaps_over_one_and_a_half_frames() -> None:
    assert cascade.dropped_frames([16.7, 25.0, 25.1, 50.0]) == 2
    assert cascade.dropped_frames([]) == 0


@pytest.mark.parametrize(
    ("field", "value", "failing"),
    [
        ("tick_p95_ms", 100.0, "budget3.tick_to_screen.p95"),
        ("tick_p99_ms", 250.0, "budget3.tick_to_screen.p99"),
        ("fanout_p95_ms", 20.1, "budget6.fanout.p95"),
        ("rest_p95_ms", 150.0, "budget13.rest.p95"),
        ("summaries", 3, "q3.summaries"),
        ("emphasis_starts_per_s", 1.5, "q3.emphasis_per_s"),
    ],
)
def test_evaluate_each_budget_fails_alone(field: str, value: float, failing: str) -> None:
    v, _ = cascade.evaluate(_with(GOOD, **{field: value}))
    assert [c.name for c in v.checks if not c.passed] == [failing]


def test_evaluate_unmeasured_is_skipped_never_passed() -> None:
    v, skipped = cascade.evaluate(cascade.Run(profile="burst"))
    assert v.checks == [] and v.passed
    assert "scr054.script_ms.p95" in skipped and "budget3.tick_to_screen.p95" in skipped


def test_evaluate_result_carries_the_synthetic_note() -> None:
    assert "synthetic" in GOOD.note and "no recorded cascade" in GOOD.note


def test_regression_flags_over_5_percent_beyond_the_floor() -> None:
    base = {"script_p95_ms": 1.0, "tick_p95_ms": 50.0}
    assert cascade.regression(base, {"script_p95_ms": 6.0, "tick_p95_ms": 50.0}) == (
        [("script_p95_ms", 1.0, 6.0)],
        [],
    )
    assert cascade.regression(base, {"script_p95_ms": 1.4, "tick_p95_ms": 52.0}) == ([], [])
    assert cascade.regression(base, {"script_p95_ms": 1.0, "tick_p95_ms": 53.0}) == (
        [("tick_p95_ms", 50.0, 53.0)],
        [],
    )


def test_regression_headline_missing_from_the_run_is_lost_not_passed() -> None:
    base = {"script_p95_ms": 1.0, "tick_p95_ms": 50.0}
    assert cascade.regression(base, {}) == ([], ["script_p95_ms", "tick_p95_ms"])
    assert cascade.regression(base, {"tick_p95_ms": 50.0}) == ([], ["script_p95_ms"])


def test_fallback_templates_are_recorded_price_size_pairs() -> None:
    recorded = {
        ("Buy", "63120.60", "0.131"),
        ("Sell", "63120.60", "0.242"),
        ("Buy", "63120.90", "0.049"),
        ("Buy", "63122.10", "0.087"),
    }
    assert set(cascade.FALLBACK_TEMPLATES) == recorded


def test_evaluate_says_when_the_run_used_the_fallback_templates() -> None:
    v, _ = cascade.evaluate(GOOD)
    assert GOOD.template_source == cascade.FALLBACK_SOURCE
    assert v.metrics["run"]["template_fallback"] == 1.0
    v2, _ = cascade.evaluate(_with(GOOD, template_source="packages/fixtures/x.jsonl"))
    assert v2.metrics["run"]["template_fallback"] == 0.0


def test_offsets_are_integer_ms() -> None:
    for name in PROFILE_NAMES:
        assert all(isinstance(o, int) for o in cascade.offsets_ms(cascade.profile(TABLE, name)))


def _window_counts(name: str) -> list[int]:
    fs = cascade.frames(cascade.profile(TABLE, name), seed=1)
    return [len(f["data"]) for f in fs]


def test_frames_per_window_counts_are_exact_per_profile() -> None:
    assert _window_counts("sustained") == [250] * 20
    assert _window_counts("burst") == [500] * 4
    ramp = _window_counts("ramp")
    assert len(ramp) == 20 and sum(ramp) == 2500
    # the cumulative count at window w's end is rate * t^2 / (2 * duration), t = (w + 1) / 2 s
    for w, n in enumerate(ramp):
        assert abs(sum(ramp[: w + 1]) - 500 * ((w + 1) / 2) ** 2 / 20) <= 1, (w, n)
