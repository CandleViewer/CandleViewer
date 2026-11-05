"""The harness's constants and one arm's settings (#856 Scope; the scout's §1 and §5)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Final, Literal

from spike.oms_demo_path.config import SYMBOL as BTCUSDT
from spike.oms_demo_path.safety import Refused

#: The ticket's symbols. The low-liquidity third is not named yet (BQ-4): S1 trades BTCUSDT
#: only, since the reused `GuardedPort` admits no other symbol; S3 widens the allow-list.
SYMBOLS: Final = (BTCUSDT, "ETHUSDT")
#: The ticket's floors for a decision-grade run: >=200 measured (`ok`) samples per arm, three
#: symbols among them.
MIN_SAMPLES_PER_ARM: Final = 200
MIN_SYMBOLS: Final = 3
#: A sample whose host-versus-exchange skew passes this is discarded (#856 Technical notes).
SKEW_LIMIT_MS: Final = 500.0
#: The decision rule agreed up front: arm (b) p99 above this means attach-only.
DECISION_P99_MS: Final = 1500.0
#: 24 §8.8 rule 2: a position-level stop lands within 2 s of the first fill.
DEADLINE_MS: Final = 2000.0
#: The decision's success bar: arm (b)'s stop writes that landed over those that were sent
#: (`stop_success_rate`). Under it the verdict is attach-only, whatever the p99 says: at most
#: one stop write in 200 may fail to land. Each one that does also enters the p99 as +inf.
MIN_STOP_SUCCESS_RATE: Final = 0.995
#: A run whose `skew` discards (each outside every statistic) pass this share of an arm's
#: samples answers `insufficient`: the discards could be its slow samples.
MAX_SKEW_DISCARD_SHARE: Final = 0.05
#: Q5 (main-orchestrator, 2026-11-05): every arm (b) opener carries an attached backstop stop
#: 5 to 10 % from the entry; the measured `trading-stop` tightens it.
BACKSTOP_MIN_PCT: Final = Decimal(5)
BACKSTOP_MAX_PCT: Final = Decimal(10)
#: Offset samples per estimate (the best round trip wins, as #843's `ClockOffset` keeps it).
OFFSET_SAMPLES: Final = 5

type Arm = Literal["a", "b"]


@dataclass(frozen=True, slots=True)
class ArmConfig:
    """One arm's run: the symbol, the order size, the distances and the waits.

    `cross_bps` puts the opener's limit through the touch (it fills whole, as a taker),
    `sl_bps` is the measured stop's distance from the reference, `backstop_pct` arm (b)'s far
    stop. `fill_wait_s` bounds the wait for the first execution push, `settle_wait_s` the wait
    for the position to show the stop. After an opener whose outcome is open (an ambiguous
    create, or no fill seen), its order is looked up by `orderLinkId` at most `lookup_tries`
    times, `lookup_every_s` apart, within `lookup_wait_s` in all (D1)."""

    symbol: str = BTCUSDT
    qty: Decimal = Decimal("0.002")
    tick: Decimal = Decimal("0.10")
    cross_bps: Decimal = Decimal(10)
    sl_bps: Decimal = Decimal(50)
    backstop_pct: Decimal = Decimal("7.5")
    fill_wait_s: float = 5.0
    settle_wait_s: float = 5.0
    offset_every: int = 20
    lookup_tries: int = 8
    lookup_every_s: float = 0.25
    lookup_wait_s: float = 2.0

    def __post_init__(self) -> None:
        if self.symbol not in SYMBOLS:
            raise Refused(f"{self.symbol} is not on the harness's symbol allow-list")
        if not BACKSTOP_MIN_PCT <= self.backstop_pct <= BACKSTOP_MAX_PCT:
            raise Refused("Q5: the arm (b) backstop sits 5 to 10 % from the entry")
        if not Decimal(0) < self.sl_bps < self.backstop_pct * 100:
            raise Refused("the measured stop sits inside the backstop: it tightens, never loosens")
        if self.qty <= 0 or self.tick <= 0 or self.cross_bps <= 0 or self.offset_every < 1:
            raise Refused("the size, the tick, the cross and the offset cadence are positive")
        if self.lookup_tries < 1 or self.lookup_every_s <= 0 or self.lookup_wait_s <= 0:
            raise Refused("the order lookup is bounded: a positive count, cadence and wait")
