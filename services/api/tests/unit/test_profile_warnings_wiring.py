"""#906 (D2-m2): `SaveTimeFigures`, the profile save's `SizingWarningsPort` over the wallet cache,
the catalogue's cached instruments and risk-limit tiers, and the ticker stream (E28-T03 #907).
Fakes over the recorded instrument page and risk-limit ladders (C-13.5); no I/O, no clock."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import cast
from uuid import UUID

import pytest

from candleviewer.accounts import profile_validator as pv
from candleviewer.accounts.sizer import SizingMarket
from candleviewer.accounts.wallet import WalletSnapshot, WalletView
from candleviewer.exchange.base.models import RiskLimitTier, TickerEvent
from candleviewer.exchange.bybit.instruments import parse_instruments
from candleviewer.exchange.bybit.risk_limits import order_tiers, parse_risk_limit_page
from candleviewer.ingestion.instruments import CatalogueSnapshot
from candleviewer.profile_warnings_wiring import SaveTimeFigures
from tests._corpus import rest
from tests.unit.accounts.test_sizer import profile

D = Decimal
ACC = UUID(int=7)
_PAGE = parse_instruments(rest("rest/instruments_before.json")["result"]["list"], fetched_at_us=0)


def _tiers(symbol: str) -> tuple[RiskLimitTier, ...]:
    page, _ = parse_risk_limit_page(rest(f"rest/risk_limit_{symbol}.json"), symbol=symbol)
    return order_tiers(page)


def _wallet(equity: str = "10000", *, stale: bool = False) -> WalletView:
    snap = WalletSnapshot(
        coin="USDT", equity=D(equity), wallet_balance=D("10000"), available_balance=D("8000"),
        unrealised_pnl=D(0), account_im_rate=D("0.01"), account_mm_rate=D("0.005"),
        updated_at=datetime(2026, 10, 5, tzinfo=UTC),
    )  # fmt: skip
    return WalletView(snap, stale, None)


class _Wallets:
    def __init__(self, view: WalletView | None) -> None:
        self.views = {ACC: view} if view is not None else {}

    def view(self, account_id: UUID) -> WalletView | None:
        return self.views.get(account_id)


class _Catalogue:
    def __init__(self, snapshot: CatalogueSnapshot | None) -> None:
        self.snapshot = lambda: snapshot


def _catalogue(**tiers: tuple[RiskLimitTier, ...]) -> _Catalogue:
    return _Catalogue(CatalogueSnapshot({i.symbol: i for i in _PAGE.instruments}, 0,
                                        risk_limits=tiers))  # fmt: skip


class _Tickers:
    def __init__(self, bid: str | None, ask: str | None, last: str | None, *, stale: bool = False):
        prices = {"bid1_price": bid, "ask1_price": ask, "last_price": last}
        self.ticker = SimpleNamespace(**{k: None if p is None else D(p) for k, p in prices.items()})
        self.stale = stale

    def latest(self, symbol: str) -> TickerEvent | None:
        return cast(TickerEvent, self.ticker) if symbol == "BTCUSDT" else None

    def is_stale(self, symbol: str) -> bool:
        return self.stale


_QUOTED = _Tickers("63999.9", "64000.1", "63990")


def _port(
    wallet: WalletView | None = None, catalogue: _Catalogue | None = None,
    tickers: _Tickers | None = _QUOTED,
) -> SaveTimeFigures:  # fmt: skip
    return SaveTimeFigures(_Wallets(wallet or _wallet()), lambda: catalogue, lambda: tickers)


async def _one(port: SaveTimeFigures, symbol: str = "BTCUSDT") -> pv.SymbolFigures:
    return (await port.figures(ACC, [symbol])).symbols[symbol]


async def test_open_symbols_are_none_until_a_position_read_model_binds() -> None:
    assert await _port().open_symbols(ACC) == ()

    async def held(account_id: UUID) -> Sequence[str]:
        return ("SOLUSDT",) if account_id == ACC else ()

    bound = SaveTimeFigures(None, lambda: None, lambda: None, positions=held)
    assert await bound.open_symbols(ACC) == ("SOLUSDT",)


@pytest.mark.parametrize("stale", [False, True])
async def test_equity_staleness_and_available_margin_come_from_the_wallet_view(stale: bool) -> None:
    """BQ-5: the fee, the day's loss and the committed risk have no source, so stay unknown."""
    save = await _port(_wallet(stale=stale)).figures(ACC, [])
    got = (save.figures.equity, save.figures.available_margin, save.equity_stale)
    assert got == (D("10000"), D("8000"), stale)
    assert set(save.figures.model_dump(exclude={"equity", "available_margin"}).values()) == {None}


@pytest.mark.parametrize(
    ("wallets", "available"),
    [(_Wallets(None), None), (_Wallets(WalletView(None, True, None)), None), (None, None),
     (_Wallets(_wallet("-5")), D("8000"))],
    ids=["untracked", "no-snapshot", "no-cache", "negative-equity"],
)  # fmt: skip
async def test_wallet_unknown_equity(wallets: _Wallets | None, available: Decimal | None) -> None:
    save = await SaveTimeFigures(wallets, lambda: None, lambda: None).figures(ACC, [])
    assert (save.figures.equity, save.figures.available_margin) == (None, available)


@pytest.mark.parametrize(
    ("tickers", "market"),
    [
        (_QUOTED, SizingMarket(mid=D(64000))),  # the mid of a quoted bid and ask
        (_Tickers(None, "64000.1", "63990"), SizingMarket(last_price=D(63990))),  # else last
        (_Tickers("0", "64000.1", "63990"), SizingMarket(last_price=D(63990))),  # no quote at 0
        (_Tickers(None, None, "0"), SizingMarket()),  # a last price at 0 is no price
        (_Tickers(None, None, None), SizingMarket()),
        (_Tickers("63999.9", "64000.1", "63990", stale=True), SizingMarket()),  # stale: none
        (None, SizingMarket()),  # no ticker stream composed
    ],
)
async def test_market_is_mid_else_last(tickers: _Tickers | None, market: SizingMarket) -> None:
    assert (await _one(_port(tickers=tickers))).market == market


async def test_the_instrument_comes_from_the_catalogue_snapshot() -> None:
    """A symbol without a ticker has no price: a save drives no ticker demand (BQ-6)."""
    got = await _one(_port(catalogue=_catalogue()))
    assert got.instrument is not None and got.instrument.symbol == "BTCUSDT"
    eth = await _one(_port(catalogue=_catalogue()), "ETHUSDT")
    assert eth.instrument is not None and eth.market == SizingMarket()
    assert (await _one(_port(catalogue=_catalogue()), "NOPEUSDT")).instrument is None


@pytest.mark.parametrize("catalogue", [None, _Catalogue(None)], ids=["no-scheduler", "no-snapshot"])
async def test_no_catalogue_is_no_instrument_and_no_rate(catalogue: _Catalogue | None) -> None:
    got = await _one(_port(catalogue=catalogue))
    assert (got.instrument, got.maintenance_margin_rate) == (None, None)


@pytest.mark.parametrize(("symbol", "lowest_id"), [("BTCUSDT", 1), ("ETHUSDT", 11)])
async def test_rate_is_lowest_tier_by_value_not_id_1(symbol: str, lowest_id: int) -> None:
    """ETHUSDT's ids start at 11, so no `tier_id == 1` exists; the ladder is reversed to prove the
    adapter sorts rather than takes the first held."""
    tiers = tuple(reversed(_tiers(symbol)))
    assert min(t.tier_id for t in tiers) == lowest_id
    got = await _one(_port(catalogue=_catalogue(**{symbol: tiers})), symbol)
    assert got.maintenance_margin_rate == D("0.0033")


@pytest.mark.parametrize(
    ("tickers", "symbol", "reason"),
    [(_QUOTED, "BTCUSDT", "maintenance_margin_rate"),  # BQ-7: tiers not cached, none fetched
     (None, "BTCUSDT", "no_reference_price"), (_QUOTED, "NOPEUSDT", "instrument")],
)  # fmt: skip
async def test_an_unknown_input_drops_the_liquidation_warning(
    tickers: _Tickers | None, symbol: str, reason: str
) -> None:
    save = await _port(catalogue=_catalogue(), tickers=tickers).figures(ACC, [symbol])
    p = profile("P-PCT", leverage="50", max_leverage_cap="50")
    found, dropped = pv.sizing_warnings(p, save, [symbol])
    assert found == ()
    assert ("stop_beyond_liquidation", reason) in {(d.code, d.reason) for d in dropped}


async def test_known_inputs_warn_stop_beyond_liquidation_and_drop_the_sizing_warning() -> None:
    """With tiers, price, instrument and equity known, a 50x profile's 2 % stop is beyond the
    estimate at BTCUSDT's lowest tier (0.0033); `sizing_below_min_order` drops as
    `figure_unknown`, as no fee, loss or committed-risk figure has a source (BQ-5)."""
    port = _port(catalogue=_catalogue(BTCUSDT=_tiers("BTCUSDT")))
    p = profile("P-PCT", leverage="50", max_leverage_cap="50")
    found, dropped = pv.sizing_warnings(p, await port.figures(ACC, ["BTCUSDT"]), ["BTCUSDT"])
    assert [(w.code, w.symbol, w.estimated) for w in found] == [
        ("stop_beyond_liquidation", "BTCUSDT", True)
    ]
    assert [(d.code, d.reason) for d in dropped] == [("sizing_below_min_order", "figure_unknown")]
