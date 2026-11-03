"""Per-connection view of the `system` safety summary (#2302; `23-ws-protocol.md` §15.9,
`24-internal-schemas.md` §8.13).

The publisher hands the gateway one in-process body per transition or count update: the wire
fields plus, for an account-keyed class, `_by_account` (account id -> that account's count and
since-time) and `_at_ms` (the event time). Neither internal key is ever serialised. Each
connection's view is derived here (C-12.4), deny by default:

- the Owner gets every body whole, less its in-process keys;
- every role gets a process-global class (`order_entry_halted`) as its wire fields;
- a Manager or Viewer gets an account-keyed class as the count and since-time of the accounts its
  `account_scope` lists, and its own state: `raised` while that count is above 0, else `cleared`;
- a Manager or Viewer gets nothing of a body or snapshot item whose class or environment is
  outside the contract.

`SafetyEdges`, held per connection, sends a `cleared` only to a connection that was sent the
`raised` it ends, never a frame that changes nothing it holds, and keeps each episode's start per
connection. It keeps the last body per (class, environment), at most 21, so that a change of the
connection's scope (`rescope`) sends at once the `raised` it newly may see and the `cleared`,
stamped with the change's time, of what it no longer may.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping
from typing import Any, Final, TypeGuard

from candleviewer.auth.scopes import PrincipalSnapshot, scoped_account_ids

SAFETY: Final = "safety"
SAFETY_CLASSES: Final = "safety_classes"
BY_ACCOUNT: Final = "_by_account"
AT_MS: Final = "_at_ms"
#: The classes whose subjects belong to an account: counted per connection's `account_scope`.
ACCOUNT_KEYED: Final = frozenset(
    {
        "native_sl_missing",
        "sl_attach_failed",
        "liquidation_risk",
        "risk_auto_flatten",
        "risk_lockout",
        "unwind_incomplete",
    }
)
#: The process-wide classes: every role receives them whole, as `exchange_state`.
PROCESS_GLOBAL: Final = frozenset({"order_entry_halted"})
CLASSES: Final = ACCOUNT_KEYED | PROCESS_GLOBAL
ENVIRONMENTS: Final = frozenset({"live", "demo", "testnet"})
#: The fields of a `safety` frame on the wire; anything else is dropped.
FRAME_FIELDS: Final = frozenset(
    {"kind", "severity", "safety_class", "environment", "state", "affected_count", "since_ms"}
)

Key = tuple[str, str]
#: A body -> the connection's view of it now (`system_filter.system_view` under its principal).
ViewOf = Callable[[Mapping[str, Any]], Mapping[str, Any] | None]


def is_faulty(body: Mapping[str, Any]) -> bool:
    """A `safety` frame no Manager or Viewer receives, because its producer got it wrong: a class
    or environment outside the contract, an account-keyed class without its breakdown and event
    time, or a process-global one that carries a breakdown."""
    if _key(body) is None:
        return True
    if body.get("safety_class") in PROCESS_GLOBAL:
        return BY_ACCOUNT in body
    return not isinstance(body.get(BY_ACCOUNT), Mapping) or not _is_ms(body.get(AT_MS))


def is_internal(key: object) -> bool:
    """An in-process key (`_by_account`, `_at_ms`, any `_`-prefixed one): never serialised."""
    return isinstance(key, str) and key.startswith("_")


def frame_view(body: Mapping[str, Any], principal: PrincipalSnapshot) -> Mapping[str, Any]:
    """A Manager's or Viewer's view of the valid `safety` frame `body` (`is_faulty` is false): a
    process-global class as its wire fields (`body` itself when it holds nothing else), an
    account-keyed one as the count, since-time and state of the principal's own accounts."""
    if body.get("safety_class") in PROCESS_GLOBAL:
        if body.keys() <= FRAME_FIELDS:
            return body
        return {key: value for key, value in body.items() if key in FRAME_FIELDS}
    public = {key: value for key, value in body.items() if key in FRAME_FIELDS}
    count, since = _in_scope(body.get(BY_ACCOUNT), principal)
    if count:
        return public | {
            "state": "raised",
            "severity": "critical",
            "affected_count": count,
            "since_ms": since,
        }
    return public | {
        "state": "cleared",
        "severity": "info",
        "affected_count": 0,
        "since_ms": body.get(AT_MS),
    }


def is_public(items: object) -> bool:
    """Whether `items` holds no in-process key (the Owner then gets the list as is)."""
    return not isinstance(items, list | tuple) or all(
        not isinstance(item, Mapping) or not any(is_internal(k) for k in item) for item in items
    )


def items_view(items: object, principal: PrincipalSnapshot | None) -> list[dict[str, Any]]:
    """The `safety_classes` items of a snapshot for `principal` (`None`: the Owner, who gets each
    item less its in-process keys). For a Manager or Viewer each item is rebuilt in a fixed key
    order, `{safety_class, environment, state}` and, only when raised, `affected_count` and
    `since_ms`: an account-keyed item is cut to its accounts (`clear` when none is affected, so
    "raised elsewhere" and "nothing anywhere" are the same bytes; `unknown` when a raised item
    lacks its breakdown), and an item whose class or environment is outside the contract is
    dropped (`dropped_items` counts them)."""
    if not isinstance(items, list | tuple):
        return []
    out: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, Mapping):
            continue
        if principal is None:
            out.append({k: v for k, v in item.items() if not is_internal(k)})
        elif (cut := _scoped_item(item, principal)) is not None:
            out.append(cut)
    return out


def dropped_items(items: object) -> int:
    """How many `safety_classes` items a Manager or Viewer is given nothing of (deny by default):
    each item whose class or environment is outside the contract."""
    if not isinstance(items, list | tuple):
        return 0
    return sum(1 for item in items if isinstance(item, Mapping) and _key(item) is None)


class SafetyEdges:
    """One connection's safety state: the last body per (class, environment) and what it was
    last sent as raised (count, the episode's start). At most 21 keys each: both are closed enums
    and every other value is refused before it is kept."""

    __slots__ = ("_bodies", "_sent")

    def __init__(self) -> None:
        self._bodies: dict[Key, Mapping[str, Any]] = {}
        self._sent: dict[Key, tuple[Any, Any]] = {}

    def seed(self, body: Mapping[str, Any], view: Mapping[str, Any]) -> None:
        """The `system` snap: keep each raised item of `body` as a body, and remember the items
        `view` (what this connection was sent) shows raised."""
        for item in _items(body.get(SAFETY_CLASSES)):
            if (key := _key(item)) is not None and item.get("state") == "raised":
                self._bodies[key] = _as_body(item)
        for item in _items(view.get(SAFETY_CLASSES)):
            if (key := _key(item)) is not None and item.get("state") == "raised":
                self._sent[key] = (item.get("affected_count"), item.get("since_ms"))

    def admit(self, body: Mapping[str, Any], view: Mapping[str, Any]) -> Mapping[str, Any] | None:
        """What to send of `view`, this connection's view of `body`: any frame but a `safety` one
        as is; a `cleared` only after a `raised` it was sent; a raised one only when its count
        changed, with the episode's start this connection holds; else nothing."""
        if view.get("kind") != SAFETY:
            return view
        key = _key(view)
        if key is None:
            return None
        self.observe(body)
        return self._step(key, view, None)

    def observe(self, body: Mapping[str, Any]) -> None:
        """Keep `body` as its key's last body (or drop the key on a clear), whatever this
        connection may see of it now, so a later `rescope` never revives a stale `raised`."""
        if body.get("kind") != SAFETY or (key := _key(body)) is None:
            return
        if body.get("state") == "raised":
            self._bodies[key] = body
        else:
            self._bodies.pop(key, None)

    def rescope(self, view_of: ViewOf, now_ms: int) -> list[Mapping[str, Any]]:
        """The connection's scope changed: each kept key seen anew under it, in key order. A key
        it now may see raised is sent `raised`; one it no longer may is sent `cleared`, stamped
        `now_ms`, the change's time, never the publisher's."""
        out: list[Mapping[str, Any]] = []
        for key in sorted(self._bodies.keys() | self._sent.keys()):
            body = self._bodies.get(key)
            view = None if body is None else view_of(body)
            if view is None:
                if key in self._sent:  # nothing of it may be seen now: end what it was sent
                    out.append(_cleared(key, now_ms))
                    del self._sent[key]
                continue
            if (sent := self._step(key, view, now_ms)) is not None:
                out.append(sent)
        return out

    def _step(
        self, key: Key, view: Mapping[str, Any], change_ms: int | None
    ) -> Mapping[str, Any] | None:
        last = self._sent.get(key)
        if view.get("state") != "raised":
            if last is None:
                return None
            del self._sent[key]
            return view if change_ms is None else {**view, "since_ms": change_ms}
        count = view.get("affected_count")
        since = view.get("since_ms") if last is None else last[1]
        if last is not None and last[0] == count:
            return None
        self._sent[key] = (count, since)
        return view if view.get("since_ms") == since else {**view, "since_ms": since}


def _scoped_item(item: Mapping[str, Any], principal: PrincipalSnapshot) -> dict[str, Any] | None:
    key = _key(item)
    if key is None:
        return None
    head: dict[str, Any] = {"safety_class": key[0], "environment": key[1]}
    state = item.get("state")
    if key[0] in PROCESS_GLOBAL:
        count, since = item.get("affected_count"), item.get("since_ms")
        if state == "raised" and _is_ms(count) and count >= 1 and _is_ms(since):
            return head | {"state": "raised", "affected_count": count, "since_ms": since}
        return head | {"state": "clear" if state == "clear" else "unknown"}
    if state == "raised":
        if not isinstance(item.get(BY_ACCOUNT), Mapping):
            return head | {"state": "unknown"}  # a fault: never read as an all-clear
        count, since = _in_scope(item.get(BY_ACCOUNT), principal)
        if count:
            return head | {"state": "raised", "affected_count": count, "since_ms": since}
        return head | {"state": "clear"}
    return head | {"state": "clear" if state == "clear" else "unknown"}


def _as_body(item: Mapping[str, Any]) -> dict[str, Any]:
    """A raised snapshot item as the body a frame of it would be, for `rescope`."""
    body: dict[str, Any] = {
        "kind": SAFETY,
        "severity": "critical",
        "safety_class": item.get("safety_class"),
        "environment": item.get("environment"),
        "state": "raised",
        "affected_count": item.get("affected_count"),
        "since_ms": item.get("since_ms"),
    }
    if BY_ACCOUNT in item:
        body |= {BY_ACCOUNT: item[BY_ACCOUNT], AT_MS: item.get("since_ms")}
    return body


def _cleared(key: Key, now_ms: int) -> dict[str, Any]:
    return {
        "kind": SAFETY,
        "severity": "info",
        "safety_class": key[0],
        "environment": key[1],
        "state": "cleared",
        "affected_count": 0,
        "since_ms": now_ms,
    }


def _items(value: object) -> list[Mapping[str, Any]]:
    if not isinstance(value, list | tuple):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _key(item: Mapping[str, Any]) -> Key | None:
    """(class, environment) when both are in the contract's closed sets, else `None`."""
    cls, env = item.get("safety_class"), item.get("environment")
    if isinstance(cls, str) and isinstance(env, str) and cls in CLASSES and env in ENVIRONMENTS:
        return cls, env
    return None


def _in_scope(by_account: object, principal: PrincipalSnapshot) -> tuple[int, int | None]:
    """The count over the accounts `principal`'s scope lists, and the earliest since-time. Keys
    are `uuid.UUID`s from the publisher, or their text."""
    if not isinstance(by_account, Mapping):
        return 0, None
    mine = scoped_account_ids(principal)
    count, since = 0, None
    for raw, entry in by_account.items():
        account = _account(raw)
        if account is None or account not in mine or not isinstance(entry, Mapping):
            continue
        n, at = entry.get("affected_count"), entry.get("since_ms")
        if not (_is_ms(n) and _is_ms(at)) or n < 1:
            continue
        count += n
        since = at if since is None else min(since, at)
    return count, since


def _account(raw: object) -> uuid.UUID | None:
    if isinstance(raw, uuid.UUID):
        return raw
    try:
        return uuid.UUID(str(raw))
    except ValueError:
        return None


def _is_ms(value: object) -> TypeGuard[int]:
    """A non-negative integer (a count or an epoch-ms time); never a bool."""
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0
