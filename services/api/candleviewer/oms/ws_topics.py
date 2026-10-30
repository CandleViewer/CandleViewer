"""The `orders`, `executions` and `positions` WS topics (E29-T13, #4207; 23-ws-protocol.md Sec.6.2,
Sec.6.2.3, Sec.15.1 to Sec.15.3 and Sec.16.1 S4, S5; 24-internal-schemas.md Sec.8.12): the OMS's
snapshot sources for the three families, and the deltas its committed steps and applied position
rows publish.

`oms` may not import `ws` (M14, CONSTITUTION Sec.3), so the topics are typed structurally, as
`accounts/wallet_topic.py` is: a subscription by the fields read here, the gateway's body
constructor and the hub's `publish`, `flush_pending` and `resnapshot` injected with
`PRIVATE_CAUSAL_ORDER` (`ws_wiring.oms_topics`). The OMS runs on the order lane and the hub on the
serving loop (29 CV-C13), so the topics have a half on each:

- **The lane's (`StepPublisher`).**
  - Sources: each order step once its write commits (`OrderStepWriter`'s `on_commit`), with the
    row as it then stands, so every step is a frame of its own, a second partial fill included
    (S4); and each position row the store applied (`PublishedPositions`, the projection's store).
  - It builds the Sec.15 items there and hands them to the serving loop (`Serving.notify`, never
    awaited, in call order).
  - A fill's frame waits for its execution row, read back for its `id` (`FILL_READ_S`), and the
    account's later steps queue behind it (`QUEUE_MAX`), so an account's frames leave in commit
    order: the execution before its order (S5).
  - A position waits in the account's hold while a fill of its key is unpublished: one the facade
    holds before its order's bind (`OrderMachines.held_fills`), or one awaiting its read. It leaves
    right after the last of them. Past `HOLD_S`, or with `HOLD_MAX` keys already held, it leaves at
    once, counted (`oms_ws_position_overtakes_total`); a later row of a held key replaces the
    earlier (Sec.8.2: whole object, last write wins).
- **The serving loop's (`OmsTopics`).**
  - It publishes each item in `PRIVATE_CAUSAL_ORDER` through `publish(..., account=)`, so only a
    subscription holding the item's account, whose principal holds the family's permission, gets
    it (C-12.4), narrowed to its `symbols`.
  - Its snapshots are per (family, account) views read on the lane (`TopicReads`): `orders` the
    open ones, `positions` the open ones, `executions` the newest `SNAPSHOT_FILLS`. They are
    loaded beside the subscription, which stays `snapshot_pending` until its accounts' views land
    (Sec.7.7), as `alerts`' are. Private: never cached by the gateway (generation 0), no
    continuity (Sec.7.6).

**One clock for both halves.** `LaneClock` stamps each delta at its commit and each snapshot read at
its start, never going back, on the lane only:
- a delta older than a snapshot carries an older `updated_at_ms`, which Sec.15's rule discards;
- a view is dropped by a delta stamped at or after its read;
- a load a delta raced (stamped at or after its read's start, so maybe missing from it) reads again,
  `LOAD_ROUNDS` times, then serves and re-snapshots.

**Failure.** The topics are a view: nothing here is awaited by a step or a projection, and nothing
raises into one. What fails is logged by its class with ids only (C-12.6), and a change that cannot
be published re-snapshots its account's subscriptions with `upstream_desync` (Sec.7.4), so a client
never silently misses one:
- a fill whose read fails sends its order's frame alone and re-snapshots `executions`;
- a full queue drops the account's queue and re-snapshots all three topics.
Hot-path rule (C-2.20): plain code; nothing queries an interpreter.
"""

from __future__ import annotations

import asyncio
import random
from collections import OrderedDict, deque
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Final, Literal, Protocol
from uuid import UUID

import structlog

from candleviewer.domain.primitives import AccountId
from candleviewer.observability import spawn
from candleviewer.storage.repositories.executions import MAX_RECENT, ExecutionRow
from candleviewer.storage.repositories.orders import OPEN_STATES, OrderRow
from candleviewer.storage.repositories.positions import PositionRow, PositionState

from .order_steps import CommittedOrderStep
from .ports import PositionKey
from .positions import PositionWrites
from .push_mapping import money_text

ORDERS: Final = "orders"
EXECUTIONS: Final = "executions"
POSITIONS: Final = "positions"
type Family = Literal["orders", "executions", "positions"]
#: The three families, in Sec.16.1 S5's order (`ws_wiring` passes `PRIVATE_CAUSAL_ORDER` itself).
FAMILIES: Final[tuple[Family, ...]] = (EXECUTIONS, ORDERS, POSITIONS)
#: A fill's execution row is read back for its `id`, at most this long; past it, or on a failure,
#: its order's frame goes alone and the account's `executions` subscriptions re-snapshot.
FILL_READ_S: Final = 2.0
#: How long a position waits for the unpublished fills of its key before it leaves anyway, counted.
HOLD_S: Final = 1.0
#: Position keys one account holds at once; a position finding the hold full leaves at once,
#: counted.
HOLD_MAX: Final = 64
#: Steps one account queues behind a fill's read; one more drops the queue and re-snapshots the
#: account's three topics (C-2.18).
QUEUE_MAX: Final = 256
#: The `executions` snapshot's fills (Sec.6.2: "Last 100 fills"), across the subscription's
#: accounts.
SNAPSHOT_FILLS: Final = MAX_RECENT
#: (family, account) views kept, least recently used dropped first; loads running at once.
MAX_VIEWS: Final = 1024
LOADS_MAX: Final = 4
#: A load a delta raced reads again at most this often, then serves what it read and re-snapshots.
LOAD_ROUNDS: Final = 3
#: A load whose read fails is tried this often in all, `LOAD_BACKOFF_S` doubled per try, jittered.
LOAD_TRIES: Final = 3
LOAD_BACKOFF_S: Final = 0.5
#: The counted overtake: a position published past its hold's bound (20 Sec.12.1; no label).
OVERTAKES: Final = "oms_ws_position_overtakes_total"
#: Sec.15.3's `exec_type`: a row of any other type is in no frame.
WS_EXEC_TYPES: Final = frozenset({"Trade", "AdlTrade", "Funding", "BustTrade", "Settle"})

_EPOCH: Final = datetime(1970, 1, 1, tzinfo=UTC)
_SIDES: Final[Mapping[str, str]] = {"Buy": "buy", "Sell": "sell"}
_ORDER_TYPES: Final[Mapping[str, str]] = {"Market": "market", "Limit": "limit"}
_DIRECTIONS: Final[Mapping[int, str]] = {1: "rise", 2: "fall"}
#: Sec.15.1's `change`, by the step's event kind; `exchange_push` is told apart by its states.
_CHANGES: Final[Mapping[str, str]] = {
    "local_create": "created", "submit_attempt": "submitted", "ack": "ack", "reject": "reject",
    "fill": "fill", "partial_fill": "fill", "amend_request": "amend", "amend_ack": "amend",
    "cancel_request": "cancel", "cancel_ack": "cancel", "kill": "cancel", "expire": "expire",
    "reconcile_diff": "reconcile", "adopt": "reconcile",
}  # fmt: skip
#: Position fields Sec.15.2 types as a decimal, never null: sent only when the row holds one.
_POSITION_AMOUNTS: Final = (
    "avg_price", "mark_price", "position_value", "leverage", "unrealised_pnl", "trailing_stop",
)  # fmt: skip


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


def epoch_ms(at: datetime) -> int:
    """`at` (aware) as Sec.13's `epochMs`, exactly."""
    return (at - _EPOCH) // timedelta(milliseconds=1)


def _money(value: Decimal | None) -> str | None:
    return None if value is None else money_text(value)


def _uuid_text(value: UUID | None) -> str | None:
    return None if value is None else str(value)


def change_of(step: CommittedOrderStep) -> str | None:
    """Sec.15.1's `change` for the step: by its event kind, and for an `exchange_push` by its
    states (a first row is `created`, an end `cancel`, a terms step `amend`, a trigger none)."""
    if step.kind != "exchange_push":
        return _CHANGES.get(step.kind)
    if step.from_state is None:
        return "created"
    if step.order.state == "cancelled":
        return "cancel"
    return "amend" if step.order.state == step.from_state else None


def order_item(
    row: OrderRow, *, environment: str, stamp: int, change: str | None = None
) -> dict[str, Any]:
    """One Sec.15.1 item: the row's columns, nothing derived (`trade_group_id` and `algo_kind`
    are not on the row, so they are left out); `rejected_reason` is the reject code, never the
    exchange's text."""
    item: dict[str, Any] = {
        "id": str(row.id), "exchange_account_id": str(row.exchange_account_id),
        "trade_group_leg_id": _uuid_text(row.trade_group_leg_id),
        "parent_order_id": _uuid_text(row.parent_order_id), "order_link_id": row.order_link_id,
        "exchange_order_id": row.exchange_order_id, "symbol": row.symbol,
        "side": _SIDES[row.side], "order_type": _ORDER_TYPES[row.order_type],
        "intent": row.intent, "state": row.state, "lifecycle_state": row.lifecycle_state,
        "qty": money_text(row.qty), "filled_qty": money_text(row.cum_exec_qty),
        "remaining_qty": money_text(row.leaves_qty), "price": _money(row.price),
        "avg_fill_price": _money(row.avg_price), "time_in_force": row.time_in_force,
        "reduce_only": row.reduce_only, "close_on_trigger": row.close_on_trigger,
        "position_idx": row.position_idx, "trigger_price": _money(row.trigger_price),
        "trigger_by": row.trigger_by,
        "trigger_direction": _DIRECTIONS.get(row.trigger_direction or 0),
        "take_profit": _money(row.take_profit), "stop_loss": _money(row.stop_loss),
        "tpsl_mode": row.tpsl_mode, "environment": environment, "is_paper": row.is_paper,
        "rejected_reason": row.reject_code, "updated_at_ms": stamp,
    }  # fmt: skip
    if change is not None:
        item["change"] = change
    return item


def execution_item(row: ExecutionRow, *, environment: str) -> dict[str, Any] | None:
    """One Sec.15.3 item, or None for a row no frame carries: one of no order (`order_id` is
    required) or of a type outside Sec.15.3's."""
    if row.order_id is None or row.exec_type not in WS_EXEC_TYPES:
        return None
    item: dict[str, Any] = {
        "id": str(row.id), "exec_id": row.exec_id, "order_id": str(row.order_id),
        "exchange_account_id": str(row.exchange_account_id), "symbol": row.symbol,
        "side": _SIDES[row.side], "exec_qty": money_text(row.exec_qty),
        "exec_price": money_text(row.exec_price), "exec_value": money_text(row.exec_value),
        "fee": money_text(row.exec_fee), "fee_coin": row.fee_currency, "is_maker": row.is_maker,
        "exec_type": row.exec_type, "environment": environment, "is_paper": row.is_paper,
        "ts_ms": epoch_ms(row.exec_ts),
    }  # fmt: skip
    if row.fee_rate is not None:
        item["fee_rate"] = money_text(row.fee_rate)
    if row.closed_pnl is not None:
        item["exec_pnl"] = money_text(row.closed_pnl)
    return item


def is_flat(row: PositionState) -> bool:
    return row.size == 0 or row.side in (None, "None")


def position_item(row: PositionRow, *, environment: str, stamp: int) -> dict[str, Any]:
    """One Sec.15.2 item. `native_stop_present`, `margin_mode`, `realised_pnl_session`,
    `trade_group_id` and `r_multiple` are left out: the row cannot tell them (a stop held by a
    Partial-mode order is on no position row, 24 Sec.8.12)."""
    side = "flat" if is_flat(row) else ("long" if row.side == "Buy" else "short")
    item: dict[str, Any] = {
        "id": str(row.id), "exchange_account_id": str(row.exchange_account_id),
        "symbol": row.symbol, "side": side, "position_idx": row.position_idx,
        "size": money_text(row.size), "liq_price": _money(row.liq_price),
        "bust_price": _money(row.bust_price), "take_profit": _money(row.take_profit),
        "stop_loss": _money(row.stop_loss), "environment": environment, "is_paper": row.is_paper,
        "updated_at_ms": stamp,
    }  # fmt: skip
    for name in _POSITION_AMOUNTS:
        if (value := getattr(row, name)) is not None:
            item[name] = money_text(value)
    if row.tpsl_mode is not None:
        item["tpsl_mode"] = row.tpsl_mode
    return item


class LaneClock:
    """Epoch milliseconds on the OMS's clock, never going back: one instance stamps every delta at
    its commit and every snapshot read at its start, on the order lane alone (module docstring)."""

    def __init__(self, now: Callable[[], datetime]) -> None:
        self._now, self._last = now, 0

    def __call__(self) -> int:
        self._last = max(self._last, epoch_ms(self._now()))
        return self._last


@dataclass(frozen=True, slots=True)
class Change:
    """One item for the serving loop: its family, the Sec.15 item, the entity's id and symbol, its
    stamp, and whether it leaves the live view (an order out of the open set, a flat position)."""

    family: Family
    item: Mapping[str, Any]
    key: str
    symbol: str
    stamp: int
    closed: bool = False


@dataclass(frozen=True, slots=True)
class View:
    """One family's rows of one account as read on the lane, built into Sec.15 items, and the
    stamp of the read's start (`LaneClock`), which each item's `updated_at_ms` carries."""

    stamp: int
    items: tuple[Mapping[str, Any], ...]


# -- the lane's half --------------------------------------------------------------------------


class Changes(Protocol):
    """`OmsTopics` as the lane reaches it, each call made on the serving loop (`Notify`)."""

    def published(self, account: UUID, changes: Sequence[Change]) -> None: ...

    def resync(self, account: UUID, families: Iterable[Family]) -> None: ...


class Notify(Protocol):
    """`oms_lane.Serving.notify`: `fn(*args)` called on the serving loop, in call order, never
    awaited; what it raises there is logged and counted, never seen here."""

    def __call__(self, fn: Callable[..., object], /, *args: Any) -> None: ...


class FillRows(Protocol):
    """`ExecutionRepository.get`, on the lane: a committed fill's row, for its `id`."""

    async def get(self, account_id: UUID, exec_id: str) -> ExecutionRow | None: ...


def _no_fills(key: PositionKey) -> frozenset[str]:
    return frozenset()


@dataclass(frozen=True, slots=True)
class _Queued:
    stamp: int
    step: CommittedOrderStep


@dataclass(slots=True)
class _Held:
    """A held position: its latest change, the `exec_id`s it waits for, its deadline (the loop's
    time, kept from the key's first hold)."""

    change: Change
    awaited: set[str]
    deadline: float


class StepPublisher:
    """The lane's half (module docstring), for the order lane's loop alone: no locks. `committed`
    is the step writer's `on_commit` and `position` the store's applied rows (`PublishedPositions`);
    neither blocks, and neither raises past its own containment. `bind` takes the facade's read of
    the fills a position's orders hold before their bind, once the facade exists."""

    def __init__(
        self, topics: Changes, notify: Notify, fills: FillRows, *, environment: str,
        clock: LaneClock, overtaken: Callable[[], None], fill_read_s: float = FILL_READ_S,
        hold_s: float = HOLD_S, hold_max: int = HOLD_MAX, queue_max: int = QUEUE_MAX,
    ) -> None:  # fmt: skip
        self._topics, self._notify, self._fills = topics, notify, fills
        self._env, self._clock, self._overtaken = environment, clock, overtaken
        self._fill_read_s, self._hold_s = fill_read_s, hold_s
        self._hold_max, self._queue_max = hold_max, queue_max
        self._held_fills: Callable[[PositionKey], frozenset[str]] = _no_fills
        #: Per account: the steps behind a fill's read, in commit order, and the task draining them.
        self._queues: dict[UUID, deque[_Queued]] = {}
        self._drains: dict[UUID, asyncio.Task[None]] = {}
        #: Per account: the committed fills not yet published, by `exec_id`, with their position.
        self._unpublished: dict[UUID, dict[str, PositionKey]] = {}
        #: Per account: the held positions by key, and the timer of the earliest deadline.
        self._holds: dict[UUID, dict[PositionKey, _Held]] = {}
        self._timers: dict[UUID, asyncio.TimerHandle] = {}
        self._closed = False

    def bind(self, held_fills: Callable[[PositionKey], frozenset[str]]) -> None:
        """The facade's `held_fills`, read at each position (a plain-view read, C-2.20)."""
        self._held_fills = held_fills

    # -- the order steps

    def committed(self, step: CommittedOrderStep) -> None:
        """A step whose write committed: its frames now, or behind its account's queue while a
        fill's read is pending there; a fill always waits for its read. A full queue drops it."""
        if self._closed:
            return
        account, queued = step.order.exchange_account_id, _Queued(self._clock(), step)
        queue = self._queues.get(account)
        if queue is None and step.fill is None:
            self._send(account, self._order_changes(queued))
            return
        if queue is not None and len(queue) >= self._queue_max:
            self._overflow(account)
            return
        if queue is None:
            queue = self._queues[account] = deque()
        queue.append(queued)
        if step.fill is not None:
            row = step.order
            key = PositionKey(AccountId(account), row.symbol, row.position_idx)
            self._unpublished.setdefault(account, {})[step.fill.exec_id] = key
        if account not in self._drains:
            self._drains[account] = spawn(self._drain(account, queue), name="oms-ws-steps")

    async def _drain(self, account: UUID, queue: deque[_Queued]) -> None:
        """The account's queue in commit order: a fill's frames once its row is read, every step
        behind it in turn. It ends once the queue is empty; an overflow or `aclose` cancels it."""
        try:
            while queue:
                queued = queue[0]
                changes = await self._changes(account, queued)
                queue.popleft()
                self._send(account, changes)
                if queued.step.fill is not None:
                    self._fill_out(account, queued.step.fill.exec_id)
        finally:
            if self._drains.get(account) is asyncio.current_task():
                del self._drains[account]
            if self._queues.get(account) is queue and not queue:
                del self._queues[account]

    async def _changes(self, account: UUID, queued: _Queued) -> tuple[Change, ...]:
        """The step's order change, its execution's first for a fill (S5). A fill whose row cannot
        be read goes without it, and the account's `executions` subscriptions re-snapshot."""
        orders = self._order_changes(queued)
        step = queued.step
        if step.fill is None:
            return orders
        row = await self._read(account, step.order.id, step.fill.exec_id)
        item = None if row is None else execution_item(row, environment=self._env)
        if row is None or item is None:
            self._call(self._topics.resync, account, (EXECUTIONS,))
            return orders
        return (Change(EXECUTIONS, item, str(row.id), row.symbol, queued.stamp), *orders)

    async def _read(self, account: UUID, order_id: UUID, exec_id: str) -> ExecutionRow | None:
        """The fill's row within `FILL_READ_S`, or None: a failure, the bound, or a row that is not
        this order's in this account (a store defect, C-12.4). Logged by ids and class only."""
        ids = {"account_id": str(account), "order_id": str(order_id), "exec_id": exec_id}
        try:
            async with asyncio.timeout(self._fill_read_s):
                row = await self._fills.get(account, exec_id)
        except Exception as exc:  # a failure or the bound, never a cancellation
            _log().warning("oms_ws_fill_unread", error=type(exc).__name__, **ids)
            return None
        if row is None or row.exchange_account_id != account or row.order_id != order_id:
            _log().warning("oms_ws_fill_unread", error="not_found", **ids)
            return None
        return row

    def _order_changes(self, queued: _Queued) -> tuple[Change, ...]:
        row, stamp = queued.step.order, queued.stamp
        item = order_item(row, environment=self._env, stamp=stamp, change=change_of(queued.step))
        closed = row.state not in OPEN_STATES
        return (Change(ORDERS, item, str(row.id), row.symbol, stamp, closed),)

    # -- the positions

    def position(self, row: PositionRow) -> None:
        """A position row the store applied: published now, unless a fill of its key is still
        unpublished; then held until the last of them is out, or its bound passes."""
        if self._closed:
            return
        account, stamp = row.exchange_account_id, self._clock()
        key = PositionKey(AccountId(account), row.symbol, row.position_idx)
        item = position_item(row, environment=self._env, stamp=stamp)
        change = Change(POSITIONS, item, str(row.id), row.symbol, stamp, is_flat(row))
        awaited = self._awaited(account, key)
        holds = self._holds.get(account, {})
        held = holds.get(key)
        if held is None and not awaited:
            self._send(account, (change,))
            return
        if held is None and len(holds) >= self._hold_max:
            self._overtake(account, change, "hold_full")
            return
        if held is None:
            due = asyncio.get_running_loop().time() + self._hold_s
            self._holds.setdefault(account, holds)[key] = _Held(change, awaited, due)
        else:  # the later row of the key replaces the earlier, and waits for both's fills
            held.change = change
            held.awaited |= awaited
        self._arm(account)

    def _awaited(self, account: UUID, key: PositionKey) -> set[str]:
        """The unpublished fills of `key`: those the facade holds before their bind, and those
        committed and not yet out. A facade read that raises counts as none (logged)."""
        try:
            held = set(self._held_fills(key))
        except Exception as exc:  # the position still goes; it waits for the committed ones
            error = type(exc).__name__
            _log().error("oms_ws_held_fills_failed", account_id=str(account), error=error)
            held = set()
        pending = self._unpublished.get(account, {})
        return held | {exec_id for exec_id, of in pending.items() if of == key}

    def _fill_out(self, account: UUID, exec_id: str) -> None:
        """A fill's frames are out: the positions waiting for it alone follow now."""
        pending = self._unpublished.get(account)
        if pending is not None:
            pending.pop(exec_id, None)
            if not pending:
                del self._unpublished[account]
        holds = self._holds.get(account)
        if not holds:
            return
        ready: list[Change] = []
        for key, held in list(holds.items()):
            held.awaited.discard(exec_id)
            if not held.awaited:
                ready.append(holds.pop(key).change)
        if ready:
            self._send(account, tuple(ready))
        if not holds:
            self._unhold(account)

    def _arm(self, account: UUID) -> None:
        """The account's timer, at its earliest held deadline (one timer an account)."""
        holds = self._holds.get(account)
        if account in self._timers or not holds:
            return
        due = min(held.deadline for held in holds.values())
        loop = asyncio.get_running_loop()
        self._timers[account] = loop.call_at(due, self._expire, account)

    def _expire(self, account: UUID) -> None:
        """The timer: each held position past its deadline leaves now, counted (`HOLD_S`)."""
        self._timers.pop(account, None)
        holds = self._holds.get(account)
        if not holds:
            return
        now = asyncio.get_running_loop().time()
        for key in [key for key, held in holds.items() if held.deadline <= now]:
            self._overtake(account, holds.pop(key).change, "hold_expired")
        if holds:
            self._arm(account)
        else:
            self._unhold(account)

    def _overtake(self, account: UUID, change: Change, reason: str) -> None:
        """A position published past its hold's bound: sent, counted, logged (no account label on
        the series; the line names the account and symbol only)."""
        self._send(account, (change,))
        try:
            self._overtaken()
        except Exception as exc:
            _log().error("oms_ws_overtake_uncounted", error=type(exc).__name__)
        _log().warning(
            "oms_ws_position_overtake", account_id=str(account), symbol=change.symbol, reason=reason
        )

    def _unhold(self, account: UUID) -> None:
        self._holds.pop(account, None)
        timer = self._timers.pop(account, None)
        if timer is not None:
            timer.cancel()

    # -- bounds and the end

    def _overflow(self, account: UUID) -> None:
        """A full queue (C-2.18): the account's queue and holds are dropped, its drain cancelled,
        and its three topics re-snapshotted, so nothing it held is silently missed."""
        _log().error("oms_ws_queue_full", account_id=str(account), queue_max=self._queue_max)
        self._forget(account)
        self._call(self._topics.resync, account, FAMILIES)

    def _forget(self, account: UUID) -> None:
        self._queues.pop(account, None)
        self._unpublished.pop(account, None)
        self._unhold(account)
        drain = self._drains.pop(account, None)
        if drain is not None:
            drain.cancel()

    async def aclose(self) -> None:
        """The runtime's closer, on the lane: nothing is taken after it, and every drain and timer
        is cancelled and waited for. What was held is the store's; a client's next snapshot reads
        it."""
        self._closed = True
        drains = list(self._drains.values())
        for account in {*self._queues, *self._holds, *self._drains}:
            self._forget(account)
        if drains:
            await asyncio.wait(drains)

    def _send(self, account: UUID, changes: tuple[Change, ...]) -> None:
        self._call(self._topics.published, account, changes)

    def _call(self, fn: Callable[..., object], *args: Any) -> None:
        """`fn(*args)` on the serving loop; a notify that raises is logged, never raised."""
        try:
            self._notify(fn, *args)
        except Exception as exc:
            _log().error("oms_ws_notify_failed", error=type(exc).__name__)


class PublishedPositions:
    """The projection's position store (`positions.PositionWrites`) for the WS topics: a row the
    store applied, never a stale write's stored row, also goes to the step publisher once the write
    returns. That hand-off is contained: the row is the projection's either way."""

    def __init__(self, inner: PositionWrites, publisher: StepPublisher) -> None:
        self._inner, self._publisher = inner, publisher

    async def upsert(self, state: PositionState) -> PositionRow:
        row = await self._inner.upsert(state)
        if row.exchange_updated_ts == state.exchange_updated_ts:
            try:
                self._publisher.position(row)
            except Exception as exc:
                ids = {"account_id": str(row.exchange_account_id), "symbol": row.symbol}
                _log().error("oms_ws_position_failed", error=type(exc).__name__, **ids)
        return row


class OpenOrders(Protocol):
    async def list_open(
        self, account_id: UUID, *, symbol: str | None = None
    ) -> tuple[OrderRow, ...]: ...


class OpenPositions(Protocol):
    async def list_open(self, account_id: UUID) -> tuple[PositionRow, ...]: ...


class RecentFills(Protocol):
    async def list_recent(
        self, account_id: UUID, *, limit: int = MAX_RECENT
    ) -> tuple[ExecutionRow, ...]: ...


class TopicReads:
    """The snapshot reads, on the order lane where the OMS's pool runs (the runtime hops each from
    the serving loop): one account's rows of one family, as Sec.15 items stamped with the read's
    start (`LaneClock`). A row of another account is left out (C-12.4, beside the store's own
    scope), and so is a flat position or a fill no frame carries."""

    def __init__(
        self, orders: OpenOrders, positions: OpenPositions, fills: RecentFills, *,
        environment: str, clock: LaneClock,
    ) -> None:  # fmt: skip
        self._orders, self._positions, self._fills = orders, positions, fills
        self._env, self._clock = environment, clock

    async def read(self, family: Family, account: UUID) -> View:
        stamp, env = self._clock(), self._env
        if family == ORDERS:
            orders = await self._orders.list_open(account)
            mine = (r for r in orders if r.exchange_account_id == account)
            return View(stamp, tuple(order_item(r, environment=env, stamp=stamp) for r in mine))
        if family == POSITIONS:
            rows = await self._positions.list_open(account)
            kept = (r for r in rows if r.exchange_account_id == account and not is_flat(r))
            return View(stamp, tuple(position_item(r, environment=env, stamp=stamp) for r in kept))
        fills = await self._fills.list_recent(account, limit=SNAPSHOT_FILLS)
        mine_fills = (r for r in fills if r.exchange_account_id == account)
        items = (execution_item(r, environment=env) for r in mine_fills)
        return View(stamp, tuple(item for item in items if item is not None))


# -- the serving loop's half --------------------------------------------------------------------


class TopicSub(Protocol):
    """The fields of a WS `Subscription` read here: its topic, its accounts (the gateway's
    narrowing of the request to the caller's grants, at `sub` and at every grant change, Sec.6.2,
    Sec.9.5) and its effective options."""

    @property
    def ch(self) -> str: ...
    @property
    def accounts(self) -> frozenset[UUID]: ...
    @property
    def effective(self) -> Mapping[str, Any]: ...


type Match = Callable[[TopicSub], bool]


class Publish(Protocol):
    """`SequencingHub.publish`: one delta to the subscriptions of `ch` holding `account`, whose
    principal holds the family's permission (C-12.4), that `select` accepts besides."""

    def __call__(
        self,
        ch: str,
        body: Mapping[str, Any] | None = ...,
        *,
        account: UUID | None = ...,
        select: Match | None = ...,
    ) -> int: ...


class FlushPending(Protocol):
    """`SequencingHub.flush_pending`: snapshot every pending subscription `match` accepts."""

    def __call__(self, match: Match | None = ...) -> int: ...


class Resnapshot(Protocol):
    """`SequencingHub.resnapshot`: a server-initiated resync of what `match` accepts (Sec.7.4)."""

    def __call__(self, match: Match, reason: Literal["upstream_desync"]) -> int: ...


class BodyFactory[B](Protocol):
    """The gateway's snapshot body from a Sec.15 payload."""

    def __call__(self, structured: Mapping[str, Any]) -> B: ...


class SnapshotReads(Protocol):
    """`TopicReads.read`, reached from the serving loop across the lane's bridge
    (`oms_wiring.OnLaneTopicReads`)."""

    async def read(self, family: Family, account: UUID) -> View: ...


class AttachedTopics(Changes, Protocol):
    """`OmsTopics` as the OMS runtime holds it: what the lane sends it, and the reads it attaches
    once ready and detaches at its stop."""

    def attach(self, reads: SnapshotReads) -> None: ...

    async def detach(self) -> None: ...


def _family(ch: str) -> Family | None:
    return next((family for family in FAMILIES if family == ch), None)


def _symbols(sub: TopicSub) -> frozenset[str] | None:
    """The subscription's `symbols` option, or None for every symbol (Sec.6.2)."""
    symbols = sub.effective.get("symbols")
    return frozenset(symbols) if symbols else None


def _open_only(sub: TopicSub) -> bool:
    return sub.effective.get("open_only") is True


def _holding(family: Family, account: UUID) -> Match:
    """The subscriptions of `family` that hold `account`."""

    def match(sub: TopicSub) -> bool:
        return sub.ch == family and account in sub.accounts

    return match


def _snapshot(family: Family, sub: TopicSub, views: Iterable[View]) -> dict[str, Any]:
    """The subscription's payload from its accounts' views: narrowed to its `symbols`; for
    `executions`, the newest `SNAPSHOT_FILLS` of them, oldest first."""
    wanted = _symbols(sub)
    items = [i for view in views for i in view.items if wanted is None or i["symbol"] in wanted]
    if family == EXECUTIONS:
        items = sorted(items, key=lambda i: (i["ts_ms"], i["id"]))[-SNAPSHOT_FILLS:]
    return {family: items}


class OmsTopics[B]:
    """The serving loop's half (module docstring), for the loop that runs the gateway: no locks.
    The runtime attaches the lane's reads once the OMS is ready (`attach`) and detaches them at its
    stop; before, and after, `build` gives None, so a subscription stays `snapshot_pending`."""

    def __init__(
        self, publish: Publish, flush_pending: FlushPending, resnapshot: Resnapshot,
        body: BodyFactory[B], *, order: Sequence[str] = FAMILIES, views_max: int = MAX_VIEWS,
        loads_max: int = LOADS_MAX, sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        rng: Callable[[], float] = random.random,
    ) -> None:  # fmt: skip
        self._publish, self._flush_pending, self._resnapshot = publish, flush_pending, resnapshot
        self._body, self._sleep, self._rng = body, sleep, rng
        self._rank = {family: rank for rank, family in enumerate(order)}
        self._reads: SnapshotReads | None = None
        self._views: OrderedDict[tuple[Family, UUID], View] = OrderedDict()
        self._views_max = views_max
        self._loads: dict[tuple[Family, UUID], asyncio.Task[None]] = {}
        #: Per key with a load in flight: the latest stamp of a delta of the key seen meanwhile.
        self._raced: dict[tuple[Family, UUID], int] = {}
        #: The keys whose last load gave up: their next change reads them again (`published`).
        self._failed: set[tuple[Family, UUID]] = set()
        self._slots = asyncio.Semaphore(loads_max)

    def attach(self, reads: SnapshotReads) -> None:
        """Read through `reads` from now on, and snapshot the subscriptions left pending."""
        self._reads = reads
        self._flush(lambda sub: _family(sub.ch) is not None)

    async def detach(self) -> None:
        """No more reads (the OMS stops): every load cancelled and waited for, every view
        dropped; a cancellation of `detach` itself still propagates."""
        self._reads = None
        loads = list(self._loads.values())
        self._loads.clear()
        self._raced.clear()
        self._failed.clear()
        self._views.clear()
        for load in loads:
            load.cancel()
        if loads:
            await asyncio.wait(loads)

    # -- SnapshotSource

    def build(self, sub: TopicSub) -> B | None:
        family = _family(sub.ch)
        if family is None or self._reads is None:
            return None
        views: list[View] = []
        for account in sorted(sub.accounts):
            key = (family, account)
            view = self._views.get(key)
            if view is None:
                self._load(key)
            else:
                self._views.move_to_end(key)
                views.append(view)
        if len(views) != len(sub.accounts):
            return None
        return self._body(_snapshot(family, sub, views))

    def generation(self, sub: TopicSub) -> int:
        return 0  # a private family's snapshot is never cached (SR-190)

    def continuity(self, sub: TopicSub, from_ts_ms: int | None) -> bool:
        return False  # no delta history: `snapshot: false` is always `snapshot_forced`

    # -- the deltas, which the lane's half sends

    def published(self, account: UUID, changes: Sequence[Change]) -> None:
        """One account's changes, in `PRIVATE_CAUSAL_ORDER`: each first drops the views it
        outdates and marks a load it may race, then goes out. A change whose publish raises
        re-snapshots its family's subscriptions of the account; one of a key whose last load gave
        up snapshots the subscriptions it left pending (they read again)."""
        last = len(self._rank)
        for change in sorted(changes, key=lambda c: self._rank.get(c.family, last)):
            family = change.family
            self._saw(family, account, change.stamp)
            try:
                self._fan_out(account, change)
            except Exception as exc:  # contained: this account's subscriptions read again
                ids = {"account_id": str(account), "family": family}
                _log().error("oms_ws_publish_failed", error=type(exc).__name__, **ids)
                self.resync(account, (family,))
            if (family, account) in self._failed:
                self._failed.discard((family, account))
                self._flush(_holding(family, account))

    def resync(self, account: UUID, families: Iterable[Family]) -> None:
        """Re-snapshot the account's subscriptions of `families` (`upstream_desync`, Sec.7.4):
        their views dropped first and a load in flight read again, so none serves what it was."""
        wanted = frozenset(families)
        for family in wanted:
            key = (family, account)
            self._views.pop(key, None)
            if key in self._raced:
                self._raced[key] = _RACED
        try:
            self._resnapshot(lambda sub: sub.ch in wanted and account in sub.accounts, _DESYNC)
        except Exception as exc:
            _log().error("oms_ws_resync_failed", account_id=str(account), error=type(exc).__name__)

    def _saw(self, family: Family, account: UUID, stamp: int) -> None:
        key = (family, account)
        if key in self._raced:
            self._raced[key] = max(self._raced[key], stamp)
        view = self._views.get(key)
        if view is not None and view.stamp <= stamp:
            del self._views[key]

    def _fan_out(self, account: UUID, change: Change) -> None:
        """The change's frame to every subscription of its family holding the account (`account=`,
        the hub's scope check, C-12.4) whose `symbols` take it. An order leaving the open set is
        `removed` too, and an `open_only` subscription gets the removal alone; a flat position is a
        removal."""
        symbol, family, key = change.symbol, change.family, change.key

        def wants(sub: TopicSub) -> bool:
            symbols = _symbols(sub)
            return symbols is None or symbol in symbols

        if family == ORDERS and change.closed:
            closed = {ORDERS: [change.item], "removed": [key]}
            self._publish(
                ORDERS, closed, account=account, select=lambda s: wants(s) and not _open_only(s)
            )
            gone = {ORDERS: [], "removed": [key]}
            self._publish(
                ORDERS, gone, account=account, select=lambda s: wants(s) and _open_only(s)
            )
        elif family == POSITIONS and change.closed:
            self._publish(
                POSITIONS, {POSITIONS: [], "removed": [key]}, account=account, select=wants
            )
        else:
            self._publish(family, {family: [change.item]}, account=account, select=wants)

    # -- the snapshot loads

    def _load(self, key: tuple[Family, UUID]) -> None:
        if key not in self._loads:
            self._loads[key] = spawn(self._load_view(key), name="oms-ws-topic-load")

    async def _load_view(self, key: tuple[Family, UUID]) -> None:
        try:
            loaded = await self._read_view(key)
        finally:
            self._loads.pop(key, None)
            self._raced.pop(key, None)
        if loaded is None:  # stays pending: the key's next change, a flush or a resync retries
            if self._reads is not None:
                self._failed.add(key)
            return
        if self._reads is None:
            return
        view, raced = loaded
        self._views[key] = view
        self._views.move_to_end(key)
        while len(self._views) > self._views_max:
            self._views.popitem(last=False)
        family, account = key
        self._flush(_holding(family, account))
        if raced:  # a delta raced every read: served, then read again (`LOAD_ROUNDS`)
            self.resync(account, (family,))

    async def _read_view(self, key: tuple[Family, UUID]) -> tuple[View, bool] | None:
        """The key's view and whether a delta raced its last read; read again while a delta stamped
        at or after the read's start arrived meanwhile (`LOAD_ROUNDS`), and tried again on a
        failure (`LOAD_TRIES`, backed off and jittered); None once every try failed."""
        family, account = key
        for attempt in range(1, LOAD_TRIES + 1):
            reads = self._reads
            if reads is None:
                return None
            try:
                async with self._slots:
                    for _ in range(LOAD_ROUNDS):
                        self._raced[key] = -1
                        view = await reads.read(family, account)
                        if self._raced.get(key, -1) < view.stamp:
                            return view, False
                    return view, True
            except Exception as exc:  # a failure or a hop's bound, never a cancellation
                ids = {"account_id": str(account), "family": family, "error": type(exc).__name__}
                if attempt == LOAD_TRIES:
                    _log().error("oms_ws_topic_load_failed", tries=attempt, **ids)
                    return None
                _log().warning("oms_ws_topic_load_retry", attempt=attempt, **ids)
            await self._sleep(LOAD_BACKOFF_S * 2 ** (attempt - 1) * (0.5 + 0.5 * self._rng()))
        return None  # not reached: the last try returns

    def _flush(self, match: Match) -> None:
        try:
            self._flush_pending(match)
        except Exception as exc:
            _log().error("oms_ws_flush_failed", error=type(exc).__name__)


#: `resync`'s mark on a load in flight: any stamp it read at is older, so it reads again.
_RACED: Final = 2**62
_DESYNC: Final = "upstream_desync"

__all__ = [
    "EXECUTIONS",
    "FAMILIES",
    "FILL_READ_S",
    "HOLD_MAX",
    "HOLD_S",
    "ORDERS",
    "OVERTAKES",
    "POSITIONS",
    "QUEUE_MAX",
    "SNAPSHOT_FILLS",
    "AttachedTopics",
    "Change",
    "LaneClock",
    "OmsTopics",
    "PublishedPositions",
    "SnapshotReads",
    "StepPublisher",
    "TopicReads",
    "View",
    "change_of",
    "execution_item",
    "order_item",
    "position_item",
]  # fmt: skip
