"""Composition-root binding (not a module) of the profile save's sizing warnings (E28-T02, #906
slice D2-m2; E28-T03 #907): `SaveTimeFigures`, the `SizingWarningsPort` over what the process
holds in memory, never fetched within the port's 0.25 s. Equity, its staleness and the available
margin are the wallet cache's; the instrument and the cached risk-limit tiers (the lowest by
`risk_limit_value`, never `tier_id == 1`; no `ensure_risk_limits`) the catalogue snapshot's; the
price the ticker's mid, else last, as `oms_wiring.ReferencePricesBinding` builds it, with no
ticker demand. No position read model is composed (`positions` is the seam), and the taker fee,
day's loss and committed risk have no source: `None`, so `sizing_below_min_order` drops as
`figure_unknown` (a residual, never an invented figure). D2-m3 wires it with the routes:
`SaveTimeFigures(account_health.wallets, lambda: ctx.ingestion.instruments,
lambda: ctx.ingestion.tickers)`."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from candleviewer.accounts.override_comparator import AccountFigures
from candleviewer.accounts.profile_validator import SaveFigures, SymbolFigures
from candleviewer.accounts.sizer import SizingMarket
from candleviewer.accounts.wallet import WalletView
from candleviewer.exchange.base.models import TickerEvent
from candleviewer.ingestion.instruments import CatalogueSnapshot

__all__ = ["Catalogue", "SaveTimeFigures", "Tickers", "Wallets"]


class Wallets(Protocol):
    """`accounts.wallet.WalletCache`'s read, or a fake."""

    def view(self, account_id: UUID) -> WalletView | None: ...


class Catalogue(Protocol):
    """`InstrumentsRefreshScheduler.snapshot`: the loaded catalogue, no I/O."""

    def snapshot(self) -> CatalogueSnapshot | None: ...


class Tickers(Protocol):
    """`ingestion.ticker_stream.TickerStream`'s reads."""

    def latest(self, symbol: str) -> TickerEvent | None: ...

    def is_stale(self, symbol: str) -> bool: ...


@dataclass(frozen=True, slots=True)
class SaveTimeFigures:
    """`SizingWarningsPort` over the wallet cache, the catalogue and the ticker stream; the last
    two are read per call, as they are attached late (and absent on the fake backend)."""

    wallets: Wallets | None
    catalogue: Callable[[], Catalogue | None]
    tickers: Callable[[], Tickers | None]
    #: BQ-3: E29-T05's position read model binds here; until then no symbol is held open.
    positions: Callable[[UUID], Awaitable[Sequence[str]]] | None = None

    async def open_symbols(self, account_id: UUID) -> Sequence[str]:
        """The symbols of the account's open positions; none while no read model is composed."""
        return () if self.positions is None else await self.positions(account_id)

    async def figures(self, account_id: UUID, symbols: Sequence[str]) -> SaveFigures:
        """The account's wallet figures and each symbol's instrument, price and rate."""
        view = None if self.wallets is None else self.wallets.view(account_id)
        wallet = None if view is None else view.snapshot
        equity = None if wallet is None or wallet.equity < 0 else wallet.equity
        figures = AccountFigures(
            equity=equity, available_margin=None if wallet is None else wallet.available_balance,
            # BQ-5: no fee tier off the order lane, no day's-loss source, no reservation ledger
            taker_fee_rate=None, realised_loss_today=None, committed_risk=None,
            open_positions_after=None, open_orders_after=None, orders_in_minute_after=None,
            maintenance_margin_rate=None,  # per symbol, below
        )  # fmt: skip
        scheduler = self.catalogue()
        snapshot = None if scheduler is None else scheduler.snapshot()
        tickers, stale = self.tickers(), view is not None and view.stale
        return SaveFigures(figures, stale, {s: _symbol(s, snapshot, tickers) for s in symbols})


def _symbol(symbol: str, snap: CatalogueSnapshot | None, tickers: Tickers | None) -> SymbolFigures:
    instrument = None if snap is None else snap.get(symbol)
    tiers = None if snap is None else snap.risk_limit_tiers(symbol)
    lowest = min(tiers, key=lambda t: t.risk_limit_value) if tiers else None
    mmr = None if lowest is None else lowest.maintenance_margin_rate
    return SymbolFigures(instrument, _market(symbol, tickers), mmr)


def _market(symbol: str, tickers: Tickers | None) -> SizingMarket:
    """`ReferencePricesBinding._price`, kept as mid or last (the warning's `estimated` differs);
    unlike it, a last price at or below 0 gives none, as `SizingMarket` refuses it."""
    ticker = None if tickers is None or tickers.is_stale(symbol) else tickers.latest(symbol)
    if ticker is None:
        return SizingMarket()
    bid, ask = ticker.bid1_price, ticker.ask1_price
    if bid is not None and ask is not None and _priced(bid) and _priced(ask):
        return SizingMarket(mid=(bid + ask) / 2)
    last = ticker.last_price
    return SizingMarket(last_price=last if last is not None and _priced(last) else None)


def _priced(price: Decimal) -> bool:
    return price.is_finite() and price > 0
