"""Snapshot + delta sequencing, resync and snapshot chunking (E17-S03; `23-ws-protocol.md` §7, §3.3,
§3.6, §6.1.1, §11).

Hot path (C-2.20): plain, allocation-light code; no statechart. One connection has exactly one
writer task (`20-architecture.md` TG5) and every frame for it is queued by `TopicEmitter` from the
event loop, so sequence allocation (`sub.seq += 1`) is a single-writer property, not a lock.

Guarantees (§7.1):

- `s` is per (connection, subscription) and increments by exactly 1 per delivered frame; a `snap`
  consumes one number too, so a resync never reuses or skips one (`meta.previous_seq` = last `s`).
- A `d` is never emitted while the subscription awaits its `snap` (`snapshot_pending`): an upstream
  gap marks every affected subscription pending, so no delta is ever applied across it.
- A snapshot above `MAX_OUTBOUND_FRAME_BYTES` is split into chunks sharing one `id`; only the final
  chunk carries `s`, intermediate ones carry `s: null` (and the CVWB `partial` flag when binary).
- Live and replay subscriptions of the same `ch` are distinct `Subscription`s with distinct
  sequence domains; replay frames carry `rs`, `wt`, `meta.source: "replay"` and the CVWB
  `replay` flag (WS-T09).
- Snapshots are rendered once per (topic, encoding, identity, generation) for public families and
  shared by subscribers; private families are rendered per subscription and never cached (SR-190).

Bounds (C-2.18): the snapshot cache holds at most `SNAPSHOT_CACHE_MAX` entries (oldest evicted);
client resyncs draw on the connection's rebuild budget (SR-193); the upstream guard holds one
int per upstream symbol; heatmap snapshots are capped at `HEATMAP_SNAPSHOT_MAX_COLUMNS` columns.
"""

from __future__ import annotations

import contextlib
import json
import secrets
import time
import uuid
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from decimal import Decimal
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final, Literal, Protocol

import structlog

from candleviewer.auth.generated_permissions import Scope
from candleviewer.observability.metrics import Counter, Gauge, Histogram
from candleviewer.ws._generated.cvwb_layout import HEADER, KINDS
from candleviewer.ws.binary import (
    FLAG_COALESCED,
    FLAG_ESTIMATED,
    FLAG_PARTIAL,
    FLAG_REPLAY,
    Frame,
    FrameEncodeError,
    encode_b64,
)
from candleviewer.ws.errors import build_ws_error
from candleviewer.ws.metrics import SAMPLE_EVERY, SAMPLE_MASK, cv_ws_malformed_updates_total
from candleviewer.ws.rebuild_budget import topic_key
from candleviewer.ws.topics import (
    FAMILIES,
    TopicError,
    is_topic_name,
    machine_refusal,
    parse_replay_session_id,
)

if TYPE_CHECKING:
    from candleviewer.ws.permissions import ConnectionAuthz, Subscription

SnapReason = Literal[
    "initial",
    "client_resync",
    "upstream_desync",
    "upstream_reconnect",
    "backpressure",
    "reconfigure",
    "instrument_revision",
    "replay_seek",
    "generation_swap",
    "history_repair",
]
#: §7.4 closed `meta.reason` set.
SNAP_REASONS: Final[tuple[str, ...]] = (
    "initial",
    "client_resync",
    "upstream_desync",
    "upstream_reconnect",
    "backpressure",
    "reconfigure",
    "instrument_revision",
    "replay_seek",
    "generation_swap",  # bars only: the series' generation changed (§7.4, #2662)
    # bars only: a re-read added or replaced bars the series serves and dropped none (§7.4, #2787)
    "history_repair",
)
#: The reasons `cv_ws_resync_total` counts: every one but `initial`, a routine attach. The one
#: source for both the counting (`TopicEmitter.snapshot`) and the series bound at import.
COUNTED_SNAP_REASONS: Final[tuple[str, ...]] = tuple(r for r in SNAP_REASONS if r != "initial")
#: §7.4: counted as incidents (alert thresholds in `06-performance-and-load-standard.md`).
INCIDENT_REASONS: Final = frozenset({"upstream_desync", "backpressure"})
#: The `meta` keys `TopicEmitter.snapshot` sets. An owning module's `SnapshotBody.meta` may not
#: name one: that is a programming error, refused when the body is built.
SERVER_META_KEYS: Final = frozenset({"reason", "previous_seq", "source"})
#: What a `d`'s `meta` may not name: those, and `stale`, which only a snapshot carries and a `d`
#: never sets or clears (§7.2). A `d` that names it is refused: a raise to the publisher with the
#: backpressure flag off; with it on, the pipeline contains it (the update is dropped and the
#: subscriber re-snapshotted). An owner's `stale` on a body is dropped (`SnapshotBody`).
DELTA_REFUSED_META_KEYS: Final = SERVER_META_KEYS | {"stale"}
#: An owner's `meta` is at most this much JSON, so it can never carry a chunk past its limit.
OWNER_META_MAX_BYTES: Final = 1024
#: §13.6 `resync.reason` (client side).
CLIENT_RESYNC_REASONS: Final = frozenset(
    {"sequence_gap", "decode_error", "state_corrupt", "client_restart", "manual"}
)

MAX_OUTBOUND_FRAME_BYTES: Final = 4 * 1024 * 1024  # §3.6
#: §3.1 `sp`: 8 bytes from the OS CSPRNG as 16 lowercase hex characters, never all zeros.
SPAN_ID_BYTES: Final = 8
_ZERO_SPAN: Final = "0" * (2 * SPAN_ID_BYTES)
#: §3.1 Room: what a frame sized against the cap is sized with in place of an `sp`, sampled or not
#: (24 bytes of JSON text, more than its 20 of MessagePack).
SP_ROOM: Final = "f" * (2 * SPAN_ID_BYTES)
#: Wider than any `s`, `previous_seq`, `ts` or snapshot counter a frame carries (`bars_publish`),
#: and the longest `meta.reason`: the width a snapshot envelope is sized at (`_widest`).
_WIDEST: Final = 2**64
_LONGEST_REASON: Final = max(SNAP_REASONS, key=len)
HEATMAP_SNAPSHOT_MAX_COLUMNS: Final = 2000  # §6.1.1
SNAPSHOT_CACHE_MAX: Final = 4096
#: §16.1 S5: causal order across private topics for one account event.
PRIVATE_CAUSAL_ORDER: Final[tuple[str, ...]] = ("executions", "orders", "positions", "trade_groups")
_CAUSAL_RANK: Final = {fam: i for i, fam in enumerate(PRIVATE_CAUSAL_ORDER)}
#: S4: the families whose updates never wait in a window, the only ones published without a body.
_UNPACED: Final = frozenset(f.family for f in FAMILIES.values() if f.never_throttled)

#: §7.2 universal snapshot fields, restricted to what each family's §14 payload schema declares
#: (`additionalProperties: false`). `source` always travels in `meta.source` (snapMeta); binary
#: frames carry the scales and the `estimated` / `replay` header flags (§3.4).
SNAP_PAYLOAD_FIELDS: Final[Mapping[str, frozenset[str]]] = {
    "book": frozenset({"price_scale", "qty_scale", "stale"}),
    "heatmap": frozenset({"estimated"}),
}
#: Families whose §14 payload declares `coalesced` / `coalesced_count` (§8).
COALESCE_FIELDS: Final = frozenset({"book", "bars", "footprint"})
#: Families whose §14/§15 payload declares them too, set only on a merged frame (a count above 1),
#: so a frame of one update leaves as it always has (#3268). `machines` merges as well, but its
#: §15.10 payload declares neither field and allows no other, so it discloses nothing.
MERGE_DISCLOSED: Final = frozenset({"heatmap", "metrics", "ticker", "positions", "wallet"})

cv_ws_resync_total = Counter(
    "cv_ws_resync_total", "Server-sent re-snapshots by reason.", labelnames=("reason",)
)
# Bind every counted reason now, so each series exists at 0 from process start. A series born at its
# first event is a single sample: `increase()` has nothing to subtract, so the first re-snapshot
# under a reason after every restart goes unseen (#2264 bound the CSRF counter for the same
# reason). `WsUpstreamDesyncHigh` (#571) reads the `upstream_desync` series.
for _resync_reason in COUNTED_SNAP_REASONS:
    cv_ws_resync_total.labels(reason=_resync_reason)
cv_ws_snapshot_bytes = Histogram(
    "cv_ws_snapshot_bytes",
    "Serialized snapshot size (all chunks); the topic label holds the topic family.",
    labelnames=("topic",),
    buckets=(1024, 16384, 131072, 716800, 2097152, 4194304, 16777216),
)
cv_ws_snapshot_build_seconds = Histogram(
    "cv_ws_snapshot_build_seconds",
    "Snapshot build + render time; the topic label holds the topic family.",
    labelnames=("topic",),
    buckets=(0.001, 0.005, 0.025, 0.1, 0.4, 1.5),
)
cv_ws_sequence_gaps_detected_total = Counter(
    "cv_ws_sequence_gaps_detected_total",
    "Client-reported sequence gaps (resync reason sequence_gap); must stay zero.",
)
cv_ws_stale_topics_in_use = Gauge(
    "cv_ws_stale_topics_in_use", "Topics whose last snapshot was stale."
)


def _log() -> Any:
    return structlog.get_logger(__name__)


def _logged_seq(value: object) -> int | None:
    """A client's `last_seq` as a log field: a plain int in [0, 2**53), else None (not logged).
    The schema allows any integer, and the JSON renderer (orjson) raises on one above 64 bits, which
    would lose the whole line, so a value is clamped here rather than at render time."""
    return value if type(value) is int and 0 <= value < 2**53 else None


def _dumps(frame: Mapping[str, Any]) -> str:
    """Same serialization as the gateway writer, so size checks match the wire."""
    return json.dumps(frame, separators=(",", ":"))


def new_span_id() -> str:
    """A §3.1 `sp`, drawn fresh for one frame: never a counter, a seeded PRNG or a value derived
    from an identifier. All zeros (1 in 2**64) is not a valid span id, so it is drawn again."""
    while True:
        span_id = secrets.token_hex(SPAN_ID_BYTES)
        if span_id != _ZERO_SPAN:
            return span_id


# -- snapshot bodies ----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SnapshotBody:
    """State of one topic as built by its owning module. `parts` is the CVWB form (empty when the
    topic has no binary form): one frame for book/trades/bars/footprint, one per column for the
    heatmap (kind 6 is single-column), mirroring `structured["columns"]` column for column, in
    order, as the window after a snapshot reads its complete buckets there (#3268). `meta` holds
    the module's own `snapMeta` keys (bars: `spec_hash`, `build_version`, `include_delta`; §6.1
    as amended by #2595), merged into every chunk's `meta`, and `stale: true` while the `stale`
    flag is set (§7.2, #3202): the flag is that key's only source, so a binary and a structured
    snapshot carry it alike. It is kept as a shallow read-only copy, so its values must be
    immutable."""

    structured: Mapping[str, Any]
    parts: tuple[Frame, ...] = ()
    price_scale: int = 0
    qty_scale: int = 0
    stale: bool = False
    estimated: bool = False
    meta: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # `stale` is the flag's alone: an owner's own key is dropped, not refused, because `replace`
        # re-feeds the frozen `meta`, which holds the key the flag set. It is set again only while
        # the flag is, so the wire agrees with the gauge (§7.2). The guards see the owner's keys
        # alone, so a stale body has the same bound as a healthy one.
        owner = {k: v for k, v in self.meta.items() if k != "stale"}
        clash = SERVER_META_KEYS.intersection(owner)
        if clash:
            raise ValueError(f"snapshot meta keys {sorted(clash)} are set by the server")
        if len(_dumps(owner)) > OWNER_META_MAX_BYTES:
            raise ValueError(f"snapshot meta is over {OWNER_META_MAX_BYTES} bytes")
        flagged = {**owner, "stale": True} if self.stale else owner
        meta = MappingProxyType(flagged)  # a read-only copy: the guard holds for good
        object.__setattr__(self, "meta", meta)


class SnapshotSource(Protocol):
    """Owning modules (book engine, bar builder, order-flow engines, ticker cache, OMS) behind one
    port. `generation` changes whenever the topic's state changes, which keys the shared cache.
    `continuity` proves a `snapshot: false` attach (§7.6): state covering `from_ts_ms` is held and
    no resync occurred since."""

    def build(self, sub: Subscription) -> SnapshotBody | None:
        """`None` while the state is not trustworthy (e.g. book rebuilding after a desync)."""

    def generation(self, sub: Subscription) -> int: ...

    def continuity(self, sub: Subscription, from_ts_ms: int | None) -> bool: ...


@dataclass(frozen=True, slots=True)
class Rendered:
    """A finished snapshot, ready for any subscriber: structured payload or b64 parts, and the
    owner's `meta` that every chunk carries. A heatmap's also keeps what its structured payload
    carries, so the window after it starts from that (`TopicEmitter.on_snapshot`, §8.2): the
    `t_ms` of each complete column and the root fields (`root` is None for any other family). A
    binary client holds the same columns through the parts, which mirror them, and `estimated`;
    kind 6 carries no `max_value`."""

    payload: Mapping[str, Any] | None
    parts: tuple[str, ...]
    stale: bool
    meta: Mapping[str, Any] = field(default_factory=dict)
    complete: tuple[int, ...] = ()
    root: Mapping[str, Any] | None = None


def cap_heatmap(body: SnapshotBody) -> SnapshotBody:
    """§6.1.1: keep only the most recent `HEATMAP_SNAPSHOT_MAX_COLUMNS` columns."""
    cols = body.structured.get("columns")
    structured = body.structured
    if isinstance(cols, list) and len(cols) > HEATMAP_SNAPSHOT_MAX_COLUMNS:
        structured = {**structured, "columns": cols[-HEATMAP_SNAPSHOT_MAX_COLUMNS:]}
    parts = body.parts[-HEATMAP_SNAPSHOT_MAX_COLUMNS:]
    return replace(body, structured=structured, parts=parts)


def structured_payload(family: str, body: SnapshotBody) -> dict[str, Any]:
    allowed = SNAP_PAYLOAD_FIELDS.get(family, frozenset())
    universal = {
        "price_scale": body.price_scale,
        "qty_scale": body.qty_scale,
        "stale": body.stale,
        "estimated": body.estimated,
    }
    return {**body.structured, **{k: v for k, v in universal.items() if k in allowed}}


def _flags(body: SnapshotBody, replay: bool) -> int:
    return (FLAG_ESTIMATED if body.estimated else 0) | (FLAG_REPLAY if replay else 0)


def _heatmap_held(body: SnapshotBody) -> tuple[tuple[int, ...], dict[str, Any]]:
    """What a heatmap snapshot's structured payload carries (§8.2): the `t_ms` of each complete
    column, and the root fields (`structured_payload`). Parts that do not mirror the columns one
    for one (`SnapshotBody`) seed nothing. Never raises: a column it cannot read is left out."""
    cols = body.structured.get("columns")
    columns = cols if isinstance(cols, list) else []
    if body.parts and len(body.parts) != len(columns):
        return (), {}
    complete = tuple(
        col["t_ms"]
        for col in columns
        if isinstance(col, Mapping) and col.get("complete") is True and type(col.get("t_ms")) is int
    )
    payload = structured_payload("heatmap", body)
    return complete, {k: v for k, v in payload.items() if k != "columns"}


def render(sub: Subscription, body: SnapshotBody, max_part_bytes: int) -> Rendered:
    fam = sub.topic.family.family
    complete: tuple[int, ...] = ()
    root: dict[str, Any] | None = None
    if fam == "heatmap":
        body = cap_heatmap(body)
        complete, root = _heatmap_held(body)
    binary = sub.effective.get("encoding") == "binary" and bool(body.parts)
    if not binary:
        return Rendered(structured_payload(fam, body), (), body.stale, body.meta, complete, root)
    if body.meta:  # `snapshot` sized the budget without the owner's keys, which every chunk carries
        max_part_bytes -= len(_dumps(dict(body.meta)))
    flags = _flags(body, sub.replay_session_id is not None)
    frames: list[Frame] = []
    for part in body.parts:
        scaled = replace(
            part, flags=part.flags | flags, price_scale=body.price_scale, qty_scale=body.qty_scale
        )
        frames.extend(split_frame(scaled, max_part_bytes))
    last = len(frames) - 1
    out = tuple(  # weight 1: a snapshot is rare, so every chunk is timed and sized
        encode_b64(f if i == last else replace(f, flags=f.flags | FLAG_PARTIAL), 1)
        for i, f in enumerate(frames)
    )
    return Rendered(None, out, body.stale, body.meta, complete, root)


# -- chunking ------------------------------------------------------------------------------------


def split_frame(frame: Frame, max_bytes: int) -> list[Frame]:
    """Split one CVWB frame into frames of at most `max_bytes` encoded bytes, at record / group
    boundaries (each chunk is a valid frame; header and trailer repeat). A single record, group or
    heatmap column larger than `max_bytes` cannot be split and raises `FrameEncodeError`."""
    kind = KINDS[frame.body_kind]
    fixed = HEADER.size + (kind.trailer.size if kind.trailer is not None else 0)
    if kind.group_prefix is not None:
        gp = kind.group_prefix.size
        units: Sequence[Any] = frame.groups or ()
        sizes = [gp + len(cells) * kind.record.size for _, cells in units]
    elif kind.body_prefix is not None:  # heatmap: one column per frame, indivisible
        size = fixed + kind.body_prefix.size + len(frame.records) * kind.record.size
        if size > max_bytes:
            raise FrameEncodeError(f"{kind.name}: one column exceeds the frame budget")
        return [frame]
    else:
        units = frame.records
        sizes = [kind.record.size] * len(units)
    if fixed + sum(sizes) <= max_bytes:
        return [frame]
    chunks: list[list[Any]] = [[]]
    used = fixed
    for unit, size in zip(units, sizes, strict=True):
        if fixed + size > max_bytes:
            raise FrameEncodeError(f"{kind.name}: one unit exceeds the frame budget")
        if used + size > max_bytes:
            chunks.append([])
            used = fixed
        chunks[-1].append(unit)
        used += size
    if kind.group_prefix is not None:
        return [replace(frame, groups=tuple(c)) for c in chunks]
    return [replace(frame, records=tuple(c)) for c in chunks]


def b64_budget(frame_limit: int, envelope_overhead: int) -> int:
    """Largest raw CVWB size whose base64 form fits `frame_limit` with the envelope around it."""
    return max(0, (frame_limit - envelope_overhead) // 4 * 3)


def _overhead(env: Mapping[str, Any]) -> int:
    """What a chunk's envelope adds to its `p`, as JSON, with room for `sp` (§3.1), plus slack."""
    return len(_dumps({**env, "e": "b64", "p": "", "sp": SP_ROOM})) + 8


def _widest(sub: Subscription) -> int:
    """`_overhead` of the widest `snap` envelope on `sub`'s `ch` and replay session: every other
    field at its widest, so a cut sized with it fits every subscriber's envelope."""
    env: dict[str, Any] = {"t": "snap", "id": f"snap-{_WIDEST}", "ch": sub.ch}
    env |= {"s": _WIDEST, "ts": _WIDEST}
    if sub.replay_session_id is not None:
        env |= {"rs": sub.replay_session_id, "wt": _WIDEST}
    source = "live" if sub.replay_session_id is None else "replay"
    env["meta"] = {"reason": _LONGEST_REASON, "source": source, "previous_seq": _WIDEST}
    return _overhead(env)


def split_structured(payload: Mapping[str, Any], budget: int) -> list[dict[str, Any]]:
    """Split a structured payload across chunks whose JSON is at most `budget` bytes. Scalars repeat
    in every chunk; list fields are sliced in key order and every chunk carries every list key
    (possibly empty), so required fields stay present and validation holds per chunk."""
    whole = dict(payload)
    if len(_dumps(whole)) <= budget:
        return [whole]
    lists = [k for k, v in whole.items() if isinstance(v, list)]
    base = {k: ([] if k in lists else v) for k, v in whole.items()}
    base_size = len(_dumps(base))
    chunks: list[dict[str, Any]] = [{**base, **{k: [] for k in lists}}]
    used = base_size
    for key in lists:
        for item in whole[key]:
            size = len(_dumps({"x": [item]})) - len('{"x":[]}') + 1  # item + comma
            if base_size + size > budget:
                raise FrameEncodeError("one structured item exceeds the frame budget")
            if used + size > budget:
                chunks.append({**base, **{k: [] for k in lists}})
                used = base_size
            chunks[-1][key].append(item)
            used += size
    return chunks


# -- shared snapshot cache -----------------------------------------------------------------------


class SnapshotCache:
    """One rendered snapshot per (topic, replay session, encoding, identity), refreshed when the
    source's `generation` moves: cost is per topic, not per subscriber (snapshot amplification,
    WS-D03). Private families never enter it (SR-190)."""

    def __init__(self, maxsize: int = SNAPSHOT_CACHE_MAX) -> None:
        self.maxsize = maxsize
        self._entries: dict[tuple[Any, ...], tuple[int, Rendered]] = {}
        self._stale: set[str] = set()
        self.builds = 0

    def __len__(self) -> int:
        return len(self._entries)

    def invalidate(self, ch: str) -> None:
        """Forget every rendered snapshot of `ch`: after a server-initiated resync the cached
        state predates the incident and must never be served again."""
        for key in [k for k in self._entries if k[0] == ch]:
            del self._entries[key]

    def get(
        self,
        sub: Subscription,
        source: SnapshotSource,
        max_part_bytes: int,
    ) -> Rendered | None:
        fam = sub.topic.family
        if fam.private:
            rendered = self._build(sub, source, max_part_bytes)
        else:
            # `paused` gates deltas, not the rendered state (#2517): it never splits the cache.
            identity = tuple(
                sorted((k, repr(v)) for k, v in sub.effective.items() if k != "paused")
            )
            key = (sub.ch, sub.replay_session_id, identity)
            gen = source.generation(sub)
            hit = self._entries.get(key)
            if hit is not None and hit[0] == gen:
                rendered = hit[1]
            else:
                rendered = self._build(sub, source, max_part_bytes)
                if rendered is None:
                    return None
                self._entries.pop(key, None)
                while len(self._entries) >= self.maxsize:
                    del self._entries[next(iter(self._entries))]
                self._entries[key] = (gen, rendered)
        if rendered is not None:
            self._mark_stale(sub.ch, rendered.stale)
        return rendered

    def _build(
        self, sub: Subscription, source: SnapshotSource, max_part_bytes: int
    ) -> Rendered | None:
        fam = sub.topic.family.family
        start = time.perf_counter()
        body = source.build(sub)
        if body is None:
            return None
        rendered = render(sub, body, max_part_bytes)
        cv_ws_snapshot_build_seconds.labels(topic=fam).observe(time.perf_counter() - start)
        self.builds += 1
        return rendered

    def _mark_stale(self, ch: str, stale: bool) -> None:
        if stale:
            self._stale.add(ch)
        else:
            self._stale.discard(ch)
        cv_ws_stale_topics_in_use.set(len(self._stale))


# -- upstream book sequence guard ----------------------------------------------------------------

UpstreamVerdict = Literal["apply", "drop", "desync"]


class UpstreamBookGuard:
    """Upstream book update-id (`u`) continuity per symbol (§7.4 trigger 1; the feed has no
    checksum, so any doubt means drop-and-rebuild). `snapshot` resets the baseline; a delta with
    `u == last + 1` applies; a duplicate or late (`u <= last`) delta is dropped; a gap desyncs
    until the next snapshot."""

    def __init__(self) -> None:
        self._last: dict[str, int | None] = {}

    def observe(self, symbol: str, u: int, *, snapshot: bool) -> UpstreamVerdict:
        if snapshot:
            self._last[symbol] = u
            return "apply"
        last = self._last.get(symbol)
        if last is None:
            return "drop"  # desynced (or never synced): wait for the rebuild snapshot
        if u <= last:
            return "drop"
        if u != last + 1:
            self._last[symbol] = None
            return "desync"
        self._last[symbol] = u
        return "apply"

    def forget(self, symbol: str) -> None:
        self._last.pop(symbol, None)


# -- per-connection emitter ----------------------------------------------------------------------


class TopicEmitter:
    """Emits `snap` / `d` for one connection, allocating sequence numbers on the event loop (the
    connection's single writer drains the queue in order).

    One data frame of a subscription in `SAMPLE_EVERY` (the one whose `s` is a multiple of it)
    leaves with the `clock` reading at which the hub took it (`push_data`), so the writer can
    observe `cv_ws_fanout_seconds` (budget #6, weighted) once the socket has it. That stamp also
    picks the frames the cost series observe: the encoder times and sizes a stamped binary delta
    (`cv_ws_frame_*{kind}`, weighted; a snapshot chunk is observed exactly) and the writer the
    stamped frame it encodes (`kind` `json` / `msgpack`). The others leave with none, and the hub
    reads no clock for them. `clock` must be the clock the writer reads; the gateway passes the
    connection's own.

    A stamped frame also carries `sp` (§3.1), drawn from `span_id` for it alone (None while
    latency telemetry is off): in a chunked snapshot, the final chunk, the one with `s`. Every
    chunk is cut with room for one (`SP_ROOM`), whether or not it is sampled."""

    def __init__(
        self,
        push: Callable[[dict[str, Any]], None],
        *,
        connection_id: str,
        wall_ms: Callable[[], int],
        clock: Callable[[], float],
        source: SnapshotSource | None = None,
        cache: SnapshotCache | None = None,
        max_frame_bytes: int = MAX_OUTBOUND_FRAME_BYTES,
        push_data: Callable[[dict[str, Any], float | None], None] | None = None,
        span_id: Callable[[], str] | None = None,
    ) -> None:
        self.push = push
        #: Where a sampled data frame goes, with its receipt time. None: through `push`, without
        #: it, like every other frame.
        self.push_data = push_data
        #: Draws the `sp` of each frame that goes to `push_data` (§3.1); None: no frame has one.
        self.span_id = span_id
        self.connection_id = connection_id
        self.wall_ms = wall_ms
        self.clock = clock
        self.source = source
        self.cache = cache if cache is not None else SnapshotCache()
        self.max_frame_bytes = max_frame_bytes
        self._snap_ids = 0
        #: E17-T03: the overflow ladder's hook. A hub `flush_pending` (a source rebuild) hands it
        #: the subscriptions it named, so a `backpressure` snapshot parked as not ready is retried.
        self.on_rebuild: Callable[[list[Subscription]], None] | None = None
        #: E17-T03: told of each `snap` once its frames are queued, with what it rendered, so the
        #: pacer's window after it starts from that (`Pacer.snapshotted`, #3268). None: flag off.
        self.on_snapshot: Callable[[Subscription, Rendered], None] | None = None

    # -- snapshots --

    def snapshot(self, sub: Subscription, reason: SnapReason) -> bool:
        """Emit a (possibly chunked) `snap`; False when the state cannot be built yet, or before
        the subscription's `sub_ok` is queued (#2831): it stays pending and no `d` is emitted
        until a later flush succeeds. Nothing once it has ended (§8.4 Lanes, defence in depth).
        Once its frames are queued, `on_snapshot` is told."""
        if self.source is None or not sub.announced or sub.ended:
            return False
        previous = sub.seq
        seq = previous + 1
        # The fan-out span starts before the build; a sampled `s` is stamped on its chunk only.
        received = None if seq & SAMPLE_MASK else self.clock()
        meta: dict[str, Any] = {
            "reason": reason,
            "source": "live" if sub.replay_session_id is None else "replay",
        }
        if previous:
            meta["previous_seq"] = previous
        self._snap_ids += 1
        snap_id = f"snap-{self._snap_ids}"
        now = self.wall_ms()
        base: dict[str, Any] = {"t": "snap", "id": snap_id, "ch": sub.ch, "s": seq, "ts": now}
        if sub.replay_session_id is not None:
            base |= {"rs": sub.replay_session_id, "wt": now}
        base["meta"] = meta
        # Sized so that no frame, `sp` included, exceeds the cap (§3.1 Room, §3.6).
        budget = b64_budget(self.max_frame_bytes, _widest(sub))
        rendered = self.cache.get(sub, self.source, budget)
        if rendered is None:
            return False
        if rendered.meta:  # the owner's keys join the server's, which win (`SERVER_META_KEYS`)
            owner = {k: v for k, v in rendered.meta.items() if k not in SERVER_META_KEYS}
            base["meta"] = {**owner, **meta}
        frames = self._frames(base, rendered)
        sub.seq, sub.snapshot_pending = seq, False
        total = 0
        for frame in frames:
            total += len(_dumps(frame))
            if received is None or self.push_data is None or frame["s"] is None:
                self.push(frame)
            else:
                if self.span_id is not None:  # the chunk with `s` names its fan-out span
                    frame["sp"] = self.span_id()
                self.push_data(frame, received)
        fam = sub.topic.family.family
        cv_ws_snapshot_bytes.labels(topic=fam).observe(total)
        if reason in COUNTED_SNAP_REASONS:
            cv_ws_resync_total.labels(reason=reason).inc()
            fields = {
                "connection_id": self.connection_id,
                "ch": sub.ch,
                "reason": reason,
                "previous_seq": previous,
            }
            if sub.replay_session_id is not None:  # a replay stream and its live twin share a `ch`
                fields["rs"] = sub.replay_session_id  # canonical, the server's own
            # 23 §7.4's incidents, `upstream_desync` and `backpressure`, log at warning.
            if reason in INCIDENT_REASONS:
                _log().warning("ws resync", **fields)
            else:
                _log().info("ws resync", **fields)
        if self.on_snapshot is not None:
            self.on_snapshot(sub, rendered)
        return True

    def _frames(self, base: dict[str, Any], rendered: Rendered) -> list[dict[str, Any]]:
        if rendered.payload is not None:  # split per subscriber, for its own envelope
            budget = self.max_frame_bytes - _overhead(base)
            payloads: list[Any] = split_structured(rendered.payload, budget)
            enc = "j"
        else:
            payloads = list(rendered.parts)
            enc = "b64"
        last = len(payloads) - 1
        out: list[dict[str, Any]] = []
        for i, p in enumerate(payloads):
            frame = {**base, "e": enc, "p": p}
            if i != last:
                frame["s"] = None
            if last == 0:
                del frame["id"]  # a single-frame snap needs no chunk correlation id
            out.append(frame)
        return out

    # -- deltas --

    def delta(
        self,
        sub: Subscription,
        body: Mapping[str, Any] | None = None,
        *,
        part: Frame | None = None,
        coalesced_count: int = 1,
        ts_ms: int | None = None,
        meta: Mapping[str, Any] | None = None,
    ) -> bool:
        """Emit one `d` consuming exactly one sequence number. Suppressed (False) while the
        subscription awaits its `snap` or is paused, so no delta crosses a gap (§7.1). A frame whose
        `s` is a multiple of `SAMPLE_EVERY` is stamped with the clock now (a paced frame at its
        release, not at its source update), and a stamped binary delta is also encoded with that
        weight (timed and sized by `cv_ws_frame_*`); the others read no clock and no timer. `meta`
        rides on the envelope (bars: the §6.1 `include_delta` echo) and may not name a key the
        server owns, or `stale` (§7.2). Suppressed too once the subscription has ended, as a
        `snap` is."""
        if meta and DELTA_REFUSED_META_KEYS.intersection(meta):  # a programming error, as on a snap
            raise ValueError("delta meta may not name a server-owned key")
        if sub.snapshot_pending or sub.effective.get("paused") is True or sub.ended:
            return False
        sub.seq += 1
        received = None if sub.seq & SAMPLE_MASK else self.clock()
        now = self.wall_ms()
        frame: dict[str, Any] = {"t": "d", "ch": sub.ch, "s": sub.seq}
        frame["ts"] = ts_ms if ts_ms is not None and sub.replay_session_id is not None else now
        if sub.replay_session_id is not None:
            frame |= {"rs": sub.replay_session_id, "wt": now}
        if meta:
            frame["meta"] = dict(meta)
        fam = sub.topic.family.family
        if part is not None and sub.effective.get("encoding") == "binary":
            flags = part.flags | (FLAG_REPLAY if sub.replay_session_id is not None else 0)
            if coalesced_count > 1:
                flags |= FLAG_COALESCED
            weight = 0 if received is None else SAMPLE_EVERY  # the stamped delta is timed too
            frame |= {"e": "b64", "p": encode_b64(replace(part, flags=flags), weight)}
        else:
            p = dict(body or {})  # a fresh dict per subscription: no shared private buffers
            if fam in COALESCE_FIELDS or (coalesced_count > 1 and fam in MERGE_DISCLOSED):
                p["coalesced"] = coalesced_count > 1
                if coalesced_count > 1:
                    p["coalesced_count"] = coalesced_count
            frame |= {"e": "j", "p": p}
        if received is None or self.push_data is None:
            self.push(frame)
        else:
            if self.span_id is not None:  # the stamped frame names its fan-out span (§3.1)
                frame["sp"] = self.span_id()
            self.push_data(frame, received)
        return True

    # -- client resync (§7.5) --

    def client_resync(
        self, authz: ConnectionAuthz, frame: Mapping[str, Any]
    ) -> dict[str, Any] | None:
        """One client `resync` (§7.5). Returns the `revoked` frame when the rate limit revoked the
        subscription, which the caller audits (SR-187, #2174), else `None`."""
        fid = frame.get("id")
        rid = fid if isinstance(fid, str) else None
        ch = frame.get("ch")
        body = frame.get("p")
        if ch is not None and not is_topic_name(ch):
            # #2572: never echoed (§13.1: the envelope `ch` is a topic name); no `ch`: §7.7, below
            err = build_ws_error(
                "invalid_options", id=rid, message="ch must be a topic name.", field="ch"
            )
            self.push(err)
            return None
        if not isinstance(ch, str) or not isinstance(body, dict):
            self.push(build_ws_error("frame_malformed", id=rid))
            return None
        rs = parse_replay_session_id(frame.get("rs"))  # §7.5: on each `err` below, when a uuid
        reason = body.get("reason")
        last_seq = body.get("last_seq")
        if (
            not isinstance(reason, str)
            or reason not in CLIENT_RESYNC_REASONS
            or not (
                last_seq is None or (isinstance(last_seq, int) and not isinstance(last_seq, bool))
            )
        ):
            self.push(build_ws_error("frame_malformed", id=rid, ch=ch, rs=rs))
            return None
        try:  # §7.5 (#3218): the subscription of `ch` in the `rs` session, else the live one
            sub = authz.named(ch, frame.get("rs"), body.get("sub_id"))
        except TopicError as exc:  # a malformed `rs`, then `sub_id`: never echoed
            err = build_ws_error(
                exc.code, id=rid, ch=ch, rs=rs, message=exc.message, field=exc.field
            )
            self.push(err)
            return None
        if sub is None:  # none of `ch` in that session, or the `sub_id` pin is not its own
            self.push(build_ws_error("not_subscribed", id=rid, ch=ch, rs=rs))
            return None
        if reason == "sequence_gap":
            cv_ws_sequence_gaps_detected_total.inc()
        # What the client says beside what the server numbered: a gap is one side's bug.
        fields: dict[str, Any] = {
            "connection_id": self.connection_id,
            "ch": sub.ch,
            "client_reason": reason,
            "server_seq": sub.seq,
        }
        if sub.replay_session_id is not None:  # a replay stream shares its `ch` with its live twin
            fields["rs"] = sub.replay_session_id  # canonical, the server's own: never the frame's
        if (seen := _logged_seq(last_seq)) is not None:
            fields["client_last_seq"] = seen
        # Of a client's reasons only `sequence_gap` is an incident (23 §7.1); §7.4 names no other.
        if reason == "sequence_gap":
            _log().warning("ws client resync", **fields)
        else:
            _log().info("ws client resync", **fields)
        budget, key = authz.rebuilds, topic_key(sub.topic, sub.replay_session_id)
        if (scope := budget.take(key, "resync")) is not None:
            budget.log(
                "resync",
                scope,
                self.connection_id,
                sub.ch,
                rs=sub.replay_session_id,
                client_reason=reason,
            )
            spent = budget.count_refusal("resync", scope, key)
            if budget.drawn(key, "resync") < budget.limits["topic"]:  # spent by `ctl`/`sub` too
                message = f"{spent}; no snapshot was taken."
                err = build_ws_error("resync_rate_limited", id=rid, ch=ch, rs=rs, message=message)
                self.push(err)
                return None  # the subscription continues (§7.5)
            self.push(build_ws_error("resync_rate_limited", id=rid, ch=ch, rs=rs))
            revoked = authz.revoke(sub, "resync_rate_limited", self.wall_ms())
            self.push(revoked)
            return revoked
        if _held(sub):
            return None  # counted in the window above; the ladder's `drain` sends that `snap`
        sub.snapshot_pending, sub.pending_reason = True, "client_resync"
        self.snapshot(sub, "client_resync")
        return None

    def flush_pending(self, subs: Iterable[Subscription]) -> int:
        """Snapshot every pending subscription with its recorded reason, except one held for its
        `backpressure` snapshot (`_held`); returns the count."""
        n = 0
        for sub in subs:
            if sub.snapshot_pending and not _held(sub) and self.snapshot(sub, sub.pending_reason):
                n += 1
        return n


#: Pending reasons that `resnapshot` never replaces, not even with `upstream_desync` (#2831): an
#: attach is no resync, and the overflow ladder owns its `backpressure` hold.
_NEVER_REPLACED: Final = frozenset({"initial", "backpressure"})


def _held(sub: Subscription) -> bool:
    """Pending its `backpressure` snapshot. The overflow ladder pends it and only its `drain`
    sends it (`ws/outbound.py`, §8.4 step 2), so every other path leaves it pending (#2831)."""
    return sub.snapshot_pending and sub.pending_reason == "backpressure"


def _refuse_bodyless(ch: str, body: Mapping[str, Any] | None) -> None:
    """A paced family's update carries its structured body, a CVWB part only beside it: a window
    merges structured bodies (§8.2, #3268). One without is refused, whatever the flag."""
    if body is None and (family := ch.split(".", 1)[0]) not in _UNPACED:
        raise ValueError(f"a {family} publish needs its structured body")


def causal_sort(items: Iterable[tuple[str, Any]]) -> list[tuple[str, Any]]:
    """Stable sort of one account event's private frames into executions -> orders -> positions ->
    trade_groups (§16.1 S5); other topics keep their relative order after them."""
    return sorted(items, key=lambda it: _CAUSAL_RANK.get(it[0].split(".", 1)[0], len(_CAUSAL_RANK)))


def in_scope(
    authz: ConnectionAuthz, sub: Subscription, account: uuid.UUID | None, user: uuid.UUID | None
) -> bool:
    """Whether an event reaches `sub`, by its family's scope (§6.2, #2398). A private family
    reaches a subscription only while the connection's principal holds the family's
    permission. Re-evaluation swaps the principal in before it removes anything (§9.5), so this
    holds even if the removal stops part-way. Then: a family scoped to accounts needs the
    event's account among the subscription's; a SELF family (`alerts`) reaches only the
    connections of the user the event belongs to, and nobody when the event names none; a NONE
    family (`recorder`) reaches every subscription. A `machines` subscription is matched by its
    entity: its kind's whole §6.4 row, applied to the scope stored on it at `sub` (no lookup)."""
    family = sub.topic.family
    if not family.private:
        return True
    if sub.topic.entity_kind is not None:  # §6.4: the whole row, on the scope stored at `sub`
        return machine_refusal(authz.principal, sub.topic.entity_kind, sub.entity) is None
    if family.permission not in authz.principal.permissions:
        return False
    if family.scope is Scope.SELF:
        return user is not None and authz.principal.user_id == user
    if family.scope is Scope.NONE:
        return True
    return account is not None and account in sub.accounts


# -- process-wide fan-out ------------------------------------------------------------------------


class Sink(Protocol):
    """One connection's frames from the hub: its `TopicEmitter`, or with the flag on its
    `ConnectionPipeline`, which paces the deltas (§8.1) and never raises into the fan-out."""

    @property
    def cache(self) -> SnapshotCache: ...

    @property
    def on_rebuild(self) -> Callable[[list[Subscription]], None] | None: ...

    def delta(
        self,
        sub: Subscription,
        body: Mapping[str, Any] | None = None,
        *,
        part: Frame | None = None,
        coalesced_count: int = 1,
        ts_ms: int | None = None,
        meta: Mapping[str, Any] | None = None,
    ) -> bool: ...

    def snapshot(self, sub: Subscription, reason: SnapReason) -> bool: ...

    def flush_pending(self, subs: Iterable[Subscription]) -> int: ...


#: The hub logs a failure it contains (`SequencingHub._log_failed`) at most once per (event, family)
#: in this many seconds, `orders` and `executions` aside: the flag-on default classify interval.
FAILURE_LOG_INTERVAL_S: Final = 1.0


class SequencingHub:
    """Routes owning-module events to every live connection's `Sink` (E17-S03 side of
    the fan-out; coalescing and the overflow ladder are E17-T03). Bounded by the gateway's
    connection caps: one entry per authenticated socket. What a sink's `snapshot`, `flush_pending`
    or `delta`, or its `on_rebuild`, raises is contained to its subscription (to its connection
    for `on_rebuild`), so no connection stops a fan-out (§10.1): the flag-on sink contains it
    itself, and the hub contains what a `TopicEmitter` lets through (flag off: `_snapshot_failed`,
    `_delta_failed`, which a waking publish follows with that `snap` at once). A cancellation is
    never contained, nor, flag off, a `d` whose `meta` names a key the server owns: that is the
    caller's own error. `clock` paces the failure lines."""

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._conns: dict[int, tuple[ConnectionAuthz, Sink]] = {}
        self._clock = clock
        #: `_quiet`, per (event, family): when its interval ends, and the lines held back in it.
        self._log_window: dict[tuple[str, str], tuple[float, int]] = {}

    def __len__(self) -> int:
        return len(self._conns)

    def register(self, authz: ConnectionAuthz, emitter: Sink) -> None:
        self._conns[id(authz)] = (authz, emitter)

    def unregister(self, authz: ConnectionAuthz) -> None:
        self._conns.pop(id(authz), None)

    def subscriptions(self, ch: str, replay_session_id: str | None = None) -> list[Subscription]:
        """The live (or one replay session's) subscriptions of `ch`, before `publish`'s scope and
        state filters: a publisher encodes only the CVWB variants they need, beside the structured
        body every paced publish carries (§8.2)."""
        subs = (authz.find(ch, replay_session_id) for authz, _ in self._conns.values())
        return [sub for sub in subs if sub is not None]

    def publish(
        self,
        ch: str,
        body: Mapping[str, Any] | None = None,
        *,
        part: Frame | None = None,
        coalesced_count: int = 1,
        account: uuid.UUID | None = None,
        user: uuid.UUID | None = None,
        replay_session_id: str | None = None,
        ts_ms: int | None = None,
        meta: Mapping[str, Any] | None = None,
        select: Callable[[Subscription], bool] | None = None,
        wake: bool = False,
    ) -> int:
        """One delta for `ch` (live, or one replay session) to every subscription in its scope:
        `account` for account-scoped private families, `user` (the owner) for SELF ones. With
        `select`, only the subscriptions it accepts, asked after the scope check: a publisher
        sends one variant per group. `select` must be pure and total: a raise stops the fan-out
        part-way. With `wake` (the source already holds `body`, §6.4), a subscription still
        pending its `snap` gets that `snap` instead of the `d`: the publish wakes it. A paced
        family (any but `orders` and `executions`, S4) needs `body`, a CVWB `part` only beside it:
        a window merges structured bodies (§8.2), so one without is refused before the fan-out,
        whatever the flag (`ValueError`, #3268)."""
        _refuse_bodyless(ch, body)
        sent = 0
        for authz, emitter in list(self._conns.values()):
            sub = authz.find(ch, replay_session_id)
            if sub is None or not in_scope(authz, sub, account, user):
                continue
            if select is not None and not select(sub):
                continue
            if wake and sub.snapshot_pending:
                try:
                    sent += emitter.flush_pending((sub,))
                except Exception as exc:  # contained to `sub`: the fan-out goes on
                    self._snapshot_failed(authz, sub, exc)
                continue
            try:
                if emitter.delta(
                    sub, body, part=part, coalesced_count=coalesced_count, ts_ms=ts_ms, meta=meta
                ):
                    sent += 1
            except Exception as exc:  # contained to `sub`: the others still get this `d`
                if meta and DELTA_REFUSED_META_KEYS.intersection(meta):
                    raise  # the caller's own error, refused before any `s` was taken
                self._delta_failed(authz, sub, exc)
                if wake:  # the source holds `body`: its `snap` goes out now, as a woken one does
                    try:
                        sent += emitter.flush_pending((sub,))
                    except Exception as snap_exc:  # contained to `sub`: the fan-out goes on
                        self._snapshot_failed(authz, sub, snap_exc)
        return sent

    def publish_private(self, account: uuid.UUID, frames: Iterable[tuple[str, Any]]) -> int:
        """One account event spanning several private topics, in §16.1 S5 causal order. The
        whole event is checked first: a paced frame without its body refuses it before any of its
        frames is published (`ValueError`, #3268)."""
        ordered = causal_sort(frames)
        for ch, body in ordered:
            _refuse_bodyless(ch, body)
        sent = 0
        for ch, body in ordered:
            sent += self.publish(ch, body, account=account)
        return sent

    def resnapshot(self, match: Callable[[Subscription], bool], reason: SnapReason) -> int:
        """Server-initiated resync (§7.4): mark every matching subscription pending FIRST (so no
        delta can slip across the gap), then emit the snapshots. A reason already pending stays,
        as under `ctl`, with one exception: `upstream_desync`, an incident, replaces any but
        `initial` (an attach is no resync) and `backpressure` (the ladder's hold), so a mundane
        reason never hides it. One held for its `backpressure` snapshot (`_held`) is only
        invalidated: the ladder sends it (#2831). A build that raises is contained to its
        subscription, so the fan-out goes on (§10.1, #3262): the flag-on sink handles it as it
        does a flushed snapshot's, and one the sink lets through (flag off) stays pending with its
        reason, for the next `flush_pending` (`_snapshot_failed`)."""
        if reason not in SNAP_REASONS:
            raise ValueError(f"unknown snap reason {reason!r}")
        if reason == "backpressure":  # the ladder pends these, so its `drain` knows them all
            raise ValueError("only the overflow ladder pends a backpressure snapshot")
        hits: list[tuple[ConnectionAuthz, Sink, Subscription]] = []
        for authz, emitter in list(self._conns.values()):
            for sub in list(authz.by_id.values()):
                if match(sub):
                    if not sub.snapshot_pending or (
                        reason == "upstream_desync" and sub.pending_reason not in _NEVER_REPLACED
                    ):
                        sub.pending_reason = reason
                    sub.snapshot_pending = True
                    hits.append((authz, emitter, sub))
        for _, emitter, sub in hits:
            emitter.cache.invalidate(sub.ch)
        sent = 0
        for authz, emitter, sub in hits:
            if _held(sub):
                continue
            try:
                if emitter.snapshot(sub, sub.pending_reason):
                    sent += 1
            except Exception as exc:  # contained to `sub`: the fan-out goes on
                self._snapshot_failed(authz, sub, exc)
        return sent

    def flush_pending(self, match: Callable[[Subscription], bool] | None = None) -> int:
        """Retry every pending snapshot (e.g. once the book engine finished its rebuild), or
        only those of the subscriptions `match` accepts. `match` is asked for every subscription
        of every connection, so it must be pure and total. One held for its `backpressure`
        snapshot is left to the overflow ladder, which the emitter's `on_rebuild` tells. Each
        subscription is flushed alone, as `ConnectionPipeline.flush_pending` does: a build that
        raises through the sink (flag off) leaves it pending with its reason (`_snapshot_failed`),
        and the rest, and every connection's `on_rebuild` (guarded too), still run (#3363)."""
        sent = 0
        for authz, emitter in list(self._conns.values()):
            subs = [s for s in authz.by_id.values() if match is None or match(s)]
            for sub in subs:
                try:
                    sent += emitter.flush_pending((sub,))
                except Exception as exc:  # contained to `sub`: the fan-out goes on
                    self._snapshot_failed(authz, sub, exc)
            if emitter.on_rebuild is not None:
                try:
                    emitter.on_rebuild(subs)
                except Exception as exc:  # contained to its connection: the fan-out goes on
                    self._log_failed("rebuild", authz, None, exc)
        return sent

    # -- the §7.4 triggers --
    # `reconfigure` comes from `ctl`, and `backpressure` snapshots belong to the overflow
    # ladder's `drain` (`ws/outbound.py`), so the hub has no trigger for either (#2830).

    def upstream_desync(self, symbol: str) -> int:
        return self.resnapshot(_live_symbol(symbol, book_only=True), "upstream_desync")

    def upstream_reconnect(self, symbol: str) -> int:
        return self.resnapshot(_live_symbol(symbol, book_only=False), "upstream_reconnect")

    def instrument_revision(self, symbol: str) -> int:
        return self.resnapshot(lambda s: symbol in s.symbols, "instrument_revision")

    def replay_seek(self, replay_session_id: str) -> int:
        return self.resnapshot(lambda s: s.replay_session_id == replay_session_id, "replay_seek")

    # -- containment (§10.1; #3262, #3363) --

    def _snapshot_failed(self, authz: ConnectionAuthz, sub: Subscription, exc: Exception) -> None:
        """A snapshot (a re-snapshot, a flush or a wake) that raised through its sink (flag off,
        `TopicEmitter`, which has no close path): `sub` stays pending with its reason for the next
        flush (§7.1). Marked again: `TopicEmitter.snapshot` clears the mark before it queues its
        frames, so a raise there must not leave a `d` to follow a `snap` its client may lack."""
        sub.snapshot_pending = True
        self._log_failed("snapshot", authz, sub, exc)

    def _delta_failed(self, authz: ConnectionAuthz, sub: Subscription, exc: Exception) -> None:
        """A `d` that raised through its sink (flag off): `TopicEmitter` queues a `d` last, so that
        update never reached `sub`'s client, though its `s` may be taken, as by a frame lost in
        transit (§7.1). `sub` now awaits an `upstream_desync` `snap`, the §7.4 reason for a stream
        with a gap ("the only correct recovery is drop-and-rebuild"), so no `d` crosses the gap; a
        waking `publish` sends that `snap` at once, any other waits for the next flush. One already
        pending keeps its reason, as it took no `d`. Marked first, which its count and log line
        cannot skip; counted as a malformed update, as flag on counts one (§8.6 D9)."""
        if not sub.snapshot_pending:
            sub.snapshot_pending, sub.pending_reason = True, "upstream_desync"
        cv_ws_malformed_updates_total.labels(topic=sub.topic.family.family).inc()
        self._log_failed("delta", authz, sub, exc)

    def _log_failed(
        self, what: str, authz: ConnectionAuthz, sub: Subscription | None, exc: Exception
    ) -> None:
        """`ws {what} failed`, by connection, family and error class only (C-12.6). `orders` and
        `executions` log every line, at `error`, as flag on logs each of their closes; the other
        families, and `rebuild` lines, which name none, log at `warning`, at most one line per
        (event, family) per `FAILURE_LOG_INTERVAL_S`, with a `suppressed` count (`_quiet`). A
        failing logger or clock changes nothing (a cancellation still propagates)."""
        with contextlib.suppress(Exception):  # never into the fan-out
            family = None if sub is None else sub.topic.family
            fields = {"connection_id": authz.connection_id, "error": type(exc).__name__}
            if family is not None:
                fields["family"] = family.family
            if family is not None and family.never_throttled:
                _log().error(f"ws {what} failed", **fields)
            elif (held := self._quiet((what, fields.get("family", "")))) is not None:
                _log().warning(f"ws {what} failed", **fields, suppressed=held)

    def _quiet(self, key: tuple[str, str]) -> int | None:
        """None holds a log line back: one per `key` (event, family) per `FAILURE_LOG_INTERVAL_S`
        on the hub's clock, as `ConnectionPipeline._quiet` does per connection. Else how many it
        held back since the last line (`suppressed`). Bounded: one entry per (event, family)."""
        now, last = self._clock(), self._log_window.get(key)
        if last is not None and now < last[0]:
            self._log_window[key] = (last[0], last[1] + 1)
            return None
        self._log_window[key] = (now + FAILURE_LOG_INTERVAL_S, 0)
        return 0 if last is None else last[1]


def _live_symbol(symbol: str, *, book_only: bool) -> Callable[[Subscription], bool]:
    def match(sub: Subscription) -> bool:
        if sub.replay_session_id is not None or sub.topic.family.private:
            return False
        if book_only and sub.topic.family.family != "book":
            return False
        return symbol in sub.symbols

    return match


# -- book depth-window deltas (§7.3) -------------------------------------------------------------

Levels = Mapping[str, str]  # price -> size, decimal strings as on the wire


def book_window(levels: Mapping[str, str], depth: int, *, descending: bool) -> dict[str, str]:
    """The `depth` best levels of one side (prices compared numerically via `Decimal`)."""
    best = sorted(levels, key=Decimal, reverse=descending)[:depth]
    return {p: levels[p] for p in best}


def window_delta(prev: Levels, new: Levels) -> list[list[str]]:
    """Levels to send so a client holding `prev` ends at `new`: changed or added levels with their
    size, and every level that left the window (deleted upstream or pushed out of depth) with
    size `"0"` so the client's window stays exactly `depth` levels (§7.3)."""
    out = [[p, s] for p, s in new.items() if prev.get(p) != s]
    out.extend([p, "0"] for p in prev if p not in new)
    return out
