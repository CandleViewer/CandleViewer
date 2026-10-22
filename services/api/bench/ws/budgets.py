"""Pure verdict logic of the E17-Q03 WS load run: no I/O, no clock, unit-tested on fake input.

What it reads: the k6 `handleSummary` JSON (`tests/load/ws/ws_load.js`) and two `/metrics` scrapes
of the backend (steady-start t0, end t1; every server number is `t1 - t0`, a series absent at t0
counting as 0, because most series are bound lazily). What it gives: a `Verdict` of named `Check`s
(`bench.ingestion.budgets`), the headline `metrics` the baseline gate compares, and the run's
validity. A budget miss fails the run with its check named; a run that trips a validity guard is
INVALID, never a pass or a fail of a budget. The one exception: a failed `scrape.metrics_timeout`
line outranks INVALID, as the stall that trips a guard is the finding.

Budget #6 is read exactly at its bucket edge (`cv_ws_fanout_seconds_bucket{le="0.02"}`), with no
interpolation: the pass rule is that at least 95 % of the weighted samples are at or under 20 ms.
Budget #3 is feeder-stamped print time to k6 decode-complete, and k6's decode-complete approximates
paint (no real paint is measured, the report says so). `gate_on` picks the variant that gates:
`excluding` (decode minus the envelope `ts`, the server's throttle wait out, as budget #6's span
starts at a paced frame's release) or `including`; the other is reported beside it.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from typing import Any, Final

from prometheus_client.parser import text_string_to_metric_families

from bench.ingestion.budgets import Check, Verdict
from bench.ingestion.gate import ABS_FLOOR_MS

#: 06 §2 and 23 §16.3, restated; `profiles.json` `thresholds` mirrors them for k6 (a test pins it).
B6_FANOUT_S: Final = 0.02
B6_QUANTILE: Final = 0.95
B3_P95_MS, B3_P99_MS = 100.0, 250.0  # "under": a reading at the limit misses it
LOCAL_P95_MS, LOCAL_HARD_MS = 40.0, 120.0
BANDWIDTH_KIB_S, BANDWIDTH_HARD_KIB_S = 350.0, 1024.0
RESNAP_KIB, RESNAP_HARD_KIB = 700.0, 2048.0
RESNAP_MS, RESNAP_HARD_MS = 400.0, 1500.0
DESYNC_PER_HOUR, DESYNC_HARD_PER_HOUR = 1.0, 5.0
LOOP_LAG_P95_MS, LOOP_LAG_P99_MS = 50.0, 100.0
CLIENT_LAG_P95_MS: Final = 20.0
#: The ticket's alert rule reads p95 only with this many sampled frames.
MIN_FANOUT_SAMPLES: Final = 40
SAMPLE_EVERY: Final = 32
MIN_FEED_RATIO: Final = 0.99
MAX_CLOCK_SKEW_MS: Final = 5.0
#: k6's trends of the hello's clock skew, absolute ms (`tests/load/ws/lib/skew.js`). The raw one is
#: the server's `clock_skew_ms` as it came: with k6 and the backend on one clock it is the hello's
#: transit and queueing, not drift. The guard judges the corrected one, which takes half the hello's
#: round trip off first. Raw is judged instead for a summary from before the correction (raw trend
#: only). A run that injects a send delay (the self-check) only reports the skew: the delay holds
#: the welcome after the server's stamp, so no reading of it means anything, and budget #6, which
#: the self-check is about, is the server's own histogram.
SKEW_RAW: Final = "cv_clock_skew_ms"
SKEW_CORRECTED: Final = "cv_clock_skew_corrected_ms"
HELLO_RTT: Final = "cv_hello_rtt_ms"
SCRAPE_LINE: Final = "scrape.metrics_timeout"
#: What reads the server's counter deltas, so is not judged when a boundary scrape never answered.
SCRAPE_BUDGETS: Final = (
    "budget6.cv_ws_fanout_seconds.p95",
    "backpressure and sequence series",
    "event-loop lag",
    "feeder ratio",
)
HELD_BUDGET: Final = "connections held at steady start"  # reads the t0 scrape alone
MAX_K6_CPU_FRAC: Final = 0.8
REPRO_TOLERANCE: Final = 0.15
#: k6 times in whole milliseconds: a latency it reports moving by that much has not changed.
K6_CLOCK_MS: Final = 1.0
#: AC 5's headline metrics (design 7): what a second run of a profile must reproduce.
HEADLINES: Final = (
    "fanout_ms",
    "tick_to_decode_trades_ms",
    "rw_bandwidth_kib_s",
    "resnapshot_kib",
    "resnapshot_ms",
    "backend_cpu_s_per_s",
    "backend_rss_mb",
)
#: Not measurable on main (the producers are pending, #2197): reported, never faked.
NOT_MEASURABLE: Final = (
    "footprint and heatmap frames: no producer (#2197, #593, #605), so their share of the "
    "re-snapshot and the bandwidth rows is not measured",
    "frame decode and fps rows (23 16.3): the browser's, with E17-K01's Chromium numbers",
    "upstream_desync per topic-hour: the feeder is not ingestion, so no upstream desync can occur "
    "and the row reads 0 by construction (a property of the harness, not a pass)",
    "full re-snapshot bytes and time: book, trades and the bars the run built, with no footprint "
    "or heatmap and a series shallower than the default history, so a pass here does not show "
    "700 KiB and 400 ms met",
)

Scrape = dict[tuple[str, tuple[tuple[str, str], ...]], float]


def parse_scrape(text: str) -> Scrape:
    """A Prometheus text exposition as `(sample name, sorted labels) -> value`."""
    out: Scrape = {}
    for fam in text_string_to_metric_families(text):
        for s in fam.samples:
            out[(s.name, tuple(sorted(s.labels.items())))] = s.value
    return out


def delta(t0: Scrape, t1: Scrape) -> Scrape:
    return {k: v - t0.get(k, 0.0) for k, v in t1.items()}


def total(d: Scrape, name: str, **labels: str) -> float:
    """The sum of the series `name` whose labels include `labels` (0 when none exists)."""
    want = set(labels.items())
    return sum(v for (n, ls), v in d.items() if n == name and want <= set(ls))


def series(d: Scrape, name: str) -> dict[str, float]:
    """Each series of `name` by its labels (`a=1,b=2`): what a failed check names."""
    return {
        ",".join(f"{k}={x}" for k, x in ls if k != "env"): v
        for (n, ls), v in d.items()
        if n == name
    }


def quantile(d: Scrape, name: str, q: float) -> float | None:
    """`histogram_quantile`: linear inside the bucket the rank falls in; `None` with no samples."""
    buckets: dict[float, float] = {}
    for (n, ls), v in d.items():
        if n == f"{name}_bucket":
            text = dict(ls)["le"]
            bound = math.inf if text == "+Inf" else float(text)
            buckets[bound] = buckets.get(bound, 0.0) + v
    if buckets.get(math.inf, 0.0) <= 0:
        return None
    rank, prev_le, prev_n = q * buckets[math.inf], 0.0, 0.0
    for le in sorted(buckets):
        if buckets[le] >= rank:
            if math.isinf(le) or buckets[le] == prev_n:
                return prev_le
            return prev_le + (le - prev_le) * (rank - prev_n) / (buckets[le] - prev_n)
        prev_le, prev_n = le, buckets[le]
    return prev_le


def fraction_le(d: Scrape, name: str, edge: float) -> tuple[float, float]:
    """`(share of the weighted samples at or under `edge`, their total)`, at the bucket edge."""
    count = total(d, f"{name}_count")
    at = sum(
        v for (n, ls), v in d.items() if n == f"{name}_bucket" and float(dict(ls)["le"]) == edge
    )
    return (at / count if count else 0.0), count


@dataclass(slots=True)
class ScrapeTally:
    """The steady state's `/metrics` scrapes as the runner tallies them (`run.json`: `scrapes`):
    `attempted` counts the periodic ones and the two boundary ones (`t0`, `t1`), `timed_out_ms` how
    long each scrape that timed out waited (a retry's wait included), `missing` the boundary scrapes
    that never answered (the counter deltas are then unread), `retried` those a retry answered."""

    timeout_s: float
    attempted: int = 0
    timed_out_ms: list[float] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    retried: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class Facts:
    """What the runner measured around k6 and the backend (all optional: a unit test omits them)."""

    steady_s: float
    k6_cpu_frac: float | None = None
    rss_bytes: int | None = None
    mem_max_bytes: int | None = None
    oom_events: int = 0
    cpu_s: float | None = None  # backend CPU seconds over the steady window
    scrapes: ScrapeTally | None = None  # None: a run saved before the counts
    steady_actual_s: float | None = None  # real seconds t0 to t1; None: a run saved before it


def _ms(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1f} ms"


@dataclass(frozen=True, slots=True)
class ClockSkew:
    """The hello's clock skew k6 measured, in absolute ms: the figure the guard reads, and why."""

    max_ms: float  # the max over the hellos; compared with `MAX_CLOCK_SKEW_MS` when `judged`
    raw: float | None  # the max of the server's own `clock_skew_ms`
    rtt_p50: float | None  # the hello-to-welcome round trip
    rtt_max: float | None
    hellos: int  # the samples behind `max_ms`
    rtt_corrected: bool  # `max_ms` is RTT-corrected; False: it is the raw max (see `clock_skew`)
    send_delay_ms: float = 0.0  # the run's injected send delay: the skew is reported, not judged

    @property
    def judged(self) -> bool:
        return self.send_delay_ms <= 0

    @property
    def text(self) -> str:
        """What the guard read, for the INVALID line and the report: `corrected max 3.0 ms against
        5 ms (max over 6 hellos of |raw - RTT/2|; raw max 13.0 ms; hello RTT p50 20.0 ms / ...)`."""
        if self.rtt_corrected:
            kind, of, note = "corrected", "|raw - RTT/2|", f"raw max {_ms(self.raw)}"
        else:
            kind, of = "raw", "|raw|"
            note = f"not RTT-corrected: the summary has no {SKEW_CORRECTED}"
            if not self.judged:
                note = f"send delay {self.send_delay_ms:g} ms injected: reported, not judged"
        hellos = f"{self.hellos} hello{'s' if self.hellos > 1 else ''}"
        parts = [f"max over {hellos} of {of}", note]
        if self.rtt_max is not None:
            parts.append(f"hello RTT p50 {_ms(self.rtt_p50)} / max {_ms(self.rtt_max)}")
        head = f"{kind} max {self.max_ms:.1f} ms"
        if self.judged:
            head += f" against {MAX_CLOCK_SKEW_MS:g} ms"
        return f"{head} ({'; '.join(parts)})"


@dataclass(slots=True)
class Result:
    verdict: Verdict
    invalid: list[str] = field(default_factory=list)
    informational: list[Check] = field(default_factory=list)
    clock_skew: ClockSkew | None = None  # what the clock-skew guard read, reported beside it
    not_judged: list[str] = field(default_factory=list)  # budgets a lost boundary scrape left out

    @property
    def status(self) -> str:
        if SCRAPE_LINE in self.failed():  # outranks INVALID; the guards it trips stay listed
            return "FAIL"
        return "INVALID" if self.invalid else "PASS" if self.verdict.passed else "FAIL"

    @property
    def exit_code(self) -> int:
        return {"PASS": 0, "FAIL": 1, "INVALID": 2}[self.status]

    def failed(self) -> list[str]:
        return [c.name for c in self.verdict.checks if c.hard and not c.passed]

    def as_dict(self) -> dict[str, Any]:
        return self.verdict.as_dict() | {
            "status": self.status,
            "invalid": self.invalid,
            "informational": [asdict(c) for c in self.informational],
            "clock_skew": {**asdict(cs), "judged": cs.judged} if (cs := self.clock_skew) else None,
            "not_judged": self.not_judged,
            "not_measurable": list(NOT_MEASURABLE),
        }


def _check(
    name: str,
    budget: str,
    measured: float,
    limit: float,
    unit: str,
    *,
    hard_line: float | None = None,
    strict: bool = False,
    hard: bool = True,
    note: str = "",
) -> Check:
    ok = measured < limit if strict else measured <= limit
    if not ok and hard_line is not None and measured > hard_line:
        note = f"{note} beyond the hard-fail line {hard_line:g} {unit}".strip()
    return Check(name, budget, measured, limit, unit, ok, hard, note)


def _stat(summ: Mapping[str, Any], name: str, key: str) -> float | None:
    trend = summ.get("trends", {}).get(name)
    return None if not trend or not trend.get("count") else float(trend[key])


def _scalar(value: float, n: float = 1.0) -> dict[str, float]:
    return {"p50": value, "p95": value, "max": value, "count": n}


def clock_skew(summ: Mapping[str, Any], send_delay_ms: float = 0.0) -> ClockSkew | None:
    """The hello's clock skew from the k6 summary: the corrected trend is read. The raw one is read
    instead when the run injects a send delay (it holds the welcome after the server's stamp, which
    breaks the correction's even split of the round trip) and for a summary from before the
    correction. `None` when no welcome was timed."""
    raw, corrected = _stat(summ, SKEW_RAW, "max"), _stat(summ, SKEW_CORRECTED, "max")
    rtt_corrected = corrected is not None and send_delay_ms <= 0
    read = corrected if rtt_corrected else raw
    if read is None:
        return None
    hellos = int(_stat(summ, SKEW_CORRECTED if rtt_corrected else SKEW_RAW, "count") or 0)
    rtt_p50, rtt_max = _stat(summ, HELLO_RTT, "p50"), _stat(summ, HELLO_RTT, "max")
    return ClockSkew(read, raw, rtt_p50, rtt_max, hellos, rtt_corrected, send_delay_ms)


def evaluate(
    prof: Mapping[str, Any], summ: Mapping[str, Any], t0: Scrape, t1: Scrape, facts: Facts
) -> Result:
    """The run's verdict. `prof` is the resolved profile (`flag`, `gate_on`, `probe`, `name`)."""
    sc = facts.scrapes
    lost = sc.missing if sc else []  # the boundary scrapes that never answered
    d = {} if lost else delta(t0, t1)
    v = Verdict(str(prof["name"]))
    res = Result(v)
    counters: Mapping[str, float] = summ.get("counters", {})
    incl = prof.get("gate_on", "excluding") == "including"
    hours = facts.steady_s / 3600.0
    m = v.metrics

    if sc and sc.attempted:  # a run saved before the counts has none
        n, within = len(sc.timed_out_ms), f"within {sc.timeout_s:g} s"
        note = f"all {sc.attempted} scrapes answered {within}"
        if n:
            note = f"backend did not answer /metrics {within}, {n} of {sc.attempted} scrapes"
        v.add(Check(SCRAPE_LINE, "ticket", n, 0.0, "scrapes", n == 0, True, note))

    # budget #6, from the server's own histogram
    share, count = fraction_le(d, "cv_ws_fanout_seconds", B6_FANOUT_S)
    p95s = quantile(d, "cv_ws_fanout_seconds", B6_QUANTILE)
    if lost:  # the budgets that read the scrape deltas have no window to read
        gone = f"{' and '.join(lost)} scrape timed out"
        names = [*SCRAPE_BUDGETS, *([HELD_BUDGET] if "t0" in lost else [])]
        res.not_judged = [f"{b}: not judged ({gone})" for b in names]
    elif count < MIN_FANOUT_SAMPLES * SAMPLE_EVERY:
        res.invalid.append(
            f"fanout_samples: {count / SAMPLE_EVERY:.0f} sampled frames, need {MIN_FANOUT_SAMPLES}"
        )
    else:
        frames = count / SAMPLE_EVERY
        v.add(
            Check(
                "budget6.cv_ws_fanout_seconds.p95",
                "#6",
                (p95s or 0.0) * 1000,
                B6_FANOUT_S * 1000,
                "ms",
                share >= B6_QUANTILE,
                True,
                f"{share:.1%} of {frames:.0f} sampled frames at or under 20 ms",
            )
        )
        fq = [(quantile(d, "cv_ws_fanout_seconds", x) or 0.0) * 1000 for x in (0.5, 0.95, 0.99)]
        m["fanout_ms"] = {"p50": fq[0], "p95": fq[1], "p99": fq[2], "count": frames}

    # budget #3 and the 23 16.3 local line, from k6's decode-complete
    incl_t, excl_t = "cv_tick_decode_ms_trades", "cv_release_decode_ms_trades"
    gated, other = (incl_t, excl_t) if incl else (excl_t, incl_t)
    for tag, trend, hard in (("", gated, True), (".other_variant", other, False)):
        p95, p99 = _stat(summ, trend, "p95"), _stat(summ, trend, "p99")
        if p95 is None or p99 is None:
            if hard:
                res.invalid.append(f"no_trades_latency_samples: {trend}")
            continue
        note = f"{'including' if trend == incl_t else 'excluding'} the server's throttle wait"
        rows = (
            (f"budget3.tick_to_decode.trades.p95{tag}", "#3", p95, B3_P95_MS, None),
            (f"budget3.tick_to_decode.trades.p99{tag}", "#3", p99, B3_P99_MS, None),
            (f"s16_3.tick_to_pixel.p95{tag}", "23 16.3", p95, LOCAL_P95_MS, LOCAL_HARD_MS),
        )
        for name, budget, val, lim, hard_line in rows:
            c = _check(
                name, budget, val, lim, "ms", hard_line=hard_line, strict=True, hard=hard, note=note
            )
            (v.checks if hard else res.informational).append(c)
        if hard:
            m["tick_to_decode_trades_ms"] = {
                "p50": _stat(summ, trend, "p50") or 0.0,
                "p95": p95,
                "p99": p99,
                "count": _stat(summ, trend, "count") or 0.0,
            }
    for fam in ("book", "bars"):  # delivery after a window's release (`ts`), not the wait in it
        p95 = _stat(summ, f"cv_release_decode_ms_{fam}", "p95")
        if p95 is not None:
            m[f"release_decode_{fam}_ms"] = _scalar(
                p95, _stat(summ, f"cv_release_decode_ms_{fam}", "count") or 0
            )

    # 23 16.3 bandwidth and re-snapshot
    bw = _stat(summ, "cv_rw_kib_s", "max")
    if not prof.get("judge_bandwidth", True):
        pass  # W5 reads per-family bytes off counters: it has no use for a 60 s window
    elif bw is None:
        res.invalid.append(
            "no_bandwidth_windows: no 60 s window of the reference workspace completed"
        )
    else:
        v.add(
            _check(
                "s16_3.bandwidth.reference_workspace",
                "23 16.3",
                bw,
                BANDWIDTH_KIB_S,
                "KiB/s",
                hard_line=BANDWIDTH_HARD_KIB_S,
                strict=True,
            )
        )
        m["rw_bandwidth_kib_s"] = _scalar(bw)
    if prof.get("probe"):
        kib, ms = _stat(summ, "cv_resnap_kib", "max"), _stat(summ, "cv_resnap_ms", "max")
        if kib is None or ms is None:
            res.invalid.append("no_resnapshot_samples: the probe completed no re-snapshot")
        else:
            part = "no footprint or heatmap, a shallow bars series"
            v.add(
                _check(
                    "s16_3.resnapshot.bytes", "23 16.3", kib, RESNAP_KIB, "KiB",
                    hard_line=RESNAP_HARD_KIB, strict=True, note=part,
                )
            )  # fmt: skip
            v.add(
                _check(
                    "s16_3.resnapshot.ms", "23 16.3", ms, RESNAP_MS, "ms",
                    hard_line=RESNAP_HARD_MS, strict=True, note=part,
                )
            )  # fmt: skip
            m["resnapshot_kib"], m["resnapshot_ms"] = _scalar(kib), _scalar(ms)
    per_hour = (_stat(summ, "cv_desync_per_ch", "max") or 0.0) / max(hours, 1e-9)
    v.add(
        _check(
            "s16_3.upstream_desync.per_topic_hour",
            "23 16.3",
            per_hour,
            DESYNC_PER_HOUR,
            "/h",
            hard_line=DESYNC_HARD_PER_HOUR,
            strict=True,
            note="no ingestion in the loop: reads 0 by construction",
        )
    )

    # ticket: zero resyncs from backpressure, zero gaps. Every non-zero series is named.
    v.add(
        _check(
            "backpressure.resyncs",
            "ticket",
            counters.get("cv_snap_backpressure", 0.0),
            0.0,
            "snaps",
        )
    )
    for name, want in (
        ("cv_ws_resync_total", "reason=backpressure"),
        ("cv_ws_overflow_total", ""),
        ("cv_ws_closes_total", "reason=slow_consumer"),
        ("cv_ws_sequence_gaps_detected_total", ""),
    ):
        for key, val in sorted(series(d, name).items()):
            if val > 0 and want in key:
                v.add(_check(f"backpressure.{name}{{{key}}}", "ticket", val, 0.0, "events"))
    v.add(_check("sequence.gaps", "ticket", counters.get("cv_seq_gaps", 0.0), 0.0, "gaps"))

    # C-14.2 event-loop lag: reported, gated only when the profile asks
    for q, limit in ((0.95, LOOP_LAG_P95_MS), (0.99, LOOP_LAG_P99_MS)):
        lag = quantile(d, "event_loop_lag_seconds", q)
        if lag is not None:
            c = _check(
                f"c14_2.event_loop_lag.p{int(q * 100)}",
                "C-14.2",
                lag * 1000,
                limit,
                "ms",
                hard=bool(prof.get("gate_loop_lag")),
            )
            (v.checks if c.hard else res.informational).append(c)
            if q == 0.95:
                m["event_loop_lag_ms"] = _scalar(lag * 1000)

    frames = sum(v for k, v in counters.items() if k.startswith("cv_frames_"))
    if frames:  # E17-T06: about one data frame in 32 carries a span id (23 3.1)
        share = counters.get("cv_sp_frames", 0.0) / frames
        ok = 1 / (2 * SAMPLE_EVERY) <= share <= 2 / SAMPLE_EVERY
        res.informational.append(
            Check(
                "e17_t06.sp_share",
                "E17-T06",
                share,
                2 / SAMPLE_EVERY,
                "share",
                ok,
                False,
                "1 in 32",
            )
        )

    # validity: a run that trips one proves nothing about a budget
    sched, pub = (
        total(d, "cv_bench_feed_scheduled_total"),
        total(d, "cv_bench_feed_published_total"),
    )
    if sched and pub / sched < MIN_FEED_RATIO:
        res.invalid.append(f"feeder_behind: published {pub:.0f} of {sched:.0f} scheduled slots")
    # the runner hands the backend `int(send_delay_ms)`: 0.5 injects no delay, so it is judged
    skew = clock_skew(summ, float(int(prof.get("send_delay_ms") or 0)))
    res.clock_skew = skew
    if skew is not None and skew.judged and skew.max_ms > MAX_CLOCK_SKEW_MS:
        res.invalid.append(f"clock_skew: {skew.text}")
    lag95 = _stat(summ, "cv_client_lag_ms", "p95")
    if lag95 is not None and lag95 >= CLIENT_LAG_P95_MS:
        res.invalid.append(f"cv_client_lag_ms: p95 {lag95:.1f} ms, the k6 client is the bottleneck")
    if facts.k6_cpu_frac is not None and facts.k6_cpu_frac >= MAX_K6_CPU_FRAC:
        res.invalid.append(f"k6_cpu: {facts.k6_cpu_frac:.0%} of its cpuset")
    for name in ("cv_unplanned_closes", "cv_auth_failures", "cv_errors", "cv_sub_refused"):
        if counters.get(name, 0.0) > 0:
            res.invalid.append(f"{name}: {counters[name]:.0f}")
    planned = int(prof["users"]) * int(prof["connections"]) + int(bool(prof.get("probe")))
    up, held = counters.get("cv_connections_up", 0.0), total(t0, "cv_ws_connections_in_use")
    unread = "t0" in lost  # no t0 scrape: the count is not measured, not 0
    if up < planned or (held < planned and not unread):  # a lighter load proves nothing
        at_start = f"{held:.0f} held at steady start"
        if unread:
            at_start = "held at steady start not measured (t0 scrape timed out)"
        res.invalid.append(
            f"connections_short: {up:.0f} authenticated and {at_start}, {planned} planned"
        )
    if facts.oom_events or (
        facts.rss_bytes and facts.mem_max_bytes and facts.rss_bytes >= facts.mem_max_bytes
    ):
        res.invalid.append(f"backend_memory: rss {facts.rss_bytes}, oom events {facts.oom_events}")
    if facts.mem_max_bytes and not facts.rss_bytes:  # a cap, but no periodic reading
        tried = bool(sc and len(sc.timed_out_ms) - len(sc.retried) - len(sc.missing) > 0)
        was = "answered" if tried else "due"  # all periodic scrapes timed out, or none was due
        res.not_judged.append(f"backend_memory rss: not judged (no periodic scrape was {was})")
    if facts.steady_s <= 0:
        res.invalid.append("no_steady_window")
    if facts.cpu_s is not None and facts.steady_s > 0 and not lost:  # a lost boundary: no delta
        m["backend_cpu_s_per_s"] = _scalar(facts.cpu_s / (facts.steady_actual_s or facts.steady_s))
    if facts.rss_bytes:
        m["backend_rss_mb"] = _scalar(facts.rss_bytes / 2**20)
    return res


def expect_failure(res: Result, name: str) -> tuple[bool, str]:
    """The self-check: the run must FAIL, with no guard tripped, and name `name` (the
    deliberately inflated metric)."""
    ok = res.status == "FAIL" and name in res.failed() and not res.invalid
    failed, invalid = ", ".join(res.failed()) or "none", "; ".join(res.invalid) or "none"
    return ok, f"{res.status}; failed: {failed}; invalid: {invalid}"


def repro_diff(
    a: Mapping[str, Mapping[str, float]],
    b: Mapping[str, Mapping[str, float]],
    tol: float = REPRO_TOLERANCE,
) -> dict[str, float]:
    """The headline metrics (`HEADLINES`, the `p95` of each) whose second run differs from the first
    by more than `tol` of the first (AC 5: within 15 %, or the variance source is named). A latency
    that moved by no more than the clock's resolution is not a change: the baseline gate's floor
    for the server's own histogram (`fanout_ms`), k6's whole millisecond for what k6 times."""
    out: dict[str, float] = {}
    for name in HEADLINES:
        if name not in a or name not in b:
            continue
        first, second = float(a[name]["p95"]), float(b[name]["p95"])
        floor = ABS_FLOOR_MS if name == "fanout_ms" else K6_CLOCK_MS
        if name.endswith("_ms") and abs(second - first) <= floor:
            continue
        rel = abs(second - first) / first if first else (0.0 if second == 0 else math.inf)
        if rel > tol:
            out[name] = rel
    return out
