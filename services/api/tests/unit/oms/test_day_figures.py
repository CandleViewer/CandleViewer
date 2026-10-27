"""The order path's day figures (E29-T04, #913 S4-S ruling Q1; 24-internal-schemas.md Sec.9.3.6).

`DayRiskFigures` serves demo and testnet only and refuses `live` at construction, and answers
None for an account of another environment than its own; it reads the wallet, the day's closed
P&L since 00:00 UTC, the positions and open orders (committed risk from the recorded stop, else
the profile's fallback distance) and the taker fee from the venue, concurrently, each kept
`FIGURES_TTL_S` on a fake monotonic clock and bounded by `FIGURES_READ_TIMEOUT_S` and
`FIGURES_BUDGET_S`; a read that fails or times out is None for its figures only and is logged by
figure and error type alone. `invalidate` drops the account's book, day's loss and wallet, and a
read in flight across it keeps nothing. `peek` (E28-T05 S3b, #909) answers only what is kept,
reading nothing (SR-E28-22).
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

import pytest
from prometheus_client import generate_latest
from structlog.testing import capture_logs

from candleviewer.domain.primitives import AccountId, Environment, Symbol, TsUs
from candleviewer.exchange.base.errors import RateBudgetExceededError, RateLimitError
from candleviewer.exchange.base.models import (
    AccountRef,
    ClosedPnl,
    FeeRate,
    Order,
    Position,
    RiskLimitTier,
    Wallet,
)
from candleviewer.exchange.base.ports import TradingPort
from candleviewer.exchange.bybit.trading import ENDPOINTS
from candleviewer.observability.metrics import Metrics
from candleviewer.oms import day_figures
from candleviewer.oms.day_figures import FIGURES_TTL_S, DayRiskFigures, committed_risk
from candleviewer.oms.ports import (
    INTERIM_PORT_LABELS,
    UNKNOWN_FIGURES,
    FiguresReading,
    NoDayFigures,
    OrderFigures,
    SymbolRates,
    announce_interim_port,
)

ACCOUNT = AccountId(UUID("7d3c9a10-28a1-4c1e-9e01-0000000000b3"))
REF = AccountRef(account_id=ACCOUNT, uid="100001", environment="demo", key_ref="kref-1")
NOW = datetime(2026, 10, 26, 9, 30, tzinfo=UTC)
MIDNIGHT_US = int(datetime(2026, 10, 26, tzinfo=UTC).timestamp()) * 1_000_000
NOW_US = MIDNIGHT_US + (9 * 3600 + 30 * 60) * 1_000_000
FALLBACK = Decimal("0.02")


def _position(
    qty: str = "1",
    entry: str | None = "100",
    stop: str | None = "90",
    *,
    side: str = "buy",
    trailing: str | None = None,
) -> Position:
    return Position.model_validate(
        {
            "account_id": ACCOUNT, "symbol": "BTCUSDT", "position_idx": 0, "side": side,
            "qty": Decimal(qty), "avg_entry_price": None if entry is None else Decimal(entry),
            "mark_price": None, "liq_price": None, "leverage": Decimal(5),
            "unrealised_pnl": Decimal(0), "cum_realised_pnl": Decimal(0), "take_profit": None,
            "stop_loss": None if stop is None else Decimal(stop),
            "trailing_stop_distance": None if trailing is None else Decimal(trailing),
            "updated_at": NOW_US,
        }
    )  # fmt: skip


def _order(
    price: str | None = "200",
    stop: str | None = None,
    *,
    leaves: str = "2",
    kind: str = "order",
    reduce_only: bool = False,
    trigger: str | None = None,
    tpsl: str | None = None,
) -> Order:
    return Order.model_validate(
        {
            "order_link_id": "link-1", "exchange_order_id": "x-1", "account_id": ACCOUNT,
            "symbol": "BTCUSDT", "side": "buy", "order_type": "limit", "qty": Decimal(leaves),
            "price": None if price is None else Decimal(price), "state": "new",
            "filled_qty": Decimal(0), "leaves_qty": Decimal(leaves), "avg_fill_price": None,
            "created_at": NOW_US, "terminal_at": None, "order_kind": kind,
            "reduce_only": reduce_only, "stop_loss": None if stop is None else Decimal(stop),
            "trigger_price": None if trigger is None else Decimal(trigger), "tpsl_mode": tpsl,
        }
    )  # fmt: skip


def _pnl(amount: str) -> ClosedPnl:
    return ClosedPnl(
        account_id=ACCOUNT, symbol="BTCUSDT", side="sell", qty=Decimal(1),
        avg_entry_price=Decimal(100), avg_exit_price=Decimal(100), closed_pnl=Decimal(amount),
        leverage=Decimal(5), opened_at=MIDNIGHT_US, closed_at=MIDNIGHT_US + 1,
    )  # fmt: skip


def _wallet(equity: str = "1000", available: str = "800") -> Wallet:
    return Wallet(
        account_id=ACCOUNT, equity=Decimal(equity), wallet_balance=Decimal(equity),
        available_to_withdraw=None, available_margin=Decimal(available), used_margin=Decimal(0),
        unrealised_pnl=Decimal(0), cum_realised_pnl=Decimal(0), account_im_rate=Decimal(0),
        account_mm_rate=Decimal(0), updated_at=NOW_US,
    )  # fmt: skip


def _tier(tier_id: int, value: str, mmr: str) -> RiskLimitTier:
    return RiskLimitTier(
        tier_id=tier_id, risk_limit_value=Decimal(value), maintenance_margin_rate=Decimal(mmr),
        initial_margin_rate=Decimal("0.01"), max_leverage=Decimal(100),
    )  # fmt: skip


class Venue:
    """The trading port's reads `DayRiskFigures` makes, counted; `fail` names reads that raise,
    `hang` reads that never answer, and `paused` reads that wait for `release` (`entered` is set
    once every paused read has started)."""

    def __init__(self) -> None:
        self.wallet_value = _wallet()
        self.records = [_pnl("-30"), _pnl("10")]
        self.held = [_position()]
        self.open = [_order()]
        self.fee = FeeRate(
            symbol="BTCUSDT", maker=Decimal("0.0002"), taker=Decimal("0.00055"), fetched_at=0
        )
        self.calls: list[str] = []
        self.windows: list[tuple[TsUs, TsUs]] = []
        self.fail: set[str] = set()
        self.error: Exception = RuntimeError("venue refused")
        self.hang: set[str] = set()
        self.paused: set[str] = set()
        self.entered, self.release = asyncio.Event(), asyncio.Event()

    async def _answer[T](self, name: str, value: T) -> T:
        self.calls.append(name)
        if name in self.fail:
            raise self.error
        if name in self.hang:
            await asyncio.Event().wait()
        if name in self.paused:
            if self.paused <= set(self.calls):
                self.entered.set()
            await self.release.wait()
        return value

    async def wallet(self, account: AccountRef) -> Wallet:
        return await self._answer("wallet", self.wallet_value)

    async def closed_pnl(self, account: AccountRef, start: TsUs, end: TsUs) -> Sequence[ClosedPnl]:
        self.windows.append((start, end))
        return await self._answer("closed_pnl", self.records)

    async def positions(self, account: AccountRef) -> Sequence[Position]:
        return await self._answer("positions", self.held)

    async def open_orders(self, account: AccountRef) -> Sequence[Order]:
        return await self._answer("open_orders", self.open)

    async def fee_rate(self, account: AccountRef, symbol: Symbol) -> FeeRate:
        return await self._answer("fee_rate", self.fee)


class Clock:
    def __init__(self) -> None:
        self.t = 100.0

    def __call__(self) -> float:
        return self.t


def _figures(
    venue: Venue,
    clock: Clock | None = None,
    tiers: dict[str, Any] | None = None,
    environment: Environment = "demo",
) -> DayRiskFigures:
    known = {"BTCUSDT": [_tier(1, "2000000", "0.01"), _tier(7, "1000", "0.005")]}
    tiers = known if tiers is None else tiers
    return DayRiskFigures(
        environment, port_for=lambda _env: cast(TradingPort, venue), tiers=tiers.get,
        now=lambda: NOW, monotonic=clock or Clock(),
    )  # fmt: skip


async def _read(figures: OrderFigures, fallback: Decimal | None = FALLBACK) -> FiguresReading:
    return await figures.read(REF, ["BTCUSDT"], fallback_sl_offset_pct=fallback)


@pytest.mark.parametrize("environment", ["live", "staging"])
def test_day_figures_live_or_unknown_environment_refused_at_construction(
    environment: str,
) -> None:
    with pytest.raises(ValueError, match="demo and testnet only"):
        DayRiskFigures(
            cast(Environment, environment), port_for=lambda _e: cast(TradingPort, Venue()),
            tiers=lambda _s: None, now=lambda: NOW, monotonic=Clock(),
        )  # fmt: skip


async def test_day_figures_each_figure_read_from_the_venue() -> None:
    venue = Venue()
    reading = await _read(_figures(venue))
    account = reading.account
    assert (account.equity, account.available_margin) == (Decimal(1000), Decimal(800))
    assert account.realised_loss_today == Decimal(20)  # -30 + 10: a net loss of 20
    # position |100 - 90| x 1 = 10; order without a stop: 200 x 0.02 x 2 = 8
    assert account.committed_risk == Decimal(18)
    assert reading.symbols == {
        "BTCUSDT": SymbolRates(
            maintenance_margin_rate=Decimal("0.005"), taker_fee_rate=Decimal("0.00055")
        )
    }
    assert account.taker_fee_rate is None and account.maintenance_margin_rate is None
    assert venue.windows == [(MIDNIGHT_US, NOW_US)]  # since 00:00 UTC


async def test_day_figures_net_gain_today_gives_zero_loss() -> None:
    venue = Venue()
    venue.records = [_pnl("50"), _pnl("-20")]
    assert (await _read(_figures(venue))).account.realised_loss_today == Decimal(0)


async def test_day_figures_within_ttl_answers_from_cache_then_reads_again() -> None:
    venue, clock = Venue(), Clock()
    figures = _figures(venue, clock)
    await _read(figures)
    first = list(venue.calls)
    clock.t += FIGURES_TTL_S - 0.001
    await _read(figures)
    assert venue.calls == first  # every figure kept
    clock.t += 0.001
    await _read(figures)
    assert venue.calls == first * 2


async def test_day_figures_invalidate_drops_book_loss_and_wallet_not_fee() -> None:
    venue = Venue()
    figures = _figures(venue)
    await _read(figures)
    venue.calls.clear()
    venue.open = [*venue.open, _order("100", "95", leaves="4")]
    figures.invalidate(ACCOUNT)
    reading = await _read(figures)
    assert sorted(venue.calls) == ["closed_pnl", "open_orders", "positions", "wallet"]
    assert reading.account.committed_risk == Decimal(38)  # + |100 - 95| x 4


async def test_day_figures_invalidate_during_read_keeps_nothing() -> None:
    venue = Venue()
    venue.paused = {"wallet", "closed_pnl", "positions"}
    figures = _figures(venue)
    async with asyncio.TaskGroup() as group:
        first = group.create_task(_read(figures))
        await venue.entered.wait()
        assert "fee_rate" in venue.calls  # the reads run together, not one after another
        figures.invalidate(ACCOUNT)  # an accepted send, while the reads are at the venue
        venue.wallet_value = _wallet(equity="700")
        venue.release.set()
    assert (await first).account.equity == Decimal(1000)  # the read still answers its value
    venue.calls.clear()
    reading = await _read(figures)
    assert sorted(venue.calls) == ["closed_pnl", "open_orders", "positions", "wallet"]
    assert reading.account.equity == Decimal(700)  # the venue's, not the pre-send answer


def _peek(figures: OrderFigures, ref: AccountRef = REF, symbol: Symbol = "BTCUSDT") -> Any:
    return figures.peek(ref, [symbol], fallback_sl_offset_pct=FALLBACK)


async def test_peek_never_reads_the_venue() -> None:
    """SR-E28-22, F-09: `peek` is synchronous and starts nothing, a reading kept or none: no port
    is asked for, so no venue read follows; the live stand-in keeps nothing to answer."""
    venue, asked = Venue(), list[Environment]()

    def port_for(environment: Environment) -> TradingPort:
        asked.append(environment)
        return cast(TradingPort, venue)

    figures = DayRiskFigures(
        "demo", port_for=port_for, tiers=lambda _s: None, now=lambda: NOW, monotonic=Clock()
    )
    assert not inspect.iscoroutinefunction(DayRiskFigures.peek)
    assert _peek(figures) is None and _peek(NoDayFigures()) is None
    await asyncio.sleep(0)  # a read the peek started would have asked for its port by now
    assert (asked, venue.calls) == ([], [])
    await _read(figures)
    asked.clear()
    venue.calls.clear()
    assert _peek(figures) is not None
    await asyncio.sleep(0)
    assert (asked, venue.calls) == ([], [])


async def test_peek_answers_only_a_kept_reading() -> None:
    """What `read` answered, the committed risk at the asked fallback, while every figure kept is
    younger than `FIGURES_TTL_S`; else None: nothing kept, a stale or dropped figure, one a failed
    read never kept, a symbol never read, an account of another environment (C-2.11)."""
    venue, clock = Venue(), Clock()
    figures = _figures(venue, clock)
    assert _peek(figures) is None
    reading = await _read(figures)
    clock.t += FIGURES_TTL_S - 0.001
    assert _peek(figures) == reading
    wider = figures.peek(REF, ["BTCUSDT"], fallback_sl_offset_pct=Decimal("0.05"))
    assert wider is not None and wider.account.committed_risk == Decimal(30)  # 10 + 200 x 0.05 x 2
    assert _peek(figures, symbol="ETHUSDT") is None
    assert _peek(figures, REF.model_copy(update={"environment": "testnet"})) is None
    clock.t += 0.001
    assert _peek(figures) is None  # stale at `FIGURES_TTL_S`: the next answer is the venue's
    await _read(figures)
    figures.invalidate(ACCOUNT)
    assert _peek(figures) is None
    venue.fail.add("positions")
    await _read(figures)
    assert _peek(figures) is None  # the book was not kept


def test_committed_risk_order_without_stop_uses_fallback_distance() -> None:
    risk = committed_risk([], [_order("200", None, leaves="2")], Decimal("0.05"))
    assert risk == Decimal(20)  # 200 x 0.05 x 2


def test_committed_risk_conditional_order_measured_from_its_trigger() -> None:
    order = _order(None, "290", leaves="1", kind="conditional", trigger="300")
    assert committed_risk([], [order], None) == Decimal(10)


def test_committed_risk_conditional_limit_order_measured_from_its_price() -> None:
    order = _order("310", "300", leaves="1", kind="conditional", trigger="290")
    assert committed_risk([], [order], None) == Decimal(10)  # |310 - 300|, not the trigger


def test_committed_risk_short_position_with_stop_above_entry() -> None:
    assert committed_risk([_position("2", "100", "104", side="sell")], [], None) == Decimal(8)


def test_committed_risk_position_trailing_distance_is_its_stop() -> None:
    trailing = _position("3", "100", None, trailing="4")
    assert committed_risk([trailing], [], FALLBACK) == Decimal(12)  # 4 x 3, not the fallback


@pytest.mark.parametrize(("tpsl", "risk"), [(None, 10), ("full", 10), ("partial", 20)])
def test_committed_risk_partial_stop_counts_as_unrecorded(tpsl: str | None, risk: int) -> None:
    order = _order("200", "195", leaves="2", tpsl=tpsl)  # partial: 200 x 0.05 x 2, errs high
    assert committed_risk([], [order], Decimal("0.05")) == Decimal(risk)


def test_committed_risk_reduce_only_and_position_stops_add_nothing() -> None:
    orders = [_order(reduce_only=True), _order(kind="stop_loss"), _order(leaves="0")]
    assert committed_risk([_position(qty="0", stop=None)], orders, None) == Decimal(0)


@pytest.mark.parametrize(
    ("positions", "orders"),
    [([_position(stop=None)], []), ([], [_order(stop=None)]), ([_position(entry=None)], [])],
)
def test_committed_risk_item_with_no_stop_or_entry_is_none(
    positions: list[Position], orders: list[Order]
) -> None:
    assert committed_risk(positions, orders, None) is None


async def test_day_figures_no_fallback_and_no_recorded_stop_gives_none() -> None:
    reading = await _read(_figures(Venue()), fallback=None)
    assert reading.account.committed_risk is None
    assert reading.account.equity == Decimal(1000)  # the other figures still stand


@pytest.mark.parametrize(
    ("read", "figure"),
    [
        ("wallet", "equity"),
        ("closed_pnl", "realised_loss_today"),
        ("positions", "committed_risk"),
        ("open_orders", "committed_risk"),
    ],
)
async def test_day_figures_read_failure_gives_none_and_keeps_nothing(
    read: str, figure: str
) -> None:
    venue = Venue()
    venue.fail.add(read)
    figures = _figures(venue)
    assert getattr((await _read(figures)).account, figure) is None
    venue.fail.clear()
    assert getattr((await _read(figures)).account, figure) is not None  # read again, not kept


@pytest.mark.parametrize(
    "refusal", [RateBudgetExceededError("no token within the wait"), RateLimitError("10006")]
)
@pytest.mark.parametrize(
    ("read", "figure"),
    [
        ("wallet", "equity"),
        ("closed_pnl", "realised_loss_today"),
        ("positions", "committed_risk"),
        ("open_orders", "committed_risk"),
    ],
)
async def test_day_figures_budget_refusal_gives_none_without_retry_or_cache(
    read: str, figure: str, refusal: Exception
) -> None:
    """C-12.7: a refused read is `figure_unknown`: asked once, not retried, nothing kept."""
    venue = Venue()
    venue.fail.add(read)
    venue.error = refusal
    figures = _figures(venue)
    assert getattr((await _read(figures)).account, figure) is None
    assert venue.calls.count(read) == 1  # no retry, though the refusal says retryable
    venue.fail.clear()
    assert getattr((await _read(figures)).account, figure) is not None
    assert venue.calls.count(read) == 2  # the refusal was not cached


@pytest.mark.parametrize("refusal", [RateBudgetExceededError("no token"), RateLimitError("10006")])
async def test_day_figures_fee_budget_refusal_gives_none_without_retry_or_cache(
    refusal: Exception,
) -> None:
    venue = Venue()
    venue.fail.add("fee_rate")
    venue.error = refusal
    figures = _figures(venue)
    assert (await _read(figures)).symbols["BTCUSDT"].taker_fee_rate is None
    assert venue.calls.count("fee_rate") == 1
    venue.fail.clear()
    assert (await _read(figures)).symbols["BTCUSDT"].taker_fee_rate is not None
    assert venue.calls.count("fee_rate") == 2


@pytest.mark.parametrize("read", ["wallet", "closed_pnl", "positions", "open_orders", "fee_rate"])
def test_day_figures_reads_take_no_lane_and_the_adapter_serves_them_on_poll(read: str) -> None:
    """C-12.7: the port's reads take no lane, so a caller cannot ask for the stop and cancel
    reserve; the adapter's endpoint table fixes each of them on the `poll` lane."""
    assert "lane" not in inspect.signature(getattr(TradingPort, read)).parameters
    assert ENDPOINTS[read].lane == "poll"


async def test_day_figures_fee_read_failure_gives_none() -> None:
    venue = Venue()
    venue.fail.add("fee_rate")
    assert (await _read(_figures(venue))).symbols["BTCUSDT"].taker_fee_rate is None


async def test_day_figures_estimated_fee_gives_none() -> None:
    venue = Venue()
    venue.fee = venue.fee.model_copy(update={"estimated": True})
    assert (await _read(_figures(venue))).symbols["BTCUSDT"].taker_fee_rate is None


@pytest.mark.parametrize("taker", ["1", "-0.0001", "NaN"])
async def test_day_figures_fee_rate_outside_unit_interval_gives_none(taker: str) -> None:
    venue = Venue()
    venue.fee = venue.fee.model_copy(update={"taker": Decimal(taker)})
    assert (await _read(_figures(venue))).symbols["BTCUSDT"].taker_fee_rate is None


async def test_day_figures_duplicate_symbols_read_once() -> None:
    venue = Venue()
    reading = await _figures(venue).read(
        REF, ["BTCUSDT", "BTCUSDT"], fallback_sl_offset_pct=FALLBACK
    )
    assert list(reading.symbols) == ["BTCUSDT"] and venue.calls.count("fee_rate") == 1


@pytest.mark.parametrize("bound", ["FIGURES_READ_TIMEOUT_S", "FIGURES_BUDGET_S"])
async def test_day_figures_read_timeout_gives_none(
    monkeypatch: pytest.MonkeyPatch, bound: str
) -> None:
    # A zero bound with no sleep: a read that answers without suspending finishes before its
    # timeout fires, so only the hung wallet read is cut; the rest stand.
    monkeypatch.setattr(day_figures, bound, 0)
    venue = Venue()
    venue.hang.add("wallet")
    reading = await _read(_figures(venue))
    assert (reading.account.equity, reading.account.available_margin) == (None, None)
    assert reading.account.realised_loss_today == Decimal(20)


async def test_day_figures_failure_logs_carry_figure_and_error_only() -> None:
    venue = Venue()
    venue.fail = {"wallet", "closed_pnl", "positions", "fee_rate"}
    with capture_logs() as logs:
        await _read(_figures(venue))
    assert sorted(e["figure"] for e in logs) == ["book", "day_loss", "fee", "wallet"]
    for event in logs:  # no amount and no account identifier (C-12.6)
        assert event == {
            "event": "oms_figures_read_failed", "log_level": "warning",
            "figure": event["figure"], "error": "RuntimeError",
        }  # fmt: skip


async def test_day_figures_refused_figure_gives_all_none_and_logs_the_type_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(day_figures, "committed_risk", lambda *_a: Decimal("-7.25"))
    with capture_logs() as logs:
        reading = await _read(_figures(Venue()))
    assert reading.account == UNKNOWN_FIGURES
    assert [e for e in logs if e["event"] == "oms_figures_read_failed"] == [
        {"event": "oms_figures_read_failed", "log_level": "warning",
         "figure": "figures", "error": "ValidationError"}
    ]  # fmt: skip
    assert "7.25" not in repr(logs)


async def test_day_figures_negative_equity_gives_none() -> None:
    venue = Venue()
    venue.wallet_value = _wallet(equity="-5", available="-5")
    reading = await _read(_figures(venue))
    assert reading.account.equity is None
    assert reading.account.available_margin == Decimal(-5)  # a deficit stands (R6)


async def test_day_figures_unknown_or_unreadable_tiers_give_none() -> None:
    def broken(_symbol: Symbol) -> None:
        raise RuntimeError("catalogue gone")

    venue = Venue()
    assert (await _read(_figures(venue, tiers={}))).symbols[
        "BTCUSDT"
    ].maintenance_margin_rate is None
    figures = DayRiskFigures(
        "demo", port_for=lambda _e: cast(TradingPort, venue), tiers=broken,
        now=lambda: NOW, monotonic=Clock(),
    )  # fmt: skip
    assert (await _read(figures)).symbols["BTCUSDT"].maintenance_margin_rate is None


@pytest.mark.parametrize("environment", ["live", "testnet"])
async def test_day_figures_account_of_another_environment_reads_nothing(
    environment: Environment,
) -> None:
    venue = Venue()
    served_not_routed = REF.model_copy(update={"environment": environment})
    with capture_logs() as logs:
        reading = await _figures(venue).read(
            served_not_routed, ["BTCUSDT"], fallback_sl_offset_pct=FALLBACK
        )
    assert set(reading.account.model_dump().values()) == {None} and venue.calls == []
    assert reading.symbols == {}  # no symbol entry: the size step requests no tiers
    assert logs == [
        {
            "event": "oms_figures_environment_mismatch", "log_level": "critical",
            "process_environment": "demo", "account_environment": environment,
        }
    ]  # fmt: skip


def test_risk_figures_interim_label_counted() -> None:
    port = _figures(Venue())
    assert "risk_figures" in INTERIM_PORT_LABELS and port.port == "risk_figures"
    metrics = Metrics("demo")
    assert announce_interim_port("risk_figures", port, metrics=metrics) is True
    line = 'oms_interim_ports{env="demo",port="risk_figures"} 1.0'
    assert line in generate_latest(metrics.registry).decode()
