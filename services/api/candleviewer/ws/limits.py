"""WS gateway resource limits (C-2.18; values from `23-ws-protocol.md` §3.6, §4.3).

Single home for every bound the gateway enforces. Overflow policy:

- Inbound frame > `MAX_INBOUND_FRAME_BYTES` -> close `1009` (checked on the
  raw text/bytes BEFORE JSON parsing, so an oversized frame is never decoded).
- `sub` with > `MAX_TOPICS_PER_SUB` topics -> the excess topics are rejected
  per-topic with `too_many_topics`; the rest are processed.
- A subscription that would grow a connection past `MAX_SUBSCRIPTIONS` ->
  rejected per-topic with `subscription_limit`; the set never grows past it.
- No successful `auth` within `AUTH_TIMEOUT_S` -> `bye auth_timeout` + close `4401`.
- `permission_change` / `revoked` fan-out: each socket's frame is sent under
  `FANOUT_SEND_TIMEOUT_S`; a stalled or failing socket is dropped from the
  registry and closed (`4429` slow consumer) so it cannot block the role-change
  request or the other sockets. Its now-forbidden subscriptions are already
  removed synchronously before any send.
"""

from __future__ import annotations

MAX_INBOUND_FRAME_BYTES = 256 * 1024
MAX_TOPICS_PER_SUB = 50
MAX_SUBSCRIPTIONS = 200
#: §16.2 / welcome `limits.max_symbols_per_connection`; excess -> `subscription_limit`.
MAX_SYMBOLS_PER_CONNECTION = 40
AUTH_TIMEOUT_S = 10.0
FANOUT_SEND_TIMEOUT_S = 2.0

CLOSE_TOO_BIG = 1009
CLOSE_SLOW_CONSUMER = 4429

# --- Server-layer (uvicorn) limits: consumed by `candleviewer.server` --------
#: Headroom over the gateway frame cap so the gateway, not the transport, is
#: what answers an over-cap frame with its own close code on borderline sizes.
SERVER_WS_HEADROOM_BYTES = 4 * 1024
#: Transport-level max message size (applies to the decompressed message).
SERVER_WS_MAX_SIZE = MAX_INBOUND_FRAME_BYTES + SERVER_WS_HEADROOM_BYTES
#: `cv.v1.json` negotiates permessage-deflate (§5); the size cap above bounds it.
SERVER_WS_PER_MESSAGE_DEFLATE = True
#: Small per-connection inbound queue; clients are limited to 30 frames/s (§16.2).
SERVER_WS_MAX_QUEUE = 4
#: Whole-process concurrent connection/task bound (8 per user x a few users).
SERVER_LIMIT_CONCURRENCY = 256
