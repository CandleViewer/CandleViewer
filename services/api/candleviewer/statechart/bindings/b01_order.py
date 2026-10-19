"""candleviewer.statechart.bindings.b01_order — MachineLogic for B1 `order`
(#1650, E50). Chart: `machines/B01.order.machine.json`.

E29-T03 implements the fill, validation and ack guards (pure, total, deny by default; catalogue
A6) and context actions; the rest stay idempotent no-ops for its later slices.
Statecharts record, synchronous code enforces (C-2.21): `VALIDATE` carries the verdicts of the
checks run before it (`gates`) and the order. `EXEC` carries a 24-internal-schemas.md Sec.8.1
`Execution` and its `exchange_order_id`; services answer a Sec.14.4 `OrderAck` (an amend's adds
its `terms`) and raise on an ambiguous outcome, so `onError` lands in `unknown` (S1). Money is
canonical decimal text in context, like the chart's `"qty": "0"`: a snapshot stays plain JSON.

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
import re
from collections.abc import Awaitable, Callable, Mapping
from decimal import Context, Decimal
from typing import Any, Final

import structlog

from candleviewer.exchange.base.errors import OmsErrorCode
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


#: `oms.execution.apply_fields`, which the OMS facade sets like the audit hook, as the statechart
#: package imports no `oms` module (C-3.1). It refuses fills with `ValueError`, as does its absence.
FillCore = Callable[[Mapping[str, Decimal], Mapping[str, Decimal]], Mapping[str, Decimal | None]]
_core: FillCore | None = None


def set_fill_core(core: FillCore | None) -> None:
    global _core
    _core = core


async def _noop_action(*_args: object, **_kwargs: object) -> None:
    return None


def _deny_guard(*_args: object, **_kwargs: object) -> bool:
    return False


async def _idempotent_service(*_args: object, **_kwargs: object) -> None:
    return None


#: `VALIDATE`'s verdicts (each `PASSED`: a bool could read as "engaged"), the order's identity, the
#: terms an amend may change besides `qty` (22-api-openapi.yaml `AmendOrderRequest`), and what an
#: EXEC shares with its order: it pairs on the bound exchange order id (SR-E29-03).
GATES: Final = ("risk", "rate", "kill_switch", "live_gate", "native_stop")
PASSED: Final = "pass"
FAILED: Final = "fail"
FACTS: Final = ("order_id", "order_link_id", "account_id", "symbol", "side")
TERMS: Final = ("price", "trigger_price", "take_profit", "stop_loss")
PAIRING: Final = ("exchange_order_id", *FACTS)
#: The local reject code T03 sets: the native-stop refusal, which E32-T01 decides.
NATIVE_STOP_REQUIRED: Final = "NATIVE_STOP_REQUIRED"
#: Bounds on what a payload may put into context (C-2.18): fills per order, id text, and money as
#: 22's `Decimal` text (C6: no exponent, space or `_`) with numeric(38,18)'s 20 + 18 digits.
MAX_FILLS: Final = 10_000
MAX_TEXT: Final = 64
_MONEY: Final = re.compile(r"-?[0-9]{1,20}(\.[0-9]{1,18})?")
REPEAT: Final = "a repeat exec_id (S4)"
_REJECT_CODES: Final = frozenset(code.value for code in OmsErrorCode)


def _fields(event: Any) -> Mapping[str, Any]:
    """An `Event`'s payload or an `onDone` result, when it is a mapping; else empty."""
    value = event.payload if hasattr(event, "payload") else getattr(event, "data", event)
    return value if isinstance(value, Mapping) else {}


def _id(raw: object) -> str | None:
    return raw if isinstance(raw, str) and 0 < len(raw) <= MAX_TEXT else None


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


def _positives(raw: object, keys: tuple[str, ...]) -> dict[str, Decimal]:
    """*raw*'s money for *keys*, each above zero (absent or null: skipped), else `ValueError`."""
    if not isinstance(raw, Mapping):
        raise ValueError("the terms are not a mapping")
    out = {key: _money(raw[key]) for key in keys if raw.get(key) is not None}
    if any(value <= 0 for value in out.values()):
        raise ValueError("a term is zero or less")
    return out


def _gates(event: Any) -> Mapping[str, Any]:
    gates = _fields(event).get("gates")
    return gates if isinstance(gates, Mapping) else {}


def _validated(event: Any) -> dict[str, str | None] | None:
    """The order as context values when every verdict is `PASSED`; `ValueError` if malformed."""
    order = _fields(event).get("order")
    if not isinstance(order, Mapping) or any(_gates(event).get(g) != PASSED for g in GATES):
        return None
    facts = {key: _id(order.get(key)) for key in FACTS}
    terms = _positives(order, ("qty", *TERMS))
    if "qty" not in terms or None in facts.values():
        raise ValueError("the order has no qty, or a malformed identity")
    stamped = {**facts, **dict.fromkeys(TERMS), **{key: _text(v) for key, v in terms.items()}}
    return stamped | {"leaves_qty": stamped["qty"]}


def _admit(context: Mapping[str, Any], event: Any) -> tuple[str, Mapping[str, Decimal | None]]:
    """`(exec_id, the order's totals after it)` for a new trade EXEC of this order, else a
    `ValueError` saying why: `REPEAT` (S4), another order's (SR-E29-03) or hostile (OM-T04)."""
    p, seen = _fields(event), context.get("seen_exec_ids")
    exec_id = _id(p.get("exec_id"))
    if exec_id is None or not isinstance(seen, list):
        raise ValueError("the execution has no exec_id, or the order no seen_exec_ids")
    if exec_id in seen:
        raise ValueError(REPEAT)
    if p.get("exec_type") != "trade" or any(
        _id(p.get(key)) is None or p.get(key) != context.get(key) for key in PAIRING
    ):
        raise ValueError("the execution is not a trade of this order's bound exchange order")
    if len(seen) >= MAX_FILLS:
        raise ValueError("the order holds MAX_FILLS fills")
    if _core is None:
        raise ValueError("the OMS has not set its fill arithmetic")
    fill = {key: _money(p.get(key)) for key in ("qty", "price", "fee", "fee_rate")}
    totals = ("qty", "filled_qty", "cum_exec_value", "fee_paid")
    return exec_id, _core({key: _money(context.get(key, "0")) for key in totals}, fill)


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
        return _admit(context, event)[1]["leaves_qty"] == 0
    except ValueError:
        return None


def has_fills(context: dict[str, Any], event: Any) -> bool:
    """Some quantity is filled, so the order's live state is `partially_filled`."""
    return _total("has_fills", lambda: _money(context.get("filled_qty", "0")) > 0)


def ret_code_ok(context: dict[str, Any], event: Any) -> bool:
    """The exchange accepted the request: the ack says `ok` (the adapter reads the code, C-2.2)."""
    return _total("ret_code_ok", lambda: _fields(event).get("ok") is True)


def is_duplicate_link_id(context: dict[str, Any], event: Any) -> bool:
    """The exchange already holds this `order_link_id`: accepted, never resent (24 Sec.8.3)."""
    duplicate = OmsErrorCode.DUPLICATE_CLIENT_ID.value
    return _total("is_duplicate_link_id", lambda: _fields(event).get("error_code") == duplicate)


def passes_all_gates(context: dict[str, Any], event: Any) -> bool:
    """Every verdict `VALIDATE` carries is `PASSED` and its order is well formed. It records the
    synchronous checks' verdicts and decides none of them (C-2.21)."""
    return _total("passes_all_gates", lambda: _validated(event) is not None)


async def stamp_validated(_i: Any, context: dict[str, Any], event: Any, _a: Any) -> None:
    """Pin the validated order (identity, `qty`, `TERMS`) into context; nothing is filled yet."""
    if (validated := _validated(event)) is None:  # unreachable behind `passes_all_gates`
        logger().error("b01_stamp_refused")
        return
    context.update(validated)


async def set_local_reject(_i: Any, context: dict[str, Any], event: Any, _a: Any) -> None:
    """`NATIVE_STOP_REQUIRED` when the native-stop verdict is `FAILED`, the one local reason T03
    exposes; any other refusal records no code (its verdicts stay in the event)."""
    native_refused = _gates(event).get("native_stop") == FAILED
    context["reject_code"] = NATIVE_STOP_REQUIRED if native_refused else None


async def apply_fill(_i: Any, context: dict[str, Any], event: Any, _a: Any) -> None:
    """S4: an admitted EXEC's totals, and its `exec_id` in `seen_exec_ids` (INV-B1-b)."""
    try:
        exec_id, totals = _admit(context, event)
    except ValueError:
        return
    context.update(
        {key: None if value is None else _text(value) for key, value in totals.items()},
        seen_exec_ids=[*context["seen_exec_ids"], exec_id],
    )


async def adopt_ack(_i: Any, context: dict[str, Any], event: Any, _a: Any) -> None:
    """A place or cancel ack (`adopt_ack`, `adopt_cancel_ack`): the exchange's order id, recorded
    once; a different one later is logged, never adopted."""
    new, known = _id(_fields(event).get("exchange_order_id")), context.get("exchange_order_id")
    if new is not None and known is None:
        context["exchange_order_id"] = new
    elif new is not None and new != known:
        logger().error("b01_exchange_order_id_mismatch", order_link_id=context.get("order_link_id"))


async def adopt_amend(_i: Any, context: dict[str, Any], event: Any, _a: Any) -> None:
    """An accepted amend's `terms`, all or none; any other result keeps the prior order (S2) and
    logs why. Never raises: on this `onDone` arm a rollback would send the amend again."""
    result = _fields(event)
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


async def map_reject_code(_i: Any, context: dict[str, Any], event: Any, _a: Any) -> None:
    """The ack's 24 Sec.8.6 code (the adapter maps it, C-2.2); else `EXCHANGE_UNKNOWN`."""
    code = _fields(event).get("error_code")
    known = isinstance(code, str) and code in _REJECT_CODES
    context["reject_code"] = code if known else OmsErrorCode.EXCHANGE_UNKNOWN.value


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


async def audit_guard_denied(_i: Any, context: dict[str, Any], event: Any, _a: Any) -> None:
    """B1's one deny arm, an EXEC's: logged and audited once with its `exec_id` and why; all but
    `REPEAT` is hostile (OM-T04), at ERROR for the OMS to answer with `FAULT`."""
    detail = {"exec_id": _id(_fields(event).get("exec_id")), "reason": ""}
    try:
        _admit(context, event)
    except ValueError as exc:
        detail["reason"] = str(exc)
    log = logger().info if detail["reason"] == REPEAT else logger().error
    log("b01_exec_refused", order_link_id=context.get("order_link_id"), **detail)
    await _hook("guard_denied", {**context, "denied": detail})


_STUB_ACTIONS = (
    "adopt_recon",
    "arm_recon_deadline",
    "arm_sl_deadline",
    "bump_recon_misses",
    "emit_terminal",
    "keep_prior_order_live",
    "mark_needs_lookup",
    "notify_amend_rejected",
    "notify_protection_region",
    "persist_event",
    "raise_critical_alert",
    "raise_naked_position_alert",
    "raise_unknown_alert",
    "record_transport_fault",
    "request_fallback_sl",
    "request_reconciliation",
    "reserve_rate_token",
    "set_reject_unresolvable",
)

ACTIONS: dict[str, Callable[..., Awaitable[None]]] = {
    **{name: _noop_action for name in _STUB_ACTIONS},
    "adopt_ack": adopt_ack,
    "adopt_amend": adopt_amend,
    "adopt_cancel_ack": adopt_ack,
    "apply_fill": apply_fill,
    "map_reject_code": map_reject_code,
    "set_local_reject": set_local_reject,
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
    "second_consecutive_miss": _deny_guard,
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
