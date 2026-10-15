"""Statechart inspector projections (E42-T07, module M21), pure and runtime-free.

The inspector never constructs or queries an `Interpreter` (MUSTNOT-03): it projects the
persisted snapshot and the registered chart, and imports only the registry API of
`candleviewer.statechart`. (Importing that package still loads `xstate_statemachine` into the
process, because `statechart/__init__` re-exports `factory`; an import-linter contract forbids
this package from importing the runtime, `factory`, `persistence` or `gateway` directly.)

- Entities follow the `machines.{entity}.state` grammar of E17-T08: `kind` for a singleton,
  `kind:id` otherwise. B8, B9, B13 and B15 have no public id yet, so they have no entity kind.
- Visibility: the inspector is an owner surface (`admin:read`, asserted again by the route), a
  user-scoped kind (`alert`, `replay`, `session`) stays self-scoped for every role, owner
  included (D2 on #414), and a scoped entry without its bound scope is refused (#2438 6.4).
- `context_summary` keeps only the keys the topic allows per kind, and only scalar values.
- `export_chart` is the Stately projection of the chart registered for a key's kind; it reads no
  instance, so the answer is the same for any id of a registered kind.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Final, Literal
from uuid import UUID

from candleviewer.admin.errors import AdminError
from candleviewer.statechart import MachineNotFoundError, Registry

Scope = Literal["account", "user", "none"]
Scalar = str | int | float | bool | None


@dataclass(frozen=True, slots=True)
class EntityKind:
    scope: Scope
    singleton: bool
    machine_kinds: tuple[str, ...]
    summary_keys: tuple[str, ...] = ()


_ACCOUNT: Final[Scope] = "account"
_USER: Final[Scope] = "user"
_NONE: Final[Scope] = "none"
#: The E17-T08 entity table (`23-ws-protocol.md` 6.4 on #2438): scope and summary keys per kind.
ENTITY_KINDS: Final[Mapping[str, EntityKind]] = MappingProxyType(
    {
        "order": EntityKind(
            _ACCOUNT, False, ("order",), ("symbol", "halted_by_kill", "recon_misses")
        ),
        "trade_group": EntityKind(_ACCOUNT, False, ("trade_group",)),
        "leg": EntityKind(_ACCOUNT, False, ("leg",)),
        "algo": EntityKind(_ACCOUNT, False, ("oco", "iceberg", "twap", "chase")),
        "alert": EntityKind(
            _USER, False, ("alert",), ("severity", "delivery_attempts", "storm_count")
        ),
        "recording": EntityKind(_NONE, False, ("recording",), ("symbol", "gap_count_24h")),
        "replay": EntityKind(_USER, False, ("replay",)),
        "book": EntityKind(_NONE, False, ("book",), ("symbol", "resync_count")),
        "session": EntityKind(_USER, False, ("session",), ("mfa_satisfied", "step_up_failures")),
        "live_gate": EntityKind(_NONE, True, ("live_gate",)),
        "kill_switch": EntityKind(
            _NONE, True, ("kill_switch",), ("scope", "cancel_working", "flatten")
        ),
        "reconciliation": EntityKind(_ACCOUNT, False, ("reconciliation",)),
        "risk_lockout": EntityKind(_ACCOUNT, False, ("risk_lockout",)),
    }
)


#: The id part: a lowercase canonical uuid or a `23-ws-protocol.md` 13 symbol.
_ID: Final = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|[A-Z0-9]{2,30}"
)


class UnknownMachineKeyError(AdminError, LookupError):
    """The key names no entity kind, or does not fit its kind (`404 not_found`)."""


def parse_machine_key(key: str) -> tuple[str, str | None]:
    """`(entity kind, id)`; a singleton has no id and every other kind has exactly one."""
    kind, sep, entity_id = key.partition(":")
    rule = ENTITY_KINDS.get(kind)
    if rule is None or rule.singleton == bool(sep) or (sep and not _ID.fullmatch(entity_id)):
        raise UnknownMachineKeyError(key)
    return kind, entity_id or None


def visible(
    kind: str, *, scope_user: UUID | None, scope_account: UUID | None, caller: UUID
) -> bool:
    """Whether the owner caller may see an entity. Fails closed: an unknown kind, another user's
    user-scoped entity and an account-scoped entity with no bound account are all refused."""
    rule = ENTITY_KINDS.get(kind)
    if rule is None:
        return False
    if rule.scope == _USER:
        return scope_user is not None and scope_user == caller
    return rule.scope != _ACCOUNT or scope_account is not None


def context_summary(kind: str, context: Mapping[str, Any]) -> dict[str, Scalar]:
    """The allowed keys of `context` for the entity kind, scalar values only."""
    rule = ENTITY_KINDS.get(kind)
    keys = rule.summary_keys if rule else ()
    return {
        k: context[k]
        for k in keys
        if k in context and (context[k] is None or isinstance(context[k], (str, int, float, bool)))
    }


def published_state(chart: Mapping[str, Any], configuration: Sequence[str]) -> str | None:
    """The active direct child of the chart root (the first region's, for a parallel chart),
    from the snapshot's full configuration (`<root>.<state>` ids); `None` if none is active."""
    root, states = str(chart["id"]), chart.get("states", {})
    if chart.get("type") == "parallel" and states:
        region = next(iter(states))
        root, states = f"{root}.{region}", states[region].get("states", {})
    active = set(configuration)
    return next((name for name in states if f"{root}.{name}" in active), None)


def export_chart(registry: Registry, machine_key: str) -> dict[str, Any]:
    """`StatechartExport` for the chart registered under the key's kind (a bare catalogue
    `machine_kind` works too); raises `UnknownMachineKeyError` for an unregistered kind."""
    # A bare catalogue kind names a chart directly; an entity key must fit the grammar.
    kind = parse_machine_key(machine_key)[0] if ":" in machine_key else machine_key
    try:
        registry.get(kind)
    except MachineNotFoundError as exc:
        raise UnknownMachineKeyError(machine_key) from exc
    return {
        "machine_kind": kind,
        "machine_hash": registry.hash(kind),
        "stately": registry.export_stately(kind),
    }
