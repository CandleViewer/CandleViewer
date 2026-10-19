"""The rebuild budget of one WS connection (SR-193, #2293; `23-ws-protocol.md` §7.5).

Each snapshot a `resync`, `ctl` or `sub` frame causes draws on it: one limit per topic (`topic_key`,
with its replay session) and one for the connection, over a sliding `REBUILD_WINDOW_S` with the
exclusive edge of `lifecycle.InboundRateLimiter`. A refusal records nothing. Each stamp keeps its
path (only a topic's own resyncs make a resync loop); a `sub` counts toward its topic only within a
window of the topic's release. Owned by the connection (`ConnectionAuthz.rebuilds`), it outlives an
`unsub`. Bounded (C-2.18): keys go in the order of their newest stamp and each call forgets those
with none in the window, so at most the connection's limit of keys are held, as `_all` holds; a
release is kept one window, and each followed a start that drew. Time is the connection's clock.

Every draw also counts toward the limit of the connection's user (`UserRebuilds`, #3476), which
all of the user's connections share; it is checked after the topic's and the connection's.
"""

from __future__ import annotations

import uuid
from collections import OrderedDict, deque
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Literal

import structlog

from candleviewer.observability.metrics import Counter
from candleviewer.ws.lifecycle import RefusalLog, RefusalLogLimiter
from candleviewer.ws.limits import (
    REBUILD_MAX_PER_CONNECTION,
    REBUILD_MAX_PER_TOPIC,
    REBUILD_MAX_PER_USER,
    REBUILD_WINDOW_S,
)

if TYPE_CHECKING:
    from candleviewer.ws.topics import ParsedTopic

Key = tuple[str, str | None]  # (topic, replay_session_id)
Scope = Literal["topic", "connection", "user"]
RebuildPath = Literal["resync", "ctl", "sub"]

cv_ws_rebuild_refused_total = Counter(
    "cv_ws_rebuild_refused_total",
    "Client WS requests the rebuild budget refused (23 section 7.5), by kind and refusing limit.",
    labelnames=("kind", "cause"),
)
for _kind in ("resync", "ctl", "sub"):  # bound now, so each series exists at 0 from the start
    for _cause in ("topic", "connection", "user"):
        cv_ws_rebuild_refused_total.labels(kind=_kind, cause=_cause)


def topic_key(topic: ParsedTopic, replay_session_id: str | None) -> Key:
    """The budget's key for `topic`: the topic and its replay session."""
    if topic.entity_kind is not None:
        return topic.ch, replay_session_id
    param = str(int(topic.param)) if topic.param and topic.param.isdigit() else topic.param
    parts = (topic.family.family, topic.symbol, topic.depth, topic.bar_type, param, topic.kind)
    return ".".join(str(part) for part in parts if part is not None), replay_session_id


class UserRebuilds:
    """The limit per user that every draw of the user's connections also counts toward (#3476): at
    most `limit` in any sliding `REBUILD_WINDOW_S`, counting the draw each accepted `sub` entry
    holds until it starts or ends (`hold`), so connections that check at once never pass it
    together. One per process (`SubscriptionServices.user_rebuilds`), on the router's clock, which
    the connections share. A user is kept while it has a draw in the window, so neither a new
    connection nor a reconnect resets it. Bounded (C-2.18): users go in the order of their newest
    draw and each call first forgets those with none in the window (`ConnectRateLimiter`'s way),
    each with at most `limit` stamps; a connection holds at most one draw (one reader)."""

    def __init__(self, limit: int = REBUILD_MAX_PER_USER) -> None:
        self.limit = limit
        self._stamps: OrderedDict[uuid.UUID, deque[float]] = OrderedDict()
        self._held: dict[uuid.UUID, int] = {}
        self._audited: OrderedDict[uuid.UUID, float] = OrderedDict()  # user -> its record's time

    def spent(self, user: uuid.UUID, now: float) -> bool:
        """True when `user` has no draw left: its draws in the window plus those held."""
        return len(self._window(user, now) or ()) + self._held.get(user, 0) >= self.limit

    def hold(self, user: uuid.UUID) -> None:
        """Hold one of `user`'s draws for an accepted `sub` entry that has not started."""
        self._held[user] = self._held.get(user, 0) + 1

    def unhold(self, user: uuid.UUID) -> None:
        """Let a held draw go: its entry started (a `stamp` follows) or ended."""
        if (left := self._held.get(user, 0) - 1) > 0:
            self._held[user] = left
        else:
            self._held.pop(user, None)

    def first_refusal(self, user: uuid.UUID, now: float) -> bool:
        """True for `user`'s first `user` refusal in a window, which its one audit record then
        stands for (#3476). Bounded as the draws: in the order of the records, aged out first."""
        while self._audited and now - next(iter(self._audited.values())) >= REBUILD_WINDOW_S:
            self._audited.popitem(last=False)
        if user in self._audited:
            return False
        self._audited[user] = now
        return True

    def stamp(self, user: uuid.UUID, now: float) -> None:
        """Record one draw of `user`."""
        stamps = self._window(user, now)
        if stamps is None:
            stamps = self._stamps[user] = deque(maxlen=self.limit)
        stamps.append(now)
        self._stamps.move_to_end(user)

    def _window(self, user: uuid.UUID, now: float) -> deque[float] | None:
        """Forget every user whose newest draw is a full window old; then `user`'s draws in the
        window, or None when it has none. A user left with none is forgotten at once, so the sweep
        never meets an empty window, whatever the order of the clock values it is given."""
        while self._stamps and now - next(iter(self._stamps.values()))[-1] >= REBUILD_WINDOW_S:
            self._stamps.popitem(last=False)
        stamps = self._stamps.get(user)
        while stamps and now - stamps[0] >= REBUILD_WINDOW_S:
            stamps.popleft()
        if stamps is not None and not stamps:
            del self._stamps[user]
            return None
        return stamps


class RebuildBudget:
    """One connection's rebuild budget (module doc), on the connection's `clock`; with `user` (the
    process's `UserRebuilds` and the connection's user), every draw also counts toward that."""

    def __init__(
        self,
        clock: Callable[[], float],
        *,
        per_topic: int = REBUILD_MAX_PER_TOPIC,
        per_connection: int = REBUILD_MAX_PER_CONNECTION,
        user: tuple[UserRebuilds, uuid.UUID] | None = None,
    ) -> None:
        self._clock = clock
        self.limits: dict[Scope, int] = {"topic": per_topic, "connection": per_connection}
        self._user = user
        if user is not None:
            self.limits["user"] = user[0].limit
        self._keys: OrderedDict[Key, deque[tuple[float, RebuildPath]]] = OrderedDict()
        self._all: deque[float] = deque(maxlen=per_connection)
        self._released: OrderedDict[Key, float] = OrderedDict()  # in the order of release
        self._logs = RefusalLogLimiter()  # the refusal line, capped per path (§7.7)
        #: #3476: the key of a `user` refusal whose audit record is due, until the request's reply
        #: is out (`permissions.audit_rebuild_refusal`, which writes it if the user's first).
        self.audit_due: Key | None = None

    def drawn(self, key: Key, path: RebuildPath | None = None) -> int:
        """`key`'s draws in the window, or those of one `path`."""
        stamps = self._stamps(key, self._clock()) or ()
        return sum(1 for _, drew in stamps if path in (None, drew))

    def take(self, key: Key, path: RebuildPath) -> Scope | None:
        """Draw one rebuild of `key` for `path`, or draw nothing and return the refusing limit."""
        scope = self.refusal(key, path)
        if scope is None:
            self.draw(key, path)
        return scope

    def refusal(self, key: Key, path: RebuildPath) -> Scope | None:
        """The limit that would refuse a draw: the first of topic, connection and user that does."""
        now = self._clock()
        stamps = self._stamps(key, now)
        mine = path != "sub" or key in self._released
        if mine and stamps is not None and len(stamps) >= self.limits["topic"]:
            return "topic"
        if len(self._all) >= self.limits["connection"]:
            return "connection"
        if self._user is not None and self._user[0].spent(self._user[1], now):
            return "user"
        return None

    def draw(self, key: Key, path: RebuildPath, *, held: bool = False) -> None:
        """Record one rebuild (a `sub` of a topic not released in the window: the connection's and
        the user's); `held`: the draw its `sub` entry held (`hold`) becomes it, in one step. A
        `sub` with no hold, one `_drop` ended while it waited, builds no snapshot: it draws on the
        connection, as SR-193 counts it, but never on the user, whose bound stays exact."""
        now = self._clock()
        stamps = self._stamps(key, now)
        self._all.append(now)
        if self._user is not None and (held or path != "sub"):
            users, user = self._user
            if held:
                users.unhold(user)
            users.stamp(user, now)
        if path == "sub" and key not in self._released:
            return
        if stamps is None:
            stamps = self._keys[key] = deque(maxlen=self.limits["topic"])
        stamps.append((now, path))
        self._keys.move_to_end(key)

    def hold(self) -> bool:
        """Hold one of the user's draws for an accepted `sub` entry, until `draw(held=True)` or
        `unhold`; False, holding nothing, without a user."""
        if self._user is None:
            return False
        self._user[0].hold(self._user[1])
        return True

    def unhold(self) -> None:
        """Let go of the draw `hold` took for an entry that never started."""
        if self._user is not None:
            self._user[0].unhold(self._user[1])

    def released(self, key: Key) -> None:
        """A subscription of `key` ended (an `unsub`, a revocation)."""
        now = self._clock()
        self._stamps(key, now)
        self._released[key] = now
        self._released.move_to_end(key)

    def count_refusal(self, path: RebuildPath, scope: Scope, key: Key) -> str:
        """Count one refusal of `key`; returns the start of its `err` message. A `user` refusal
        leaves `key` due for the user's audit record (`audit_due`) when none is due; the window is
        marked only as that record is written (`first_user_refusal`)."""
        cv_ws_rebuild_refused_total.labels(kind=path, cause=scope).inc()
        if scope == "user" and self.audit_due is None:
            self.audit_due = key
        return f"Rebuild budget spent ({self.limits[scope]} a minute per {scope})"

    def first_user_refusal(self) -> bool:
        """True, and the user's window marked, when no record of the user's was written in it
        (`UserRebuilds.first_refusal`): asked just before that record is written."""
        return self._user is not None and self._user[0].first_refusal(self._user[1], self._clock())

    def log(
        self,
        path: RebuildPath,
        scope: Scope,
        connection_id: str,
        ch: str,
        *,
        rs: str | None,
        **fields: Any,
    ) -> None:
        """`ws resync rate limited` (23 §7.7) per refused `resync` or `ctl` and per `sub` frame: the
        first `REFUSAL_LOG_LIMIT` a window per path, one `capped` (that refusal's own line, flagged,
        so it names its `ch` and `rs` too), then none. `rs`: the canonical id of the replay session
        of `ch`'s stream, never the client's text; None for a live stream, which has no key."""
        if (verdict := self._logs.admit(path, self._clock())) is RefusalLog.NONE:
            return
        limit, log = self.limits[scope], structlog.get_logger(__name__)
        line = {"path": path, "scope": scope, "limit": limit, "window_s": REBUILD_WINDOW_S}
        if rs is not None:  # a replay stream and its live twin share a `ch`
            fields["rs"] = rs
        if verdict is RefusalLog.SUMMARY:
            line["capped"] = True
        log.warning("ws resync rate limited", connection_id=connection_id, ch=ch, **line, **fields)

    def _stamps(self, key: Key, now: float) -> deque[tuple[float, RebuildPath]] | None:
        """Age out the stamps a full window old and forget each key left with none; then `key`'s
        stamps, or None when it has none in the window."""
        while self._all and now - self._all[0] >= REBUILD_WINDOW_S:
            self._all.popleft()
        while self._keys and now - next(iter(self._keys.values()))[-1][0] >= REBUILD_WINDOW_S:
            self._keys.popitem(last=False)
        while self._released and now - next(iter(self._released.values())) >= REBUILD_WINDOW_S:
            self._released.popitem(last=False)
        stamps = self._keys.get(key)
        while stamps and now - stamps[0][0] >= REBUILD_WINDOW_S:
            stamps.popleft()
        return stamps
