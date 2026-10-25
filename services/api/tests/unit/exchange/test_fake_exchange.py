"""Acceptance criterion 2: "Fake adapter satisfies the protocol" —
`isinstance(FakeExchange(), MarketDataPort)` must be `True`, and the fake
must be usable end-to-end (seed data in, get it back out) so downstream
unit tests never need a network fixture to exercise `MarketDataPort`
consumers."""

from __future__ import annotations

from candleviewer.domain.events import Instrument
from candleviewer.exchange.base import FakeExchange, MarketDataPort
from candleviewer.exchange.base.errors import NotFoundError
from candleviewer.exchange.base.models import (
    BookLevel,
    BookSnapshot,
    FundingEvent,
    KlineEvent,
    LiquidationEvent,
    OpenInterestEvent,
    RiskLimitTier,
    TickerEvent,
    TradeEvent,
)


def _instrument(symbol: str = "BTCUSDT") -> Instrument:
    return Instrument(
        symbol=symbol,
        base_coin="BTC",
        quote_coin="USDT",
        settle_coin="USDT",
        status="trading",
        contract_type="linear_perpetual",
        launch_time=0,
        tick_size="0.5",
        price_scale=1,
        min_price="0.5",
        max_price="1000000",
        qty_step="0.001",
        min_order_qty="0.001",
        max_order_qty="100",
        max_mkt_order_qty="50",
        min_notional="5",
        max_leverage="100",
        min_leverage="1",
        leverage_step="0.01",
        funding_interval_min=480,
        upper_funding_rate="0.03",
        lower_funding_rate="-0.03",
        copy_trading=False,
        metadata_version=1,
        fetched_at=0,
    )


def test_fake_exchange_satisfies_market_data_port() -> None:
    assert isinstance(FakeExchange(), MarketDataPort)


async def test_fake_exchange_instruments_round_trip() -> None:
    inst = _instrument()
    fake = FakeExchange(instruments=[inst])
    assert list(await fake.instruments()) == [inst]


async def test_fake_exchange_instrument_lookup_by_symbol() -> None:
    inst = _instrument()
    fake = FakeExchange(instruments=[inst])
    assert await fake.instrument("BTCUSDT") == inst


async def test_fake_exchange_instrument_missing_symbol_raises_not_found_error() -> None:
    fake = FakeExchange()
    try:
        await fake.instrument("NOSUCHSYMBOL")
    except NotFoundError:
        pass
    else:
        raise AssertionError("expected NotFoundError")


async def test_fake_exchange_server_time_us_returns_seeded_value() -> None:
    fake = FakeExchange(server_time=1_700_000_000_000_000)
    assert await fake.server_time_us() == 1_700_000_000_000_000


async def test_fake_exchange_subscribe_trades_filters_by_symbol_and_replays() -> None:
    trade_btc = _trade("BTCUSDT")
    trade_eth = _trade("ETHUSDT")
    fake = FakeExchange(trades=[trade_btc, trade_eth])
    collected = [event async for event in fake.subscribe_trades(["BTCUSDT"])]
    assert collected == [trade_btc]


async def test_fake_exchange_subscribe_book_filters_by_symbol_and_depth() -> None:
    snap = _book_snapshot("BTCUSDT", depth=50)
    other_depth = _book_snapshot("BTCUSDT", depth=200)
    other_symbol = _book_snapshot("ETHUSDT", depth=50)
    fake = FakeExchange(book_events=[snap, other_depth, other_symbol])
    collected = [e async for e in fake.subscribe_book(["BTCUSDT"], depth=50)]
    assert collected == [snap]


async def test_fake_exchange_subscribe_ticker_filters_by_symbol() -> None:
    ticker = _ticker("BTCUSDT")
    other = _ticker("ETHUSDT")
    fake = FakeExchange(tickers=[ticker, other])
    collected = [e async for e in fake.subscribe_ticker(["BTCUSDT"])]
    assert collected == [ticker]


async def test_fake_exchange_subscribe_klines_filters_by_symbol_and_interval() -> None:
    kline = _kline("BTCUSDT", interval="1", start=0)
    other_interval = _kline("BTCUSDT", interval="5", start=0)
    fake = FakeExchange(klines=[kline, other_interval])
    collected = [e async for e in fake.subscribe_klines(["BTCUSDT"], interval="1")]
    assert collected == [kline]


async def test_fake_exchange_subscribe_liquidations_filters_by_symbol() -> None:
    liq = _liquidation("BTCUSDT")
    other = _liquidation("ETHUSDT")
    fake = FakeExchange(liquidations=[liq, other])
    collected = [e async for e in fake.subscribe_liquidations(["BTCUSDT"])]
    assert collected == [liq]


async def test_fake_exchange_fetch_klines_filters_by_symbol_interval_and_range() -> None:
    in_range = _kline("BTCUSDT", interval="1", start=100)
    out_of_range = _kline("BTCUSDT", interval="1", start=999)
    fake = FakeExchange(klines=[in_range, out_of_range])
    result = await fake.fetch_klines("BTCUSDT", "1", start=0, end=500)
    assert list(result) == [in_range]


async def test_fake_exchange_fetch_klines_respects_limit() -> None:
    klines = [_kline("BTCUSDT", interval="1", start=i) for i in range(5)]
    fake = FakeExchange(klines=klines)
    result = await fake.fetch_klines("BTCUSDT", "1", start=0, end=10, limit=2)
    assert len(result) == 2


async def test_fake_exchange_fetch_recent_trades_filters_by_symbol_and_limit() -> None:
    trades = [_trade("BTCUSDT"), _trade("BTCUSDT"), _trade("ETHUSDT")]
    fake = FakeExchange(trades=trades)
    result = await fake.fetch_recent_trades("BTCUSDT", limit=1)
    assert len(result) == 1
    assert result[0].symbol == "BTCUSDT"


async def test_fake_exchange_fetch_orderbook_returns_seeded_snapshot() -> None:
    snap = _book_snapshot("BTCUSDT", depth=50)
    fake = FakeExchange(book_events=[snap])
    assert await fake.fetch_orderbook("BTCUSDT", depth=50) == snap


async def test_fake_exchange_fetch_orderbook_missing_raises_not_found_error() -> None:
    fake = FakeExchange()
    try:
        await fake.fetch_orderbook("BTCUSDT", depth=50)
    except NotFoundError:
        pass
    else:
        raise AssertionError("expected NotFoundError")


async def test_fake_exchange_fetch_open_interest_filters_by_symbol_interval_range() -> None:
    oi = _open_interest("BTCUSDT", interval="5min", ts_event=100)
    fake = FakeExchange(open_interest=[oi])
    result = await fake.fetch_open_interest("BTCUSDT", "5min", start=0, end=200)
    assert list(result) == [oi]


async def test_fake_exchange_fetch_funding_history_filters_by_symbol_and_range() -> None:
    funding = _funding("BTCUSDT", ts_event=100)
    fake = FakeExchange(funding=[funding])
    result = await fake.fetch_funding_history("BTCUSDT", start=0, end=200)
    assert list(result) == [funding]


async def test_fake_exchange_fetch_risk_limits_returns_the_symbols_seeded_tiers() -> None:
    tier = _risk_limit_tier()
    fake = FakeExchange(risk_limits={"BTCUSDT": [tier]})
    assert await fake.fetch_risk_limits("BTCUSDT") == [tier]
    assert await fake.fetch_risk_limits("ETHUSDT") == []


def _book_snapshot(symbol: str, *, depth: int) -> BookSnapshot:
    level = BookLevel(price="100", qty="1", price_ticks=200)
    return BookSnapshot(
        event_id="00000000-0000-7000-8000-000000000001",
        ts_event=0,
        ts_ingest=0,
        source="live",
        symbol=symbol,
        depth=depth,
        bids=(level,),
        asks=(level,),
        update_id=1,
        cross_seq=1,
        ts_match=0,
        reason="subscribe",
    )


def _ticker(symbol: str) -> TickerEvent:
    return TickerEvent(
        event_id="00000000-0000-7000-8000-000000000002",
        ts_event=0,
        ts_ingest=0,
        source="live",
        symbol=symbol,
        last_price="100",
        mark_price="100",
        index_price="100",
        bid1_price="99",
        bid1_qty="1",
        ask1_price="101",
        ask1_qty="1",
        open_interest="1",
        open_interest_value="100",
        turnover_24h="100",
        volume_24h="1",
        price_24h_pcnt="0.01",
        funding_rate="0.0001",
        next_funding_time=0,
        is_delta=False,
    )


def _kline(symbol: str, *, interval: str, start: int) -> KlineEvent:
    return KlineEvent(
        event_id="00000000-0000-7000-8000-000000000003",
        ts_event=0,
        ts_ingest=0,
        source="live",
        symbol=symbol,
        interval=interval,  # type: ignore[arg-type]
        start=start,
        end=start + 1,
        open="100",
        high="101",
        low="99",
        close="100",
        volume="1",
        turnover="100",
        confirmed=True,
    )


def _liquidation(symbol: str) -> LiquidationEvent:
    return LiquidationEvent(
        event_id="00000000-0000-7000-8000-000000000004",
        ts_event=0,
        ts_ingest=0,
        source="live",
        symbol=symbol,
        price="100",
        qty="1",
        side="buy",
        liquidated_side="long",
        notional="100",
        batch_index=0,
        ts_estimated=False,
    )


def _open_interest(symbol: str, *, interval: str, ts_event: int) -> OpenInterestEvent:
    return OpenInterestEvent(
        event_id="00000000-0000-7000-8000-000000000005",
        ts_event=ts_event,
        ts_ingest=0,
        source="live",
        symbol=symbol,
        open_interest="1",
        open_interest_value="100",
        interval=interval,  # type: ignore[arg-type]
        origin="ws_ticker",
    )


def _funding(symbol: str, *, ts_event: int) -> FundingEvent:
    return FundingEvent(
        event_id="00000000-0000-7000-8000-000000000006",
        ts_event=ts_event,
        ts_ingest=0,
        source="live",
        symbol=symbol,
        funding_rate="0.0001",
        funding_interval_min=480,
        next_funding_time=0,
        settled=True,
        annualized_rate="0.03",
    )


def _risk_limit_tier() -> RiskLimitTier:
    return RiskLimitTier(
        tier_id=1,
        risk_limit_value="1000000",
        maintenance_margin_rate="0.005",
        initial_margin_rate="0.01",
        max_leverage="100",
    )


def _trade(symbol: str) -> TradeEvent:
    return TradeEvent(
        event_id="00000000-0000-7000-8000-000000000000",
        ts_event=0,
        ts_ingest=0,
        source="live",
        symbol=symbol,
        trade_id="1",
        price="100",
        qty="1",
        side="buy",
        is_block_trade=False,
        price_ticks=200,
        notional="100",
        seq=1,
    )
