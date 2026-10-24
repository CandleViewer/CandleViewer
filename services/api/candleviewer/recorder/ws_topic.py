"""The `recorder` WS topic (E16-T08, #492; 23 §6.2.2, §15.8): the recorder module's snapshot source
for the family and the frame it publishes once a second.

The recorder may not import `ws` (CONSTITUTION §3), so the protocol is met structurally, as the
alerts and wallet topics meet it: `sub` is typed by the fields read here, and the gateway's body
constructor and its hub's `subscriptions`, `publish` and `resnapshot` are injected
(`ws_wiring.recorder_topic`).

- Snapshot: the last `RecordingStatusCache` status in the subscription's view, its `symbols`
  narrowed to the `symbols` option when that names any. A requested symbol the recorder does not
  track is `{symbol, state: "idle"}` in a full frame and left out of a restricted one. `None` until
  a runtime is bound, so a subscription stays `snapshot_pending` (§7.7). Private: generation 0, and
  every `snapshot: false` attach is forced (§7.6).
- View: `role_restricted`, recorded on the subscription at `sub` for every principal but the Owner
  (ruling Q6), never a client value, and again at each §9.5 re-evaluation: a principal that is no
  longer the Owner is re-snapped (`reconfigure`) in the restricted view, while one that becomes the
  Owner keeps the restricted view until it resubscribes. A restricted frame has no symbol recorded
  only for an open position, no `position_open` and no endpoint, so no path character.
- Deltas: on each computation, the whole frame (never merged, §8.2), one `publish` per (symbols,
  view) group, which also wakes that group's pending subscriptions; a full frame reaches only a
  principal that is the Owner now. A publish that raises re-snapshots every `recorder`
  subscription with `upstream_desync` (§7.4).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any, Final, Literal, Protocol

import structlog

from candleviewer.recorder import control as rc
from candleviewer.recorder.status import RecordingStatusCache, StatusSnapshot, epoch_ms

RECORDER: Final = "recorder"
#: Per-symbol fields sent as they are, once the runtime knows them.
_PLAIN: Final = (
    "lag_ms", "rows_last_hour", "dropped_messages", "resyncs_last_hour", "disk_bytes", "lingering",
)  # fmt: skip


class RecorderSub(Protocol):
    """The fields of a WS `Subscription` read here."""

    @property
    def ch(self) -> str: ...
    @property
    def symbols(self) -> frozenset[str]: ...
    @property
    def role_restricted(self) -> bool: ...


Match = Callable[[RecorderSub], bool]


class Subscriptions(Protocol):
    """`SequencingHub.subscriptions`: the live subscriptions of `ch`."""

    def __call__(self, ch: str) -> Sequence[RecorderSub]: ...


class Publish(Protocol):
    """`SequencingHub.publish`: one delta to the subscriptions `select` accepts."""

    def __call__(
        self,
        ch: str,
        body: Mapping[str, Any] | None = ...,
        *,
        select: Match | None = ...,
        viewer: Callable[[Any], bool] | None = ...,
        wake: bool = ...,
    ) -> int: ...


class Resnapshot(Protocol):
    """`SequencingHub.resnapshot`: a server-initiated resync of what `match` accepts (§7.4)."""

    def __call__(self, match: Match, reason: Literal["upstream_desync"]) -> int: ...


class BodyFactory[B](Protocol):
    """The gateway's snapshot body from a §15.8 payload."""

    def __call__(self, structured: Mapping[str, Any]) -> B: ...


def _row(e: rc.RecordedEntry) -> dict[str, Any]:
    row: dict[str, Any] = {"symbol": e.symbol, "state": e.state, "reason": e.reason}
    row |= {"pinned": e.pinned} | {k: v for k in _PLAIN if (v := getattr(e, k)) is not None}
    if e.lingering is not None:
        row["linger_until_ms"] = None if e.linger_until is None else epoch_ms(e.linger_until)
    if e.last_event_at is not None:
        row["last_event_at_ms"] = epoch_ms(e.last_event_at)
    if e.refusal is not None:
        row["refusal"] = e.refusal
    return row


def _link(c: rc.Connection, restricted: bool) -> dict[str, Any]:
    out = {"state": c.state, "subscribed_topics": c.subscribed_topics}
    out |= {"reconnects_last_hour": c.reconnects_last_hour, "last_ping_ms": c.last_ping_ms}
    return out if restricted else {"endpoint": c.endpoint} | out  # an endpoint holds a path


def frame(
    snapshot: StatusSnapshot, symbols: frozenset[str], restricted: bool
) -> dict[str, Any] | None:
    """The §15.8 frame of `snapshot` for a subscription naming `symbols` (none: all) in the full
    or the restricted view; `None` while no runtime is bound."""
    status = snapshot.status
    if status is None:
        return None
    entries = snapshot.restricted if restricted else status.entries
    rows = {e.symbol: _row(e) for e in entries if not symbols or e.symbol in symbols}
    if not restricted:  # a missing symbol in a restricted frame is unknown, never idle
        rows |= {s: {"symbol": s, "state": "idle"} for s in symbols - rows.keys()}
    out: dict[str, Any] = {"overall": status.overall, "role_restricted": restricted}
    out |= {"connections": [_link(c, restricted) for c in status.connections]}
    out |= {"symbols": [rows[s] for s in sorted(rows)]}
    out |= {"ingest_rate_msgs_per_sec": status.ingest_rate_msgs_per_sec}
    out |= {"write_backlog_rows": status.write_backlog_rows}
    if snapshot.policy is not None:
        out["policy"] = snapshot.policy
    if snapshot.storage is not None:
        out["storage"] = snapshot.storage
    return out


def _group(symbols: frozenset[str], restricted: bool) -> Match:
    def match(sub: RecorderSub) -> bool:
        return sub.symbols == symbols and sub.role_restricted == restricted

    return match


def _any_recorder(sub: RecorderSub) -> bool:
    return sub.ch == RECORDER


def _owner_now(principal: Any) -> bool:
    """A full frame's viewer: the connection's principal as it is now (§9.5) is the Owner."""
    return principal.is_owner is True


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


class RecorderTopic[B]:
    """The `recorder` topic's snapshot source and publisher (see the module docstring), for the
    event loop that runs the gateway and the status cache: no locks."""

    def __init__(
        self,
        subscriptions: Subscriptions,
        publish: Publish,
        resnapshot: Resnapshot,
        body: BodyFactory[B],
    ) -> None:
        self._subscriptions, self._publish = subscriptions, publish
        self._resnapshot, self._body = resnapshot, body
        self._cache: RecordingStatusCache | None = None

    def attach(self, cache: RecordingStatusCache) -> None:
        """Serve `cache`, and publish each status it computes, once. Before, `build` gives
        `None`, so a subscription stays `snapshot_pending` (§7.7)."""
        if self._cache is not None:
            raise ValueError("the recorder topic is already attached")
        self._cache = cache
        cache.listen(self.refreshed)

    # -- SnapshotSource

    def build(self, sub: RecorderSub) -> B | None:
        snapshot = None if self._cache is None else self._cache.snapshot()
        body = None if snapshot is None else frame(snapshot, sub.symbols, sub.role_restricted)
        return None if body is None else self._body(body)

    def generation(self, sub: RecorderSub) -> int:
        return 0  # a private family's snapshot is never cached

    def continuity(self, sub: RecorderSub, from_ts_ms: int | None) -> bool:
        return False  # no delta history: `snapshot: false` is always `snapshot_forced`

    # -- deltas, once a second

    def refreshed(self, snapshot: StatusSnapshot) -> None:
        """Publish `snapshot` to every `recorder` subscription: one whole frame per group."""
        if snapshot.status is None:
            return
        try:
            groups = {(s.symbols, s.role_restricted) for s in self._subscriptions(RECORDER)}
            for symbols, restricted in groups:
                self._publish(
                    RECORDER,
                    frame(snapshot, symbols, restricted),
                    select=_group(symbols, restricted),
                    viewer=None if restricted else _owner_now,
                    wake=True,
                )
        except Exception as exc:  # contained: the topic is a view, the cache goes on
            _log().error("recorder_topic_publish_failed", error=type(exc).__name__)
            try:
                self._resnapshot(_any_recorder, "upstream_desync")
            except Exception as resync:
                _log().error("recorder_topic_resync_failed", error=type(resync).__name__)
