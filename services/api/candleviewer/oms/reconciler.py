"""The reconciliation pass (E29-T06 #914 PR 2a; 24-internal-schemas.md Sec.8.5; the orchestrator's
ruling of record on #914, BQ-1 to BQ-18). Plain code: B19 (`statechart/bindings/
b19_reconciliation.py`) records the job, and its services call this module's phases through
`ReconcilePhases`; nothing here builds, sends to or queries an interpreter. Unwired: no composition
root binds any of it yet (PR 2b), so nothing here runs in production.

**The phases (BQ-18, 24 Sec.8.5's phase table).**

* `fetch` is step 1: the account's four reads on the `poll` lane, the recorded stops' copy (before
  the positions) and the hand-overs. Headroom is read first, and a lane with none fails the fetch
  as a rate-limited read does; the reads run one after another, so the fetch stops at the first
  rate-limit answer (C-12.7). Every row must name the account asked for (BQ-12, C-2.11): the
  adapter drops and counts another account's row (ruling R12), and a row that reaches the pass all
  the same fails the fetch, as a failed read does, and pages once per episode, as one the diff's
  reads meet does. A hand-over entry that no longer reads is listed
  in `errors` (`handover_unreadable`, by its id), a standing item.
* `diff` plans steps 2 to 3d and steps 4 and 5's tests, and applies nothing. One row it cannot plan
  goes to `errors` and the plan goes on; steps 4 and 5 are planned from step 1's reads alone, so no
  local read can stop them. Its exchange reads (3b's and 3d's history lookups) stop at the first
  rate-limit answer too: the rows not read are listed and wait for the next pass.
* `remediate` applies the plan in 24's order (steps 2, 3a, 3b, 3c, 3d, 4, 5). Each action's
  failure goes to `errors` and never ends the pass; step 5 runs whatever came before it (C-2.6).
  A fill's row it reads again that is another account's is paged and listed as the diff's reads
  do, and the fill is kept for the next pass.

**What B1 is sent** (24 Sec.8.5's table): only the facade commands it already takes, as
`actor="system"`. A bound live row takes the exchange's facts as the private stream sends them,
with `source: reconcile` (BQ-8); an `unknown`, `quarantined` or `untracked` row takes a
`RECON_FOUND_*`, carrying the first of the order's fills this pass read that the row has not
applied, the rest then sent as `EXEC`s and an end after them (`found_sends`): an `unknown` row
takes no `EXEC` (INV-B1-e), and B1 adopts no totals without their execution (OM-R02). An
`untracked` row's fills ride its finding too: B1 chart version 8 applies its `EXEC`s and keeps it
`untracked`, and the last fill of a filled order is carried by the `RECON_FOUND_FILLED` that closes
it, once the fills read complete it; a finding that leaves the row `untracked` is sent but never
listed as a correction. A row the
pass finds nowhere takes `RECON_MISS`, with the closed `reject_code` `HistoryRetentionPolicy`
decides (BQ-15): past the history span on demo, `DEMO_RETENTION_EXPIRED`; a live `unknown` row
older than the venue's 24 h span is paged P1 and held, never abandoned. Fills pair through the
bound id only, never by their link id alone (Sec.8.3 rule 7), and an unbound row binds only after
the full match (`b01.full_match`, SR-E29-03).

**What the pass writes ahead.** An order no row takes is adopted `untracked` automatically, audited
`order.adopted_untracked` with the venue's identity before its row (BQ-17, C-2.9); a finding with no
OMS intent opens the account's freeze (E39-T04's setter, BQ-16; an exchange-placed one is audited
and paged instead) before any write that can raise (SR-E27-19). B1's own steps are its write-ahead
`order_events` rows and audits; step 4's drift and the rest are in the report, which B19's
`persist_report` writes as `oms.reconcile` (C-2.9).

**Step 5** (BQ-9; Sec.8.8 rules 4 and 6): a position with no exchange-side stop (none on the
position and no stop order of the OMS's open for it, one bound to an own row or matching its
recorded stop: a foreign stop never counts, SR-E29-06) gets the record in force attached through
E29-T04's recorded-stop writer on the `critical` lane (`ProtectiveStops`), counted in
`naked_position_alerts_total`; with no record in force it is paged P1 once per episode (a pass
that reads it protected or flat ends one), listed in `errors` (`no_record_in_force`, a standing
item) and left to E32-T02, and order entry is not held for it (BQ-9). A Full-mode stop looser
than the record is put back (`sl_restored`; a refusal is `sl_restore_refused`); a tighter one
stays and pages once (`sl_tighter`). A position whose key has a stop request in flight at the copy
is skipped this pass.

**Not here** (E45-T01's named carries, BQ-2): step 6 (the records a flat read ended), the recorded
stops held for reconciliation, the Partial-mode restore and SR-E29-06 (ii)'s foreign-stop cancel.
A live process still refuses to start until they land.

Every await is bounded (C-2.18); cancellation passes through. Logs carry ids, symbols, kinds and
outcomes only, never a price, a size or a credential (C-12.6).
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Final, Literal, Protocol
from uuid import UUID, uuid4

import structlog

from candleviewer.domain.order_link import OUR_ID, ext_key
from candleviewer.domain.primitives import AccountId, Environment, OrderLinkId, Symbol, TsUs
from candleviewer.exchange.base.errors import RateBudgetExceededError, RateLimitError
from candleviewer.exchange.base.models import (
    AccountRef,
    ExchangeCapabilities,
    Execution,
    Order,
    Position,
    RateLane,
)
from candleviewer.statechart.bindings import b01_order as b01
from candleviewer.storage.repositories.executions import ExecType, NewExecution
from candleviewer.storage.repositories.orders import (
    NewOrder,
    OrderRow,
    OrderSide,
    RecordedStopBind,
)
from candleviewer.storage.repositories.recorded_stops import RecordedStopRow

from .commands import found_view
from .errors import OrderStepRefused, ReconcileAnomaly
from .handovers import HandoverRead, WaitingExecution, WaitingOrder
from .order_link_resolution import HistoryRetentionPolicy
from .order_machine import Actor, CommandEvent, PushEvent
from .pairing import STOP_SIDES, first_bindable, is_stop_claim, matching_record, takes_waiting
from .ports import (
    ExecutionHandovers,
    Finding,
    ForeignOrderLockout,
    OrderHandovers,
    RateReading,
    TradingAccounts,
)
from .push_mapping import exec_payload, money_text, order_event, push_payload
from .reconcile_report import (
    FILLS_UNREAD,
    HANDOVER_UNREADABLE,
    NO_RECORD_IN_FORCE,
    UNTRACKED_FILLS_UNREAD,
    PositionDrift,
    ReconcileReport,
    ReportDraft,
    Step,
    Trigger,
)
from .stop_ratchet import loosens


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


#: Each OMS port call (C-2.18), as the facade's own ports are bounded.
PORT_TIMEOUT_S: Final = 5.0
#: Each exchange read: the adapter's 5 s lane wait for each of its pages, a few pages deep.
READ_TIMEOUT_S: Final = 30.0
#: Each facade call: B1's 10 s write-ahead through the facade's 5 s ports (`stream_push`'s bound).
FACADE_TIMEOUT_S: Final = 30.0
#: `gap_from`'s safety overlap (24 Sec.8.5): dedupe makes overlap free.
GAP_OVERLAP_US: Final = 5_000_000
#: A first pass with no mark reads at most one 7-day execution window back (BQ-10, C-12.7).
FIRST_WINDOW_US: Final = 7 * 86_400_000_000
#: Where history never expires, the venue shows a cancelled or rejected order for 24 h (Sec.14.1).
LIVE_HISTORY_SPAN_US: Final = 86_400_000_000
#: An empty order read decides a fill only once one counted a cadence earlier exists (Sec.8.5 3d).
EMPTY_READ_CADENCE_US: Final = 30_000_000
#: The pages the pass raised once, the oldest forgotten past the bound (C-2.18).
PAGED_BOUND: Final = 4096
#: The order states that end an order at the venue, as the adapter names them (24 Sec.8.12).
_ENDED: Final = frozenset(
    {"cancelled", "partially_filled_canceled", "deactivated", "rejected", "filled", "expired"}
)
#: The order states a venue shows an order still open in.
_OPEN: Final = frozenset({"new", "untriggered", "triggered", "partially_filled"})
_EPOCH: Final = datetime(1970, 1, 1, tzinfo=UTC)
_ONE_US: Final = timedelta(microseconds=1)
#: The persisted states 3b leaves alone: held waits for the operator; a create, a cancel and an
#: amend in flight wait for their own answer (B1 v7 gives them no `RECON_MISS`).
_LEFT_TO_THEIR_REQUEST: Final = frozenset(
    {"held", "new", "pending_submit", "submitted", "pending_cancel", "pending_amend"}
)
#: The persisted states a `RECON_FOUND_*` reaches (24 Sec.8.5's table). Their fills ride their
#: finding, never step 2's `EXEC`: an `unknown` or `quarantined` row takes no `EXEC` (INV-B1-e),
#: and an `untracked` row's are sent just before its finding, which closes it only once the fills
#: read complete it (`found_sends`; B1 chart version 8 applies each `EXEC`).
_FINDABLE: Final = frozenset({"unknown", "quarantined", "untracked"})
#: A row's final states (B1's finals).
_TERMINAL: Final = frozenset({"filled", "cancelled", "rejected", "expired", "killed"})
#: The unbound states 3a binds to an open order only after the full match (Sec.8.3 rule 3).
_BOUND_BY_MATCH: Final = frozenset({"unknown", "quarantined"})
_SIDES: Final[Mapping[str, OrderSide]] = {"buy": "Buy", "sell": "Sell"}
_TYPES: Final[Mapping[str, Literal["Market", "Limit"]]] = {"market": "Market", "limit": "Limit"}
_TIFS: Final[Mapping[str, Literal["GTC", "IOC", "FOK", "PostOnly"]]] = {
    "gtc": "GTC", "ioc": "IOC", "fok": "FOK", "post_only": "PostOnly",
}  # fmt: skip
_EXEC_TYPES: Final[Mapping[str, ExecType]] = {
    "trade": "Trade", "funding": "Funding", "adl_trade": "AdlTrade", "bust_trade": "BustTrade",
    "settle": "Settle", "session_settle_pnl": "SessionSettlePnl",
}  # fmt: skip
_RATE_LIMITED: Final = (RateLimitError, RateBudgetExceededError)
#: The page for a row of another account met in the pass (BQ-12, C-2.11): a key and an account
#: mixed up. Its episode ends with an order diff that met none.
_ANOTHER: Final = "oms_rows_of_another_account"
#: The page for a hand-over entry that no longer reads (24 Sec.8.5): once per entry, as it keeps
#: its slot until the Owner prunes it.
_UNREADABLE: Final = "oms_handover_unreadable"


# --- Ports ---------------------------------------------------------------------------------------


class TradingReads(Protocol):
    """An environment's trading port, its reads only (`exchange.base.TradingPort`)."""

    capabilities: ExchangeCapabilities

    async def open_orders(
        self,
        account: AccountRef,
        symbol: Symbol | None = None,
        *,
        order_link_id: OrderLinkId | None = None,
    ) -> Sequence[Order]: ...

    async def order_history(
        self,
        account: AccountRef,
        *,
        order_link_id: OrderLinkId | None = None,
        exchange_order_id: str | None = None,
        start: TsUs | None = None,
        end: TsUs | None = None,
    ) -> Sequence[Order]: ...

    async def positions(self, account: AccountRef) -> Sequence[Position]: ...

    async def executions(
        self, account: AccountRef, start: TsUs, end: TsUs
    ) -> Sequence[Execution]: ...


class ReadRouter(Protocol):
    """`routing.TradingRouter`: the account's own port, and its lane's headroom, read without a
    token (C-2.11, C-12.7)."""

    def port_for(self, environment: Environment) -> TradingReads: ...

    def headroom(self, account: AccountRef, lane: RateLane) -> RateReading: ...


class LocalOrders(Protocol):
    """The order store's reads (`OrderStore`), and the account's unfinished rows: `held` and
    `untracked` included, which `list_open` leaves out (24 Sec.8.5 step 3)."""

    async def unfinished_for(self, account_id: UUID) -> Sequence[OrderRow]: ...

    async def get_by_exchange_order_id(
        self, account_id: UUID, exchange_order_id: str
    ) -> OrderRow | None: ...

    async def get_by_link_id(self, account_id: UUID, order_link_id: str) -> OrderRow | None: ...

    async def link_id_taken(self, order_link_id: str) -> bool: ...


class StoredExecutions(Protocol):
    """The executions store: which `exec_id`s the account holds already (S4), and the insert of
    one that fills no order (`ExecutionStore.insert`)."""

    async def stored(self, account_id: UUID, exec_ids: Collection[str]) -> frozenset[str]: ...

    async def insert(self, execution: NewExecution) -> bool: ...


class RecordedStopCopy(Protocol):
    """The account's live recorded stops (`pending` and `in_force`, 24 Sec.8.8 rule 6), copied in
    step 1 before the positions are read."""

    async def live_for_account(self, account_id: UUID) -> Sequence[RecordedStopRow]: ...


class Handovers(OrderHandovers, ExecutionHandovers, Protocol):
    """The hand-over store (`oms/handovers.py`, 21 Sec.3.3.12): the two writers' ports the stream
    and the lookups take, and the pass's reads, its decision on a fill and its prune."""

    async def waiting_orders(self, account_id: AccountId) -> HandoverRead[WaitingOrder]: ...

    async def waiting_executions(self, account_id: AccountId) -> HandoverRead[WaitingExecution]: ...

    async def decide(self, account_id: AccountId, exec_id: str) -> bool: ...

    async def prune(self, account_id: AccountId, entry_ids: Collection[int]) -> int:
        """Deletes the entries whose fill is paired or whose order has a row (21 Sec.3.3.12)."""
        ...


class OrderMachinesPort(Protocol):
    """`order_machine.OrderMachines`: the commands B1 already takes (BQ-1)."""

    async def command(
        self,
        account_id: UUID,
        order_id: UUID,
        event: CommandEvent,
        payload: Mapping[str, Any] | None = None,
        *,
        actor: Actor,
        expected_seq: int | None = None,
        on_taken: Callable[[], None] | None = None,
    ) -> str: ...

    async def push(
        self, account_id: UUID, order_id: UUID, event: PushEvent, payload: Mapping[str, Any]
    ) -> None: ...

    async def discover(
        self, order: NewOrder, *, environment: str, pass_id: str | None = None
    ) -> str: ...

    async def materialise(
        self,
        order: NewOrder,
        *,
        environment: str,
        pass_id: str | None = None,
        binds: RecordedStopBind | None = None,
    ) -> str: ...


@dataclass(frozen=True, slots=True)
class PositionDriftSeen:
    """What the projection held for a position before a REST read was applied over it."""

    side: str | None
    qty: Decimal


class PositionTruth(Protocol):
    """The position projection's REST side (step 4): what it holds for each of the account's keys,
    and the apply of an exchange read over it (`rest_reconcile` snapshots, 21 Sec.3.3.7), which
    answers what it held before when the read changed it, else None (equal, or older)."""

    async def held(self, account_id: UUID) -> Mapping[tuple[str, int], PositionDriftSeen]: ...

    async def apply(self, position: Position, *, pass_id: str) -> PositionDriftSeen | None: ...


#: What a step-5 stop write did: sent and answered, refused by the venue, no longer needed on the
#: writer's own re-read (a restore's stop no longer looser, an attach's position flat or
#: protected), or not sent (the writer refused before any send).
StopWrite = Literal["sent", "refused", "not_looser", "not_sent"]


class ProtectiveStops(Protocol):
    """E29-T04's recorded-stop writer for a position (Sec.8.8 rules 4 to 6), on the `critical`
    lane: the attach of a missing stop from the record in force (audited `sl.attached`, reason
    `record_in_force`), and the restore of the record over a looser Full-mode stop (audited
    `sl.modified` with both values). Each derives what it sends from its own read."""

    async def attach_recorded(
        self, account: AccountRef, position: Position, record: RecordedStopRow, *, pass_id: str
    ) -> StopWrite: ...

    async def restore_recorded(
        self, account: AccountRef, position: Position, record: RecordedStopRow, *, pass_id: str
    ) -> StopWrite: ...


class ExchangePlaced(Protocol):
    """A finding with no OMS intent whose order the venue itself placed: audited
    (`oms.no_intent_detected`) and paged, never frozen (24 Sec.8.10)."""

    async def exchange_placed(self, account_id: UUID, *, finding: Finding, key: str) -> None: ...


class AdoptionAudit(Protocol):
    """`order.adopted_untracked`, written ahead of the row (24 Sec.15.5, BQ-17)."""

    async def adopted(
        self, account_id: AccountId, *, row_id: UUID, order: Order, pass_id: str
    ) -> None: ...


class Pager(Protocol):  # structurally the statechart's `Pager`
    def raise_alert(
        self, severity: Literal["page", "alert"], summary: str, *, machine_kind: str
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class ReconcilePorts:
    """Everything the pass reads and writes through (PR 2b binds them)."""

    accounts: TradingAccounts
    router: ReadRouter
    orders: LocalOrders
    executions: StoredExecutions
    stops: RecordedStopCopy
    handovers: Handovers
    machines: OrderMachinesPort
    positions: PositionTruth
    protective: ProtectiveStops
    lockout: ForeignOrderLockout
    exchange_placed: ExchangePlaced
    adoptions: AdoptionAudit
    pager: Pager


# --- The pure part: the window, the history rule, the views and the found sequence --------------


def gap_window(
    *, last_message_us: int | None, last_reconciled_us: int | None, now_us: int
) -> tuple[TsUs, TsUs]:
    """The execution read's window (24 Sec.8.5, BQ-10): from `min(last private-stream message,
    last good pass) - 5 s` to `now_us`, the bound step 1 reads to and the watermark a good pass
    stores. An account with neither mark reads one 7-day window back (C-12.7)."""
    marks = [m for m in (last_message_us, last_reconciled_us) if m is not None]
    start = min(marks) - GAP_OVERLAP_US if marks else now_us - FIRST_WINDOW_US
    return max(0, min(start, now_us)), now_us


def history_covers(retention: HistoryRetentionPolicy, created_us: int, now_us: int) -> bool:
    """Whether a miss in the order history proves anything (BQ-15, Sec.14.1): where history is
    retained (demo), always, `HistoryRetentionPolicy` deciding what a miss past it means; where it
    never expires (live), only for an order created within the venue's 24 h span, as it shows a
    cancelled or rejected order no longer. Capability-driven, never the environment."""
    return retention.retention_days is not None or now_us - created_us <= LIVE_HISTORY_SPAN_US


def miss_code(retention: HistoryRetentionPolicy, created_us: int, now_us: int) -> str:
    """The `reject_code` a miss of an `unknown` row carries (Sec.8.3 rule 6, BQ-15)."""
    if retention.unresolvable_by_history(created_at=created_us, now=now_us):
        return b01.DEMO_RETENTION_EXPIRED
    return b01.UNRESOLVED_AFTER_RECONCILE


def row_view(row: OrderRow) -> dict[str, Any]:
    """A row as B1's context names an order, for `b01.full_match` (SR-E29-03), as `found_view`
    names the exchange's: ids and text, `reduce_only`, money as canonical decimal text."""
    money = {
        key: None if value is None else money_text(value)
        for key, value in (
            ("qty", row.qty),
            ("price", row.price),
            ("trigger_price", row.trigger_price),
            ("stop_loss", row.stop_loss),
        )
    }
    return {
        "order_link_id": row.order_link_id,
        "account_id": str(row.exchange_account_id),
        "symbol": row.symbol,
        "side": row.side.lower(),
        "reduce_only": row.reduce_only,
        **money,
    }


def full_match(row: OrderRow, order: Order) -> bool:
    """SR-E29-03's full match, B1's own predicate; a malformed value never matches (A6)."""
    try:
        return b01.full_match(row_view(row), found_view(order))
    except (ValueError, ArithmeticError):
        return False


@dataclass(frozen=True, slots=True)
class FoundCommand:
    """A finding's facade command (`RECON_FOUND_*`), with its closed payload."""

    event: CommandEvent
    payload: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class FoundPush:
    """A push that follows a finding (`EXEC`, then an end), with its closed payload."""

    event: PushEvent
    payload: Mapping[str, Any]


type Send = FoundCommand | FoundPush


def fill_push(fill: Execution, row: OrderRow) -> dict[str, Any]:
    """A fill as the stream sends it, to the row bound to its order, `source: reconcile`."""
    return exec_payload(fill, order_id=row.id, order_link_id=row.order_link_id) | {
        "source": "reconcile"
    }


def fact_push(order: Order, row: OrderRow, ts_event: TsUs) -> dict[str, Any]:
    """An order's status as the stream sends it, under the row's own link id (Sec.8.3 rule 7)."""
    return push_payload(order, order_link_id=row.order_link_id, ts_event=ts_event) | {
        "source": "reconcile"
    }


def found_sends(
    row: OrderRow, order: Order, fills: Sequence[Execution], *, pass_id: str, ts_event: TsUs
) -> tuple[Send, ...] | None:
    """What a found `unknown`, `quarantined` or `untracked` row takes (24 Sec.8.5's table). An
    `unknown` or `quarantined` row takes no `EXEC` (INV-B1-e) and B1 adopts no totals without
    their execution (OM-R02): its finding carries the first fill this pass read that it has not
    applied, the rest follow as `EXEC`s, and an end other than `filled` comes after them (INV-B1-k).
    An `untracked` row is recorded, never managed: one finding by the order's state, the fills it
    does not carry sent before it as `EXEC`s, which B1 chart version 8 applies to the row and
    which leave it `untracked`; a filled order's last fill rides its `RECON_FOUND_FILLED`, the one
    arm that closes the row, and the step writer stores that fill. As the store takes `filled`
    only with the row's `qty` filled, a filled order is sent its finding only when the fills read
    complete the row: their sum, over what the row holds already, is its `qty` (an order filled in
    several executions closes so too). None when the totals the venue shows are not the fills read
    (they lie outside every window read), or for such an order whose fills read cannot complete
    it: nothing is adopted, the row is listed and the next pass reads again, an `untracked` row's
    as a standing item, its fills kept (`UNTRACKED_FILLS_UNREAD`)."""
    base: dict[str, Any] = {"exchange_order_id": order.exchange_order_id, "pass_id": pass_id}
    if order.state not in _ENDED and order.state not in _OPEN:
        return None  # a status 24 Sec.8.12 does not map: decided by no finding
    ended = order.state in _ENDED
    if row.state == "untracked":
        logged = list(fills)
        if order.state == "filled":
            read = sum((f.qty for f in fills), Decimal(0))
            if not fills or row.cum_exec_qty + read != row.qty:
                return None  # no fill read, or fills that do not complete it (`state_mismatch`)
            last = logged.pop()
            carried = exec_payload(last, order_id=row.id, order_link_id=row.order_link_id)
            finding = FoundCommand("RECON_FOUND_FILLED", base | {"execution": carried})
        elif ended:
            finding = FoundCommand("RECON_FOUND_CANCELLED", base)
        else:
            live: CommandEvent = (
                "RECON_FOUND_PARTIAL" if order.filled_qty > 0 else "RECON_FOUND_LIVE"
            )
            finding = FoundCommand(live, base)
        return (*(FoundPush("EXEC", fill_push(f, row)) for f in logged), finding)
    fresh = sum((f.qty for f in fills), Decimal(0))
    if order.filled_qty != row.cum_exec_qty + fresh:
        return None
    if not fills:
        if order.state == "filled":
            return None  # `filled` needs its execution, and none is left to carry
        if ended:
            return (FoundCommand("RECON_FOUND_CANCELLED", base),)
        resting: CommandEvent = (
            "RECON_FOUND_PARTIAL" if row.cum_exec_qty > 0 else "RECON_FOUND_LIVE"
        )
        return (FoundCommand(resting, base),)
    first = exec_payload(fills[0], order_id=row.id, order_link_id=row.order_link_id)
    if order.state == "filled" and len(fills) == 1:
        return (FoundCommand("RECON_FOUND_FILLED", base | {"execution": first}),)
    sends: list[Send] = [FoundCommand("RECON_FOUND_PARTIAL", base | {"execution": first})]
    sends += [FoundPush("EXEC", fill_push(f, row)) for f in fills[1:]]
    if ended and order.state != "filled":
        end = order_event(order)
        if end is not None:
            sends.append(FoundPush(end, fact_push(order, row, ts_event)))
    return tuple(sends)


# --- Step 1's reads and the plan ----------------------------------------------------------------


class FetchError(Exception):
    """A failed fetch (24 Sec.8.5's phase table): `kind` is the cause's class or a named check,
    never its text, so nothing it carries can hold a value or a credential (C-12.6)."""

    def __init__(self, kind: str) -> None:
        super().__init__(f"the reconciliation fetch failed ({kind})")
        self.kind = kind


@dataclass(frozen=True, slots=True)
class Fetched:
    """Step 1's reads (24 Sec.8.5), every row the account's."""

    account: AccountRef
    pass_id: str
    trigger: Trigger
    window: tuple[TsUs, TsUs]
    started_us: int
    retention: HistoryRetentionPolicy
    remote_open: tuple[Order, ...]
    records: tuple[RecordedStopRow, ...]
    positions: tuple[Position, ...]
    executions: tuple[Execution, ...]
    waiting_orders: tuple[WaitingOrder, ...]
    waiting_executions: tuple[WaitingExecution, ...]
    unreadable: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class StoreFill:
    """Step 2: an execution that fills no order (funding, ADL, bust, settle), stored with none."""

    execution: Execution


@dataclass(frozen=True, slots=True)
class PushFill:
    """Steps 2 and 3d: a fill to the row bound to its order (Sec.8.3 rule 7), or to an unbound
    live row its link id names, whose reorder buffer holds it until its bind (S5)."""

    step: Step
    row: OrderRow
    execution: Execution
    entry_id: int | None = None


@dataclass(frozen=True, slots=True)
class LateFill:
    """3d: a fill of an order this pass binds or records first (3a to 3c): its row is read again
    when it is applied, and with none, or an `untracked` one, the fill is kept for the next pass,
    whose finding carries it to that row (`found_sends`)."""

    execution: Execution
    entry_id: int | None = None


@dataclass(frozen=True, slots=True)
class PushFact:
    """3a, 3b: a bound live row's trigger or end, as the stream sends it (`source: reconcile`)."""

    step: Step
    row: OrderRow
    order: Order
    event: PushEvent
    listed: Literal["corrected", "resolved_from_history"]


@dataclass(frozen=True, slots=True)
class Find:
    """3a, 3b: an `unknown`, `quarantined` or `untracked` row found (`found_sends`)."""

    step: Step
    row: OrderRow
    sends: tuple[Send, ...]
    listed: Literal["corrected", "resolved_from_history"]
    entry_ids: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class Mismatch:
    """3a, 3b: the order under the row's id is not the row's (SR-E29-03): no OMS intent, handed
    over, the row held, the order recorded beside it under `ext_key(orderId)`."""

    step: Step
    row: OrderRow
    order: Order


@dataclass(frozen=True, slots=True)
class Miss:
    """3b: a row the pass found nowhere: `RECON_MISS`, with an `unknown` row's closed code."""

    row: OrderRow
    reject_code: str | None


@dataclass(frozen=True, slots=True)
class HoldPastSpan:
    """3b: a live `unknown` row older than the venue's 24 h span: paged P1 once and kept (BQ-15)."""

    row: OrderRow


@dataclass(frozen=True, slots=True)
class Adopt:
    """3c: an order no row takes, recorded `untracked` under `key` (a foreign stop's too), its
    freeze opened first where it has no OMS intent (SR-E27-19)."""

    order: Order
    key: str
    foreign_stop: bool
    no_intent: bool
    entry_id: int | None = None


@dataclass(frozen=True, slots=True)
class Anomaly:
    """3c: a `ReconcileAnomaly` (S6): audited, alerted, no mutation."""

    order: Order
    no_intent: bool


@dataclass(frozen=True, slots=True)
class Materialise:
    """3c, 3d: a recorded stop's TP/SL order, materialised and bound (Sec.8.3 rule 7), with the
    fill that showed it in 3d."""

    step: Step
    record: RecordedStopRow
    order: Order
    fill: Execution | None = None
    entry_id: int | None = None


@dataclass(frozen=True, slots=True)
class KeepFill:
    """3d: a fill kept in `oms_handovers` for the next pass: its order's read failed, or found no
    order a first time (`empty_read`)."""

    execution: Execution
    empty_read: bool


@dataclass(frozen=True, slots=True)
class Unpaired:
    """3d: a fill with no OMS intent: frozen for once and marked decided, then listed on every
    pass until the Owner resolves it; one decided by an earlier pass is listed only."""

    execution: Execution
    order: Order | None
    decided: bool


@dataclass(frozen=True, slots=True)
class FixPosition:
    """Step 4: the exchange's position, which differs from what the OMS holds."""

    position: Position


@dataclass(frozen=True, slots=True)
class AttachStop:
    """Step 5: a position with no exchange-side stop, and a record in force (BQ-9)."""

    position: Position
    record: RecordedStopRow


@dataclass(frozen=True, slots=True)
class PageNaked:
    """Step 5: a position with no exchange-side stop and no record in force (BQ-9)."""

    position: Position


@dataclass(frozen=True, slots=True)
class RestoreStop:
    """Step 5: a Full-mode stop looser than the record in force."""

    position: Position
    record: RecordedStopRow


@dataclass(frozen=True, slots=True)
class PageTighter:
    """Step 5: a stop tighter than the record, which stays: restoring would loosen it."""

    position: Position


type Action = (
    StoreFill | PushFill | LateFill | PushFact | Find | Mismatch | Miss | HoldPastSpan | Adopt
    | Anomaly | Materialise | KeepFill | Unpaired | FixPosition | AttachStop | PageNaked
    | RestoreStop | PageTighter
)  # fmt: skip


@dataclass
class Plan:
    """The diff's plan (BQ-18): its actions in 24 Sec.8.5's order, each a divergence, and the
    report the pass fills in, the diff's errors in it already."""

    fetched: Fetched
    draft: ReportDraft
    actions: list[Action] = field(default_factory=list)
    #: Hand-over entries already settled (a fill stored already, an order recorded already).
    settled: list[int] = field(default_factory=list)
    #: The account's `untracked` rows: as the diff read them, then as the remediation leaves
    #: them; None when the diff could not read the rows, so `oms_untracked_orders` keeps its
    #: last count.
    untracked: int | None = None
    #: The exchange order ids bound to the account's own rows the diff read (`untracked` ones
    #: excepted, as their orders are foreign): an open stop order among them is the OMS's (step
    #: 5). Empty when the order store could not be read, so the records alone decide.
    ours: frozenset[str] = frozenset()

    @property
    def divergences(self) -> int:
        return len(self.actions)

    def kinds(self) -> list[str]:
        return sorted({type(action).__name__ for action in self.actions})

    def count_untracked(self, change: int) -> None:
        """An `untracked` row recorded (+1) or closed (-1) by the remediation, once counted."""
        if self.untracked is not None:
            self.untracked += change


async def _bounded[T](call: Awaitable[T], seconds: float) -> T:
    async with asyncio.timeout(seconds):
        return await call


def _at(us: int) -> datetime:
    return _EPOCH + us * _ONE_US


def _us(at: datetime) -> int:
    return (at - _EPOCH) // _ONE_US


def _rows_of_another(account_id: AccountId, fetched: Iterable[Any]) -> int:
    """The rows naming another account (BQ-12): none should reach the pass (ruling R12)."""
    return sum(1 for row in fetched if getattr(row, "account_id", account_id) != account_id)


def adopted_row(
    row_id: UUID, account_id: AccountId, order: Order, key: str, *, stop: bool
) -> NewOrder:
    """The `untracked` row of an order no row takes (24 Sec.8.3 "Adopted rows"): the venue's terms
    under `key`; no fill totals, which B1 adopts only with their executions (OM-R02). `ValueError`
    for an order the table cannot hold (`[O-4]`: a stop shown with no quantity)."""
    if order.qty <= 0:
        raise ValueError("an order with no quantity cannot be held")
    kind = STOP_SIDES.get(order.order_kind)
    return NewOrder(
        id=row_id,
        exchange_account_id=account_id,
        order_link_id=key,
        symbol=order.symbol,
        side=_SIDES[order.side],
        intent=kind[0] if stop and kind is not None else ("stop_loss" if stop else "entry"),
        order_type=_TYPES[order.order_type],
        qty=order.qty,
        price=order.price,
        trigger_price=order.trigger_price,
        take_profit=order.take_profit,
        stop_loss=order.stop_loss,
        tpsl_mode="Partial" if order.tpsl_mode == "partial" else "Full",
        time_in_force=_TIFS.get(order.time_in_force, "GTC"),
        reduce_only=order.reduce_only,
        position_idx=order.position_idx,
        exchange_order_id=order.exchange_order_id,
        exchange_created_ts=_at(order.created_at),
        exchange_updated_ts=None if order.updated_at is None else _at(order.updated_at),
    )


def materialised_row(
    row_id: UUID,
    account_id: AccountId,
    record: RecordedStopRow,
    order: Order,
    link: str,
    qty: Decimal,
) -> NewOrder:
    """A recorded stop's materialised row (24 Sec.8.3 rule 7), as E29-T05's stream writes it:
    the order's terms, the record's side and mode, reduce-only and close-on-trigger."""
    return NewOrder(
        id=row_id,
        exchange_account_id=account_id,
        order_link_id=link,
        symbol=order.symbol,
        side=_SIDES[order.side],
        intent=record.kind,
        order_type=_TYPES[order.order_type],
        qty=qty,
        price=order.price,
        trigger_price=order.trigger_price,
        tpsl_mode=record.tpsl_mode,
        time_in_force=_TIFS.get(order.time_in_force, "GTC"),
        reduce_only=True,
        close_on_trigger=True,
        position_idx=order.position_idx,
        exchange_order_id=order.exchange_order_id,
        provenance="recorded_stop",
    )


def new_execution(execution: Execution) -> NewExecution:
    """An execution that fills no order, as `executions` stores it (21 Sec.3.3.6)."""
    return NewExecution(
        exchange_account_id=execution.account_id,
        exec_id=execution.exec_id,
        symbol=execution.symbol,
        side=_SIDES[execution.side],
        exec_qty=execution.qty,
        exec_price=execution.price,
        exec_value=execution.qty * execution.price,
        exec_type=_EXEC_TYPES[execution.exec_type],
        is_maker=execution.is_maker,
        exec_ts=_at(execution.ts_exec),
        order_link_id=execution.order_link_id,
        exec_fee=execution.fee,
        fee_rate=execution.fee_rate,
        fee_currency=execution.fee_currency or "USDT",
        closed_pnl=execution.closed_pnl,
    )


def _in_force(position: Position, records: Sequence[RecordedStopRow]) -> RecordedStopRow | None:
    """The stop-loss record in force for the position's side (Sec.8.8 rule 6): one in force, or a
    pending Full-mode one this pass's read shows at its trigger; the latest of them."""
    side = _SIDES.get(position.side or "")
    shown = position.stop_loss

    def counts(r: RecordedStopRow) -> bool:
        if r.kind != "stop_loss" or r.position_side != side:
            return False
        if r.status == "in_force":
            return True
        full_shown = r.tpsl_mode == "Full" and shown is not None and shown == r.trigger_price
        return r.status == "pending" and r.answered_at is not None and full_shown

    found = [r for r in records if counts(r)]
    return max(found, key=lambda r: (r.created_at, r.id), default=None)


def _raced(records: Sequence[RecordedStopRow]) -> bool:
    """A stop request of the key was in flight when the pass copied the records (Sec.8.8 rule 6)."""
    return any(r.status == "pending" and r.answered_at is None for r in records)


_STOP_KINDS: Final = frozenset({"stop_loss", "partial_stop_loss", "trailing_stop"})


def _covered(
    position: Position,
    remote_open: Sequence[Order],
    ours: Collection[str],
    records: Sequence[RecordedStopRow],
) -> bool:
    """A stop order of the OMS's open for the position (24 Sec.8.5 step 5's paired stops): one
    bound to a row of the account that is not `untracked`, or one that matches a recorded stop of
    the position (Sec.8.8 rule 6), as 3c's `_matching` reads it. A foreign stop never counts
    (SR-E29-06): it is never paired with the position's protection, and 3c records and freezes
    it. With the order store unread, `ours` is empty and the records alone decide, so a stop the
    pass cannot show is the OMS's leaves the position to step 5's repair (C-2.6)."""
    closing = "sell" if position.side == "buy" else "buy"
    for o in remote_open:
        if o.order_kind not in _STOP_KINDS or (o.symbol, o.position_idx, o.side) != (
            position.symbol, position.position_idx, closing,
        ):  # fmt: skip
            continue
        if o.exchange_order_id in ours:
            return True
        if matching_record(o, first_bindable(o, records)) is not None:
            return True
    return False


class Reconciler:
    """The pass's phases (module docstring). One serves every account; B19 runs one pass at a
    time per account, so a pass never overlaps itself. Its helpers read it through its public
    surface (`ports`, `now_us`, `new_id`, `count_naked`, `page_once`, `alert_once`, `rearm`),
    never a private name."""

    def __init__(
        self,
        ports: ReconcilePorts,
        *,
        now_us: Callable[[], int],
        new_id: Callable[[], UUID] = uuid4,
        on_naked: Callable[[], None] | None = None,
    ) -> None:
        self._p, self._now, self._new_id = ports, now_us, new_id
        self._on_naked = on_naked
        self._paged: OrderedDict[tuple[str, AccountId, tuple[str, ...]], None] = OrderedDict()

    @property
    def ports(self) -> ReconcilePorts:
        """The ports the pass reads and writes through."""
        return self._p

    def now_us(self) -> int:
        """The pass's clock, in microseconds (as `ReconcilePhases.now_us`)."""
        return self._now()

    def new_id(self) -> UUID:
        """A new row's id."""
        return self._new_id()

    def count_naked(self) -> None:
        """Counts `naked_position_alerts_total` (BQ-9), where the wiring gave a counter."""
        if self._on_naked is not None:
            self._on_naked()

    async def reconcile(
        self,
        account_id: AccountId,
        gap_from: TsUs,
        *,
        pass_id: str,
        trigger: Trigger,
    ) -> ReconcileReport:
        """24 Sec.8.5's `reconcile(account, gap_from)`: fetch, diff and remediate, then the report.
        Raises `FetchError` for a failed fetch, as B19's fetch phase does."""
        now = self._now()
        fetched = await self.fetch(
            account_id, pass_id=pass_id, trigger=trigger, window=(gap_from, now)
        )
        plan = await self.diff(fetched)
        await self.remediate(plan)
        return self.finish(plan)

    # --- Step 1 ---------------------------------------------------------------------------------

    async def fetch(
        self,
        account_id: AccountId,
        *,
        pass_id: str,
        trigger: Trigger,
        window: tuple[TsUs, TsUs],
    ) -> Fetched:
        """Step 1 (module docstring); `FetchError` for a failed fetch, the cause's class only."""
        started = self._now()
        p = self._p
        try:
            account = await _bounded(p.accounts.trading_account(account_id), PORT_TIMEOUT_S)
            if account.account_id != account_id:
                raise FetchError("other_account")
            if not p.router.headroom(account, "poll").available:
                raise FetchError("no_headroom")  # as a rate-limited read (C-12.7)
            port = p.router.port_for(account.environment)
            remote_open = tuple(await _bounded(port.open_orders(account), READ_TIMEOUT_S))
            records = tuple(await _bounded(p.stops.live_for_account(account_id), PORT_TIMEOUT_S))
            positions = tuple(await _bounded(port.positions(account), READ_TIMEOUT_S))
            start, end = window
            executions = tuple(await _bounded(port.executions(account, start, end), READ_TIMEOUT_S))
            orders = await _bounded(p.handovers.waiting_orders(account_id), PORT_TIMEOUT_S)
            fills = await _bounded(p.handovers.waiting_executions(account_id), PORT_TIMEOUT_S)
            retention = HistoryRetentionPolicy.from_capabilities(port.capabilities)
        except FetchError:
            raise
        except Exception as exc:  # never a CancelledError
            raise FetchError(type(exc).__name__) from None
        foreign = _rows_of_another(
            account_id,
            (
                *remote_open, *positions, *executions,
                *(w.order for w in orders.entries), *(w.execution for w in fills.entries),
            ),
        ) + sum(1 for r in records if r.exchange_account_id != account_id)  # fmt: skip
        if foreign:
            _log().critical("reconcile_rows_of_another_account", account_id=str(account_id),
                            rows=foreign, pass_id=pass_id)  # fmt: skip
            self.page_once(_ANOTHER, account_id)
            raise FetchError("other_account")  # BQ-12, C-2.11: a key and an account mixed up
        return Fetched(
            account=account,
            pass_id=pass_id,
            trigger=trigger,
            window=window,
            started_us=started,
            retention=retention,
            remote_open=remote_open,
            records=records,
            positions=positions,
            executions=executions,
            waiting_orders=orders.entries,
            waiting_executions=fills.entries,
            unreadable=(*orders.unreadable, *fills.unreadable),
        )

    # --- The diff: a plan, never a write (BQ-18) --------------------------------------------------

    async def diff(self, fetched: Fetched) -> Plan:
        """Steps 2 to 3d, and steps 4 and 5's tests, as a plan. One row it cannot plan goes to
        `errors`; steps 4 and 5 are planned whatever the order steps did."""
        account = fetched.account
        draft = ReportDraft(account.account_id, fetched.pass_id, fetched.trigger, fetched.window)
        plan = Plan(fetched, draft)
        for entry_id in fetched.unreadable:  # listed every pass, paged once (24 Sec.8.5)
            draft.error("1", HANDOVER_UNREADABLE, str(entry_id))
            self.page_once(_UNREADABLE, account.account_id, str(entry_id))
        try:
            await _OrderDiff(self, plan).run()
        except Exception as exc:  # the order steps as a whole; 4 and 5 still plan
            draft.error("2", type(exc).__name__)
        try:
            await self._plan_positions(plan)
        except Exception as exc:
            draft.error("4", type(exc).__name__)
        self._plan_stops(plan)
        return plan

    async def _plan_positions(self, plan: Plan) -> None:
        """Step 4: exchange is truth; a position the OMS holds otherwise is a divergence."""
        f = plan.fetched
        held = await _bounded(self._p.positions.held(f.account.account_id), PORT_TIMEOUT_S)
        for p in f.positions:
            seen = held.get((p.symbol, p.position_idx))
            if seen is None:
                if p.qty > 0:
                    plan.actions.append(FixPosition(p))
            elif seen.qty != p.qty or (p.qty > 0 and seen.side != p.side):
                plan.actions.append(FixPosition(p))

    def _plan_stops(self, plan: Plan) -> None:
        """Step 5's tests, from step 1's reads alone, so nothing before them can stop them
        (C-2.6), each position on its own (BQ-18): one that cannot be planned is listed by its
        class and symbol, and every other position still plans. A position read protected or
        flat ends its naked episode, so its next one pages again (24 Sec.8.5: once per episode);
        one not judged this pass keeps its episode."""
        f = plan.fetched
        standing: set[tuple[str, ...]] = set()
        for p in f.positions:
            key = (p.symbol, str(p.position_idx))
            try:
                if self._plan_stop(plan, p):
                    standing.add(key)
            except Exception as exc:
                standing.add(key)
                plan.draft.error("5", type(exc).__name__, p.symbol)
        self.rearm(_NAKED_PAGES, f.account.account_id, lambda key: key not in standing)

    def _plan_stop(self, plan: Plan, p: Position) -> bool:
        """One position's step 5; true while it may stand naked: read so, or left this pass to a
        stop request in flight at the copy."""
        f, draft = plan.fetched, plan.draft
        if p.qty <= 0 or p.side is None:
            return False
        records = [r for r in f.records if (r.symbol, r.position_idx) == (p.symbol, p.position_idx)]
        if _raced(records):
            return True
        record = _in_force(p, records)
        stop = p.stop_loss if p.stop_loss is not None and p.stop_loss > 0 else None
        if stop is None and not _covered(p, f.remote_open, plan.ours, records):
            if record is None:  # BQ-9: paged, listed, left to E32-T02; entry is not held
                plan.actions.append(PageNaked(p))
                draft.error("5", NO_RECORD_IN_FORCE, p.symbol)
            else:
                plan.actions.append(AttachStop(p, record))
            return True
        if stop is not None and record is not None and record.tpsl_mode == "Full":
            # A recorded native trail moves its stop toward the market, never away (Sec.10.7):
            # its stop is the recorded one while tighter, and is put back if ever looser.
            trailed = record.trailing_distance is not None and p.trailing_stop_distance is not None
            if loosens(record.position_side, record.trigger_price, stop):
                plan.actions.append(RestoreStop(p, record))
            elif not trailed and loosens(record.position_side, stop, record.trigger_price):
                plan.actions.append(PageTighter(p))
        return False

    # --- The remediation and the report -----------------------------------------------------------

    async def remediate(self, plan: Plan) -> None:
        """The plan applied in 24 Sec.8.5's order (steps 2, 3a, 3b, 3c, 3d, 4, then 5): one
        action's failure goes to `errors` and never ends the pass, so step 5 always runs (C-2.6)."""
        await _Remediation(self, plan).run()

    def finish(self, plan: Plan) -> ReconcileReport:
        """The pass's report, its run time from its fetch to now."""
        return plan.draft.freeze(max(0, (self._now() - plan.fetched.started_us) // 1000))

    def page_once(self, reason: str, account_id: AccountId, *key: str) -> None:
        """One P1 page per reason and subject while its episode lasts, across passes: a standing
        item pages once, never on every 30 s pass, and pages again once a pass has read its
        episode over (`rearm`). Logged by its reason and account."""
        if self._first(reason, account_id, key):
            _log().critical(
                "reconcile_paged", reason=reason, account_id=str(account_id), cv_page=True
            )
            self._p.pager.raise_alert("page", _PAGES[reason], machine_kind=_KIND)

    def alert_once(self, reason: str, account_id: AccountId, *key: str) -> None:
        """An alert, once per subject's episode as `page_once` pages: a finding listed again on
        every pass raises no second alert (24 Sec.8.5)."""
        if self._first(reason, account_id, key):
            self._p.pager.raise_alert("alert", _ALERTS[reason], machine_kind=_KIND)

    def rearm(
        self,
        reasons: Collection[str],
        account_id: AccountId,
        ended: Callable[[tuple[str, ...]], bool],
    ) -> None:
        """Ends the episodes of the account's marks under `reasons` whose subject `ended` says
        this pass read over, so each pages again when it is next found."""
        over = [m for m in self._paged if m[0] in reasons and m[1] == account_id and ended(m[2])]
        for mark in over:
            del self._paged[mark]

    def _first(self, reason: str, account_id: AccountId, key: tuple[str, ...]) -> bool:
        """Marks a subject's episode, true the first time (a bounded memory, C-2.18: past the
        bound the oldest mark is forgotten)."""
        mark = (reason, account_id, key)
        if mark in self._paged:
            return False
        self._paged[mark] = None
        if len(self._paged) > PAGED_BOUND:
            self._paged.popitem(last=False)
        return True


class _Unread(Exception):  # an exchange read this pass did not make or that failed
    def __init__(self, kind: str) -> None:
        super().__init__(kind)
        self.kind = kind


class _AnotherAccount(Exception):  # a store or adapter answered another account's row (C-12.4)
    pass


def _kind(exc: BaseException) -> str:
    return exc.kind if isinstance(exc, _Unread) else type(exc).__name__


class _OrderDiff:
    """Steps 2 to 3d of one pass's diff (24 Sec.8.5), planned in its order: reads only."""

    def __init__(self, reconciler: Reconciler, plan: Plan) -> None:
        self._r, self._plan, self._f = reconciler, plan, plan.fetched
        self._p, self._now = reconciler.ports, reconciler.now_us
        self._draft = plan.draft
        self._account = self._f.account.account_id
        self._bound: dict[str, OrderRow] = {}
        self._unbound: dict[str, OrderRow] = {}
        self._by_xid: dict[str, OrderRow | None] = {}
        self._by_link: dict[str, OrderRow | None] = {}
        self._reads: dict[tuple[str, str], Order | None] = {}
        self._failed: dict[tuple[str, str], str] = {}
        self._limited = False  # a rate-limit answer ends this pass's reads (C-12.7)
        self._planned: set[str] = set()  # exchange order ids 3a to 3c bind or record
        self._for_finding: dict[str, list[Execution]] = {}
        self._entries: dict[str, WaitingExecution] = {}
        self._waiting: list[Execution] = []

    def _add(self, action: Action) -> None:
        self._plan.actions.append(action)

    async def run(self) -> None:
        p = self._p
        self._port = p.router.port_for(self._f.account.environment)
        rows = tuple(await _bounded(p.orders.unfinished_for(self._account), PORT_TIMEOUT_S))
        if any(row.exchange_account_id != self._account for row in rows):
            raise self._another("unfinished_for")
        self._bound = {r.exchange_order_id: r for r in rows if r.exchange_order_id}
        self._unbound = {r.order_link_id: r for r in rows if not r.exchange_order_id}
        self._by_xid.update(self._bound)
        self._plan.ours = frozenset(x for x, r in self._bound.items() if r.state != "untracked")
        self._plan.untracked = sum(1 for row in rows if row.state == "untracked")
        await self._step_2(await self._unapplied())
        paired, rest = self._step_3a()
        await self._step_3b(rows, paired)
        for fills in self._for_finding.values():  # a found row's fills no finding took: kept
            self._plan.actions.extend(KeepFill(e, empty_read=False) for e in fills)
        await self._step_3c(rest)
        await self._step_3d()
        if all(e.kind != _AnotherAccount.__name__ for e in self._draft.errors):
            self._r.rearm((_ANOTHER,), self._account, lambda _key: True)  # read none: over

    async def _unapplied(self) -> list[Execution]:
        """Step 1's fills and the hand-overs', deduped by `exec_id`, less those stored already
        (S4), in `(ts_exec, seq)` order; a stored hand-over is settled (pruned)."""
        self._entries = {w.execution.exec_id: w for w in self._f.waiting_executions}
        unique: dict[str, Execution] = {}
        for e in (*self._f.executions, *(w.execution for w in self._f.waiting_executions)):
            unique.setdefault(e.exec_id, e)
        if not unique:
            return []
        call = self._p.executions.stored(self._account, tuple(unique))
        stored = await _bounded(call, PORT_TIMEOUT_S)
        for exec_id in stored:
            if (entry := self._entries.get(exec_id)) is not None:
                self._plan.settled.append(entry.entry_id)
        fresh = (e for e in unique.values() if e.exec_id not in stored)
        return sorted(fresh, key=lambda e: (e.ts_exec, e.seq))

    def _entry_id(self, e: Execution) -> int | None:
        entry = self._entries.get(e.exec_id)
        return None if entry is None else entry.entry_id

    async def _step_2(self, fills: Sequence[Execution]) -> None:
        """Each fill to the row bound to its order, never by its link id alone; a found row's
        (`unknown`, `quarantined`, `untracked`) ride its finding (`_FINDABLE`); the rest wait for
        3d."""
        for e in fills:
            try:
                if e.exec_type != "trade":
                    self._add(StoreFill(e))
                    continue
                row = await self._row_by_xid(e.exchange_order_id)
                if row is None:
                    self._waiting.append(e)
                elif row.state in _FINDABLE:
                    self._for_finding.setdefault(e.exchange_order_id, []).append(e)
                else:
                    self._add(PushFill("2", row, e, self._entry_id(e)))
            except Exception as exc:
                self._draft.error("2", _kind(exc), e.exec_id)

    def _step_3a(self) -> tuple[set[UUID], list[Order]]:
        """Present both sides: a bound row takes the exchange's state; an unbound `unknown` or
        `quarantined` row only after the full match; the rest are 3c's."""
        paired: set[UUID] = set()
        rest: list[Order] = []
        for r in self._f.remote_open:
            try:
                row = self._bound.get(r.exchange_order_id)
                if row is not None:
                    paired.add(row.id)
                    self._present(row, r, "3a", "corrected")
                    continue
                named = self._unbound.get(r.order_link_id)
                if named is None or named.state not in _BOUND_BY_MATCH:
                    rest.append(r)
                    continue
                paired.add(named.id)
                self._planned.add(r.exchange_order_id)
                if full_match(named, r):
                    self._find(named, r, "3a", "corrected")
                else:
                    self._add(Mismatch("3a", named, r))
            except Exception as exc:
                self._draft.error("3a", _kind(exc), r.order_link_id)
        return paired, rest

    def _present(
        self,
        row: OrderRow,
        order: Order,
        step: Step,
        listed: Literal["corrected", "resolved_from_history"],
    ) -> None:
        """A bound row's order as the exchange shows it: a finding for a row B1 lets reconcile
        find, else the stream's own facts (BQ-8); a fill moves an order, never its status."""
        if row.state in _FINDABLE:
            self._find(row, order, step, listed)
            return
        event = order_event(order)  # `ValueError` for a status 24 Sec.8.12 does not map
        if event is not None and not (event == "TRIGGERED" and row.state == "triggered"):
            self._add(PushFact(step, row, order, event, listed))

    def _find(
        self,
        row: OrderRow,
        order: Order,
        step: Step,
        listed: Literal["corrected", "resolved_from_history"],
    ) -> None:
        xid = order.exchange_order_id
        fills = sorted(
            [
                *self._for_finding.get(xid, ()),
                *(e for e in self._waiting if e.exchange_order_id == xid),
            ],
            key=lambda e: (e.ts_exec, e.seq),
        )
        sends = found_sends(row, order, fills, pass_id=self._f.pass_id, ts_event=self._f.window[1])
        if sends is None:  # the venue's totals are not the fills read: nothing is adopted
            # An `untracked` row's stands, its fills kept below (24 Sec.8.5); any other holds.
            kind = UNTRACKED_FILLS_UNREAD if row.state == "untracked" else FILLS_UNREAD
            self._draft.error(step, kind, row.order_link_id)
            return
        self._for_finding.pop(xid, None)
        self._waiting = [e for e in self._waiting if e.exchange_order_id != xid]
        entries = tuple(i for i in (self._entry_id(e) for e in fills) if i is not None)
        self._add(Find(step, row, sends, listed, entries))

    async def _step_3b(self, rows: Sequence[OrderRow], paired: set[UUID]) -> None:
        """Local rows absent remotely, looked up in the order history, one read each; a request
        in flight, and a held row, wait for their own answer."""
        f, now = self._f, self._now()
        for row in rows:
            if row.id in paired or row.state in _LEFT_TO_THEIR_REQUEST:
                continue
            try:
                hist = await self._history_of(row)
                if hist is not None and (row.exchange_order_id or full_match(row, hist)):
                    if not row.exchange_order_id:
                        self._planned.add(hist.exchange_order_id)
                    self._present(row, hist, "3b", "resolved_from_history")
                elif hist is not None:
                    self._planned.add(hist.exchange_order_id)
                    self._add(Mismatch("3b", row, hist))
                elif row.state == "unknown":
                    created = _us(row.created_ts)
                    if not history_covers(f.retention, created, now):
                        self._add(HoldPastSpan(row))
                    else:
                        self._add(Miss(row, miss_code(f.retention, created, now)))
                else:
                    self._add(Miss(row, None))
            except Exception as exc:
                self._draft.error("3b", _kind(exc), row.order_link_id)

    async def _step_3c(self, rest: Sequence[Order]) -> None:
        """Open orders no live row takes, and the orders a lookup or a mismatch handed over: a
        recorded stop's TP/SL order is materialised; any other is recorded `untracked` (a foreign
        stop among them) or, where a final or another account's row holds its id, an anomaly.
        No OMS intent opens the freeze first (SR-E27-19). An anomaly's episode ends once its
        order is none of these, so it alerts again if it comes back (24 Sec.8.5)."""
        p = self._p
        items = [(r, None) for r in rest] + [(w.order, w.entry_id) for w in self._f.waiting_orders]
        here = {(r.exchange_order_id,) for r, _ in items}
        self._r.rearm(_ANOMALY_ALERTS, self._account, lambda key: key not in here)
        for r, entry_id in items:
            try:
                xid = r.exchange_order_id
                if xid in self._planned:
                    continue
                b = await self._row_by_xid(xid)
                if b is not None and not (b.state in _TERMINAL and entry_id is None):
                    if entry_id is not None:
                        self._plan.settled.append(entry_id)
                    continue  # recorded already: 3a, 3b or an earlier pass
                stop = is_stop_claim(r) and b is None
                if stop and (record := self._matching(r)) is not None:
                    self._planned.add(xid)
                    self._add(Materialise("3c", record, r, None, entry_id))
                    continue
                o = await self._row_by_link(r.order_link_id)
                elsewhere = o is None and await _bounded(
                    p.orders.link_id_taken(r.order_link_id), PORT_TIMEOUT_S
                )
                key: str | None
                if b is not None or elsewhere or (o is not None and o.state in _TERMINAL):
                    key = None  # S6: a final row's, or an id only a final or another's row holds
                elif o is None:
                    key = r.order_link_id  # foreign (its ext- key), or ours whose row was lost
                elif o.state == "held" or o.exchange_order_id:
                    key = ext_key(xid)  # not that row's order: recorded beside it
                else:
                    continue  # draft, validated or submitting: its own send decides (rule 3)
                if key is None:
                    self._add(Anomaly(r, no_intent=b is None))
                else:
                    self._planned.add(xid)
                    self._add(Adopt(r, key, stop, no_intent=b is None, entry_id=entry_id))
            except Exception as exc:
                self._draft.error("3c", _kind(exc), r.order_link_id)

    async def _step_3d(self) -> None:
        """The fills step 2 found no bound row for, once 3a to 3c have bound or recorded their
        orders: each to its row once, or to an unbound live row's reorder buffer, or listed with
        no OMS intent once its order is read; a read that failed or found nothing decides nothing
        yet, and the fill is kept for the next pass."""
        for e in self._waiting:
            entry = self._entries.get(e.exec_id)
            entry_id = None if entry is None else entry.entry_id
            try:
                xid = e.exchange_order_id
                if xid in self._planned:
                    self._add(LateFill(e, entry_id))
                    continue
                named = await self._row_by_link(e.order_link_id)
                if named is not None and takes_waiting(named):
                    self._add(PushFill("3d", named, e, entry_id))
                    continue
                if entry is not None and entry.decided:
                    self._add(Unpaired(e, None, decided=True))
                    continue
                order = await self._history(("xid", xid))
            except Exception as exc:  # a read that fails decides nothing (Sec.8.5 step 3d)
                self._draft.error("3d", _kind(exc), e.exec_id)
                self._add(KeepFill(e, empty_read=False))
                continue
            if order is not None and is_stop_claim(order) and (rec := self._matching(order)):
                self._planned.add(order.exchange_order_id)
                self._add(Materialise("3d", rec, order, e, entry_id))
            elif order is None and not self._empty_read_decides(entry):
                self._add(KeepFill(e, empty_read=True))
            else:
                self._add(Unpaired(e, order, decided=False))

    # --- Reads, each once a pass -----------------------------------------------------------------

    async def _row_by_xid(self, xid: str) -> OrderRow | None:
        """The account's row bound to the exchange order id, in any state (`ux_orders_exch_id`)."""
        if xid not in self._by_xid:
            call = self._p.orders.get_by_exchange_order_id(self._account, xid)
            row = await _bounded(call, PORT_TIMEOUT_S)
            if row is not None and (row.exchange_account_id, row.exchange_order_id) != (
                self._account,
                xid,
            ):
                raise self._another("get_by_exchange_order_id", xid)
            self._by_xid[xid] = row
        return self._by_xid[xid]

    async def _row_by_link(self, link: str) -> OrderRow | None:
        if link not in self._by_link:
            call = self._p.orders.get_by_link_id(self._account, link)
            row = await _bounded(call, PORT_TIMEOUT_S)
            if row is not None and row.exchange_account_id != self._account:
                raise self._another("get_by_link_id", link)
            self._by_link[link] = row
        return self._by_link[link]

    async def _history_of(self, row: OrderRow) -> Order | None:
        """3b's lookup: by the bound exchange order id, the only key an `ext-` row has, else by
        the row's own link id, never an `ext-` one on the wire (24 Sec.14.2 rule 11)."""
        xid = row.exchange_order_id
        if xid:
            return await self._history(("xid", xid))
        link = row.order_link_id
        if OUR_ID.fullmatch(link) is None:
            raise _Unread("unreadable_id")
        return await self._history(("link", link))

    async def _history(self, key: tuple[Literal["xid", "link"], str]) -> Order | None:
        """One order-history read a pass per key (by exchange order id, or by our own link id);
        a rate-limit answer ends the pass's reads."""
        if key in self._failed:
            raise _Unread(self._failed[key])
        if key in self._reads:
            return self._reads[key]
        if self._limited:
            raise _Unread("rate_limited")
        kind, value = key
        account = self._f.account
        call = (
            self._port.order_history(account, exchange_order_id=value)
            if kind == "xid"
            else self._port.order_history(account, order_link_id=value)
        )
        try:
            orders = await _bounded(call, READ_TIMEOUT_S)
        except Exception as exc:
            self._limited = self._limited or isinstance(exc, _RATE_LIMITED)
            self._failed[key] = type(exc).__name__
            raise _Unread(type(exc).__name__) from None
        if any(o.account_id != self._account for o in orders):
            raise self._another("order_history", value)
        found = {
            o.exchange_order_id: o
            for o in orders
            if (o.exchange_order_id if kind == "xid" else o.order_link_id) == value
        }
        if len(found) > 1:
            raise _Unread("ambiguous")
        self._reads[key] = next(iter(found.values()), None)
        return self._reads[key]

    def _another(self, read: str, subject: str | None = None) -> _AnotherAccount:
        """A read of the diff answered a row of another account (BQ-12, C-2.11): logged by the
        read and the id it asked for, never the row, and paged once per episode; the step that
        made the read lists it in `errors`."""
        _log().critical(
            "reconcile_row_of_another_account", account_id=str(self._account), read=read,
            subject=subject, pass_id=self._f.pass_id,
        )  # fmt: skip
        self._r.page_once(_ANOTHER, self._account)
        return _AnotherAccount()

    def _matching(self, order: Order) -> RecordedStopRow | None:
        """The record of the order's own position it matches (Sec.8.8 rule 6), from the copy."""
        key = (order.symbol, order.position_idx)
        records = [r for r in self._f.records if (r.symbol, r.position_idx) == key]
        return matching_record(order, first_bindable(order, records))

    def _empty_read_decides(self, entry: WaitingExecution | None) -> bool:
        """An empty read decides only once an earlier one counted a cadence before exists."""
        if entry is None or entry.empty_reads < 1 or entry.first_empty_read_at is None:
            return False
        return _us(entry.first_empty_read_at) <= self._now() - EMPTY_READ_CADENCE_US


_PROTECTIVE: Final = (AttachStop, PageNaked, RestoreStop, PageTighter)
#: Each page's summary: fixed text that names no account, symbol or value (C-12.6).
_PAGES: Final[Mapping[str, str]] = {
    "oms_unknown_past_history": "An unknown order is older than the venue's history span.",
    "oms_naked_no_record_in_force": "An open position has no stop and no recorded stop in force.",
    "oms_naked_attach_failed": "Reconciliation could not attach a naked position's recorded stop.",
    "oms_stop_restore_refused": "The venue refused to put a recorded stop back.",
    "oms_stop_tighter_than_recorded": "A position's stop is tighter than the recorded one.",
    "oms_position_drift": "Reconciliation corrected a position the OMS held otherwise.",
    "oms_freeze_failed": "Reconciliation could not freeze an account for a finding with no intent.",
    _ANOTHER: "Reconciliation read a row of another account.",
    _UNREADABLE: "A hand-over entry no longer reads; it waits for the Owner.",
}
#: Each alert's summary, as fixed as a page's.
_ALERTS: Final[Mapping[str, str]] = {"oms_reconcile_anomaly": "Reconciliation met an anomaly."}
#: A naked position's pages: its episode ends when a pass reads the position protected or flat.
_NAKED_PAGES: Final = frozenset({"oms_naked_no_record_in_force", "oms_naked_attach_failed"})
#: An anomaly's alert: its episode ends when its order is no longer among 3c's orders.
_ANOMALY_ALERTS: Final = frozenset({"oms_reconcile_anomaly"})


def _step_of(action: Action) -> Step:
    match action:
        case StoreFill() | FixPosition():
            return "2" if isinstance(action, StoreFill) else "4"
        case PushFill(step=step) | PushFact(step=step) | Find(step=step) | Mismatch(step=step):
            return step
        case Materialise(step=step):
            return step
        case Miss() | HoldPastSpan():
            return "3b"
        case Adopt() | Anomaly():
            return "3c"
        case LateFill() | KeepFill() | Unpaired():
            return "3d"
        case _:
            return "5"


def _subject(action: Action) -> str | None:
    match action:
        case StoreFill(e) | PushFill(execution=e) | LateFill(e) | KeepFill(e) | Unpaired(e):
            return e.exec_id
        case PushFact(row=row) | Find(row=row) | Mismatch(row=row) | Miss(row) | HoldPastSpan(row):
            return row.order_link_id
        case Adopt(order=order) | Anomaly(order=order) | Materialise(order=order):
            return order.exchange_order_id
        case FixPosition(p) | AttachStop(p) | PageNaked(p) | RestoreStop(p) | PageTighter(p):
            return p.symbol


class _Remediation:
    """The plan applied in 24 Sec.8.5's order; step 5 after every other step, whatever they did."""

    def __init__(self, reconciler: Reconciler, plan: Plan) -> None:
        self._r, self._plan, self._f = reconciler, plan, plan.fetched
        self._draft = plan.draft
        self._p = reconciler.ports
        self._account = self._f.account.account_id
        self._pid = self._f.pass_id
        self._settled: list[int] = list(plan.settled)
        self._listed: set[tuple[str, str]] = set()

    async def run(self) -> None:
        for action in self._plan.actions:
            if not isinstance(action, _PROTECTIVE):
                await self._one(action)
        await self._prune()
        for action in self._plan.actions:  # step 5 runs whatever came before (C-2.6)
            if isinstance(action, _PROTECTIVE):
                await self._one(action)

    async def _one(self, action: Action) -> None:
        try:
            await self._apply(action)
        except ReconcileAnomaly:  # S6, audited and counted by the facade: no mutation
            self._list("anomalies", _subject(action) or "")
        except Exception as exc:  # one action's failure never ends the pass (BQ-18)
            self._draft.error(_step_of(action), type(exc).__name__, _subject(action))

    def _list(self, name: str, value: str) -> None:
        if value and (name, value) not in self._listed:
            self._listed.add((name, value))
            getattr(self._draft, name).append(value)

    async def _b1_command(
        self, row: OrderRow, event: CommandEvent, payload: Mapping[str, Any]
    ) -> str:
        call = self._p.machines.command(self._account, row.id, event, payload, actor="system")
        return await _bounded(call, FACADE_TIMEOUT_S)

    async def _b1_push(self, row: OrderRow, event: PushEvent, payload: Mapping[str, Any]) -> None:
        await _bounded(
            self._p.machines.push(self._account, row.id, event, payload), FACADE_TIMEOUT_S
        )

    async def _apply(self, action: Action) -> None:
        p = self._p
        match action:
            case StoreFill(e):
                await _bounded(p.executions.insert(new_execution(e)), PORT_TIMEOUT_S)
            case PushFill(_, row, e, entry_id):
                await self._fill(row, e, entry_id)
            case LateFill(e, entry_id):
                recorded = await self._reread(e.exchange_order_id, e)
                if recorded is None:  # its order not recorded, or another account's row: kept
                    await self._keep(e, empty_read=False)
                elif recorded.state == "untracked":  # its finding carries it, next pass
                    await self._keep(e, empty_read=False)
                else:
                    await self._fill(recorded, e, entry_id)
            case PushFact(_, row, order, event, listed):
                await self._b1_push(row, event, fact_push(order, row, self._f.window[1]))
                self._list(listed, row.order_link_id)
            case Find(_, row, sends, listed, entry_ids):
                answered: str = row.state
                for send in sends:  # in `found_sends`' order; a send that fails ends them
                    if isinstance(send, FoundCommand):
                        answered = await self._b1_command(row, send.event, send.payload)
                    else:
                        await self._b1_push(row, send.event, send.payload)
                self._settled.extend(entry_ids)
                if row.state != "untracked":
                    self._list(listed, row.order_link_id)
                elif answered != "untracked":  # closed (`filled`, `cancelled`): a correction
                    self._list(listed, row.order_link_id)
                    self._plan.count_untracked(-1)
            case Mismatch(_, row, order):
                await self._no_intent("order", order.exchange_order_id, order.exchange_placed)
                await _bounded(p.handovers.hand_over_order(self._account, order), PORT_TIMEOUT_S)
                xid = order.exchange_order_id
                await self._b1_command(
                    row, "MISMATCH", {"exchange_order_id": xid, "pass_id": self._pid}
                )
                self._list("held", row.order_link_id)
                await self._record(order, ext_key(xid), stop=False, entry_id=None)
            case Miss(row, code):
                payload: dict[str, Any] = {"pass_id": self._pid}
                if code is not None:
                    payload["reject_code"] = code
                state = await self._b1_command(row, "RECON_MISS", payload)
                if row.state not in ("unknown", "untracked"):
                    self._list("newly_unknown", row.order_link_id)
                elif state in ("rejected", "cancelled"):  # the second miss in a row
                    self._list("abandoned", row.order_link_id)
                    if row.state == "untracked":
                        self._plan.count_untracked(-1)
            case HoldPastSpan(row):
                self._r.page_once("oms_unknown_past_history", self._account, row.order_link_id)
            case Adopt(order, key, stop, no_intent, entry_id):
                if no_intent:
                    await self._no_intent("order", order.exchange_order_id, order.exchange_placed)
                await self._record(order, key, stop=stop, entry_id=entry_id)
            case Anomaly(order, no_intent):
                if no_intent:
                    await self._no_intent("order", order.exchange_order_id, order.exchange_placed)
                self._anomaly(order)
            case Materialise(_, record, order, fill, entry_id):
                await self._materialise(record, order, fill, entry_id)
            case KeepFill(e, empty_read):
                await self._keep(e, empty_read=empty_read)
            case Unpaired(e, order, decided):
                if not decided:  # no OMS intent: frozen first, then kept and decided
                    placed = order is not None and order.exchange_placed
                    await self._no_intent("execution", e.exec_id, placed)
                    await self._keep(e, empty_read=False)
                    await _bounded(p.handovers.decide(self._account, e.exec_id), PORT_TIMEOUT_S)
                self._list("unpaired", e.exec_id)
            case FixPosition(position):
                await self._position(position)
            case AttachStop(position, record):
                await self._attach(position, record)
            case PageNaked(position):
                self._r.page_once(
                    "oms_naked_no_record_in_force", self._account, position.symbol,
                    str(position.position_idx),
                )  # fmt: skip
            case RestoreStop(position, record):
                await self._restore(position, record)
            case PageTighter(position):
                shown = str(position.stop_loss)  # the page's key, never logged
                self._r.page_once(
                    "oms_stop_tighter_than_recorded", self._account, position.symbol, shown
                )
                self._list("sl_tighter", position.symbol)

    async def _fill(self, row: OrderRow, e: Execution, entry_id: int | None) -> None:
        """A fill to its row, as the stream sends it; one the row's final state refuses is an S6
        anomaly, audited by the facade, and the row is listed."""
        try:
            await self._b1_push(row, "EXEC", fill_push(e, row))
        except ReconcileAnomaly:
            self._list("anomalies", row.order_link_id)
            return
        self._list("corrected", row.order_link_id)
        if entry_id is not None:
            self._settled.append(entry_id)

    async def _keep(self, e: Execution, *, empty_read: bool) -> None:
        call = self._p.handovers.hand_over_execution(self._account, e, empty_read=empty_read)
        await _bounded(call, PORT_TIMEOUT_S)

    async def _reread(self, xid: str, e: Execution) -> OrderRow | None:
        """The row bound to a fill's order (3d), read again once this pass bound or recorded the
        order. A row of another account (BQ-12, C-2.11) is answered as none, as the diff's reads
        refuse one: logged by the read and the id asked for, never the row, paged once per episode,
        and listed against the fill, which holds the watermark; the caller keeps the fill."""
        call = self._p.orders.get_by_exchange_order_id(self._account, xid)
        row = await _bounded(call, PORT_TIMEOUT_S)
        if row is None or row.exchange_account_id == self._account:
            return row
        _log().critical(
            "reconcile_row_of_another_account", account_id=str(self._account),
            read="get_by_exchange_order_id", subject=xid, pass_id=self._pid,
        )  # fmt: skip
        self._r.page_once(_ANOTHER, self._account)
        self._draft.error("3d", _AnotherAccount.__name__, e.exec_id)
        return None

    async def _no_intent(self, finding: Finding, key: str, exchange_placed: bool) -> None:
        """No OMS intent (SR-E27-19): the freeze, E39-T04's one setter, or for an order the
        venue placed itself its audit and page alone (24 Sec.8.10). A failure pages and ends
        neither the action nor the pass."""
        try:
            if exchange_placed:
                call = self._p.exchange_placed.exchange_placed(
                    self._account, finding=finding, key=key
                )
            else:
                call = self._p.lockout.open(self._account, finding=finding, key=key)
            await _bounded(call, PORT_TIMEOUT_S)
        except Exception as exc:
            _log().error(
                "reconcile_freeze_failed", account_id=str(self._account), finding=finding,
                failure=type(exc).__name__,
            )  # fmt: skip
            self._r.page_once("oms_freeze_failed", self._account, finding, key)
            self._draft.error("3c" if finding == "order" else "3d", "freeze_failed", key)

    async def _record(self, order: Order, key: str, *, stop: bool, entry_id: int | None) -> None:
        """`adopt_untracked`: the order recorded `untracked` under `key`, audited ahead (C-2.9).
        An order the table cannot hold, or whose id a row holds already (`ux_orders_exch_id`), is
        an anomaly, never merged (24 Sec.8.5)."""
        try:
            new = adopted_row(self._r.new_id(), self._account, order, key, stop=stop)
        except (ValueError, KeyError):
            self._anomaly(order)
            return
        audit = self._p.adoptions.adopted(
            self._account, row_id=new.id, order=order, pass_id=self._pid
        )
        await _bounded(audit, PORT_TIMEOUT_S)
        env = self._f.account.environment
        try:
            call = self._p.machines.discover(new, environment=env, pass_id=self._pid)
            await _bounded(call, FACADE_TIMEOUT_S)
        except OrderStepRefused as exc:
            if not exc.deterministic:
                raise
            self._anomaly(order)
            return
        self._list("foreign_stops" if stop else "untracked", key)
        self._plan.count_untracked(1)
        if entry_id is not None:
            self._settled.append(entry_id)

    def _anomaly(self, order: Order) -> None:
        """`ReconcileAnomaly` (S6): logged and listed on every pass, alerted once per episode
        (24 Sec.8.5: repeated, with no second page); nothing is changed."""
        _log().error(
            "reconcile_anomaly", account_id=str(self._account),
            exchange_order_id=order.exchange_order_id, pass_id=self._pid,
        )  # fmt: skip
        self._r.alert_once("oms_reconcile_anomaly", self._account, order.exchange_order_id)
        self._list("anomalies", order.order_link_id)

    async def _materialise(
        self, record: RecordedStopRow, order: Order, fill: Execution | None, entry_id: int | None
    ) -> None:
        """A recorded stop's order (Sec.8.3 rule 7): its row under "Adopted rows"'s id, bound to
        the record in the same transaction, `source: reconcile`; then the fill that showed it.
        In 3c `entry_id` is the order's hand-over entry, settled once its row exists; in 3d it is
        the fill's, settled only once `_fill` applied the fill, as `PushFill` settles one, so a
        re-read that fails, answers another account's row or none, or an `EXEC` that fails,
        leaves the fill in `oms_handovers` for the next pass (24 Sec.8.5 step 3d)."""
        p, xid = self._p, order.exchange_order_id
        link = order.order_link_id
        if OUR_ID.fullmatch(link) is None:
            link = ext_key(xid)
        else:  # "Adopted rows": its own id only while no row of the account holds it
            holder = await _bounded(p.orders.get_by_link_id(self._account, link), PORT_TIMEOUT_S)
            link = link if holder is None else ext_key(xid)
        qty = self._size_of(record, order, fill)
        new = materialised_row(self._r.new_id(), self._account, record, order, link, qty)
        binds = RecordedStopBind(record_id=record.id, kind=record.kind)
        call = p.machines.materialise(
            new, environment=self._f.account.environment, pass_id=self._pid, binds=binds
        )
        await _bounded(call, FACADE_TIMEOUT_S)
        if fill is None:  # 3c: the order's hand-over entry, now that its row exists
            if entry_id is not None:
                self._settled.append(entry_id)
            return
        row = await self._reread(xid, fill)
        if row is None:
            await self._keep(fill, empty_read=False)
        else:
            await self._fill(row, fill, entry_id)  # settled once applied

    def _size_of(self, record: RecordedStopRow, order: Order, fill: Execution | None) -> Decimal:
        """The materialised row's provisional size (the 2026-10-26 ruling): the order's; for a
        Full-mode order showing none, its fill's, else the position it closes as step 1 read it.
        `ValueError` when none is known: nothing is decided, and the next pass reads again."""
        if order.qty > 0:
            return order.qty
        if record.tpsl_mode == "Full":
            if fill is not None:
                return fill.qty
            side = {"Buy": "buy", "Sell": "sell"}[record.position_side]
            for p in self._f.positions:
                key = (p.symbol, p.position_idx, p.side)
                if key == (order.symbol, order.position_idx, side) and p.qty > 0:
                    return p.qty
        raise ValueError("no size is known for the recorded stop's order")

    async def _position(self, position: Position) -> None:
        """Step 4: exchange is truth; the drift is reported with both values and alerted."""
        call = self._p.positions.apply(position, pass_id=self._pid)
        seen = await _bounded(call, PORT_TIMEOUT_S)
        if seen is None:
            return
        self._draft.position_drift.append(
            PositionDrift(
                position.symbol,
                position.position_idx,
                seen.side,
                seen.qty,
                position.side,
                position.qty,
            )
        )
        _log().critical(
            "reconcile_position_drift", account_id=str(self._account), symbol=position.symbol,
            position_idx=position.position_idx, pass_id=self._pid,
        )  # fmt: skip
        self._p.pager.raise_alert("page", _PAGES["oms_position_drift"], machine_kind=_KIND)

    async def _attach(self, position: Position, record: RecordedStopRow) -> None:
        """BQ-9: the record in force attached through the recorded-stop writer, on the `critical`
        lane, and counted in `naked_position_alerts_total`."""
        self._r.count_naked()
        call = self._p.protective.attach_recorded(
            self._f.account, position, record, pass_id=self._pid
        )
        outcome = await _bounded(call, FACADE_TIMEOUT_S)
        if outcome == "sent":
            self._list("sl_repaired", position.symbol)
            return
        if outcome == "not_looser":  # the writer's own read: flat or protected since step 1
            return
        self._draft.error("5", f"attach_{outcome}", position.symbol)
        self._r.page_once(
            "oms_naked_attach_failed", self._account, position.symbol, str(position.position_idx)
        )

    async def _restore(self, position: Position, record: RecordedStopRow) -> None:
        """The recorded stop put back over a looser Full-mode stop; a refusal pages once and the
        position is tested again on every later pass (24 Sec.8.5)."""
        call = self._p.protective.restore_recorded(
            self._f.account, position, record, pass_id=self._pid
        )
        outcome = await _bounded(call, FACADE_TIMEOUT_S)
        if outcome == "sent":
            self._list("sl_restored", position.symbol)
        elif outcome == "refused":
            self._r.page_once(
                "oms_stop_restore_refused", self._account, position.symbol, str(record.id)
            )
            self._list("sl_restore_refused", position.symbol)
        elif outcome == "not_sent":
            self._draft.error("5", "restore_not_sent", position.symbol)

    async def _prune(self) -> None:
        """The hand-overs whose fill is paired or whose order has a row (21 Sec.3.3.12)."""
        settled = sorted(set(self._settled))
        if not settled:
            return
        try:
            await _bounded(self._p.handovers.prune(self._account, settled), PORT_TIMEOUT_S)
        except Exception as exc:
            self._draft.error("3d", type(exc).__name__)


_KIND: Final = "oms.reconciler"
