"""candleviewer.statechart.bindings.b01_order — MachineLogic for B1 `order`
(#1650, E50; E29-T03 #847). Chart: `machines/B01.order.machine.json`, version 5.

Guards are pure, total and deny by default (catalogue A6). Statecharts record, synchronous code
enforces (C-2.21): `VALIDATE` carries the verdicts of the checks run before it (`gates`) and the
order. `EXEC` carries a 24-internal-schemas.md Sec.8.1 `Execution` and its `exchange_order_id`.
Money is canonical decimal text in context, like the chart's `"qty": "0"`: a snapshot stays plain
JSON. Every event has a closed payload schema (`SCHEMAS`), registered for this machine only.

The effects go through what the OMS facade wires (`set_ports`, `set_audit_hook`,
`set_fill_core`), as the statechart package imports no `oms` module (C-3.1):

* `persist_event` hands each `lifecycle` step to the write-ahead store inside
  `asyncio.timeout(CV_PERSIST_TIMEOUT)`. A refused or timed-out write raises, and
  `actionErrorPolicy: "rollback"` leaves configuration and context as they were (24 Sec.8.2 S7,
  S8, S11). It is the one action that raises by design; the rest are total (A1). A timed-out
  write raises `StepOutcomeUnknown`: its row may have committed, so the facade rebuilds the order
  from its events.
* The services call the OMS's command port (E29-T04) inside `asyncio.timeout(CV_COMMAND_TIMEOUT)`;
  it answers a Sec.14.4 `OrderAck` and raises on an ambiguous outcome, as does a call that does not
  answer in time, so `onError` lands in `unknown` (S1). Each is idempotent under re-entry: a
  rollback that re-arms an invoke gets the recorded outcome, never a second send, and a `place`
  this process did not begin looks the id up before it sends (SR-E29-15).
* The notices (`notify_*`, `emit_terminal`, the alerts, the `request_*` hand-offs) go to the
  bounded `outbox` in context, which the facade drains: no action sends to its own machine
  (CV-C25), and a rolled-back step takes its notices with it (CV-C02).
* Hydration (24 Sec.8.2 "Recovery"): the facade replays an order's recorded steps on a fresh
  machine between `begin_replay` and `end_replay`, as B16 replays its already-audited events. The
  replay is marked here, by order, not by a `replay` key in each payload: B1's closed schemas take
  none, and no push could claim one. The order's attempts this process kept are forgotten first,
  so a machine a resync rebuilt resumes as a restarted one does. The persist port answers each
  replayed step's recorded `seq` with nothing written, and the facade audits and notifies nothing
  for it; a service answers the outcome the record holds, and one the record does not answer
  waits for the replay to end, so nothing is sent again for a step the record holds (S8,
  SR-E29-15).

KILL (owner decision #1778 item X, option a): root `lifecycle.on.KILL` lands in the final
`lifecycle.killed`, whose entry marks the order `halted_by_kill`, audits (write-ahead, C-2.9),
then cancels through the OMS's audited cancel service (SR-E29-06), unless the order was never
sent or is an unverified duplicate; `cancel_pending` keeps its in-flight cancel instead of sending
a second one. The cancel outcome is not trusted here: reconciliation re-syncs the exchange (C-2.5).
The `protection` region is untouched by KILL (C-2.6): it only audits. A recorded stop's row
(`MATERIALISED`, 24 Sec.8.3 rule 7) is a position's protective stop, so KILL never cancels it: in
each live state it can reach, the guarded `is_recorded_stop` arm, ahead of the cancelling one,
consumes and audits the KILL and sends nothing.

A recorded stop's row follows its order's trigger price and quantity through `TERMS_CHANGED`, a
written step (24 Sec.8.3 rule 7, the sixth item; INV-B1-q): the guarded `recorded_terms_changed`
arm re-enters `submitted`, `triggered` or `partially_filled`, and `audit_terms_refused` records
any other, never as a `guard_denied` the OMS would answer with `FAULT`.
"""

from __future__ import annotations

import asyncio
import re
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, replace
from decimal import Context, Decimal
from typing import Any, Final, Literal, Protocol

import structlog

from candleviewer.exchange.base.errors import NotFoundError, OmsErrorCode
from candleviewer.statechart.bindings import register_binding_module
from candleviewer.statechart.config import (
    CV_COMMAND_TIMEOUT,
    CV_KILL_CANCEL_TIMEOUT,
    CV_PERSIST_TIMEOUT,
    register_event_schemas,
)


def logger() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


#: Audit hook injected by the OMS (bindings never import `audit`; B10/B16 pattern).
#: Called as `hook(name, context)`; must not raise.
AuditHook = Callable[[str, dict[str, Any]], Awaitable[None]]


async def _no_hook(_name: str, _ctx: dict[str, Any]) -> None:
    return None


_hook: AuditHook = _no_hook


def set_audit_hook(hook: AuditHook | None) -> None:
    global _hook
    _hook = hook or _no_hook


#: `oms.execution.apply_fields`, which the OMS facade sets like the audit hook, as the statechart
#: package imports no `oms` module (C-3.1). It refuses fills with `ValueError`, as does its absence.
FillCore = Callable[[Mapping[str, Decimal], Mapping[str, Decimal]], Mapping[str, Decimal | None]]
_core: FillCore | None = None


def set_fill_core(core: FillCore | None) -> None:
    global _core
    _core = core


CommandKind = Literal["place", "cancel", "kill_cancel", "amend", "attach_stop", "lookup"]


@dataclass(frozen=True, slots=True)
class Step:
    """One `lifecycle` step for its write-ahead row (24 Sec.8.2 S8), as `persist_event` hands it
    to the OMS: the lifecycle state of the last committed row (`from_state`, None before the row
    exists) and the state entered, the trigger (an event name, or `done.invoke.<id>` and
    `error.platform.<id>` for a service's result) with its payload, and the context it leaves."""

    order_id: str | None
    account_id: str | None
    order_link_id: str | None
    from_state: str | None
    to_state: str
    event: str
    payload: Mapping[str, Any]
    context: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class Command:
    """A request to the OMS's command port. `key` names one attempt (the order, the command and
    the `event_seq` of the step that entered its state), stable across a rollback's re-entry, so
    the port can deduplicate on it. `order` is the context's view of the order; `terms` an
    amend's requested terms or the stop an attach asks for."""

    kind: CommandKind
    key: str
    order: Mapping[str, Any]
    terms: Mapping[str, Any]


class CommandPort(Protocol):
    """The OMS's exchange side (E29-T04 implements it, through its audited, budget-drawing
    services, SR-E29-06). Each answers a 24 Sec.14.4 `OrderAck` as a mapping (`ok`, `error_code`,
    `exchange_order_id`; an attach adds the `position` row it read back) and raises on an
    ambiguous outcome (a timeout, a transport error, an HTTP 5xx, `UNKNOWN_STATE`,
    `TRANSPORT_ERROR`, `SERVICE_UNAVAILABLE`), so the order reaches `unknown` (S1). An accepted
    `place` names its `exchange_order_id` as B1 keeps one (`text_id`); one that does not is an
    ambiguous outcome too (ruling 3 on #3972; #3972's 24 Sec.8.3 rule 7), which B1 raises as
    `ExchangeOrderIdMissingError`. `lookup` answers the order found under the `order_link_id` in
    realtime and history (24 Sec.8.3 rule 3), or an empty mapping. `cancel` serves a KILL's cancel
    too (`kind` `kill_cancel`). An `attach_stop` is never answered from an earlier call's result:
    a rebuilt machine attaches under the same key and must read the position back afresh
    (INV-B1-f)."""

    async def place(self, command: Command) -> Mapping[str, Any]: ...

    async def cancel(self, command: Command) -> Mapping[str, Any]: ...

    async def amend(self, command: Command) -> Mapping[str, Any]: ...

    async def attach_stop(self, command: Command) -> Mapping[str, Any]: ...

    async def lookup(self, command: Command) -> Mapping[str, Any]: ...


#: The write-ahead store: commits the step's `order_events` row (with its execution for a fill)
#: and answers the row's `seq`; it raises, with nothing written, when it refuses (S7).
PersistPort = Callable[[Step], Awaitable[int]]


def _wall_us() -> int:
    return time.time_ns() // 1_000


@dataclass(frozen=True, slots=True)
class OrderPorts:
    """What the OMS facade wires into B1. Unwired, `persist_event` refuses every step past
    `draft` and the services raise, so an order goes nowhere it cannot be recorded (S7)."""

    persist: PersistPort | None = None
    commands: CommandPort | None = None
    now_us: Callable[[], int] = _wall_us


_ports = OrderPorts()


def set_ports(ports: OrderPorts | None) -> None:
    global _ports
    _ports = ports or OrderPorts()


def ports_wired() -> bool:
    """Whether an OMS facade wired B1's ports: they are process-wide, so a second facade would take
    over the first one's machines (one facade per process, C-2.11)."""
    return _ports.persist is not None


class PortMissingError(RuntimeError):
    """B1 needs a port the OMS facade has not wired."""


class RecordedFailureError(RuntimeError):
    """A re-entered invoke whose command already failed: it fails again, with nothing resent."""


class ExchangeOrderIdMissingError(RuntimeError):
    """An accepted `place` whose answer names no exchange order id B1 keeps (`text_id`: text of 1
    to `MAX_TEXT` characters with no control character): an ambiguous outcome (ruling 3 on #3972;
    #3972's 24 Sec.8.3 rule 7), so the order waits in `unknown` for reconciliation (S1), never in
    `submitted` with nothing bound."""


class StepOutcomeUnknown(RuntimeError):
    """The write-ahead store did not answer in time: the step rolls back, but its row may have
    committed (a COMMIT in flight still lands), so the OMS facade rebuilds the order from its
    events, where the row decides (24 Sec.8.2 S7)."""


#: `VALIDATE`'s verdicts (each `PASSED`: a bool could read as "engaged"), the order's identity, the
#: terms an amend may change besides `qty` (22-api-openapi.yaml `AmendOrderRequest`), and what an
#: EXEC shares with its order: it pairs on the bound exchange order id (SR-E29-03).
GATES: Final = ("risk", "rate", "kill_switch", "live_gate", "native_stop")
PASSED: Final = "pass"
FAILED: Final = "fail"
FACTS: Final = ("order_id", "order_link_id", "account_id", "symbol", "side")
TERMS: Final = ("price", "trigger_price", "take_profit", "stop_loss")
PAIRING: Final = ("exchange_order_id", *FACTS)
#: The OMS codes the binding records (24 Sec.8.6): the native-stop refusal E32-T01 decides, and
#: two reconciliation passes that found nothing (Sec.8.5).
NATIVE_STOP_REQUIRED: Final = "NATIVE_STOP_REQUIRED"
UNRESOLVED_AFTER_RECONCILE: Final = "UNRESOLVED_AFTER_RECONCILE"
#: The command port's answer to a resumed create too old to re-send that no lookup found within
#: the venue's 24 h history (E29-T04, [LANE-26]; 24 Sec.8.3 rule 6): nothing was sent, so
#: `submitting`'s last arm ends the order `rejected`, and `map_reject_code` keeps it as the row's
#: reason. Past that history the port answers an empty lookup instead (`unknown`, SEC-2B1-02).
EXPIRED_UNSENT: Final = "EXPIRED_UNSENT"
#: Why an order waits in `unknown` with no transport fault: the venue answered a cancel's 110001
#: (`NotFoundError`). It does not hold the order, which says nothing of how it ended (24 Sec.8.6).
ALREADY_TERMINAL: Final = "already_terminal"
#: The fact `issue_kill_cancel` leaves in context for the KILL's own result (`OrderMachines.kill`):
#: `sent`, the code of an answer that cancelled nothing, `already_terminal`, `timeout` or `failed`.
KILL_CANCEL: Final = "kill_cancel"
#: Bounds on what a payload may put into context (C-2.18): fills per order, id text, and money as
#: 22's `Decimal` text (C6: no exponent, space or `_`) with numeric(38,18)'s 20 + 18 digits.
MAX_FILLS: Final = 10_000
MAX_TEXT: Final = 64
#: The last microsecond since the epoch a `datetime` holds (9999-12-31): no exchange time is later.
MAX_EXCHANGE_US: Final = 253_402_300_799_999_999
_MONEY: Final = re.compile(r"-?[0-9]{1,20}(\.[0-9]{1,18})?")
#: Control characters (Unicode `Cc`: C0, DEL and C1), which no id, code or text B1 keeps holds:
#: in an exchange id or code one is hostile or malformed data (OM-T04), and Postgres refuses NUL
#: in a bound text column (22021), so B1 refuses it before the write-ahead store would.
_CONTROL: Final = re.compile(r"[\x00-\x1f\x7f-\x9f]")
#: Deadlines (A2), absolute microseconds the OMS's scheduler fires: the stop is confirmed within
#: 2 s of the first fill (24 Sec.8.8 rule 2), and an order still `unknown` pages at 60 s (Sec.8.5).
SL_DEADLINE_US: Final = 2_000_000
RECON_DEADLINE_US: Final = 60_000_000
#: Notices the facade has not drained (C-2.18): past it the oldest is dropped, logged at ERROR.
OUTBOX_MAX: Final = 64
#: Command outcomes this process keeps for re-entry, the oldest dropped first (C-2.18).
MAX_ATTEMPTS: Final = 4096
REPEAT: Final = "a repeat exec_id (S4)"
#: An EXEC before the bind waits in the facade's reorder buffer (SR-E29-03), never a FAULT.
UNBOUND: Final = "the order has no bound exchange_order_id yet"
#: The terms a recorded stop's row takes from its order on the exchange (24 Sec.8.3 rule 7).
FOLLOWED: Final = ("qty", "trigger_price")
#: A redelivered `TERMS_CHANGED` naming the terms the row holds (S4, S5): quiet, never recorded.
UNCHANGED: Final = "the push names the terms the row holds"
_REJECT_CODES: Final = frozenset(code.value for code in OmsErrorCode) | {EXPIRED_UNSENT}
_DUPLICATE: Final = OmsErrorCode.DUPLICATE_CLIENT_ID.value
#: A KILL's cancel answered without a cancel, by code: the record each is audited under (C-2.9).
_KILL_REFUSALS: Final = {
    OmsErrorCode.ORDER_NOT_FOUND.value: "kill_cancel_already_terminal",
    OmsErrorCode.RATE_BUDGET_EXCEEDED.value: "kill_cancel_rate_budget_exceeded",
}
#: Codes 24 Sec.8.6 routes to retry, poll or reconcile: the command port raises them (S1), so one
#: recorded as a reject is logged at ERROR.
_AMBIGUOUS: Final = frozenset({"TRANSPORT_ERROR", "SERVICE_UNAVAILABLE", "UNKNOWN_STATE"})
#: The invoking `lifecycle` states and the command each one's service sends.
_INVOKES: Final = {"submitting": "place", "cancel_pending": "cancel", "amend_pending": "amend"}
#: The steps that create the order's row, each a state and the event that enters it from `draft`:
#: `validated` (24 Sec.8.4), `untracked` (S9) and a recorded stop's `submitted` (Sec.8.3 rule 7).
FIRST_ROWS: Final = {
    "validated": "VALIDATE",
    "untracked": "DISCOVERED",
    "submitted": "MATERIALISED",
}
_READINGS: Final = ("SL_OBSERVED", "SL_LOST")
#: The states an order enters only with a fill reported, whose entry always starts the stop.
_FILL_STATES: Final = frozenset({"partially_filled", "filled"})


def _fields(event: Any) -> Mapping[str, Any]:
    """An `Event`'s payload or an `onDone` result, when it is a mapping; else empty. A failed
    service's event carries the exception, never data (CV-C21)."""
    if hasattr(event, "payload"):
        value = event.payload
    elif hasattr(event, "error"):
        value = None
    else:
        value = getattr(event, "data", event)
    return value if isinstance(value, Mapping) else {}


def _name(event: Any) -> str:
    kind = getattr(event, "type", "")
    return kind if isinstance(kind, str) else ""


def _leaf(interp: Any, region: str = "lifecycle") -> str | None:
    """The machine's active leaf in *region*; an entry action sees the state it enters."""
    head = f"order.{region}."
    ids = getattr(interp, "current_state_ids", ())
    return next((s[len(head) :] for s in ids if isinstance(s, str) and s.startswith(head)), None)


def text_id(raw: object) -> str | None:
    """*raw* as B1 keeps an id or a code: text of 1 to `MAX_TEXT` characters with no control
    character (`_CONTROL`), else None. The OMS facade keeps an `exec_id` by the same rule. The
    exchange adapter's order id is text of 1 to 64 characters (`ExchangeOrderId`, 24 Sec.14.2 rule
    11), so `MAX_TEXT` holds every one; E29-T04's command port also refuses an accepted create
    whose id is not printable or holds whitespace (`oms.commands.order_id_kept`, #4020 Low 1)."""
    if isinstance(raw, str) and 0 < len(raw) <= MAX_TEXT and _CONTROL.search(raw) is None:
        return raw
    return None


_id = text_id


def _money(raw: object) -> Decimal:
    """Money from `_MONEY` text, else `ValueError`; never from a float."""
    if not isinstance(raw, str) or not _MONEY.fullmatch(raw):
        raise ValueError("a money value is not C6 text that numeric(38,18) holds")
    return Decimal(raw)


def _text(value: Decimal) -> str:
    """Canonical decimal text: fixed point, no exponent, no trailing zeros."""
    out = format(value, "f")
    out = out.rstrip("0").rstrip(".") if "." in out else out
    return "0" if out == "-0" else out


def _same(a: object, b: object) -> bool:
    """Two money values agree: both absent, or equal amounts (`ValueError` if malformed)."""
    if a is None or b is None:
        return a is None and b is None
    return _money(a) == _money(b)


def _positives(raw: object, keys: tuple[str, ...]) -> dict[str, Decimal]:
    """*raw*'s money for *keys*, each above zero (absent or null: skipped), else `ValueError`."""
    if not isinstance(raw, Mapping):
        raise ValueError("the terms are not a mapping")
    out = {key: _money(raw[key]) for key in keys if raw.get(key) is not None}
    if any(value <= 0 for value in out.values()):
        raise ValueError("a term is zero or less")
    return out


def _filled(context: Mapping[str, Any]) -> bool:
    try:
        return _money(context.get("filled_qty", "0")) > 0
    except ValueError:
        return False


def _misses(context: Mapping[str, Any]) -> int:
    value = context.get("recon_misses", 0)
    return value if type(value) is int and value >= 0 else 0


def _code(event: Any) -> str | None:
    code = _fields(event).get("error_code")
    return code if isinstance(code, str) and len(code) <= MAX_TEXT else None


def _gates(event: Any) -> Mapping[str, Any]:
    gates = _fields(event).get("gates")
    return gates if isinstance(gates, Mapping) else {}


def _order(order: Mapping[str, Any]) -> dict[str, Any]:
    """An order's identity and terms as context values, else `ValueError`."""
    facts = {key: _id(order.get(key)) for key in FACTS}
    terms = _positives(order, ("qty", *TERMS))
    reduce_only = order.get("reduce_only", False)
    if "qty" not in terms or None in facts.values() or not isinstance(reduce_only, bool):
        raise ValueError("the order has no qty, a malformed identity or a reduce_only not a bool")
    stamped = {**facts, **dict.fromkeys(TERMS), **{key: _text(v) for key, v in terms.items()}}
    return stamped | {"leaves_qty": stamped["qty"], "reduce_only": reduce_only}


def _validated(event: Any) -> dict[str, Any] | None:
    """The order as context values when every verdict is `PASSED`; `ValueError` if malformed."""
    order = _fields(event).get("order")
    if not isinstance(order, Mapping) or any(_gates(event).get(g) != PASSED for g in GATES):
        return None
    return _order(order)


def _pairs(context: Mapping[str, Any], p: Mapping[str, Any]) -> bool:
    """*p* is a trade of the exchange order this order is bound to, every field it pairs on the
    order's own (SR-E29-03)."""
    return (
        p.get("exec_type") == "trade"
        and _id(context.get("exchange_order_id")) is not None
        and all(_id(p.get(key)) is not None and p.get(key) == context.get(key) for key in PAIRING)
    )


def _admit(
    context: Mapping[str, Any], p: Mapping[str, Any]
) -> tuple[str, Mapping[str, Decimal | None]]:
    """`(exec_id, the order's totals after it)` for a new trade execution *p* of this order, else
    a `ValueError` saying why: `REPEAT` (S4), `UNBOUND`, another order's (SR-E29-03) or hostile
    (OM-T04)."""
    seen = context.get("seen_exec_ids")
    exec_id = _id(p.get("exec_id"))
    if exec_id is None or not isinstance(seen, list):
        raise ValueError("the execution has no exec_id, or the order no seen_exec_ids")
    if exec_id in seen:
        raise ValueError(REPEAT)
    if _id(context.get("exchange_order_id")) is None:
        raise ValueError(UNBOUND)
    if not _pairs(context, p):
        raise ValueError("the execution is not a trade of this order's bound exchange order")
    if p.get("fee_currency") is not None and _id(p.get("fee_currency")) is None:
        raise ValueError("the execution's fee currency is not text an id holds")
    if len(seen) >= MAX_FILLS:
        raise ValueError("the order holds MAX_FILLS fills")
    if _core is None:
        raise ValueError("the OMS has not set its fill arithmetic")
    fill = {key: _money(p.get(key)) for key in ("qty", "price", "fee", "fee_rate")}
    totals = ("qty", "filled_qty", "cum_exec_value", "fee_paid")
    return exec_id, _core({key: _money(context.get(key, "0")) for key in totals}, fill)


def _apply(context: dict[str, Any], p: Mapping[str, Any]) -> None:
    """S4: an admitted execution's totals, and its `exec_id` in `seen_exec_ids` (INV-B1-b)."""
    try:
        exec_id, totals = _admit(context, p)
    except ValueError:
        return
    context.update(
        {key: None if value is None else _text(value) for key, value in totals.items()},
        seen_exec_ids=[*context["seen_exec_ids"], exec_id],
    )


def _bind(context: dict[str, Any], raw: object, mismatch: str) -> None:
    """Record the exchange order id once; a different one later is logged, never adopted."""
    new, known = _id(raw), context.get("exchange_order_id")
    if new is not None and known is None:
        context["exchange_order_id"] = new
    elif new is not None and new != known:
        logger().error(mismatch, order_link_id=context.get("order_link_id"))


def _post(context: dict[str, Any], kind: str, **detail: Any) -> None:
    """Queue a notice for the OMS facade (CV-C25). It lives in context, so a rolled-back step
    takes it back (CV-C02); `seq` orders it for the facade's cursor; at most `OUTBOX_MAX`."""
    raw = context.get("outbox")
    box = (
        [dict(entry) for entry in raw if isinstance(entry, Mapping)]
        if isinstance(raw, list)
        else []
    )
    last = box[-1].get("seq") if box else -1
    box.append({"seq": last + 1 if type(last) is int else 0, "kind": kind, **detail})
    if len(box) > OUTBOX_MAX:
        dropped = box.pop(0)
        link = context.get("order_link_id")
        logger().error("b01_outbox_overflow", order_link_id=link, dropped=dropped.get("kind"))
    context["outbox"] = box


# --- Guards: pure, total, deny by default (A6) ------------------------------------------------


def _total(name: str, check: Callable[[], bool]) -> bool:
    """A6: a guard that fails denies, logged at ERROR; it never raises."""
    try:
        return check()
    except Exception as exc:  # any internal failure is a denial (A6)
        logger().error("b01_guard_failed", guard=name, failure=type(exc).__name__)
        return False


def exec_new_and_closes(context: dict[str, Any], event: Any) -> bool:
    """A new EXEC of this order that fills it; in `cancel_pending` the fill wins (S3)."""
    return _total("exec_new_and_closes", lambda: _closes(context, event) is True)


def exec_new_and_partial(context: dict[str, Any], event: Any) -> bool:
    """A new EXEC of this order that leaves quantity open."""
    return _total("exec_new_and_partial", lambda: _closes(context, event) is False)


def _closes(context: Mapping[str, Any], event: Any) -> bool | None:
    """Whether a new EXEC fills the order; None when it is refused (the deny arm says why)."""
    try:
        return _admit(context, _fields(event))[1]["leaves_qty"] == 0
    except ValueError:
        return None


def has_fills(context: dict[str, Any], event: Any) -> bool:
    """Some quantity is filled, so the order's live state is `partially_filled`."""
    return _total("has_fills", lambda: _money(context.get("filled_qty", "0")) > 0)


def ret_code_ok(context: dict[str, Any], event: Any) -> bool:
    """The exchange accepted the request: the ack says `ok` (the adapter reads the code, C-2.2)."""
    return _total("ret_code_ok", lambda: _fields(event).get("ok") is True)


def ret_code_ok_and_has_fills(context: dict[str, Any], event: Any) -> bool:
    """The first `amend` result arm (B1.5): an accepted amend of an order with fills."""
    return ret_code_ok(context, event) and has_fills(context, event)


def is_duplicate_link_id(context: dict[str, Any], event: Any) -> bool:
    """The exchange already holds this `order_link_id`: accepted, never resent (24 Sec.8.3)."""
    return _total("is_duplicate_link_id", lambda: _fields(event).get("error_code") == _DUPLICATE)


def _found(event: Any) -> Mapping[str, Any] | None:
    """The order a duplicate-id `place` result's lookup found under our id, or None."""
    result = _fields(event)
    found = result.get("lookup")
    if result.get("error_code") != _DUPLICATE or not isinstance(found, Mapping) or not found:
        return None
    return found


def full_match(context: Mapping[str, Any], found: Mapping[str, Any]) -> bool:
    """SR-E29-03: the found order is the row's, field for field; its type is `limit` exactly
    when the row has a price (`ValueError` on malformed money, which the guard denies). Public:
    E29-T04's command port decides a duplicate's hand-over by it, so the port and B1's guards
    can never disagree."""
    order_type = "limit" if context.get("price") is not None else "market"
    return (
        _id(found.get("exchange_order_id")) is not None
        and all(found.get(key) == context.get(key) for key in FACTS[1:])
        and found.get("order_type") == order_type
        and found.get("reduce_only") is context.get("reduce_only")
        and all(_same(found.get(k), context.get(k)) for k in ("qty", "price", "trigger_price"))
        and _same(found.get("stop_loss"), context.get("stop_loss"))
    )


def is_duplicate_link_id_full_match(context: dict[str, Any], event: Any) -> bool:
    """A duplicate-id result whose lookup found our order as the row describes it (SR-E29-03):
    adopted, never resent (24 Sec.8.3 rule 3); a failed, empty or partial lookup is a denial."""

    def check() -> bool:
        found = _found(event)
        return found is not None and full_match(context, found)

    return _total("is_duplicate_link_id_full_match", check)


def is_link_id_mismatch(context: dict[str, Any], event: Any) -> bool:
    """A duplicate-id result whose lookup found an order under our id that is not the row's:
    the order is held for the operator (SR-E29-03), never adopted."""

    def check() -> bool:
        found = _found(event)
        return found is not None and not full_match(context, found)

    return _total("is_link_id_mismatch", check)


def second_consecutive_miss(context: dict[str, Any], event: Any) -> bool:
    """A second `RECON_MISS` with no finding between them: `recon_misses` counts the earlier
    ones, and `adopt_recon` and `record_remote_state` reset it (24 Sec.8.5)."""
    return _total("second_consecutive_miss", lambda: _misses(context) >= 1)


def passes_all_gates(context: dict[str, Any], event: Any) -> bool:
    """Every verdict `VALIDATE` carries is `PASSED` and its order is well formed. It records the
    synchronous checks' verdicts and decides none of them (C-2.21)."""
    return _total("passes_all_gates", lambda: _validated(event) is not None)


def adoption_allowed(context: dict[str, Any], event: Any) -> bool:
    """Denies every adoption until E45-S01 records the Owner's decision D6 (B1.5, SR-E29-12)."""
    return False


def is_recorded_stop(context: dict[str, Any], event: Any) -> bool:
    """The order is a recorded stop's TP/SL order (`MATERIALISED`, 24 Sec.8.3 rule 7): only
    `record_materialised` sets `recorded_stop`, so a KILL on it is consumed and audited, never a
    cancel of the position's protective stop (C-2.6, INV-B1-p). It records which row this is and
    decides nothing else (C-2.21)."""
    return _total("is_recorded_stop", lambda: context.get("recorded_stop") is True)


def _followed(context: Mapping[str, Any], p: Mapping[str, Any]) -> dict[str, Decimal]:
    """The terms a TERMS_CHANGED moves a recorded stop's row to, else ValueError saying why (24
    Sec.8.3 rule 7)."""
    if context.get("recorded_stop") is not True:
        raise ValueError("the row is not a recorded stop's (24 Sec.8.3 rule 7)")
    bound = _id(context.get("exchange_order_id"))
    if bound is None or _id(p.get("exchange_order_id")) != bound:
        raise ValueError("the push is not of the row's bound exchange order (SR-E29-03)")
    terms = _positives(p, FOLLOWED)
    if not terms:
        raise ValueError("the push names no trigger price or quantity")
    if terms.get("qty", _money(context.get("qty"))) < _money(context.get("filled_qty", "0")):
        raise ValueError("the quantity is under the filled quantity (INV-1)")
    if all(_same(_text(v), context.get(k)) for k, v in terms.items()):
        raise ValueError(UNCHANGED)
    return terms


def _takes_terms(context: Mapping[str, Any], event: Any) -> bool:
    try:
        _followed(context, _fields(event))
    except ValueError:
        return False  # an expected denial: no ERROR (only `_total` logs a guard that fails)
    return True


def recorded_terms_changed(context: dict[str, Any], event: Any) -> bool:
    """INV-B1-q: a `TERMS_CHANGED` a recorded stop's row takes. True only for the row
    `record_materialised` marked, a push of its bound exchange order (SR-E29-03) naming a trigger
    price or quantity, each above zero, a quantity not under the filled one (INV-1), and a term
    that differs from the row's. It records the exchange's terms and decides nothing else
    (C-2.21)."""
    return _total("recorded_terms_changed", lambda: _takes_terms(context, event))


def _reading(raw: object) -> dict[str, Any]:
    """A protection reading (B1.5) as context values: the position row's exchange time
    (`updated_time`, ms), its stop and its size; `ValueError` if malformed."""
    if not isinstance(raw, Mapping):
        raise ValueError("a reading is not a mapping")
    when, stop = raw.get("updated_time"), raw.get("stop_loss")
    if type(when) is not int or when < 0:
        raise ValueError("a reading has no exchange time")
    size = _text(_money(raw.get("size")))
    return {
        "updated_time": when,
        "stop_loss": None if stop is None else _text(_money(stop)),
        "size": size,
    }


def _covers(context: Mapping[str, Any], reading: Mapping[str, Any]) -> bool:
    """The reading shows the stop the OMS requested and recorded (SR-E29-06) on an open
    position, which a Full-mode stop covers whole. A discovered order's stop is the one found on
    the exchange, not one the OMS requested, so it never counts (S9, SR-E29-12)."""
    requested, stop = context.get("stop_loss"), reading["stop_loss"]
    if requested is None or stop is None or context.get("discovered") is True:
        return False
    return _money(stop) == _money(requested) and _money(reading["size"]) > 0


def _latest(context: Mapping[str, Any], reading: Mapping[str, Any]) -> Mapping[str, Any]:
    """INV-B1-f: the last reading decides. *reading*, unless the one kept in `sl_reading` is later
    by exchange time, or as late and a loss: on a tie the loss wins. Between two readings of one
    time that are not losses, the one taken last decides."""
    last = context.get("sl_reading")
    if not isinstance(last, Mapping) or type(last.get("updated_time")) is not int:
        return reading
    when = last["updated_time"]
    if when > reading["updated_time"]:
        return last
    if when == reading["updated_time"] and last.get("kind") == "SL_LOST":
        return last
    return reading


def _confirms(context: Mapping[str, Any], reading: Mapping[str, Any]) -> bool:
    """*reading* shows the requested stop on the open position, and the last reading (`_latest`)
    does too: a kept reading only vetoes. A later or tied loss, or a later reading of another stop
    or of a flat position, denies a reading delivered late; a later reading of the stop never
    confirms one that does not show it, so one stamped ahead of the exchange's clock cannot
    decide every reading after it (INV-B1-f)."""
    latest = _latest(context, reading)
    return (
        _covers(context, reading) and latest.get("kind") != "SL_LOST" and _covers(context, latest)
    )


def sl_attach_ok(context: dict[str, Any], event: Any) -> bool:
    """The attach result's read-back is a reading (`_reading`) that shows the requested stop on
    the open position, and no reading recorded during the attach denies it (`_confirms`,
    INV-B1-f): an `SL_LOST` the exchange stamped at or after the read-back does, as on a tie the
    loss wins. The call's own acknowledgement is no evidence: a result without a read-back is a
    denial."""
    return _total(
        "sl_attach_ok", lambda: _confirms(context, _reading(_fields(event).get("position")))
    )


def sl_observed_ok(context: dict[str, Any], event: Any) -> bool:
    """`SL_OBSERVED` counts as `sl_attach_ok`'s read-back does: it shows the requested stop on the
    open position, and no later kept reading denies it (INV-B1-f). Another stop, a flat position,
    a discovered order's stop, or a reading the exchange stamped at or before a recorded loss (or
    before a later recorded reading that does not show the stop) leaves `sl_missing` as it is."""
    return _total("sl_observed_ok", lambda: _confirms(context, _reading(_fields(event))))


# --- The write-ahead step (S7, S8, S11) -------------------------------------------------------


def _step_payload(event: Any) -> dict[str, Any]:
    """What the step's row records of its trigger: the payload or the service's result, and for a
    failed service only the exception's class (CV-C21: `event.error`, never its message)."""
    fault = getattr(event, "error", None)
    if isinstance(fault, BaseException):
        return {"error": type(fault).__name__}
    return dict(_fields(event))


async def persist_event(i: Any, context: dict[str, Any], event: Any, _a: Any) -> None:
    """S8: the step's `order_events` row is committed before the machine moves on. Nothing is
    written in `draft`, nor for a step that leaves it with no row (`rejected`, `killed`): the
    first row is `validated`'s (24 Sec.8.4), `untracked`'s, or a recorded stop's `submitted`, each
    entered from `draft` by its own event (`FIRST_ROWS`). A refused or timed-out write raises,
    so `actionErrorPolicy: "rollback"` restores the configuration and context (S7, S11); a
    timed-out one raises `StepOutcomeUnknown`, as its row may have committed."""
    to_state, from_state = _leaf(i), context.get("persisted_state")
    first = FIRST_ROWS.get(str(to_state)) == _name(event)
    if to_state in (None, "draft") or (from_state is None and not first):
        return
    if _ports.persist is None:
        raise PortMissingError("no write-ahead store is wired, so no step may commit (S7)")
    step = Step(
        order_id=context.get("order_id"),
        account_id=context.get("account_id"),
        order_link_id=context.get("order_link_id"),
        from_state=from_state,
        to_state=str(to_state),
        event=_name(event),
        payload=_step_payload(event),
        context=dict(context),
    )
    try:
        async with asyncio.timeout(CV_PERSIST_TIMEOUT):
            seq = await _ports.persist(step)
    except TimeoutError as exc:
        raise StepOutcomeUnknown(f"the {to_state} step's write did not answer in time") from exc
    context.update(persisted_state=to_state, event_seq=seq)
    link = _id(step.order_link_id) or ""
    if (kind := _INVOKES.get(str(to_state))) is not None and link not in _REPLAYS:
        _remember((link, f"{kind}:{seq}"))  # a replayed step begins no attempt: it is resumed


# --- Services: the command port, once per attempt (S1, SR-E29-15) -----------------------------


@dataclass(slots=True)
class _Attempt:
    """A command attempt this process knows: begun by a step it committed (`persist_event`), or
    resumed by the service; and how it ended (a result, or the class of what it raised)."""

    result: Mapping[str, Any] | None = None
    failure: str | None = None


_ATTEMPTS: OrderedDict[tuple[str, str], _Attempt] = OrderedDict()


def _remember(key: tuple[str, str]) -> _Attempt:
    attempt = _ATTEMPTS.setdefault(key, _Attempt())
    _ATTEMPTS.move_to_end(key)
    while len(_ATTEMPTS) > MAX_ATTEMPTS:
        _ATTEMPTS.popitem(last=False)
    return attempt


#: Orders being replayed from their `order_events` (`begin_replay`), by `order_link_id`: an invoke
#: the record does not answer waits on the order's gate until the replay ends, and a recorded step
#: that leaves its state first cancels it with nothing sent.
_REPLAYS: dict[str, asyncio.Event] = {}


def begin_replay(order_link_id: str, outcomes: Mapping[str, Mapping[str, Any] | str]) -> None:
    """Hydration starts: *outcomes* are the order's recorded service outcomes, keyed as `_command`
    keys an attempt (`<kind>:<event_seq>`), each the result mapping or the class name of what the
    call raised. The machine replayed is a new one, after a restart or a resync that closed the
    one before it, so it holds only what the record holds: the order's attempts this process kept
    are forgotten first, the attach's read-back and a request cut off unanswered included, and
    its stop is attached and read back again (INV-B1-f). A replayed invoke answers its outcome
    with nothing sent; `persist_event` begins no attempt meanwhile, so an invoke the record does
    not answer runs once the replay ends, as a request this process did not begin: a `place`
    looks the id up before it sends (SR-E29-15)."""
    _forget_link(order_link_id)
    _REPLAYS[order_link_id] = asyncio.Event()
    for key, outcome in outcomes.items():
        attempt = _remember((order_link_id, key))
        if isinstance(outcome, str):
            attempt.result, attempt.failure = None, outcome
        else:
            attempt.result, attempt.failure = dict(outcome), None


def end_replay(order_link_id: str) -> None:
    """Hydration ended, or failed: an invoke waiting on the order's gate runs now."""
    gate = _REPLAYS.pop(order_link_id, None)
    if gate is not None:
        gate.set()


def _forget(context: Mapping[str, Any]) -> None:
    _forget_link(_id(context.get("order_link_id")) or "")


def _forget_link(link: str) -> None:
    for key in [key for key in _ATTEMPTS if key[0] == link]:
        del _ATTEMPTS[key]


def _attempt_key(context: Mapping[str, Any], kind: CommandKind) -> tuple[str, str]:
    """The attempt a *kind* command belongs to: the order and the `event_seq` of the step that
    entered the invoking state; an attach is one attempt per machine (`begin_replay` forgets it)."""
    attempt_of = "once" if kind == "attach_stop" else context.get("event_seq")
    return (_id(context.get("order_link_id")) or "", f"{kind}:{attempt_of}")


def fail_attempt(context: Mapping[str, Any], invoke: str, failure: str) -> None:
    """S1: the write-ahead store refused, for its own data, the step a `place`, `cancel` or
    `amend` result would commit (a place ack naming an exchange order id another order of the
    account holds, say). The rollback re-arms the invoke, which would answer the same recorded
    result into the same refusal until the runtime cuts the chain, leaving the order in its
    invoking state with nothing running. The attempt is recorded as failed instead, so the
    re-armed invoke raises `RecordedFailureError` and `onError` takes the order to `unknown` once,
    where reconciliation decides (24 Sec.8.5). *invoke* is the id of `done.invoke.<id>`; another
    invoke's attempt is left as it is. The OMS facade calls this from the failed step's report,
    which comes before the rollback re-arms the invoke."""
    kinds: dict[str, CommandKind] = {"place": "place", "cancel": "cancel", "amend": "amend"}
    kind = kinds.get(invoke)
    if kind is not None:
        attempt = _remember(_attempt_key(context, kind))
        attempt.result, attempt.failure = None, failure


def _view(context: Mapping[str, Any]) -> dict[str, Any]:
    keys = (*FACTS, "exchange_order_id", "qty", "filled_qty", *TERMS, "reduce_only")
    return {key: context.get(key) for key in keys}


async def _dispatch(port: CommandPort, command: Command, *, resumed: bool) -> Mapping[str, Any]:
    if command.kind != "place":
        call = {"cancel": port.cancel, "amend": port.amend, "attach_stop": port.attach_stop}
        return dict(await call[command.kind](command))
    look = replace(command, kind="lookup")
    if resumed:  # the attempt may have left before this process began: look first (SR-E29-15)
        found = dict(await port.lookup(look))
        if found:
            return {"ok": False, "error_code": _DUPLICATE, "lookup": found}
    result = dict(await port.place(command))
    if result.get("ok") is True and _id(result.get("exchange_order_id")) is None:
        raise ExchangeOrderIdMissingError("an accepted place names no exchange order id B1 keeps")
    if result.get("error_code") == _DUPLICATE and "lookup" not in result:
        result["lookup"] = dict(await port.lookup(look))  # success-after-lookup, Sec.8.3 rule 3
    return result


async def _command(
    context: Mapping[str, Any], kind: CommandKind, terms: Mapping[str, Any] | None = None
) -> Mapping[str, Any]:
    """*kind* once per attempt: a re-entered invoke gets the recorded outcome, a recorded failure
    fails again, and only a `place` this process did not begin looks the id up first. An attach
    is one attempt per machine: `begin_replay` forgets it, so a rebuilt machine reads the stop
    back afresh. The attempt's calls are bounded together by `CV_COMMAND_TIMEOUT`: a port that
    hangs fails the attempt with `TimeoutError`, recorded as any failure, so the order reaches
    `unknown` (S1)."""
    port = _ports.commands
    if port is None:
        raise PortMissingError(f"no command port is wired for {kind}")
    key = _attempt_key(context, kind)
    attempt = _ATTEMPTS.get(key)
    if attempt is not None and attempt.failure is not None:
        raise RecordedFailureError(f"{kind} failed before ({attempt.failure}); nothing is resent")
    if attempt is not None and attempt.result is not None:
        return attempt.result
    if (gate := _REPLAYS.get(key[0])) is not None:
        await gate.wait()  # unanswered by the record: after the replay, unless a step cancels it
    command = Command(kind=kind, key=":".join(key), order=_view(context), terms=dict(terms or {}))
    resumed, attempt = attempt is None, attempt or _remember(key)
    try:
        async with asyncio.timeout(CV_COMMAND_TIMEOUT):
            result = await _dispatch(port, command, resumed=resumed)
    except Exception as exc:  # recorded, then raised: `onError` lands in `unknown` (S1)
        attempt.failure = type(exc).__name__
        raise
    attempt.result = result
    return result


async def place_order(_i: Any, context: dict[str, Any], _e: Any) -> Mapping[str, Any]:
    """`submitting`'s invoke: the order's create, once per attempt (S1, SR-E29-15)."""
    return await _command(context, "place")


async def cancel_order(_i: Any, context: dict[str, Any], _e: Any) -> Mapping[str, Any]:
    """`cancel_pending`'s invoke: the cancel, once per attempt."""
    return await _command(context, "cancel")


async def amend_order(_i: Any, context: dict[str, Any], _e: Any) -> Mapping[str, Any]:
    """`amend_pending`'s invoke: the terms `stage_amend` staged; with none, a local refusal and no
    exchange call, so the prior order stays live (S2). The result names the terms it sent."""
    terms = context.get("amend_terms")
    if not isinstance(terms, Mapping) or not terms:
        return {"ok": False, "error_code": OmsErrorCode.INSTRUMENT_FILTER.value}
    return {**await _command(context, "amend", terms), "terms": dict(terms)}


async def attach_native_sl(_i: Any, context: dict[str, Any], _e: Any) -> Mapping[str, Any]:
    """`sl_pending`'s invoke: the stop the OMS requested, attached and read back (24 Sec.8.8 rule
    2). Nothing is sent without a stop the OMS requested (SR-E29-06): none was requested, or the
    order was discovered on the exchange, whose stop is not the OMS's to attach or move (S9,
    SR-E29-12; 24 Sec.8.8 rule 5). The result is then not `sl_attach_ok`, so the region reaches
    `sl_missing`, which alerts and hands the position to B8."""
    stop = context.get("stop_loss")
    if stop is None or context.get("discovered") is True:
        return {"ok": False, "error_code": NATIVE_STOP_REQUIRED}
    return await _command(context, "attach_stop", {"stop_loss": stop})


# --- Context actions --------------------------------------------------------------------------


async def stamp_validated(_i: Any, context: dict[str, Any], event: Any, _a: Any) -> None:
    """Pin the validated order (identity, `qty`, `TERMS`, `reduce_only`); nothing is filled yet."""
    try:
        validated = _validated(event)
    except ValueError:
        validated = None  # unreachable behind `passes_all_gates`
    if validated is None:
        logger().error("b01_stamp_refused")
        return
    context.update(validated)


async def reserve_rate_token(_i: Any, context: dict[str, Any], event: Any, _a: Any) -> None:
    """Records the reservation the synchronous rate governor made before `VALIDATE` (C-2.21)."""
    context["rate_reservation"] = _id(_fields(event).get("rate_reservation"))


async def set_local_reject(_i: Any, context: dict[str, Any], event: Any, _a: Any) -> None:
    """`NATIVE_STOP_REQUIRED` when the native-stop verdict is `FAILED`, the one local reason T03
    exposes; any other refusal records no code (its verdicts stay in the event)."""
    native_refused = _gates(event).get("native_stop") == FAILED
    context["reject_code"] = NATIVE_STOP_REQUIRED if native_refused else None


async def apply_fill(_i: Any, context: dict[str, Any], event: Any, _a: Any) -> None:
    """S4: an admitted EXEC's totals, and its `exec_id` in `seen_exec_ids` (INV-B1-b)."""
    _apply(context, _fields(event))


async def adopt_ack(_i: Any, context: dict[str, Any], event: Any, _a: Any) -> None:
    """A place ack, or a duplicate-id result whose lookup fully matched (SR-E29-03): the exchange
    order id, recorded once; a different one later is logged, never adopted."""
    result = _fields(event)
    found = result.get("lookup")
    raw = result.get("exchange_order_id")
    if raw is None and isinstance(found, Mapping):
        raw = found.get("exchange_order_id")
    _bind(context, raw, "b01_exchange_order_id_mismatch")


async def adopt_cancel_ack(_i: Any, context: dict[str, Any], event: Any, _a: Any) -> None:
    """A cancel ack binds nothing (SR-E29-03, OM-S05): its id is compared with the bound one,
    and a mismatch, or an ack for an order with no bound id, is logged at ERROR."""
    new, known = _id(_fields(event).get("exchange_order_id")), context.get("exchange_order_id")
    if known is None:
        logger().error("b01_cancel_ack_unbound", order_link_id=context.get("order_link_id"))
    elif new is not None and new != known:
        logger().error("b01_exchange_order_id_mismatch", order_link_id=context.get("order_link_id"))


async def stage_amend(_i: Any, context: dict[str, Any], event: Any, _a: Any) -> None:
    """`AMEND`'s requested terms, for the amend service: an invoke reads the context, not the event
    that entered its state. Malformed terms stage nothing, and the service refuses them locally."""
    try:
        terms = {key: _text(v) for key, v in _positives(_fields(event), ("qty", *TERMS)).items()}
    except Exception:  # A1: a malformed amend stages nothing
        terms = {}
    if not terms:
        logger().error("b01_amend_not_staged", order_link_id=context.get("order_link_id"))
    context["amend_terms"] = terms or None


async def adopt_amend(_i: Any, context: dict[str, Any], event: Any, _a: Any) -> None:
    """An accepted amend's `terms`, all or none; any other result keeps the prior order (S2) and
    logs why. Never raises: on this `onDone` arm a rollback would send the amend again."""
    result = _fields(event)
    context["amend_terms"] = None
    try:
        if result.get("ok") is not True:
            raise ValueError("the amend ack is not ok")
        terms = _positives(result.get("terms"), ("qty", *TERMS))
        filled, qty = _money(context.get("filled_qty")), terms.get("qty") or _money(context["qty"])
        if qty < filled:
            raise ValueError("the amend puts qty under filled_qty (INV-1)")
        leaves = Context(prec=40).subtract(qty, filled)  # exact: both fit numeric(38,18)
    except Exception as exc:  # any failure keeps the prior order
        link = context.get("order_link_id")
        logger().error("b01_amend_not_adopted", order_link_id=link, reason=str(exc))
        return
    context.update({key: _text(value) for key, value in terms.items()}, leaves_qty=_text(leaves))


async def keep_prior_order_live(_i: Any, context: dict[str, Any], event: Any, _a: Any) -> None:
    """S2: the amend is refused, so the order stands as it was; the staged terms are dropped."""
    context["amend_terms"] = None
    logger().warning(
        "b01_amend_rejected", order_link_id=context.get("order_link_id"), error_code=_code(event)
    )


async def map_reject_code(_i: Any, context: dict[str, Any], event: Any, _a: Any) -> None:
    """The ack's 24 Sec.8.6 code (the adapter maps it, C-2.2), or the command port's
    `EXPIRED_UNSENT`; else `EXCHANGE_UNKNOWN`. A code Sec.8.6 routes to retry, poll or reconcile
    is the port's to raise (S1): one recorded here is logged at ERROR, as the order may be live
    on the exchange."""
    code = _fields(event).get("error_code")
    known = isinstance(code, str) and code in _REJECT_CODES
    context["reject_code"] = code if known else OmsErrorCode.EXCHANGE_UNKNOWN.value
    if code in _AMBIGUOUS:
        link = context.get("order_link_id")
        logger().error("b01_ambiguous_outcome_recorded_as_reject", order_link_id=link, code=code)


async def record_transport_fault(_i: Any, context: dict[str, Any], event: Any, _a: Any) -> None:
    """S1: the outcome is ambiguous, so the order waits in `unknown` for reconciliation. The venue's
    110001 is no fault: marked `ALREADY_TERMINAL`, with its code, and reconciled at once."""
    fault = getattr(event, "error", None)
    if isinstance(fault, NotFoundError):  # the mark is `unknown`'s entry alert's to take
        context[ALREADY_TERMINAL] = code = fault.exchange_ret_code
        link = context.get("order_link_id")
        logger().warning("b01_already_terminal", order_link_id=link, exchange_ret_code=code)
        _post(context, "request_reconciliation", reason=ALREADY_TERMINAL)
        return
    what = type(fault).__name__ if isinstance(fault, BaseException) else _name(event)
    logger().error("b01_transport_fault", order_link_id=context.get("order_link_id"), fault=what)


async def mark_needs_lookup(_i: Any, context: dict[str, Any], _e: Any, _a: Any) -> None:
    """An unverified duplicate: reconciliation must look the id up before anything binds it."""
    context["needs_lookup"] = True


async def record_cancel_refused(_i: Any, context: dict[str, Any], event: Any, _a: Any) -> None:
    """INV-B1-j: the exchange refused the cancel, so the order is live again."""
    link = context.get("order_link_id")
    logger().warning("b01_cancel_refused", order_link_id=link, error_code=_code(event))


async def adopt_remote_cancel(_i: Any, context: dict[str, Any], event: Any, _a: Any) -> None:
    """The exchange ended the order without our cancel (INV-B1-k). The push is checked against
    the bound id and, as the facade sends it only once every execution is applied, against
    `filled_qty`; a disagreement is logged at ERROR for reconciliation."""
    p, link = _fields(event), context.get("order_link_id")
    known, cum = context.get("exchange_order_id"), p.get("cum_exec_qty")
    if _id(p.get("exchange_order_id")) not in (None, known):
        logger().error("b01_exchange_order_id_mismatch", order_link_id=link)
    try:
        outran = cum is not None and _money(cum) != _money(context.get("filled_qty", "0"))
    except ValueError:
        outran = True
    if outran:
        logger().error("b01_remote_cancel_outran_fills", order_link_id=link)


async def record_mismatch(_i: Any, context: dict[str, Any], event: Any, _a: Any) -> None:
    """SR-E29-03: an order under our id does not match the row. Nothing is taken from it; `held`
    pages on entry and waits for the operator."""
    p = _fields(event)
    found = p.get("lookup")
    other = p.get("exchange_order_id")
    if other is None and isinstance(found, Mapping):
        other = found.get("exchange_order_id")
    link = context.get("order_link_id")
    logger().error("b01_link_id_mismatch", order_link_id=link, exchange_order_id=_id(other))


async def record_discovered(_i: Any, context: dict[str, Any], event: Any, _a: Any) -> None:
    """`DISCOVERED`: reconciliation found an exchange order with no local row (24 Sec.8.5 step
    3c). Its identity, terms and exchange order id are recorded as found, and `discovered` marks
    them as the exchange's, not the OMS's: it is never managed (S9, SR-E29-12), and its stop is
    never one the OMS requested, so the attach service sends nothing for it."""
    order = _fields(event).get("order")
    try:
        if not isinstance(order, Mapping) or _id(order.get("exchange_order_id")) is None:
            raise ValueError("the discovered order has no exchange_order_id")
        found = _order(order)
    except Exception:  # A1: an order we cannot read stays unrecorded; its row write refuses it
        logger().error("b01_discovered_order_refused")
        return
    context.update(found, exchange_order_id=order["exchange_order_id"], discovered=True)


async def record_materialised(_i: Any, context: dict[str, Any], event: Any, _a: Any) -> None:
    """`MATERIALISED`: the TP/SL order of a stop the OMS recorded has appeared (24 Sec.8.3 rule 7,
    Sec.8.8 rule 6). Its identity, terms and exchange order id are recorded as the matched order
    shows them, bound at entry, and `recorded_stop` marks the row, so a KILL never cancels it
    (`is_recorded_stop`). A TP/SL order only closes its position: one that is not reduce-only, or
    that names no exchange order id B1 can keep (`text_id`), is refused, nothing is stamped and
    its first row write refuses it (S7). The arm sends nothing: `submitted` invokes no service."""
    order = _fields(event).get("order")
    try:
        if not isinstance(order, Mapping) or _id(order.get("exchange_order_id")) is None:
            raise ValueError("the recorded stop's order names no exchange_order_id")
        if order.get("reduce_only") is not True:
            raise ValueError("a recorded stop's order only closes its position")
        found = _order(order)
    except Exception:  # A1: an order we cannot read stays unrecorded; its row write refuses it
        logger().error("b01_recorded_stop_refused")
        return
    context.update(found, exchange_order_id=order["exchange_order_id"], recorded_stop=True)


async def adopt_terms(_i: Any, context: dict[str, Any], event: Any, _a: Any) -> None:
    """`TERMS_CHANGED` that `recorded_terms_changed` took (INV-B1-q): the row takes the trigger
    price and quantity its order shows on the exchange, as canonical text, and `leaves_qty`
    follows; `persist_event`, first in the re-entered state's entry, writes them with the step's
    row. Never raises (A1): a push it cannot read changes nothing and is logged."""
    try:
        terms = _followed(context, _fields(event))
        qty = terms.get("qty", _money(context["qty"]))
        leaves = Context(prec=40).subtract(qty, _money(context.get("filled_qty", "0")))
    except Exception as exc:  # A1: unreachable behind the guard
        link = context.get("order_link_id")
        logger().error("b01_terms_not_adopted", order_link_id=link, reason=type(exc).__name__)
        return
    context.update({key: _text(value) for key, value in terms.items()}, leaves_qty=_text(leaves))


async def adopt_untracked(_i: Any, context: dict[str, Any], _e: Any, _a: Any) -> None:
    """`ADOPT` passed `adoption_allowed` (deny-all until E45-S01 records D6), whose verdicts
    include a native stop attached (C-2.6): the order is managed from here as it was discovered,
    its stop the OMS's now; the adoption's own audit record is its route's (SR-E29-12)."""
    context.update(needs_lookup=False, discovered=False)
    logger().warning("b01_untracked_adopted", order_link_id=context.get("order_link_id"))


async def adopt_recon(_i: Any, context: dict[str, Any], event: Any, _a: Any) -> None:
    """Reconciliation found the order (after its SR-E29-03 full match, INV-B1-m): it binds the
    exchange order id, applies an execution it carries as an EXEC would be (S4), restarts
    `recon_misses`, and lets a KILL cancel the order again (INV-B1-h). It adopts no totals
    without their execution (OM-R02)."""
    p = _fields(event)
    context.update(kill_skip_cancel=False, needs_lookup=False, recon_misses=0)
    _bind(context, p.get("exchange_order_id"), "b01_exchange_order_id_mismatch")
    execution = p.get("execution")
    if isinstance(execution, Mapping):
        _apply(context, execution)


async def record_remote_state(_i: Any, context: dict[str, Any], event: Any, _a: Any) -> None:
    """`untracked` heard from the exchange (INV-B1-l): the order exists, so `recon_misses`
    restarts. The fact is logged, with the `exec_id` of an `EXEC` (INV-5); no managing action runs
    (SR-E29-12)."""
    context["recon_misses"] = 0
    link, exec_id = context.get("order_link_id"), _id(_fields(event).get("exec_id"))
    logger().info(
        "b01_untracked_order_seen", order_link_id=link, trigger=_name(event), exec_id=exec_id
    )


async def bump_recon_misses(_i: Any, context: dict[str, Any], _e: Any, _a: Any) -> None:
    """A reconciliation pass found no record of the order (24 Sec.8.5)."""
    context["recon_misses"] = _misses(context) + 1


async def set_reject_unresolvable(_i: Any, context: dict[str, Any], _e: Any, _a: Any) -> None:
    """24 Sec.8.5: two consecutive passes found nothing, so the order ends `rejected`."""
    context["reject_code"] = UNRESOLVED_AFTER_RECONCILE
    logger().warning("b01_unresolved_after_reconcile", order_link_id=context.get("order_link_id"))


async def set_cancel_missing_remote(_i: Any, context: dict[str, Any], _e: Any, _a: Any) -> None:
    """24 Sec.8.5: two passes found no record of an `untracked` order, so it ends `cancelled`."""
    logger().warning("b01_untracked_missing_remote", order_link_id=context.get("order_link_id"))


async def record_sl_fact_ignored(_i: Any, context: dict[str, Any], event: Any, _a: Any) -> None:
    """INV-B1-f: a protection fact the leaf does not act on is consumed, never deferred. A reading
    is kept in `sl_reading` when it is the last one (`_latest`: by exchange time, and on a tie the
    loss wins), so a loss during the attach still decides the attach's result (`sl_attach_ok`).
    `sl_present`'s `SL_LOST` arm records its loss the same way, so no reading the exchange stamped
    at or before it returns the region to `sl_present` (`sl_observed_ok`)."""
    kind = _name(event)
    if kind not in _READINGS:
        return
    try:
        reading = _reading(_fields(event)) | {"kind": kind}
    except Exception:  # A1: a malformed reading is dropped, never kept
        logger().error("b01_sl_reading_refused", order_link_id=context.get("order_link_id"))
        return
    if _latest(context, reading) is reading:
        context["sl_reading"] = reading


async def arm_sl_deadline(_i: Any, context: dict[str, Any], _e: Any, _a: Any) -> None:
    """A2: the stop must be confirmed by this absolute time (24 Sec.8.8 rule 2); the OMS's
    scheduler sends `SL_DEADLINE` then."""
    context["sl_deadline_us"] = _ports.now_us() + SL_DEADLINE_US


async def arm_recon_deadline(_i: Any, context: dict[str, Any], _e: Any, _a: Any) -> None:
    """A2: the time an order still `unknown` pages (24 Sec.8.5)."""
    context["recon_deadline_us"] = _ports.now_us() + RECON_DEADLINE_US


# --- Notices, through the outbox (CV-C25) -----------------------------------------------------


def starts_protection(context: Mapping[str, Any], lifecycle: str | None, trigger: str = "") -> bool:
    """INV-B1-o: whether the order's fills call for its `protection` region (24 Sec.8.8 rule 2):
    always in `partially_filled` and `filled`, which an order enters only on a reported fill, an
    execution found by reconciliation included; for an `EXEC` an S6 arm consumed; and in any
    other state when the order holds a fill (a `cancelled` or `expired` order ended with fills).
    Never for a reduce-only order: it opens no position, and C-2.6 covers position-opening
    orders, so its exits page nothing. The OMS facade asks the same after a hydration."""
    if context.get("reduce_only") is True:
        return False
    return lifecycle in _FILL_STATES or trigger == "EXEC" or _filled(context)


async def notify_protection_region(i: Any, context: dict[str, Any], event: Any, _a: Any) -> None:
    """INV-B1-o: asks the facade for `FIRST_FILL` when `starts_protection` says so; the region
    consumes a repeat, so no flag tracks the first fill. An `EXEC` that an S6 arm consumed calls
    for this order's stop only when it pairs with the order (SR-E29-03): another order's fill, or a
    hostile one, never starts an attach of this order's stop (SR-E29-06), so the position goes to
    B8 instead, which reads it and attaches its fallback stop if none is there (C-2.6)."""
    leaf, trigger = _leaf(i), _name(event)
    if not starts_protection(context, leaf, trigger):
        return
    if trigger != "EXEC" or starts_protection(context, leaf) or _pairs(context, _fields(event)):
        _post(context, "first_fill")
        return
    exec_id = _id(_fields(event).get("exec_id"))
    logger().error("b01_unpaired_exec", order_link_id=context.get("order_link_id"), exec_id=exec_id)
    _post(context, "request_fallback_sl")


async def notify_amend_rejected(_i: Any, context: dict[str, Any], event: Any, _a: Any) -> None:
    """S2: the UI is told the amend was refused and the prior order stands."""
    _post(context, "amend_rejected", error_code=_code(event))


async def emit_terminal(i: Any, context: dict[str, Any], _e: Any, _a: Any) -> None:
    """The order ended: the facade publishes it and evicts the machine (MUST-11)."""
    _post(context, "terminal", state=_leaf(i))
    _forget(context)


async def raise_unknown_alert(_i: Any, context: dict[str, Any], _e: Any, _a: Any) -> None:
    """S1: an order in `unknown` is an incident; it pages once `recon_deadline_us` passes. One the
    venue does not hold (`ALREADY_TERMINAL`) is a ticket, reconciling; the mark ends here."""
    if ALREADY_TERMINAL in context:
        detail = {"exchange_ret_code": context.pop(ALREADY_TERMINAL)}
        link = context.get("order_link_id")
        logger().error("b01_order_unknown", order_link_id=link, reason=ALREADY_TERMINAL, **detail)
        _post(context, "alert", alert="order_already_terminal", **detail)
        return
    logger().error("b01_order_unknown", order_link_id=context.get("order_link_id"))
    _post(context, "alert", alert="order_unknown")


async def raise_critical_alert(i: Any, context: dict[str, Any], _e: Any, _a: Any) -> None:
    """`quarantined` and `held` page (P1): the order's exchange state is not trusted."""
    state = _leaf(i)
    logger().critical(
        "b01_order_untrusted", order_link_id=context.get("order_link_id"), state=state
    )
    _post(context, "alert", alert=f"order_{state}")


async def raise_naked_position_alert(_i: Any, context: dict[str, Any], _e: Any, _a: Any) -> None:
    """C-2.6: the stop is not confirmed, the `SL_ATTACH_FAILED` alert (B1.8)."""
    logger().critical("b01_position_naked", order_link_id=context.get("order_link_id"))
    _post(context, "alert", alert="SL_ATTACH_FAILED")


async def request_reconciliation(_i: Any, context: dict[str, Any], _e: Any, _a: Any) -> None:
    """`quarantined` asks the reconciler for the order's exchange state (24 Sec.8.5)."""
    _post(context, "request_reconciliation")


async def request_fallback_sl(_i: Any, context: dict[str, Any], _e: Any, _a: Any) -> None:
    """Hands the position to B8, which attaches a fallback stop and reads it back (24 Sec.8.8
    rule 3) or pages (INV-B8-d)."""
    _post(context, "request_fallback_sl")


# --- KILL arm (#1650) and the audits (C-2.9) --------------------------------------------------


async def mark_halted_by_kill(_i: Any, context: dict[str, Any], _e: Any, _a: Any) -> None:
    context["halted_by_kill"] = True


async def skip_kill_cancel(_i: Any, context: dict[str, Any], _e: Any, _a: Any) -> None:
    """Nothing of ours to cancel: never sent (`draft`, `validated`), or an unverified duplicate."""
    context["kill_skip_cancel"] = True


async def issue_kill_cancel(_i: Any, context: dict[str, Any], _e: Any, _a: Any) -> None:
    """At most one exchange cancel per KILL, and only if the order was sent (INV-B1-h): through
    the OMS's audited cancel service (SR-E29-06; the same client order id, C-2.10), bounded by
    `CV_KILL_CANCEL_TIMEOUT`. Failure or timeout is audited, never raised: rolling back would
    un-kill the order; so is any other answer but `ok`, after the bound, with its code: the venue's
    110001 at warning, and reconciled (24 Sec.8.6). Reconciliation re-syncs the exchange (C-2.5)."""
    if context.get("kill_skip_cancel"):
        unverified = context.get("needs_lookup") is True
        why = "unverified_duplicate" if unverified else "unsubmitted"
        await _hook(f"kill_no_cancel_{why}", context)
        return
    link = context.get("order_link_id")
    command = Command(kind="kill_cancel", key=f"{link}:kill_cancel", order=_view(context), terms={})
    answer: Mapping[str, Any] = {}
    try:
        if _ports.commands is None:
            raise PortMissingError("no command port is wired for the kill cancel")
        async with asyncio.timeout(CV_KILL_CANCEL_TIMEOUT):
            answer = await _ports.commands.cancel(command)
    except NotFoundError as exc:  # the venue's 110001: audited below, no failure
        answer = {"ok": False, "error_code": exc.code, "exchange_ret_code": exc.exchange_ret_code}
    except TimeoutError:
        context[KILL_CANCEL] = "timeout"
        logger().error("b01_kill_cancel_timeout", order_link_id=link)
        await _hook("kill_cancel_timeout", context)
    except Exception as exc:  # audited; reconciliation re-syncs
        context[KILL_CANCEL] = "failed"
        logger().error("b01_kill_cancel_failed", order_link_id=link, failure=type(exc).__name__)
        await _hook("kill_cancel_failed", context)
    if answer.get("ok") is True:
        context[KILL_CANCEL] = "sent"
    if answer.get("ok") is not False:  # accepted, or nothing answered: nothing more to record
        return
    code, ret = _code(answer), answer.get("exchange_ret_code")
    name = _KILL_REFUSALS.get(str(code), "kill_cancel_refused")
    refusal = str(ret) if type(ret) is int else code  # the venue's own code, else the OMS's
    if terminal := name == "kill_cancel_already_terminal":  # it does not hold it: reconcile
        _post(context, "request_reconciliation", reason=ALREADY_TERMINAL)
    context[KILL_CANCEL] = ALREADY_TERMINAL if terminal else (code or "refused")
    log = logger().warning if terminal else logger().error
    log(f"b01_{name}", order_link_id=link, refusal=refusal)
    await _hook(name, {**context, "denied": {"reason": refusal}})  # a copy: no stale `denied`


async def audit_kill_cancel_in_flight(_i: Any, context: dict[str, Any], _e: Any, _a: Any) -> None:
    """`cancel_pending` KILL: the in-flight cancel is reused; no second cancel."""
    await _hook("kill_cancel_in_flight", context)


async def audit_kill(_i: Any, context: dict[str, Any], _e: Any, _a: Any) -> None:
    await _hook("halted_by_kill", context)


async def audit_kill_ignored_terminal(_i: Any, context: dict[str, Any], _e: Any, _a: Any) -> None:
    await _hook("kill_ignored_terminal", context)


async def audit_kill_protection_retained(
    _i: Any, context: dict[str, Any], _e: Any, _a: Any
) -> None:
    await _hook("kill_protection_retained", context)


async def audit_guard_denied(_i: Any, context: dict[str, Any], event: Any, _a: Any) -> None:
    """B1's one deny arm, an EXEC's: logged and audited once with its `exec_id` and why. A repeat
    (S4) and an EXEC before the bind are expected, at INFO: an `UNBOUND` one waits in the facade's
    reorder buffer (SR-E29-03), never a `FAULT`. Anything else is hostile (OM-T04), at ERROR, for
    the OMS to answer with `FAULT`."""
    p = _fields(event)
    detail = {"exec_id": _id(p.get("exec_id")), "reason": ""}
    try:
        _admit(context, p)
    except ValueError as exc:
        detail["reason"] = str(exc)
    log = logger().info if detail["reason"] in (REPEAT, UNBOUND) else logger().error
    log("b01_exec_refused", order_link_id=context.get("order_link_id"), **detail)
    await _hook("guard_denied", {**context, "denied": detail})


async def audit_reconcile_anomaly(i: Any, context: dict[str, Any], event: Any, _a: Any) -> None:
    """S6 (INV-B1-o): an EXEC for an order that is held or final changes nothing. It is logged
    and audited as a `ReconcileAnomaly` with its `exec_id`, and the order stays as it is."""
    detail = {
        "trigger": _name(event),
        "state": _leaf(i),
        "exec_id": _id(_fields(event).get("exec_id")),
    }
    logger().error("b01_reconcile_anomaly", order_link_id=context.get("order_link_id"), **detail)
    await _hook("reconcile_anomaly", {**context, "anomaly": detail})


async def audit_terms_refused(i: Any, context: dict[str, Any], event: Any, _a: Any) -> None:
    """INV-B1-q, C-07b: a `TERMS_CHANGED` the guarded arm did not take changes nothing and is
    never deferred. A redelivered push naming the row's terms (`UNCHANGED`, S4, S5) is logged at
    INFO and recorded nowhere; any other (a row that is not a recorded stop's, another order's
    push, no term, a term not above zero, a quantity under the filled one) is logged at ERROR and
    recorded as `terms_refused`, which the OMS writes as an anomaly (S6, OM-T04), never through
    `guard_denied`, which it answers with `FAULT`."""
    try:
        _followed(context, _fields(event))
        why = ""  # unreachable: the guarded arm took it
    except ValueError as exc:
        why = str(exc)
    except Exception as exc:  # a push or context it cannot read (A1)
        why = type(exc).__name__
    link = context.get("order_link_id")
    if why == UNCHANGED:
        logger().info("b01_terms_unchanged", order_link_id=link)
        return
    logger().error("b01_terms_refused", order_link_id=link, reason=why, state=_leaf(i))
    await _hook("terms_refused", {**context, "denied": {"reason": why, "trigger": _name(event)}})


async def audit_operator_command_refused(
    i: Any, context: dict[str, Any], event: Any, _a: Any
) -> None:
    """INV-B1-m: `OPERATOR_RESOLVED` outside `held`, or `ADOPT` outside `untracked`, is refused and
    audited, never kept for a later state."""
    refused = {"trigger": _name(event), "state": _leaf(i)}
    logger().warning(
        "b01_operator_command_refused", order_link_id=context.get("order_link_id"), **refused
    )
    await _hook("operator_command_refused", {**context, "refused": refused})


def _audited(name: str) -> Callable[..., Awaitable[None]]:
    async def audit(_i: Any, context: dict[str, Any], _e: Any, _a: Any) -> None:
        await _hook(name, context)

    return audit


ACTIONS: dict[str, Callable[..., Awaitable[None]]] = {
    "adopt_ack": adopt_ack,
    "adopt_amend": adopt_amend,
    "adopt_cancel_ack": adopt_cancel_ack,
    "adopt_recon": adopt_recon,
    "adopt_remote_cancel": adopt_remote_cancel,
    "adopt_terms": adopt_terms,
    "adopt_untracked": adopt_untracked,
    "apply_fill": apply_fill,
    "arm_recon_deadline": arm_recon_deadline,
    "arm_sl_deadline": arm_sl_deadline,
    "audit_guard_denied": audit_guard_denied,
    "audit_kill": audit_kill,
    "audit_kill_cancel_in_flight": audit_kill_cancel_in_flight,
    "audit_kill_ignored_terminal": audit_kill_ignored_terminal,
    "audit_kill_protection_retained": audit_kill_protection_retained,
    "audit_operator_command_refused": audit_operator_command_refused,
    "audit_reconcile_anomaly": audit_reconcile_anomaly,
    "audit_terms_refused": audit_terms_refused,
    "bump_recon_misses": bump_recon_misses,
    "emit_terminal": emit_terminal,
    "issue_kill_cancel": issue_kill_cancel,
    "keep_prior_order_live": keep_prior_order_live,
    "map_reject_code": map_reject_code,
    "mark_halted_by_kill": mark_halted_by_kill,
    "mark_needs_lookup": mark_needs_lookup,
    "notify_amend_rejected": notify_amend_rejected,
    "notify_protection_region": notify_protection_region,
    "persist_event": persist_event,
    "raise_critical_alert": raise_critical_alert,
    "raise_naked_position_alert": raise_naked_position_alert,
    "raise_unknown_alert": raise_unknown_alert,
    "record_cancel_refused": record_cancel_refused,
    "record_discovered": record_discovered,
    "record_materialised": record_materialised,
    "record_mismatch": record_mismatch,
    "record_remote_state": record_remote_state,
    "record_sl_fact_ignored": record_sl_fact_ignored,
    "record_transport_fault": record_transport_fault,
    "request_fallback_sl": request_fallback_sl,
    "request_reconciliation": request_reconciliation,
    "reserve_rate_token": reserve_rate_token,
    "set_cancel_missing_remote": set_cancel_missing_remote,
    "set_local_reject": set_local_reject,
    "set_reject_unresolvable": set_reject_unresolvable,
    "skip_kill_cancel": skip_kill_cancel,
    "stage_amend": stage_amend,
    "stamp_validated": stamp_validated,
}
_AUDITED = "adoption_denied command_refused_unowned kill_ignored_unowned operator_resolved"
_AUDITED += " kill_spared_recorded_stop"
ACTIONS.update({f"audit_{name}": _audited(name) for name in _AUDITED.split()})

GUARDS: dict[str, Callable[..., bool]] = {
    "adoption_allowed": adoption_allowed,
    "exec_new_and_closes": exec_new_and_closes,
    "exec_new_and_partial": exec_new_and_partial,
    "has_fills": has_fills,
    "is_duplicate_link_id": is_duplicate_link_id,
    "is_duplicate_link_id_full_match": is_duplicate_link_id_full_match,
    "is_link_id_mismatch": is_link_id_mismatch,
    "is_recorded_stop": is_recorded_stop,
    "passes_all_gates": passes_all_gates,
    "recorded_terms_changed": recorded_terms_changed,
    "ret_code_ok": ret_code_ok,
    "ret_code_ok_and_has_fills": ret_code_ok_and_has_fills,
    "second_consecutive_miss": second_consecutive_miss,
    "sl_attach_ok": sl_attach_ok,
    "sl_observed_ok": sl_observed_ok,
}

SERVICES: dict[str, Callable[..., Awaitable[Any]]] = {
    "amend_order": amend_order,
    "attach_native_sl": attach_native_sl,
    "cancel_order": cancel_order,
    "place_order": place_order,
}

register_binding_module("order", __name__)


# --- Closed event schemas (E29 threat model, T03 row; 28 B1.8 version 3 (g)) ------------------


def _closed(**properties: dict[str, Any]) -> dict[str, Any]:
    """A closed payload: these keys only, each typed; none required, so an empty payload still
    reaches the guards, which deny what they cannot use (A6)."""
    return {"type": "object", "additionalProperties": False, "properties": properties}


_DECIMAL: Final = r"^-?[0-9]{1,20}(\.[0-9]{1,18})?$"  # the guards re-check with `fullmatch`
_TEXT: Final = {"type": "string", "minLength": 1, "maxLength": MAX_TEXT}
_MONEY_TEXT: Final = {"type": "string", "pattern": _DECIMAL}
_MONEY_OR_NULL: Final = {"type": ["string", "null"], "pattern": _DECIMAL}
#: Exchange times since the epoch, up to the last instant a `datetime` holds (OM-T04): an order
#: push's or a reading's `updated_time` in ms, an execution's `ts_exec` and `ts_ingest` in µs, so
#: the step writer's conversion never overflows; an execution's `seq` is a bigint.
_MS: Final = {"type": "integer", "minimum": 0, "maximum": MAX_EXCHANGE_US // 1_000}
_US: Final = {"type": "integer", "minimum": 0, "maximum": MAX_EXCHANGE_US}
_SEQ: Final = {"type": "integer", "minimum": 0, "maximum": 2**63 - 1}
_FLAG: Final = {"type": "boolean"}
_VERDICT: Final = {"enum": [PASSED, FAILED]}
_SIDE: Final = {"enum": ["buy", "sell"]}
#: Where an exchange fact came from, which its write-ahead row records (24 Sec.8.2 S8, OM-R02).
_SOURCE: Final = {"enum": ["rest", "ws_private", "reconcile", "paper"]}
#: Who meets a recorded stop's TP/SL order first: the private stream or reconciliation (Sec.8.2).
_MATERIALISED_BY: Final = {"enum": ["ws_private", "reconcile"]}
_TERMS: Final = {"qty": _MONEY_TEXT} | dict.fromkeys(TERMS, _MONEY_OR_NULL)
#: The order as 24 Sec.8.1 names it: identity, terms and, for one found on the exchange, its id.
_ORDER: Final = _closed(
    **dict.fromkeys(FACTS[:-1], _TEXT),
    side=_SIDE,
    **_TERMS,
    reduce_only=_FLAG,
    exchange_order_id=_TEXT,
)
#: A 24 Sec.8.1 `Execution`, with the exchange order id it pairs on (SR-E29-03).
_EXECUTION: Final = _closed(
    **dict.fromkeys(("exec_id", "exchange_order_id", *FACTS[:-1], "fee_currency"), _TEXT),
    side=_SIDE,
    **dict.fromkeys(("qty", "price", "fee", "fee_rate"), _MONEY_TEXT),
    closed_pnl=_MONEY_OR_NULL,
    exec_type={"enum": ["trade", "funding", "adl_trade", "bust_trade", "settle"]},
    is_maker=_FLAG,
    **dict.fromkeys(("ts_exec", "ts_ingest"), _US),
    seq=_SEQ,
    source=_SOURCE,
)
#: An order push the exchange sent: the order's status and cumulative fill when it changed.
_PUSH: Final = _closed(
    exchange_order_id=_TEXT,
    order_link_id=_TEXT,
    order_status=_TEXT,
    cum_exec_qty=_MONEY_TEXT,
    updated_time=_MS,
    source=_SOURCE,
)
#: A protection reading (B1.5): the position row's exchange time, stop and size.
_READING: Final = _closed(updated_time=_MS, stop_loss=_MONEY_OR_NULL, size=_MONEY_TEXT)
#: A recorded stop's order shown with another trigger price or quantity, changed in place (24
#: Sec.8.3 rule 7): its terms, the exchange time S5 orders it by, and who met it.
_TERMS_PUSH: Final = _closed(
    exchange_order_id=_TEXT,
    order_link_id=_TEXT,
    **dict.fromkeys(FOLLOWED, _MONEY_TEXT),
    updated_time=_MS,
    source=_MATERIALISED_BY,
    pass_id=_TEXT,
)
#: A reconciliation finding, sent after its SR-E29-03 full match (INV-B1-m).
_FOUND: Final = _closed(exchange_order_id=_TEXT, execution=_EXECUTION, pass_id=_TEXT)
_REASON: Final = _closed(reason=_TEXT)

SCHEMAS: Final[dict[str, dict[str, Any]]] = {
    "ADOPT": _closed(
        gates=_closed(
            **{g: _VERDICT for g in ("validator", "kill_switch", "live_gate", "native_stop")}
        ),
        decided_by=_TEXT,
    ),
    "AMEND": _closed(**_TERMS),
    "AMEND_REJECTED": _closed(error_code=_TEXT, source=_SOURCE),
    "CANCEL": _closed(),
    "DISCOVERED": _closed(order=_ORDER, pass_id=_TEXT),
    "EXEC": _EXECUTION,
    "EXPIRE": _PUSH,
    "FAULT": _closed(reason=_TEXT, exec_id=_TEXT),
    "FIRST_FILL": _closed(),
    "KILL": _REASON,
    "MATERIALISED": _closed(order=_ORDER, pass_id=_TEXT, source=_MATERIALISED_BY),
    "MISMATCH": _closed(exchange_order_id=_TEXT, pass_id=_TEXT),
    "OPERATOR_RESOLVED": _closed(decided_by=_TEXT, reason=_TEXT),
    "RECON_FOUND_CANCELLED": _FOUND,
    "RECON_FOUND_FILLED": _FOUND,
    "RECON_FOUND_LIVE": _FOUND,
    "RECON_FOUND_PARTIAL": _FOUND,
    "RECON_MISS": _closed(pass_id=_TEXT),
    "REMOTE_CANCELLED": _PUSH,
    "SEND": _closed(),
    "SL_DEADLINE": _closed(),
    "SL_LOST": _READING,
    "SL_OBSERVED": _READING,
    "TERMS_CHANGED": _TERMS_PUSH,
    "TRANSPORT_FAULT": _REASON,
    "TRIGGERED": _PUSH,
    "VALIDATE": _closed(
        gates=_closed(**{g: _VERDICT for g in GATES}),
        order=_ORDER,
        rate_reservation=_TEXT,
    ),
}
register_event_schemas("order", SCHEMAS)
