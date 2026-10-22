"""W5 (23 16.6): the cost of per-topic coalescing under the `saturated` class, and its answer.

The question is whether the fixed class multipliers (x2 `lagging`, x4 `saturated`, `WS/pacing.py`)
should stay or become per family. No product code measures it: the client reads, off the wire, each
family's bytes, frames, `coalesced_count` and staleness in each class, and process CPU per phase,
fed-but-unsubscribed baseline taken off, gives the CPU a family costs. A cohort is put into a class
by delaying `pong` to the server's `s-rtt-*` probes (`pacing.classify` reads the RTT), so the class
is deterministic, and `system` `connection_quality.applied` says which class a phase really ran in.

The rule is pre-registered here, before any run, so the data gives the answer:

- relief(f, c) = 1 - bytes(f, c) / bytes(f, healthy); cost(f, c) = p95(f, c) - p95(f, healthy)
  (floored at 1 ms, the k6 clock's resolution); efficiency = relief / cost.
- p95(f, c) is how long an update waits in the window the multiplier widens, never
  release-to-decode: the envelope `ts` is stamped when a window is RELEASED (`sequencing.py`,
  `pacing._flush`), so a decode minus it excludes the wait the multiplier adds and the cost would
  read 1 ms for every family. Trades: the feeder-stamped time of the oldest print a frame carries,
  to decode-complete (the stamp budget #3 uses; the merge keeps the oldest). Book and bars: a
  merged frame carries no oldest-update stamp (the book merge keeps its newest update's header, a
  bars frame has none), so it is the interval between two releases on the reference symbol's
  stream, the longest an update waits there (`cv_hold_ms_<family>`).
- **Keep the fixed multipliers** when every family carrying at least 10 % of the healthy bytes shows
  at least 50 % relief at x4 and their efficiencies are within 2x of each other.
- **Per-family multipliers** otherwise, in particular when an append family (trades: windows batch,
  never merge, 8.2) gets under 20 % relief and pays 3x or more latency, which is the expected case.
  Each family keeps (x2, x4) when its relief at x4 is at least 30 %, else (x1, x1).
- Multipliers that adapt at run time, per topic, need a signal from the product (the queue keeps
  per-subscription bytes for `bye.hint`); that is a separate design for #572, not here.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final

from bench.ws.budgets import Scrape, total

CLASSES: Final = ("healthy", "lagging", "saturated")
FAMILIES: Final = ("book", "trades", "bars", "footprint", "heatmap")
APPEND_FAMILIES: Final = frozenset({"trades"})
MIN_SHARE: Final = 0.10
MIN_RELIEF: Final = 0.50
APPEND_RELIEF: Final = 0.20
APPEND_LATENCY_X: Final = 3.0
EFFICIENCY_SPREAD: Final = 2.0
WORTHY_RELIEF: Final = 0.30
LATENCY_FLOOR_MS: Final = 1.0
ADAPTIVE_NOTE: Final = (
    "Multipliers that adapt at run time, per topic, need a signal from the product: a separate "
    "design (#572)."
)
#: The k6 trend each family's staleness is read from (see the rule above).
STALENESS_TREND: Final = {
    "trades": "cv_tick_decode_ms_trades",
    "book": "cv_hold_ms_book",
    "bars": "cv_hold_ms_bars",
}
MIXED: Final = ("mixed-healthy", "mixed-lagging", "mixed-saturated")


@dataclass(frozen=True, slots=True)
class Obs:
    """One family in one class, over a phase: payload bytes and frames per second (all
    connections), the p95 staleness of `STALENESS_TREND`, and the updates a frame carried on
    average (`coalesced_count`: the frames plus what the server merged away, per frame)."""

    bytes_s: float
    frames_s: float
    p95_ms: float
    coalesced: float = 1.0


@dataclass(slots=True)
class Answer:
    recommendation: str  # "keep_fixed" | "per_family"
    reasons: list[str] = field(default_factory=list)
    rows: list[dict[str, Any]] = field(default_factory=list)
    proposed: dict[str, tuple[int, int]] = field(
        default_factory=dict
    )  # family -> (lagging, saturated)
    note: str = ADAPTIVE_NOTE


def decide(obs: Mapping[str, Mapping[str, Obs]]) -> Answer:
    """The pre-registered rule over `obs[family][class]`; a family without data in `healthy` or
    `saturated` is left out."""
    fams = {f: c for f, c in obs.items() if c.get("healthy") and c.get("saturated")}
    fams = {f: c for f, c in fams.items() if c["healthy"].bytes_s > 0}
    base = sum(c["healthy"].bytes_s for c in fams.values()) or 1.0
    answer, effs = Answer("keep_fixed"), []
    for fam, by in sorted(fams.items()):
        h, s = by["healthy"], by["saturated"]
        relief = 1.0 - s.bytes_s / h.bytes_s
        cost = max(s.p95_ms - h.p95_ms, LATENCY_FLOOR_MS)
        slow = s.p95_ms / h.p95_ms if h.p95_ms > 0 else math.inf
        share = h.bytes_s / base
        row = {"family": fam, "share": share, "relief": relief, "cost_ms": cost, "slowdown": slow,
               "efficiency": relief / cost, "coalesced": s.coalesced}  # fmt: skip
        answer.rows.append(row)
        answer.proposed[fam] = (2, 4) if relief >= WORTHY_RELIEF else (1, 1)
        if share >= MIN_SHARE:
            effs.append(relief / cost)
            if relief < MIN_RELIEF:
                answer.reasons.append(
                    f"{fam} carries {share:.0%} of the bytes but only {relief:.0%} relief at x4"
                )
        if fam in APPEND_FAMILIES and relief < APPEND_RELIEF and slow >= APPEND_LATENCY_X:
            answer.reasons.append(f"{fam} (append): {relief:.0%} relief at {slow:.1f}x the latency")
    positive = [e for e in effs if e > 0]
    if len(positive) > 1 and max(positive) / min(positive) > EFFICIENCY_SPREAD:
        answer.reasons.append(
            f"efficiency spread {max(positive) / min(positive):.1f}x across the families"
        )
    if answer.reasons:
        answer.recommendation = "per_family"
    else:
        answer.proposed = {f: (2, 4) for f in answer.proposed}
    return answer


def cpu_by_family(
    idle_cpu_s_per_s: float, phases: Mapping[tuple[str, str], float]
) -> dict[tuple[str, str], float]:
    """Process CPU seconds per second a family costs in a class: its single-family phase minus the
    fed-but-unsubscribed baseline, never below zero."""
    return {key: max(0.0, cpu - idle_cpu_s_per_s) for key, cpu in phases.items()}


def applied_class(counters: Mapping[str, float]) -> str:
    """The worst class the server announced to the cohort (`cv_class_<name>` counts the
    `connection_quality` frames by class); none announced means `healthy` (the start class)."""
    for name in reversed((*CLASSES, "overflowing")):
        if counters.get(f"cv_class_{name}", 0) > 0:
            return name
    return "healthy"


def obs_from_summary(
    summ: Mapping[str, Any], family: str, steady_s: float, conflated: float = 0.0
) -> Obs | None:
    """One family's `Obs` in the phase a k6 summary describes, `None` when it saw no frame or no
    staleness sample (a family outside `STALENESS_TREND` has neither).
    `conflated` is the phase's delta of `cv_ws_conflated_total{topic=family}`, which is where the
    merge count lives: a binary frame carries only a `coalesced` flag, not the count."""
    counters, trends = summ.get("counters", {}), summ.get("trends", {})
    frames = float(counters.get(f"cv_frames_{family}", 0.0))
    if frames <= 0 or steady_s <= 0:
        return None
    lat = trends.get(STALENESS_TREND.get(family, ""), {})
    if not lat.get("count"):  # no staleness sample: never read as 0 ms
        return None
    return Obs(
        float(counters.get(f"cv_bytes_{family}", 0.0)) / steady_s,
        frames / steady_s,
        float(lat["p95"]),
        (frames + conflated) / frames,
    )


@dataclass(frozen=True, slots=True)
class Phase:
    """One run of the W5 plan: what it subscribed, how the cohort's `pong` was delayed, what k6
    and the scrapes measured over its steady window, and its run's status: `INVALID` when it
    tripped any validity guard, else its verdict."""

    name: str
    families: tuple[str, ...]
    rtt_delay_ms: int
    summary: Mapping[str, Any]
    delta: Scrape
    steady_s: float
    status: str
    delta_s: float | None = None  # the real seconds `delta` spans (t0 to t1); None: `steady_s`


def intended_class(rtt_delay_ms: int) -> str:
    """The class a `pong` delay puts a cohort in (`pacing.classify`: lagging from 150 ms of RTT,
    saturated above 500 ms)."""
    return "healthy" if rtt_delay_ms < 150 else "lagging" if rtt_delay_ms <= 500 else "saturated"


def analyze(phases: Sequence[Phase], left_out: Sequence[str] = ()) -> dict[str, Any]:
    """The answer from the whole plan: `decide` over the mixed phases, the CPU a family costs from
    the single-family phases, and a note for every phase that did not run as intended. `left_out`
    names the phases the caller did not read (a lost scrape) and noted itself: skipped, no more."""
    notes: list[str] = []
    skipped: list[str] = []
    obs: dict[str, dict[str, Obs]] = {}
    applied: dict[str, str] = {}
    for ph in phases:  # the single-family and idle phases are read for CPU alone: INVALID is normal
        if ph.status == "INVALID" and ph.name.startswith("mixed-"):
            notes.append(f"phase {ph.name} is INVALID and is left out")
            skipped.append(ph.name)
    for ph in (p for p in phases if p.name.startswith("mixed-") and p.status != "INVALID"):
        want, got = intended_class(ph.rtt_delay_ms), applied_class(ph.summary.get("counters", {}))
        applied[ph.name] = got
        if got != want:
            notes.append(
                f"phase {ph.name}: the server applied {got}, the cohort was set up for {want}"
            )
            skipped.append(ph.name)
            continue
        for fam in FAMILIES:
            merged = total(ph.delta, "cv_ws_conflated_total", topic=fam)
            if o := obs_from_summary(ph.summary, fam, ph.steady_s, merged):
                obs.setdefault(fam, {})[want] = o
            elif fam in STALENESS_TREND and ph.summary.get("counters", {}).get(f"cv_frames_{fam}"):
                notes.append(f"phase {ph.name}: {fam} frames arrived but no staleness sample")
    for name in MIXED:  # a plan without one of the three classes is not a whole answer
        if name not in {ph.name for ph in phases}:
            if name not in left_out:
                notes.append(f"phase {name} is not in the plan")
            skipped.append(name)
    answer = decide(obs)
    for fam in sorted(set(obs) - {r["family"] for r in answer.rows}):
        notes.append(f"{fam}: no observation in both the healthy and the saturated phase, left out")
    cpu = {
        p.name: total(p.delta, "process_cpu_seconds_total") / (p.delta_s or p.steady_s)
        for p in phases
        if p.steady_s > 0
    }
    idle = cpu.get("idle")
    single = {(f, c): v for n, v in cpu.items() for f, _, c in [n.partition("-")] if f in FAMILIES}
    per_family = {} if idle is None else cpu_by_family(idle, single)
    return {
        "recommendation": answer.recommendation if answer.rows else "no_data",
        "reasons": answer.reasons,
        "rows": answer.rows,
        "proposed_multipliers": answer.proposed,
        "cpu_s_per_s": {"idle": idle, **{f"{f}/{c}": v for (f, c), v in per_family.items()}},
        "applied_class": applied,
        "skipped": skipped,
        "notes": notes,
        "adaptive": answer.note,
    }


def exit_code(answer: Mapping[str, Any]) -> int:
    """0 only for an answer with a table from every mixed phase; 1 for no data, an empty table or a
    mixed phase left out, so a dispatch with no usable W5 answer is red, never an empty `w5.json`
    under a green run."""
    empty = answer["recommendation"] == "no_data" or not answer["rows"]
    return 1 if empty or answer["skipped"] else 0


def headline(answer: Mapping[str, Any]) -> str:
    """The line `runner w5` prints first: the recommendation and why, or, for every answer
    `exit_code` holds red (no data, no table, a mixed phase left out), that there is no usable
    answer, so a red log never opens with a recommendation. It counts the phases left out; the
    note under it names each one, once."""
    if exit_code(answer):
        n = len(answer["skipped"])
        left = f" ({n} mixed phase{'' if n == 1 else 's'} left out)" if n else ""
        return f"W5: no usable answer{left}"
    return f"W5: {answer['recommendation']}: {'; '.join(answer['reasons']) or 'every rule met'}"
