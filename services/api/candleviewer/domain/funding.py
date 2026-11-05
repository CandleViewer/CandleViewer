"""Funding-rate domain primitives (E24-T02): the ONE interval accessor and the
ONE annualisation formula.

`docs/plan/22-api-openapi.yaml` `/market/funding`: the funding interval is
instrument-specific (8 h common, some 1/2/4 h) - never assume 8 h. Every
consumer (backfill writer, API, countdown) resolves the interval through
`resolve_funding_interval_minutes` and annualises through `annualised_pct`;
no derivatives module may carry its own interval literal (CI guard:
`tests/unit/orderflow/test_funding_interval_guard.py`).

Exchange-neutral (C-2.2): no exchange field names here.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Final, Literal, Protocol

from pydantic import BaseModel, ConfigDict

#: Minutes in a 365-day year. The annualisation numerator (not an interval).
MINUTES_PER_YEAR: Final[int] = 525_600
#: 22 `getFundingHistory`: `annualised_pct` is served at 6 fractional digits, `ROUND_HALF_UP`.
ANNUALISED_PCT_QUANTUM: Final = Decimal("0.000001")
#: 22 `FundingEstimate.amount` / 24 §1.5 funding payments: 8 dp, `ROUND_HALF_UP`.
ESTIMATE_QUANTUM: Final = Decimal("0.00000001")
#: 22 `FundingPageMeta.coverage.gaps`: `maxItems`.
GAP_CAP: Final[int] = 64
_US_PER_MIN: Final[int] = 60_000_000


class FundingRowRejected(ValueError):
    """A funding-history row (or its envelope) failed strict validation.
    `reason` is a bounded enum value safe to use as a metric label."""

    def __init__(self, message: str, reason: str = "envelope") -> None:
        super().__init__(message)
        self.reason = reason


class FundingPage(list["FundingSettlement"]):
    """Accepted rows of one upstream page plus the bounded reasons of rows the
    adapter rejected (fail-closed per row, STRIDE D1)."""

    def __init__(
        self, rows: Iterable[FundingSettlement] = (), rejected_reasons: list[str] | None = None
    ) -> None:
        super().__init__(rows)
        self.rejected_reasons: list[str] = rejected_reasons or []


#: `funding_rates.source` for rows backfilled from the settled-history endpoint.
SOURCE_HISTORY: Final[str] = "history"

#: Intervals the exchange is known to publish are not enforced here (a new
#: interval must not need a code change); only sanity bounds are.
MIN_INTERVAL_MIN: Final[int] = 1
MAX_INTERVAL_MIN: Final[int] = 24 * 60


class FundingIntervalUnknown(LookupError):
    """The instrument (or its interval) is unknown. Never defaulted at
    runtime: a wrong interval corrupts the countdown and the annualisation
    together (ticket technical notes)."""


class PredictedFundingRefused(ValueError):
    """A predicted/estimated funding value reached a settled-row writer."""


class HasFundingInterval(Protocol):
    @property
    def funding_interval_min(self) -> int: ...


def resolve_funding_interval_minutes(instrument: HasFundingInterval | None) -> int:
    """The single accessor: the instrument's `funding_interval_min`, or raise."""
    if instrument is None:
        raise FundingIntervalUnknown("instrument is not in the instruments cache")
    value = instrument.funding_interval_min
    if isinstance(value, bool) or not isinstance(value, int):
        raise FundingIntervalUnknown("instrument funding interval is not an integer")
    if not MIN_INTERVAL_MIN <= value <= MAX_INTERVAL_MIN:
        raise FundingIntervalUnknown(f"instrument funding interval {value} min is out of range")
    return value


def annualised_pct(funding_rate: Decimal, interval_min: int) -> Decimal:
    """`funding_rate * (525600 / interval_min) * 100`, in `Decimal`."""
    if not MIN_INTERVAL_MIN <= interval_min <= MAX_INTERVAL_MIN:
        raise FundingIntervalUnknown(f"funding interval {interval_min} min is out of range")
    return funding_rate * (Decimal(MINUTES_PER_YEAR) / Decimal(interval_min)) * Decimal(100)


def served_annualised_pct(funding_rate: Decimal, interval_min: int) -> Decimal:
    """22 `annualised_pct` as served: `annualised_pct` quantised to 6 dp `ROUND_HALF_UP`."""
    exact = annualised_pct(funding_rate, interval_min)
    return exact.quantize(ANNUALISED_PCT_QUANTUM, rounding=ROUND_HALF_UP)


def fixed_point(value: Decimal) -> str:
    """Fixed point with trailing fractional zeros dropped (`8.760000` -> `8.76`), never `-0`."""
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


def _missing_between(
    a: int, a_stored: bool, b: int, b_stored: bool, step: int, grid: int | None
) -> bool:
    """Whether a settlement was due in the span `a`..`b`: a stored edge is exclusive (it is the
    settlement), a covered edge inclusive. With a grid (a known settlement time), the first grid
    time at or past `a`; without one, only a span of at least one interval surely holds one."""
    if grid is None:
        return b - a > step or (b - a >= step and not (a_stored and b_stored))
    due = grid + -((grid - a) // step) * step  # the first grid time at or after `a`
    if a_stored and due == a:
        due += step
    return due < b or (due == b and not b_stored)


def funding_gaps(
    settled_us: Sequence[int],
    *,
    interval_min: int,
    lo_us: int,
    hi_us: int | None,
    lo_is_settlement: bool = False,
    grid_us: int | None = None,
) -> tuple[tuple[int, int], ...]:
    """22 `FundingPageMeta.coverage.gaps` over `[lo_us, hi_us]` (`hi_us` None: no open tail).

    `settled_us` are the stored settlements inside the span, ascending; `lo_us` is a stored
    settlement (`lo_is_settlement`) when a page resumes after one or the listing bounds the span.
    A span is a gap when a settlement was due in it and none is stored (`_missing_between`):
    `grid_us` is any settlement time of the symbol, which fixes its grid. Past `GAP_CAP` the
    oldest are joined into one span, so no missing settlement is left out."""
    step = interval_min * _US_PER_MIN
    gaps: list[tuple[int, int]] = []
    anchor, anchor_stored = lo_us, lo_is_settlement
    for ts in settled_us:
        if _missing_between(anchor, anchor_stored, ts, True, step, grid_us):
            gaps.append((anchor, ts))
        anchor, anchor_stored = ts, True
    if hi_us is not None and hi_us > anchor:  # `hi_us` is a covered edge
        if _missing_between(anchor, anchor_stored, hi_us, False, step, grid_us):
            gaps.append((anchor, hi_us))
    if len(gaps) > GAP_CAP:
        cut = len(gaps) - GAP_CAP + 1
        gaps = [(gaps[0][0], gaps[cut - 1][1]), *gaps[cut:]]
    return tuple(gaps)


class FundingEstimate(BaseModel):
    """24 §19.110 / 22 `FundingEstimate`: one position's estimated charge at the next settlement.
    Server-computed only (C-2.12); `None` on the position, never a zero amount, is "no charge"."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    amount: Decimal
    direction: Literal["pay", "receive", "none"]
    funding_rate: Decimal
    settles_at: int
    computed_at: int


def estimate_funding(
    *,
    side: Literal["long", "short"] | None,
    size: Decimal,
    mark_price: Decimal | None,
    funding_rate: Decimal | None,
    settles_at_us: int | None,
    computed_at_us: int,
) -> FundingEstimate | None:
    """|size x mark x rate| at 8 dp `ROUND_HALF_UP`; a long pays and a short receives when the
    rate is positive, the reverse when negative, `none` at exactly zero. `None` when the position
    is flat or the mark, the rate or the settlement time is not held."""
    if side is None or size <= 0:
        return None
    if mark_price is None or funding_rate is None or settles_at_us is None:
        return None
    raw = size * mark_price * funding_rate
    amount = abs(raw).quantize(ESTIMATE_QUANTUM, rounding=ROUND_HALF_UP)
    direction: Literal["pay", "receive", "none"]
    if funding_rate == 0:
        direction = "none"
    elif (funding_rate > 0) == (side == "long"):
        direction = "pay"
    else:
        direction = "receive"
    return FundingEstimate(
        amount=amount,
        direction=direction,
        funding_rate=funding_rate,
        settles_at=settles_at_us,
        computed_at=computed_at_us,
    )


@dataclass(frozen=True, slots=True)
class FundingSettlement:
    """A normalised settled-history print as the adapter returns it: the
    exchange gives no interval and no annualisation, so neither is carried."""

    ts_us: int
    symbol: str
    funding_rate: Decimal


@dataclass(frozen=True, slots=True)
class SettledFunding:
    """One settled funding payment. The only shape the store accepts."""

    ts_us: int
    symbol: str
    funding_rate: Decimal
    interval_min: int
    annualised_pct: Decimal
    source: str = SOURCE_HISTORY


@dataclass(frozen=True, slots=True)
class PredictedFunding:
    """The current, unsettled, accruing rate. Never persisted."""

    ts_us: int
    symbol: str
    funding_rate: Decimal
    predicted: Literal[True] = True
    estimated: Literal[True] = True


def settle(symbol: str, ts_us: int, funding_rate: Decimal, interval_min: int) -> SettledFunding:
    """Build a settled row, computing `annualised_pct` at write time."""
    return SettledFunding(
        ts_us=ts_us,
        symbol=symbol,
        funding_rate=funding_rate,
        interval_min=interval_min,
        annualised_pct=annualised_pct(funding_rate, interval_min),
    )


__all__ = [
    "ANNUALISED_PCT_QUANTUM",
    "ESTIMATE_QUANTUM",
    "GAP_CAP",
    "MAX_INTERVAL_MIN",
    "MINUTES_PER_YEAR",
    "MIN_INTERVAL_MIN",
    "SOURCE_HISTORY",
    "FundingEstimate",
    "FundingIntervalUnknown",
    "FundingSettlement",
    "HasFundingInterval",
    "PredictedFunding",
    "PredictedFundingRefused",
    "SettledFunding",
    "annualised_pct",
    "estimate_funding",
    "fixed_point",
    "funding_gaps",
    "resolve_funding_interval_minutes",
    "served_annualised_pct",
    "settle",
]
