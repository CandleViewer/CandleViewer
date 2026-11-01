"""The OMS's command port: B1's `CommandPort` (E29-T04 #913; 24-internal-schemas.md Sec.8.3,
Sec.8.4, Sec.8.6, Sec.8.8).

B1's services call it (`statechart/bindings/b01_order.py`, `_dispatch`): `place` in `submitting`,
`lookup` before a create this process did not begin, `attach_stop` in `sl_pending`, `cancel` in
`cancel_pending` and a KILL's, `amend` in `amend_pending`. Every call reaches the exchange through
`routing.TradingRouter`, so it is signed for its account's own environment (C-2.11), and every
answer is a mapping B1's guards read (24 Sec.14.4 `OrderAck`), never the exchange's text
(SR-E29-09). Logs carry ids, codes and state names, never a price or a size (21 Sec.12).

**place.** The request is built from the stored order only: the `NewOrder` the pipeline
registered (`expect`), else the stored row, so a retry sends the same `order_link_id` and the same
native stop (C-2.10, C-2.6). A stop or take-profit that is not a finite price above zero is
refused before anything is sent, whatever the exchange port checks (#2877 ruling 2), and so is an
order that is not reduce-only and names no stop (C-2.6, SEC-2B1-04), which `FirstPersist.check`
and B1's gate already refuse upstream. A rule's order (its row's `origin`, 21 Sec.3.3.4) takes the
`entry` lane, a reduce-only one included, so a create a restart resumes keeps it (24 Sec.8.4
"Rule-originated orders" item 3); any other reduce-only order with a reducing intent takes the
`critical` lane, any other the `entry` lane (SR-E29-01, 24 Sec.8.7). A registered order is a first
send (`place_or_adopt`). One not registered is a create a restart resumes (SR-E29-15, [LANE-26]),
in this order:

1. the id is looked up first, whatever the switches say, as reading is never an order: an order
   found is adopted and nothing is sent (C-2.10);
2. the synchronous switches, then the clock halt, are asked (C-2.21): a refusal is
   `ResendRefused`, nothing sent, so no create is re-sent under a clock a `10002` tripped
   (SEC-2B1-01). A serving loop that has stalled, and a clock not composed or not measured yet,
   are a third outcome: the switches' fence (#913 L4) or the halt (ruling Q8) lets `OmsNotReady`
   through, logged as a refusal is (`oms_resend_refused`, with its code) and raised as it is,
   nothing sent, so B1 lands the order in `unknown` all the same;
3. where history never expires (`order_retention_days` None: live), a create older than
   `LIVE_RESEND_MAX_AGE_S` is never re-sent. Within the venue's history span
   (`LIVE_HISTORY_SPAN_S`, 24 h) the miss means it never landed: it ends `rejected` with
   `b01.EXPIRED_UNSENT`, its `oms.resend_refused` record (its age and the bound) written ahead
   and the user alerted (`OrderNotices`, `alert` `order_never_sent`, "not found within the
   venue's 24 h history"). At or past the span the miss proves nothing (24 Sec.14.1): it is
   answered as an empty lookup, so B1 lands it in `unknown` for reconciliation, and its entry's
   attach rows are never voided blind (SEC-2B1-02);
4. otherwise `adopt_or_resend` looks once more and re-sends the same request while history still
   covers the id (Sec.8.3 rule 6: demo keeps its 6 days).

One `SUBMIT_TIMEOUT_S` deadline bounds all of `place` (CR-2B1-04): the stored row's and the
account's reads, the exchange calls, and the answer's record, hand-over, credential report or
alert each end by it, each within its own bound too, so a best-effort one cut by it is logged and
the answer stands, as on its own timeout.

The answer: an accepted create names its exchange order id, text of 1 to `b01.MAX_TEXT`
characters, printable, with no whitespace (#4020 Low 1), else `AckWithoutOrderId`, an ambiguous
outcome (ruling 3 on #3972). A refusal carries the code and the exchange's return code, never its
message (SR-E29-09), with the call's allow-listed record (SR-E29-08). An order found under the id
is answered as a duplicate with what the lookup found and no top-level id, so B1 binds it only on
its own full match (SR-E29-03, #4020 Low 3); the port runs the same `full_match` first: a match is
audited ahead (`orders.submit`, `adopted_after_lookup`, C-2.9), and an order that does not match is
handed to the next reconciliation pass before the answer (`OrderHandovers`), the answer an empty
lookup when that fails (S2-Q3: `unknown`, never `held` with nothing handed over). An id no lookup
settles is an empty lookup (`unknown`), except a re-send the venue may hold (`resend_unconfirmed`:
a duplicate, an ambiguous answer or a refused token), a duplicate with no lookup, so B1 looks the
id up at once (Sec.8.3 rule 3) and never sends it under a new id. A refused rate token is
`RATE_BUDGET_EXCEEDED` with its `retry_after_s` (nothing left, so `rejected`, never `unknown`).
Anything else raised is raised, the venue's outage (`SERVICE_UNAVAILABLE`, #2863) included, so B1
lands the order in `unknown` (S1): no call is repeated because an error says `retryable`.

The records written for a registered order carry the correlation id of the request that
registered it (`expect(..., request_id=)`, #3990), never one from the context the call runs in,
which is B1's; a resumed create's and an attach's carry none (21 Sec.3.10.1).

**24 Sec.8.6, before any answer.** An `AUTH_ERROR` that carries the exchange's return code, answered
or raised, goes to `CredentialRejections` as it came (the orchestrator's Q-I ruling: `oms` holds no
exchange code, C-2.2); a `CLOCK_DRIFT` trips the clock halt, which refuses order entry until a fresh
measurement clears it, and starts one resync of the clock at a time, which `aclose()` cancels at
shutdown.

**lookup.** The id in open orders, then in history: the order found, else an empty mapping, on
which B1 sends. A found order is audited as above when it matches, and handed over first when it
does not; a hand-over that fails raises, as an empty answer would send the order.

**attach_stop** (24 Sec.8.8 rules 2 and 6). The position is read first. One that shows the
requested stop is answered with that reading and audited (`sl.attached`, `already_set`), and
nothing is recorded or sent (the orchestrator's Q-E ruling). Otherwise the gate clears the
position's key (21 Sec.3.3.11, bounded as every other call), waiting up to `ATTACH_GATE_WAIT_S`
for a complete read it starts or joins (protective, 24 Sec.8.4), the request is recorded ahead
(`trading_stop`, audited `sl.attached` in the insert's transaction), and one `trading-stop` call
sends the stop with the take-profit the position shows (24 Sec.8.9: both sides), that side left
out when the reading shows no finite price above zero, so nothing is removed by implication. Its
answer settles the row (`answered`, or `refused` with its void audited `sl.modified`), and a
read-back answers B1. A send that raises leaves the row in flight, for the complete read. A
Partial-mode stop is refused, audited, before anything is sent (Q-F: no stop size can be sent
until G-8b's `sl_size`, #3963), so B1 goes to `sl_missing` and B8. The kill switch, the switches
and the clock halt never gate it: a protective write, which 24 Sec.8.10 carves out (C-2.6,
C-4.14).

A failure before the send is answered, never raised, with nothing sent (S4-H): the account read, as
the cancel's, refused (out of scope or with no active key: `ACCOUNT_UNAVAILABLE`) or failing
otherwise (`STORE_UNAVAILABLE`); the position unread, or its read malformed (`POSITION_UNREAD`: no
blind send, which could replace a tighter stop set outside the OMS, 24 Sec.8.8 rule 5); the gate's
refusal or a request already in flight for the position (`STOP_REQUEST_PENDING`); or a store the
gate or the record cannot reach (`STORE_UNAVAILABLE`). A record whose write is not confirmed (a
timeout, or a storage failure at its commit) may leave its row `pending`, for the complete read
(21 Sec.3.3.11) to put in force or void. Each is logged `oms_stop_not_sent` (the reason, the
failure's class and the order's ids, never a price or a size) and audited `sl.attached` denied with
its reason ahead of the answer, which carries no reading, so B1 lands in `sl_missing` as on a
refused `trading-stop`: it pages `SL_ATTACH_FAILED` and asks B8 for the fallback attach
(24 Sec.8.8 rule 3; E32). The venue holds nothing this attach added. A stored row that cannot be
read (there is none to name), an account read that answers another account's ref (a defect,
SR-E27-21), a route to another environment (C-2.11) and an audit that cannot be written, the
request's or the denial's (C-2.9), still raise, which B1 also lands in `sl_missing`.

**cancel** (24 Sec.8.8 rule 6, SR-E29-06; INV-B1-h, INV-B1-j; the S4 rulings Q8, Q9 and Q11).
B1's cancel in `cancel_pending` and a KILL's (`kill_cancel`): one `cancel` call names the stored
row by its exchange order id once bound, else by its own id (a KILL out of `unknown`), the same
every time (C-2.10; no `ext-` key on the wire, 24 Sec.14.2 rule 11), in the lane its exit
registered with it (`ExitWatch.lane`: a rule's own cancel `entry`, every other reason `critical`,
24 Sec.8.4 item 3), and in `critical` when it finds none (a KILL's, a rebuilt machine's call
resumed after a restart, or one whose registration was dropped or forgotten: the protective
direction, C-12.7). Nothing gates it:
an exit is never gated (24 Sec.8.10, C-2.6). A recorded stop's row is never a KILL's to cancel
(C-2.6, INV-B1-p); a user's cancel of one goes out only once a
`poll`-lane read shows its position flat (Q9, fail closed); both refuse `NATIVE_STOP_REQUIRED`,
so B1 keeps the row live (INV-B1-j), as on `STORE_UNAVAILABLE`, a read before the send that failed
(nothing sent, retried after `STORE_UNAVAILABLE_RETRY_AFTER_S`) and `ACCOUNT_UNAVAILABLE`, an
account out of scope or with no active key (no outage, so no retry; the wiring pages it). A command
naming another order is a defect, raised. Else it answers as a create
does (24 Sec.8.6), and anything raised once the call began is raised, never repeated (Q11: B1 lands
the order in `unknown`), the venue's 110001 too, as `NotFoundError` with its code: the venue does
not hold the order, which says nothing of how it ended, so reconciliation reads it. One deadline
of its kind bounds all of it. An exit service's `expect_exit`, once the facade took its command
(`take_exit`), gets the answer B1 got, None when the call raised but for the venue's 110001, which
says why the order parks; a KILL's spends none.

**amend** (the S4 rulings Q2 to Q4 and Q11; 24 Sec.8.8 rules 5 and 6, Sec.8.9). A TP/SL change
meets Q3's scope and `stop_ratchet` before any record or send (refusals audited `orders.amend`
denied), is re-paired (both sides, a side the order lacks left out) and recorded ahead as one
`entry_attach` insert naming the order (`sl.modified` / `tp.modified`, reason `amend`), then sent
and settled. A held key answers `STOP_REQUEST_IN_FLIGHT`; a raise leaves the rows in flight (S1).
An account the port cannot sign for (refused, or with no active key) answers `ACCOUNT_UNAVAILABLE`,
audited, nothing sent (the 11:34Z ruling); a read that fails before the send, `STORE_UNAVAILABLE`.
It goes in its registration's lane when that names one (a rule's amend, `entry`: 24 Sec.8.4
"Rule-originated orders" item 3), else in the order's own (a reduce-only order whose intent
reduces `critical`, any other `entry`). Its records name the request whose registration B1's call
spent (`expect_exit`, `_spend`), each request's registration its own (#4643): each side's request
and each void the principal with the role and the correlation id, the port's own refusals the
correlation id (C-2.9, #3990); a rule's amend (`ExitWatch.origin`) makes each side's request and
each void the rule's, the principal named as the owner it acts for (24 Sec.15.5). B1's call
spends only a registration whose command the facade took
(`take_exit`, #4662), so a call that comes after its exit ended never names another request whose
command waits at the facade. A call that finds none (a registration dropped past `max_watches`,
or forgotten by an exit service that ended first, `oms.exits`) names no request, and says so:
each of its records is marked `attribution: unregistered`, and it is logged once
(`oms_exit_call_unregistered`, SEC-4662-01).
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Final, Literal
from uuid import UUID, uuid4

import structlog

from candleviewer.domain.primitives import AccountId
from candleviewer.exchange.base.errors import (
    AuthError,
    ClockDriftError,
    ExchangeError,
    NotFoundError,
    OmsErrorCode,
    RateBudgetExceededError,
)
from candleviewer.exchange.base.models import (
    AccountRef,
    AmendOrderRequest,
    CancelOrderRequest,
    Order,
    OrderAck,
    OrderLane,
    PlaceOrderRequest,
    Position,
    TradingStopRequest,
)
from candleviewer.observability import spawn
from candleviewer.observability.tracing import attach_context, span
from candleviewer.statechart.bindings import b01_order as b01
from candleviewer.statechart.config import CV_COMMAND_TIMEOUT, CV_KILL_CANCEL_TIMEOUT
from candleviewer.storage.errors import StorageError
from candleviewer.storage.repositories.orders import NewOrder, OrderRow, OrderStoreError
from candleviewer.storage.repositories.recorded_stops import (
    NewRecordedStop,
    RecordedStopRow,
    StopKind,
)

from .cancel_all_coalescer import unfolded
from .classify import REDUCING_INTENTS
from .clock_halt import ClockHalt
from .errors import (
    AccountScopeDenied,
    AckWithoutOrderId,
    HandoverUnavailable,
    OmsNotReady,
    OrderEntryRefused,
    OrderRefused,
    ResendRefused,
    StopRequestInFlight,
    StopRequestPending,
    StoreUnavailable,
    TradingDisabled,
    problem_for,
)
from .order_link_resolution import (
    Adopted,
    HistoryRetentionPolicy,
    PlaceOutcome,
    Sent,
    Unresolved,
    adopt_or_resend,
    find_by_link_id,
    place_or_adopt,
)
from .order_machine import OrderAudit, OrderAuditRecord, OrderNotice, OrderNotices, is_data_refusal
from .ports import (
    STOP_REQUEST_RETRY_AFTER_S,
    AuditOutcome,
    AuditSeverity,
    CredentialRejections,
    KeyedRecord,
    OrderFigures,
    OrderHandovers,
    PositionKey,
    RuleOrigin,
    StopRequestGate,
    SubmitActor,
    SubmitAudit,
    TradingAccounts,
    TradingSwitches,
)
from .repository import OrderRepository, RecordedStopRepository
from .routing import RoutedPort, TradingRouter, read_position, retry_after
from .stop_ratchet import TPSL_SIDES, ratchet_refusal, tpsl_scope_refusal

__all__ = [
    "ACCOUNT_UNAVAILABLE",
    "ALREADY_SET",
    "AMEND_AUDIT_GRACE_S",
    "AMEND_REASON",
    "AMEND_REFUSED",
    "AMEND_SETTLE_RESERVE_S",
    "AMEND_TIMEOUT_S",
    "ATTACH_GATE_WAIT_S",
    "CANCEL_TIMEOUT_S",
    "EXPIRED_UNSENT_REASON",
    "KILL_CANCEL_TIMEOUT_S",
    "LIVE_HISTORY_SPAN_S",
    "LIVE_RESEND_MAX_AGE_S",
    "MAX_WATCHES",
    "NEVER_SENT_ALERT",
    "PARTIAL_STOP_UNSUPPORTED",
    "PORT_TIMEOUT_S",
    "POSITION_UNREAD",
    "RECORDED_STOP_READ_S",
    "RESEND_REFUSED",
    "STOP_LOOSENING_REFUSED",
    "STOP_NOT_SENT",
    "STOP_REQUEST_IN_FLIGHT",
    "STOP_REQUEST_PENDING",
    "STORE_UNAVAILABLE",
    "STORE_UNAVAILABLE_RETRY_AFTER_S",
    "SUBMIT_TIMEOUT_S",
    "ExitKind",
    "ExitWatch",
    "OmsCommandPort",
    "PlaceWatch",
    "found_view",
    "order_id_kept",
    "place_request",
]

#: The bound on one `place` as a whole, in seconds (CR-2B1-04): one deadline that the stored
#: row's and the account's reads, the exchange calls (the create and, after a duplicate, its
#: lookups; or a resumed create's lookups and re-send) and the answer's record, hand-over,
#: credential report or alert all end by. So an entry's stop request is answered within
#: 3 x `CV_PERSIST_TIMEOUT` + this (its first persist, its `SEND` and its result step, [LANE-25],
#: Q4), inside the stop request's bound (`oms_wiring.OmsBounds`) and B1's own
#: `CV_COMMAND_TIMEOUT`. It also bounds `attach_stop`'s one `trading-stop` call.
SUBMIT_TIMEOUT_S: Final = 5.0
#: The bound on each other call (a read, the store, an audit, a notice, a hand-over, the stop
#: gate), in seconds; inside `place` its deadline may end one sooner.
PORT_TIMEOUT_S: Final = 5.0
#: How long an attach waits for its key's complete read (24 Sec.8.4, the Q2 ruling), in seconds:
#: with the gate's read before and after it (`STOP_GATE_READ_TIMEOUT_S` each) inside
#: `PORT_TIMEOUT_S`, and with the `trading-stop` call's `SUBMIT_TIMEOUT_S` inside B1's attempt.
ATTACH_GATE_WAIT_S: Final = 2.0
#: The bound on all of a user's `cancel` (B1's `cancel_pending`), in seconds: inside B1's
#: `CV_COMMAND_TIMEOUT` and past a recorded stop's read plus the `critical` lane's wait (24
#: Sec.8.7), so, while the store reads answer promptly, a token that does not come is a refusal (the
#: order live), not `unknown` (Q8).
CANCEL_TIMEOUT_S: Final = CV_COMMAND_TIMEOUT - 1.0
#: The bound on a recorded stop's position read, in seconds: the call keeps the lane's wait (Q9).
RECORDED_STOP_READ_S: Final = 3.0
#: An exit's answer when a read before its send fails: nothing sent, so the order stays live, to be
#: retried after `retry_after_s` (the S4 rulings: an exit raises only once its venue call began).
STORE_UNAVAILABLE: Final = "STORE_UNAVAILABLE"
#: The wait `STORE_UNAVAILABLE` advises, in seconds: one figure for the cancel and the amend alike
#: (the S4-B1 ruling; S4-B2 imports it). `retry_after` rounds it up to the answer's whole seconds.
STORE_UNAVAILABLE_RETRY_AFTER_S: Final = 1.0
#: An exit's answer when the account it is signed for refuses its read, out of scope or with no
#: active key: no outage, so no `retry_after_s` (a client must not read it as a conflict, nor wait
#: for it). Nothing is sent, the order stays live, and the wiring has paged it (S4-B1 ruling B).
ACCOUNT_UNAVAILABLE: Final = "ACCOUNT_UNAVAILABLE"
#: What the account read refuses with: the pair `oms_wiring.CommandAccounts` pages CRITICAL.
_ACCOUNT_REFUSED: Final = (AccountScopeDenied, OrderEntryRefused)
#: The bound on all of a KILL's cancel, in seconds, inside B1's `CV_KILL_CANCEL_TIMEOUT`: it runs in
#: B1's `killed` entry, under the order's lock. Tighten each bound, never raise it: the
#: constructor refuses a larger figure.
KILL_CANCEL_TIMEOUT_S: Final = CV_KILL_CANCEL_TIMEOUT - 1.0
#: The bound on an amend as a whole (B1's `amend_pending`), in seconds, as `CANCEL_TIMEOUT_S` is a
#: cancel's: its reads, the gate, the record, the call and the settle all end by it, inside B1's
#: `CV_COMMAND_TIMEOUT`. Tighten it, never raise it.
AMEND_TIMEOUT_S: Final = CV_COMMAND_TIMEOUT - 2.0
#: How long past `AMEND_TIMEOUT_S` a `STORE_UNAVAILABLE` refusal's audit may take, still inside
#: B1's bound: a read the deadline ended is answered, recorded, never raised (the 10:18Z ruling).
AMEND_AUDIT_GRACE_S: Final = 1.0
#: How long before the amend's deadline its venue call must end, in seconds, so an answer that
#: lands just inside it still leaves `_settle_stop` time to settle the rows (review fold 2). The
#: call's credential report (24 Sec.8.6) ends with the call too, answered or raised, so the
#: reserve is the settle's alone (#913 CG19, S4-B2's Fable L2).
AMEND_SETTLE_RESERVE_S: Final = 0.5
#: A read that failed before the amend's send (the 10:18Z ruling): `STORE_UNAVAILABLE` (as the
#: cancel's) with this reason, retried after `STORE_UNAVAILABLE_RETRY_AFTER_S`, the one wait the
#: cancel's and the amend's share (the 11:34Z ruling).
STORE_UNAVAILABLE_REASON: Final = "store_unavailable"
#: The amend's audit reason for `ACCOUNT_UNAVAILABLE`: the port cannot sign for the order's
#: account before its send (refused, or with no active key). No outage, so no retry (the 11:34Z
#: ruling, B).
ACCOUNT_UNAVAILABLE_REASON: Final = "account_unavailable"
_NO_ACTIVE_KEY: Final = "no_active_key"
#: How old a create a restart resumes may be and still be re-sent where history never expires
#: (`order_retention_days` None: live), in seconds ([LANE-26], binding). Tighten it, never raise
#: it: a resumed send survives a restart or a dropped connection measured in seconds, and after
#: minutes the market and the trader's intent have moved. It also sits far inside
#: `LIVE_HISTORY_SPAN_S`, so a miss in open orders and history within it means the create never
#: landed. At exactly the bound the create is still re-sent; a microsecond past it, never. The
#: constructor refuses a larger figure.
LIVE_RESEND_MAX_AGE_S: Final = 120.0
#: How far back live's history read shows every order the venue took, in seconds: a `Cancelled`,
#: `Rejected` or `Deactivated` order for 24 hours only, one with no fill for 7 days only (24
#: Sec.14.1, assumed pending E29-K01). Read against the stored `created_ts`, which no order of the
#: row can predate: a resumed create younger than it that no lookup found never landed, and ends
#: unsent ([LANE-26]); from it on a miss proves nothing, and the create is answered as an empty
#: lookup, `unknown` for reconciliation (SEC-2B1-02). At exactly the span a miss proves nothing.
LIVE_HISTORY_SPAN_S: Final = 86_400.0
_LIVE_HISTORY_SPAN_US: Final = round(LIVE_HISTORY_SPAN_S * 1_000_000)
#: Registered orders not yet sent (C-2.18): past it the oldest is dropped, its watch answered None.
MAX_WATCHES: Final = 1024
#: `attach_stop`'s audit reasons and its local refusal's code.
ALREADY_SET: Final = "already_set"
STOP_REQUESTED: Final = "first_fill_attach"
STOP_REFUSED: Final = "trading_stop_refused"
PARTIAL_STOP_UNSUPPORTED: Final = "PARTIAL_STOP_UNSUPPORTED"
#: S4-H: an attach that failed before its send, answered with nothing sent (module docstring):
#: its code the answer's (these, or the exits' `ACCOUNT_UNAVAILABLE` and `STORE_UNAVAILABLE`,
#: with no `retry_after_s`: nothing retries an attach) and, lower-cased, its record's reason;
#: and the log naming it.
POSITION_UNREAD: Final = "POSITION_UNREAD"
STOP_REQUEST_PENDING: Final = "STOP_REQUEST_PENDING"
STOP_NOT_SENT: Final = "oms_stop_not_sent"
ADOPTED: Final = "adopted_after_lookup"
SL_ATTACHED: Final = "sl.attached"
SL_MODIFIED: Final = "sl.modified"
TP_MODIFIED: Final = "tp.modified"
#: `amend`'s audit reasons and local codes: a Q3 refusal answers its rule in capitals, the ratchet
#: `STOP_LOOSENING_REFUSED` (403 `risk_limit_breached`), a held key `STOP_REQUEST_IN_FLIGHT` (409).
AMEND_REASON: Final = "amend"
AMEND_REFUSED: Final = "amend_refused"
ORDERS_AMEND: Final = "orders.amend"
STOP_LOOSENING_REFUSED: Final = "STOP_LOOSENING_REFUSED"
STOP_REQUEST_IN_FLIGHT: Final = "STOP_REQUEST_IN_FLIGHT"
ORDER_NOT_AMENDABLE: Final = "ORDER_NOT_AMENDABLE"
_MODIFIED: Final[Mapping[StopKind, str]] = {"stop_loss": SL_MODIFIED, "take_profit": TP_MODIFIED}
#: The terms B1's `stage_amend` may stage (`qty` and `b01.TERMS`).
_AMENDABLE: Final = ("qty", *b01.TERMS)
#: What a read before the amend's send raises when the store or the gate cannot answer.
_UNREAD: Final = (TimeoutError, StorageError, OrderStoreError, StoreUnavailable)
#: The detail of each record B1's exit call writes when it finds no registration (its exit ended
#: first, so it names no request), and what that call logs (SEC-4662-01).
UNREGISTERED: Final[Mapping[str, str]] = {"attribution": "unregistered"}
EXIT_CALL_UNREGISTERED: Final = "oms_exit_call_unregistered"
#: [LANE-26]: a resumed create that ends unsent, its record's action and reason, and its alert.
RESEND_REFUSED: Final = "oms.resend_refused"
EXPIRED_UNSENT_REASON: Final = "expired_unsent"
NEVER_SENT_ALERT: Final = "order_never_sent"
CLOCK_RESYNC_REASON: Final = "order_10002"
_DUPLICATE: Final = OmsErrorCode.DUPLICATE_CLIENT_ID.value
_EPOCH: Final = datetime(1970, 1, 1, tzinfo=UTC)
#: The stored vocabulary (21 Sec.3.3.4) as the trading port takes it (24 Sec.14.4).
_SIDES: Final[Mapping[str, Literal["buy", "sell"]]] = {"Buy": "buy", "Sell": "sell"}
_TYPES: Final[Mapping[str, Literal["market", "limit"]]] = {"Market": "market", "Limit": "limit"}
_TIFS: Final[Mapping[str, Literal["gtc", "ioc", "fok", "post_only"]]] = {
    "GTC": "gtc",
    "IOC": "ioc",
    "FOK": "fok",
    "PostOnly": "post_only",
}
_TRIGGERS: Final[Mapping[str, Literal["last", "mark", "index"]]] = {
    "LastPrice": "last",
    "MarkPrice": "mark",
    "IndexPrice": "index",
}
_DIRECTIONS: Final[Mapping[int, Literal["rise", "fall"]]] = {1: "rise", 2: "fall"}
_MODES: Final[Mapping[str, Literal["full", "partial"]]] = {"Full": "full", "Partial": "partial"}
_POSITION_IDX: Final[Mapping[int, Literal[0, 1, 2]]] = {0: 0, 1: 1, 2: 2}

#: The exits an exit service waits on (`expect_exit`): B1's cancel and its amend.
type ExitKind = Literal["cancel", "amend"]
type StoredOrder = NewOrder | OrderRow


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


def _log_resend_refused(link: str, refusal: OrderRefused) -> None:
    """A resumed create that was not re-sent, and why: the refusal's class and its problem code."""
    _log().warning(
        "oms_resend_refused",
        order_link_id=link,
        refusal=type(refusal).__name__,
        code=problem_for(refusal).code,
    )


def order_id_kept(raw: object) -> str | None:
    """*raw* as the OMS keeps an exchange order id: B1's `text_id` (text of 1 to `b01.MAX_TEXT`
    characters, no control character), printable, and holding no whitespace, as the exchange's
    ids hold none (#4020 Low 1); else None."""
    kept = b01.text_id(raw)
    if kept is None or not kept.isprintable() or any(c.isspace() for c in kept):
        return None
    return kept


def place_request(order: StoredOrder, account: AccountRef) -> PlaceOrderRequest:
    """The create for the stored `order`, in the trading port's vocabulary, for `account`: the same
    id, terms and native stop on every send (C-2.10, C-2.6). A rule's order (its row's `origin`)
    rides `entry`, a reduce-only one included, so a create a restart resumes keeps the lane its
    request had (24 Sec.8.4 "Rule-originated orders" item 3, C-12.7); any other is `critical` only
    when it is reduce-only and its intent reduces (SR-E29-01; the reserve is the exits'), else
    `entry`."""
    lane: OrderLane = "entry"
    if order.origin != "rule" and order.reduce_only and order.intent in REDUCING_INTENTS:
        lane = "critical"
    trigger_by = None if order.trigger_by is None else _TRIGGERS[order.trigger_by]
    direction = order.trigger_direction
    return PlaceOrderRequest(
        account=account,
        symbol=order.symbol,
        side=_SIDES[order.side],
        order_type=_TYPES[order.order_type],
        qty=order.qty,
        price=order.price,
        time_in_force=_TIFS[order.time_in_force],
        order_link_id=order.order_link_id,
        reduce_only=order.reduce_only,
        close_on_trigger=order.close_on_trigger,
        position_idx=_POSITION_IDX[order.position_idx],
        trigger_price=order.trigger_price,
        trigger_by=trigger_by,
        trigger_direction=None if direction is None else _DIRECTIONS[direction],
        take_profit=order.take_profit,
        stop_loss=order.stop_loss,
        tpsl_mode=_MODES[order.tpsl_mode],
        lane=lane,
    )


def found_view(order: Order) -> dict[str, Any]:
    """An order a lookup found, as B1's context names an order (`b01.full_match`, 24 Sec.8.1):
    ids and text, `reduce_only`, the order type, and money as canonical decimal text."""
    money = {
        key: None if value is None else _decimal_text(value)
        for key, value in (
            ("qty", order.qty),
            ("price", order.price),
            ("trigger_price", order.trigger_price),
            ("stop_loss", order.stop_loss),
            ("take_profit", order.take_profit),
        )
    }
    return {
        "exchange_order_id": order.exchange_order_id,
        "order_link_id": order.order_link_id,
        "account_id": str(order.account_id),
        "symbol": order.symbol,
        "side": order.side,
        "order_type": order.order_type,
        "reduce_only": order.reduce_only,
        **money,
    }


def _decimal_text(value: Decimal) -> str:
    """Canonical decimal text, as B1 keeps money: fixed point, no exponent, no trailing zeros."""
    out = format(value, "f")
    out = out.rstrip("0").rstrip(".") if "." in out else out
    return "0" if out == "-0" else out


def _reading(position: Position) -> dict[str, Any]:
    """A protection reading (B1.5 `_reading`): the row's exchange time in ms, its stop, its size."""
    stop = position.stop_loss
    return {
        "updated_time": position.updated_at // 1_000,
        "stop_loss": None if stop is None else _decimal_text(stop),
        "size": _decimal_text(position.qty),
    }


def _shows(position: Position | None, stop: Decimal) -> bool:
    """The reading shows the requested stop on an open position, as B1's `_covers` reads it."""
    return position is not None and position.stop_loss == stop and position.qty > 0


def _record(ack: OrderAck) -> dict[str, Any]:
    """The call's allow-listed record (SR-E29-08) for the step's row; none if the port kept none."""
    return {} if ack.record is None else {"record": ack.record.model_dump(mode="json")}


def _duplicate(found: Mapping[str, Any]) -> dict[str, Any]:
    """A duplicate-id answer (24 Sec.8.3 rule 3): what the lookup found, no top-level id."""
    return {"ok": False, "error_code": _DUPLICATE, "lookup": dict(found)}


def _us(at: datetime) -> int:
    return (at - _EPOCH) // timedelta(microseconds=1)


def _at(us: int) -> datetime:
    return _EPOCH + timedelta(microseconds=us)


def _uuid(raw: object) -> UUID:
    if not isinstance(raw, str):
        raise ValueError("the command does not name its order")
    return UUID(raw)


def _stop_of(terms: Mapping[str, Any]) -> Decimal:
    """The stop an attach asks for: decimal text above zero (B1 stamps it so), else `ValueError`."""
    raw = terms.get("stop_loss")
    if not isinstance(raw, str):
        raise ValueError("the attach names no stop")
    try:
        stop = Decimal(raw)
    except InvalidOperation:
        raise ValueError("the attach's stop is not decimal text") from None
    if not stop.is_finite() or stop <= 0:
        raise ValueError("the attach's stop is not a price above zero")
    return stop


def _price(value: Decimal) -> bool:
    """A finite price above zero (finite first: ordering a NaN raises)."""
    return value.is_finite() and value > 0


def _protective(row: OrderRow) -> bool:
    """A recorded protective close (C-2.6, 24 Sec.8.10): what `closePosition` and
    `closeAllPositions` record, a reduce-only `flatten`. Its re-send passes the switches'
    `TradingDisabled` (live trading not enabled, the B18 kill switch, the audit-break halt, the
    order-entry gate) as `submit`'s step 6 does; the fence's `OmsNotReady` and the clock halt
    still refuse. The row keeps no route, so a reduce-only `flatten` `placeOrder` recorded passes
    too: reduce-only, it can never open or add to a position."""
    return row.reduce_only and row.intent == "flatten"


def _amend_lane(row: OrderRow, watch: ExitWatch | None) -> OrderLane:
    """An amend's lane: its registration's when that names one (a rule's amend, `entry`, 24
    Sec.8.4 "Rule-originated orders" item 3), else the order's own: `critical` for a reduce-only
    order whose intent reduces (SR-E29-01), any other `entry`."""
    if watch is not None and watch.lane is not None:
        return watch.lane
    return "critical" if row.reduce_only and row.intent in REDUCING_INTENTS else "entry"


def _check_stops(order: StoredOrder) -> None:
    """C-2.6, checked here before anything is sent, whatever the callers and the exchange port
    check: an order that is not reduce-only carries its native stop (SEC-2B1-04; `FirstPersist`
    and B1's gate refuse one without it upstream), and its stop and take-profit, where it names
    one, are finite prices above zero (#2877 ruling 2), as a zero or a negative could remove a
    protection by implication. `ValueError` otherwise, logged CRITICAL, so B1 lands the order in
    `unknown` with nothing sent."""
    link = order.order_link_id
    if not order.reduce_only and order.stop_loss is None:
        _log().critical("oms_create_stop_missing", order_link_id=link)
        raise ValueError("an order that is not reduce-only carries its native stop (C-2.6)")
    for name, value in (("stop_loss", order.stop_loss), ("take_profit", order.take_profit)):
        if value is not None and not _price(value):
            _log().critical("oms_create_price_refused", order_link_id=link, side=name)
            raise ValueError(f"the order's {name} is not a price above zero")


def _amend_terms(terms: Mapping[str, Any]) -> dict[str, Decimal | None] | None:
    """B1's staged terms as `Decimal`, else None; a TP/SL side may be None or <= 0 (Q3 names it)."""
    if not terms or any(key not in _AMENDABLE for key in terms):
        return None
    out: dict[str, Decimal | None] = {}
    for key, raw in terms.items():
        if raw is None and key in TPSL_SIDES:
            out[key] = None
            continue
        if not isinstance(raw, str):
            return None
        try:
            value = Decimal(raw)
        except InvalidOperation:
            return None
        if key not in TPSL_SIDES and not _price(value):
            return None
        out[key] = value
    return out


def _paired(
    row: OrderRow, sides: Mapping[str, Decimal | None]
) -> tuple[Decimal | None, Decimal | None]:
    """24 Sec.8.9's re-pairing: both sides, unchanged at the order's value, a lacking one out."""
    if not sides:
        return None, None
    kept = {
        side: value
        for side, value in (("stop_loss", row.stop_loss), ("take_profit", row.take_profit))
        if value is not None and _price(value)
    }
    paired = {**kept, **sides}
    return paired.get("stop_loss"), paired.get("take_profit")


def _moved(row: OrderRow, sides: Mapping[str, Decimal | None]) -> dict[str, Decimal | None]:
    """The sides an amend changes. The exit service re-pairs both into its terms, the unchanged one
    at the order's own value (Q2, 24 Sec.8.9), and that side is no change: its record says
    `changed: "false"` (`_record_amend`)."""
    current = {"stop_loss": row.stop_loss, "take_profit": row.take_profit}
    return {side: value for side, value in sides.items() if value != current.get(side)}


def _check_amend_stops(request: AmendOrderRequest) -> None:
    """C-2.6 before the send: a TP/SL sent is a price above zero (the venue reads `0` as remove)."""
    for name, value in (("stop_loss", request.stop_loss), ("take_profit", request.take_profit)):
        if value is not None and not _price(value):
            _log().critical("oms_amend_price_refused", order_link_id=request.order_link_id)
            raise ValueError(f"the amend's {name} is not a price above zero")


def _kept_take_profit(position: Position | None) -> Decimal | None:
    """The take-profit the position shows, sent back with the stop (24 Sec.8.9: one call writes
    both sides); a reading that shows no finite price above zero leaves that side out, so the venue
    keeps what it holds and nothing is removed by implication (#2877 ruling 2)."""
    take_profit = None if position is None else position.take_profit
    return take_profit if take_profit is not None and _price(take_profit) else None


def _seconds(us: int) -> str:
    """Microseconds as exact decimal seconds text: `121`, `120.000001`."""
    return _decimal_text(Decimal(us).scaleb(-6))


@dataclass(frozen=True, slots=True)
class _Expired:
    """A resumed live create no lookup found, older than the live re-send bound and younger than
    the venue's history span ([LANE-26], SEC-2B1-02)."""

    age_us: int


@dataclass(eq=False, slots=True)
class PlaceWatch:
    """The pipeline's wait on one order's create (`OmsCommandPort.expect`). `answer()` resolves once
    `place` answered B1, with the answer it gave; with None when the call raised (B1 then lands the
    order in `unknown`) or when the registration was dropped unspent (`MAX_WATCHES`). `request_id`
    is the registering HTTP request's correlation id, which the order's records carry (#3990), and
    `carrier` its W3C trace context, `oms.send`'s, which the create's span starts under (20
    Sec.12.3)."""

    order: NewOrder
    _future: asyncio.Future[Mapping[str, Any] | None] = field(repr=False)
    request_id: UUID | None = None
    carrier: Mapping[str, str] = field(default_factory=dict, repr=False)

    @property
    def answered(self) -> bool:
        return self._future.done()

    async def answer(self) -> Mapping[str, Any] | None:
        """The answer; a waiter's own cancellation never cancels it."""
        return await asyncio.shield(self._future)

    def resolve(self, answer: Mapping[str, Any] | None) -> None:
        if not self._future.done():
            self._future.set_result(answer)


@dataclass(eq=False, slots=True)
class ExitWatch:
    """An exit service's wait on one order's cancel or amend (`expect_exit`), as `PlaceWatch` is
    the pipeline's on a create: it answers what B1's own call was answered, or None when the call
    raised (Q11) or the registration was dropped or forgotten; the venue's 110001 answers
    why the order parks (`_parked`), as S4-C reads it apart from a fault. B1's call spends it once
    the facade took its command (`OmsCommandPort.take_exit`); a KILL's spends none.
    `request_id` and `actor` name the request the exit is for (#3990). `lane` is the lane its
    exit service registered for B1's call (24 Sec.8.4 "Rule-originated orders" item 3): a
    cancel's by its reason, an amend's `entry` for a rule's, None for the order's own lane.
    `origin` is a rule's request's rule, registered the same way: the stop-side records the
    command port writes for a rule's amend are the rule's, naming the owner through `actor` (24
    Sec.15.5)."""

    order_id: UUID
    kind: ExitKind
    _future: asyncio.Future[Mapping[str, Any] | None] = field(repr=False)
    request_id: UUID | None = None
    actor: SubmitActor | None = None
    lane: OrderLane | None = None
    origin: RuleOrigin | None = None

    @property
    def answered(self) -> bool:
        return self._future.done()

    async def answer(self) -> Mapping[str, Any] | None:
        """The answer; a waiter's own cancellation never cancels it."""
        return await asyncio.shield(self._future)

    def resolve(self, answer: Mapping[str, Any] | None) -> None:
        if not self._future.done():
            self._future.set_result(answer)


class OmsCommandPort:
    """B1's `CommandPort` (module docstring), one per process with the facade it is wired into."""

    def __init__(
        self,
        *,
        router: TradingRouter,
        accounts: TradingAccounts,
        orders: OrderRepository,
        stops: RecordedStopRepository,
        handovers: OrderHandovers,
        credentials: CredentialRejections,
        clock_halt: ClockHalt,
        switches: TradingSwitches,
        audit: OrderAudit,
        submit_audit: SubmitAudit,
        gate: StopRequestGate,
        notices: OrderNotices,
        now_us: Callable[[], int],
        submit_timeout_s: float = SUBMIT_TIMEOUT_S,
        cancel_timeout_s: float = CANCEL_TIMEOUT_S,
        kill_cancel_timeout_s: float = KILL_CANCEL_TIMEOUT_S,
        amend_timeout_s: float = AMEND_TIMEOUT_S,
        port_timeout_s: float = PORT_TIMEOUT_S,
        live_resend_max_age_s: float = LIVE_RESEND_MAX_AGE_S,
        max_watches: int = MAX_WATCHES,
        figures: OrderFigures | None = None,
    ) -> None:
        if max_watches < 1:
            raise ValueError("max_watches holds at least one registration")
        if not 0 <= live_resend_max_age_s <= LIVE_RESEND_MAX_AGE_S:  # NaN fails it too
            raise ValueError("the live re-send bound is only ever tightened, never raised")
        bounds = (
            (cancel_timeout_s, CANCEL_TIMEOUT_S),
            (kill_cancel_timeout_s, KILL_CANCEL_TIMEOUT_S),
            (amend_timeout_s, AMEND_TIMEOUT_S),
        )
        if not all(0 < bound <= most for bound, most in bounds):  # NaN fails it too
            raise ValueError("a cancel bound is only ever tightened, inside B1's own")
        if not amend_timeout_s > AMEND_SETTLE_RESERVE_S + AMEND_AUDIT_GRACE_S:  # #4395 Low L1
            raise ValueError("the amend's bound leaves its venue call no time")
        self._router = router
        self._accounts = accounts
        self._orders = orders
        self._stops = stops
        self._handovers = handovers
        self._credentials = credentials
        self._clock_halt = clock_halt
        self._switches = switches
        self._audit = audit
        self._submit_audit = submit_audit
        self._gate = gate
        self._notices = notices
        self._now_us = now_us
        self._submit_timeout_s = submit_timeout_s
        self._cancel_timeout_s = cancel_timeout_s
        self._kill_cancel_timeout_s = kill_cancel_timeout_s
        self._amend_timeout_s = amend_timeout_s
        self._port_timeout_s = port_timeout_s
        self._live_resend_max_age_us = round(live_resend_max_age_s * 1_000_000)
        self._max_watches = max_watches
        self._figures = figures  # an accepted amend drops the account's (24 Sec.9.3.6)
        self._watches: OrderedDict[UUID, PlaceWatch] = OrderedDict()
        #: Each exit's registration, in registration order (#4643): True once the facade took its
        #: command (`take_exit`, #4662), which B1's call alone spends (`_spend`).
        self._exits: OrderedDict[ExitWatch, bool] = OrderedDict()
        self._resync: asyncio.Task[None] | None = None
        self._closed = False

    @property
    def resync_task(self) -> asyncio.Task[None] | None:
        """The clock resync the last `CLOCK_DRIFT` started, while one runs or has run."""
        return self._resync

    @property
    def submit_timeout_s(self) -> float:
        """The one deadline on all of a `place` (`SUBMIT_TIMEOUT_S`, CR-2B1-04), as this port
        applies it: the pipeline's wait for a create's answer must outlast it, as its default does
        with B1's turn added (`OrderSubmission`, D-2B2-01)."""
        return self._submit_timeout_s

    async def aclose(self) -> None:
        """At shutdown (slice 3's lifecycle; every task owned, C-2.18): no `CLOCK_DRIFT` starts a
        resync from here on, and the one running is cancelled and awaited. The halt stays as it
        is. A second call does nothing more."""
        self._closed = True
        task = self._resync
        if task is None or task.done():
            return
        task.cancel()
        await asyncio.wait([task])  # its cancellation is its end; the caller's own propagates

    # --- place -----------------------------------------------------------------------------

    def expect(
        self,
        order: NewOrder,
        *,
        request_id: UUID | None = None,
        carrier: Mapping[str, str] | None = None,
    ) -> PlaceWatch:
        """Register the order the pipeline is about to send (`SEND`): its `place` builds the create
        from `order` and sends it as a first send, and the watch answers what B1 was answered. A
        second registration of the order replaces the first, which is answered None. `request_id`
        is the correlation id of the HTTP request submitting it (#3990): the order's records carry
        it, as B1's calls run in its own task, outside the request's context; for the same reason
        `carrier` is the request's trace context, which the create's span starts under."""
        future = asyncio.get_running_loop().create_future()
        watch = PlaceWatch(order, future, request_id, dict(carrier or {}))
        replaced = self._watches.pop(order.id, None)
        if replaced is not None:
            replaced.resolve(None)
        self._watches[order.id] = watch
        while len(self._watches) > self._max_watches:
            _, dropped = self._watches.popitem(last=False)
            _log().error("oms_place_watch_dropped", order_link_id=dropped.order.order_link_id)
            dropped.resolve(None)
        return watch

    def forget(self, order_id: UUID) -> None:
        """Drop the order's registration while `place` has not spent it: the pipeline's `SEND` did
        not commit, so no create leaves for it (S2-Q5). Its watch answers None."""
        watch = self._watches.pop(order_id, None)
        if watch is not None:
            watch.resolve(None)

    async def place(self, command: b01.Command) -> Mapping[str, Any]:
        """B1's create (module docstring); the order's registration, if any, is spent here. The
        create is one `exchange.place_order` span under its registering request's `oms.send`, the
        watch's `carrier`; a create resumed with no registration starts a trace of its own (20
        Sec.12.3)."""
        watch = self._watches.pop(_uuid(command.order.get("order_id")), None)
        carrier = {} if watch is None else watch.carrier
        try:
            with attach_context(carrier), span("exchange.place_order"):
                answer = await self._place(command, watch)
        except BaseException:
            if watch is not None:
                watch.resolve(None)
            raise
        if watch is not None:
            watch.resolve(answer)
        return answer

    async def _place(self, command: b01.Command, watch: PlaceWatch | None) -> dict[str, Any]:
        if watch is None:
            return await self._resume(command)
        _check_names(command, watch.order)
        order = watch.order
        _check_stops(order)
        by = self._deadline(self._submit_timeout_s)  # all of `place` ends by it (CR-2B1-04)
        account = await self._account(order, by=by)
        port = self._router.port_for(account.environment)
        request = place_request(order, account)
        try:
            outcome = await self._venue_gated(account, place_or_adopt(port, request), by=by)
        except RateBudgetExceededError as exc:
            _log().warning("oms_create_rate_refused", order_link_id=order.order_link_id)
            return {
                "ok": False,
                "error_code": OmsErrorCode.RATE_BUDGET_EXCEEDED.value,
                "retry_after_s": retry_after(exc.retry_after_s),
            }
        return await self._answer(command, account, outcome, watch.request_id, by=by)

    async def _resume(self, command: b01.Command) -> dict[str, Any]:
        """A create a restart resumes (module docstring, [LANE-26]), all of it by one deadline. No
        refused rate token is answered as a rejection here: the earlier create may have landed
        (`adopt_or_resend`)."""
        by = self._deadline(self._submit_timeout_s)
        row = await self._stored(command, by=by)
        account = await self._account(row, by=by)
        port = self._router.port_for(account.environment)
        request = place_request(row, account)
        resumed = self._resumed(account, port, request, row)
        outcome = await self._venue_gated(account, resumed, by=by)
        if isinstance(outcome, _Expired):
            return await self._expire(account, row, outcome.age_us, by=by)
        return await self._answer(command, account, outcome, None, by=by)

    async def _resumed(
        self, account: AccountRef, port: RoutedPort, request: PlaceOrderRequest, row: OrderRow
    ) -> PlaceOutcome | _Expired:
        """[LANE-26]'s order: the lookup whatever the switches say, the switches (a protective
        close's carve-out applies, `_protective`) and the clock halt, the live bounds, then
        `adopt_or_resend`, which looks once more just before its one re-send (SR-E29-15) and
        applies rule 6 from the port's own retention (24 Sec.8.3: demo's 6 days). A refusal is
        `ResendRefused`; `OmsNotReady`, the switches' while the serving loop stalls (#913 L4,
        SEC-S3L4-03) or the halt's while no clock is measured yet (`ClockHalt.refusal`), is
        raised as it is: both are logged `oms_resend_refused`, and nothing is sent."""
        link = request.order_link_id
        try:
            found = await find_by_link_id(port, request)
        except (AuthError, ClockDriftError):
            raise
        except ExchangeError:  # a failed read is never the order's outcome (Sec.8.3 rule 3)
            _log().warning("oms_resend_lookup_failed", order_link_id=link)
            return Unresolved(order_link_id=link, reason="lookup_failed")
        if found is not None:
            return Adopted(order=found[0], source=found[1])
        try:  # either may let `OmsNotReady` through: logged as a refusal is, raised as it is
            refusal: OrderRefused | None = self._switches.refusal(
                account.account_id, account.environment
            )
            if isinstance(refusal, TradingDisabled) and _protective(row):
                _log().info(  # C-2.6 (24 Sec.8.10): as `submit`'s step 6 carve-out
                    "oms_resend_protective_close_admitted",
                    order_link_id=link,
                    code=problem_for(refusal).code,
                )
                refusal = None
            if refusal is None:  # SEC-2B1-01: never a re-send under a clock a `10002` tripped
                refusal = self._clock_halt.refusal()
        except OmsNotReady as not_ready:  # a stalled serving loop (L4), or no clock measured (Q8)
            _log_resend_refused(link, not_ready)
            raise  # as it is: B1 lands the order in `unknown` (S1), nothing was sent
        if refusal is not None:
            _log_resend_refused(link, refusal)
            raise ResendRefused(refusal)
        retention = HistoryRetentionPolicy.from_capabilities(port.capabilities)
        created, now = _us(row.created_ts), self._now_us()
        age = now - created
        if retention.retention_days is None and age > self._live_resend_max_age_us:
            if age >= _LIVE_HISTORY_SPAN_US:  # SEC-2B1-02: a miss there proves nothing
                _log().warning("oms_resend_past_history", order_link_id=link, age_s=_seconds(age))
                return Unresolved(order_link_id=link, reason="history_expired")
            return _Expired(age_us=age)
        _check_stops(row)
        return await adopt_or_resend(
            port, request, retention=retention, created_at=created, now=now
        )

    async def _expire(
        self, account: AccountRef, row: OrderRow, age_us: int, *, by: float
    ) -> dict[str, Any]:
        """[LANE-26]: a resumed create past the live bound that no lookup found within the venue's
        history span ends unsent, through `submitting`'s last arm (`rejected`,
        `b01.EXPIRED_UNSENT`). Its record is written ahead (C-2.9: one that does not land raises,
        so B1 lands the order in `unknown`), then the user is alerted that the order was not found
        within the venue's 24 h history; an alert that does not land, by `place`'s deadline or at
        all, is logged CRITICAL, never dropped silently: the order's end and its record stand."""
        link = row.order_link_id
        age_s, bound_s = _seconds(age_us), _seconds(self._live_resend_max_age_us)
        detail = {"order_link_id": link, "age_s": age_s, "bound_s": bound_s}
        reason = EXPIRED_UNSENT_REASON
        await self._audit_order(
            row.id, account.account_id, RESEND_REFUSED, "denied", "warning", reason, detail, by=by
        )
        _log().warning("oms_resend_expired", order_link_id=link, age_s=age_s, bound_s=bound_s)
        when = row.created_ts.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
        alert = {"alert": NEVER_SENT_ALERT, "created_at": row.created_ts.isoformat()}
        alert["message"] = (
            f"an order from {when} was not found within the venue's 24 h history and was not "
            "placed; re-enter it if still wanted"
        )
        notice = OrderNotice("alert", row.id, row.exchange_account_id, link, alert)
        try:
            await self._bounded(self._notices.notify(notice), by=by)
        except Exception as exc:  # the alert is lost, never the order's end or its record
            lost = type(exc).__name__
            _log().critical("oms_never_sent_alert_lost", order_link_id=link, failure=lost)
        return {"ok": False, "error_code": b01.EXPIRED_UNSENT}

    async def _answer(
        self,
        command: b01.Command,
        account: AccountRef,
        outcome: PlaceOutcome,
        request_id: UUID | None,
        *,
        by: float,
    ) -> dict[str, Any]:
        if isinstance(outcome, Sent):
            return await self._sent(account, outcome.ack, by=by)
        if isinstance(outcome, Adopted):
            found = found_view(outcome.order)
            order, source = outcome.order, outcome.source
            if await self._settled_found(command, account, order, found, source, request_id, by=by):
                return _duplicate(found)
            return _duplicate({})
        _log().warning(
            "oms_create_unresolved", order_link_id=outcome.order_link_id, reason=outcome.reason
        )
        if outcome.reason == "resend_unconfirmed":
            # The venue may hold the order under the id (a duplicate, an ambiguous re-send, a
            # refused token): a duplicate with no lookup, so B1 looks the id up at once (24 Sec.8.3
            # rule 3) and binds it only on its full match, never under a new id ([LANE-26]).
            return {"ok": False, "error_code": _DUPLICATE}
        return _duplicate({})

    async def _sent(self, account: AccountRef, ack: OrderAck, *, by: float) -> dict[str, Any]:
        if ack.ok:
            kept = order_id_kept(ack.exchange_order_id)
            if kept is None:
                _log().error("oms_ack_without_order_id", order_link_id=ack.order_link_id)
                raise AckWithoutOrderId(
                    "an accepted create names no exchange order id the OMS keeps"
                )
            return {"ok": True, "exchange_order_id": kept, **_record(ack)}
        await self._venue(account, ack.error_code, ack.exchange_ret_code, by=by)
        refused = {"ok": False, "error_code": ack.error_code}
        return {**refused, "exchange_ret_code": ack.exchange_ret_code, **_record(ack)}

    async def _settled_found(
        self,
        command: b01.Command,
        account: AccountRef,
        order: Order,
        found: Mapping[str, Any],
        source: str,
        request_id: UUID | None,
        *,
        by: float | None = None,
    ) -> bool:
        """What a lookup found under the row's id, settled before the answer: a full match is
        audited as adopted (C-2.9), with the registering request's id when there is one, and True;
        another order is handed to reconciliation first, True once it is, False when it cannot be
        (S2-Q3). Each call ends by `by`, `place`'s deadline, when there is one."""
        try:
            match = b01.full_match(command.order, found)
        except ValueError:  # malformed money, which B1's guards deny too
            match = False
        link = order.order_link_id
        if match:
            detail = {"order_link_id": link, "exchange_order_id": order.exchange_order_id}
            detail |= {"source": source, "exchange_state": order.state}
            order_id = _uuid(command.order.get("order_id"))
            await self._audit_order(
                order_id,
                account.account_id,
                "orders.submit",
                "success",
                "warning",
                ADOPTED,
                detail,
                request_id=request_id,
                by=by,
            )
            _log().info("oms_create_adopted", order_link_id=link, source=source)
            return True
        _log().error("oms_link_id_held_by_another_order", order_link_id=link, source=source)
        try:
            await self._bounded(self._handovers.hand_over_order(account.account_id, order), by=by)
        except Exception as exc:  # S2-Q3: nothing handed over, so nothing is held on it
            _log().error("oms_handover_failed", order_link_id=link, failure=type(exc).__name__)
            return False
        return True

    # --- lookup ----------------------------------------------------------------------------

    async def lookup(self, command: b01.Command) -> Mapping[str, Any]:
        """The id in open orders, then in history (24 Sec.8.3 rule 3): the order found, or an
        empty mapping, on which B1 sends the create. A found order is settled as `place` settles
        it; one not handed over raises `HandoverUnavailable`, so B1 sends nothing. A failed read
        raises, the venue's outage included (#2863), and is never repeated here."""
        order, request_id = await self._order_of(command)
        account = await self._account(order)
        port = self._router.port_for(account.environment)
        request = place_request(order, account)
        by = self._deadline(self._port_timeout_s)
        found = await self._venue_gated(account, find_by_link_id(port, request), by=by)
        if found is None:
            return {}
        exchange_order, source = found
        view = found_view(exchange_order)
        settled = await self._settled_found(
            command, account, exchange_order, view, source, request_id
        )
        if not settled:
            raise HandoverUnavailable("the order found under the id was not handed over")
        return view

    # --- attach_stop -----------------------------------------------------------------------

    async def attach_stop(self, command: b01.Command) -> Mapping[str, Any]:
        """The stop B1 asks for after the first fill (24 Sec.8.8 rule 2), read back afresh on
        every call (INV-B1-f; module docstring). A failure before the send is answered with
        nothing sent (`_not_sent`); a record whose write is not confirmed (a timeout, or a storage
        failure at its commit) may leave its row `pending`, for the complete read (21 Sec.3.3.11)
        to put in force or void."""
        stop = _stop_of(command.terms)
        account_id, order_id = (
            _uuid(command.order.get("account_id")),
            _uuid(command.order.get("order_id")),
        )
        row = await self._bounded(self._orders.get(account_id, order_id))
        if row is None:
            raise ValueError("no stored order of the account has the command's id")
        detail = {"order_link_id": row.order_link_id, "symbol": row.symbol}
        detail["position_idx"] = str(row.position_idx)
        if row.tpsl_mode != "Full":  # Q-F: no stop size until G-8b's `sl_size` (#3963; 24 Sec.8.9)
            await self._audit_order(
                order_id, account_id, SL_ATTACHED, "denied", "error", "partial_mode", detail
            )
            _log().error("oms_partial_stop_refused", order_link_id=row.order_link_id)
            return {"ok": False, "error_code": PARTIAL_STOP_UNSUPPORTED}
        try:  # the account read as the cancel's (S4-B1 ruling B)
            account = await self._account(row)
        except ValueError:  # the account resolved is another's: a defect, raised (SR-E27-21)
            raise
        except _ACCOUNT_REFUSED as exc:  # out of scope (soft-deleted) or no active key: no outage
            return await self._not_sent(row, ACCOUNT_UNAVAILABLE, detail, exc)
        except Exception as exc:  # unread, or a defect that reads as an outage
            return await self._not_sent(row, STORE_UNAVAILABLE, detail, exc)
        port = self._router.port_for(account.environment)
        try:  # this read only, never the send or the read-back after it
            before = await self._position(account, port, row)
        except (ExchangeError, TimeoutError, ValueError) as exc:  # unread, or read malformed
            return await self._not_sent(row, POSITION_UNREAD, detail, exc)
        if before is not None and _shows(before, stop):  # Q-E: no call, but the trail (C-2.9)
            await self._audit_order(
                order_id, account_id, SL_ATTACHED, "success", "info", ALREADY_SET, detail
            )
            return {"ok": True, "position": _reading(before)}
        key = PositionKey(account.account_id, row.symbol, row.position_idx)
        cleared = self._gate.clear(key, wait_s=ATTACH_GATE_WAIT_S, protective=True)
        try:
            await self._bounded(cleared)  # whatever the gate bounds itself (C-2.18)
        except StopRequestPending as exc:
            return await self._not_sent(row, STOP_REQUEST_PENDING, detail, exc)
        except (StoreUnavailable, TimeoutError) as exc:  # its reads, past even `PORT_TIMEOUT_S`
            return await self._not_sent(row, STORE_UNAVAILABLE, detail, exc)
        try:
            recorded = await self._record_stop(row, stop, detail)
        except StopRequestInFlight as exc:  # another request recorded for the position meanwhile
            return await self._not_sent(row, STOP_REQUEST_PENDING, detail, exc)
        except (OrderStoreError, StorageError, TimeoutError) as exc:
            # not confirmed, so its row may stay pending (docstring); `AuditNotDurable` raises
            return await self._not_sent(row, STORE_UNAVAILABLE, detail, exc)
        request = TradingStopRequest(
            account=account,
            symbol=row.symbol,
            position_idx=_POSITION_IDX[row.position_idx],
            stop_loss=stop,
            # read ahead of the gate: after its wait (4 s at most) a take-profit moved at the venue
            # meanwhile is sent back as read, never the stop (CR-S3H3B-04); a fresh read, bounded
            # at `PORT_TIMEOUT_S`, would not fit with the gate and `SUBMIT_TIMEOUT_S` in B1's
            # attempt (`CV_COMMAND_TIMEOUT`)
            take_profit=_kept_take_profit(before),
        )
        by = self._deadline(self._submit_timeout_s)  # a raise leaves the row in flight
        ack = await self._venue_gated(account, port.set_trading_stop(request), by=by)
        if not ack.ok:
            await self._venue(account, ack.error_code, ack.exchange_ret_code)
        await self._settle_stop(recorded, ack.ok, ack.error_code, detail)
        after = await self._position(account, port, row)
        answer: dict[str, Any] = {"ok": ack.ok}
        if not ack.ok:
            answer |= {"error_code": ack.error_code, "exchange_ret_code": ack.exchange_ret_code}
        if after is not None:
            answer["position"] = _reading(after)
        return answer

    async def _record_stop(
        self, row: OrderRow, stop: Decimal, detail: Mapping[str, str | None]
    ) -> tuple[RecordedStopRow, ...]:
        """The request's stop-loss row, written ahead with its `sl.attached` record in the insert's
        transaction (21 Sec.3.3.11), which the row names (`audit_record_id`)."""
        stop_id = uuid4()
        new = NewRecordedStop(
            id=stop_id,
            exchange_account_id=row.exchange_account_id,
            symbol=row.symbol,
            position_idx=_POSITION_IDX[row.position_idx],
            position_side=row.side,
            kind="stop_loss",
            source="trading_stop",
            order_id=None,
            tpsl_mode="Full",
            trigger_price=stop,
            size=None,
            audit_record_id=self._submit_audit.record_id(SL_ATTACHED, str(stop_id)),
            actor_user_id=None,
        )
        record = _stop_record(SL_ATTACHED, new, "success", "info", STOP_REQUESTED, detail)

        async def requested(_rows: tuple[RecordedStopRow, ...]) -> None:
            await self._submit_audit.write(record)

        return await self._bounded(self._stops.record([new], write_ahead=requested))

    async def _not_sent(
        self, row: OrderRow, code: str, detail: Mapping[str, str | None], failure: Exception
    ) -> Mapping[str, Any]:
        """An attach that failed before its send (S4-H, module docstring): logged with the
        failure's class, never its text, as `oms_stop_settle_failed` is; then audited
        `sl.attached` denied with its reason ahead of the answer (C-2.9), an audit that does not
        land raising; the answer carries no reading, so B1 lands in `sl_missing`."""
        reason = code.lower()
        _log().error(
            STOP_NOT_SENT, reason=reason, order_link_id=row.order_link_id, symbol=row.symbol,
            position_idx=row.position_idx, failure=type(failure).__name__,
        )  # fmt: skip
        await self._audit_order(
            row.id, row.exchange_account_id, SL_ATTACHED, "denied", "error", reason, detail
        )
        return {"ok": False, "error_code": code}

    async def _settle_stop(
        self,
        recorded: tuple[RecordedStopRow, ...],
        ok: bool,
        error_code: str | None,
        detail: Mapping[str, str | None],
        *,
        reason: str = STOP_REFUSED,
        by: float | None = None,
        actor: SubmitActor | None = None,
        request_id: UUID | None = None,
        origin: RuleOrigin | None = None,
    ) -> None:
        """The request's answer on its rows: `answered`, or `refused`, each void audited ahead
        with `reason` (`_void_record`, keyed apart from its request, #4587) under the request's
        `actor`, the principal its rows hold, and its `request_id` (#4643): the writer refuses a
        record that names a user without the role (C-2.9), so a void without it would never
        land. A rule's amend's voids (`origin`) are the rule's, as its requests are. A settle that
        fails leaves the rows in flight, for the complete read (21 Sec.3.3.11), and is logged: the
        exchange's answer stands."""
        ids = [row.id for row in recorded]
        account_id, at = recorded[0].exchange_account_id, _at(self._now_us())
        try:
            if ok:
                await self._bounded(self._stops.settle(account_id, ids, "answered", at=at), by=by)
                return
            voided = {**detail, "error_code": error_code}
            records = [
                _void_record(row, reason, voided, actor, request_id, origin) for row in recorded
            ]

            async def void(_rows: tuple[RecordedStopRow, ...]) -> None:
                for record in records:
                    await self._submit_audit.write(record)

            await self._bounded(
                self._stops.settle(account_id, ids, "refused", at=at, write_ahead=void), by=by
            )
        except Exception as exc:  # the rows stay in flight, which only the complete read ends
            _log().error("oms_stop_settle_failed", answered=ok, failure=type(exc).__name__)

    # --- cancel, B1's and a KILL's, and the exit services' watch; amend (S4-B2) -----------------

    def expect_exit(
        self,
        order_id: UUID,
        kind: ExitKind,
        *,
        request_id: UUID | None = None,
        actor: SubmitActor | None = None,
        lane: OrderLane | None = None,
        origin: RuleOrigin | None = None,
    ) -> ExitWatch:
        """Register the exit an exit service is about to command (`CANCEL`, `AMEND`), answered as
        B1 was, in `lane` when it names one, its records a rule's when it names an `origin`. Each
        is its request's own (#4643): a second of the order and kind never replaces the first.
        B1's call spends it only once the facade took its command (`take_exit`, `_spend`); past
        `max_watches` the oldest is dropped, answered None (C-2.18)."""
        future = asyncio.get_running_loop().create_future()
        watch = ExitWatch(order_id, kind, future, request_id, actor, lane, origin)
        self._exits[watch] = False
        while len(self._exits) > self._max_watches:
            dropped, _ = self._exits.popitem(last=False)
            _log().error("oms_exit_watch_dropped", order_id=str(dropped.order_id))
            dropped.resolve(None)
        return watch

    def take_exit(self, watch: ExitWatch) -> None:
        """The facade took the registration's command (`OrderMachines.command`'s `on_taken`, under
        the order's lock, before it is sent): from now on B1's call for its step may spend it
        (#4662). A watch no longer held (spent, dropped or forgotten) is left as it is."""
        if watch in self._exits:
            self._exits[watch] = True

    def forget_exit(self, watch: ExitWatch) -> None:
        """Drop a registration B1 has not spent: its exit service forgets its own on every way out
        but B1's call having spent it (`oms.exits`), its command refused, its step settled with
        no call, or no call yet as it ends. Its watch answers None; another request's
        registration of the order stays, and a watch no longer held is left as it is."""
        if watch in self._exits:
            del self._exits[watch]
            watch.resolve(None)

    def _spend(self, order_id: UUID, kind: ExitKind) -> ExitWatch | None:
        """B1's call spends the order's oldest registration of `kind` whose command the facade
        took (`take_exit`, #4662), never one whose command still waits at the facade or was
        refused there. The facade takes the order's commands one at a time and refuses another
        exit of the order while one's step stands, and B1 calls only while a step stands, so the
        call finds its own step's registration, or none once that exit forgot it (#4643). A call
        that finds none is logged once with the order's id (`EXIT_CALL_UNREGISTERED`), and its
        records say so (`UNREGISTERED`, SEC-4662-01)."""
        wanted = (order_id, kind)
        taken = (w for w, took in self._exits.items() if took and (w.order_id, w.kind) == wanted)
        watch = next(taken, None)
        if watch is not None:
            del self._exits[watch]
        else:
            _log().warning(EXIT_CALL_UNREGISTERED, order_id=str(order_id), kind=kind)
        return watch

    async def cancel(self, command: b01.Command) -> Mapping[str, Any]:
        """B1's cancel (`cancel_pending`) and a KILL's (`kill_cancel`), module docstring; the
        order's exit registration is spent by B1's own cancel only, never by a KILL's."""
        kill = command.kind == "kill_cancel"
        order_id = _uuid(command.order.get("order_id"))  # parsed before any registration is popped
        watch = None if kill else self._spend(order_id, "cancel")
        # The registration's lane, its reason's; a KILL's, or a call that finds none (a rebuilt
        # machine's, resumed after a restart), `critical`: the protective direction (C-12.7).
        lane: OrderLane = "critical" if watch is None or watch.lane is None else watch.lane
        try:
            answer = await self._cancel(command, kill=kill, lane=lane)
        except BaseException as exc:
            if watch is not None:
                watch.resolve(_parked(exc))
            raise
        if watch is not None:
            watch.resolve(answer)
        return answer

    async def _cancel(self, command: b01.Command, *, kill: bool, lane: OrderLane) -> dict[str, Any]:
        bound = self._kill_cancel_timeout_s if kill else self._cancel_timeout_s
        by = self._deadline(bound)  # all of the cancel, inside B1's own bound on it
        try:  # the reads before the send: one that fails sends nothing, so the order stays live
            row = await self._stored(command, by=by)
            link, recorded = row.order_link_id, row.provenance == "recorded_stop"
            if recorded and kill:  # C-2.6, INV-B1-p: B1's guarded arm spares it, and the port too
                _log().critical("oms_kill_spared_recorded_stop", order_link_id=link)
                return {"ok": False, "error_code": b01.NATIVE_STOP_REQUIRED}
            account = await self._account(row, by=by)
        except ValueError:  # the command names another order or account: a defect, raised
            raise
        except _ACCOUNT_REFUSED as exc:  # no outage, so no retry is advised: answered, not retried
            _log().warning("oms_cancel_account_refused", kill=kill, refusal=type(exc).__name__)
            return {"ok": False, "error_code": ACCOUNT_UNAVAILABLE}
        except Exception as exc:  # unread (an outage): answered, retried after the shared wait
            if _transient(exc):
                _log().warning("oms_cancel_unread", kill=kill, failure=type(exc).__name__)
            else:  # a defect reads as an outage: still answered so, but it is seen
                _log().error("oms_cancel_unread_unexpected", kill=kill, failure=type(exc).__name__)
            wait = retry_after(STORE_UNAVAILABLE_RETRY_AFTER_S)
            return {"ok": False, "error_code": STORE_UNAVAILABLE, "retry_after_s": wait}
        port = self._router.port_for(account.environment)
        if recorded and not await self._flat(account, port, row, by=by):
            return {"ok": False, "error_code": b01.NATIVE_STOP_REQUIRED}
        request = CancelOrderRequest(
            account=account,
            symbol=row.symbol,
            order_link_id=link,
            exchange_order_id=row.exchange_order_id,
            lane=lane,
        )
        try:
            call = port.cancel_order(request)  # a KILL's never waits on a cancel-all fold
            ack = await self._venue_gated(account, unfolded(call) if kill else call, by=by)
        except RateBudgetExceededError as exc:
            _log().warning("oms_cancel_rate_refused", order_link_id=link, kill=kill)
            code, wait = OmsErrorCode.RATE_BUDGET_EXCEEDED.value, retry_after(exc.retry_after_s)
            return {"ok": False, "error_code": code, "retry_after_s": wait}
        if ack.ok:  # it binds nothing: B1 compares the id it names with the bound one (OM-S05)
            kept = order_id_kept(ack.exchange_order_id)
            return {"ok": True, "exchange_order_id": kept, **_record(ack)}
        if ack.error_code == OmsErrorCode.ORDER_NOT_FOUND:  # 24 Sec.8.6: reconcile, never back live
            ret_code = ack.exchange_ret_code
            raise NotFoundError("the venue does not hold the order", exchange_ret_code=ret_code)
        if kill:  # INV-B1-h: B18's cancel-all and reconciliation settle the venue
            _log().error("oms_kill_cancel_refused", order_link_id=link, error_code=ack.error_code)
        return await self._sent(account, ack, by=by)

    async def _flat(
        self, account: AccountRef, port: RoutedPort, row: OrderRow, *, by: float
    ) -> bool:
        """Q9, fail closed: a recorded stop's row is cancelled only once a `poll`-lane read, ended
        by `RECORDED_STOP_READ_S`, shows its position flat, or none (logged apart: a missed position
        would too); one that shows it open, or fails, keeps the stop (24 Sec.8.8 rule 6), logged."""
        link, read = row.order_link_id, read_position(port, account, row.symbol, row.position_idx)
        within = min(by, self._deadline(RECORDED_STOP_READ_S))
        try:
            held = await self._venue_gated(account, read, by=within)
            if held is not None and held.qty != 0:  # any size, a NaN's too, is a position held
                _log().warning("oms_recorded_stop_kept", order_link_id=link, position="open")
                return False
        except Exception as exc:  # unread: the stop stays, as over an open position (C-2.6)
            failure = type(exc).__name__
            _log().warning(
                "oms_recorded_stop_kept", order_link_id=link, position="unread", failure=failure
            )
            return False
        if held is None:  # flat, but a position the read missed (a materialisation defect) too
            _log().warning("oms_recorded_stop_released", order_link_id=link, position="none")
        return True

    async def amend(self, command: b01.Command) -> Mapping[str, Any]:
        """`amend_pending`'s call: the stored order changed in place (module docstring); the
        order's amend registration (`expect_exit`) names the request each record of it names,
        and gets the answer, None when the call raises."""
        watch = self._spend(_uuid(command.order.get("order_id")), "amend")
        try:
            answer = await self._amend(command, watch)
        except BaseException:
            if watch is not None:
                watch.resolve(None)
            raise
        if watch is not None:
            watch.resolve(answer)
        return answer

    async def _amend(self, command: b01.Command, watch: ExitWatch | None) -> dict[str, Any]:
        actor, rid, origin = (
            (None, None, None) if watch is None else (watch.actor, watch.request_id, watch.origin)
        )
        unnamed: Mapping[str, str] = UNREGISTERED if watch is None else {}  # SEC-4662-01
        by = self._deadline(self._amend_timeout_s)  # all of the amend, inside B1's own bound
        account_id = _uuid(command.order.get("account_id"))
        order_id = _uuid(command.order.get("order_id"))
        link = b01.text_id(command.order.get("order_link_id"))
        try:
            row = await self._bounded(self._orders.get(account_id, order_id), by=by)
        except _UNREAD as exc:
            return await self._unread(
                order_id, account_id, {"order_link_id": link, **unnamed}, exc, by=by,
                request_id=rid,
            )  # fmt: skip
        if row is None:
            raise ValueError("no stored order of the account has the command's id")
        _check_names(command, row)
        detail = {"order_link_id": row.order_link_id, "symbol": row.symbol, **unnamed}
        detail["position_idx"] = str(row.position_idx)
        requested = _amend_terms(command.terms)
        if requested is None:  # as B1 refuses terms it could not stage: nothing is sent
            code = OmsErrorCode.INSTRUMENT_FILTER.value
            return await self._amend_refused(
                row, code, "terms_not_staged", detail, by=by, request_id=rid
            )
        if row.provenance != "placed":  # a recorded stop's TP/SL order is not the user's to amend
            return await self._amend_refused(
                row, ORDER_NOT_AMENDABLE, "not_amendable", detail, by=by, request_id=rid
            )
        sides = {side: value for side, value in requested.items() if side in TPSL_SIDES}
        rule = tpsl_scope_refusal(
            sides, reduce_only=row.reduce_only, tpsl_mode=row.tpsl_mode, filled_qty=row.cum_exec_qty
        )
        if rule is not None:
            return await self._amend_refused(row, rule.upper(), rule, detail, by=by, request_id=rid)
        stop, take_profit = _paired(row, sides)
        if sides and stop is None:  # an entry carries its native stop (C-2.6): never sent bare
            rule = "native_stop_required"
            return await self._amend_refused(
                row, b01.NATIVE_STOP_REQUIRED, rule, detail, by=by, request_id=rid
            )
        try:
            account = await self._account(row, by=by)
        except _UNREAD as exc:
            return await self._unread(
                row.id, row.exchange_account_id, detail, exc, by=by, request_id=rid
            )
        except (AccountScopeDenied, OrderEntryRefused) as exc:  # a raise would land `unknown`
            if isinstance(exc, OrderEntryRefused) and exc.reason != _NO_ACTIVE_KEY:
                raise
            reason = ACCOUNT_UNAVAILABLE_REASON
            return await self._amend_refused(
                row, ACCOUNT_UNAVAILABLE, reason, detail, by=by, request_id=rid
            )
        request = AmendOrderRequest(
            account=account,
            symbol=row.symbol,
            order_link_id=row.order_link_id,
            exchange_order_id=row.exchange_order_id,
            qty=requested.get("qty"),
            price=requested.get("price"),
            trigger_price=requested.get("trigger_price"),
            take_profit=take_profit,
            stop_loss=stop,
            lane=_amend_lane(row, watch),
        )
        _check_amend_stops(request)
        recorded: tuple[RecordedStopRow, ...] = ()
        if stop is not None:
            key = PositionKey(account.account_id, row.symbol, row.position_idx)
            try:  # Q4 on every stop recorded or sent, read after the gate, before the record (m2)
                await self._bounded(self._gate.clear(key), by=by)
                live = self._stops.live_for_key(key.account_id, row.symbol, row.position_idx)
                in_force = await self._bounded(live, by=by)
            except StopRequestPending as held:
                return _held(row.order_link_id, held.retry_after_s)
            except _UNREAD as exc:
                return await self._unread(
                    row.id, row.exchange_account_id, detail, exc, by=by, request_id=rid
                )
            loose = ratchet_refusal(
                side=row.side, requested=stop, current=row.stop_loss, in_force=in_force
            )
            if loose is not None:
                return await self._amend_refused(
                    row, STOP_LOOSENING_REFUSED, loose, detail, by=by, request_id=rid
                )
            try:  # any other failure raises: a timed-out insert may have committed rows that only
                # the complete read resolves, so it is never answered as unsent (fold 2 minor 2)
                recorded = await self._record_amend(
                    row, stop, take_profit, detail, _moved(row, sides), by=by, actor=actor,
                    request_id=rid, origin=origin,
                )  # fmt: skip
            except StopRequestInFlight:
                return _held(row.order_link_id, STOP_REQUEST_RETRY_AFTER_S)
        port = self._router.port_for(account.environment)
        try:
            venue_by = by - AMEND_SETTLE_RESERVE_S  # the settle keeps its time
            ack = await self._venue_gated(account, port.amend_order(request), by=venue_by)
        except RateBudgetExceededError as exc:  # nothing left: the rows are void, unsent
            code = OmsErrorCode.RATE_BUDGET_EXCEEDED.value
            if recorded:
                await self._settle_stop(
                    recorded, False, code, detail, reason=AMEND_REFUSED, by=by, actor=actor,
                    request_id=rid, origin=origin,
                )  # fmt: skip
            _log().warning("oms_amend_rate_refused", order_link_id=row.order_link_id)
            retry = retry_after(exc.retry_after_s)
            return {"ok": False, "error_code": code, "retry_after_s": retry}
        if not ack.ok:  # its report ends with the call: the settle keeps its reserve (CG19)
            await self._venue(account, ack.error_code, ack.exchange_ret_code, by=venue_by)
        if recorded:
            await self._settle_stop(
                recorded, ack.ok, ack.error_code, detail, reason=AMEND_REFUSED, by=by, actor=actor,
                request_id=rid, origin=origin,
            )  # fmt: skip
        if ack.ok:
            if self._figures is not None:  # the amend moved the account's room
                self._figures.invalidate(account.account_id)
            kept = order_id_kept(ack.exchange_order_id)
            bound = {} if kept is None else {"exchange_order_id": kept}
            return {"ok": True, **bound, **_record(ack)}
        refused = {"ok": False, "error_code": ack.error_code}
        return {**refused, "exchange_ret_code": ack.exchange_ret_code, **_record(ack)}

    async def _unread(
        self,
        order_id: UUID,
        account_id: UUID,
        detail: Mapping[str, str | None],
        exc: BaseException,
        *,
        by: float,
        request_id: UUID | None,
    ) -> dict[str, Any]:
        """The 10:18Z ruling: a read failing before the send is `STORE_UNAVAILABLE`, nothing sent
        and the order live, audited ahead under the request's `request_id` within
        `AMEND_AUDIT_GRACE_S` past the amend's bound (an audit that fails raises, C-2.9). A stored
        row read that fails is audited under the command's own ids, before `_check_names`: B1's
        context is the server's, so trusted."""
        failure = type(exc).__name__
        await self._audit_order(
            order_id, account_id, ORDERS_AMEND, "denied", "warning", STORE_UNAVAILABLE_REASON,
            {**detail, "failure": failure}, request_id=request_id, by=by + AMEND_AUDIT_GRACE_S,
        )  # fmt: skip
        _log().warning("oms_amend_store_unavailable", order_link_id=detail.get("order_link_id"))
        retry = retry_after(STORE_UNAVAILABLE_RETRY_AFTER_S)
        return {"ok": False, "error_code": STORE_UNAVAILABLE, "retry_after_s": retry}

    async def _amend_refused(
        self,
        row: OrderRow,
        code: str,
        reason: str,
        detail: Mapping[str, str | None],
        *,
        by: float,
        request_id: UUID | None,
    ) -> dict[str, Any]:
        """A refusal, nothing recorded or sent, audited ahead (`orders.amend` denied, C-2.9) under
        the request's `request_id`, within `AMEND_AUDIT_GRACE_S` past the amend's bound, as
        `_unread`'s."""
        await self._audit_order(
            row.id,
            row.exchange_account_id,
            ORDERS_AMEND,
            "denied",
            "warning",
            reason,
            detail,
            request_id=request_id,
            by=by + AMEND_AUDIT_GRACE_S,
        )
        _log().warning("oms_amend_refused", order_link_id=row.order_link_id, code=code)
        return {"ok": False, "error_code": code}

    async def _record_amend(
        self,
        row: OrderRow,
        stop: Decimal,
        tp: Decimal | None,
        detail: Mapping[str, str | None],
        changed: Mapping[str, object],
        *,
        by: float,
        request_id: UUID | None,
        actor: SubmitActor | None = None,
        origin: RuleOrigin | None = None,
    ) -> tuple[RecordedStopRow, ...]:
        """Q2: one `entry_attach` insert naming the order, each row audited in its transaction;
        a re-paired side the amend does not change is audited `changed: "false"`. Rows and records
        name the requesting principal the amend's exit watch holds (`actor`, C-2.9), and records
        its request's correlation id (`request_id`, #4643); a rule's amend (`origin`) makes each
        record the rule's, naming that principal as the owner it acts for (24 Sec.15.5)."""
        sides: dict[StopKind, Decimal | None] = {"stop_loss": stop, "take_profit": tp}
        news = [
            NewRecordedStop(
                id=(i := uuid4()), exchange_account_id=row.exchange_account_id, symbol=row.symbol,
                position_idx=_POSITION_IDX[row.position_idx], position_side=row.side, kind=kind,
                source="entry_attach", order_id=row.id, tpsl_mode="Full", trigger_price=price,
                size=None, audit_record_id=self._submit_audit.record_id(_MODIFIED[kind], str(i)),
                actor_user_id=None if actor is None else actor.user_id,
            )
            for kind, price in sides.items()
            if price is not None
        ]  # fmt: skip
        marked = {kind: {**detail, "changed": str(kind in changed).lower()} for kind in sides}
        records = [
            _stop_record(
                _MODIFIED[new.kind], new, "success", "info", AMEND_REASON, marked[new.kind], actor,
                request_id=request_id, origin=origin,
            )
            for new in news
        ]  # fmt: skip

        async def requested(_rows: tuple[RecordedStopRow, ...]) -> None:
            for record in records:
                await self._submit_audit.write(record)

        return await self._bounded(self._stops.record(news, write_ahead=requested), by=by)

    # --- the rest ----------------------------------------------------------------------------

    async def _stored(self, command: b01.Command, *, by: float | None = None) -> OrderRow:
        """The command's order as stored: by its account and `order_link_id`, and the same id."""
        link = b01.text_id(command.order.get("order_link_id"))
        if link is None:
            raise ValueError("the command names no order_link_id")
        account_id = _uuid(command.order.get("account_id"))
        row = await self._bounded(self._orders.get_by_link_id(account_id, link), by=by)
        if row is None:
            raise ValueError("no stored order of the account holds the command's id")
        _check_names(command, row)
        return row

    async def _order_of(self, command: b01.Command) -> tuple[StoredOrder, UUID | None]:
        """The registered order (unspent) and its request's id, else the stored one and None;
        either named as the command is."""
        watch = self._watches.get(_uuid(command.order.get("order_id")))
        if watch is None:
            return await self._stored(command), None
        _check_names(command, watch.order)
        return watch.order, watch.request_id

    async def _account(self, order: StoredOrder, *, by: float | None = None) -> AccountRef:
        """The order's account as the trading port takes it, with its own key (SR-E27-21)."""
        account_id = AccountId(order.exchange_account_id)
        account = await self._bounded(self._accounts.trading_account(account_id), by=by)
        if account.account_id != order.exchange_account_id:
            raise ValueError("the trading account resolved is another account's")
        return account

    async def _position(
        self, account: AccountRef, port: RoutedPort, row: OrderRow
    ) -> Position | None:
        read = read_position(port, account, row.symbol, row.position_idx)
        return await self._venue_gated(account, read, by=self._deadline(self._port_timeout_s))

    def _deadline(self, seconds: float) -> float:
        """The loop's time `seconds` from now: a deadline one call, or all of `place`, ends by."""
        return asyncio.get_running_loop().time() + seconds

    async def _bounded[T](self, call: Awaitable[T], *, by: float | None = None) -> T:
        """`call` within `PORT_TIMEOUT_S`, and by `by` (`place`'s deadline, CR-2B1-04) when that
        comes first: each call keeps a timeout of its own, so a caller that catches one (a
        best-effort report, a hand-over, an alert) still catches it at the deadline."""
        when = self._deadline(self._port_timeout_s)
        async with asyncio.timeout_at(when if by is None else min(when, by)):
            return await call

    async def _venue_gated[T](self, account: AccountRef, call: Awaitable[T], *, by: float) -> T:
        """The exchange `call`, by `by`; then, out of its window, 24 Sec.8.6's branch for a
        raised `AuthError` or `ClockDriftError`, its report bounded on its own (and by `by`)."""
        try:
            async with asyncio.timeout_at(by):
                return await call
        except (AuthError, ClockDriftError) as exc:
            await self._venue(account, exc.code.value, exc.exchange_ret_code, by=by)
            raise

    async def _venue(
        self,
        account: AccountRef,
        code: str | None,
        ret_code: int | None,
        *,
        by: float | None = None,
    ) -> None:
        """24 Sec.8.6, before the answer (module docstring). Its own failures are logged, never
        raised: the exchange's answer stands."""
        if code == OmsErrorCode.CLOCK_DRIFT:
            self._clock_halt.trip()
            _log().critical("oms_clock_drift_halt", environment=account.environment)
            if not self._closed and (self._resync is None or self._resync.done()):
                resync = self._clock_halt.resync(reason=CLOCK_RESYNC_REASON)
                self._resync = spawn(resync, name="oms-clock-resync")
        elif code == OmsErrorCode.AUTH_ERROR and ret_code is not None:
            try:  # the call too: a port that raises before awaiting loses only the report
                refused = self._credentials.refused(
                    account.account_id, error_code=code, exchange_ret_code=ret_code
                )
                await self._bounded(refused, by=by)
            except Exception as exc:  # the rejection is lost, never the order's answer
                _log().critical("oms_auth_rejection_lost", failure=type(exc).__name__)

    async def _audit_order(
        self,
        order_id: UUID,
        account_id: UUID,
        action: str,
        outcome: AuditOutcome,
        severity: AuditSeverity,
        reason: str,
        detail: Mapping[str, str | None],
        *,
        request_id: UUID | None = None,
        by: float | None = None,
    ) -> None:
        """A record about the order, written ahead of its answer (C-2.9): one that does not land,
        by `by` when given, raises, so nothing is answered unrecorded. `request_id` is the
        registering request's (#3990), never read from the context the call runs in."""
        record = OrderAuditRecord(
            action, order_id, account_id, outcome, severity, reason, detail, request_id
        )
        await self._bounded(self._audit.write(record), by=by)


def _transient(error: Exception) -> bool:
    """What an outage raises, which a later read may pass: a timeout, `StoreUnavailable`, or a
    storage failure that is no data refusal (the order machine's test of what every try meets)."""
    if isinstance(error, TimeoutError | StoreUnavailable):
        return True
    return isinstance(error, StorageError) and not is_data_refusal(error)


def _parked(error: BaseException) -> dict[str, Any] | None:
    """An exit watch's answer to a cancel that raised: None, but for the venue's 110001, which says
    why B1 parks the order in `unknown` (and its code), so an exit service tells it from a fault."""
    if not isinstance(error, NotFoundError):
        return None
    return {
        "ok": False,
        "unknown": b01.ALREADY_TERMINAL,
        "exchange_ret_code": error.exchange_ret_code,
    }


def _held(link: str, wait: int) -> dict[str, Any]:
    """A key a stop request still holds: 409 `stop_request_in_flight`, never a raise."""
    _log().warning("oms_amend_stop_key_held", order_link_id=link)
    return {"ok": False, "error_code": STOP_REQUEST_IN_FLIGHT, "retry_after_s": wait}


def _check_names(command: b01.Command, order: StoredOrder) -> None:
    """The command names `order` (its id, `order_link_id` and account), else `ValueError`."""
    named = tuple(command.order.get(key) for key in ("order_id", "order_link_id", "account_id"))
    if named != (str(order.id), order.order_link_id, str(order.exchange_account_id)):
        raise ValueError("the command names another order than the stored one")


def _stop_record(
    action: str,
    row: NewRecordedStop | RecordedStopRow,
    outcome: AuditOutcome,
    severity: AuditSeverity,
    reason: str,
    detail: Mapping[str, str | None],
    actor: SubmitActor | None = None,
    *,
    name: str | None = None,
    request_id: UUID | None = None,
    origin: RuleOrigin | None = None,
) -> KeyedRecord:
    """A stop request's record, the row its object and the row's id its name (21 Sec.3.3.11), or
    `name`, which only a void's gives (`_void_record`); it names the row's own principal
    (`actor_user_id`) and, for a user's, the request's `actor` with the role, which the writer
    refuses it without (C-2.9), and the request's correlation id (`request_id`, #4643). A rule's
    (`origin`) is the rule's record, and its `actor` the owner it acts for (24 Sec.15.5)."""
    return KeyedRecord(
        action=action,
        name=str(row.id) if name is None else name,
        account_id=row.exchange_account_id,
        object_kind="recorded_stop",
        object_id=row.id,
        outcome=outcome,
        severity=severity,
        reason=reason,
        actor_user_id=row.actor_user_id,
        actor=actor,
        detail={**detail, "kind": row.kind, "source": row.source},
        request_id=request_id,
        origin=origin,
    )


def _void_record(
    row: RecordedStopRow,
    reason: str,
    detail: Mapping[str, str | None],
    actor: SubmitActor | None,
    request_id: UUID | None,
    origin: RuleOrigin | None = None,
) -> KeyedRecord:
    """A refused request's void of `row`, `sl.modified` (`tp.modified` for a take-profit side)
    denied with `reason` under the request's `actor`, `request_id` and, for a rule's, `origin`;
    every void the port writes is built here. It is named `<reason>:<row id>`, as the stop
    gate's and the sweep's voids are, never as its request: an amend's request holds `<row id>`
    under the same action, and a void named so would be deduped against it and lost (#4587)."""
    name = f"{reason}:{row.id}"
    return _stop_record(
        _MODIFIED[row.kind], row, "denied", "warning", reason, detail, actor, name=name,
        request_id=request_id, origin=origin,
    )  # fmt: skip
