"""The venue cancel-all fold's port (E29-T04 #913 slice 4, S4-F; 24 Sec.8.7 "Cancel-all"; the
orchestrator's ruling of 2026-10-24 21:11Z, Q1 (a) and Q3).

`CancelAllCoalescer` wraps an environment's trading port where the wiring builds the OMS's
`TradingRouter`, so B1's command port and S4-C's exit service are unchanged: every call passes
through as it is but a fold member's `cancel_order`, which meets its fold's `CancelAllJoin`.

- **Coverage** (`coverage`): a `poll`-lane `open_orders(account, symbol)` read, never the
  `critical` lane's budget (Q3), shows whether every plain order resting on the symbol is among the
  fold's members (`covers`). A read that fails, or that shows one more, keeps the symbol on
  per-order cancels.
- **A fold** (`fold`, a context manager): its members' `cancel_order` calls meet the join while it
  is open. Each arrives only once its own B1 `CANCEL` is written ahead, as the command port calls
  `cancel_order` only then (C-2.9). Once every member has arrived, one venue `cancel-all` leaves,
  behind the per-UID spacer (`order.cancel_all`, 1/s per UID), and answers each member by its own
  ack; a member the acks do not name sends its own cancel, and so does every member of a fold that
  is abandoned (a member that never arrives, the gather's bound, a spacer slot past its wait).
- **The residual** (named for the security look, as ruled): an order placed on the symbol between
  the coverage read and the venue call is cancelled by the venue's call too, with no B1 `CANCEL`
  of its own; B1 learns of it from the private stream and reconciliation, as of any cancel it did
  not send (24 Sec.8.6). The window is the gather's bound plus the spacer's wait, at most
  `GATHER_S + SPACER_WAIT_S`.

One event loop's, as the order lanes are. Nothing here imports the exchange adapter (C-2.2).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Collection, Iterator, Sequence
from contextlib import contextmanager
from decimal import Decimal
from typing import Any, Final

import structlog

from candleviewer.domain.primitives import AccountId, OrderLinkId, Symbol, TsUs
from candleviewer.exchange.base.models import (
    AccountInfo,
    AccountRef,
    AmendOrderRequest,
    CancelOrderRequest,
    ClosedPnl,
    Execution,
    FeeRate,
    Order,
    OrderAck,
    PlaceOrderRequest,
    Position,
    RateHeadroom,
    RateLane,
    TradingStopRequest,
    Wallet,
)
from candleviewer.exchange.base.ports import PrivateStream

from .cancel_all_fold import GATHER_S, CancelAllJoin, CancelAllSpacer, covers
from .routing import RoutedPort

__all__ = ["SPACER_WAIT_S", "CancelAllCoalescer"]

#: How long a fold's call may wait for its UID's spacer slot before the fold is abandoned: a slot
#: further off leaves the members to their own cancels, inside their 9 s (24 Sec.8.7).
SPACER_WAIT_S: Final = 2.0


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


class CancelAllCoalescer:
    """An environment's `RoutedPort` with the fold's meeting point (module docstring)."""

    def __init__(
        self,
        inner: RoutedPort,
        *,
        spacer: CancelAllSpacer,
        monotonic: Callable[[], float],
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        gather_s: float = GATHER_S,
        spacer_wait_s: float = SPACER_WAIT_S,
    ) -> None:
        self.capabilities = inner.capabilities
        self._inner, self._spacer = inner, spacer
        self._monotonic, self._sleep = monotonic, sleep
        self._gather_s, self._spacer_wait_s = gather_s, spacer_wait_s
        self._joins: dict[tuple[AccountId, str], CancelAllJoin] = {}

    async def coverage(self, account: AccountRef, symbol: Symbol, members: Collection[str]) -> bool:
        """Whether the venue's cancel-all may fold `symbol`'s cancels (Q3); False when the read
        fails, so the symbol stays on per-order cancels."""
        try:
            resting = await self._inner.open_orders(account, symbol)
        except Exception as exc:  # no proof of coverage: the fail-safe
            _log().warning("oms_cancel_all_coverage_unread", failure=type(exc).__name__)
            return False
        return covers(resting, members)

    @contextmanager
    def fold(
        self, account: AccountRef, symbol: Symbol, members: Collection[str]
    ) -> Iterator[CancelAllJoin]:
        """The members' join while the block runs: each member's `cancel_order` meets it. A member
        already in another open fold is refused (`ValueError`): one order meets one fold."""
        keys = [(account.account_id, link) for link in members]
        if any(key in self._joins for key in keys):
            raise ValueError("an order is already a member of an open fold")

        async def send() -> Sequence[OrderAck] | None:
            deadline = self._monotonic() + self._spacer_wait_s
            if not await self._spacer.turn(account.uid, deadline=deadline):
                _log().warning("oms_cancel_all_slot_refused", symbol=symbol)
                return None
            return await self._inner.cancel_all(account, symbol)

        join = CancelAllJoin(
            members, send, monotonic=self._monotonic, sleep=self._sleep, gather_s=self._gather_s
        )
        for key in keys:
            self._joins[key] = join
        try:
            yield join
        finally:
            for key in keys:
                if self._joins.get(key) is join:
                    del self._joins[key]

    async def cancel_order(self, req: CancelOrderRequest) -> OrderAck:
        """A fold member's cancel meets its join; any other, or a member the fold leaves to its own
        cancel, goes to the venue as it is."""
        link = req.order_link_id
        join = None if link is None else self._joins.get((req.account.account_id, link))
        if join is not None and link is not None:
            ack = await join.arrive(link)
            if ack is not None:
                return ack
        return await self._inner.cancel_order(req)

    # --- every other call passes through as it is ----------------------------------------------

    def headroom(self, account: AccountRef, lane: RateLane) -> RateHeadroom:
        return self._inner.headroom(account, lane)

    async def place_order(self, req: PlaceOrderRequest) -> OrderAck:
        return await self._inner.place_order(req)

    async def place_batch(self, reqs: Sequence[PlaceOrderRequest]) -> Sequence[OrderAck]:
        return await self._inner.place_batch(reqs)

    async def amend_order(self, req: AmendOrderRequest) -> OrderAck:
        return await self._inner.amend_order(req)

    async def cancel_all(self, account: AccountRef, symbol: Symbol | None) -> Sequence[OrderAck]:
        return await self._inner.cancel_all(account, symbol)

    async def set_trading_stop(self, req: TradingStopRequest) -> OrderAck:
        return await self._inner.set_trading_stop(req)

    async def set_leverage(self, account: AccountRef, symbol: Symbol, leverage: Decimal) -> None:
        await self._inner.set_leverage(account, symbol, leverage)

    async def open_orders(
        self,
        account: AccountRef,
        symbol: Symbol | None = None,
        *,
        order_link_id: OrderLinkId | None = None,
    ) -> Sequence[Order]:
        return await self._inner.open_orders(account, symbol, order_link_id=order_link_id)

    async def order_history(
        self,
        account: AccountRef,
        *,
        order_link_id: OrderLinkId | None = None,
        exchange_order_id: str | None = None,
        start: TsUs | None = None,
        end: TsUs | None = None,
    ) -> Sequence[Order]:
        return await self._inner.order_history(
            account, order_link_id=order_link_id, exchange_order_id=exchange_order_id,
            start=start, end=end,
        )  # fmt: skip

    async def positions(self, account: AccountRef) -> Sequence[Position]:
        return await self._inner.positions(account)

    async def executions(self, account: AccountRef, start: TsUs, end: TsUs) -> Sequence[Execution]:
        return await self._inner.executions(account, start, end)

    async def closed_pnl(self, account: AccountRef, start: TsUs, end: TsUs) -> Sequence[ClosedPnl]:
        return await self._inner.closed_pnl(account, start, end)

    async def wallet(self, account: AccountRef) -> Wallet:
        return await self._inner.wallet(account)

    async def fee_rate(self, account: AccountRef, symbol: Symbol) -> FeeRate:
        return await self._inner.fee_rate(account, symbol)

    async def account_info(self, account: AccountRef) -> AccountInfo:
        return await self._inner.account_info(account)

    async def subscribe_private(self, account: AccountRef) -> PrivateStream:
        return await self._inner.subscribe_private(account)
