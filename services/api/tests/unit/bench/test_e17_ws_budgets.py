"""E17-Q03 (#568): the verdict, the W5 rule, the gate and the reproducibility check, offline.

No k6, no backend: the k6 summary and the `/metrics` scrapes are written here, as the harness reads
them. The two cases the ticket names are in: a bandwidth over 1 MiB/s for the reference workspace
fails the run with that metric named (AC 3), and an inflated fan-out fails budget #6 (the
self-check).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from bench.ingestion import HARNESS_VERSION as E08_HARNESS_VERSION
from bench.ingestion import gate
from bench.ingestion.budgets import Check, Verdict
from bench.ws import HARNESS_VERSION, budgets, w5
from bench.ws.budgets import Facts, Scrape

PROFILE: dict[str, Any] = {
    "name": "A",
    "gate_on": "excluding",
    "probe": True,
    "flag": "on",
    "users": 5,
    "connections": 1,
}
HELD = budgets.parse_scrape("cv_ws_connections_in_use 6")  # 5 users x 1 connection + the probe
FACTS = Facts(
    steady_s=3600.0, k6_cpu_frac=0.3, rss_bytes=200 << 20, mem_max_bytes=8 << 30, cpu_s=600.0
)
FANOUT = "cv_ws_fanout_seconds"


def trend(
    p95: float, *, p99: float | None = None, n: int = 100, mx: float | None = None
) -> dict[str, float]:
    return {"count": n, "p50": p95 / 2, "p95": p95, "p99": p99 or p95, "max": mx or p95}


def summary(**over: Any) -> dict[str, Any]:
    """What a healthy hour looks like to `handleSummary`: every row inside its budget."""
    trends = {
        "cv_tick_decode_ms_trades": trend(95.0, p99=99.0),
        "cv_release_decode_ms_trades": trend(2.0, p99=4.0),
        "cv_rw_kib_s": trend(9.0),
        "cv_resnap_kib": trend(9.0),
        "cv_resnap_ms": trend(6.0),
        "cv_client_lag_ms": trend(1.0),
        "cv_clock_skew_ms": trend(1.0),
    }
    counters = {"cv_seq_gaps": 0, "cv_connections_up": 6}
    out: dict[str, Any] = {"schema": 1, "trends": trends, "counters": counters}
    for key, value in over.items():
        bucket = "trends" if key.startswith("cv_") and isinstance(value, dict) else "counters"
        out[bucket][key] = value
    return out


def histogram(name: str, cumulative: dict[float, int]) -> str:
    total = max(cumulative.values())
    lines = [f'{name}_bucket{{env="demo",le="{le:g}"}} {n}' for le, n in cumulative.items()]
    lines += [
        f'{name}_bucket{{env="demo",le="+Inf"}} {total}',
        f'{name}_count{{env="demo"}} {total}',
    ]
    return "\n".join(lines)


#: 100 sampled frames (weight 32): 98.4 % at or under 20 ms, p95 inside the edge.
HEALTHY = {0.01: 2900, 0.02: 3150, 0.03: 3200}


def scrape(
    fanout: dict[float, int] | None = None, extra: str = "", fed: tuple[int, int] = (1000, 1000)
) -> Scrape:
    text = histogram(FANOUT, fanout or HEALTHY)
    text += f'\ncv_bench_feed_scheduled_total{{kind="book"}} {fed[0]}'
    text += f'\ncv_bench_feed_published_total{{kind="book"}} {fed[1]}\n{extra}'
    return budgets.parse_scrape(text)


def evaluate(
    summ: dict[str, Any],
    t1: Scrape | None = None,
    prof: dict[str, Any] | None = None,
    facts: Facts = FACTS,
    t0: Scrape | None = None,
) -> budgets.Result:
    t1 = t1 if t1 is not None else scrape()
    return budgets.evaluate(prof or PROFILE, summ, HELD if t0 is None else t0, t1, facts)


def test_a_series_absent_at_t0_counts_as_zero_and_the_edge_is_read_exactly() -> None:
    t1 = scrape({0.01: 10, 0.02: 3040, 0.03: 3200})
    d = budgets.delta(budgets.parse_scrape('cv_ws_fanout_seconds_count{env="demo"} 0'), t1)
    assert budgets.fraction_le(d, FANOUT, 0.02) == (0.95, 3200)
    assert budgets.quantile(d, FANOUT, 0.95) == pytest.approx(0.02)
    short = budgets.delta({}, scrape({0.02: 3039, 0.03: 3200}))
    assert budgets.fraction_le(short, FANOUT, 0.02)[0] < 0.95
    assert budgets.quantile(budgets.delta({}, {}), FANOUT, 0.95) is None


@pytest.mark.parametrize(
    ("at_edge", "failed"), [(3040, []), (3039, ["budget6.cv_ws_fanout_seconds.p95"])]
)
def test_budget_6_passes_at_exactly_95_percent_and_fails_one_sample_short(
    at_edge: int, failed: list[str]
) -> None:
    assert evaluate(summary(), scrape({0.02: at_edge, 0.03: 3200})).failed() == failed


@pytest.mark.parametrize(("sp", "ok"), [(4, True), (0, False), (60, False)])
def test_the_span_id_share_is_a_sanity_row_about_one_frame_in_32(sp: int, ok: bool) -> None:
    summ = summary(cv_frames_book=100, cv_frames_trades=28, cv_sp_frames=sp)
    res = evaluate(summ)
    row = next(c for c in res.informational if c.name == "e17_t06.sp_share")
    assert row.passed is ok and res.status == "PASS"  # informational: never fails a run


def test_a_healthy_run_passes_and_every_row_is_named() -> None:
    res = evaluate(summary())
    assert (res.status, res.exit_code, res.failed(), res.invalid) == ("PASS", 0, [], [])
    names = {c.name for c in res.verdict.checks}
    assert {
        "budget6.cv_ws_fanout_seconds.p95",
        "budget3.tick_to_decode.trades.p95",
        "budget3.tick_to_decode.trades.p99",
        "s16_3.tick_to_pixel.p95",
        "s16_3.bandwidth.reference_workspace",
        "s16_3.resnapshot.bytes",
        "s16_3.resnapshot.ms",
        "s16_3.upstream_desync.per_topic_hour",
        "backpressure.resyncs",
        "sequence.gaps",
    } <= names
    assert {
        "fanout_ms",
        "tick_to_decode_trades_ms",
        "rw_bandwidth_kib_s",
        "backend_cpu_s_per_s",
    } <= set(res.verdict.metrics)


def test_bandwidth_over_one_mib_a_second_fails_the_run_naming_the_metric() -> None:
    res = evaluate(summary(cv_rw_kib_s=trend(1126.4)))  # 1.1 MiB/s: the ticket's scenario
    assert (res.status, res.exit_code) == ("FAIL", 1)
    assert res.failed() == ["s16_3.bandwidth.reference_workspace"]
    row = next(c for c in res.verdict.checks if c.name == res.failed()[0])
    assert "hard-fail line" in row.note and row.measured > 1024


def test_an_inflated_fanout_fails_budget_6_which_is_the_self_check() -> None:
    slow = scrape({0.01: 100, 0.02: 400, 0.03: 900, 0.05: 3200})  # most frames past 20 ms
    res = evaluate(summary(), slow)
    assert res.failed() == ["budget6.cv_ws_fanout_seconds.p95"]
    ok, text = budgets.expect_failure(res, "budget6.cv_ws_fanout_seconds.p95")
    assert ok and "FAIL" in text
    assert not budgets.expect_failure(evaluate(summary()), "budget6.cv_ws_fanout_seconds.p95")[0]


@pytest.mark.parametrize(
    ("gate_on", "failed"),
    [("excluding", []), ("including", ["s16_3.tick_to_pixel.p95"])],
)
def test_the_profile_picks_which_latency_gates_and_the_other_is_reported(
    gate_on: str, failed: list[str]
) -> None:
    res = evaluate(summary(), prof=PROFILE | {"gate_on": gate_on})
    assert res.failed() == failed
    other = {c.name for c in res.informational}
    assert "budget3.tick_to_decode.trades.p95.other_variant" in other


@pytest.mark.parametrize(
    ("summ", "t1", "facts", "needle"),
    [
        (summary(), scrape(fed=(1000, 900)), FACTS, "feeder_behind"),
        (summary(cv_clock_skew_ms=trend(6.0)), None, FACTS, "clock_skew"),
        (summary(cv_client_lag_ms=trend(25.0)), None, FACTS, "cv_client_lag_ms"),
        (summary(), None, Facts(3600.0, k6_cpu_frac=0.85), "k6_cpu"),
        (summary(cv_unplanned_closes=1), None, FACTS, "cv_unplanned_closes"),
        (summary(cv_auth_failures=2), None, FACTS, "cv_auth_failures"),
        (summary(cv_errors=1), None, FACTS, "cv_errors"),
        (summary(cv_sub_refused=3), None, FACTS, "cv_sub_refused"),
        (summary(), None, Facts(3600.0, oom_events=1), "backend_memory"),
        (
            summary(),
            None,
            Facts(3600.0, rss_bytes=9 << 30, mem_max_bytes=8 << 30),
            "backend_memory",
        ),
        (summary(), scrape({0.02: 320, 0.03: 320}), FACTS, "fanout_samples"),
        (summary(cv_rw_kib_s=trend(1.0, n=0)), None, FACTS, "no_bandwidth_windows"),
        (summary(cv_resnap_ms=trend(1.0, n=0)), None, FACTS, "no_resnapshot_samples"),
        (summary(), None, Facts(0.0), "no_steady_window"),
    ],
)
def test_a_tripped_validity_guard_makes_the_run_invalid_never_a_budget_verdict(
    summ: dict[str, Any], t1: Scrape | None, facts: Facts, needle: str
) -> None:
    res = evaluate(summ, t1, facts=facts)
    assert res.status == "INVALID" and res.exit_code == 2
    assert any(needle in x for x in res.invalid), res.invalid


@pytest.mark.parametrize(
    ("summ", "t0"),
    [
        (summary(cv_connections_up=4), None),  # a VU that died before its socket opened
        (summary(), budgets.parse_scrape("cv_ws_connections_in_use 5")),  # the server holds fewer
        (summary(), budgets.parse_scrape("")),  # and none at all
    ],
)
def test_a_run_with_fewer_connections_than_planned_is_invalid_never_a_pass(
    summ: dict[str, Any], t0: Scrape | None
) -> None:
    """k6 exits 0 when a VU's script throws, and no budget sees a lighter load: the counts do."""
    res = evaluate(summ, t0=t0)
    assert res.status == "INVALID" and any("connections_short" in x for x in res.invalid)
    assert evaluate(summary()).status == "PASS"  # 5 users x 1 connection and the probe, all up


# -- the clock-skew guard judges the skew corrected for the hello's own transit ------------------


def hello_skew(raw: float, corrected: float, rtt_p50: float, rtt_max: float) -> dict[str, Any]:
    """The three trends the k6 client records at each welcome (`tests/load/ws/lib/skew.js`)."""
    rtt = {"count": 6, "p50": rtt_p50, "p95": rtt_max, "p99": rtt_max, "max": rtt_max}
    return {
        "cv_clock_skew_ms": trend(raw, n=6),
        "cv_clock_skew_corrected_ms": trend(corrected, n=6),
        "cv_hello_rtt_ms": rtt,
    }


def test_a_same_host_skew_that_is_only_the_hellos_transit_passes_the_guard() -> None:
    """One host clock, so no drift: 10 of the 13 ms reported are half the 20 ms round trip."""
    res = evaluate(summary(**hello_skew(raw=13.0, corrected=3.0, rtt_p50=20.0, rtt_max=26.0)))
    assert (res.status, res.invalid) == ("PASS", [])


def test_a_real_drift_is_still_invalid_and_the_message_names_corrected_raw_and_rtt() -> None:
    """8 ms of drift on top of a 10 ms transit reads 18 ms raw and 8 ms corrected."""
    res = evaluate(summary(**hello_skew(raw=18.0, corrected=8.0, rtt_p50=20.0, rtt_max=22.0)))
    assert (res.status, res.exit_code) == ("INVALID", 2)
    assert res.invalid == [
        "clock_skew: corrected max 8.0 ms against 5 ms (max over 6 hellos of |raw - RTT/2|; "
        "raw max 18.0 ms; hello RTT p50 20.0 ms / max 22.0 ms)"
    ]


def test_a_corrected_skew_above_the_raw_one_is_what_the_guard_judges() -> None:
    """The server's clock 8 ms behind on a 20 ms round trip reads 2 ms raw and 8 ms corrected."""
    res = evaluate(summary(**hello_skew(raw=2.0, corrected=8.0, rtt_p50=20.0, rtt_max=22.0)))
    assert res.status == "INVALID" and res.invalid[0].startswith("clock_skew: corrected max 8.0 ms")


@pytest.mark.parametrize(("corrected", "status"), [(5.0, "PASS"), (5.1, "INVALID")])
def test_the_corrected_skew_is_held_to_the_same_5_ms_as_the_raw_one_was(
    corrected: float, status: str
) -> None:
    assert budgets.MAX_CLOCK_SKEW_MS == 5.0
    skew = hello_skew(raw=corrected + 10.0, corrected=corrected, rtt_p50=20.0, rtt_max=22.0)
    assert evaluate(summary(**skew)).status == status


@pytest.mark.parametrize(("raw", "status"), [(5.0, "PASS"), (6.0, "INVALID")])
def test_a_summary_without_the_corrected_trend_is_judged_on_its_raw_skew_as_before(
    raw: float, status: str
) -> None:
    assert evaluate(summary(cv_clock_skew_ms=trend(raw))).status == status


def test_a_raw_only_skew_says_in_its_message_that_it_was_not_corrected() -> None:
    res = evaluate(summary(cv_clock_skew_ms=trend(6.0, n=6)))
    assert res.invalid == [
        "clock_skew: raw max 6.0 ms against 5 ms (max over 6 hellos of |raw|; "
        "not RTT-corrected: the summary has no cv_clock_skew_corrected_ms)"
    ]


def test_the_selfcheck_profile_judges_the_raw_skew_so_it_still_fails_budget_6() -> None:
    """25 ms of send delay holds the welcome after the server's stamp: 1 ms raw, 13 ms corrected."""
    from bench.ws import profiles

    prof = profiles.resolve(profiles.load(), "selfcheck") | {"name": "selfcheck"}
    slow = scrape({0.01: 100, 0.02: 400, 0.03: 900, 0.05: 3200})
    skew = hello_skew(raw=1.0, corrected=13.0, rtt_p50=27.0, rtt_max=29.0)
    res = evaluate(summary(**skew), slow, prof)
    ok, text = budgets.expect_failure(res, prof["expect_fail"])
    assert (res.status, ok) == ("FAIL", True), text


def test_a_send_delay_run_with_a_real_raw_skew_is_invalid_and_says_raw_was_judged() -> None:
    skew = hello_skew(raw=6.0, corrected=8.5, rtt_p50=27.0, rtt_max=29.0)
    res = evaluate(summary(**skew), prof=PROFILE | {"send_delay_ms": 25})
    assert res.invalid == [
        "clock_skew: raw max 6.0 ms against 5 ms (max over 6 hellos of |raw|; "
        "send delay 25 ms injected: raw judged; hello RTT p50 27.0 ms / max 29.0 ms)"
    ]


RELEASE, TICK = "cv_release_decode_ms_trades", "cv_tick_decode_ms_trades"
B3 = "budget3.tick_to_decode.trades"


@pytest.mark.parametrize(
    ("trend_name", "p95", "p99", "gate_on", "failed"),
    [
        (RELEASE, 100.0, 99.0, "excluding", [f"{B3}.p95", "s16_3.tick_to_pixel.p95"]),
        (RELEASE, 39.9, 250.0, "excluding", [f"{B3}.p99"]),
        (TICK, 40.0, 99.0, "including", ["s16_3.tick_to_pixel.p95"]),
        (RELEASE, 39.9, 249.9, "excluding", []),
    ],
)
def test_the_under_targets_are_strict_as_the_k6_thresholds_are(
    trend_name: str, p95: float, p99: float, gate_on: str, failed: list[str]
) -> None:
    """The ticket says under 100 ms and 23 16.3 under 40 ms: a reading at the limit misses it, as
    `p(95)<40` in ws_load.js does. Budget #6's 20 ms stays at or under, as written."""
    prof = PROFILE | {"gate_on": gate_on}
    assert evaluate(summary(**{trend_name: trend(p95, p99=p99)}), prof=prof).failed() == failed


def test_the_rows_that_cannot_fail_by_construction_say_so_beside_the_verdict() -> None:
    res = evaluate(summary())
    notes = {c.name: c.note for c in res.verdict.checks}
    assert "no ingestion" in notes["s16_3.upstream_desync.per_topic_hour"]
    assert "no footprint" in notes["s16_3.resnapshot.bytes"]
    assert "no footprint" in notes["s16_3.resnapshot.ms"]
    listed = " ".join(res.as_dict()["not_measurable"])
    assert "upstream_desync" in listed and "full re-snapshot" in listed


def test_the_metrics_name_their_percentiles_and_a_p99_is_not_a_max() -> None:
    m = evaluate(summary()).verdict.metrics
    assert {"p50", "p95", "p99", "count"} <= set(m["fanout_ms"]) and "max" not in m["fanout_ms"]
    assert "p99" in m["tick_to_decode_trades_ms"] and "max" not in m["tick_to_decode_trades_ms"]
    assert m["rw_bandwidth_kib_s"]["max"] == m["rw_bandwidth_kib_s"]["p95"]  # a lone value


def test_invalid_wins_over_a_budget_miss() -> None:
    res = evaluate(summary(cv_rw_kib_s=trend(1126.4), cv_errors=1))
    assert res.failed() == ["s16_3.bandwidth.reference_workspace"] and res.status == "INVALID"


def test_every_nonzero_backpressure_series_is_named_and_a_routine_close_is_not() -> None:
    extra = "\n".join(
        [
            'cv_ws_resync_total{env="demo",reason="backpressure"} 3',
            'cv_ws_resync_total{env="demo",reason="client_resync"} 9',
            'cv_ws_overflow_total{env="demo",reason="drop"} 2',
            'cv_ws_closes_total{env="demo",reason="slow_consumer"} 1',
            'cv_ws_closes_total{env="demo",reason="client_closed"} 8',
            'cv_ws_sequence_gaps_detected_total{env="demo"} 1',
        ]
    )
    res = evaluate(summary(), scrape(extra=extra))
    assert sorted(res.failed()) == [
        "backpressure.cv_ws_closes_total{reason=slow_consumer}",
        "backpressure.cv_ws_overflow_total{reason=drop}",
        "backpressure.cv_ws_resync_total{reason=backpressure}",
        "backpressure.cv_ws_sequence_gaps_detected_total{}",
    ]
    assert evaluate(summary(cv_snap_backpressure=1)).failed() == ["backpressure.resyncs"]


def test_upstream_desync_is_per_topic_per_hour() -> None:
    one = summary(cv_desync_per_ch=trend(1.0, n=1))
    assert evaluate(one).failed() == [
        "s16_3.upstream_desync.per_topic_hour"
    ]  # 1 in 1 h is not "< 1"
    assert evaluate(one, facts=Facts(7200.0)).failed() == []  # 1 in 2 h is


def test_event_loop_lag_is_reported_and_gates_only_when_the_profile_asks() -> None:
    lag = (
        'event_loop_lag_seconds_bucket{le="0.25"} 100\nevent_loop_lag_seconds_bucket{le="+Inf"} 100'
    )
    res = evaluate(summary(), scrape(extra=lag))
    assert res.status == "PASS" and any(
        "event_loop_lag" in c.name and not c.passed for c in res.informational
    )
    assert (
        "c14_2.event_loop_lag.p95"
        in evaluate(summary(), scrape(extra=lag), PROFILE | {"gate_loop_lag": True}).failed()
    )


def test_repro_names_the_headlines_that_moved_more_than_15_percent() -> None:
    def metrics(p95: float) -> dict[str, dict[str, float]]:
        return {"fanout_ms": {"p95": p95}, "rw_bandwidth_kib_s": {"p95": 9.0}}

    assert budgets.repro_diff(metrics(5.0), metrics(5.7)) == {}  # +14 %
    assert budgets.repro_diff(metrics(5.0), metrics(6.0)) == pytest.approx({"fanout_ms": 0.2})


def test_repro_ignores_the_clock_floor_and_what_is_not_a_headline() -> None:
    """+52 % on 0.26 ms of fan-out and 2 to 3 ms on k6's 1 ms clock are the clock, not a change;
    only the design's headline set counts, and a real move in it is still named."""
    a = {"fanout_ms": {"p95": 0.50}, "tick_to_decode_trades_ms": {"p95": 2.0}}
    a |= {"release_decode_book_ms": {"p95": 2.0}, "rw_bandwidth_kib_s": {"p95": 9.0}}
    b = {"fanout_ms": {"p95": 0.76}, "tick_to_decode_trades_ms": {"p95": 3.0}}
    b |= {"release_decode_book_ms": {"p95": 9.0}, "rw_bandwidth_kib_s": {"p95": 12.0}}
    assert budgets.repro_diff(a, b) == pytest.approx({"rw_bandwidth_kib_s": 1 / 3})
    b["tick_to_decode_trades_ms"] = {"p95": 4.0}  # 2 ms is more than a tick of k6's clock
    assert set(budgets.repro_diff(a, b)) == {"rw_bandwidth_kib_s", "tick_to_decode_trades_ms"}
    moved = budgets.repro_diff({"fanout_ms": {"p95": 5.0}}, {"fanout_ms": {"p95": 6.0}})
    assert moved == pytest.approx({"fanout_ms": 0.2})


def test_the_json_thresholds_k6_reads_equal_the_budgets_this_module_judges() -> None:
    from bench.ws import profiles

    th = profiles.load()["thresholds"]
    assert th == {
        "tick_p95_ms": budgets.B3_P95_MS,
        "tick_p99_ms": budgets.B3_P99_MS,
        "local_tick_p95_ms": budgets.LOCAL_P95_MS,
        "bandwidth_kib_s": budgets.BANDWIDTH_KIB_S,
        "resnapshot_kib": budgets.RESNAP_KIB,
        "resnapshot_ms": budgets.RESNAP_MS,
        "client_lag_p95_ms": budgets.CLIENT_LAG_P95_MS,
    }


# -- the baseline gate, at the ticket's 10 % and C-13.9's 5 % ----------------------------------


def _verdict(p95: float) -> Verdict:
    v = Verdict("A", [Check("x", "#6", p95, 20.0, "ms", True)])
    v.metrics = {"fanout_ms": {"p50": p95, "p95": p95, "max": p95, "count": 100.0}}
    return v


def _baseline(version: str = HARNESS_VERSION) -> dict[str, Any]:
    return {
        "harness_version": version,
        "machine_profile": "laptop",
        "gate": "gated",
        "run_profile": "full",
        "metrics": {"fanout_ms": {"p50": 10.0, "p95": 10.0, "max": 10.0, "count": 100.0}},
    }


@pytest.mark.parametrize(
    ("p95", "tolerance", "status"),
    [(10.9, 0.10, "PASS"), (11.5, 0.10, "FAIL"), (10.9, 0.05, "FAIL"), (10.4, 0.05, "PASS")],
)
def test_the_gate_tolerance_is_a_parameter(p95: float, tolerance: float, status: str) -> None:
    g = gate.compare(
        _verdict(p95),
        _baseline(),
        "laptop",
        {"fanout_ms": tolerance},
        "full",
        harness_version=HARNESS_VERSION,
    )
    assert g.status == status


def test_a_baseline_of_another_harness_version_is_not_compared() -> None:
    g = gate.compare(
        _verdict(99.0),
        _baseline("e17-q03/0"),
        "laptop",
        {"fanout_ms": 0.1},
        "full",
        harness_version=HARNESS_VERSION,
    )
    assert not g.gated and g.failures == [] and "e17-q03/0" in g.reason
    legacy = gate.compare(
        _verdict(99.0), _baseline(E08_HARNESS_VERSION), "laptop", {"fanout_ms": 0.1}, "full"
    )
    assert legacy.status == "FAIL"  # E08's own default is unchanged


def test_a_caller_key_never_replaces_what_the_gate_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CI", raising=False)
    extra = {"gate": "gated", "metrics": {}, "commit": "abc"}
    out = gate.record(
        _verdict(10.0), "laptop", "steady 1 s", "full", tmp_path,
        harness_version=HARNESS_VERSION, extra=extra,
    )  # fmt: skip
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["gate"] == "warn-only" and data["metrics"]["fanout_ms"]["p95"] == 10.0
    assert data["commit"] == "abc"  # a key the gate does not write is kept


# -- W5: the rule, pre-registered ------------------------------------------------------------------


def obs(bytes_s: float, p95: float) -> w5.Obs:
    return w5.Obs(bytes_s, bytes_s / 100, p95)


def test_w5_keeps_the_fixed_multipliers_when_every_big_family_gets_relief_at_similar_cost() -> None:
    answer = w5.decide(
        {
            "book": {"healthy": obs(100, 5), "saturated": obs(30, 25)},  # 70 % relief for 20 ms
            "bars": {"healthy": obs(60, 5), "saturated": obs(24, 17)},  # 60 % for 12 ms
        }
    )
    assert answer.recommendation == "keep_fixed" and answer.reasons == []
    assert answer.proposed == {"book": (2, 4), "bars": (2, 4)}


def test_w5_recommends_per_family_when_an_append_family_gets_no_relief_and_pays_in_latency() -> (
    None
):
    answer = w5.decide(
        {
            "book": {"healthy": obs(100, 5), "saturated": obs(30, 25)},
            "trades": {
                "healthy": obs(60, 10),
                "saturated": obs(57, 110),
            },  # 5 % relief at 11x the latency
        }
    )
    assert answer.recommendation == "per_family"
    assert any("trades" in r and "append" in r for r in answer.reasons)
    assert answer.proposed == {"book": (2, 4), "trades": (1, 1)}
    assert "separate design" in answer.note


def test_w5_recommends_per_family_when_efficiencies_differ_by_more_than_2x() -> None:
    answer = w5.decide(
        {
            "book": {"healthy": obs(100, 10), "saturated": obs(20, 14)},  # 0.80 relief / 4 ms
            "bars": {"healthy": obs(90, 10), "saturated": obs(30, 70)},  # 0.67 relief / 60 ms
        }
    )
    assert answer.recommendation == "per_family" and any(
        "efficiency spread" in r for r in answer.reasons
    )


def test_w5_helpers() -> None:
    assert w5.cpu_by_family(0.2, {("book", "healthy"): 0.35, ("trades", "healthy"): 0.1}) == {
        ("book", "healthy"): pytest.approx(0.15),
        ("trades", "healthy"): 0.0,
    }
    assert [w5.intended_class(ms) for ms in (0, 149, 300, 500, 700)] == [
        "healthy",
        "healthy",
        "lagging",
        "lagging",
        "saturated",
    ]
    assert (
        w5.applied_class({}) == "healthy"
        and w5.applied_class({"cv_class_lagging": 2, "cv_class_saturated": 1}) == "saturated"
    )
    o = w5.obs_from_summary(
        {
            "counters": {"cv_frames_book": 100, "cv_bytes_book": 5000},
            "trends": {"cv_hold_ms_book": {"count": 90, "p95": 7}},
        },
        "book",
        10.0,
        conflated=300.0,
    )
    assert o == w5.Obs(500.0, 10.0, 7.0, 4.0)  # 100 frames carrying 400 updates
    assert w5.obs_from_summary({}, "book", 10.0) is None


def test_w5_analyze_reads_the_phases_and_flags_a_class_that_was_not_reached() -> None:
    def phase(
        name: str,
        rtt: int,
        classes: dict[str, float],
        frames: int,
        nbytes: int,
        p95: float,
        cpu: float,
    ) -> w5.Phase:
        counters = {"cv_frames_book": frames, "cv_bytes_book": nbytes} | classes
        summ = {"counters": counters, "trends": {"cv_hold_ms_book": {"count": 9, "p95": p95}}}
        d = budgets.parse_scrape(
            f'process_cpu_seconds_total {cpu}\ncv_ws_conflated_total{{topic="book"}} {frames}'
        )
        return w5.Phase(name, ("book",), rtt, summ, d, 100.0, "PASS")

    idle = w5.Phase(
        "idle", (), 0, {}, budgets.parse_scrape("process_cpu_seconds_total 20"), 100.0, "PASS"
    )
    out = w5.analyze(
        [
            idle,
            phase("mixed-healthy", 0, {}, 1000, 100000, 5, 30),
            phase("mixed-saturated", 700, {"cv_class_saturated": 1}, 400, 30000, 25, 25),
            phase("book-healthy", 0, {}, 10, 10, 1, 35),
            phase("mixed-lagging", 300, {}, 10, 10, 1, 1),
        ]
    )
    assert (
        out["recommendation"] == "keep_fixed"
        and out["applied_class"]["mixed-saturated"] == "saturated"
    )
    assert out["cpu_s_per_s"]["book/healthy"] == pytest.approx(0.15)
    assert any(
        "mixed-lagging" in n for n in out["notes"]
    )  # it ran, but the server never announced lagging
    assert out["skipped"] == ["mixed-lagging"]
    assert w5.exit_code(out) == 1  # half an answer is not a green run
    assert json.dumps(out)  # the artefact is plain JSON


def test_w5_prices_the_wait_in_the_window_that_release_to_decode_cannot_see() -> None:
    """An update held in a window is stamped at its source and released, with the envelope `ts`,
    when the window closes. Decode minus `ts` reads the same 2 ms at x1 and at x4; decode minus the
    source is the window. The rule must price the second, or every family costs the 1 ms floor."""

    def phase(windows: dict[str, float], bytes_by_family: dict[str, int]) -> dict[str, Any]:
        flat = {"count": 100, "p95": 2.0}  # release-to-decode: whatever the window
        counters = {f"cv_frames_{f}": 100 for f in windows} | {
            f"cv_bytes_{f}": n for f, n in bytes_by_family.items()
        }
        return {
            "counters": counters,
            "trends": {
                "cv_release_decode_ms_trades": flat,
                "cv_release_decode_ms_book": flat,
                "cv_release_decode_ms_bars": flat,
                "cv_tick_decode_ms_trades": {"count": 100, "p95": windows["trades"] + 2.0},
                "cv_hold_ms_book": {"count": 100, "p95": windows["book"]},
                "cv_hold_ms_bars": {"count": 100, "p95": windows["bars"]},
            },
        }

    healthy = phase(
        {"trades": 100.0, "book": 50.0, "bars": 250.0},
        {"trades": 60_000, "book": 100_000, "bars": 40_000},
    )
    saturated = phase(  # x4: the windows grow, book and bars merge, trades only batch
        {"trades": 400.0, "book": 200.0, "bars": 1000.0},
        {"trades": 58_000, "book": 30_000, "bars": 16_000},
    )
    obs: dict[str, dict[str, w5.Obs]] = {}
    for fam in ("trades", "book", "bars"):
        h, s = (w5.obs_from_summary(x, fam, 100.0) for x in (healthy, saturated))
        assert h is not None and s is not None
        obs[fam] = {"healthy": h, "saturated": s}
    answer = w5.decide(obs)
    cost = {r["family"]: r["cost_ms"] for r in answer.rows}
    assert cost == pytest.approx({"trades": 300.0, "book": 150.0, "bars": 750.0})
    assert answer.recommendation == "per_family"
    assert any("trades" in r and "append" in r for r in answer.reasons)  # 3 % relief, 3.9x the wait


def test_w5_never_reads_a_family_without_a_staleness_sample_as_zero_latency() -> None:
    only_release = {
        "counters": {"cv_frames_book": 10, "cv_bytes_book": 100},
        "trends": {"cv_release_decode_ms_book": {"count": 10, "p95": 2.0}},
    }
    assert w5.obs_from_summary(only_release, "book", 10.0) is None


def test_a_w5_dispatch_with_no_usable_answer_is_red() -> None:
    row = [{"family": "book"}]
    assert w5.exit_code({"recommendation": "keep_fixed", "skipped": [], "rows": row}) == 0
    assert w5.exit_code({"recommendation": "per_family", "skipped": [], "rows": row}) == 0
    assert w5.exit_code({"recommendation": "no_data", "skipped": [], "rows": []}) == 1
    assert (
        w5.exit_code({"recommendation": "per_family", "skipped": ["mixed-lagging"], "rows": row})
        == 1
    )
    assert (
        w5.exit_code({"recommendation": "keep_fixed", "skipped": [], "rows": []}) == 1
    )  # no table


def test_a_w5_headline_says_every_rule_met_only_for_an_answer_with_a_table() -> None:
    row = [{"family": "book"}]
    met = {"recommendation": "keep_fixed", "reasons": [], "rows": row}
    assert w5.headline(met) == "W5: keep_fixed: every rule met"
    split = {"recommendation": "per_family", "reasons": ["a", "b"], "rows": row}
    assert w5.headline(split) == "W5: per_family: a; b"
    nothing = {"recommendation": "no_data", "reasons": [], "rows": []}
    assert w5.headline(nothing) == "W5: no usable answer"


def mixed(name: str, rtt: int, cls: str | None, *, hold: float | None) -> w5.Phase:
    """A mixed phase that ran and reached its class: its book frames, and a staleness sample
    unless `hold` is None."""
    counters = {"cv_frames_book": 100, "cv_bytes_book": 5000} | (
        {f"cv_class_{cls}": 5} if cls else {}
    )
    trends = {} if hold is None else {"cv_hold_ms_book": {"count": 9, "p95": hold}}
    summ = {"counters": counters, "trends": trends}
    return w5.Phase(name, ("book",), rtt, summ, budgets.parse_scrape(""), 10.0, "PASS")


def test_a_w5_answer_with_no_rows_or_a_missing_mixed_phase_is_red_not_keep_fixed() -> None:
    """The saturated phase ran, in its class, but its frames carried no staleness sample: only the
    healthy side has an observation, no family has both, and an empty table must not read as 'keep
    the multipliers'. A plan that lacks one of the three mixed phases is no whole answer either."""
    healthy, lagging = (
        mixed("mixed-healthy", 0, None, hold=50.0),
        mixed("mixed-lagging", 300, "lagging", hold=100.0),
    )
    blind = w5.analyze([healthy, lagging, mixed("mixed-saturated", 700, "saturated", hold=None)])
    assert blind["recommendation"] == "no_data" and blind["rows"] == [] and blind["skipped"] == []
    assert any("book" in n and "no staleness sample" in n for n in blind["notes"])
    assert w5.exit_code(blind) == 1
    whole = w5.analyze([healthy, lagging, mixed("mixed-saturated", 700, "saturated", hold=200.0)])
    assert whole["rows"] and w5.exit_code(whole) == 0
    short = w5.analyze([healthy, mixed("mixed-saturated", 700, "saturated", hold=200.0)])
    assert short["skipped"] == ["mixed-lagging"] and w5.exit_code(short) == 1


def test_a_profile_can_leave_the_bandwidth_window_to_the_runs_that_read_it() -> None:
    """W5 reads per-family bytes off counters, not the reference workspace's 60 s window, so a short
    dry run of its phases is not INVALID for lacking one."""
    no_window = summary(cv_rw_kib_s=trend(1.0, n=0))
    assert any("no_bandwidth_windows" in x for x in evaluate(no_window).invalid)
    w5_like = evaluate(no_window, prof=PROFILE | {"judge_bandwidth": False})
    assert w5_like.status == "PASS" and not any(
        "bandwidth" in c.name for c in w5_like.verdict.checks
    )
