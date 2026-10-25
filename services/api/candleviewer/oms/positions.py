"""The position projection and the protection readings (E29-T05 #848, S5b; 24-internal-schemas.md
Sec.8.12, 21-database-schema.md Sec.3.3.7 "Writes"). Plain code on the hot-path contract (C-2.20):
`PositionProjection.take` is the private-stream consumer's `PositionRows` seam. One position row
upserts `positions` and, when it applied, appends a `ws_push` snapshot; its protection reading
goes to each live order that protects the position (the facade's `push_protection`), and to
`ProtectionReadings` when none took it, never dropped (C-2.6). A row dated ahead of the clock is
refused by the store: it gives no reading until it applies, so it is logged, counted, paged once
and held, then applied again at the account's next row (or `reapply`, on the clock's re-sync).

**The Partial-mode residual** (#4413): a stop held only by a Partial-mode order is not on the
position row, so its reading is `SL_LOST`: a live order in `sl_present` records it, and a position
no live order protects pages through `NoPositionProtection` once per episode, until E32-T02's B8
reads the orders.

**Bounds (C-2.18).** Every await is bounded on the monotonic clock: each store call and the
fallback `take_reading` by `PORT_TIMEOUT_S`; the readings by ONE `PUSH_TIMEOUT_S` deadline across
every protecting order's push; the fallback never draws on that deadline, so a hung push cannot
starve it. The held rows' re-apply shares ONE `REAPPLY_BOUND_S` deadline, every call of it inside;
a row whose reads that deadline ends is held again for a later take, never handed on as unprotected.
The worst case of one `take` is `TAKE_BUDGET_S` = re-apply 4 s + upsert 5 s + readings 30 s +
fallback 5 s + snapshot 5 s = 49 s, under the consumer's own 50 s bound on `take`. It raises
nothing but `CancelledError`, which would end the account's stream as a defect. Logs carry ids,
the symbol, a kind and an outcome only: never a price, a size or a PnL (C-12.6)."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any, Final, Literal, Protocol
from uuid import UUID

import structlog

from candleviewer.domain.primitives import AccountId
from candleviewer.exchange.base.models import Position
from candleviewer.storage.repositories.positions import (
    FutureDatedPositionError,
    NewPositionSnapshot,
    PositionRow,
    PositionSnapshotRow,
    PositionState,
)

from .errors import OrderStepUnknown, ProtectionReadingsUnavailable
from .ports import PositionKey, ProtectionReadings
from .push_mapping import ForProtection, reading_payload
from .stream_push import PORT_TIMEOUT_S, PUSH_TIMEOUT_S, Pager

MAX_REFUSED: Final = 256  # future-dated rows held, the latest per key, the oldest evicted
MAX_EPISODES: Final = 4096  # keys with a paged lost stop: the oldest dropped is a repeat page
MAX_REAPPLY_PER_TAKE: Final = 4
REAPPLY_BOUND_S: Final = 4.0  # one deadline across a take's re-applied rows
TAKE_BUDGET_S: Final = REAPPLY_BOUND_S + PORT_TIMEOUT_S + PUSH_TIMEOUT_S + 2 * PORT_TIMEOUT_S

type Outcome = Literal[
    "foreign_row", "invalid", "applied", "stale", "future_dated", "refused_evicted", "reapplied",
    "store_failed", "push_unknown", "push_failed", "to_protection", "reading_unavailable",
    "reading_failed", "snapshot_failed",
]  # fmt: skip
type _Stored = Literal["applied", "stale", "invalid", "failed", "dated"]

_EPOCH: Final = datetime(1970, 1, 1, tzinfo=UTC)
_SIDES: Final[Mapping[str | None, Literal["Buy", "Sell", "None"]]] = {
    "buy": "Buy", "sell": "Sell", None: "None"
}  # fmt: skip


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


class ProtectingOrders(Protocol):  # the facade, structurally
    def protecting(self, key: PositionKey) -> tuple[UUID, ...]: ...

    async def push_protection(
        self, account_id: UUID, order_id: UUID, event: str, payload: Mapping[str, Any]
    ) -> bool: ...


class PositionWrites(Protocol):
    async def upsert(self, state: PositionState) -> PositionRow: ...


class SnapshotWrites(Protocol):
    async def append(self, snapshot: NewPositionSnapshot) -> PositionSnapshotRow: ...


class PositionCounts(Protocol):
    def count(self, outcome: Outcome) -> None: ...  # sync; S8 binds a catalogue series


@dataclass(frozen=True, slots=True)
class _Held:
    position: Position
    route: ForProtection
    stored: bool = False  # its store step decided: only its reading is owed


class PositionProjection:
    def __init__(
        self, *, orders: ProtectingOrders, positions: PositionWrites, snapshots: SnapshotWrites,
        readings: ProtectionReadings, counts: PositionCounts, pager: Pager,
        monotonic: Callable[[], float],
    ) -> None:  # fmt: skip
        self._orders, self._positions, self._snapshots = orders, positions, snapshots
        self._readings, self._counts, self._pager, self._now = readings, counts, pager, monotonic
        self._held: OrderedDict[PositionKey, _Held] = OrderedDict()
        self._dated: OrderedDict[PositionKey, None] = OrderedDict()  # paged, not yet applied
        self._lost: OrderedDict[PositionKey, None] = OrderedDict()  # paged, no SL_OBSERVED since

    async def take(self, account_id: AccountId, position: Position, route: ForProtection) -> None:
        """One position row of the account's stream (24 Sec.8.12), in arrival order."""
        key = route.key
        if key.account_id != account_id or position.account_id != account_id:
            _log().error("position_foreign_row", stream_account_id=str(account_id), **_ids(key))
            self._count("foreign_row")  # defence in depth: the adapter binds rows per account
            return
        self._held.pop(key, None)  # this newer row supersedes a held one
        await self._reapply(account_id, MAX_REAPPLY_PER_TAKE)
        await self._apply(_Held(position, route), None)

    async def reapply(self, account_id: AccountId) -> None:
        """Every held row of the account, oldest first, under one deadline (S8 calls it on the
        clock's re-sync); a row it does not reach stays held."""
        await self._reapply(account_id, MAX_REFUSED)

    async def _reapply(self, account_id: AccountId, most: int) -> None:
        until = self._now() + REAPPLY_BOUND_S
        for key in [k for k in self._held if k.account_id == account_id][:most]:
            if self._now() >= until:
                return
            held = self._held.pop(key, None)
            if held is None:  # a newer row of the key took its place meanwhile
                continue
            try:
                handed = await self._apply(held, until)
            except asyncio.CancelledError:  # a cancel never drops a held row (C-2.6)
                self._held.setdefault(key, held)
                raise
            if handed:
                self._count("reapplied")

    async def _apply(self, held: _Held, until: float | None) -> bool:
        """Steps 3-7 for one row; True once its reading was handed on. A re-applied row whose
        reading was not is held again, its store step kept."""
        key, stored, applied = held.route.key, held.stored, False
        if not stored:
            outcome = await self._store(held.position, key, until)
            if outcome == "dated":  # C2: no reading, no snapshot until it applies
                self._hold(key, held)
                return False
            stored, applied = outcome != "failed", outcome == "applied"
            if until is not None and self._now() >= until:
                # the shared deadline is spent: no read at zero; the row is held again
                if applied:  # its `ws_push` snapshot is not appended again on the re-apply
                    self._count("snapshot_failed")
                self._hold(key, replace(held, stored=stored))
                return False
        handed = await self._read(held.route, until)
        if applied:
            await self._snapshot(held.position, key, until)
        if until is not None and not handed:
            self._hold(key, replace(held, stored=stored))
        return handed

    async def _store(self, p: Position, key: PositionKey, until: float | None) -> _Stored:
        try:
            state = _state(p)
        except Exception as exc:  # `check_fields`: the reading still goes (C-2.6)
            _log().error("position_invalid", kind=type(exc).__name__, **_ids(key))
            self._count("invalid")
            return "invalid"
        try:
            row = await self._bounded(self._positions.upsert(state), PORT_TIMEOUT_S, until)
        except FutureDatedPositionError:
            _log().error("position_future_dated", **_ids(key))
            self._count("future_dated")
            if key not in self._dated:  # once per key until it applies
                _latch(self._dated, key, MAX_REFUSED)
                self._page("a position push is dated ahead of the clock: clock fault")
            return "dated"
        except Exception as exc:  # a failure or the bound: the reading still goes
            _log().error("position_store_failed", kind=type(exc).__name__, **_ids(key))
            self._count("store_failed")
            return "failed"
        if row.exchange_updated_ts != state.exchange_updated_ts:
            self._count("stale")  # B1 judges the reading by exchange time itself (INV-B1-f)
            return "stale"
        self._dated.pop(key, None)
        self._count("applied")
        return "applied"

    async def _read(self, route: ForProtection, until: float | None) -> bool:
        """C3: each protecting order takes the reading under one deadline; none took it, then
        `ProtectionReadings` under its own bound. True once handed on."""
        key, value = route.key, route.reading
        if value.event == "SL_OBSERVED":  # the episode ends, wherever the reading goes
            self._lost.pop(key, None)
        payload = reading_payload(value)
        deadline = self._now() + self._left(PUSH_TIMEOUT_S, until)
        took = False
        for order_id in self._protecting(key):
            took = await self._push(key, order_id, value.event, payload, deadline) or took
        if took:
            return True
        if until is not None and self._now() >= until:
            # the shared re-apply deadline ended the pushes: the reading is owed to a live order,
            # so the row is held again, never handed to `ProtectionReadings` as unprotected
            return False
        self._count("to_protection")
        try:
            await self._bounded(self._readings.take_reading(key, value), PORT_TIMEOUT_S, until)
        except ProtectionReadingsUnavailable:
            _log().error("position_reading_unavailable", reading=value.event, **_ids(key))
            self._count("reading_unavailable")
            self._episode(key, value.event)
            return True
        except Exception as exc:  # fail closed: a lost stop no one took pages
            _log().error("position_reading_failed", kind=type(exc).__name__, **_ids(key))
            self._count("reading_failed")
            self._episode(key, value.event)
            return False
        return True

    def _protecting(self, key: PositionKey) -> tuple[UUID, ...]:
        try:
            return self._orders.protecting(key)
        except Exception as exc:
            _log().error("position_push_failed", kind=type(exc).__name__, **_ids(key))
            self._count("push_failed")
            return ()

    async def _push(
        self, key: PositionKey, order_id: UUID, event: str, payload: Mapping[str, Any],
        deadline: float,
    ) -> bool:  # fmt: skip
        for attempt in (1, 2):  # an unknown outcome is delivered once more (24 Sec.8.12)
            try:
                async with asyncio.timeout(max(deadline - self._now(), 0.0)):
                    return await self._orders.push_protection(
                        key.account_id, order_id, event, payload
                    )
            except OrderStepUnknown:
                if attempt == 2:
                    _log().error("position_push_unknown", order_id=str(order_id), **_ids(key))
                    self._count("push_unknown")
            except Exception as exc:  # refused, illegal, an anomaly, the deadline: not taken
                kind = type(exc).__name__
                _log().error("position_push_failed", kind=kind, order_id=str(order_id), **_ids(key))
                self._count("push_failed")
                return False
        return False

    async def _snapshot(self, p: Position, key: PositionKey, until: float | None) -> None:
        try:
            snap = NewPositionSnapshot(
                exchange_account_id=p.account_id, symbol=p.symbol, size=p.qty, reason="ws_push",
                position_idx=p.position_idx, avg_price=p.avg_entry_price, mark_price=p.mark_price,
                unrealised_pnl=p.unrealised_pnl, cum_realised_pnl=p.cum_realised_pnl,
                liq_price=p.liq_price,
            )  # fmt: skip
            await self._bounded(self._snapshots.append(snap), PORT_TIMEOUT_S, until)
        except Exception as exc:
            _log().error("position_snapshot_failed", kind=type(exc).__name__, **_ids(key))
            self._count("snapshot_failed")

    def _hold(self, key: PositionKey, held: _Held) -> None:
        self._held.pop(key, None)
        self._held[key] = held
        if len(self._held) > MAX_REFUSED:
            old, _ = self._held.popitem(last=False)
            _log().error("position_refused_evicted", **_ids(old))
            self._count("refused_evicted")

    def _episode(self, key: PositionKey, event: str) -> None:
        if event == "SL_LOST" and key not in self._lost:  # P1, once per episode
            _latch(self._lost, key, MAX_EPISODES)
            self._page("a position lost its stop and no machine protects it")

    def _left(self, seconds: float, until: float | None) -> float:
        return max(seconds if until is None else min(seconds, until - self._now()), 0.0)

    async def _bounded[T](self, call: Awaitable[T], seconds: float, until: float | None) -> T:
        async with asyncio.timeout(self._left(seconds, until)):
            return await call

    def _count(self, outcome: Outcome) -> None:
        try:
            self._counts.count(outcome)
        except Exception as exc:
            _log().error("position_count_failed", kind=type(exc).__name__, outcome=outcome)

    def _page(self, summary: str) -> None:
        try:
            self._pager.raise_alert("page", summary, machine_kind="oms.positions")
        except Exception as exc:
            _log().error("position_page_failed", kind=type(exc).__name__)


def _state(p: Position) -> PositionState:
    """The `positions` row of a pushed position; the stamp from integer microseconds."""
    return PositionState(
        exchange_account_id=p.account_id, symbol=p.symbol, size=p.qty,
        position_idx=p.position_idx, side=_SIDES[p.side], avg_price=p.avg_entry_price,
        leverage=p.leverage, mark_price=p.mark_price, liq_price=p.liq_price,
        unrealised_pnl=p.unrealised_pnl, cum_realised_pnl=p.cum_realised_pnl,
        take_profit=p.take_profit, stop_loss=p.stop_loss, trailing_stop=p.trailing_stop_distance,
        exchange_updated_ts=_EPOCH + timedelta(microseconds=p.updated_at),
    )  # fmt: skip


def _latch(keys: OrderedDict[PositionKey, None], key: PositionKey, cap: int) -> None:
    keys[key] = None
    if len(keys) > cap:
        keys.popitem(last=False)


def _ids(key: PositionKey) -> dict[str, object]:  # ids and the symbol only (C-12.6)
    return {
        "account_id": str(key.account_id), "symbol": key.symbol, "position_idx": key.position_idx
    }  # fmt: skip
