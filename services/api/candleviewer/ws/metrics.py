"""CVWB encode metrics (E17-T02 follow-up, docs/plan/20-architecture.md section 12.1) and the
send-path series of the gateway (E17-T06: fan-out span, frame encode time and size); with the
backpressure flag on, also its conflation, class, RTT and queue depth series (below).

Module-level series (the encoder is a pure function with no facade); `export_cvwb_metrics()` and
`export_ws_metrics()` serve them on the scraped registry. ``kind`` is the six-name body-kind enum
of section 3.4 (plus ``json`` and ``msgpack``, a data frame as its connection's codec sent it, on
the E17-T06 series), so children are pre-bound once and the hot path does no label lookup or
formatting.

The send-path series are `FastHistogram`s: a `prometheus_client` `Histogram.observe` takes a lock
per value and builds an iterator per call (~0.5-1 us), several times what #571's < 2 % overhead
budget leaves for a frame on the send path. Even the lock-free one costs ~0.25 us in situ, so the
three series observed per frame are also sampled, one frame in `SAMPLE_EVERY`, with that weight.
"""

from __future__ import annotations

import sys
from asyncio import CancelledError
from typing import Final, Literal, get_args

from candleviewer.observability.fast_histogram import FastHistogram
from candleviewer.observability.metrics import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    ReexportCollector,
)
from candleviewer.observability.metrics_catalogue import (
    CLASS_HELP,
    COALESCED_BUCKETS,
    COALESCED_HELP,
    CONFLATED_HELP,
    FANOUT_BUCKETS,
    FANOUT_HELP,
    FRAME_BYTES_BUCKETS,
    FRAME_BYTES_HELP,
    FRAME_ENCODE_BUCKETS,
    FRAME_ENCODE_HELP,
    QUEUE_BYTES_BUCKETS,
    QUEUE_BYTES_HELP,
    QUEUE_FRAMES_BUCKETS,
    QUEUE_FRAMES_HELP,
    RTT_BUCKETS,
    RTT_HELP,
)
from candleviewer.ws._generated.cvwb_layout import KINDS
from candleviewer.ws.lifecycle import CLOSE_REASONS, OTHER_CLOSE_REASON

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
#: E16-T08: live `recorder` subscriptions across all connections (inc at admit, dec when dropped).
cv_ws_recorder_subscriptions_in_use = Gauge(
    "cv_ws_recorder_subscriptions_in_use",
    "Live WS subscriptions of the recorder topic (one 1 Hz status frame each).",
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
# reason and is reached through `RevocationHub.close_for` (from `_close_each` and from `run_auth`'s
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
#: its state, an `account_notice` naming no account and an account list on another `kind` (only the
#: Owner receives those), a socket with no principal, a principal with none of the three roles. An
#: `account_notice` cut to nothing for a socket (SR-E29-10, #3864) is the contract, as is a flag
#: frame left with no key: it is not counted. The closed `reason` set: no frame content.
WithheldReason = Literal["unknown_kind", "invalid_body", "no_principal", "no_role"]
WITHHELD_REASONS: Final[tuple[WithheldReason, ...]] = get_args(WithheldReason)
cv_ws_system_frames_withheld_total = Counter(
    "cv_ws_system_frames_withheld_total",
    "System WS frames not queued for a socket: a kind outside 23 section 15.9, a kill switch "
    "without its state, an account notice naming no account or an account list on another "
    "kind, no principal or no role (SR-188, #3125, #3864). A deny-all socket counts every "
    "other frame as no_role. A Manager's or Viewer's feature_flags frame left with no key it "
    "may learn is the contract and is not counted, nor is an account_notice naming no "
    "account it may view.",
    labelnames=("reason",),
)
# Bound now, as `cv_ws_closes_total` is, so each series exists at 0 from process start and the
# first frame after a restart is not a lone sample that `increase()` cannot see.
for _withheld in WITHHELD_REASONS:
    cv_ws_system_frames_withheld_total.labels(reason=_withheld)

# -- E17-T03 backpressure (pacing.py, outbound.py) -----------------------------------------------
cv_ws_overflow_total = Counter(
    "cv_ws_overflow_total",
    "23 section 8.4 overflow by reason: per topic drop, drop_share, unmergeable, resnapshot; per "
    "close, and per close whose flush deadline expired; withdrawn: per queued frame a withdrawn "
    "grant or permission dropped (section 9.5).",
    labelnames=("reason",),
)
cv_ws_malformed_updates_total = Counter(
    "cv_ws_malformed_updates_total",
    "Producer updates a coalescing queue refused as malformed; the topic label is the family.",
    labelnames=("topic",),
)

# -- E22-T02 (#654) `trades.{symbol}` (trades_publish.py); bounded labels only --------------------
cv_ws_frames_emitted_total = Counter(
    "cv_ws_frames_emitted_total",
    "Frames a topic publisher emitted, per topic family (E22-T02: `trades`).",
    labelnames=("topic",),
)
#: Bounded `cv_ws_tape_prints_dropped_total{reason}` values: a print below the set's `min_size`,
#: or one shed when more than `PENDING_MAX` items waited for one frame (`overflow`).
TAPE_DROP_REASONS: Final = frozenset({"min_size", "overflow"})
cv_ws_tape_prints_dropped_total = Counter(
    "cv_ws_tape_prints_dropped_total",
    "Prints a `trades` option set dropped, by reason (`min_size`, `overflow`).",
    labelnames=("reason",),
)
cv_ws_tape_frames_coalesced_total = Counter(
    "cv_ws_tape_frames_coalesced_total",
    "`trades` frames that appended more than one source batch (`coalesced`).",
)
#: Bounded `cv_ws_trades_subscribe_rejected_total{reason}` values (E22 threat model section 10).
TRADES_REJECT_REASONS: Final = frozenset(
    {"min_size_floor", "cluster_range", "sub_cap_user", "option_sets", "symbols"}
)
cv_ws_trades_subscribe_rejected_total = Counter(
    "cv_ws_trades_subscribe_rejected_total",
    "`trades` subscriptions and retunes refused by an E22 bound, by reason.",
    labelnames=("reason",),
)
cv_ws_frames_emitted_total.labels(topic="trades")
for _drop_reason in TAPE_DROP_REASONS:
    cv_ws_tape_prints_dropped_total.labels(reason=_drop_reason)
for _trades_reason in TRADES_REJECT_REASONS:
    cv_ws_trades_subscribe_rejected_total.labels(reason=_trades_reason)

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
#: failed rows in a row (`ws audit rows abandoned`), or a §6.4 removal's dropped by its queue or
#: left in it when its writer ended (`ws machine revocations not audited`).
AuditFailureReason = Literal["error", "timeout", "cancelled", "abandoned"]  # the closed set
AUDIT_FAILURE_REASONS: Final[tuple[str, ...]] = get_args(AuditFailureReason)
cv_ws_audit_failures_total = Counter(
    "cv_ws_audit_failures_total",
    "WS audit rows not confirmed written (SR-186): error, timeout, cancelled or abandoned.",
    labelnames=("reason",),
)
for _audit_reason in AUDIT_FAILURE_REASONS:  # bound now, so increase() sees the first failure
    cv_ws_audit_failures_total.labels(reason=_audit_reason)
# -- #571 (E17-T06, #2525 review): the store-backed WS principal load (`ws_wiring.py`) ----------
#: How a principal load (`StorePrincipalLoader`, at a first `auth` and at each re-evaluation)
#: failed. `timeout`: a `TimeoutError`, its `PRINCIPAL_LOAD_TIMEOUT_S` bound or the store's own.
#: `error`: anything else raised (the store, an unknown user or role). Either way the load answers
#: the deny-all snapshot, as it did before the count. A non-active user's deny-all is the store's
#: answer and is not counted.
PrincipalLoadFailureReason = Literal["timeout", "error"]  # the closed set
PRINCIPAL_LOAD_FAILURE_REASONS: Final[tuple[str, ...]] = get_args(PrincipalLoadFailureReason)
cv_ws_principal_load_failures_total = Counter(
    "cv_ws_principal_load_failures_total",
    "WS principal loads that failed and answered the deny-all snapshot: timeout or error.",
    labelnames=("reason",),
)
for _load_reason in PRINCIPAL_LOAD_FAILURE_REASONS:  # bound now, so increase() sees the first
    cv_ws_principal_load_failures_total.labels(reason=_load_reason)
#: The two children, so the failure path does no label lookup.
PRINCIPAL_LOAD_FAILURES: Final = {
    r: cv_ws_principal_load_failures_total.labels(reason=r) for r in PRINCIPAL_LOAD_FAILURE_REASONS
}

#: #3185: one per `ws.subscribe.denied` record a connection's budget kept from the writer
#: (`limits.DENIAL_AUDITS_PER_WINDOW` in any sliding `DENIAL_AUDIT_WINDOW_S`), however many
#: refusals it held. Deliberate, not a failure: no `cv_ws_audit_failures_total` reason, so
#: `WsAuditWriteFailed` does not fire on it. Unlabelled: its one series exists from import.
cv_ws_subscribe_denied_unaudited_total = Counter(
    "cv_ws_subscribe_denied_unaudited_total",
    "ws.subscribe.denied records not written: their connection's budget for the window was spent.",
)
#: #415 (E17-R-14): one per `ws.subscribe.granted` record a connection's own budget kept from the
#: writer, of the same size and window as the denial records' (#3185). Deliberate, as that one is.
#: Unlabelled: its one series exists from import.
cv_ws_subscribe_granted_unaudited_total = Counter(
    "cv_ws_subscribe_granted_unaudited_total",
    "ws.subscribe.granted records not written: their connection's budget for the window was spent.",
)
#: #415 (E17-R-15, §6.2): one per account id a `sub` entry named that its scope narrowing took
#: away. The reply stays silent; the frame's `ws.subscribe.denied` record lists the entry.
#: Unlabelled.
cv_ws_subscribe_narrowed_total = Counter(
    "cv_ws_subscribe_narrowed_total",
    "Account ids a WS sub named that the scope narrowing took away (silent in the reply).",
)


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

# -- E17-T06 with CV_WS_BACKPRESSURE_ENABLED on (#412's wiring, ruling D6) ----------------------
# Per process: no connection, user, symbol or channel in any label. The two labelled series bind
# their closed sets where those sets live, at import (`pacing.CONFLATED`, `pacing.CLASS_COUNTS`).
# `cv_ws_coalesced_updates` is observed as a merged window leaves (a `FastHistogram`, as the send
# path's are). The RTT and the two depths are plain `Histogram`s: one observation per probe sample
# or classification (about once per `classify_interval_ms` per connection), never per frame.
cv_ws_conflated_total = Counter("cv_ws_conflated_total", CONFLATED_HELP, labelnames=("topic",))
cv_ws_connection_class = Gauge("cv_ws_connection_class", CLASS_HELP, labelnames=("state",))
cv_ws_coalesced_updates = FastHistogram(
    "cv_ws_coalesced_updates", COALESCED_HELP, buckets=COALESCED_BUCKETS
)
cv_ws_rtt_seconds = Histogram("cv_ws_rtt_seconds", RTT_HELP, buckets=RTT_BUCKETS)
cv_ws_queue_bytes = Histogram("cv_ws_queue_bytes", QUEUE_BYTES_HELP, buckets=QUEUE_BYTES_BUCKETS)
cv_ws_queue_frames = Histogram(
    "cv_ws_queue_frames", QUEUE_FRAMES_HELP, buckets=QUEUE_FRAMES_BUCKETS
)

#: Every series the ws package owns (module-level, re-exported on the app registry): the `cv_ws_*`
#: ones and the 23 section 6.4 `cv_machine_ws_*` ones (`machines.py`).
CV_WS_NAMES: Final[frozenset[str]] = frozenset(
    {
        "cv_ws_connections_in_use",
        "cv_ws_handshake_seconds",
        "cv_ws_auth_failures_total",
        "cv_ws_principal_load_failures_total",
        "cv_ws_closes_total",
        "cv_ws_connect_rate_limited_total",
        "cv_ws_audit_failures_total",
        "cv_ws_subscribe_denied_unaudited_total",
        "cv_ws_subscribe_granted_unaudited_total",
        "cv_ws_subscribe_narrowed_total",
        "cv_ws_clock_skew_ms",
        "cv_ws_system_frames_withheld_total",
        "cv_ws_subscribe_total",
        "cv_ws_client_topics_depth",
        "cv_ws_alerts_subscriptions_in_use",
        "cv_ws_recorder_subscriptions_in_use",
        "cv_ws_revoked_total",
        "cv_ws_permission_snapshots_refused_total",
        "cv_ws_publish_denied_total",
        "cv_ws_upstream_consumers_in_use",
        "cv_ws_resync_total",
        "cv_ws_rebuild_refused_total",
        "cv_ws_snapshot_bytes",
        "cv_ws_snapshot_build_seconds",
        "cv_ws_sequence_gaps_detected_total",
        "cv_ws_stale_topics_in_use",
        "cv_ws_snapshot_overdue_total",
        "cv_ws_fanout_seconds",
        "cv_ws_frame_encode_seconds",
        "cv_ws_frame_bytes",
        "cv_ws_overflow_total",
        "cv_ws_malformed_updates_total",
        "cv_ws_conflated_total",
        "cv_ws_connection_class",
        "cv_ws_coalesced_updates",
        "cv_ws_rtt_seconds",
        "cv_ws_queue_bytes",
        "cv_ws_queue_frames",
        "cv_ws_frames_emitted_total",
        "cv_ws_tape_prints_dropped_total",
        "cv_ws_tape_frames_coalesced_total",
        "cv_ws_trades_subscribe_rejected_total",
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
#: The one `cv_ws_coalesced_updates` series: `Pacer` observes each merged window that leaves.
COALESCED_UPDATES: Final = cv_ws_coalesced_updates.labels()


def export_ws_metrics(registry: CollectorRegistry, *, env: str) -> ReexportCollector:
    """Serve every `CV_WS_NAMES` series on `registry` (the scraped one) with `env`."""
    # The owning modules declare their series at import; import them so every family exists.
    from candleviewer.ws import (  # noqa: F401
        machines,
        pacing,
        permissions,
        rebuild_budget,
        revocation,
        sequencing,
        upstream,
    )

    return ReexportCollector(registry, names=CV_WS_NAMES, const_labels={"env": env})


def export_cvwb_metrics(registry: CollectorRegistry, *, env: str) -> ReexportCollector:
    """Serve the CVWB encode series on `registry` (the scraped one) with `env`."""
    return ReexportCollector(registry, names=EXPORTED_NAMES, const_labels={"env": env})
