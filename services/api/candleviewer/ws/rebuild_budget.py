"""The rebuild budget of one WS connection (SR-193, #2293; `23-ws-protocol.md` §7.5).

Each snapshot a `resync`, `ctl` or `sub` frame causes draws on it. Two limits share one sliding
window of `REBUILD_WINDOW_S`: one per topic (`topic_key`, with its replay session) and one for the
connection. A stamp leaves the window once it is a full window old (the exclusive edge of
`lifecycle.InboundRateLimiter`); a refused request records nothing, so asking again never
lengthens the wait. Each stamp keeps its path: only a topic's own resyncs make a resync loop.

It belongs to the connection (`ConnectionAuthz.rebuilds`), so an `unsub` and a new `sub` keep a
topic's stamps. Bounded (C-2.18): keys are kept in the order of their newest stamp and each call
forgets, from the front, every key with no stamp in the window. A key held has one, and so has
`_all`, which never holds more than the connection's limit: so many keys at most, of at most the
topic's limit of stamps each. Time is the connection's injected monotonic clock.
"""

from __future__ import annotations

from collections import OrderedDict, deque
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Literal

import structlog

from candleviewer.observability.metrics import Counter
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

    def __len__(self) -> int:
        """The keys held: those with a stamp in the window at the last call."""
        return len(self._keys)

    def drawn(self, key: Key, path: RebuildPath | None = None) -> int:
        """`key`'s draws in the window, or those of one `path`."""
        stamps = self._stamps(key, self._clock()) or ()
        return sum(1 for _, drew in stamps if path in (None, drew))

    def take(self, key: Key, path: RebuildPath) -> Scope | None:
        """Draw one rebuild of `key` for `path`; or draw nothing and return the limit that refused
        (the topic's when both do)."""
        now = self._clock()
        stamps = self._stamps(key, now)
        if stamps is not None and len(stamps) >= self.limits["topic"]:
            return "topic"
        if len(self._all) >= self.limits["connection"]:
            return "connection"
        if stamps is None:
            stamps = self._keys[key] = deque(maxlen=self.limits["topic"])
        stamps.append((now, path))
        self._keys.move_to_end(key)
        self._all.append(now)
        return None

    def refused(
        self, path: RebuildPath, scope: Scope, connection_id: str, ch: str, **fields: Any
    ) -> str:
        """Count and log one refusal (`ws resync rate limited`, 23 §7.7); returns the start of its
        `err` message."""
        cv_ws_rebuild_refused_total.labels(kind=path, cause=scope).inc()
        limit, log = self.limits[scope], structlog.get_logger(__name__)
        line = {"path": path, "scope": scope, "limit": limit, "window_s": REBUILD_WINDOW_S}
        log.warning("ws resync rate limited", connection_id=connection_id, ch=ch, **line, **fields)
        return f"Rebuild budget spent ({limit} a minute per {scope})"

    def _stamps(self, key: Key, now: float) -> deque[tuple[float, RebuildPath]] | None:
        """Age out the stamps a full window old and forget each key left with none; then `key`'s
        stamps, or None when it has none in the window."""
        while self._all and now - self._all[0] >= REBUILD_WINDOW_S:
            self._all.popleft()
        while self._keys and now - next(iter(self._keys.values()))[-1][0] >= REBUILD_WINDOW_S:
            self._keys.popitem(last=False)
        stamps = self._keys.get(key)
        while stamps and now - stamps[0][0] >= REBUILD_WINDOW_S:
            stamps.popleft()
        return stamps
