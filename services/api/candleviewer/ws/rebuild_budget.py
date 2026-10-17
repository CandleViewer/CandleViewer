"""The rebuild budget of one WS connection (SR-193, #2293; `23-ws-protocol.md` §7.5).

Each snapshot a `resync`, `ctl` or `sub` frame causes draws on it: one limit per topic (`topic_key`,
with its replay session) and one for the connection, over a sliding `REBUILD_WINDOW_S` with the
exclusive edge of `lifecycle.InboundRateLimiter`. A refusal records nothing. Each stamp keeps its
path (only a topic's own resyncs make a resync loop); a `sub` counts toward its topic only within a
window of the topic's release. Owned by the connection (`ConnectionAuthz.rebuilds`), it outlives an
`unsub`. Bounded (C-2.18): keys go in the order of their newest stamp and each call forgets those
with none in the window, so at most the connection's limit of keys are held, as `_all` holds; a
release is kept one window, and each followed a start that drew. Time is the connection's clock.
"""

from __future__ import annotations

from collections import OrderedDict, deque
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Literal

import structlog

from candleviewer.observability.metrics import Counter
from candleviewer.ws.lifecycle import RefusalLog, RefusalLogLimiter
from candleviewer.ws.limits import (
    REBUILD_MAX_PER_CONNECTION,
    REBUILD_MAX_PER_TOPIC,
    REBUILD_WINDOW_S,
)

if TYPE_CHECKING:
    from candleviewer.ws.topics import ParsedTopic

Key = tuple[str, str | None]  # (topic, replay_session_id)
Scope = Literal["topic", "connection"]
RebuildPath = Literal["resync", "ctl", "sub"]

cv_ws_rebuild_refused_total = Counter(
    "cv_ws_rebuild_refused_total",
    "Client WS requests the rebuild budget refused (23 section 7.5), by kind and refusing limit.",
    labelnames=("kind", "cause"),
)
for _kind in ("resync", "ctl", "sub"):  # bound now, so each series exists at 0 from the start
    for _cause in ("topic", "connection"):
        cv_ws_rebuild_refused_total.labels(kind=_kind, cause=_cause)


def topic_key(topic: ParsedTopic, replay_session_id: str | None) -> Key:
    """The budget's key for `topic`: the topic and its replay session."""
    if topic.entity_kind is not None:
        return topic.ch, replay_session_id
    param = str(int(topic.param)) if topic.param and topic.param.isdigit() else topic.param
    parts = (topic.family.family, topic.symbol, topic.depth, topic.bar_type, param, topic.kind)
    return ".".join(str(part) for part in parts if part is not None), replay_session_id


class RebuildBudget:
    """One connection's rebuild budget (module doc), on the connection's `clock`."""

    def __init__(
        self,
        clock: Callable[[], float],
        *,
        per_topic: int = REBUILD_MAX_PER_TOPIC,
        per_connection: int = REBUILD_MAX_PER_CONNECTION,
    ) -> None:
        self._clock = clock
        self.limits: dict[Scope, int] = {"topic": per_topic, "connection": per_connection}
        self._keys: OrderedDict[Key, deque[tuple[float, RebuildPath]]] = OrderedDict()
        self._all: deque[float] = deque(maxlen=per_connection)
        self._released: OrderedDict[Key, float] = OrderedDict()  # in the order of release
        self._logs = RefusalLogLimiter()  # the refusal line, capped per path (§7.7)

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
        """The limit that would refuse a draw (the topic's when both would), else None."""
        stamps = self._stamps(key, self._clock())
        mine = path != "sub" or key in self._released
        if mine and stamps is not None and len(stamps) >= self.limits["topic"]:
            return "topic"
        if len(self._all) >= self.limits["connection"]:
            return "connection"
        return None

    def draw(self, key: Key, path: RebuildPath) -> None:
        """Record one rebuild (a `sub` of a topic not released in the window: the connection's)."""
        now = self._clock()
        stamps = self._stamps(key, now)
        self._all.append(now)
        if path == "sub" and key not in self._released:
            return
        if stamps is None:
            stamps = self._keys[key] = deque(maxlen=self.limits["topic"])
        stamps.append((now, path))
        self._keys.move_to_end(key)

    def released(self, key: Key) -> None:
        """A subscription of `key` ended (an `unsub`, a revocation)."""
        now = self._clock()
        self._stamps(key, now)
        self._released[key] = now
        self._released.move_to_end(key)

    def count_refusal(self, path: RebuildPath, scope: Scope) -> str:
        """Count one refusal; returns the start of its `err` message."""
        cv_ws_rebuild_refused_total.labels(kind=path, cause=scope).inc()
        return f"Rebuild budget spent ({self.limits[scope]} a minute per {scope})"

    def log(
        self, path: RebuildPath, scope: Scope, connection_id: str, ch: str, **fields: Any
    ) -> None:
        """`ws resync rate limited` (23 §7.7) per refused `resync` or `ctl` and per `sub` frame: the
        first `REFUSAL_LOG_LIMIT` a window per path, one `capped`, then none."""
        if (verdict := self._logs.admit(path, self._clock())) is RefusalLog.NONE:
            return
        limit, log = self.limits[scope], structlog.get_logger(__name__)
        line = {"path": path, "scope": scope, "limit": limit, "window_s": REBUILD_WINDOW_S}
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
