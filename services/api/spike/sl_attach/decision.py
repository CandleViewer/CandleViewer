"""The decision rule agreed up front in #856 (Technical notes; acceptance "The spike ends in a
decision"): arm (b)'s p99 `exposure_ms` above 1.5 s means the OMS defaults to attach-only;
otherwise the `trading-stop` window is accepted at the measured p99.

A run below the ticket's floors (200 kept samples per arm, three symbols) answers
`insufficient`, never a verdict. An offline run's answer carries `evidence: false`: the corpus is
docs-transcribed, so it proves the wiring, never the venue. Arm (b) is measured as a
backstop-then-tighten modify (Q5), which the answer says.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final, Literal

from spike.sl_attach.config import DEADLINE_MS, DECISION_P99_MS, MIN_SAMPLES_PER_ARM, MIN_SYMBOLS

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


def _kept(table: Mapping[str, object]) -> int:
    kept = table["kept"]
    return kept if isinstance(kept, int) else 0


def _symbols(table: Mapping[str, object]) -> int:
    symbols = table["symbols"]
    return len(symbols) if isinstance(symbols, list) else 0


def decide(summary: Mapping[str, object], *, offline: bool) -> dict[str, object]:
    a, b = _arm(summary, "a"), _arm(summary, "b")
    p99 = _p99(b)
    floors = all(_kept(t) >= MIN_SAMPLES_PER_ARM and _symbols(t) >= MIN_SYMBOLS for t in (a, b))
    verdict: Verdict
    if not floors or p99 is None:
        verdict = "insufficient"
    elif p99 > DECISION_P99_MS:
        verdict = "attach-only"
    else:
        verdict = "trading-stop-window-accepted"
    return {
        "verdict": verdict,
        "arm_b_p99_ms": p99,
        "threshold_ms": DECISION_P99_MS,
        "deadline_ms": DEADLINE_MS,
        "deadline_met": None if p99 is None else p99 <= DEADLINE_MS,
        "evidence": not offline,
        "measured": MEASURED,
    }
