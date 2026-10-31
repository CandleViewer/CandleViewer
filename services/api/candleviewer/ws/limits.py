"""WS gateway resource limits (C-2.18; values from `23-ws-protocol.md` §3.6, §4.3).

Single home for every bound the gateway enforces. Overflow policy:

- Inbound frame > `MAX_INBOUND_FRAME_BYTES` -> close `1009` (checked on the
  raw text/bytes BEFORE JSON parsing, so an oversized frame is never decoded).
- Until the first `auth_ok`, a frame > `MAX_PREAUTH_FRAME_BYTES` -> close `1009` (checked the
  same way, so it is never scanned or decoded), and a MessagePack frame past the smaller value
  budget `ws/codec.py` sets for that window -> `frame_malformed`.
- Every inbound frame is charged against the connection's inbound rate (§8.5) before it is
  decoded, `inbound_frame_weight` tokens by its size, so a refused frame is never decoded; from
  the first `auth_ok` a frame that opens with `t: "pong"` takes from its own `pong` budget first.
- JSON text frame with > `MAX_JSON_CONTAINERS` `[` and `{` characters, or whose value count
  (`json_values_over_count`) is past the SR-185 value bound the gateway applies to both
  encodings (`codec.MAX_MSGPACK_VALUES`) -> `frame_malformed` (a protocol violation); it is never
  decoded. One within it is decoded (the cap bounds the C
  decoder's nesting), and a value nested deeper than `MAX_JSON_DEPTH` -> `frame_malformed` too.
- From the first `auth_ok`, a `pong` > `MAX_PONG_BYTES` -> `bye protocol_violation` + close `1002`
  (§8.5); one whose first member is `t: "pong"` is never decoded.
- `sub` with > `MAX_TOPICS_PER_SUB` topics -> the whole frame is refused with
  `too_many_topics` (`field: topics`) before any entry is read; nothing is subscribed (SR-192).
- The refusals of one `sub` that `ws.subscribe.denied` records -> ONE record for the frame, which
  counts them all and lists the first `MAX_DENIALS_LISTED` (SR-192, #2292).
- A connection's `ws.subscribe.denied` records past `DENIAL_AUDITS_PER_WINDOW` in any sliding
  `DENIAL_AUDIT_WINDOW_S` -> not written, each counted once; the `sub_ok` is unchanged (#3185).
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
- A `resync`, a `ctl` that would re-snapshot or a `sub` entry that would start a
  subscription, past the connection's or its user's rebuild budget -> `resync_rate_limited`; it
  changes nothing, and only a topic's own resync loop is revoked (SR-193).
- A connection's queued `bars.*` frames past
  `BARS_SHARE_PCT` of either limit of its outbound budget -> those topics alone are
  dropped and re-snapshotted (`drop_share`); no other family loses a frame (SR-E12-07).
"""

from __future__ import annotations

from typing import Any

MAX_INBOUND_FRAME_BYTES = 256 * 1024
#: §13.1 `envelope.id` `maxLength`, in characters. A request `id` that is not a string within it
#: is dropped before the frame is handled, so no reply echoes it (#2572).
ENVELOPE_ID_MAX_LEN = 64
#: §13 `common.schema.json#/$defs/subId` `maxLength`: a `resync` `p.sub_id` is a string of 1 to this
#: many characters, else refused with `invalid_options` (§7.5, #3218).
SUB_ID_MAX_LEN = 64
#: SR-184: max container nesting of an inbound frame. The deepest legitimate
#: client frame (`sub`/`ctl` envelope -> p -> options -> list -> object) is ~6
#: levels in ws-schema.json; 32 leaves headroom. A JSON frame is checked on its decoded value
#: (`json_nests_deeper`); the container cap below bounds the depth the decoder can reach.
MAX_JSON_DEPTH = 32
#: SR-040: max size, in encoded bytes, of an inbound frame until the first `auth_ok`, the `hello`
#: included. The largest conforming frame there, with each enum list naming every member once,
#: is an `auth` with the longest `access_token` the schema allows (4 096 characters) in ASCII,
#: about 4.2 KiB: this is about 1.9x that, and 1/32 of `MAX_INBOUND_FRAME_BYTES`. A non-ASCII
#: token of that many characters can exceed it, and is refused here. Checked on the raw frame
#: BEFORE any scan or decode.
MAX_PREAUTH_FRAME_BYTES = 8 * 1024
#: §8.5: max size, in encoded bytes, of a `pong` from the first `auth_ok`. A `pong` echoes the `id`
#: of the server `ping` it answers (ASCII, at most `ENVELOPE_ID_MAX_LEN` characters); with `ts` and
#: every heartbeat field at 2**53 - 1 it is about 210 bytes of JSON text, so this is headroom.
MAX_PONG_BYTES = 256
#: SR-184: max `[` plus `{` characters in an inbound JSON text frame. The count ignores strings,
#: so it can only over-count. The widest conforming frame, a `sub` of 50 topics with every option
#: the schema defines and every list full, has about 400: this is about 2.5x that. Checked BEFORE
#: the decode and the depth check.
MAX_JSON_CONTAINERS = 1024
#: §13.5 `maxItems` of `sub.topics` and `unsub.topics`, and `welcome.limits.max_topics_per_request`.
MAX_TOPICS_PER_SUB = 50
#: SR-192: the one `ws.subscribe.denied` record of a `sub` frame lists the `object_id` and
#: `reason` of at most this many of its refusals, in request order; its `count` holds them all.
MAX_DENIALS_LISTED = 10
#: #3185 (23 section 4.3): `ws.subscribe.denied` records one connection writes in any sliding
#: `DENIAL_AUDIT_WINDOW_S`, the CSRF and session-fixation refusal budgets' size and window. Past it
#: a frame's record is counted (`cv_ws_subscribe_denied_unaudited_total`), not written.
DENIAL_AUDITS_PER_WINDOW = 20
DENIAL_AUDIT_WINDOW_S = 60.0
MAX_SUBSCRIPTIONS = 200
#: §3.6 / §16.2 / `welcome.limits.max_outbound_frame_bytes`: the most one outbound frame holds; a
#: snapshot or a `bars` delta is split above it (`sequencing`). The number's one home (#572).
MAX_OUTBOUND_FRAME_BYTES = 4 * 1024 * 1024
#: §16.2 / welcome `limits.max_symbols_per_connection`; excess -> `subscription_limit`.
MAX_SYMBOLS_PER_CONNECTION = 40
#: §5.1 / §16.2 / welcome `limits.min_throttle_ms`: a requested throttle is raised to it (0 stays
#: 0 for `orders` and `executions`). The number's one home (#572); `ws/topics.py` names it.
MIN_THROTTLE_MS = 50
#: SR-E12-07 (§6.1): `bars.*` subscriptions per connection, live and replay; the next one gets
#: `subscription_limit`. With `history` <= 1 000 this bounds one socket's snapshot amplification.
MAX_BARS_SUBSCRIPTIONS = 16
#: E21-T01 (§6.1, §16.2, BQ-2): distinct (symbol, depth >= 200) `book` subscriptions per connection,
#: live and replay counted together; the next is refused `subscription_limit`. The default of the
#: `ws.max_deep_book_subs` setting (`CV_WS_MAX_DEEP_BOOK_SUBS`), which may lower it only.
MAX_DEEP_BOOK_SUBSCRIPTIONS = 4
#: The depth from which a `book` subscription counts against that cap.
DEEP_BOOK_MIN_DEPTH = 200
#: SR-E12-07 (§8.4): the share, in percent of each limit of a connection's outbound
#: budget, that its queued `bars.*` frames may hold, so `book` and `trades` are not starved.
BARS_SHARE_PCT = 50
#: SR-193 (§7.5, §16.2): the rebuild budget of a connection, which every snapshot a client causes
#: draws on: per subscription key, and in all, in any sliding `REBUILD_WINDOW_S`. The connection's
#: limit is a full attach of `MAX_SUBSCRIPTIONS` plus one full replace.
REBUILD_MAX_PER_TOPIC = 5
REBUILD_MAX_PER_CONNECTION = 2 * MAX_SUBSCRIPTIONS
REBUILD_WINDOW_S = 60.0
#: #3476 (§7.5, §16.2): the rebuild budget of a user, which every connection of the user draws on
#: too, in the same window. Fixed, never derived from `MAX_CONNECTIONS_PER_USER` (a setting can
#: raise that): one full attach of 8 connections of `MAX_SUBSCRIPTIONS`, the §16.2 defaults.
REBUILD_MAX_PER_USER = 4 * REBUILD_MAX_PER_CONNECTION
#: §16.2: `machines.{entity}.state` registry entries, live and terminal. Past it a payload for a
#: new entity is refused, counted and logged (rate-limited); no live entry is evicted, so no live
#: machine's state is lost.
MACHINE_ENTRIES_MAX = 20_000
#: §6.4: a terminal entry stays this long; at most `MACHINE_TERMINAL_MAX` are kept, oldest first.
MACHINE_TERMINAL_RETENTION_S = 60.0
MACHINE_TERMINAL_MAX = 10_000
#: §6.4: one retention-timer callback removes at most this many terminal entries; each removal
#: revokes its subscriptions (C-2.17), so the rest wait for the next loop turn.
#: It bounds one callback's hold, not the queue: 64 x 40 subscriptions (06 §10's plan, not a cap)
#: is 2 560 frames; more drops, counted. A user-scoped kind's entity has one user's 8 sockets.
MACHINE_SWEEP_BATCH = 64
#: §6.4: `revoked` frames of removals waiting for their audit writer (C-2.18). Past it the oldest
#: removal's rows are dropped, counted (`abandoned`) and logged.
MACHINE_AUDIT_PENDING_MAX = 4_096
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
#: each record of a `sub` frame, `ws.subscribe.denied` and `ws.subscribe.granted` (#2174).
FANOUT_AUDIT_TIMEOUT_S = 2.0
#: ...and on its rows as a whole: once this many rows in a row have raised or timed out, the rest
#: are abandoned, even when the writer is only slow: a stalled WAL costs 3 bounds, not one per row.
FANOUT_AUDIT_MAX_FAILURES = 3

CLOSE_TOO_BIG = 1009
CLOSE_SLOW_CONSUMER = 4429

# --- Server-layer (uvicorn) limits: consumed by `candleviewer.server` --------
#: Headroom over the gateway frame cap, so that the gateway, not the transport, answers a frame a
#: little over its cap (its `bye frame_too_big`, then `1009`). A fragmented message is charged
#: `WS_FRAGMENT_OVERHEAD_BYTES` per fragment against the same 4 KiB (#2176): at
#: `WS_MAX_FRAGMENTS_PER_MESSAGE` fragments, a message at the gateway cap fills it exactly, and a
#: larger one is closed by the transport (`1009`, no `bye`). It stays 4 KiB: clients send a message
#: in one frame, or a few large ones, so the charge there is a few hundred bytes at most.
SERVER_WS_HEADROOM_BYTES = 4 * 1024
#: Transport-level max message size (applies to the decompressed message).
SERVER_WS_MAX_SIZE = MAX_INBOUND_FRAME_BYTES + SERVER_WS_HEADROOM_BYTES
#: §3.5: permessage-deflate is agreed for `cv.v1.json` only; `server.CvWebSocketsProtocol` withdraws
#: it from a `cv.v1.msgpack` upgrade. The size cap above bounds the inflated message.
SERVER_WS_PER_MESSAGE_DEFLATE = True
#: Whole-process concurrent connection/task bound (8 per user x a few users). #2176: live WebSockets
#: are not counted against it (`server.CvHttpToolsProtocol`), so it stays for HTTP requests, the
#: REST control path and the kill switch included (C-2.21); the gateway bounds WebSockets
#: (`MAX_UNAUTHENTICATED_SOCKETS` before `auth_ok`, `MAX_CONNECTIONS_PER_USER` after it). A
#: WebSocket's handler still running after its connection is lost counts until it returns.
SERVER_LIMIT_CONCURRENCY = 256
#: #2176 (SR-191): seconds a kept-alive HTTP connection may stay idle after a response before it is
#: closed. uvicorn's own default, set here with the other server bounds; the first bytes of the
#: next request start `SERVER_READ_HEADER_TIMEOUT_S`.
SERVER_KEEP_ALIVE_TIMEOUT_S = 5
#: #2176: a connection that has not sent a complete request line and headers within this many
#: seconds of opening, or of its first bytes after a response, is closed, in both protocol classes
#: of `candleviewer.server`. It bounds how long a connection that has not completed its headers
#: can occupy one of the `SERVER_LIMIT_CONCURRENCY` slots, which the REST control path, the kill
#: switch included, needs (C-2.21). An answer sent before its request's body has all come starts
#: it too: the rest of that body and the next request line and headers come within it. A body the
#: app reads, and the rate at which connections open, are not bounded here. A client sends its
#: request line and headers in one write.
SERVER_READ_HEADER_TIMEOUT_S = 10.0
#: #2176: request line and headers that take more bytes than this get a 400 and the close, in the
#: HTTP protocol class (a WebSocket upgrade passes it first). 32 KiB is above what a browser sends
#: this API (its cookies are a CSRF token and a refresh token scoped to one route) and matches
#: nginx's default buffers (4 x 8 KiB). websockets bounds an upgrade per line (8 192 B) and per
#: header count (128), about 1 MiB in all, so this is the tighter total; a request past one of those
#: by one long line or one header too many still fits under it and gets websockets' 414 or 431.
SERVER_MAX_REQUEST_HEAD_BYTES = 32 * 1024
#: #2176: a message of more than this many fragments (its first frame and the continuation
#: frames after it) is refused with `1009`, as `frame_too_big` is. 64 carries a message at the
#: gateway cap (`MAX_INBOUND_FRAME_BYTES`) in fragments of 4 KiB.
WS_MAX_FRAGMENTS_PER_MESSAGE = 64
#: #2176: charged per fragment against `SERVER_WS_MAX_SIZE`, which websockets counts in payload
#: bytes: a buffered fragment costs about 42 B more than its payload in uvicorn's protocol
#: (measured on 0.54.0: 43 B for 1 B, 50 B for 8 B). `SERVER_WS_HEADROOM_BYTES` covers the charge
#: on a message at the gateway cap in `WS_MAX_FRAGMENTS_PER_MESSAGE` fragments.
WS_FRAGMENT_OVERHEAD_BYTES = 64
#: #2176: the bound on the WebSocket protocol's inbound message queue, in messages kept for the
#: app at once. Past it the rest of a read is held unparsed, and reading stays paused, until the
#: app has read the queue. A read is parsed in pieces of this many smallest client frames (6 KiB),
#: the next only once the queue is empty: the queue's bytes are bounded by the messages one piece
#: completes, decompressed (each at most `SERVER_WS_MAX_SIZE`). With permessage-deflate one 6 KiB
#: piece can complete about 23 frames whose payloads inflate to that cap, so a connection's queue
#: can hold about 6 MiB before reading pauses; the gateway's rate and size checks apply as each
#: message is read. A client within the inbound rate (30/s, 300/min, §8.5) sends at most 300
#: messages a minute.
WS_MAX_QUEUED_MESSAGES = 1024
#: #2176: every inbound WebSocket frame (data, continuation, ping, pong) takes one token of a
#: per-connection bucket of `WS_INBOUND_FRAME_BURST` tokens, refilled at this rate; a frame that
#: finds none closes the connection `4429`, counted as `client_rate_limited`. A client within the
#: gateway's inbound rate sends at most 30 messages in a second and 300 a minute (5 a second over
#: time), a message in one frame or a few, plus a `pong` to the server's ping every 15 s: 64 a
#: second is over 12x that sustained rate and twice its one-second burst.
WS_INBOUND_FRAMES_PER_S = 64
#: #2176: the frame bucket's size: 30 messages of 8 frames, or a message in 64 fragments, with room.
WS_INBOUND_FRAME_BURST = 256
#: #2176: seconds a closed connection's transport may take to send what it still holds; then it is
#: aborted. A transport's close waits for its write buffer to drain, which a peer that stops
#: reading never lets happen; a reading peer drains a full buffer (64 KiB over the kernel's) in
#: well under this on loopback or the tailnet. The bound assumes a response written under flow
#: control (chunks of at most the transport's high-water mark). A route that returns a large
#: artefact must stream it (`FileResponse`, `StreamingResponse`): one `send()` of the whole body
#: starts uvicorn's keep-alive timer at the write, so the close comes 5 s after it and this
#: bound's abort 5 s after the close.
SERVER_CLOSE_DRAIN_TIMEOUT_S = 5.0


def json_depth_exceeds(text: str, limit: int) -> bool:
    """True if `text` nests `[`/`{` deeper than `limit` (string-aware, O(n)).

    A cheap pre-scan so a hostile frame never reaches the recursive decoder. The REST bodies that
    take JSON still call it before they parse; the WS gateway checks the decoded value instead
    (`json_nests_deeper`, #4924), and its tests check that one against this."""
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


#: §8.5 (#4924, an orchestrator contract decision of 2026-10-29): an inbound frame takes one token
#: of the inbound rate, plus one per full 32 KiB of its encoded bytes, plus one per full 4 096
#: values (`INBOUND_WEIGHT_VALUES`). A JSON frame's values are its pre-decode over-count
#: (`json_values_over_count`); a MessagePack frame's are bounded by twice its size, as its decoder
#: charges a container twice (itself, and as an element) and every value takes at least one byte.
#: Either is charged with the rest before the frame is decoded, counted up to one past the value
#: bound; a MessagePack frame gets back, after its decode, what that bound took past the values its
#: decoder charged. A frame at `MAX_INBOUND_FRAME_BYTES` takes 9 for its
#: bytes; one at the value bound 4 more; a `pong` takes 1.
INBOUND_WEIGHT_BYTES = 32 * 1024
INBOUND_WEIGHT_VALUES = 4096
#: §8.5 (#4924): a MessagePack frame also takes one token per full 512 containers. Its decoder
#: calls a hook per container, so a frame of many small containers costs more than its bytes and
#: values show; JSON's decoder builds them in C. Bounded before decode by its size (a container
#: takes a byte), up to one past `MAX_JSON_CONTAINERS`; what that took past the containers its
#: decoder counted is given back after it.
INBOUND_WEIGHT_CONTAINERS = 512


def inbound_frame_weight(size: int, values: int = 0, containers: int = 0) -> int:
    """The inbound-rate tokens of a frame of `size` encoded bytes holding `values` values and,
    for MessagePack, `containers` containers (§8.5). The caller counts each only up to one past
    its bound (`codec.MAX_MSGPACK_VALUES`, `MAX_JSON_CONTAINERS`), so a frame past one is refused
    as `frame_malformed`, never priced out of the rate's reach."""
    return (
        1
        + size // INBOUND_WEIGHT_BYTES
        + values // INBOUND_WEIGHT_VALUES
        + containers // INBOUND_WEIGHT_CONTAINERS
    )


def json_values_over_count(text: str) -> int:
    """An upper bound on the values JSON `text` holds, counted as SR-185 charges a MessagePack
    frame (each container, array element, object key and object value is one), from its characters
    alone and before any decode.

    In valid JSON every value but the top-level one, and every key, comes right after exactly one
    structural `[`, `{`, `,` or `:`: an array's first element after its `[`, an object's first key
    after its `{`, each later element or key after a `,`, each value after its key's `:`. So the
    count of those four characters, plus one, is at least the frame's values. It can only
    over-count: an empty container's `[` or `{` precedes nothing, and the characters inside
    strings are counted too. Each count is one pass in C."""
    return 1 + text.count("[") + text.count("{") + text.count(",") + text.count(":")


#: The containers a decoded JSON value holds (`json_nests_deeper`): `json.loads` builds exact lists
#: and dicts, so a type lookup finds them (much faster than `isinstance` on every element).
_JSON_CONTAINERS: frozenset[type] = frozenset({list, dict})


def json_nests_deeper(value: object, limit: int) -> bool:
    """True if a decoded JSON `value` nests lists and objects deeper than `limit`: the depth
    `json_depth_exceeds` reads from the text, where a top-level container is depth 1.

    Iterative, a level at a time, so no input can exhaust the stack; it reads each element once
    and stops at the first level past `limit`."""
    level: list[Any] = [value] if type(value) in _JSON_CONTAINERS else []
    depth = 0
    while level:
        depth += 1
        if depth > limit:
            return True
        below: list[Any] = []
        for node in level:
            items = node.values() if type(node) is dict else node
            below += [item for item in items if type(item) in _JSON_CONTAINERS]
        level = below
    return False
