"""WS gateway resource limits (C-2.18; values from `23-ws-protocol.md` §3.6, §4.3).

Single home for every bound the gateway enforces. Overflow policy:

- Inbound frame > `MAX_INBOUND_FRAME_BYTES` -> close `1009` (checked on the
  raw text/bytes BEFORE JSON parsing, so an oversized frame is never decoded).
- Until the first `auth_ok`, a frame > `MAX_PREAUTH_FRAME_BYTES` -> close `1009` (checked the
  same way, so it is never scanned or decoded), and a MessagePack frame past the smaller value
  budget `ws/codec.py` sets for that window -> `frame_malformed`.
- JSON text frame with > `MAX_JSON_CONTAINERS` `[` and `{` characters -> `frame_malformed` (a
  protocol violation); it is never depth-scanned or decoded.
- `sub` with > `MAX_TOPICS_PER_SUB` topics -> the whole frame is refused with
  `too_many_topics` (`field: topics`) before any entry is read; nothing is subscribed (SR-192).
- The refusals of one `sub` that `ws.subscribe.denied` records -> ONE record for the frame, which
  counts them all and lists the first `MAX_DENIALS_LISTED` (SR-192, #2292).
- `unsub` with > `MAX_TOPICS_PER_SUB` topics -> the whole frame is refused with
  `invalid_options` (`field: topics`) before any entry is read; nothing is unsubscribed (#2875).
- A subscription that would grow a connection past `MAX_SUBSCRIPTIONS` ->
  rejected per-topic with `subscription_limit`; the set never grows past it.
- No successful `auth` within `AUTH_TIMEOUT_S` -> `bye auth_timeout` + close `4401`.
- An `auth` call past `AUTH_CALL_TIMEOUT_S` -> `bye internal_error` + close `1011` (#2155).
- A socket past `MAX_UNAUTHENTICATED_SOCKETS` awaiting auth -> `bye server_shedding_load` + `1013`.
- `permission_change` / `revoked` fan-out: each socket's frame is sent under
  `FANOUT_SEND_TIMEOUT_S`; a stalled or failing socket is dropped from the
  registry and closed (`4429` slow consumer) so it cannot block the role-change
  request or the other sockets. Every socket's now-forbidden subscriptions are
  removed synchronously before any send; a socket whose swap raises is evicted
  the same way. The fan-out's audit rows are written once every socket has its
  frames, or when the change raises or is cancelled, each under
  `FANOUT_AUDIT_TIMEOUT_S`; after `FANOUT_AUDIT_MAX_FAILURES` failed rows in a
  row the rest are abandoned and logged with a count (#2824).
"""

from __future__ import annotations

MAX_INBOUND_FRAME_BYTES = 256 * 1024
#: §13.1 `envelope.id` `maxLength`, in characters. A request `id` that is not a string within it
#: is dropped before the frame is handled, so no reply echoes it (#2572).
ENVELOPE_ID_MAX_LEN = 64
#: SR-184: max container nesting of an inbound frame. The deepest legitimate
#: client frame (`sub`/`ctl` envelope -> p -> options -> list -> object) is ~6
#: levels in ws-schema.json; 32 leaves headroom. Checked BEFORE `json.loads`.
MAX_JSON_DEPTH = 32
#: SR-040: max size, in encoded bytes, of an inbound frame until the first `auth_ok`, the `hello`
#: included. The largest conforming frame there, with each enum list naming every member once,
#: is an `auth` with the longest `access_token` the schema allows (4 096 characters) in ASCII,
#: about 4.2 KiB: this is about 1.9x that, and 1/32 of `MAX_INBOUND_FRAME_BYTES`. A non-ASCII
#: token of that many characters can exceed it, and is refused here. Checked on the raw frame
#: BEFORE any scan or decode.
MAX_PREAUTH_FRAME_BYTES = 8 * 1024
#: SR-184: max `[` plus `{` characters in an inbound JSON text frame. The count ignores strings,
#: so it can only over-count. The widest conforming frame, a `sub` of 50 topics with every option
#: the schema defines and every list full, has about 400: this is about 2.5x that. Checked BEFORE
#: the depth scan and `json.loads`.
MAX_JSON_CONTAINERS = 1024
#: §13.5 `maxItems` of `sub.topics` and `unsub.topics`, and `welcome.limits.max_topics_per_request`.
MAX_TOPICS_PER_SUB = 50
#: SR-192: the one `ws.subscribe.denied` record of a `sub` frame lists the `object_id` and
#: `reason` of at most this many of its refusals, in request order; its `count` holds them all.
MAX_DENIALS_LISTED = 10
MAX_SUBSCRIPTIONS = 200
#: §16.2 / welcome `limits.max_symbols_per_connection`; excess -> `subscription_limit`.
MAX_SYMBOLS_PER_CONNECTION = 40
#: SR-E12-07 (§6.1): `bars.*` subscriptions per connection, live and replay; the next one gets
#: `subscription_limit`. With `history` <= 1 000 this bounds one socket's snapshot amplification.
MAX_BARS_SUBSCRIPTIONS = 16
#: §16.2: `machines.{entity}.state` registry entries, live and terminal. Past it a payload for a
#: new entity is refused, counted and logged (rate-limited); no entry is evicted, so no live
#: machine's state is lost.
MACHINE_ENTRIES_MAX = 20_000
AUTH_TIMEOUT_S = 10.0
#: #2155 (C-2.18): the bound on each call an `auth` makes (the session service's `authenticate`,
#: the principal read and its SR-189 re-read). Past it: `bye internal_error` + `1011`. Longer than
#: the store loader's own 5 s bound, whose deny-all answer comes first; shorter than the default
#: auth window.
AUTH_CALL_TIMEOUT_S = 6.0
#: #2155: sockets between `accept` and their first `auth_ok`, per process. 8 users (one owner, a few
#: managers) x `MAX_CONNECTIONS_PER_USER` (8 by default) all reconnecting at once; reachable only
#: over loopback or the tailnet (C-12.9). The next socket gets `bye server_shedding_load` + `1013`.
MAX_UNAUTHENTICATED_SOCKETS = 64
FANOUT_SEND_TIMEOUT_S = 2.0
#: Bound on each audit row of that fan-out, like `CLOSE_AUDIT_TIMEOUT_S` on a close's row, and on
#: a `sub` frame's `ws.subscribe.granted` row (#2174).
FANOUT_AUDIT_TIMEOUT_S = 2.0
#: ...and on its rows as a whole: once this many rows in a row have raised or timed out, the rest
#: are abandoned, even when the writer is only slow: a stalled WAL costs 3 bounds, not one per row.
FANOUT_AUDIT_MAX_FAILURES = 3

CLOSE_TOO_BIG = 1009
CLOSE_SLOW_CONSUMER = 4429

# --- Server-layer (uvicorn) limits: consumed by `candleviewer.server` --------
#: Headroom over the gateway frame cap so the gateway, not the transport, is
#: what answers an over-cap frame with its own close code on borderline sizes.
SERVER_WS_HEADROOM_BYTES = 4 * 1024
#: Transport-level max message size (applies to the decompressed message).
SERVER_WS_MAX_SIZE = MAX_INBOUND_FRAME_BYTES + SERVER_WS_HEADROOM_BYTES
#: §3.5: permessage-deflate is agreed for `cv.v1.json` only; `server.CvWebSocketsProtocol` withdraws
#: it from a `cv.v1.msgpack` upgrade. The size cap above bounds the inflated message.
SERVER_WS_PER_MESSAGE_DEFLATE = True
#: Small per-connection inbound queue; clients are limited to 30 frames/s (§16.2).
SERVER_WS_MAX_QUEUE = 4
#: Whole-process concurrent connection/task bound (8 per user x a few users).
SERVER_LIMIT_CONCURRENCY = 256


def json_depth_exceeds(text: str, limit: int) -> bool:
    """True if `text` nests `[`/`{` deeper than `limit` (string-aware, O(n)).

    A cheap pre-scan so a hostile frame never reaches the recursive decoder."""
    if text.count("[") + text.count("{") <= limit:
        return False  # cannot nest deeper than the number of openers
    depth = 0
    in_str = False
    esc = False
    for ch in text:
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch in "[{":
            depth += 1
            if depth > limit:
                return True
        elif ch in "]}":
            depth -= 1
    return False
