"""CVWB encode metrics (E17-T02 follow-up, docs/plan/20-architecture.md section 12.1) and the
send-path series of the gateway (E17-T06: fan-out span, frame encode time and size).

Module-level series (the encoder is a pure function with no facade); `export_cvwb_metrics()` and
`export_ws_metrics()` serve them on the scraped registry. ``kind`` is the six-name body-kind enum
of section 3.4 (plus ``json`` and ``msgpack``, a data frame as its connection's codec sent it, on
the E17-T06 series), so children are pre-bound once and the hot path does no label lookup or
formatting.

The E17-T06 series are `FastHistogram`s: a `prometheus_client` `Histogram.observe` takes a lock
per value and builds an iterator per call (~0.5-1 us), several times what #571's < 2 % overhead
budget leaves for a frame on the send path. Even the lock-free one costs ~0.25 us in situ, so the
three series observed per frame are also sampled, one frame in `SAMPLE_EVERY`, with that weight.
"""

from __future__ import annotations

import sys
from asyncio import CancelledError
from bisect import bisect_left
from collections.abc import Iterable, Mapping, Sequence
from itertools import accumulate, pairwise
from math import isfinite
from typing import Any, Final, Literal, get_args

from candleviewer.observability.metrics import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    ReexportCollector,
    check_label_names,
)
from candleviewer.observability.metrics_catalogue import (
    FANOUT_BUCKETS,
    FANOUT_HELP,
    FRAME_BYTES_BUCKETS,
    FRAME_BYTES_HELP,
    FRAME_ENCODE_BUCKETS,
    FRAME_ENCODE_HELP,
)
from candleviewer.ws._generated.cvwb_layout import KINDS
from candleviewer.ws.lifecycle import CLOSE_REASONS, OTHER_CLOSE_REASON

#: One child's scrape reading: cumulative bucket counts (the last, `+Inf`, is the count), sum.
Reading = tuple[tuple[float, ...], float]


class FastHistogramChild:
    """One series of a `FastHistogram`: the per-bucket counts (not cumulative; the last bucket is
    `+Inf`) and then the sum, in one list.

    Only the event loop observes; a scrape may run on another thread (`/metrics` is a sync route).
    `reading()` copies the list in one C call that no other thread can interleave under the GIL,
    so a scrape sees every bucket and the sum from one instant: the count (the `+Inf` bucket) can
    be one observation ahead of the sum, the one the loop is midway through, which Prometheus
    tolerates. Nothing is torn or lost: one writer, atomic slot stores, immutable numbers.
    """

    __slots__ = ("_bounds", "_cells")

    def __init__(self, bounds: tuple[float, ...]) -> None:
        self._bounds = bounds
        self._cells: list[float] = [0] * (len(bounds) + 1) + [0.0]

    def observe(self, value: float, weight: int = 1) -> None:
        """Count `value` `weight` times in the first bucket whose bound is >= it (Prometheus `le`;
        past the last bound, `+Inf`) and add `value * weight` to the sum: one bisect and two
        increments, with no lock, label lookup or object built. A call site that observes one
        event in N passes `weight=N`, so the counts and the sum estimate the whole stream and the
        exposition stays a valid histogram. `weight` is a positive int (not checked, for speed);
        NaN is out of domain."""
        cells = self._cells
        cells[bisect_left(self._bounds, value)] += weight
        cells[-1] += value * weight

    def reading(self) -> Reading:
        """This series for a scrape: (cumulative bucket counts, ending with `+Inf`; the sum)."""
        *counts, total = tuple(self._cells)  # the one-step copy the class doc relies on
        return tuple(accumulate(counts)), total


class FastHistogram:
    """A histogram for the WS hot path, exposed exactly as a `prometheus_client` `Histogram`.

    Every child (one per closed label set, or the one series when there are no labels) is bound
    here and none is ever added, so `labels()` is a lookup. The scrape side is an `_Exposition` on
    `registry` (None: the library's default, where `export_ws_metrics()` re-exports from).

    Why the send path samples: #571 caps its instrumentation at 2 % of the fan-out path, and a
    frame there costs 10-55 us. Measured in situ, an `observe` is ~0.25 us and a clock read ~0.07
    us, so observing three series and stamping every frame would cost 1.0-2.5 us, 2-25 % of it.
    The three per-frame series (`cv_ws_fanout_seconds`, `cv_ws_frame_encode_seconds`,
    `cv_ws_frame_bytes`) therefore observe one frame in `SAMPLE_EVERY`, chosen by a counter and
    never at random, with `weight=SAMPLE_EVERY`; the clock reads that only feed a skipped
    observation are skipped too. Rates are right for a long-lived subscription, and a count is
    a lower bound within `SAMPLE_EVERY - 1` frames of it (its first 31 frames are never
    observed); the quantiles are those of a systematic sample, unbiased unless the stream a
    counter walks has a period that divides `SAMPLE_EVERY`. So no counter is shared by
    connections or kinds (eight subscribers fed in turn by one would always sample the same
    one): the counter is the subscription's own `s`, the hub stamps the frame it selects, and
    the encoder and the writer observe the frames it stamped.
    """

    def __init__(
        self,
        name: str,
        documentation: str,
        *,
        buckets: Sequence[float],
        labelnames: Sequence[str] = (),
        label_values: Iterable[Sequence[str]] = (),
        registry: CollectorRegistry | None = None,
    ) -> None:
        bounds = tuple(float(b) for b in buckets)
        if not bounds or not all(map(isfinite, bounds)) or any(a >= b for a, b in pairwise(bounds)):
            raise ValueError(f"{name}: buckets must be finite and ascending; +Inf is implicit")
        check_label_names(name, labelnames)
        keys = tuple(tuple(v) for v in label_values) or ((),)
        if len(set(keys)) != len(keys) or any(len(k) != len(labelnames) for k in keys):
            raise ValueError(f"{name}: label_values must be distinct, one value per label name")
        self.name = name
        self.buckets = bounds
        self.labelnames = tuple(labelnames)
        #: The closed label sets, in binding order (the exposition's series order).
        self.label_values = keys
        self._children = {key: FastHistogramChild(bounds) for key in keys}
        self._exposition = _Exposition.serve(self, documentation, registry)

    def labels(self, *values: str) -> FastHistogramChild:
        """The child bound for `values` (none: the unlabelled series). KeyError outside the
        closed set: no child is created after construction."""
        return self._children[values]

    def readings(self) -> dict[tuple[str, ...], Reading]:
        """Every child's reading for one scrape, each taken once."""
        return {key: child.reading() for key, child in self._children.items()}

    def sample_value(
        self, name: str, labels: Mapping[str, str], readings: Mapping[tuple[str, ...], Reading]
    ) -> float | None:
        """The value of one exposition sample from `readings`; None keeps the library's own
        (`_created`)."""
        cumulative, total = readings[tuple(labels.get(n, "") for n in self.labelnames)]
        suffix = name.removeprefix(self.name)
        if suffix == "_bucket":
            return float(cumulative[bisect_left(self.buckets, float(labels["le"]))])
        if suffix == "_count":
            return float(cumulative[-1])
        if suffix == "_sum":
            return float(total)
        return None


class _Exposition(Histogram):
    """The scrape side of one `FastHistogram`: a facade `Histogram` that nothing observes.

    `ws/` may not import `prometheus_client` (import-linter E04-T03, semgrep
    `cv-obs-no-prometheus-import`) and the facade exports no `Collector` or metric family type, so
    the adapter is a `Histogram` with the fast one's name, help, labels and buckets. `collect()`
    takes the library's own family (sample names, `le` strings, order, `_created`, all at zero)
    and swaps in the fast values: the exposition is a `Histogram`'s, byte for byte.
    """

    #: Bound by `serve()` once the template children exist; None only while it builds them.
    fast: FastHistogram | None = None

    @classmethod
    def serve(
        cls, fast: FastHistogram, documentation: str, registry: CollectorRegistry | None
    ) -> _Exposition:
        names, buckets = fast.labelnames, fast.buckets
        if registry is None:  # the library default: no handle to it is importable here
            out = cls(fast.name, documentation, names, buckets=buckets)
        else:
            out = cls(fast.name, documentation, names, buckets=buckets, registry=registry)
        for key in fast.label_values:
            if key:
                out.labels(*key)
        out.fast = fast
        return out

    def collect(self) -> Iterable[Any]:  # Any: the family type is not nameable from ws/
        families = list(super().collect())
        fast = self.fast
        if fast is None:  # scraped while `serve()` builds it: nothing is observed yet
            return families
        readings = fast.readings()
        for family in families:
            samples = []
            for s in family.samples:
                value = fast.sample_value(s.name, s.labels, readings)
                samples.append(s if value is None else s._replace(value=value))
            family.samples = samples
        return families


cvwb_frames_encoded_total = Counter(
    "cvwb_frames_encoded_total", "CVWB frames encoded.", labelnames=("kind",)
)
cvwb_bytes_encoded_total = Counter(
    "cvwb_bytes_encoded_total", "CVWB bytes encoded (header + body).", labelnames=("kind",)
)

# -- E17-S01 connection lifecycle (gateway.py); bounded labels only (reason/code enums) --------
cv_ws_connections_in_use = Gauge(
    "cv_ws_connections_in_use", "Open client WS connections (any lifecycle state)."
)
cv_ws_handshake_seconds = Histogram(
    "cv_ws_handshake_seconds",
    "Socket accept to first auth_ok.",
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)
cv_ws_auth_failures_total = Counter(
    "cv_ws_auth_failures_total", "Failed WS auth frames, by reason.", labelnames=("reason",)
)
cv_ws_closes_total = Counter(
    "cv_ws_closes_total",
    "Server-initiated WS closes by bye reason (the close code is fixed per reason).",
    labelnames=("reason",),
)
# Bind every `reason` now, so each series exists at 0 from process start. A series born at its first
# close is a single sample: `increase()` has nothing to subtract, so the first close under a reason
# after every restart goes unseen (#2264 bound the CSRF counter for the same reason). Read by
# `WsOriginRefusalsHigh` (`origin_forbidden`) and `WsSlowConsumerClosed` (`slow_consumer`, #571).
# Bound here, beside the counter, so `export_ws_metrics` serves every series without the gateway.
# `normal` and `other` have no counting path today (`server_shedding_load` counts sheds, #2155).
# Nothing closes with `normal`. `other` has no producer: `lifecycle.bye_frame` raises on an
# unknown reason on a connection's first close (a sealed close on one already closing skips it, and
# its only caller without `bye=` passes `token_expired`), and a `bye=` frame is built only by
# `user_disabled_bye` (a fixed reason), by the gateway's `refuse_connect` and the flag-on
# `pipeline.slow_consumer_bye` (both through `lifecycle.bye_frame`, so validated) and by
# `revocation.bye_frame`, which does not validate its
# reason and is reached through `RevocationHub.close_for` (from `_close_all` and from `run_auth`'s
# revoked-before-registration check), whose reasons are the ones `revoke` remembered. So only
# `app._hub_publisher` (it narrows a revoke reason to `user_disabled` or `session_revoked`) keeps
# `other` empty. They stay bound all the same (a hand-kept exclusion list would rot), so their 0
# is not coverage.
for _close_reason in (*CLOSE_REASONS, OTHER_CLOSE_REASON):
    cv_ws_closes_total.labels(reason=_close_reason)
cv_ws_connect_rate_limited_total = Counter(
    "cv_ws_connect_rate_limited_total",
    "WS sockets refused by the per-user connect rate (bye client_rate_limited after a valid auth).",
)
cv_ws_clock_skew_ms = Histogram(
    "cv_ws_clock_skew_ms",
    "Absolute client clock skew reported in welcome (milliseconds).",
    buckets=(10, 50, 100, 250, 500, 1000, 2000, 5000, 30000),
)

# -- SR-188 `system` topic (gateway.py `push_system`, system_filter.py `withheld_reason`) --------
#: Why a `system` frame was left out of a socket's queue for a reason that is not its role's cut:
#: a `kind` outside 23 section 15.9 (nobody receives it, the Owner included), a kill switch without
#: its state (only the Owner does), a socket with no principal, a principal with none of the three
#: roles. The closed `reason` set: no frame content.
WithheldReason = Literal["unknown_kind", "invalid_body", "no_principal", "no_role"]
WITHHELD_REASONS: Final[tuple[WithheldReason, ...]] = get_args(WithheldReason)
cv_ws_system_frames_withheld_total = Counter(
    "cv_ws_system_frames_withheld_total",
    "System frames not queued for a socket: an unknown kind, no kill switch state, no principal or "
    "no role.",
    labelnames=("reason",),
)
# Bound now, as `cv_ws_closes_total` is, so each series exists at 0 from process start and the
# first frame after a restart is not a lone sample that `increase()` cannot see.
for _withheld in WITHHELD_REASONS:
    cv_ws_system_frames_withheld_total.labels(reason=_withheld)

# -- E17-T03 backpressure (pacing.py, outbound.py) -----------------------------------------------
cv_ws_overflow_total = Counter(
    "cv_ws_overflow_total",
    "23 section 8.4 overflow by reason: per topic drop, unmergeable, resnapshot; per close, "
    "and per close whose flush deadline expired.",
    labelnames=("reason",),
)
cv_ws_malformed_updates_total = Counter(
    "cv_ws_malformed_updates_total",
    "Producer updates a coalescing queue refused as malformed; the topic label is the family.",
    labelnames=("topic",),
)

#: Bounded `cv_ws_auth_failures_total{reason}` values. `token_expired` counts
#: tokens the session service accepted but the gateway clock had already passed
#: (a sub-ms race in production); tokens the service refuses count as `rejected`.
AUTH_FAILURE_REASONS: Final = frozenset(
    {"missing_token", "rejected", "token_expired", "user_mismatch"}
)

# -- SR-186 / SR-E17-04 (#2174): WS audit rows not confirmed written -----------------------------
#: How a best-effort WS audit row (threat model WS-R04) failed. `error`: the sink raised, so the
#: row is lost. `timeout`: its bound expired first; it may still land (the writer finishes an
#: append it began). `cancelled`: a cancellation ended the wait, and the row is lost unless its
#: append had begun. `abandoned`: never handed to the writer, after `FANOUT_AUDIT_MAX_FAILURES`
#: failed rows in a row (the fan-out's `ws audit rows abandoned`, cause `writer_down`).
AuditFailureReason = Literal["error", "timeout", "cancelled", "abandoned"]  # the closed set
AUDIT_FAILURE_REASONS: Final[tuple[str, ...]] = get_args(AuditFailureReason)
cv_ws_audit_failures_total = Counter(
    "cv_ws_audit_failures_total",
    "WS audit rows not confirmed written (SR-186): error, timeout, cancelled or abandoned.",
    labelnames=("reason",),
)
for _audit_reason in AUDIT_FAILURE_REASONS:  # bound now, so increase() sees the first failure
    cv_ws_audit_failures_total.labels(reason=_audit_reason)


def count_audit_failure(rows: int = 1, reason: AuditFailureReason | None = None) -> None:
    """Count `rows` WS audit rows not confirmed written. Without `reason`, call it directly in the
    `except` that caught the failure: the exception being handled names it (a bare `TimeoutError`,
    the bound: `timeout`; a cancellation: `cancelled`; anything else, an `ExceptionGroup` whatever
    it wraps (the sink raised), or no exception: `error`). A reason outside the closed set counts
    as `error`, so it never adds a series, and never raises inside the caller's `except`."""
    if reason is None:
        exc = sys.exception()
        reason = "timeout" if isinstance(exc, TimeoutError) else "error"
        reason = "cancelled" if isinstance(exc, CancelledError) else reason
    reason = reason if reason in AUDIT_FAILURE_REASONS else "error"
    cv_ws_audit_failures_total.labels(reason=reason).inc(rows)


# -- E17-T06 send path (sequencing.py stamps, gateway.py writer observes, binary.py encodes) ---
#: The send path observes one frame in `SAMPLE_EVERY`, with that weight (see `FastHistogram`). The
#: sampled frame is the one whose subscription counter, its `s`, reaches a multiple of it: the
#: 32nd, the 64th, and so on. The hub stamps it; the encoder (a CVWB kind) and the writer (`json`
#: or `msgpack`, by the connection's codec) observe the stamped frame. A power of two, so that the
#: sampler is `s & SAMPLE_MASK`: no division, no random number, no state beyond the counter.
SAMPLE_MASK: Final = 31
SAMPLE_EVERY: Final = SAMPLE_MASK + 1

#: The closed `kind` set: the six body-kind names, and a whole data frame as the writer sent it,
#: by the codec the connection negotiated (23 section 2.2): the text of a `cv.v1.json` connection
#: (`json`) or the bytes of a `cv.v1.msgpack` one (`msgpack`).
JSON_KIND: Final = "json"
MSGPACK_KIND: Final = "msgpack"
FRAME_KINDS: Final[tuple[str, ...]] = (*(k.name for k in KINDS.values()), JSON_KIND, MSGPACK_KIND)

#: The gateway segment of budget #6 (06-performance section 2): a subscription's turn in the hub
#: loop, not bus receipt -> the writer has handed the data frame to the socket. No labels: the
#: span has one meaning, and no symbol, user, connection or channel may become a series.
cv_ws_fanout_seconds = FastHistogram("cv_ws_fanout_seconds", FANOUT_HELP, buckets=FANOUT_BUCKETS)
cv_ws_frame_encode_seconds = FastHistogram(
    "cv_ws_frame_encode_seconds",
    FRAME_ENCODE_HELP,
    buckets=FRAME_ENCODE_BUCKETS,
    labelnames=("kind",),
    label_values=[(k,) for k in FRAME_KINDS],
)
cv_ws_frame_bytes = FastHistogram(
    "cv_ws_frame_bytes",
    FRAME_BYTES_HELP,
    buckets=FRAME_BYTES_BUCKETS,
    labelnames=("kind",),
    label_values=[(k,) for k in FRAME_KINDS],
)

#: Every series the ws package owns (module-level, re-exported on the app registry): the `cv_ws_*`
#: ones and the 23 section 6.4 `cv_machine_ws_*` ones (`machines.py`).
CV_WS_NAMES: Final[frozenset[str]] = frozenset(
    {
        "cv_ws_connections_in_use",
        "cv_ws_handshake_seconds",
        "cv_ws_auth_failures_total",
        "cv_ws_closes_total",
        "cv_ws_connect_rate_limited_total",
        "cv_ws_audit_failures_total",
        "cv_ws_clock_skew_ms",
        "cv_ws_system_frames_withheld_total",
        "cv_ws_subscribe_total",
        "cv_ws_client_topics_depth",
        "cv_ws_revoked_total",
        "cv_ws_permission_snapshots_refused_total",
        "cv_ws_upstream_consumers_in_use",
        "cv_ws_resync_total",
        "cv_ws_snapshot_bytes",
        "cv_ws_snapshot_build_seconds",
        "cv_ws_sequence_gaps_detected_total",
        "cv_ws_stale_topics_in_use",
        "cv_ws_fanout_seconds",
        "cv_ws_frame_encode_seconds",
        "cv_ws_frame_bytes",
        "cv_ws_overflow_total",
        "cv_ws_malformed_updates_total",
        "cv_machine_ws_publish_total",
        "cv_machine_ws_scope_missing_total",
        "cv_machine_ws_registry_full_total",
    }
)

EXPORTED_NAMES: Final[frozenset[str]] = frozenset(
    {"cvwb_frames_encoded_total", "cvwb_bytes_encoded_total"}
)

#: body_kind -> (frames child, bytes child); fixed at import, never grows.
ENCODED: Final = {
    k: (
        cvwb_frames_encoded_total.labels(kind=v.name),
        cvwb_bytes_encoded_total.labels(kind=v.name),
    )
    for k, v in KINDS.items()
}


#: body_kind -> (seconds, bytes) children of the kind, observed by `binary.encode` for a frame its
#: caller weights: `SAMPLE_EVERY` for the delta the hub stamped (it encodes once per subscription
#: per delta), 1 for each chunk of a snapshot (rare, so every one is observed).
ENCODE_COST: Final = {
    k: (cv_ws_frame_encode_seconds.labels(v.name), cv_ws_frame_bytes.labels(v.name))
    for k, v in KINDS.items()
}
#: The writer's encode of a data frame: its seconds, and the bytes encoded for the send (a JSON text
#: is ASCII: chars == bytes). The writer observes the pair of the connection's codec for the frame
#: the hub stamped, one in `SAMPLE_EVERY`: `json.dumps` on `cv.v1.json`, `encode_server_frame` on
#: `cv.v1.msgpack`. With `CV_WS_BACKPRESSURE_ENABLED` on, `pipeline.ConnectionPipeline.push`
#: observes the pair instead, at the frame's one encode.
JSON_ENCODE_SECONDS: Final = cv_ws_frame_encode_seconds.labels(JSON_KIND)
JSON_FRAME_BYTES: Final = cv_ws_frame_bytes.labels(JSON_KIND)
MSGPACK_ENCODE_SECONDS: Final = cv_ws_frame_encode_seconds.labels(MSGPACK_KIND)
MSGPACK_FRAME_BYTES: Final = cv_ws_frame_bytes.labels(MSGPACK_KIND)
#: What a stamped frame's span id `sp` adds to it (23 section 3.1): 24 bytes of JSON text, 20 of
#: MessagePack (a 3-byte key, a 17-byte value), which its `json` / `msgpack` bytes leave out.
SP_JSON_BYTES: Final = 24
SP_MSGPACK_BYTES: Final = 20


def frame_bytes(payload: str | bytes, sp: str | None, *, msgpack: bool) -> int:
    """A stamped frame's `cv_ws_frame_bytes{json|msgpack}` value: its length as encoded for the
    send (MessagePack bytes or ASCII JSON text), less its `sp` if it carries one, so it weighs
    what an unsampled frame does (20 section 12.1). `msgpack` is the codec the caller encoded it
    with, the connection's: it says what `sp` added, never the payload's Python type."""
    if sp is None:
        return len(payload)
    return len(payload) - (SP_MSGPACK_BYTES if msgpack else SP_JSON_BYTES)


#: The one fan-out series; the writer observes it for each stamped data frame it sends, and the
#: hub stamps one data frame of a subscription in `SAMPLE_EVERY`.
FANOUT_SECONDS: Final = cv_ws_fanout_seconds.labels()


def export_ws_metrics(registry: CollectorRegistry, *, env: str) -> ReexportCollector:
    """Serve every `CV_WS_NAMES` series on `registry` (the scraped one) with `env`."""
    # The owning modules declare their series at import; import them so every family exists.
    from candleviewer.ws import (  # noqa: F401
        machines,
        permissions,
        revocation,
        sequencing,
        upstream,
    )

    return ReexportCollector(registry, names=CV_WS_NAMES, const_labels={"env": env})


def export_cvwb_metrics(registry: CollectorRegistry, *, env: str) -> ReexportCollector:
    """Serve the CVWB encode series on `registry` (the scraped one) with `env`."""
    return ReexportCollector(registry, names=EXPORTED_NAMES, const_labels={"env": env})
