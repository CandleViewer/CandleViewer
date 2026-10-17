"""Per-role view of a `system` frame (SR-188, `23-ws-protocol.md` §15.9; #2175).

`system` is implicit (§6.2), so it is filtered per frame, not at `sub`: `_Connection.push_system`,
the one place a `system` frame is queued, asks `system_view` what the socket's principal may get
at that moment, so a role or grant change or an in-place re-`auth` applies to every later frame.
Deny by default: a `kind` outside §15.9's nine reaches nobody, and a principal with none of the
three roles (the deny-all snapshot) gets nothing. The Owner gets the frame whole; a Manager or
Viewer only the fields `NEUTRAL_FIELDS` lists for its `kind`, health components without `detail`
(`04-security-program.md` §7.2.2 row 48), a kill switch without who engaged it or why, its
accounts cut to the socket's `account_scope`, and only the flag keys that the injected
`FlagVisible` admits for its roles (E42-T03): none without one, and a `feature_flags` frame left
with no key is not sent. A body with nothing to leave out is passed on as is (no copy). A left-out
field, and a flag frame left with no key, are the contract, so nothing is audited or counted for
them; a whole frame that is faulty (an unknown `kind`, a kill switch without its state) or that
this socket cannot receive is named by `withheld_reason` for the gateway's counter.
`kill_switch_view` is that kill-switch cut on its own, for `auth_ok.kill_switch` (§4.3).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final

from candleviewer.auth.scopes import PrincipalSnapshot

if TYPE_CHECKING:  # the annotation only: the filter stays free of the metrics facade at run time
    from candleviewer.ws.metrics import WithheldReason

_BASE: Final = frozenset({"kind", "severity", "message"})
_KILL_SWITCH: Final = "kill_switch"
_COMPONENTS: Final = "components"
_ACCOUNTS: Final = "exchange_account_ids"
_FLAGS: Final = "feature_flags"
_EXCHANGE: Final = "exchange"
_APPLIED: Final = "applied"

#: (flag key, a principal's roles) -> whether that principal may learn the flag: its registry
#: `visibility`, and never for a key no flag definition names. The composition root builds it from
#: the flag registry (`ws` imports no `admin` code); without one no Manager or Viewer learns a flag.
FlagVisible = Callable[[str, frozenset[str]], bool]

#: §15.9 `kind` -> the fields a Manager or Viewer receives. Read-only, as is every table here: a
#: widened one is a reviewed change to this file, not a run-time one.
NEUTRAL_FIELDS: Final[Mapping[str, frozenset[str]]] = MappingProxyType(
    {
        "health": _BASE
        | {"health", _COMPONENTS, _EXCHANGE, "clock_offset_ms", "degraded_topics", _KILL_SWITCH}
        | {_FLAGS},
        _KILL_SWITCH: _BASE | {_KILL_SWITCH},
        _FLAGS: _BASE | {_FLAGS},
        "exchange_state": _BASE | {_EXCHANGE, "public_ws", "private_ws", "affected_symbols"},
        "connection_quality": _BASE | {"class", "queue_pct", "rtt_ms", _APPLIED},
        "shutdown_notice": _BASE | {"reason", "closing_in_ms", "expected_downtime_ms"},
        "degraded_data": _BASE | {"degraded_topics", "affected_symbols"},
        "clock_drift": _BASE | {"clock_offset_ms"},
        "notice": _BASE | {"reason"},
    }
)
#: The fields of a health component a Manager or Viewer receives.
NEUTRAL_COMPONENT: Final = frozenset({"name", "state", "last_good_at"})
#: The fields of `exchange` (`health`, `exchange_state`) and of `applied` (`connection_quality`) a
#: Manager or Viewer receives (§15.9 names them): the properties of the schema but
#: `rate_budget_free_pct`, the Owner's until E42-T05, its first producer, decides who sees it.
NEUTRAL_EXCHANGE: Final = frozenset({"public_ws", "private_ws", "rest"})
NEUTRAL_APPLIED: Final = frozenset({"throttle_multiplier", "forced_coalesce", "degraded_topics"})
_OBJECTS: Final[Mapping[str, frozenset[str]]] = MappingProxyType(
    {_EXCHANGE: NEUTRAL_EXCHANGE, _APPLIED: NEUTRAL_APPLIED}
)
#: The `killSwitch` fields a Manager or Viewer receives, besides its own `exchange_account_ids`.
NEUTRAL_KILL_SWITCH: Final = frozenset({"engaged", "scope", "engaged_at_ms"})
#: The roles that receive the role-neutral view (C-12.4); `owner` receives the frame whole.
SCOPED_ROLES: Final = frozenset({"manager", "viewer"})


def system_view(
    body: object, principal: PrincipalSnapshot | None, *, flag_visible: FlagVisible | None = None
) -> Mapping[str, Any] | None:
    """What `principal` receives of the `system` frame `body`: `body` itself, a copy holding only
    its role-neutral fields, or `None` for nothing. `flag_visible` decides the flag keys a Manager
    or Viewer may learn; without it they learn none. Never changes `body`."""
    if principal is None or not isinstance(body, Mapping):
        return None
    kind = body.get("kind")
    if not isinstance(kind, str):
        return None
    fields = NEUTRAL_FIELDS.get(kind)
    if fields is None:
        return None
    if principal.is_owner:
        return body
    if principal.roles.isdisjoint(SCOPED_ROLES):
        return None
    if _is_stateless(kind, body):
        return None  # a kill-switch frame is its state: never sent without it
    view = body
    for key in body:
        if key not in fields or not _is_neutral(key, body[key], principal.roles, flag_visible):
            view = _project(body, fields, principal, flag_visible)
            break
    if kind == _FLAGS and _FLAGS not in view:
        return None  # a flag frame is its keys: never sent with none the role may learn
    return view


def withheld_reason(body: object, principal: PrincipalSnapshot | None) -> WithheldReason | None:
    """Why `system_view` gives `principal` nothing of `body` for a reason that is not its role's
    cut. The frame is judged before the socket: a `kind` outside §15.9 (nobody receives it, the
    Owner included) and a kill-switch frame without its state (only the Owner receives that) are
    faults of the producer; then come no principal, and none of the three roles. `None` when it
    receives the frame, or is not meant to (a `feature_flags` frame with no key its role may learn,
    E42-T03): that is the contract. A Manager's or Viewer's flag frame has none, shown or not, so
    no flag predicate is needed."""
    kind = body.get("kind") if isinstance(body, Mapping) else None
    if not isinstance(body, Mapping) or not isinstance(kind, str) or kind not in NEUTRAL_FIELDS:
        return "unknown_kind"
    if principal is not None and principal.is_owner:
        return None
    if _is_stateless(kind, body):
        return "invalid_body"
    if principal is None:
        return "no_principal"
    return "no_role" if principal.roles.isdisjoint(SCOPED_ROLES) else None


def kill_switch_view(
    state: Mapping[str, Any], principal: PrincipalSnapshot
) -> Mapping[str, Any] | None:
    """What `principal` receives of the kill-switch `state`, in `auth_ok` (§4.3) as in a `system`
    frame: `state` itself for the Owner, a copy with only its role-neutral fields and its own
    accounts for a Manager or Viewer, `None` (nothing) for a principal with no role."""
    if principal.is_owner:
        return state
    if principal.roles.isdisjoint(SCOPED_ROLES):
        return None
    return _kill_switch_view(state, principal)


def _is_stateless(kind: str, body: Mapping[str, Any]) -> bool:
    """A kill-switch frame without its state, which only the Owner (any frame whole) receives."""
    return kind == _KILL_SWITCH and not isinstance(body.get(_KILL_SWITCH), Mapping)


def _is_neutral(
    key: str, value: object, roles: frozenset[str], visible: FlagVisible | None
) -> bool:
    """Whether a Manager or Viewer may receive this field of the kind's list as is: a nested
    object only with neutral fields and an empty list of accounts, a list only of such objects,
    a flag map only with keys it may learn."""
    if key == _FLAGS:  # with a key, and every key one the role may learn
        return isinstance(value, Mapping) and 0 < len(_flags(value, roles, visible)) == len(value)
    if key == _KILL_SWITCH:
        return isinstance(value, Mapping) and all(
            k in NEUTRAL_KILL_SWITCH or (k == _ACCOUNTS and value[k] == []) for k in value
        )
    if key == _COMPONENTS:
        return isinstance(value, list) and all(
            isinstance(item, Mapping) and all(k in NEUTRAL_COMPONENT for k in item)
            for item in value
        )
    if (neutral := _OBJECTS.get(key)) is not None:
        return isinstance(value, Mapping) and all(k in neutral for k in value)
    return True


def _project(
    body: Mapping[str, Any],
    fields: frozenset[str],
    principal: PrincipalSnapshot,
    visible: FlagVisible | None,
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in body.items():
        if key not in fields:
            continue
        if key == _FLAGS:
            if shown := _flags(value, principal.roles, visible):
                out[key] = shown
        elif key == _KILL_SWITCH:
            if isinstance(value, Mapping):
                out[key] = _kill_switch_view(value, principal)
        elif key == _COMPONENTS:
            if isinstance(value, list | tuple):
                out[key] = [_only(c, NEUTRAL_COMPONENT) for c in value if isinstance(c, Mapping)]
        elif (neutral := _OBJECTS.get(key)) is not None:
            if isinstance(value, Mapping):
                out[key] = _only(value, neutral)
        else:
            out[key] = value
    return out


def _flags(value: object, roles: frozenset[str], visible: FlagVisible | None) -> dict[str, Any]:
    """The flags of `value` a principal with `roles` may learn: the string keys `visible` admits,
    none without it, none of anything but a flag map."""
    if visible is None or not isinstance(value, Mapping):
        return {}
    return {
        key: flag for key, flag in value.items() if isinstance(key, str) and visible(key, roles)
    }


def _only(item: Mapping[str, Any], keys: frozenset[str]) -> dict[str, Any]:
    return {key: value for key, value in item.items() if key in keys}


def _kill_switch_view(state: Mapping[str, Any], principal: PrincipalSnapshot) -> dict[str, Any]:
    out = _only(state, NEUTRAL_KILL_SWITCH)
    if _ACCOUNTS in state:
        out[_ACCOUNTS] = _viewable(state[_ACCOUNTS], principal)
    return out


def _viewable(ids: object, principal: PrincipalSnapshot) -> list[str]:
    """The ids in `ids` that the connection's `account_scope` lists, canonical. Anything that is
    not a list or tuple of account ids names no account (a `str` or `bytes` is not one)."""
    if not isinstance(ids, list | tuple):
        return []
    mine = {grant.exchange_account_id for grant in principal.account_grants if grant.can_view}
    out: list[str] = []
    for raw in ids:
        account = _account(raw)
        if account is not None and account in mine:
            out.append(str(account))
    return out


def _account(raw: object) -> uuid.UUID | None:
    if isinstance(raw, uuid.UUID):
        return raw
    if not isinstance(raw, str):
        return None
    try:
        return uuid.UUID(raw)
    except ValueError:
        return None
