"""The handler table (24 §11.5, R6; BQ-10 and BQ-13 of #863): one declared handler per action type.

Each of the 25 `ActionType`s declares `idempotent` or the guard it relies on against a double fire,
whether it places orders, the capability it needs and the ticket that binds it. The three flags
have one owner, the catalogue's `ActionSpec` (C-16.5); the table adds the guard's name, the
capability, the binder and the handler. Building the table refuses a type with neither flag, a
key outside `ActionType` and a type left undeclared, so the table is complete or the module does
not import.

No handler is bound in E35-T09: check 2 blocks every type `unavailable` until its slice binds it,
and check 8 refuses `widen_stop`, retired, for good as `native_sl` (24 §8.8 rule 5), bound or not
(`rules/executor/gates.py`, E35-T10). No order path is reachable from here (C-2.6): an
order-placing handler arrives with its slice's native-stop suite.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Final, Literal, Protocol, get_args
from uuid import UUID

from candleviewer.rules.executor.keys import request_sha256
from candleviewer.rules.executor.results import BlockedBy
from candleviewer.rules.ir.models import ActionType
from candleviewer.rules.scope import ActionRequest
from candleviewer.rules.vocabulary.catalogue import ACTIONS, RETIRED_ACTIONS, ActionSpec

Capability = Literal[
    "oms_entry", "oms_reduce", "oms_cancel", "oms_amend", "position_stop", "lockouts",
    "leverage", "algos", "notifications", "journal", "variables", "signals", "rule_control",
    "none",
]  # fmt: skip
#: The capabilities whose handlers run inside the engine (E35-T13): only these may be served by a
#: bound stand-in sink, so no stand-in ever reaches an OMS path, and only their six types name no
#: account. Every other capability reaches past the engine, behind the rollout port (24 §11.5).
ENGINE_INTERNAL: Final[frozenset[Capability]] = frozenset(
    {"notifications", "journal", "variables", "signals", "rule_control"}
)
#: How a handler's call ended, which `on_error` reads (24 §11.9): `accepted` and `done` took
#: effect; `refused` is a definite refusal, never retried (`blocked_by` when a check of the set
#: maps it); `pre_anchor` a refusal before the OMS anchor existed and `no_answer` a timeout or a
#: transport failure, the two `retry_once` may retry; `in_flight` is recorded `unknown` and never
#: re-sent; `raised` an engine-internal action that raised.
AnswerClass = Literal[
    "accepted", "refused", "pre_anchor", "no_answer", "in_flight", "done", "raised"
]


@dataclass(frozen=True, slots=True)
class HandlerAnswer:
    answer: AnswerClass
    error_code: str | None = None
    blocked_by: BlockedBy | None = None
    order_id: UUID | None = None
    group_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class Prepared:
    """One action's request for one account, built once by `Handler.prepare` and sent unchanged
    by every attempt, so a retry meets the anchor as the same request (`request_sha256`)."""

    request: Mapping[str, Any] = field(repr=False)
    request_sha256: str


def prepared(request: Mapping[str, Any]) -> Prepared:
    """`Prepared` for `request`, fingerprinted once, here (24 §11.9): a copy frozen at every depth
    (each mapping read-only, each list a tuple), so no later change to the caller's request
    reaches it, and its canonical form, so its fingerprint, is the request's."""
    held = MappingProxyType({k: _frozen(v) for k, v in request.items()})
    return Prepared(held, request_sha256(held))


def _frozen(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({k: _frozen(v) for k, v in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_frozen(v) for v in value)
    return value


class Handler(Protocol):
    """What runs an action: `prepare` is pure and builds the request once; `send` hands it over
    under the action's `client_ref`, once, or twice for `retry_once`, never rebuilt."""

    def prepare(self, req: ActionRequest, account_id: UUID | None) -> Prepared: ...

    async def send(self, prepared: Prepared, *, client_ref: str) -> HandlerAnswer: ...


class HandlerTableError(Exception):
    """The table is incomplete, or a type declares neither `idempotent` nor a guard."""


@dataclass(frozen=True, slots=True)
class HandlerSpec:
    """An action type's declaration: the catalogue's three flags, and the table's own columns."""

    action_type: str
    places_orders: bool
    idempotent: bool
    guarded: bool
    guard: str | None
    capability: Capability
    bound_by: str | None
    handler: Handler | None = None
    refused_as: BlockedBy | None = None  # a type refused for good, bound or not

    def __post_init__(self) -> None:
        if not self.idempotent and not (self.guarded and self.guard):
            raise HandlerTableError(f"{self.action_type} declares neither idempotent nor a guard")


@dataclass(frozen=True, slots=True)
class HandlerBinding:
    """The table's columns beside the catalogue's flags: never a flag of its own (BQ-10)."""

    capability: Capability
    bound_by: str | None
    guard: str | None = None
    refused_as: BlockedBy | None = None


def _b(capability: Capability, bound_by: str | None, guard: str | None = None) -> HandlerBinding:
    return HandlerBinding(capability, bound_by, guard)


#: The anchor keeps an action's `client_ref` and `request_sha256`: a repeat answers the first.
_ANCHOR: Final = "fire_key_anchor"
#: 24 §11.5 "Actions that cannot run yet" and #5000's out-of-scope list name each binder.
BINDINGS: Final[Mapping[str, HandlerBinding]] = MappingProxyType(
    {
        "place_order": _b("oms_entry", "E35-T11", _ANCHOR),
        "scale_in": _b("oms_entry", "E35-T11", _ANCHOR),
        "scale_out": _b("oms_reduce", "E35-T12", _ANCHOR),
        "flatten_position": _b("oms_reduce", "E35-T12"),
        "flatten_all_positions": _b("oms_reduce", "E35-T12"),
        "cancel_order": _b("oms_cancel", "E35-T12"),
        "cancel_all_orders": _b("oms_cancel", "E35-T12"),
        "modify_stop_loss": _b("oms_amend", "E35-T12"),  # a position's stop: #915
        "modify_take_profit": _b("oms_amend", "E35-T12"),
        "tighten_stop": _b("oms_amend", "E35-T12"),
        "move_to_breakeven": _b("position_stop", "#915"),
        "reverse_position": _b("position_stop", "#915", _ANCHOR),
        "halt_new_orders": _b("lockouts", "E39"),
        "resume_new_orders": _b("lockouts", "E39"),
        "reduce_leverage": _b("leverage", None),  # no leverage operation is planned yet
        "arm_chase_limit": _b("algos", "E33", _ANCHOR),
        "start_iceberg_slice": _b("algos", "E33", _ANCHOR),
        "start_twap": _b("algos", "E33", _ANCHOR),
        # The fire key on the alerts outbox's one row per delivery.
        "send_notification": _b("notifications", "E35-T13", "fire_key_outbox"),
        "log_journal_tag": _b("journal", "E35-T13"),
        "set_variable": _b("variables", "E35-T13"),
        # The fire key, and the signal chain's depth limit (RE-D7).
        "emit_signal": _b("signals", "E35-T13", "fire_key_signal_depth"),
        "pause_rule": _b("rule_control", "E35-T13"),
        "enable_rule": _b("rule_control", "E35-T13"),
        # Retired (24 §8.8 rule 5): never sent, so no repeat can reach a venue.
        "widen_stop": HandlerBinding("none", None, "never_sent", refused_as="native_sl"),
    }
)


def build_handlers(
    bindings: Mapping[str, HandlerBinding],
    catalogue: Iterable[ActionSpec],
    retired: frozenset[str],
) -> Mapping[str, HandlerSpec]:
    """The table, in `ActionType`'s order, or `HandlerTableError` naming what is wrong."""
    types: tuple[str, ...] = get_args(ActionType)
    if outside := sorted(set(bindings) - set(types)):
        raise HandlerTableError(f"bindings outside ActionType: {outside}")
    if missing := [t for t in types if t not in bindings]:
        raise HandlerTableError(f"action types with no binding: {missing}")
    declared = {spec.type: spec for spec in catalogue}
    table: dict[str, HandlerSpec] = {}
    for action_type in types:
        bound = bindings[action_type]
        if action_type in retired:  # no catalogue entry: declared refused for good, here
            if bound.refused_as is None:
                raise HandlerTableError(f"{action_type} is retired and names no refusal")
            flags = (False, False, True)
        else:
            spec = declared[action_type]
            flags = (spec.places_orders, spec.idempotent, spec.guarded)
        table[action_type] = HandlerSpec(
            action_type, *flags, guard=bound.guard, capability=bound.capability,
            bound_by=bound.bound_by, refused_as=bound.refused_as,
        )  # fmt: skip
    return MappingProxyType(table)


HANDLERS: Final[Mapping[str, HandlerSpec]] = build_handlers(BINDINGS, ACTIONS, RETIRED_ACTIONS)
