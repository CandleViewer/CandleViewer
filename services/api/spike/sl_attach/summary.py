"""The per-arm tables (#856 acceptance "Both arms are measured"; the scout's §5): kept and
discarded counts by reason, p50/p95/p99 and max of the arm's metric (arm (a) `ack_ms`, arm (b)
`exposure_ms`), the success rate, the full `retCode` histogram with both taxonomy columns, the
requests per protected position (reads apart: they feed 24 §8.7's `reserved_for_protective`)
and the headroom of arm (b)'s p99 under §8.8 rule 2's 2 s. Each arm is also split by symbol.

A discarded sample is outside every statistic but its count; the success rate is `ok` over the
kept samples; the cost counts only samples that protected a position (`ok`). The percentiles
read the `ok` samples only, so `measured` (their count) and `measured_symbols` are what the
decision's floors read: a rejected or ambiguous sample never counts towards a percentile's `n`.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from typing import Final

from spike.oms_demo_path.measure import stats
from spike.sl_attach.config import DEADLINE_MS, Arm
from spike.sl_attach.results import Sample

METRIC: Final[dict[Arm, str]] = {"a": "ack_ms", "b": "exposure_ms"}


def _histogram(kept: Sequence[Sample]) -> list[dict[str, object]]:
    rows = Counter(
        (s.stage, s.ret_code, s.adapter_error_code, s.s86_code, s.taxonomy_divergent)
        for s in kept
        if s.ret_code is not None or s.adapter_error_code is not None
    )
    keys = ("stage", "ret_code", "adapter_error_code", "s86_code", "divergent")
    ordered = sorted(rows.items(), key=lambda kv: (str(kv[0][0]), kv[0][1] or -1))
    out: list[dict[str, object]] = []
    for key, n in ordered:
        out.append({**dict(zip(keys, key, strict=True)), "n": n})
    return out


def _mean(values: Sequence[int]) -> float | None:
    return None if not values else round(sum(values) / len(values), 3)


def arm_table(samples: Sequence[Sample], arm: Arm) -> dict[str, object]:
    mine = [s for s in samples if s.arm == arm]
    kept = [s for s in mine if s.outcome != "discarded"]
    dropped = [s for s in mine if s.outcome == "discarded"]
    ok = [s for s in kept if s.outcome == "ok"]
    measured = [s for s in ok if getattr(s, METRIC[arm]) is not None]
    values: list[float] = [getattr(s, METRIC[arm]) for s in measured]
    latency = stats(values, digits=3)
    table: dict[str, object] = {
        "metric": METRIC[arm],
        "n": len(mine),
        "kept": len(kept),
        "discarded": dict(sorted(Counter(str(s.discard_reason) for s in dropped).items())),
        "outcomes": dict(sorted(Counter(s.outcome for s in kept).items())),
        "success_rate": None if not kept else round(len(ok) / len(kept), 4),
        "measured": len(values),
        "measured_symbols": sorted({s.symbol for s in measured}),
        "latency_ms": latency,
        "ret_codes": _histogram(kept),
        "requests_per_protected_position": {
            "order_class": _mean([s.requests_order_class for s in ok]),
            "position_class": _mean([s.requests_position_class for s in ok]),
            "reads": _mean([s.requests_reads for s in ok]),
        },
        "symbols": sorted({s.symbol for s in kept}),
    }
    if arm == "b" and "p99" in latency:
        table["deadline_headroom_ms"] = round(DEADLINE_MS - latency["p99"], 3)
    return table


def summarise(samples: Sequence[Sample]) -> dict[str, object]:
    arms: dict[str, object] = {}
    for arm in ("a", "b"):
        symbols = sorted({s.symbol for s in samples if s.arm == arm})
        by_symbol = {
            sym: arm_table([s for s in samples if s.symbol == sym], arm) for sym in symbols
        }
        arms[arm] = arm_table(samples, arm) | {"by_symbol": by_symbol}
    return {"arms": arms}
