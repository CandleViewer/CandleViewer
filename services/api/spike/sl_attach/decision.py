"""The decision rule agreed up front in #856 (Technical notes; acceptance "The spike ends in a
decision"): arm (b)'s p99 `exposure_ms` above 1.5 s means the OMS defaults to attach-only;
otherwise the `trading-stop` window is accepted at the measured p99.

A run below the ticket's floors answers `insufficient`, never a verdict. The floors count the
samples each arm's percentile is read from (`measured`: the `ok` ones, 200 per arm, spanning
three symbols), never the kept total: a run of 190 refused stop writes and 10 successes has no
p99 worth a verdict. An offline run's answer carries `evidence: false`: the corpus is
docs-transcribed, so it proves the wiring, never the venue. Arm (b) is measured as a
backstop-then-tighten modify (Q5), which the answer says.

A failed stop write is unbounded exposure, never a sample left out: each arm (b) sample whose
`trading-stop` failed or never landed is +inf in the p99 (`summary`), and the verdict is
attach-only when arm (b)'s `stop_success_rate` is under `MIN_STOP_SUCCESS_RATE` (0.995) or
unknown. Both apply above the floors: 200 successes and 1,800 refused writes answer attach-only.
An arm (b) opener that filled but whose stop write was never sent (a lost or late execution
push, an ambiguous create that filled) is such a failure too (`stop_landed` false).

What the bar resolves at the n = 200 floor: it is a run gate, not a measured 0.5 % failure
rate. 200 landed and one failed (0.99502) passes it, two (0.990099) fail it. The 95 %
Clopper-Pearson upper bound on the true failure rate is 1.83 % with no failure in 200 and
2.74 % with one in 201; the ADR quotes that bound beside the rate. Only a larger run narrows it.

Skew discards leave every statistic, so a run that discarded more than
`MAX_SKEW_DISCARD_SHARE` (5 %) of either arm's samples for skew answers `insufficient`: the
discards could be its slow samples. Each arm's share is in the answer.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final, Literal

from spike.sl_attach.config import (
    DEADLINE_MS,
    DECISION_P99_MS,
    MAX_SKEW_DISCARD_SHARE,
    MIN_SAMPLES_PER_ARM,
    MIN_STOP_SUCCESS_RATE,
    MIN_SYMBOLS,
)

type Verdict = Literal["insufficient", "attach-only", "trading-stop-window-accepted"]
MEASURED: Final = "arm (b) times a trading-stop modify after an attached-backstop open (Q5)"


def _arm(summary: Mapping[str, object], arm: str) -> Mapping[str, object]:
    arms = summary["arms"]
    assert isinstance(arms, Mapping)  # noqa: S101 - `summarise` builds it
    table = arms[arm]
    assert isinstance(table, Mapping)  # noqa: S101 - `summarise` builds it
    return table


def _p99(table: Mapping[str, object]) -> float | None:
    latency = table["latency_ms"]
    return latency.get("p99") if isinstance(latency, Mapping) else None


def _measured(table: Mapping[str, object]) -> int:
    measured = table["measured"]
    return measured if isinstance(measured, int) else 0


def _symbols(table: Mapping[str, object]) -> int:
    symbols = table["measured_symbols"]
    return len(symbols) if isinstance(symbols, list) else 0


def _rate(table: Mapping[str, object]) -> float | None:
    rate = table["stop_success_rate"]
    return rate if isinstance(rate, float) else None


def _skew(table: Mapping[str, object]) -> float:
    share = table.get("skew_discard_share")
    return share if isinstance(share, float) else 0.0


def decide(summary: Mapping[str, object], *, offline: bool) -> dict[str, object]:
    a, b = _arm(summary, "a"), _arm(summary, "b")
    p99, rate = _p99(b), _rate(b)
    floors = all(_measured(t) >= MIN_SAMPLES_PER_ARM and _symbols(t) >= MIN_SYMBOLS for t in (a, b))
    skew_ok = all(_skew(t) <= MAX_SKEW_DISCARD_SHARE for t in (a, b))
    verdict: Verdict
    if not floors or not skew_ok or p99 is None:
        verdict = "insufficient"
    elif p99 > DECISION_P99_MS or rate is None or rate < MIN_STOP_SUCCESS_RATE:
        verdict = "attach-only"
    else:
        verdict = "trading-stop-window-accepted"
    return {
        "verdict": verdict,
        "arm_b_p99_ms": p99,
        "arm_b_measured": _measured(b),
        "arm_b_success_rate": b.get("success_rate"),
        "arm_b_stop_success_rate": rate,
        "arm_b_unbounded": b.get("unbounded"),
        "min_stop_success_rate": MIN_STOP_SUCCESS_RATE,
        "skew_discard_share": {"a": _skew(a), "b": _skew(b)},
        "max_skew_discard_share": MAX_SKEW_DISCARD_SHARE,
        "threshold_ms": DECISION_P99_MS,
        "deadline_ms": DEADLINE_MS,
        "deadline_met": None if p99 is None else p99 <= DEADLINE_MS,
        "evidence": not offline,
        "measured": MEASURED,
    }
