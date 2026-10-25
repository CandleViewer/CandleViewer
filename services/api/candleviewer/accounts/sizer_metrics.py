"""The leg sizer's metrics (E28-T03 #907, BQ-20): recorded from a `LegSizing`, beside `size_leg`.

`size_leg` stays pure (no clock, no metrics), so the caller that sizes a leg (E28-T05 #909, E34)
either calls `size_leg_observed`, which times the call and records it, or times it itself and
calls `SizerMetrics.record`. Every label value comes from a closed set of `accounts.sizer`:
`outcome` and `reason` from `LegSizing`'s outcome and its `SkipReason` / `FailReason` (`none` for
`ok`), `cap` from `CapName`; none names an account, a symbol or a value. The four series are
catalogued `planned` (`observability.metrics_catalogue`) until a caller wires them.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Final, get_args

from candleviewer.accounts.override_comparator import AccountFigures
from candleviewer.accounts.profiles import AccountProfile
from candleviewer.accounts.sizer import (
    CapName,
    FailReason,
    LegSizing,
    SizingIntent,
    SizingMarket,
    SkipReason,
    size_leg,
)
from candleviewer.domain.events import Instrument
from candleviewer.observability.metrics import BoundedMetric, MetricChild, Metrics
from candleviewer.observability.metrics_catalogue import CATALOGUE

DURATION: Final = "cv_sizer_duration_seconds"
OUTCOMES: Final = "cv_sizer_outcomes_total"
CLAMPED: Final = "cv_sizer_clamped_total"
FALLBACK: Final = "cv_sizer_stop_fallback_total"
#: Every `(outcome, reason)` pair a leg can carry, in the catalogue's `max_series` (11).
OUTCOME_REASONS: Final[tuple[tuple[str, str], ...]] = (
    ("ok", "none"),
    *(("skip", reason.value) for reason in SkipReason),
    *(("fail", reason.value) for reason in FailReason),
)
#: The caps of 24 Sec.9.3.2, the `cap` label's values (7).
CAPS: Final[tuple[str, ...]] = get_args(CapName)


class SizerMetrics:
    """The four series, every child bound once at construction (each label set is closed)."""

    __slots__ = ("_clamped", "_duration", "_fallback", "_outcomes")

    def __init__(
        self,
        *,
        duration: BoundedMetric,
        outcomes: BoundedMetric,
        clamped: BoundedMetric,
        fallback: BoundedMetric,
    ) -> None:
        self._duration = duration.child()
        self._outcomes = {pair: outcomes.labels(*pair) for pair in OUTCOME_REASONS}
        self._clamped: dict[str, MetricChild] = {cap: clamped.labels(cap) for cap in CAPS}
        self._fallback = fallback.child()

    @classmethod
    def register(cls, metrics: Metrics) -> SizerMetrics:
        """Register the four through the facade, as catalogued (idempotent)."""
        spec = {s.name: s for s in CATALOGUE}
        d, o, c, f = spec[DURATION], spec[OUTCOMES], spec[CLAMPED], spec[FALLBACK]
        return cls(
            duration=metrics.histogram(
                d.name, d.help, d.labels, buckets=d.buckets or (), max_series=d.max_series
            ),
            outcomes=metrics.counter(o.name, o.help, o.labels, max_series=o.max_series),
            clamped=metrics.counter(c.name, c.help, c.labels, max_series=c.max_series),
            fallback=metrics.counter(f.name, f.help, f.labels, max_series=f.max_series),
        )

    def record(self, leg: LegSizing, elapsed_s: float) -> None:
        """One sized leg: its time, its outcome, each cap that lowered it, its ATR fallback."""
        self._duration.observe(elapsed_s)
        reason = "none" if leg.reason is None else leg.reason.value
        self._outcomes[(leg.outcome, reason)].inc()
        for rule in leg.rules:  # a cap is in `rules` only when it lowered the quantity
            child = self._clamped.get(rule)
            if child is not None:
                child.inc()
        if leg.stop_fallback:
            self._fallback.inc()


def size_leg_observed(
    intent: SizingIntent,
    profile: AccountProfile,
    wallet: AccountFigures,
    inst: Instrument,
    market: SizingMarket,
    *,
    observer: SizerMetrics,
    clock: Callable[[], float] = time.perf_counter,
) -> LegSizing:
    """`size_leg`, timed by `clock` and recorded; a programming error raises unrecorded."""
    start = clock()
    leg = size_leg(intent, profile, wallet, inst, market)
    observer.record(leg, clock() - start)
    return leg
