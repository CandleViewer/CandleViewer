"""What one private-stream push does (E29-T05 #848, S4b; 24-internal-schemas.md Sec.8.12). Plain
code on the hot-path contract (C-2.20): `StreamPushes.handle` pairs one order row or trade execution
(`oms.pairing`) under ONE 5 s deadline across all its reads, on the monotonic clock, then sends the
paired row's B1 event through `PushTarget` (the facade's `push`), or opens the lockout for a push no
row or record takes, hands an undecided fill over, or leaves it to reconciliation. A push matched
to a recorded stop (step 3) goes to `RecordedStopStream` (S6b), outside the 5 s hand-over bound: it
answers the order's row, materialised or found by its exchange id, and the push is delivered to that
row as to any other, then the record hook runs (`after_bind`); with no row, nothing is decided (the
next pass reads the order afresh, and a fill is handed over undecided). A recorded stop's row takes
its order's changed terms first (S7a, `oms.stop_terms`): an order push's at most once a second, the
latest winning, sent before any other push of that order and by `flush` at the account's next row
or `heartbeat`; a fill over the row's quantity sends them first, or reads the order and sends its
terms, else is delivered anyway and counted. It raises nothing but `CancelledError`. Ids only in
logs (C-12.6). Nothing here imports the facade or the statechart.
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, replace
from decimal import Decimal
from functools import partial
from typing import Any, Final, Literal, Protocol
from uuid import UUID

import structlog

from candleviewer.domain.primitives import AccountId, TsUs
from candleviewer.exchange.base.models import Execution, Order, PrivateEvent
from candleviewer.storage.repositories.orders import OrderRow
from candleviewer.storage.repositories.recorded_stops import RecordedStopRow

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
from .stop_terms import PendingTerms, TermsKey, differs, terms_payload

HANDOVER_BOUND_S: Final = 5.0  # 24 Sec.8.12: one bound, all of a push's reads
PORT_TIMEOUT_S: Final = 5.0  # the lockout, the hand-over, the records (C-2.18)
PUSH_TIMEOUT_S: Final = 30.0  # the facade's 5 s ports, B1's 10 s write-ahead and FOLLOWS = 4
#: `recorded_stop_stream.TAKE_BUDGET_S`: the account and link reads, the 30 s materialise (24
#: Sec.8.12, Q5) and the two read-backs; the seam's own bounds end it first.
STOP_TAKE_BOUND_S: Final = 4 * PORT_TIMEOUT_S + PUSH_TIMEOUT_S
PAGED_ORDERS: Final = 1024  # the order ids a full buffer paged on, the oldest forgotten

type Outcome = Literal[
    "paired", "held", "anomaly", "buffer_full", "refused", "unknown", "unknown_twice",
    "not_loaded", "no_intent", "exchange_placed", "undecided", "pairing_refused",
    "lockout_failed", "handover_unavailable", "stop_materialised", "stop_found", "stop_undecided",
    "after_bind_failed", "unmapped", "stop_qty_refused", "stop_no_position", "terms",
    "terms_coalesced", "terms_before_fill_unread",
]  # fmt: skip
type Decision = ToRow | WaitOnRow | ToRecordedStop | NoIntent | Undecided
type Event = Literal["EXEC", "TRIGGERED", "EXPIRE", "REMOTE_CANCELLED"]
type Sent = Event | Literal["TERMS_CHANGED"]  # what `PushTarget` is sent


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


class PushTarget(Protocol):  # `OrderMachines.push`
    async def push(
        self, account_id: UUID, order_id: UUID, event: Sent, payload: Mapping[str, Any]
    ) -> None: ...


class StreamReads(Protocol):  # the order and recorded-stop stores' reads
    async def get_by_exchange_order_id(self, account_id: UUID, xid: str) -> OrderRow | None: ...
    async def get_by_link_id(self, account_id: UUID, order_link_id: str) -> OrderRow | None: ...
    async def live_for_key(
        self, account_id: UUID, symbol: str, position_idx: int
    ) -> tuple[RecordedStopRow, ...]: ...


class FillOrders(Protocol):
    """A fill's order, read by its exchange order id (S8 binds it); None when none was found."""

    async def order_of(self, account_id: UUID, xid: str, symbol: str) -> Order | None: ...


class RecordedStopStream(Protocol):
    """`oms.recorded_stop_stream`'s: the recorded stop's order's row, materialised with its
    record's bind or found by the order's exchange id, or None; then the record hook."""

    async def take(
        self, account_id: AccountId, decision: ToRecordedStop, push: Order | Execution,
        event: Event | None, ts_event: TsUs,
    ) -> OrderRow | None: ...  # fmt: skip

    async def after_bind(self, account_id: AccountId, decision: ToRecordedStop) -> None: ...


class NoIntentRecords(Protocol):
    """Writes `oms.no_intent_detected` (`exchange_placed: true`, `frozen: false`), then pages."""

    async def exchange_placed(self, account_id: UUID, *, finding: Finding, key: str) -> None: ...


class PushCounts(Protocol):
    def count(self, outcome: Outcome) -> None: ...  # sync


class Pager(Protocol):  # structurally the statechart's `Pager`, which the hot-path contract bars
    def raise_alert(
        self, severity: Literal["page", "alert"], summary: str, *, machine_kind: str
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class _Ctx:
    account_id: AccountId
    route: ForPairing
    ts_event: TsUs
    deadline: float  # the hand-over bound's end, on the monotonic clock


@dataclass(frozen=True, slots=True)
class _Terms:
    """A recorded stop's row's terms to send: the push that showed them, the row, B1's payload."""

    ctx: _Ctx
    order_id: UUID
    payload: Mapping[str, object]


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
        self._pending: PendingTerms[_Terms] = PendingTerms()

    async def handle(self, account_id: AccountId, event: PrivateEvent, r: ForPairing) -> None:
        """One push: pair, then dispatch. Raises nothing but `CancelledError`."""
        deadline = self._now() + self._bound
        ctx = _Ctx(account_id, r, event.ts_event, deadline)
        if r.unmapped:  # paired for detection only: no B1 event is sent for it
            _log().warning("stream_unmapped_status", **self._ids(ctx))
            self._counts.count("unmapped")
        await self._dispatch(ctx, await self._decide(ctx, deadline))

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

    async def _dispatch(self, ctx: _Ctx, d: Decision | None) -> None:
        push = ctx.route.push
        match d:
            case None:
                return
            case ToRow(row) | WaitOnRow(row):
                await self._deliver(ctx, row, held=isinstance(d, WaitOnRow))
            case ToRecordedStop():
                await self._take_recorded_stop(ctx, d)
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

    async def _take_recorded_stop(self, ctx: _Ctx, d: ToRecordedStop) -> None:
        """The recorded stop's order's row takes the push, then the record hook runs (24 Sec.8.12
        step 3, Sec.8.3 rule 7). A seam that raised or overran its bound decided nothing, so the
        row is read again here; with no row the push is left undecided, never dropped (C-2.6)."""
        r = ctx.route
        try:
            row = await self._bounded(
                self._stops.take(ctx.account_id, d, r.push, r.event, ctx.ts_event),
                STOP_TAKE_BOUND_S,
            )
        except Exception as exc:  # a defect or the bound: what the write did is unknown
            _log().error("stream_recorded_stop_failed", kind=type(exc).__name__, **self._ids(ctx))
            row = await self._reread(ctx)
        if row is None:
            await self._dispatch(ctx, Undecided(empty_read=False))
            return
        await self._deliver(ctx, row, held=False)
        try:  # the hook runs again at the key's next applied position row
            await self._bounded(self._stops.after_bind(ctx.account_id, d))
        except Exception as exc:
            _log().warning("stream_after_bind_failed", kind=type(exc).__name__, **self._ids(ctx))
            self._counts.count("after_bind_failed")

    async def _reread(self, ctx: _Ctx) -> OrderRow | None:
        """The row bound to the push's order, on a deadline of its own; None when none is, the read
        failed, or it answered a row that is not the push's (a store defect, C-12.4)."""
        a, push = ctx.account_id, ctx.route.push
        found = await self._read(
            partial(self._reads.get_by_exchange_order_id, a, push.exchange_order_id),
            self._now() + PORT_TIMEOUT_S,
        )
        if not isinstance(found, OrderRow):
            return None
        if (found.exchange_account_id, found.exchange_order_id) != (a, push.exchange_order_id):
            _log().error("stream_recorded_stop_foreign_row", **self._ids(ctx))
            return None
        return found

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

    async def flush(self, account_id: AccountId) -> None:
        """The account's pending terms whose row sent none in the last second (24 Sec.8.12), at
        its next row or `heartbeat` status (`StreamConsumer`). Raises nothing but
        `CancelledError`."""
        for slot in self._pending.due(account_id, self._now()):
            await self._send_terms(slot)

    async def _deliver(self, ctx: _Ctx, row: OrderRow, *, held: bool) -> None:
        r = ctx.route
        if row.provenance == "recorded_stop":  # its terms first (24 Sec.8.3 rule 7, sixth item)
            if isinstance(r.push, Execution):
                await self._before_fill(ctx, row, r.push)
            else:
                await self._terms_step(ctx, row, r.push, at_once=r.event is not None)
        if r.event is None:  # a status no event follows
            return
        link = row.order_link_id
        payload = (
            exec_payload(r.push, order_id=row.id, order_link_id=link)
            if isinstance(r.push, Execution)
            else push_payload(r.push, order_link_id=link, ts_event=ctx.ts_event)
        )
        await self._step(ctx, row.id, r.event, payload, "held" if held else "paired")

    async def _terms_step(self, ctx: _Ctx, row: OrderRow, order: Order, *, at_once: bool) -> None:
        """An order push to a recorded stop's row: its changed terms, at once before the push's
        own event (an end or a trigger), else coalesced (`oms.stop_terms`). A push showing the
        row's terms drops a pending slot: the latest terms win."""
        key: TermsKey = (ctx.account_id, row.id)
        payload = terms_payload(order, row, ctx.ts_event) if differs(order, row) else None
        if payload is None or at_once:
            self._pending.take(key)
            if payload is not None:
                await self._send_terms(_Terms(ctx, row.id, payload))
            return
        now, evicted = self._pending.offer(key, _Terms(ctx, row.id, payload), self._now())
        for slot in (evicted, now):
            if slot is not None:
                await self._send_terms(slot)
        if now is None:
            self._counts.count("terms_coalesced")

    async def _before_fill(self, ctx: _Ctx, row: OrderRow, fill: Execution) -> None:
        """A fill of a recorded stop's row (24 Sec.8.12 "A fill before its terms"): the row's
        pending terms first; a fill still over the row's quantity less its fills reads the order
        within what is left of the hand-over bound and sends its terms when it shows a larger
        quantity. Else the fill is delivered anyway, counted: B1's fill guard refuses it and the
        facade's `FAULT` quarantines the row for E29-T06. Never dropped, never held."""
        qty = row.qty
        pending = self._pending.take((ctx.account_id, row.id))
        if pending is not None and await self._send_terms(pending):
            qty = Decimal(str(pending.payload.get("qty", qty)))
        if fill.qty <= qty - row.cum_exec_qty:
            return
        a, xid = ctx.account_id, fill.exchange_order_id
        order = await self._read(partial(self._fills.order_of, a, xid, fill.symbol), ctx.deadline)
        payload = None
        if isinstance(order, Order) and order.exchange_order_id == xid and order.qty > qty:
            payload = terms_payload(order, row, ctx.ts_event)
        if payload is None or not await self._send_terms(_Terms(ctx, row.id, payload)):
            _log().warning("stream_terms_before_fill_unread", **self._ids(ctx))
            self._counts.count("terms_before_fill_unread")

    async def _send_terms(self, slot: _Terms) -> bool:
        """`TERMS_CHANGED` to the slot's row, its send noted for the interval; True when taken."""
        ctx = slot.ctx
        outcome = await self._step(ctx, slot.order_id, "TERMS_CHANGED", slot.payload, "terms")
        self._pending.sent((ctx.account_id, slot.order_id), self._now())
        return outcome == "terms"

    async def _step(
        self, ctx: _Ctx, order_id: UUID, event: Sent, payload: Mapping[str, Any], ok: Outcome
    ) -> Outcome:
        """`event` to the row, its outcome counted; an unknown one is delivered once more (24
        Sec.8.2)."""
        for _ in (1, 2):
            outcome = await self._send(ctx, order_id, event, payload, ok)
            if outcome is not None:
                self._counts.count(outcome)
                return outcome
        _log().error("stream_step_unknown_twice", **self._ids(ctx))
        self._counts.count("unknown_twice")
        return "unknown_twice"

    async def _send(
        self, ctx: _Ctx, order_id: UUID, event: Sent, payload: Mapping[str, Any], ok: Outcome
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
        except Exception as exc:  # anything else: the outcome is unknown, never redelivered
            _log().error("stream_push_failed", kind=type(exc).__name__, **self._ids(ctx))
            return "unknown"
        return ok

    async def _bounded[T](self, call: Awaitable[T], seconds: float | None = None) -> T:
        async with asyncio.timeout(PORT_TIMEOUT_S if seconds is None else seconds):
            return await call

    def _page(self, summary: str) -> None:
        self._pager.raise_alert("page", summary, machine_kind="oms.stream_push")

    @staticmethod
    def _ids(ctx: _Ctx) -> dict[str, str]:  # ids only (C-12.6)
        push = ctx.route.push
        ids = {"account_id": str(ctx.account_id), "exchange_order_id": push.exchange_order_id}
        return ids | ({"exec_id": push.exec_id} if isinstance(push, Execution) else {})
