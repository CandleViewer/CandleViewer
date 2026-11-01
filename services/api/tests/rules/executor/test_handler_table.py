"""E35-T09 (#5000) slice 2c: the handler table for all 25 action types (BQ-10, BQ-13 of #863).

Each type declares `idempotent` or the guard it relies on (24 R6, US-RULE-003's NFR), whether it
places orders and the capability it needs. The three flags have one owner, the catalogue's
`ActionSpec`; the table adds the guard's name, the capability, the ticket that binds the handler
and the handler, unbound everywhere in E35-T09, so check 2 blocks every type `unavailable` but
`widen_stop`, which check 8 refuses for good as `native_sl` (24 §8.8 rule 5; E35-T10).
"""

from __future__ import annotations

import uuid
from dataclasses import fields, replace
from decimal import Decimal
from typing import Any, get_args

import pytest

from candleviewer.rules.executor.gates import Gates
from candleviewer.rules.executor.handlers import (
    BINDINGS,
    HANDLERS,
    Capability,
    HandlerAnswer,
    HandlerBinding,
    HandlerSpec,
    HandlerTableError,
    Prepared,
    bind_handlers,
    build_handlers,
    prepared,
)
from candleviewer.rules.executor.keys import request_sha256
from candleviewer.rules.executor.results import BlockedBy
from candleviewer.rules.ir.models import ActionType, RuleScope
from candleviewer.rules.scope import ScopeInstanceRef
from candleviewer.rules.vocabulary.catalogue import ACTIONS, RETIRED_ACTIONS
from tests.rules.executor.request_builders import Switches, action_request

#: Any request: check 8 refuses `widen_stop` by its type, whatever the request names.
_REQ = action_request(
    RuleScope(level="account"), uuid.UUID(int=0xA1), ScopeInstanceRef("*@*", None, None)
)

ACCOUNT = uuid.UUID(int=0xB1)

#: 24 §11.5 "Actions that cannot run yet" and #5000's out-of-scope list: capability, binder.
_OWNERS: dict[str, tuple[str, str | None]] = {
    "place_order": ("oms_entry", "E35-T11"), "scale_in": ("oms_entry", "E35-T11"),
    "scale_out": ("oms_reduce", "E35-T12"), "flatten_position": ("oms_reduce", "E35-T12"),
    "flatten_all_positions": ("oms_reduce", "E35-T12"),
    "cancel_order": ("oms_cancel", "E35-T12"), "cancel_all_orders": ("oms_cancel", "E35-T12"),
    "modify_stop_loss": ("oms_amend", "E35-T12"), "modify_take_profit": ("oms_amend", "E35-T12"),
    "tighten_stop": ("oms_amend", "E35-T12"),
    "move_to_breakeven": ("position_stop", "#915"), "reverse_position": ("position_stop", "#915"),
    "halt_new_orders": ("lockouts", "E39"), "resume_new_orders": ("lockouts", "E39"),
    "reduce_leverage": ("leverage", None),
    "arm_chase_limit": ("algos", "E33"), "start_iceberg_slice": ("algos", "E33"),
    "start_twap": ("algos", "E33"),
    "send_notification": ("notifications", "E35-T13"), "log_journal_tag": ("journal", "E35-T13"),
    "set_variable": ("variables", "E35-T13"), "emit_signal": ("signals", "E35-T13"),
    "pause_rule": ("rule_control", "E35-T13"), "enable_rule": ("rule_control", "E35-T13"),
    "widen_stop": ("none", None),
}  # fmt: skip


#: A non-idempotent type's guard declarations the table refuses: none, a `guarded` flag with no
#: guard named, a guard the catalogue does not declare, and an empty name.
_UNDECLARED: tuple[dict[str, Any], ...] = (
    {"guarded": False, "guard": None}, {"guarded": True, "guard": None},
    {"guarded": False, "guard": "fire_key_outbox"}, {"guarded": True, "guard": ""},
)  # fmt: skip


def refusal(spec: HandlerSpec) -> BlockedBy | None:
    """What the checks that read the table refuse (E35-T10): check 2 (`unavailable` while no
    handler is bound, the rollout port on, no stand-in), then check 8 (a type refused for good)."""
    gates = Gates(switches=Switches(rollout=True))
    return gates.before_scope(spec, None, stand_in=False) or gates.stop_check(spec, _REQ, None)


class _Bound:
    """A handler that a later slice would bind: here only to show the table's refusal goes."""

    def prepare(self, req: Any, account_id: Any, *, max_notional_usd: Any = None) -> Prepared:
        raise AssertionError("never reached")

    async def send(self, prepared: Prepared, *, client_ref: str) -> HandlerAnswer:
        raise AssertionError("never reached")


def test_every_action_type_has_a_handler_declaring_idempotent_or_a_guard() -> None:
    """Scenario: Every action type has a declared handler. Each of the 25 types declares
    `idempotent` or its guard, whether it places orders and its capability, and blocks
    `unavailable` while unbound (`widen_stop` aside, below)."""
    types = set(get_args(ActionType))
    assert len(types) == 25
    assert set(HANDLERS) == types == {spec.type for spec in ACTIONS} | RETIRED_ACTIONS
    for action_type, spec in HANDLERS.items():
        assert spec.action_type == action_type
        assert spec.idempotent or (spec.guarded and spec.guard), action_type
        assert spec.capability in get_args(Capability) and isinstance(spec.places_orders, bool)
        assert (spec.capability, spec.bound_by) == _OWNERS[action_type], action_type
        if action_type not in RETIRED_ACTIONS:
            assert refusal(spec) == "unavailable", action_type


def test_a_handler_spec_without_idempotent_or_a_guard_is_refused() -> None:
    bare: dict[str, Any] = {
        "action_type": "send_notification", "places_orders": False, "idempotent": False,
        "capability": "notifications", "bound_by": "E35-T13",
    }  # fmt: skip
    for declared in _UNDECLARED:
        with pytest.raises(HandlerTableError):
            HandlerSpec(**bare, **declared)
    stripped = [replace(a, guarded=False) if a.type == "emit_signal" else a for a in ACTIONS]
    with pytest.raises(HandlerTableError, match="emit_signal"):
        build_handlers(BINDINGS, stripped, RETIRED_ACTIONS)
    outside = {**BINDINGS, "teleport": BINDINGS["send_notification"]}
    with pytest.raises(HandlerTableError, match="outside"):
        build_handlers(outside, ACTIONS, RETIRED_ACTIONS)
    missing = {k: v for k, v in BINDINGS.items() if k != "place_order"}
    with pytest.raises(HandlerTableError, match="place_order"):
        build_handlers(missing, ACTIONS, RETIRED_ACTIONS)
    unrefused = {**BINDINGS, "widen_stop": replace(BINDINGS["widen_stop"], refused_as=None)}
    with pytest.raises(HandlerTableError, match="widen_stop"):
        build_handlers(unrefused, ACTIONS, RETIRED_ACTIONS)


def test_the_handler_flags_come_from_the_catalogue() -> None:
    """BQ-10: one owner per declaration (C-16.5). The table's own columns hold no flag, and the
    catalogue declares the two guards this ticket names (`send_notification`, `emit_signal`)."""
    catalogue = {spec.type: spec for spec in ACTIONS}
    for action_type, spec in HANDLERS.items():
        if action_type in RETIRED_ACTIONS:
            continue
        declared = catalogue[action_type]
        flags = (declared.places_orders, declared.idempotent, declared.guarded)
        assert (spec.places_orders, spec.idempotent, spec.guarded) == flags, action_type
    assert {f.name for f in fields(HandlerBinding)} == {
        "capability", "bound_by", "guard", "refused_as",
    }  # fmt: skip
    assert catalogue["send_notification"].guarded and catalogue["emit_signal"].guarded
    flipped = [replace(a, places_orders=not a.places_orders) for a in ACTIONS]
    rebuilt = build_handlers(BINDINGS, flipped, RETIRED_ACTIONS)
    assert all(rebuilt[a.type].places_orders is a.places_orders for a in flipped)


def test_unbound_handlers_block_as_unavailable() -> None:
    for action_type, spec in HANDLERS.items():
        assert spec.handler is None, action_type
        assert refusal(spec) == ("native_sl" if action_type == "widen_stop" else "unavailable")
    assert refusal(replace(HANDLERS["send_notification"], handler=_Bound())) is None


def test_no_order_placing_handler_is_bound_before_its_slice() -> None:
    """C-2.6: no order path is reached in E35-T09. An order-placing handler bound here would
    reach the OMS before its slice's native-SL suite (E35-T11's entry handlers, E33's algos,
    #915's reversal), so each is unbound and names the slice that binds it."""
    placing = {t for t, spec in HANDLERS.items() if spec.places_orders}
    assert placing == {
        "place_order", "scale_in", "reverse_position", "arm_chase_limit", "start_iceberg_slice",
        "start_twap",
    }  # fmt: skip
    for action_type in placing:
        spec = HANDLERS[action_type]
        assert spec.handler is None and spec.bound_by is not None, action_type
        assert spec.guard == "fire_key_anchor", action_type


def test_widen_stop_is_refused_as_native_sl_never_unavailable() -> None:
    """`widen_stop` only loosens a stop (24 §8.8 rule 5): retired, refused for good as
    `native_sl`, never `unavailable`, which would read as an action still to come; check 2 lets it
    through and check 8 refuses it by type (E35-T10)."""
    spec = HANDLERS["widen_stop"]
    gates = Gates(switches=Switches(rollout=False))  # the rollout port off: still never unavailable
    assert gates.before_scope(spec, None, stand_in=False) is None
    assert gates.stop_check(spec, _REQ, None) == "native_sl"
    assert refusal(spec) == "native_sl"
    assert refusal(replace(spec, handler=_Bound())) == "native_sl"  # a binding changes nothing
    assert (spec.places_orders, spec.capability, spec.bound_by) == (False, "none", None)


def test_prepared_keeps_a_frozen_copy_no_later_change_reaches() -> None:
    """A request is built once and sent unchanged by every attempt (24 §11.9): `prepared` keeps a
    copy frozen at every depth, so a later change to the caller's request, nested too, reaches
    neither the request a retry sends nor its fingerprint, and the copy takes no change itself."""
    source: dict[str, Any] = {
        "symbol": "BTCUSDT", "stop": {"trigger": Decimal("62000")},
        "legs": [{"qty": Decimal("0.010"), "account": ACCOUNT}],
    }  # fmt: skip
    prep = prepared(source)
    assert prep.request_sha256 == request_sha256(source)
    source["symbol"], source["stop"]["trigger"] = "ETHUSDT", Decimal("1")
    source["legs"][0]["qty"] = Decimal("9")
    source["legs"].append({"qty": Decimal("1")})
    assert prep.request == {
        "symbol": "BTCUSDT", "stop": {"trigger": Decimal("62000")},
        "legs": ({"qty": Decimal("0.010"), "account": ACCOUNT},),
    }  # fmt: skip
    assert request_sha256(prep.request) == prep.request_sha256
    with pytest.raises(TypeError):  # read-only at every depth
        prep.request["stop"]["trigger"] = Decimal("2")


class _Capable(_Bound):
    """A bindable handler of the `signals` capability (E35-T13, BQ-2 of #5005)."""

    capability: Capability = "signals"


def test_a_handler_binds_only_to_a_type_of_its_capability() -> None:
    """BQ-2 of #5005: binding checks each handler against its type's declared capability, and
    refuses a type outside the table or one refused for good; the static table stays unbound."""
    bound = bind_handlers(HANDLERS, {"emit_signal": _Capable()})
    assert isinstance(bound["emit_signal"].handler, _Capable)
    assert HANDLERS["emit_signal"].handler is None  # a new table; the static one is unchanged
    for action_type in ("set_variable", "place_order", "widen_stop", "teleport"):
        with pytest.raises(HandlerTableError, match=action_type):
            bind_handlers(HANDLERS, {action_type: _Capable()})
