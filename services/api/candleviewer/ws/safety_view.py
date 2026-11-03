"""Per-connection view of the `system` safety summary (#2302; `23-ws-protocol.md` §15.9,
`24-internal-schemas.md` §8.13).

The publisher hands the gateway one in-process body per change of a key, unwindowed: the wire
fields plus, for an account-keyed class, `_by_account` (account id -> that account's count and
since-time) and `_at_ms` (the event time). Neither internal key is ever serialised. Each
connection's view is derived here (C-12.4), deny by default:

- the Owner gets every body whole, less its in-process keys;
- every role gets a process-global class (`order_entry_halted`) as its wire fields, rebuilt;
- a Manager or Viewer gets an account-keyed class as the count and since-time of the accounts its
  `account_scope` lists, and its own state: `raised` while that count is above 0, else `cleared`,
  stamped with the gateway's own time;
- a Manager or Viewer gets nothing of a body or snapshot item whose class or environment is
  outside the contract.

`SafetyEdges`, held per connection, applies the transition and count-update rules to that
connection's own view: a `raised` or `cleared` is sent at once, a count update at most once per
key per `WINDOW_S` (the latest at the window's end), a `cleared` only to a connection that was
sent the `raised` it ends, never a frame that changes nothing it holds, and each episode's start
is kept per connection. So what a connection is sent, and when, follows from its own view alone.
It keeps the last valid body per (class, environment), at most 21, so that a change of the
connection's scope (`rescope`) sends at once the `raised` it newly may see and the `cleared`,
stamped with the change's time, of what it no longer may. Its window timers are its own: each is
cancelled when its key's transition or a rescope replaces it, and all at the socket's teardown.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping
from functools import partial
from typing import Any, Final, Protocol, TypeGuard

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

#: §8.13 rule 5: a connection is sent at most one count update per key per this many seconds.
WINDOW_S: Final = 1.0

Key = tuple[str, str]
#: A body -> the connection's view of it now (`system_filter.system_view` under its principal).
ViewOf = Callable[[Mapping[str, Any]], Mapping[str, Any] | None]


class Timer(Protocol):
    """A scheduled callback: `asyncio.TimerHandle` in the gateway."""

    def cancel(self) -> None: ...


#: (delay in seconds, callback) -> its `Timer`: the gateway's is its loop's `call_later`.
CallLater = Callable[[float, Callable[[], None]], Timer]


def is_faulty(body: Mapping[str, Any]) -> bool:
    """A `safety` frame no Manager or Viewer receives, because its producer got it wrong: a class
    or environment outside the contract, an account-keyed class without its breakdown and event
    time, or a process-global one that carries a breakdown or whose state, count and since-time
    do not make a frame."""
    if _key(body) is None:
        return True
    if body.get("safety_class") in PROCESS_GLOBAL:
        return BY_ACCOUNT in body or _global_frame(body) is None
    return not isinstance(body.get(BY_ACCOUNT), Mapping) or not _is_ms(body.get(AT_MS))


def is_unkeyed(body: Mapping[str, Any]) -> bool:
    """A `safety` frame whose class or environment is outside the contract: no role is sent it,
    the Owner included (the gateway counts it `invalid_body`)."""
    return body.get("kind") == SAFETY and _key(body) is None


def is_internal(key: object) -> bool:
    """An in-process key (`_by_account`, `_at_ms`, any `_`-prefixed one): never serialised."""
    return isinstance(key, str) and key.startswith("_")


def frame_view(
    body: Mapping[str, Any], principal: PrincipalSnapshot, *, now_ms: int | None = None
) -> Mapping[str, Any] | None:
    """A Manager's or Viewer's view of the valid `safety` frame `body` (`is_faulty` is false),
    rebuilt from the seven fields: a process-global class as they are, an account-keyed one as
    the count, since-time and state of the principal's own accounts. Its `cleared` is stamped
    `now_ms`, the gateway's time on receipt, never the body's: without it, nothing."""
    key = _key(body)
    if key is None:
        return None
    if key[0] in PROCESS_GLOBAL:
        rebuilt = _global_frame(body)
        return body if rebuilt == body else rebuilt  # nothing to change: passed on, not copied
    count, since = _in_scope(body.get(BY_ACCOUNT), principal)
    if count:
        return _frame(key, "raised", count, since)
    return None if now_ms is None else _frame(key, "cleared", 0, now_ms)


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
    """One connection's safety state: the last valid body per (class, environment), what it was
    last sent as raised (count, the episode's start), and the open count-update windows. At most
    21 keys each: both are closed enums and every other value is refused before it is kept.

    `call_later` schedules each window's end; `due(key)` is called when a window ends with a
    count update held, and the gateway then sends `release(key, ...)`. Every timer is tracked
    here and cancelled by its key's next transition, a rescope, or `stop` (teardown)."""

    __slots__ = ("_bodies", "_call_later", "_due", "_held", "_sent", "_stopped", "_windows")

    def __init__(self, *, call_later: CallLater, due: Callable[[Key], None]) -> None:
        self._bodies: dict[Key, Mapping[str, Any]] = {}
        self._sent: dict[Key, tuple[Any, Any]] = {}
        self._windows: dict[Key, Timer] = {}
        self._held: set[Key] = set()
        self._call_later = call_later
        self._due = due
        self._stopped = False

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
        """What to send now of `view`, this connection's view of `body`: any frame but a `safety`
        one as is; a `raised` or `cleared` transition at once (a `cleared` only after a `raised`
        it was sent); a count update at once outside the key's window, else held for its end;
        else nothing."""
        if view.get("kind") != SAFETY:
            return view
        key = _key(view)
        if key is None:
            return None
        self.observe(body)
        return self._step(key, view, windowed=True)

    def observe(self, body: Mapping[str, Any]) -> None:
        """Keep `body` as its key's last body (or drop the key on a clear), whatever this
        connection may see of it now, so a later `rescope` never revives a stale `raised`. Only
        a body `is_faulty` accepts is kept: a faulty one changes nothing here."""
        if body.get("kind") != SAFETY or is_faulty(body) or (key := _key(body)) is None:
            return
        if body.get("state") == "raised":
            self._bodies[key] = body
        else:
            self._bodies.pop(key, None)

    def rescope(self, view_of: ViewOf, now_ms: int) -> list[Mapping[str, Any]]:
        """The connection's scope changed: each kept key seen anew under it, in key order, sent
        at once (a held count update goes with it). A key it now may see raised is sent `raised`;
        one it no longer may is sent `cleared`, stamped `now_ms`, the change's time."""
        out: list[Mapping[str, Any]] = []
        for key in sorted(self._bodies.keys() | self._sent.keys()):
            body = self._bodies.get(key)
            view = None if body is None else view_of(body)
            if view is None:
                if key in self._sent:  # nothing of it may be seen now: end what it was sent
                    out.append(_cleared(key, now_ms))
                    del self._sent[key]
                self._end_window(key)
                continue
            if (sent := self._step(key, view, windowed=False, change_ms=now_ms)) is not None:
                out.append(sent)
        return out

    def release(self, key: Key, view_of: ViewOf) -> Mapping[str, Any] | None:
        """The count update held for `key` when its window ended (`due`), seen under the
        connection's principal now; `None` when nothing it holds changed."""
        body = self._bodies.get(key)
        view = None if body is None else view_of(body)
        return None if view is None else self._step(key, view, windowed=False)

    def stop(self) -> None:
        """Teardown: every window timer is cancelled and none is started after."""
        self._stopped = True
        for key in list(self._windows):
            self._end_window(key)

    def _step(
        self, key: Key, view: Mapping[str, Any], *, windowed: bool, change_ms: int | None = None
    ) -> Mapping[str, Any] | None:
        last = self._sent.get(key)
        if view.get("state") != "raised":
            if last is None:
                return None
            del self._sent[key]
            self._end_window(key)  # a transition discards a held count update
            return view if change_ms is None else {**view, "since_ms": change_ms}
        count = view.get("affected_count")
        if last is not None and last[0] == count:
            self._held.discard(key)  # back to what it holds: nothing is due
            return None
        if last is not None and windowed and key in self._windows:
            self._held.add(key)  # a count update inside the window: the latest, at its end
            return None
        since = view.get("since_ms") if last is None else last[1]
        self._sent[key] = (count, since)
        self._start_window(key)
        return view if view.get("since_ms") == since else {**view, "since_ms": since}

    def _start_window(self, key: Key) -> None:
        self._end_window(key)
        if not self._stopped:
            self._windows[key] = self._call_later(WINDOW_S, partial(self._window_ended, key))

    def _end_window(self, key: Key) -> None:
        self._held.discard(key)
        if (timer := self._windows.pop(key, None)) is not None:
            timer.cancel()

    def _window_ended(self, key: Key) -> None:
        self._windows.pop(key, None)
        if key in self._held:
            self._held.discard(key)
            self._due(key)


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


def _global_frame(body: Mapping[str, Any]) -> dict[str, Any] | None:
    """A process-global `safety` body rebuilt from its seven fields, as `_scoped_item` rebuilds
    a snapshot item; `None` when its state, count and since-time do not make a frame."""
    key, state = _key(body), body.get("state")
    count, since = body.get("affected_count"), body.get("since_ms")
    if key is None or not (_is_ms(count) and _is_ms(since)):
        return None
    if state == "raised" and count >= 1:
        return _frame(key, "raised", count, since)
    if state == "cleared" and count == 0:
        return _frame(key, "cleared", 0, since)
    return None


def _frame(key: Key, state: str, count: int, since: int | None) -> dict[str, Any]:
    return {
        "kind": SAFETY,
        "severity": "critical" if state == "raised" else "info",
        "safety_class": key[0],
        "environment": key[1],
        "state": state,
        "affected_count": count,
        "since_ms": since,
    }


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
    return _frame(key, "cleared", 0, now_ms)


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
