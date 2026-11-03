"""Bar domain model (`docs/plan/24-internal-schemas.md` §3.1-§3.2, ticket E12-T01).

Interface-first foundation for every builder (E12-S01…S04) and for E13/E18/E19/E26, which
key off `spec_hash`. Money and quantity are `Decimal` throughout; conversion to DOUBLE
happens only at the storage boundary (E12-T02).

Hot path: builders mutate an internal draft and materialise a frozen `Bar` with
`Bar.model_construct(...)` only for an `open`, a `close` or an amend, and the forming bar on
demand (`forming()`, §3.2, #2022). Validation happens once, at spec level, never per trade.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from functools import cached_property
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from candleviewer.bars.errors import BarSpecError
from candleviewer.bars.limits import MAX_REVERSAL_BRICKS, RENKO_TICKS_RANGE
from candleviewer.domain.primitives import Notional, Px, Qty, Symbol, TsUs
from candleviewer.exchange.base.models import TradeEvent

BarKind = Literal["time", "tick", "volume", "range", "delta", "renko"]

#: Per-kind parameter field (renko reuses `range_ticks` as its brick size, §3.1).
KIND_PARAM: dict[str, str] = {
    "time": "interval_ms",
    "tick": "tick_count",
    "volume": "volume_threshold",
    "range": "range_ticks",
    "delta": "delta_threshold",
    "renko": "range_ticks",
}
PARAM_FIELDS: tuple[str, ...] = (
    "interval_ms",
    "tick_count",
    "volume_threshold",
    "range_ticks",
    "delta_threshold",
)


MAX_SIG_DIGITS = 28  # decimal context precision; instrument tick/lot values are far shorter


def _normalise(d: Decimal) -> Decimal:
    """`Decimal("50.00")` -> `Decimal("50")`; never exponent form for integers."""
    return Decimal(format(d.normalize(), "f"))


def check_renko_bounds(range_ticks: int | Decimal, reversal_bricks: int) -> None:
    """SR-E12-03 / BR-29 renko bounds (reject, never clamp); raises `BarSpecError` (-> 422)."""
    lo, hi = RENKO_TICKS_RANGE
    if not lo <= range_ticks <= hi:
        raise BarSpecError(f"The renko brick size must be between {lo} and {hi} ticks.")
    if reversal_bricks > MAX_REVERSAL_BRICKS:
        raise BarSpecError(f"reversal_bricks must be at most {MAX_REVERSAL_BRICKS}.")


class BarSpec(BaseModel):
    """What series a builder produces. Exactly one per-kind parameter is set, matching `kind`.

    Identity is `spec_hash` (sha256 over canonical JSON, defaults included) — see
    `candleviewer.bars.spec`.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: BarKind
    interval_ms: int | None = Field(default=None, gt=0)
    tick_count: int | None = Field(default=None, gt=0)
    volume_threshold: Qty | None = Field(default=None, gt=0, allow_inf_nan=False)
    range_ticks: int | None = Field(default=None, gt=0)
    delta_threshold: Qty | None = Field(default=None, gt=0, allow_inf_nan=False)
    price_source: Literal["last", "mark"] = "last"
    session_anchor_utc_min: int = Field(default=0, ge=0, lt=1440)
    align_to_epoch: bool = True
    renko_wick: bool = False
    reversal_bricks: int = Field(default=2, ge=1)

    @model_validator(mode="after")
    def _exactly_one(self) -> BarSpec:
        expected = KIND_PARAM[self.kind]
        populated = [f for f in PARAM_FIELDS if getattr(self, f) is not None]
        stray = [f for f in populated if f != expected]
        if stray:
            raise BarSpecError(
                f"A bar spec of kind '{self.kind}' must not set {', '.join(stray)}; "
                f"it takes {expected} only."
            )
        if expected not in populated:
            raise BarSpecError(f"A bar spec of kind '{self.kind}' requires {expected} to be set.")
        if self.kind == "renko":
            check_renko_bounds(self.param_value, self.reversal_bricks)
        for f in ("volume_threshold", "delta_threshold"):
            v = getattr(self, f)
            if v is not None:
                digits = v.as_tuple().digits
                sig = len("".join(map(str, digits)).rstrip("0"))
                if sig > MAX_SIG_DIGITS:
                    raise BarSpecError(
                        f"{f} has {sig} significant digits; at most {MAX_SIG_DIGITS} are allowed."
                    )
                object.__setattr__(self, f, _normalise(v))
        return self

    @property
    def param_value(self) -> int | Decimal:
        """The populated per-kind parameter (exactly one exists, see `_exactly_one`)."""
        v: int | Decimal | None = getattr(self, KIND_PARAM[self.kind])
        if v is None:  # pragma: no cover - unreachable for a validated spec
            raise BarSpecError(f"A bar spec of kind '{self.kind}' has no parameter.")
        return v

    @cached_property
    def spec_hash(self) -> str:
        """Memoised 64-hex identity; computed once per spec, never per trade."""
        from candleviewer.bars.spec import compute_spec_hash  # cycle break: spec imports models

        return compute_spec_hash(self)


class Bar(BaseModel):
    """One bar (§3.1).

    `min_delta`/`max_delta` are the **running intra-bar path extremes** of the cumulative
    delta (minimum/maximum the delta reached at any trade inside the bar), NOT the endpoint
    values and NOT min/max of per-trade deltas. BI-3: `min_delta <= delta <= max_delta`.
    `synthetic=True` marks a `BarSeries.densify()` filler bar, which is never persisted.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    spec_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    symbol: Symbol
    index: int = Field(ge=0)
    open_time: TsUs
    close_time: TsUs
    open: Px
    high: Px
    low: Px
    close: Px
    volume: Qty
    buy_volume: Qty
    sell_volume: Qty
    delta: Qty
    min_delta: Qty
    max_delta: Qty
    trade_count: int = Field(ge=0)
    turnover: Notional
    vwap: Px
    closed: bool
    partial: bool
    gap_before: bool
    synthetic: bool = False


class BarUpdate(BaseModel):
    """A builder emission (§3.2)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["open", "update", "close"]
    bar: Bar
    amended: bool = False


class BuilderState(BaseModel):
    """Envelope for a builder snapshot, persisted every 60 s per `(symbol, spec_hash)` (§3.2).

    `blob` is the builder's versioned orjson JSON, see 24-internal §3.2; its layout is
    owned by each builder implementation (E12-S01…S04) and versioned by `state_version`.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    spec_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    symbol: Symbol
    state_version: int = Field(ge=1)
    last_trade_seq: int | None = None
    blob: bytes


class BarBuilder(Protocol):
    """Builder contract (§3.2). Declaration only; implementations land in E12-S01…S04."""

    spec: BarSpec

    def on_trade(self, t: TradeEvent) -> Sequence[BarUpdate]: ...

    def on_clock(self, now_us: TsUs) -> Sequence[BarUpdate]: ...

    def forming(self) -> BarUpdate | None:
        """The forming bar as an `update` (`bar.closed=False`), or None; changes no state.
        `on_trade`/`on_clock` return only an `open`, a `close` or an amended `close` (§3.2)."""
        ...

    def snapshot(self) -> BuilderState: ...

    def restore(self, state: BuilderState) -> None: ...
