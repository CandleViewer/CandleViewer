"""candleviewer.statechart.bindings.b01_order — MachineLogic for B1 `order`
(#1650, E50). Chart: `machines/B01.order.machine.json`.

E29-T03 implements the guards (pure, total, deny by default; catalogue A6) and the context
actions; the effectful actions and the services stay idempotent no-ops for its next slice.
Statecharts record, synchronous code enforces (C-2.21): risk, the rate budget, the kill switch,
the live gate and the native-stop decision (E32-T01) run before `VALIDATE`, which carries their
verdicts (`gates`) and the validated order (`order`). `EXEC` carries a 24-internal-schemas.md
Sec.8.1 `Execution`; `place`, `cancel` and `amend` finish with a Sec.14.4 `OrderAck` (the amend's
adds the `terms` it sent), all as JSON. A service answers only a definite outcome and raises on an
ambiguous one, so `onError` takes the order to `unknown` (S1). Money is canonical decimal text in
context, like the chart's `"qty": "0"`, so a snapshot stays plain JSON.

KILL semantics (owner decision #1778 item X, option a): root `lifecycle.on.KILL`
lands in the final `lifecycle.killed`, whose entry marks the order
`halted_by_kill`, audits (write-ahead, C-2.9), then issues the exchange cancel
through the same `cancel_order` service the `cancel_pending` invoke uses —
skipped for never-submitted `draft`/`validated`; `cancel_pending` keeps its
in-flight cancel instead of sending a second one. The cancel outcome is NOT
trusted here — reconciliation re-syncs the true exchange state (C-2.10, C-2.5).
The `protection` region is untouched by KILL (C-2.6): it only audits.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from decimal import Decimal, InvalidOperation
from typing import Any, Final

import structlog

from candleviewer.exchange.base.errors import OmsErrorCode
from candleviewer.oms.errors import ExecutionRefused
from candleviewer.oms.execution import Fill, OrderFills, apply_execution
from candleviewer.statechart.bindings import register_binding_module
from candleviewer.statechart.config import CV_KILL_CANCEL_TIMEOUT, register_event_schemas


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


async def _noop_action(*_args: object, **_kwargs: object) -> None:
    return None


async def _idempotent_service(*_args: object, **_kwargs: object) -> None:
    return None


#: `VALIDATE`'s verdicts (each must be `True`), the order's identity, and its optional terms
#: an amend may change besides `qty` (24 Sec.14.4 `AmendOrderRequest`).
GATES: Final = ("risk", "rate", "kill_switch", "live_gate", "native_stop")
FACTS: Final = ("order_id", "order_link_id", "account_id", "symbol", "side")
TERMS: Final = ("price", "trigger_price", "take_profit", "stop_loss")
#: The reject codes T03 sets (#847): the native-stop refusal (E32-T01 decides it) and 24
#: Sec.8.5's second consecutive reconciliation miss.
NATIVE_STOP_REQUIRED: Final = "NATIVE_STOP_REQUIRED"
UNRESOLVED_AFTER_RECONCILE: Final = "UNRESOLVED_AFTER_RECONCILE"
RECON_MISSES_TO_REJECT: Final = 2
#: Bounds on what a payload may put into context (C-2.18): fills per order, id and number text.
MAX_FILLS: Final = 10_000
MAX_TEXT: Final = 64
_REJECT_CODES: Final = frozenset(code.value for code in OmsErrorCode)


def _fields(event: Any) -> Mapping[str, Any]:
    """An `Event`'s payload or an `onDone` result, when it is a mapping; else empty."""
    value = event.payload if hasattr(event, "payload") else getattr(event, "data", event)
    return value if isinstance(value, Mapping) else {}


def _id(raw: object) -> str | None:
    return raw if isinstance(raw, str) and 0 < len(raw) <= MAX_TEXT else None


def _number(raw: object) -> Decimal | None:
    """A finite decimal from bounded text; never from a float."""
    if not isinstance(raw, str) or len(raw) > MAX_TEXT:
        return None
    try:
        value = Decimal(raw)
    except InvalidOperation:
        return None
    return value if value.is_finite() else None


def _text(value: Decimal) -> str:
    """Canonical decimal text: fixed point, no exponent, no trailing zeros."""
    out = format(value, "f")
    if "." in out:
        out = out.rstrip("0").rstrip(".")
    return "0" if out == "-0" else out


def _positives(raw: Mapping[str, Any], keys: tuple[str, ...]) -> dict[str, Decimal] | None:
    """*raw*'s values for *keys*, each above zero (absent or null: skipped), else None."""
    out: dict[str, Decimal] = {}
    for key in keys:
        if raw.get(key) is not None:
            value = _number(raw[key])
            if value is None or value <= 0:
                return None
            out[key] = value
    return out


def _totals(context: Mapping[str, Any]) -> OrderFills:
    """The context's fill values; refuses a context these actions did not write."""
    qty, filled, value, fee = (
        _number(context.get(key, "0"))
        for key in ("qty", "filled_qty", "cum_exec_value", "fee_paid")
    )
    if qty is None or filled is None or value is None or fee is None:
        raise ExecutionRefused("the order context holds a fill value that is not a decimal")
    return OrderFills(qty, filled, value, fee)


def _misses(context: Mapping[str, Any]) -> int:
    misses = context.get("recon_misses", 0)
    if type(misses) is not int or misses < 0:
        raise ValueError("recon_misses is not a count")
    return misses


def _gates(event: Any) -> Mapping[str, Any]:
    gates = _fields(event).get("gates")
    return gates if isinstance(gates, Mapping) else {}


def _validated(event: Any) -> dict[str, str | None] | None:
    """The validated order as context values when every gate passed and it is well formed."""
    order = _fields(event).get("order")
    if not isinstance(order, Mapping) or any(_gates(event).get(g) is not True for g in GATES):
        return None
    facts = {key: _id(order.get(key)) for key in FACTS}
    terms = _positives(order, ("qty", *TERMS))
    if terms is None or "qty" not in terms or None in facts.values():
        return None
    stamped: dict[str, str | None] = {**facts, **dict.fromkeys(TERMS)}
    stamped.update({key: _text(value) for key, value in terms.items()})
    stamped["leaves_qty"] = stamped["qty"]
    return stamped


def _accepted_fill(context: Mapping[str, Any], event: Any) -> tuple[str, OrderFills] | None:
    """`(exec_id, totals after it)` for a new EXEC of this order; None for a repeat (S4), or one
    that is malformed, another order's, past `MAX_FILLS` or refused by `apply_execution`."""
    p, seen = _fields(event), context.get("seen_exec_ids")
    link, exec_id = _id(context.get("order_link_id")), _id(p.get("exec_id"))
    if isinstance(seen, list) and exec_id in seen:
        return None  # the deny arm audits a repeat, which changes nothing (INV-B1-b)
    qty, price, fee = (_number(p.get(key)) for key in ("qty", "price", "fee"))
    try:
        if link is None or exec_id is None or p.get("order_link_id") != link:
            raise ExecutionRefused("the execution is malformed or another order's")
        if not isinstance(seen, list) or len(seen) >= MAX_FILLS:
            raise ExecutionRefused("seen_exec_ids is missing or at MAX_FILLS")
        if qty is None or price is None or fee is None:
            raise ExecutionRefused("the execution's qty, price or fee is not a decimal")
        return exec_id, apply_execution(_totals(context), Fill(exec_id, qty, price, fee))
    except ExecutionRefused as exc:
        logger().error("b01_exec_refused", reason=str(exc), order_link_id=link)
        return None


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
    found = _accepted_fill(context, event)
    return None if found is None else found[1].closes


def has_fills(context: dict[str, Any], event: Any) -> bool:
    """Some quantity is filled, so the order's live state is `partially_filled`."""
    return _total("has_fills", lambda: _totals(context).filled_qty > 0)


def ret_code_ok(context: dict[str, Any], event: Any) -> bool:
    """The exchange accepted the request: the ack says `ok` (the adapter reads retCode, C-2.2)."""
    return _total("ret_code_ok", lambda: _fields(event).get("ok") is True)


def is_duplicate_link_id(context: dict[str, Any], event: Any) -> bool:
    """The exchange already holds this `order_link_id`: accepted, never resent (24 Sec.8.3)."""
    duplicate = OmsErrorCode.DUPLICATE_CLIENT_ID.value
    return _total("is_duplicate_link_id", lambda: _fields(event).get("error_code") == duplicate)


def passes_all_gates(context: dict[str, Any], event: Any) -> bool:
    """Every verdict `VALIDATE` carries is `True` and its order is well formed. It records the
    synchronous checks' verdicts and decides none of them (C-2.21)."""
    return _total("passes_all_gates", lambda: _validated(event) is not None)


def second_consecutive_miss(context: dict[str, Any], event: Any) -> bool:
    """This `RECON_MISS` is the second in a row (24 Sec.8.5)."""
    return _total("second_consecutive_miss", lambda: _misses(context) + 1 >= RECON_MISSES_TO_REJECT)


async def stamp_validated(_i: Any, context: dict[str, Any], event: Any, _a: Any) -> None:
    """Pin the validated order (identity, `qty`, `TERMS`) into context; nothing is filled yet."""
    validated = _validated(event)
    if validated is None:  # unreachable behind `passes_all_gates`
        logger().error("b01_stamp_refused")
        return
    context.update(validated)


async def set_local_reject(_i: Any, context: dict[str, Any], event: Any, _a: Any) -> None:
    """`NATIVE_STOP_REQUIRED` when the native-stop verdict refused, the one local reason T03
    exposes; any other refusal records no code (its verdicts stay in the event)."""
    native_refused = _gates(event).get("native_stop") is False
    context["reject_code"] = NATIVE_STOP_REQUIRED if native_refused else None


async def apply_fill(_i: Any, context: dict[str, Any], event: Any, _a: Any) -> None:
    """S4: the EXEC's new totals (`apply_execution`) and its `exec_id` in `seen_exec_ids`. Only
    an EXEC a guard admitted reaches it; a repeat changes nothing (INV-B1-b)."""
    found = _accepted_fill(context, event)
    if found is None:
        return
    exec_id, totals = found
    context.update(
        filled_qty=_text(totals.filled_qty),
        leaves_qty=_text(totals.leaves_qty),
        cum_exec_value=_text(totals.cum_exec_value),
        fee_paid=_text(totals.fee_paid),
        avg_price=None if totals.avg_price is None else _text(totals.avg_price),
        seen_exec_ids=[*context["seen_exec_ids"], exec_id],
    )


def _adopt_exchange_id(context: dict[str, Any], fields: Mapping[str, Any]) -> None:
    """The exchange's order id, recorded once; a different one later is logged, never adopted."""
    new, known = _id(fields.get("exchange_order_id")), context.get("exchange_order_id")
    if new is not None and known is None:
        context["exchange_order_id"] = new
    elif new is not None and new != known:
        logger().error("b01_exchange_order_id_mismatch", order_link_id=context.get("order_link_id"))


async def adopt_ack(_i: Any, context: dict[str, Any], event: Any, _a: Any) -> None:
    """A place or cancel ack (`adopt_ack`, `adopt_cancel_ack`): adopt the exchange's order id."""
    _adopt_exchange_id(context, _fields(event))


async def adopt_recon(_i: Any, context: dict[str, Any], event: Any, _a: Any) -> None:
    """Reconciliation found the order: adopt its id, and the run of misses ends."""
    _adopt_exchange_id(context, _fields(event))
    context["recon_misses"] = 0


async def adopt_amend(_i: Any, context: dict[str, Any], event: Any, _a: Any) -> None:
    """An accepted amend: adopt the `terms` it sent. A result that is not `ok`, or terms that are
    malformed or would put `qty` under `filled_qty` (INV-1), keep the prior order as it is (S2).
    Never raises: on this `onDone` arm a rollback would send the amend again."""
    result = _fields(event)
    sent = result.get("terms")
    terms = _positives(sent, ("qty", *TERMS)) if isinstance(sent, Mapping) else None
    if result.get("ok") is not True or terms is None:
        return
    filled = _number(context.get("filled_qty"))
    qty = terms.get("qty", _number(context.get("qty")))
    if filled is None or qty is None or qty < filled:
        logger().error("b01_amend_terms_refused", order_link_id=context.get("order_link_id"))
        return
    context.update({key: _text(value) for key, value in terms.items()})
    context["leaves_qty"] = _text(OrderFills(qty, filled).leaves_qty)


async def keep_prior_order_live(_i: Any, context: dict[str, Any], _e: Any, _a: Any) -> None:
    """S2: a rejected amend leaves the prior order live and unchanged; only `adopt_amend` changes
    the terms, so `qty`, the price and the stop stay. `notify_amend_rejected` tells the UI."""
    logger().info("b01_amend_rejected_prior_kept", order_link_id=context.get("order_link_id"))


async def map_reject_code(_i: Any, context: dict[str, Any], event: Any, _a: Any) -> None:
    """The ack's internal code (24 Sec.8.6; the adapter maps the retCode, C-2.2). A code outside
    the taxonomy, or none, takes the table's default for any other code, `EXCHANGE_UNKNOWN`."""
    code = _fields(event).get("error_code")
    known = isinstance(code, str) and code in _REJECT_CODES
    context["reject_code"] = code if known else OmsErrorCode.EXCHANGE_UNKNOWN.value


async def record_transport_fault(_i: Any, context: dict[str, Any], event: Any, _a: Any) -> None:
    """S1: `unknown`, never resent. Keeps the failure's class name, never its text (it may echo
    a signed request)."""
    failure = getattr(event, "error", None)
    name = type(failure).__name__ if isinstance(failure, BaseException) else ""
    context["transport_fault"] = name[:MAX_TEXT] if name.isidentifier() else "unknown"


async def bump_recon_misses(_i: Any, context: dict[str, Any], _e: Any, _a: Any) -> None:
    context["recon_misses"] = _misses(context) + 1


async def set_reject_unresolvable(_i: Any, context: dict[str, Any], _e: Any, _a: Any) -> None:
    """24 Sec.8.5: the second consecutive miss rejects the order as unresolvable."""
    context["recon_misses"] = _misses(context) + 1
    context["reject_code"] = UNRESOLVED_AFTER_RECONCILE


# --- KILL arm (#1650) ----------------------------------------------------------------


async def mark_halted_by_kill(_i: Any, context: dict[str, Any], _e: Any, _a: Any) -> None:
    context["halted_by_kill"] = True


async def skip_kill_cancel(_i: Any, context: dict[str, Any], _e: Any, _a: Any) -> None:
    """Nothing of ours to cancel: never sent (`draft`, `validated`), or an unverified duplicate."""
    context["kill_skip_cancel"] = True


async def issue_kill_cancel(i: Any, context: dict[str, Any], event: Any, _a: Any) -> None:
    """At most one exchange cancel per order, only if submitted (INV-B1-h): via the
    chart's own `cancel_order` service (the same client order id, C-2.10), bounded by
    `CV_KILL_CANCEL_TIMEOUT`. Failure or timeout is audited, never raised: rolling
    back would un-kill the order. Reconciliation re-syncs the exchange (C-2.5).

    E29: route through the audited OMS cancel service instead of calling the
    binding's service from an action (review #2133)."""
    if context.get("kill_skip_cancel"):
        await _hook("kill_no_cancel_unsubmitted", context)
        return
    try:
        async with asyncio.timeout(CV_KILL_CANCEL_TIMEOUT):
            await SERVICES["cancel_order"](i, context, event)
    except TimeoutError:
        logger().error("b01_kill_cancel_timeout")
        await _hook("kill_cancel_timeout", context)
    except Exception as exc:  # audited; reconciliation re-syncs
        logger().error("b01_kill_cancel_failed", error=type(exc).__name__)
        await _hook("kill_cancel_failed", context)


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


async def audit_guard_denied(_i: Any, context: dict[str, Any], _e: Any, _a: Any) -> None:
    await _hook("guard_denied", context)


_STUB_ACTIONS = (
    "arm_recon_deadline",
    "arm_sl_deadline",
    "emit_terminal",
    "mark_needs_lookup",
    "notify_amend_rejected",
    "notify_protection_region",
    "persist_event",
    "raise_critical_alert",
    "raise_naked_position_alert",
    "raise_unknown_alert",
    "request_fallback_sl",
    "request_reconciliation",
    "reserve_rate_token",
)

ACTIONS: dict[str, Callable[..., Awaitable[None]]] = {
    **{name: _noop_action for name in _STUB_ACTIONS},
    "adopt_ack": adopt_ack,
    "adopt_amend": adopt_amend,
    "adopt_cancel_ack": adopt_ack,
    "adopt_recon": adopt_recon,
    "apply_fill": apply_fill,
    "bump_recon_misses": bump_recon_misses,
    "keep_prior_order_live": keep_prior_order_live,
    "map_reject_code": map_reject_code,
    "record_transport_fault": record_transport_fault,
    "set_local_reject": set_local_reject,
    "set_reject_unresolvable": set_reject_unresolvable,
    "stamp_validated": stamp_validated,
    "audit_guard_denied": audit_guard_denied,
    "audit_kill": audit_kill,
    "audit_kill_cancel_in_flight": audit_kill_cancel_in_flight,
    "audit_kill_ignored_terminal": audit_kill_ignored_terminal,
    "audit_kill_protection_retained": audit_kill_protection_retained,
    "issue_kill_cancel": issue_kill_cancel,
    "mark_halted_by_kill": mark_halted_by_kill,
    "skip_kill_cancel": skip_kill_cancel,
}

GUARDS: dict[str, Callable[..., bool]] = {
    "exec_new_and_closes": exec_new_and_closes,
    "exec_new_and_partial": exec_new_and_partial,
    "has_fills": has_fills,
    "is_duplicate_link_id": is_duplicate_link_id,
    "passes_all_gates": passes_all_gates,
    "ret_code_ok": ret_code_ok,
    "second_consecutive_miss": second_consecutive_miss,
}

SERVICES: dict[str, Callable[..., Awaitable[Any]]] = {
    "amend_order": _idempotent_service,
    "attach_native_sl": _idempotent_service,
    "cancel_order": _idempotent_service,
    "place_order": _idempotent_service,
}

register_binding_module("order", __name__)

#: Permissive payload schemas (B2-B9 shape); E29 tightens them.
_ANY_PAYLOAD: dict[str, Any] = {"type": "object", "additionalProperties": True}
register_event_schemas(
    {
        name: _ANY_PAYLOAD
        for name in (
            "AMEND",
            "AMEND_REJECTED",
            "CANCEL",
            "EXEC",
            "EXPIRE",
            "FAULT",
            "FIRST_FILL",
            "KILL",
            "RECON_FOUND_CANCELLED",
            "RECON_FOUND_FILLED",
            "RECON_FOUND_LIVE",
            "RECON_FOUND_PARTIAL",
            "RECON_MISS",
            "SEND",
            "SL_DEADLINE",
            "SL_LOST",
            "SL_OBSERVED",
            "TRANSPORT_FAULT",
            "TRIGGERED",
            "VALIDATE",
        )
    }
)


# --- #847 slice 1: `untracked` and `held` (G-3) and exchange outcomes, chart version 1 ----
# Stubs until #847 slices 4-5: the guards deny (A6), so a duplicate result parks in `unknown`.
ACTIONS.update(
    dict.fromkeys(
        "adopt_remote_cancel adopt_untracked record_cancel_refused record_discovered"
        " record_mismatch set_cancel_missing_remote".split(),
        _noop_action,
    )
)


def _audited(name: str) -> Callable[..., Awaitable[None]]:
    async def audit(_i: Any, context: dict[str, Any], _e: Any, _a: Any) -> None:
        await _hook(name, context)

    return audit


_AUDITED = "adoption_denied command_refused_unowned kill_ignored_unowned operator_resolved"
ACTIONS.update({f"audit_{name}": _audited(name) for name in _AUDITED.split()})

GUARDS.update(
    dict.fromkeys(
        "adoption_allowed is_duplicate_link_id_full_match is_link_id_mismatch"
        " ret_code_ok_and_has_fills".split(),
        _deny_guard,
    )
)
register_event_schemas(
    dict.fromkeys(
        ("ADOPT", "DISCOVERED", "MISMATCH", "OPERATOR_RESOLVED", "REMOTE_CANCELLED"), _ANY_PAYLOAD
    )
)

# --- #847 slice 1b, chart version 2 (C-2.6, INV-B1-f): the attach result counts only if its
# read-back confirms the stop (fail-closed until slice 5), and no protection reading is deferred.
GUARDS["sl_attach_ok"] = _deny_guard
ACTIONS["record_sl_fact_ignored"] = _noop_action
