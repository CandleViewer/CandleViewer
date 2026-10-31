"""Composition-root wiring (not a module): liquidation history and its store (E24-T03, #667).

Only the composition root sees the store, the instruments cache and the order-flow service
together (C-3.1). The store is reached through `GuardedLiquidationStore`: until the hot tier is
started every read or write raises `StorageTierUnavailable` (the router's 503, the stream's
retried write, never a 500 or a dropped print). On the real backend the QuestDB store is built on
first use over the hot tier's own ILP writer and PGWire reader; the fake backend keeps an
in-memory one. The ingestion stream (`app.wire_public_ws`) writes through
`ctx.orderflow.liquidations`, so prints and history share this one store.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any

from candleviewer.domain.liquidations import LiqPrint
from candleviewer.orderflow.liquidations import LiquidationService, LiquidationStore
from candleviewer.storage.errors import StorageTierUnavailable

if TYPE_CHECKING:
    from candleviewer.app import AppContext


class GuardedLiquidationStore:
    """`LiquidationStore` that fails closed with `StorageTierUnavailable`."""

    def __init__(
        self,
        ctx: AppContext,
        inner: LiquidationStore | None,
        factory: Callable[[object], LiquidationStore | None] | None = None,
    ) -> None:
        self._ctx, self._inner, self._factory = ctx, inner, factory

    def _live(self) -> LiquidationStore:
        repo = self._ctx.storage.market_data  # raises StorageTierUnavailable until started
        if self._inner is None and self._factory is not None:
            self._inner = self._factory(repo)
        if self._inner is None:
            raise StorageTierUnavailable("no hot-tier liquidations client is wired")
        return self._inner

    async def write_prints(self, rows: Sequence[LiqPrint]) -> None:
        await self._live().write_prints(rows)

    async def read_prints(
        self, symbol: str, rng: Any, side: str | None, limit: int
    ) -> Sequence[LiqPrint]:
        return await self._live().read_prints(symbol, rng, side, limit)

    async def first_ts(self, symbol: str) -> int | None:
        return await self._live().first_ts(symbol)


def wire_liquidations(
    ctx: AppContext,
    *,
    store: LiquidationStore | None,
    store_factory: Callable[[object], LiquidationStore | None] | None = None,
) -> LiquidationService:
    """Attach `LiquidationService` to orderflow over the guarded store."""

    def _listed(symbol: str) -> bool | None:
        scheduler = ctx.ingestion.instruments
        snap = scheduler.snapshot() if scheduler is not None else None
        if snap is None:
            return None
        inst = snap.get(symbol)
        return inst is not None and inst.status == "trading"

    service = LiquidationService(
        store=GuardedLiquidationStore(ctx, store, store_factory), listed=_listed
    )
    ctx.orderflow.attach_liquidations(service)
    return service


__all__ = ["GuardedLiquidationStore", "wire_liquidations"]
