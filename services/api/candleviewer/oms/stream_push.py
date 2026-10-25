"""What one private-stream push does (E29-T05 #848, S4b; 24-internal-schemas.md Sec.8.12). Plain
code on the hot-path contract (C-2.20): `StreamPushes.handle` pairs one order row or trade execution
(`oms.pairing`) under ONE 5 s deadline across all its reads, on the monotonic clock, then sends the
paired row's B1 event through `PushTarget` (the facade's `push`), or opens the lockout for a push no
row or record takes, hands an undecided fill over, or leaves it to reconciliation. It raises nothing
but `CancelledError`. Ids only in logs (C-12.6). Nothing here imports the facade or the statechart.
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, replace
from functools import partial
from typing import Any, Final, Literal, Protocol
from uuid import UUID

import structlog

from candleviewer.domain.primitives import AccountId, TsUs
from candleviewer.exchange.base.models import Execution, Order, PrivateEvent
from candleviewer.storage.errors import StorageQueryFailed
from candleviewer.storage.repositories.orders import OrderRow
from candleviewer.storage.repositories.recorded_stops import (
    RecordedStopNotBindable,
    RecordedStopRow,
)

from .errors import (
    IllegalTransition,
    OrderBufferFull,
    OrderNotLoaded,
    OrderStepRefused,
    OrderStepUnknown,
    ReconcileAnomaly,
)
from .pairing import (
    NeedBound,
    NeedNamed,
    NeedOrder,
    NeedStops,
    NoAnswer,
    NoIntent,
    PairingRefused,
    Reads,
    ToRecordedStop,
    ToRow,
    Undecided,
    WaitOnRow,
    pair,
)  # fmt: skip
from .ports import ExecutionHandovers, Finding, ForeignOrderLockout
from .push_mapping import ForPairing, exec_payload, push_payload

HANDOVER_BOUND_S: Final = 5.0  # 24 Sec.8.12: one bound, all of a push's reads
PORT_TIMEOUT_S: Final = 5.0  # the lockout, the hand-over, the records (C-2.18)
PUSH_TIMEOUT_S: Final = 30.0  # the facade's 5 s ports, B1's 10 s write-ahead and FOLLOWS = 4
PAGED_ORDERS: Final = 1024  # the order ids a full buffer paged on, the oldest forgotten

type Outcome = Literal[
    "paired", "held", "anomaly", "buffer_full", "refused", "unknown", "unknown_twice",
    "not_loaded", "no_intent", "exchange_placed", "undecided", "pairing_refused",
    "lockout_failed", "handover_unavailable", "stop_pending_s6", "stop_unbindable", "unmapped",
]  # fmt: skip
type Decision = ToRow | WaitOnRow | ToRecordedStop | NoIntent | Undecided
type Event = Literal["EXEC", "TRIGGERED", "EXPIRE", "REMOTE_CANCELLED"]


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


class PushTarget(Protocol):  # `OrderMachines.push`
    async def push(
        self, account_id: UUID, order_id: UUID, event: Event, payload: Mapping[str, Any]
    ) -> None: ...


class StreamReads(Protocol):  # the order and recorded-stop stores' reads
    async def get_by_exchange_order_id(self, account_id: UUID, xid: str) -> OrderRow | None: ...
    async def get_by_link_id(self, account_id: UUID, order_link_id: str) -> OrderRow | None: ...
    async def live_for_key(
        self, account_id: UUID, symbol: str, position_idx: int
    ) -> tuple[RecordedStopRow, ...]: ...
    async def for_exchange_order(
        self, account_id: UUID, xid: str
    ) -> tuple[RecordedStopRow, ...]: ...


class FillOrders(Protocol):
    """A fill's order, read by its exchange order id (S8 binds it); None when none was found."""

    async def order_of(self, account_id: UUID, xid: str, symbol: str) -> Order | None: ...


class RecordedStopStream(Protocol):
    """S6's: materialise the recorded stop's row and let it take the push."""

    async def take(
        self, account_id: UUID, decision: ToRecordedStop, push: Order | Execution,
        event: Event | None, ts_event: TsUs,
    ) -> None: ...  # fmt: skip


class NoIntentRecords(Protocol):
    """Writes `oms.no_intent_detected` (`exchange_placed: true`, `frozen: false`), then pages."""

    async def exchange_placed(self, account_id: UUID, *, finding: Finding, key: str) -> None: ...


class PushCounts(Protocol):
    def count(self, outcome: Outcome) -> None: ...  # sync


class Pager(Protocol):  # structurally the statechart's `Pager`, which the hot-path contract bars
    def raise_alert(
        self, severity: Literal["page", "alert"], summary: str, *, machine_kind: str
    ) -> None: ...


class NoRecordedStopStream:
    """`RecordedStopStream` until S6: the record is OMS intent, so it opens nothing; S8 never binds
    it."""

    def __init__(self, counts: PushCounts) -> None:
        self._counts = counts

    async def take(
        self, account_id: UUID, decision: ToRecordedStop, push: Order | Execution,
        event: Event | None, ts_event: TsUs,
    ) -> None:  # fmt: skip
        _log().warning("stream_recorded_stop_pending", account_id=str(account_id))
        self._counts.count("stop_pending_s6")


@dataclass(frozen=True, slots=True)
class _Ctx:
    account_id: AccountId
    route: ForPairing
    ts_event: TsUs


class StreamPushes:
    def __init__(
        self, *, target: PushTarget, reads: StreamReads, fill_orders: FillOrders,
        lockout: ForeignOrderLockout, handovers: ExecutionHandovers, stops: RecordedStopStream,
        no_intent: NoIntentRecords, counts: PushCounts, pager: Pager,
        monotonic: Callable[[], float], handover_bound_s: float = HANDOVER_BOUND_S,
    ) -> None:  # fmt: skip
        self._target, self._reads, self._fills = target, reads, fill_orders
        self._lockout, self._handovers, self._stops = lockout, handovers, stops
        self._records, self._counts, self._pager = no_intent, counts, pager
        self._now, self._bound = monotonic, handover_bound_s
        self._paged: OrderedDict[UUID, None] = OrderedDict()

    async def handle(self, account_id: AccountId, event: PrivateEvent, r: ForPairing) -> None:
        """One push: pair, then dispatch. Raises nothing but `CancelledError`."""
        ctx = _Ctx(account_id, r, event.ts_event)
        deadline = self._now() + self._bound
        if r.unmapped:  # paired for detection only: no B1 event is sent for it
            _log().warning("stream_unmapped_status", **self._ids(ctx))
            self._counts.count("unmapped")
        await self._dispatch(ctx, await self._decide(ctx, deadline), deadline, retry=True)

    async def _decide(self, ctx: _Ctx, deadline: float) -> Decision | None:
        push, reads = ctx.route.push, Reads()
        while True:
            try:
                d = pair(push, reads)
            except PairingRefused:
                _log().error("stream_pairing_refused", **self._ids(ctx))
                self._counts.count("pairing_refused")
                return Undecided(empty_read=False) if isinstance(push, Execution) else None
            if not isinstance(d, NeedBound | NeedNamed | NeedOrder | NeedStops):
                return d
            name, call = self._call(ctx, d)
            answer: Any = await self._read(call, deadline)
            reads = replace(reads, **{name: answer})

    def _call(
        self, ctx: _Ctx, need: NeedBound | NeedNamed | NeedOrder | NeedStops
    ) -> tuple[str, Callable[[], Awaitable[object]]]:
        a, push = ctx.account_id, ctx.route.push
        match need:
            case NeedBound(x):
                return "bound", partial(self._reads.get_by_exchange_order_id, a, x)
            case NeedNamed(link):
                return "named", partial(self._reads.get_by_link_id, a, link)
            case NeedOrder(x):
                return "order", partial(self._fills.order_of, a, x, push.symbol)
            case NeedStops(symbol, idx):
                return "stops", partial(self._reads.live_for_key, a, symbol, idx)

    async def _read(self, call: Callable[[], Awaitable[object]], deadline: float) -> object:
        left = deadline - self._now()
        if left <= 0:  # the bound is spent: a read it cuts short decides nothing
            return NoAnswer.FAILED
        try:
            async with asyncio.timeout(left):
                return await call()
        except Exception:  # a failure, or the bound: never a CancelledError
            return NoAnswer.FAILED

    async def _dispatch(
        self, ctx: _Ctx, d: Decision | None, deadline: float, *, retry: bool
    ) -> None:
        push = ctx.route.push
        match d:
            case None:
                return
            case ToRow(row) | WaitOnRow(row):
                await self._deliver(ctx, row, held=isinstance(d, WaitOnRow))
            case ToRecordedStop() if retry:
                await self._stop(ctx, d, deadline)
            case ToRecordedStop():  # a second one is not retried: the write was refused once
                _log().error("stream_recorded_stop_unbindable", **self._ids(ctx))
                self._counts.count("stop_unbindable")
            case NoIntent():
                await self._open(ctx, d.finding, d.key, placed=d.exchange_placed)
                if isinstance(push, Execution):
                    await self._hand_over(ctx, push, empty_read=False)
            case Undecided(empty_read):
                if not isinstance(push, Execution):  # the pass reads the order afresh
                    _log().warning("stream_order_undecided", **self._ids(ctx))
                    self._counts.count("undecided")
                elif not await self._hand_over(ctx, push, empty_read=empty_read):
                    self._counts.count("undecided")  # fail closed until T06 keeps it (plan R2)
                    await self._open(ctx, "undecided", push.exec_id, placed=False)

    async def _stop(self, ctx: _Ctx, d: ToRecordedStop, deadline: float) -> None:
        r = ctx.route
        try:
            await self._bounded(self._stops.take(ctx.account_id, d, r.push, r.event, ctx.ts_event))
        except (RecordedStopNotBindable, StorageQueryFailed) as exc:
            # The AC (LANE-46): act on what the stores hold now, never on the refused write.
            _log().warning(
                "stream_recorded_stop_refused", kind=type(exc).__name__, **self._ids(ctx)
            )
            found = await self._read(
                partial(self._reads.for_exchange_order, ctx.account_id, d.order.exchange_order_id),
                deadline,
            )
            _log().info("stream_recorded_stop_reread", rows=_count(found), **self._ids(ctx))
            again: Decision | None
            if found is NoAnswer.FAILED:  # nothing found: decide nothing
                again = Undecided(empty_read=False) if isinstance(r.push, Execution) else None
            else:
                again = await self._decide(ctx, deadline)
                if isinstance(again, NoIntent) and found:  # a record of this order is OMS intent
                    again = ToRecordedStop(d.record, d.order)
            await self._dispatch(ctx, again, deadline, retry=False)
        except Exception as exc:
            _log().error("stream_recorded_stop_failed", kind=type(exc).__name__, **self._ids(ctx))
            self._counts.count("stop_unbindable")

    async def _open(self, ctx: _Ctx, finding: Finding, key: str, *, placed: bool) -> None:
        """The lockout (or, for an exchange-placed push, its audit and page): first, bounded."""
        a = ctx.account_id
        try:
            await self._bounded(
                self._records.exchange_placed(a, finding=finding, key=key)
                if placed
                else self._lockout.open(a, finding=finding, key=key)
            )
        except Exception as exc:
            _log().error("stream_lockout_failed", kind=type(exc).__name__, **self._ids(ctx))
            self._page(f"the lockout for a push with no OMS intent failed: {type(exc).__name__}")
            self._counts.count("lockout_failed")
        else:
            self._counts.count("exchange_placed" if placed else "no_intent")

    async def _hand_over(self, ctx: _Ctx, fill: Execution, *, empty_read: bool) -> bool:
        try:
            await self._bounded(
                self._handovers.hand_over_execution(ctx.account_id, fill, empty_read=empty_read)
            )
        except Exception as exc:  # HandoverUnavailable until T06, or a failure or the bound
            _log().warning("stream_handover_unavailable", kind=type(exc).__name__, **self._ids(ctx))
            self._counts.count("handover_unavailable")
            return False
        return True

    async def _deliver(self, ctx: _Ctx, row: OrderRow, *, held: bool) -> None:
        r = ctx.route
        if r.event is None:  # a status no event follows: S6 adds TERMS_CHANGED here
            return
        link = row.order_link_id
        payload = (
            exec_payload(r.push, order_id=row.id, order_link_id=link)
            if isinstance(r.push, Execution)
            else push_payload(r.push, order_link_id=link, ts_event=ctx.ts_event)
        )
        for attempt in (1, 2):  # an unknown outcome is delivered once more (24 Sec.8.2)
            outcome = await self._send(ctx, row.id, r.event, payload, "held" if held else "paired")
            if outcome is not None:
                self._counts.count(outcome)
                return
            if attempt == 2:
                _log().error("stream_step_unknown_twice", **self._ids(ctx))
                self._counts.count("unknown_twice")

    async def _send(
        self, ctx: _Ctx, order_id: UUID, event: Event, payload: Mapping[str, Any], ok: Outcome
    ) -> Outcome | None:  # None: the facade's outcome is unknown
        try:
            await self._bounded(
                self._target.push(ctx.account_id, order_id, event, payload), PUSH_TIMEOUT_S
            )
        except ReconcileAnomaly:  # already audited by the facade
            return "anomaly"
        except OrderStepRefused as exc:
            _log().warning("stream_step_refused", deterministic=exc.deterministic, **self._ids(ctx))
            return "refused"
        except OrderNotLoaded:
            _log().error("stream_order_not_loaded", **self._ids(ctx))
            return "not_loaded"
        except OrderBufferFull:
            _log().error("stream_buffer_full", **self._ids(ctx))
            if order_id not in self._paged:  # no lockout: the push has OMS intent
                self._paged[order_id] = None
                if len(self._paged) > PAGED_ORDERS:
                    self._paged.popitem(last=False)
                self._page("an order's reorder buffer is full; reconciliation must resync it")
            return "buffer_full"
        except IllegalTransition:
            _log().error("stream_illegal_transition", **self._ids(ctx))
            return "refused"
        except OrderStepUnknown:
            return None
        except TimeoutError:  # a cancel landed mid-step: not delivered again
            _log().error("stream_push_timeout", **self._ids(ctx))
            return "unknown"
        return ok

    async def _bounded[T](self, call: Awaitable[T], seconds: float = PORT_TIMEOUT_S) -> T:
        async with asyncio.timeout(seconds):
            return await call

    def _page(self, summary: str) -> None:
        self._pager.raise_alert("page", summary, machine_kind="oms.stream_push")

    @staticmethod
    def _ids(ctx: _Ctx) -> dict[str, str]:  # ids only (C-12.6)
        push = ctx.route.push
        ids = {"account_id": str(ctx.account_id), "exchange_order_id": push.exchange_order_id}
        return ids | ({"exec_id": push.exec_id} if isinstance(push, Execution) else {})


def _count(found: object) -> int:
    return len(found) if isinstance(found, tuple) else -1
