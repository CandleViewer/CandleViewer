"""E25-D01 contract audit: what the plan docs and the shipped rule vocabulary say about detectors.

Standalone, offline, stdlib only. Nothing here is market or user evidence; the tool reads the repo's
own text and prints, with a source label on every row, (1) every regime vocabulary and how many
distinct ones exist, (2) every speed-of-tape window, baseline and update cadence named anywhere,
(3) the parameter names and defaults of the iceberg, stop-run and absorption detectors per source,
(4) where each document places the computation (client-side vs backend-side, with the matched
phrase per component so a hedge such as CMP-134's is visible), (5) the analytics events named on
the `- **Analytics/audit:**` lines of SCR-055..059 (only those lines, so a pointer line that
mentions an event name never counts), (6) the Poisson noise floor of a trades-per-second window at
1 / 5 / 30 s (the arithmetic the report's window recommendation quotes; a lower bound, since real
tape is overdispersed), (6b) the deterministic-mean step response of those windows and of three
rolling-baseline lengths to a sustained burst — detection latency, re-normalisation, the dip after
the burst, warm-up — under two sd models printed side by side, the Poisson sd and the baseline
window's sample sd (the baseline trade-off of F4c / Q13), with a median/MAD baseline's cliff at
B / 2 and, by a seeded brute force with Poisson draws, where its hold ends once the buckets are
noisy, (7) the `22` `MetricCode` members against the shipped vocabulary's codes (G11) and (8) the
Sprint 10 and 13 dates from `calendar_cv.py`. A row reads NOT FOUND when the anchor text moved; the
tool never guesses a value and never raises on a moved anchor. Results are TypedDicts, so
`mypy --strict` is clean (delta lens round 2, item 8). The lens rounds are named as the report names
them: the pre-PR lens, then the orchestrator's text lens rounds 1, 3 and 4 and delta lens round 2.

Usage: python3 -I docs/design/_tools/e25_d01_contract_audit.py          (Markdown)
       python3 -I docs/design/_tools/e25_d01_contract_audit.py --json   (the boards' numbers)
"""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import math
import re
import sys
from collections.abc import Callable
from pathlib import Path
from statistics import median, median_low
from typing import TypedDict

ROOT = Path(__file__).resolve().parents[3]
PLAN = "docs/plan/"
SHIPPED = "services/api/candleviewer/rules/vocabulary/metrics.py"
# prints/s; 5 is the order of the one recorded BTCUSDT window (E22-D01 §3.0), shape only
RATES = (5, 50)
WINDOWS_S = (1, 5, 30)  # the windows 11 / 14 / 22 name
Z, PUSH_HZ, COOLDOWN_S = 3.0, 4, 60  # US-DET-002 z > 3; SCR-055 4 Hz; US-DET-002 cooldown 60 s
SCAN_PER_S = 4.0  # one-token scan, E22-D01 F5 (heuristic)
BURST_K = 3.0  # a sustained burst at 3x the usual rate (shape only, like the noise floor)
MAD_SCALE = 1.4826  # MAD-to-sd consistency constant, so the median/MAD z compares with the sd ones
MEDIAN_SEEDS = 20  # seeded runs of the median/MAD brute force (text lens round 4, item 2)
BASELINES_S = {  # the three rolling-baseline lengths the sources name (F5, C3, Q13)
    300: "shipped tape_speed_zscore base_ms=300000; 22 '1 s vs 300 s baseline'",
    1200: "Jigsaw POT Average Time, '20 minutes is the default' (report 3.2)",
    3600: "14 SCR-055 A11y readout 'above the 1-hour mean'",
}
HEDGE = "or by a backend detector service"  # CMP-134's placement hedge (15-component-catalogue.md)
ZONE_CODES = (  # the imbalance-zone codes F13's layout reads (shipped metrics.py; F13, F14, G11)
    "nearest_imbalance_zone_distance",
    "imbalance_zone_side",
    "imbalance_zone_strength",
    "imbalance_zone_mitigated",
    "imbalance_zone_retest_count",
    "imbalance_hold_rate",
)


class Regime(TypedDict):  # the result shapes, so `mypy --strict` passes (delta lens round 2, 8)
    raw: dict[str, str | None]
    sets: dict[str, list[str]]
    sources: int
    distinct: int


class Params(TypedDict):
    by_source: dict[str, list[str]]
    distinct_name_sets: int


class Placement(TypedDict):
    components_saying_client_side: int
    hedged: str
    phrases: dict[str, str]
    screens_saying_backend_side: int


class Noise(TypedDict):
    rows: dict[str, dict[str, float]]
    cooldown_cap_per_h: int
    digit_swaps_vs_scan: float


class Step(TypedDict):
    rate_per_s: int
    burst_multiple: float
    display_window_s: int
    detect_latency_s: dict[str, float]
    extreme_fraction_of_b: dict[str, float]
    baselines: dict[str, dict[str, str | int]]


class Codes(TypedDict):
    contract_members: int
    shipped_metric_codes: int
    shipped_indicator_series: int
    shared: list[str]
    unmatched_contract_members: list[str]
    zone_codes_missing: list[str]


def read_text(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def grab(rel: str, pattern: str, group: int = 1) -> str | None:
    m = re.search(pattern, read_text(rel), re.DOTALL)
    return re.sub(r"\s+", " ", m.group(group)).strip() if m else None


def block(rel: str, start: str, end: str) -> str:
    """Text between the first `start` heading and the next `end`; '' when `start` moved."""
    t = read_text(rel)
    try:
        i = t.index(start)
    except ValueError:
        return ""  # the dependent rows then read NOT FOUND instead of killing the run
    j = t.find(end, i + len(start))
    return t[i : j if j > 0 else len(t)]


def regime_vocabularies() -> Regime:
    found = {
        "11 US-DET-008": grab(PLAN + "11-user-stories.md", r"classified as ([a-z, ]+ or calm)"),
        "14 SCR-057": grab(PLAN + "14-screens-catalogue.md", r"Classification badge \(([^)]*)\)"),
        "15 CMP-133": grab(PLAN + "15-component-catalogue.md", r"`regime: ([^`]*)` · `confidence`"),
        "21 §4.11": grab(PLAN + "21-database-schema.md", r"regime\s+SYMBOL[^\n]*--\s*([^\n]*)"),
        "22 RegimeExplanation": grab(
            PLAN + "22-api-openapi.yaml", r"RegimeExplanation:.*?enum: \[([^\]]*)\]"
        ),
        "24 §7.2": grab(PLAN + "24-internal-schemas.md", r"`market_regime`\s*\|\s*enum `([^`]*)`"),
        "30 §6.2": grab(PLAN + "30-release-roadmap.md", r"market-regime classifier \(([^)]*)\)"),
        "shipped metrics.py": grab(SHIPPED, r'"market_regime", "Market regime", "enum:([^"]*)"'),
    }
    sets: dict[str, list[str]] = {}
    for src, raw in found.items():
        if raw is None:
            continue
        toks = re.split(r"[|/,]| or ", raw.replace("\\|", "|").replace("`", ""))
        sets[src] = sorted({t.strip().strip("'\"").lower() for t in toks if t.strip()})
    distinct = {tuple(v) for v in sets.values()}
    return {"raw": found, "sets": sets, "sources": len(sets), "distinct": len(distinct)}


def tape_windows() -> dict[str, str | None]:
    s11, s14, s22, s23 = (
        PLAN + "11-user-stories.md",
        PLAN + "14-screens-catalogue.md",
        PLAN + "22-api-openapi.yaml",
        PLAN + "23-ws-protocol.md",
    )
    return {
        "11 US-DET-001 given window": grab(s11, r"Given a (\d+-second window)"),
        "11 US-DET-001 switched window": grab(s11, r"switch to a (\d+-second window)"),
        "11 US-DET-001 NFR cadence": grab(s11, r"NFR: update at (\d+ Hz)"),
        "11 US-DET-002 threshold / cooldown": " / ".join(
            x or "NOT FOUND"
            for x in (
                grab(s11, r"threshold of (z > 3)"),
                grab(s11, r"cooldown [^.]*default (\d+ s)"),
            )
        ),
        "14 SCR-055 Data windows": grab(s14, r"`metrics\.\{symbol\}`; window ([^.]*)\."),
        "14 SCR-055 checklist selector": grab(s14, r"rolling window selector \(([^)]*)\)"),
        "14 SCR-055 Performance cadence": grab(s14, r"pushed on `metrics\.\{symbol\}` at (\d+ Hz)"),
        "14 SCR-055 A11y baseline": grab(s14, r"sigma above the (1-hour mean)"),
        "14 SCR-057 Performance cadence": grab(
            s14, r"pushed on `metrics\.\{symbol\}` at most (\d+ Hz)"
        ),
        "22 /market/metrics windows": grab(s22, r"`book_updates_per_sec` \(windows ([^)]*)\)"),
        "22 tape_acceleration": grab(s22, r"`tape_acceleration` \(([^)]*)\)"),
        "23 metrics.{symbol} default throttle": grab(
            s23, r"`metrics\.\{symbol\}`\s*\|[^|]*\|[^|]*\|\s*(\d+ ms)"
        ),
        "shipped tape_speed params": grab(
            SHIPPED, r'"tape_speed", "Tape speed", "count", _T, "([^"]*)"'
        ),
        "shipped tape_speed_zscore params": grab(
            SHIPPED, r'"tape_speed_zscore", [^\n]*?_T, "([^"]*)"'
        ),
        "shipped book_speed params": grab(
            SHIPPED, r'"book_speed", "Book speed", "count", _B, "([^"]*)"'
        ),
    }


def detector_params() -> dict[str, Params | str | None]:
    s22, s24, s14 = (
        PLAN + "22-api-openapi.yaml",
        PLAN + "24-internal-schemas.md",
        PLAN + "14-screens-catalogue.md",
    )
    cfg = block(s22, "    DetectorConfig:", "    DetectorMethodology:")
    names24 = {"iceberg": "iceberg_present_at_level", "stop_run": "stop_run_detected"}
    out: dict[str, Params | str | None] = {}
    for det in ("iceberg", "stop_run", "absorption"):
        desc = grab(s22, r"`" + det + r"` \(([^)]*)\)") or ""
        desc_pairs = [p.strip() for p in desc.split(",") if "estimated" not in p and p.strip()]
        sub = re.search(r"        " + det + r":\n(.*?)(?=\n        \w+:|\Z)", cfg, re.DOTALL)
        cfg_pairs = (
            [
                f"{n} {d.strip()}"
                for n, d in re.findall(r"(\w+): \{[^}]*default: ([^,}]*)", sub.group(1))
            ]
            if sub
            else []
        )
        cell = grab(s24, r"`" + names24.get(det, det) + r"`\s*\|[^|]*\|([^|]*)\|") or ""
        pairs24 = [p.replace("=", " ") for p in re.findall(r"`([^`]*)`", cell)]
        ship = (
            grab(SHIPPED, r'"' + names24.get(det, det) + r'", "[^"]*", "[^"]*", _[A-Z], "([^"]*)"')
            or ""
        )
        ship_pairs = [p.replace("=", " ") for p in ship.split(";") if p]
        by_src = {
            "22 /market/metrics description": desc_pairs,
            "22 DetectorConfig": [p for p in cfg_pairs if not p.startswith("enabled")],
            "24 §7.2": pairs24,
            "shipped metrics.py": ship_pairs,
        }
        name_sets = {tuple(sorted(p.split()[0] for p in v)) for v in by_src.values() if v}
        out[det] = {"by_source": by_src, "distinct_name_sets": len(name_sets)}
    out["14 SCR-059 threshold names"] = grab(s14, r"explicit thresholds \(([^)]*)\)")
    return out


def placement() -> Placement:
    """Per component the clause saying client-side (hedges visible); per screen, backend-side."""
    s14, s15 = PLAN + "14-screens-catalogue.md", PLAN + "15-component-catalogue.md"
    cmps = (
        ("CMP-131", "CMP-132"),
        ("CMP-132", "CMP-133"),
        ("CMP-133", "CMP-134"),
        ("CMP-134", "CMP-135"),
    )
    scrs = (("SCR-055", "SCR-056"), ("SCR-056", "SCR-057"), ("SCR-057", "SCR-058"))
    phrases: dict[str, str] = {}
    for a, b in cmps:
        m = re.search(r"[^.;\n]*client-side[^.;\n]*", block(s15, f"### {a}", f"### {b}"))
        phrases[a] = re.sub(r"\s+", " ", m.group(0)).strip() if m else "NOT FOUND"
    return {
        "components_saying_client_side": sum(p != "NOT FOUND" for p in phrases.values()),
        "hedged": ", ".join(c for c, p in phrases.items() if HEDGE in p) or "none",
        "phrases": phrases,
        "screens_saying_backend_side": sum(
            "backend-side" in block(s14, f"### {a}", f"### {b}") for a, b in scrs
        ),
    }


def analytics() -> dict[str, int]:
    """Event names counted on the `- **Analytics/audit:**` lines of SCR-055..059 only."""
    s14 = PLAN + "14-screens-catalogue.md"
    lines = [
        ln
        for n in range(55, 60)
        for ln in block(s14, f"### SCR-0{n}", f"### SCR-0{n + 1}").splitlines()
        if ln.startswith("- **Analytics/audit:**")
    ]
    joined = "\n".join(lines)
    return {
        k: joined.count(k)
        for k in ("methodology.opened", "regime.explain_opened", "regime.panel_opened")
    }


def metric_codes() -> Codes:
    """`22` `MetricCode` vs the shipped vocabulary, matched by name (G11): the `_ROWS` metric
    descriptors (10-tuples — name, title, unit, input, params, warm-up, …) and the `_KERNEL_BOUND`
    indicator series (7-tuples — metric, indicator, output, title, tape flag, …) of `metrics.py`."""
    enum = block(PLAN + "22-api-openapi.yaml", "    MetricCode:\n", "\n    # ===")
    contract = re.findall(r"^\s+- ([a-z_]+)\s*$", enum, re.MULTILINE)
    src = read_text(SHIPPED)
    row = r'^\s*\("([a-z0-9_]+)", "[^"]*", "[^"]*", '  # name, title, unit — then the input field
    metric = re.findall(row + r'(?:_[A-Z]|"[a-z]+"), "[^"]*", \d+, ', src, re.MULTILINE)
    series = re.findall(row + r'"[^"]*", _(?:NO_)?TAPE, ', src, re.MULTILINE)
    shipped = set(metric) | set(series)
    return {
        "contract_members": len(contract),
        "shipped_metric_codes": len(metric),
        "shipped_indicator_series": len(series),
        "shared": sorted(shipped & set(contract)),
        "unmatched_contract_members": [c for c in contract if c not in shipped],
        "zone_codes_missing": [c for c in ZONE_CODES if c not in contract],
    }


def poisson_tail(n: float, k: int) -> float:
    """P(X >= k) for X ~ Poisson(n): the CDF summed in log space, so exp(-n) never underflows."""
    log_cdf = -math.inf
    for i in range(k):
        log_pmf = -n + i * math.log(n) - math.lgamma(i + 1)
        hi, lo = max(log_cdf, log_pmf), min(log_cdf, log_pmf)
        log_cdf = hi + math.log1p(math.exp(lo - hi)) if lo > -math.inf else hi
    return max(0.0, 1.0 - math.exp(log_cdf))


def z3_threshold(n: float) -> int:
    """The smallest count with z > Z strictly: floor(n + Z*sqrt(n)) + 1, so n = 25 gives 41.

    `ceil(n + Z*sqrt(n))` was wrong when n + Z*sqrt(n) is an integer: at n = 25 it gave 40, which
    is z = 3 exactly, not z > 3 (text lens round 1, item 6).
    """
    return math.floor(n + Z * math.sqrt(n)) + 1


def noise_floor() -> Noise:
    rows: dict[str, dict[str, float]] = {}
    for lam in RATES:
        for w in WINDOWS_S:
            n = lam * w
            thr = z3_threshold(n)
            p = poisson_tail(n, thr)
            indep = 3600 / w
            rows[f"{lam}/s x {w} s"] = {
                "expected_prints": n,
                "cv_pct": round(100 / math.sqrt(n), 1),
                "z3_threshold_prints": thr,
                "p_cross_pct": round(100 * p, 2),
                "independent_windows_per_h": int(indep),
                "false_crossings_per_h": round(p * indep, 1),
                "overlap_pct_at_push": round(100 * (1 - 1 / (PUSH_HZ * w)), 1),
            }
    return {
        "rows": rows,
        "cooldown_cap_per_h": 3600 // COOLDOWN_S,
        "digit_swaps_vs_scan": PUSH_HZ / SCAN_PER_S,
    }


def _z_sample_sd(f: float, n: float, k: float, into: bool) -> float:
    """z with the baseline window's sample sd when a fraction f of its buckets is burst (into=True:
    the burst rate against a baseline filling with burst; False: the usual rate against one emptying
    of it): Poisson within-bucket variance plus the between-bucket variance of the two-level mix."""
    burst = f if into else 1 - f
    mean = n * (1 + burst * (k - 1))
    var = mean + burst * (1 - burst) * ((k - 1) * n) ** 2
    return ((k * n if into else n) - mean) / math.sqrt(var)


def _root(fn: Callable[[float], float]) -> float:
    """Bisection on (0, 1) for the single sign change of a monotonic fn."""
    lo, hi, sign = 0.0, 1.0, fn(0.0) > 0
    for _ in range(60):
        mid = (lo + hi) / 2
        if (fn(mid) > 0) == sign:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def _uniform(seed: int, i: int) -> float:
    """Counter-based uniform in [0, 1): SHA-256 of (seed, draw index), so every platform and
    Python version draws the same sequence without a stateful generator."""
    digest = hashlib.sha256(f"{seed}:{i}".encode()).digest()
    return int.from_bytes(digest[:7], "big") / 2**56


def _poisson(u: float, mean: float) -> int:
    """One Poisson draw by inversion of the uniform u."""
    p, x = math.exp(-mean), 0
    cdf = p
    while u > cdf:
        x += 1
        p *= mean / x
        cdf += p
    return x


def _median_mad_hold(b: int, n: float, k: float, w: int) -> tuple[int, int, int]:
    """Seconds until a median/MAD baseline of B = b s (b // w buckets of n expected prints) stops
    reading a sustained k x burst as extreme (z <= Z) with Poisson draws per bucket: the median and
    the min / max over MEDIAN_SEEDS seeded runs. The numerator is the burst level k * n, as in the
    two mean models; the MAD is scaled by MAD_SCALE. As the burst fraction nears one half the median
    climbs through the usual distribution's upper tail and the MAD widens, so the hold ends before
    the deterministic flip at B / 2 (median_cliff_s)."""
    ends: list[int] = []
    for seed in range(MEDIAN_SEEDS):
        draws = iter(range(1 << 30))  # the draw index of this seed's sequence
        window = [_poisson(_uniform(seed, next(draws)), n) for _ in range(b // w)]
        for i in range(1, b // w + 1):
            window.pop(0)
            window.append(_poisson(_uniform(seed, next(draws)), k * n))
            med = median(window)
            mad = median(abs(v - med) for v in window) * MAD_SCALE
            if mad > 0 and (k * n - med) / mad <= Z:
                ends.append(i * w)
                break
        else:
            ends.append(b)  # the deterministic bound: at B every bucket is a burst bucket
    return median_low(ends), min(ends), max(ends)


def step_response() -> Step:
    """Deterministic-mean step response at RATES[0] prints/s to a BURST_K x burst (shape only).

    (a) Detection latency per fast window: after a step to BURST_K x the usual rate the window's
    mean count ramps linearly over the window length; the latency is when it first exceeds the
    z > 3 threshold of noise_floor(). (b) Per rolling-baseline length B, for the display window
    WINDOWS_S[1]: inside a sustained burst the baseline mean rises linearly to the burst rate over
    B, so the burst reads z <= 3 ("no longer extreme") at some t < B and z = 0 ("usual") at t = B;
    after a burst at least B long ends, the baseline decays over B and the usual rate reads z < -1
    ("below usual") for part of B. Two sd models side by side (delta lens round 2, item 1): `*_s`
    takes the baseline sd as the Poisson sqrt of its mean; `*_sample_sd_s` takes the sample sd of
    the baseline window's bucket counts — US-DET-002's "z-score against the configured baseline
    window" read conventionally — which the burst's own buckets inflate. Warm-up is B itself.
    (c) A median/MAD baseline (one of the burst-robust levers of F4c / Q13) keeps the usual level
    as its median while fewer than half of its buckets are burst buckets, then jumps to the burst
    level, so z falls to 0 at once at `median_cliff_s` = B / 2 — a cliff, not the mean's slope
    (deterministic mean; any burst multiple above 1; text lens round 3, item 2). With Poisson
    draws per bucket the hold ends earlier and the cliff has a short ramp: `median_hold_noisy_s`
    is the median over MEDIAN_SEEDS seeded runs of the first bucket at which z <= Z, with the min
    and max beside it (_median_mad_hold; text lens round 4, item 2). `extreme_fraction_of_b` is
    the fraction of B at which the burst stops reading extreme under each model, the same at every
    length: the sample-sd mean's is the smallest, the median/MAD's 0.5 sits between it and the
    Poisson-sd mean's (text lens round 4, item 3).
    """
    lam, k, w_disp = RATES[0], BURST_K, WINDOWS_S[1]
    detect: dict[str, float] = {}
    for w in WINDOWS_S:
        n = lam * w
        detect[f"{w} s"] = round(w * (z3_threshold(n) - n) / ((k - 1) * n), 1)
    n = lam * w_disp
    # Poisson sd: z(r) = sqrt(n) * (k - r) / sqrt(r), r = baseline mean / usual rate; z = Z, z = -1
    s_hi = (-Z / math.sqrt(n) + math.sqrt((Z / math.sqrt(n)) ** 2 + 4 * k)) / 2
    s_lo = (1 / math.sqrt(n) + math.sqrt(1 / n + 4)) / 2
    r_extreme, r_quiet = s_hi**2, s_lo**2
    # sample sd: the burst fraction of B at which z = Z, and the usual fraction at which z = -1
    f_extreme = _root(lambda f: _z_sample_sd(f, n, k, True) - Z)
    g_quiet = _root(lambda g: _z_sample_sd(g, n, k, False) + 1)
    baselines: dict[str, dict[str, str | int]] = {}
    for b, src in BASELINES_S.items():
        hold, hold_min, hold_max = _median_mad_hold(b, n, k, w_disp)
        baselines[f"{b} s"] = {
            "source": src,
            "warmup_s": b,
            "extreme_until_s": round(b * (r_extreme - 1) / (k - 1)),
            "extreme_until_sample_sd_s": round(b * f_extreme),
            "usual_at_s": b,
            "below_usual_for_s": round(b * (k - r_quiet) / (k - 1)),
            "below_usual_for_sample_sd_s": round(b * g_quiet),
            "median_cliff_s": b // 2,
            "median_hold_noisy_s": hold,
            "median_hold_noisy_min_s": hold_min,
            "median_hold_noisy_max_s": hold_max,
        }
    return {
        "rate_per_s": lam,
        "burst_multiple": k,
        "display_window_s": w_disp,
        "detect_latency_s": detect,
        "extreme_fraction_of_b": {
            "poisson_sd": round((r_extreme - 1) / (k - 1), 2),
            "sample_sd": round(f_extreme, 2),
            "median_mad": 0.5,
        },
        "baselines": baselines,
    }


def sprints() -> dict[str, str]:
    """The sprint dates from calendar_cv.py, loaded by path (sys.path is left alone)."""
    spec = importlib.util.spec_from_file_location(
        "calendar_cv", ROOT / "docs/plan/backlog/_tools/calendar_cv.py"
    )
    if spec is None or spec.loader is None:
        return {f"S{n:02d}": "NOT FOUND" for n in (10, 12, 13)}
    calendar_cv = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(calendar_cv)
    return {
        f"S{n:02d}": " -> ".join(str(d) for d in calendar_cv.sprint_range(n)) for n in (10, 12, 13)
    }


def main(argv: list[str]) -> int:
    # `python -I` ignores PYTHONIOENCODING / PYTHONUTF8, so a non-UTF-8 locale would otherwise
    # encode the section signs and multiplication signs below in locale bytes (text lens round 1,
    # item 7).
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")
    reg, tape, params, pl = regime_vocabularies(), tape_windows(), detector_params(), placement()
    events, noise, st = analytics(), noise_floor(), step_response()
    codes, spr = metric_codes(), sprints()
    data: dict[str, object] = {
        "regime": reg,
        "tape": tape,
        "params": params,
        "placement": pl,
        "analytics": events,
        "noise": noise,
        "step": st,
        "codes": codes,
        "sprints": spr,
    }
    if "--json" in argv:
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return 0
    print(f"## Regime vocabularies ({reg['sources']} sources, {reg['distinct']} distinct sets)\n")
    for src, toks in reg["sets"].items():
        print(f"- {src}: {', '.join(toks)}")
    print("\n## Speed-of-tape windows, baselines and cadences\n")
    for k, v in tape.items():
        print(f"- {k}: {v if v is not None else 'NOT FOUND'}")
    print("\n## Detector parameters per source\n")
    for det, d in params.items():
        if isinstance(d, str) or d is None:
            print(f"- {det}: {d}")
            continue
        print(f"- {det} ({d['distinct_name_sets']} distinct parameter-name sets):")
        for src, pairs in d["by_source"].items():
            print(f"  - {src}: {', '.join(pairs) if pairs else 'NOT FOUND'}")
    print("\n## Placement and analytics\n")
    print(
        f"- components saying client-side: {pl['components_saying_client_side']} "
        f"(hedged: {pl['hedged']})"
    )
    for cmp_id, phrase in pl["phrases"].items():
        print(f"  - {cmp_id}: {phrase}")
    print(f"- screens saying backend-side: {pl['screens_saying_backend_side']}")
    print(f"- events on the SCR-055..059 Analytics/audit lines: {events}")
    print("\n## Poisson noise floor of a prints/s window (lower bound; z > 3 at 4 Hz pushes)\n")
    print(
        "| Rate x window | E[prints] | CV % | z>3 at | P(cross) % | indep./h | false/h "
        "| overlap % |"
    )
    print("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    for k, r in noise["rows"].items():
        print(
            f"| {k} | {r['expected_prints']:g} | {r['cv_pct']} | {r['z3_threshold_prints']:g} | "
            f"{r['p_cross_pct']} | {r['independent_windows_per_h']:g} | "
            f"{r['false_crossings_per_h']} | "
            f"{r['overlap_pct_at_push']} |"
        )
    print(
        f"\ncooldown caps alerts at {noise['cooldown_cap_per_h']}/h; a 4 Hz digit swap is "
        f"{noise['digit_swaps_vs_scan']:g}x the one-token scan rate"
    )
    print(
        f"\n## Step response (deterministic mean, {st['rate_per_s']} prints/s, "
        f"a {st['burst_multiple']:g}x sustained burst; shape only; Poisson sd / sample sd)\n"
    )
    print(
        "- detection latency to z > 3 per fast window (the same under both sd models): "
        + ", ".join(f"{w}: {t} s" for w, t in st["detect_latency_s"].items())
    )
    frac = st["extreme_fraction_of_b"]
    print(
        "- the burst stops reading extreme at this fraction of B, the same at every length: "
        f"Poisson sd {frac['poisson_sd']}, sample sd {frac['sample_sd']}, median/MAD "
        f"{frac['median_mad']} (deterministic)"
    )
    print(
        f"- rolling baseline vs the {st['display_window_s']} s display window (warm-up | stops "
        "reading extreme, Poisson sd / sample sd | reads usual | reads below usual after it ends, "
        "Poisson sd / sample sd | a median/MAD baseline's cliff at B / 2, then where its hold ends "
        f"with Poisson draws per bucket — median and min-max over {MEDIAN_SEEDS} seeds):"
    )
    for b, row in st["baselines"].items():
        print(
            f"  - {b} ({row['source']}): {row['warmup_s']} s | {row['extreme_until_s']} / "
            f"{row['extreme_until_sample_sd_s']} s | {row['usual_at_s']} s | "
            f"{row['below_usual_for_s']} / {row['below_usual_for_sample_sd_s']} s | "
            f"{row['median_cliff_s']} s, noisy {row['median_hold_noisy_s']} s "
            f"({row['median_hold_noisy_min_s']}-{row['median_hold_noisy_max_s']})"
        )
    print("\n## 22 MetricCode vs the shipped vocabulary (G11)\n")
    print(
        f"- MetricCode members: {codes['contract_members']}; shipped metric descriptors: "
        f"{codes['shipped_metric_codes']}; shipped indicator series: "
        f"{codes['shipped_indicator_series']}"
    )
    print(f"- shared names: {', '.join(codes['shared']) or 'none'}")
    print(
        "- MetricCode members with no shipped code of that name: "
        + (", ".join(codes["unmatched_contract_members"]) or "none")
    )
    print(
        "- imbalance-zone codes F13 reads that MetricCode lacks: "
        + (", ".join(codes["zone_codes_missing"]) or "none")
    )
    print("\n## Sprints (calendar_cv.py)\n")
    for k, v in spr.items():
        print(f"- {k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
