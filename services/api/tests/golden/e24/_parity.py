"""E24-T06 parity core: the engine runners, the per-series tolerance table, `ParityDivergence`,
`compare`, and the canonical JSON dump.

Every series is read through `metric_value`, the same read path a pane, a query and a rule use.
Liquidation series (`liquidation_notional`) are the follow-up PR's (#5273 fixtures)."""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from functools import partial
from pathlib import Path

from candleviewer.orderflow.derivatives import (
    DESCRIPTORS,
    BarMetrics,
    DerivativesEngine,
    DerivBar,
    FundingRow,
    InstrumentMeta,
    OiSample,
    TickerSnapshot,
    Value,
    metric_value,
)
from tests.golden.e24._loader import Rows
from tests.golden.e24._reference import Ref

#: The series this PR compares: (label, descriptor, params, key in the reference rows).
SERIES: tuple[tuple[str, str, Mapping[str, str], str], ...] = (
    ("open_interest", "open_interest", {}, "open_interest"),
    ("open_interest_value", "open_interest_value", {}, "open_interest_value"),
    ("open_interest_delta", "open_interest_delta", {}, "open_interest_delta"),
    ("oi_price_quadrant", "oi_price_quadrant", {}, "oi_price_quadrant"),
    ("funding_rate", "funding_rate", {}, "funding_rate"),
    ("funding_annualized", "funding_annualized", {}, "funding_annualized"),
    ("time_to_funding_ms", "time_to_funding_ms", {}, "time_to_funding_ms"),
    ("basis[last]", "basis", {"source": "last"}, "basis:last"),
    ("basis[mark]", "basis", {"source": "mark"}, "basis:mark"),
    ("premium_pct[last]", "premium_pct", {"source": "last"}, "premium_pct:last"),
    ("premium_pct[mark]", "premium_pct", {"source": "mark"}, "premium_pct:mark"),
)
#: Descriptors the follow-up PR adds (they need the liquidation fixtures of #5273).
FOLLOW_UP_DESCRIPTORS = frozenset({"liquidation_notional"})
#: Exact equality everywhere except the two divisions: the reference rounds half away from zero
#: at 1e-18 (annualised, so 5e-19) / 1e-12 (premium); the engine divides at 28 digits, half-even.
TOLERANCE: Mapping[str, Decimal] = {
    "funding_annualized": Decimal("5e-19"),
    "premium_pct[last]": Decimal("1e-12"),
    "premium_pct[mark]": Decimal("1e-12"),
}


class ParityDivergence(AssertionError):
    """The engine and the reference disagree. The message names the metric, the first divergent
    bar, both values and every series' divergence count."""


@dataclass(frozen=True)
class Divergence:
    label: str
    start_ms: int
    engine: Value
    reference: object


@dataclass
class Report:
    bars: int
    counts: dict[str, int] = field(default_factory=dict)
    first: dict[str, Divergence] = field(default_factory=dict)
    non_none: dict[str, int] = field(default_factory=dict)

    @property
    def clean(self) -> bool:
        return not any(self.counts.values())

    def summary(self) -> dict[str, object]:
        return {"bars": self.bars, "divergent": self.counts, "non_none": self.non_none}


def iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _dec(s: str | None) -> Decimal | None:
    return None if s is None else Decimal(s)


def to_engine(
    rows: Rows,
) -> tuple[InstrumentMeta, list[DerivBar], list[OiSample], list[TickerSnapshot], list[FundingRow]]:
    bars = [DerivBar(s, e, Decimal(o), Decimal(c)) for s, e, o, c in rows.bars]
    oi = [OiSample(ts, Decimal(o), Decimal(v), "rest") for ts, o, v in rows.oi]
    tickers = [
        TickerSnapshot(ts, _dec(last), _dec(mark), _dec(idx), _dec(rate), nxt)
        for ts, last, mark, idx, rate, nxt in rows.tickers
    ]
    funding = [FundingRow(ts, Decimal(r)) for ts, r in rows.funding]
    return InstrumentMeta(rows.interval_min), bars, oi, tickers, funding


def run_full(rows: Rows, *, interval_min: int | None = None) -> tuple[BarMetrics, ...]:
    """One `load()`; `interval_min` overrides the instrument (the 8 h-assumption mutation)."""
    meta, bars, oi, tickers, funding = to_engine(rows)
    if interval_min is not None:
        meta = InstrumentMeta(interval_min)
    return DerivativesEngine(meta).load(bars, oi=oi, tickers=tickers, funding=funding)


def run_incremental(rows: Rows) -> tuple[BarMetrics, ...]:
    """Bars appended one by one with the rows fed by timestamp (a bar first on a tie)."""
    meta, bars, oi, tickers, funding = to_engine(rows)
    engine = DerivativesEngine(meta)
    events: list[tuple[int, int, Callable[[], object]]] = []
    events += [(b.start_ms, 0, partial(engine.upsert_bar, b)) for b in bars]
    events += [(r.ts_ms, 1, partial(engine.on_oi, r)) for r in oi]
    events += [(r.ts_ms, 2, partial(engine.on_ticker, r)) for r in tickers]
    events += [(r.ts_ms, 3, partial(engine.on_funding, r)) for r in funding]
    for _, _, apply in sorted(events, key=lambda e: e[:2]):
        apply()
    return engine.series


def shift_bars(rows: Rows, by_ms: int) -> Rows:
    """The same bars `by_ms` later (a bucketing off-by-one for the mutation tests)."""
    bars = [(s + by_ms, e + by_ms, o, c) for s, e, o, c in rows.bars]
    return Rows(rows.interval_min, bars, rows.oi, rows.tickers, rows.funding)


def _equal(label: str, a: object, b: object) -> bool:
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, Decimal) and isinstance(b, Decimal):
        return abs(a - b) <= TOLERANCE.get(label, Decimal(0))
    return a == b


def compare(series: Sequence[BarMetrics], ref: Ref) -> Report:
    """Diff every series over every bar. The grids must match first."""
    starts = [m.start_ms for m in series]
    if starts != sorted(ref):
        raise ParityDivergence(f"bar grids differ: engine {len(starts)} bars, reference {len(ref)}")
    report = Report(bars=len(series))
    for label, name, params, key in SERIES:
        report.counts[label] = report.non_none[label] = 0
        for m in series:
            ev, rv = metric_value(m, name, params), ref[m.start_ms][key]
            report.non_none[label] += ev is not None
            if not _equal(label, ev, rv):
                report.counts[label] += 1
                report.first.setdefault(label, Divergence(label, m.start_ms, ev, rv))
    return report


def assert_parity(report: Report) -> None:
    if report.clean:
        return
    worst = min(report.first.values(), key=lambda d: d.start_ms)
    counts = ", ".join(f"{k}={v}" for k, v in report.counts.items() if v)
    raise ParityDivergence(
        f"{worst.label} diverges first at bar {worst.start_ms} ({iso(worst.start_ms)}): "
        f"engine={worst.engine!r} reference={worst.reference!r}; divergent bars: {counts}"
    )


def canonical_json(series: Sequence[BarMetrics]) -> str:
    """Sorted keys, Decimal as str, no wall-clock: byte-identical across runs."""
    out = []
    for m in series:
        row: dict[str, object] = {"start_ms": m.start_ms}
        for label, name, params, _ in SERIES:
            v = metric_value(m, name, params)
            row[label] = str(v) if isinstance(v, Decimal) else v
        out.append(row)
    return json.dumps(out, sort_keys=True, separators=(",", ":"))


def write_summary(reports: Mapping[str, Report]) -> None:
    """`CV_PARITY_SUMMARY=<path>` writes the per-case divergence counts (the artifact)."""
    dest = os.environ.get("CV_PARITY_SUMMARY")
    if dest:
        body = {k: r.summary() for k, r in sorted(reports.items())}
        Path(dest).write_text(json.dumps(body, indent=2, sort_keys=True), encoding="utf-8")


def regen_requested() -> bool:
    """`CV_REGEN_GOLDEN=1` asks to rewrite the goldens; refused if `CI`/`GITHUB_ACTIONS` is set."""
    if os.environ.get("CV_REGEN_GOLDEN") != "1":
        return False
    if os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS"):
        raise RuntimeError("CV_REGEN_GOLDEN=1 is refused in CI: goldens are regenerated locally")
    return True


def descriptor_names() -> set[str]:
    return set(DESCRIPTORS)
