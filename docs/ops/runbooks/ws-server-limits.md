# Runbook: WebSocket server limits

The API container starts through `python -m candleviewer.server`, which builds the uvicorn
configuration from `candleviewer/ws/limits.py` (single source; protocol `23-ws-protocol.md` §16.2).
Do not pass `--ws-*` flags or override the entrypoint in compose; edit `ws/limits.py` instead.

| Setting                                | Value                                | Source                          |
| -------------------------------------- | ------------------------------------ | ------------------------------- |
| `ws_max_size`                          | inbound frame cap + 4 KiB headroom   | `SERVER_WS_MAX_SIZE`            |
| `ws_per_message_deflate`               | on (JSON encoding only; size-capped) | `SERVER_WS_PER_MESSAGE_DEFLATE` |
| `limit_concurrency`                    | 256; live WebSockets not counted     | `SERVER_LIMIT_CONCURRENCY`      |
| `ws_ping_interval` / `ws_ping_timeout` | 15 s / 45 s                          | `ws/lifecycle.py` heartbeat     |
| `timeout_keep_alive`                   | 5 s idle between HTTP requests       | `SERVER_KEEP_ALIVE_TIMEOUT_S`   |
| request line and headers deadline      | 10 s, in both protocol classes       | `SERVER_READ_HEADER_TIMEOUT_S`  |
| fragments per WebSocket message        | 64                                   | `WS_MAX_FRAGMENTS_PER_MESSAGE`  |
| size charged per fragment              | 64 B, against `ws_max_size`          | `WS_FRAGMENT_OVERHEAD_BYTES`    |
| request line and headers size          | 32 KiB, in the HTTP protocol class   | `SERVER_MAX_REQUEST_HEAD_BYTES` |
| messages queued per WebSocket          | 1 024, then reading pauses           | `WS_MAX_QUEUED_MESSAGES`        |
| frames per WebSocket, at once          | 256, then 4429                       | `WS_INBOUND_FRAME_BURST`        |
| frames per WebSocket, refill           | 64 a second                          | `WS_INBOUND_FRAMES_PER_S`       |
| drain after a close, or a peer's FIN   | 5 s, then the transport is aborted   | `SERVER_CLOSE_DRAIN_TIMEOUT_S`  |

`proxy_headers` is off (see below). Symptom of a too-small cap: clients closed with 1009.
Regression test: `tests/unit/ws/test_server_limits.py`.

Deflate per subprotocol (on for `cv.v1.json`, off for `cv.v1.msgpack`, protocol §3.5) comes from
`ws=CvWebSocketsProtocol` in `uvicorn_kwargs()`: any other start also deflates `cv.v1.msgpack`.

The rows from the request deadline on, and `limit_concurrency`'s exclusion of WebSockets, live in
the protocol classes that `uvicorn_kwargs()` passes (`http=CvHttpToolsProtocol`,
`ws=CvWebSocketsProtocol`, #2176): any other start has none of them.

- A client that sends its request line and headers slower than the deadline (10 s from the
  connection's opening, or from its first bytes after a response) is closed with no response, no
  log line and no metric. On an upgrade it bounds the request line and headers, not the `101`
  (the "Upgrade complete within" row of `23-ws-protocol.md` §16.2).
- Request line and headers over 32 KiB get uvicorn's `400` and the close, with the warning
  `Request line and headers too large.` on `uvicorn.error`. A WebSocket upgrade is an HTTP request
  until then, so it meets this bound first.
- An upgrade under 32 KiB with a line over 8 192 bytes, or more than 128 headers, gets websockets'
  `414` or `431` at once, and the close.
- A request answered before its body has all come gets its answer, and the rest of the body is
  read and let go of, as uvicorn does. The answer starts the deadline: the rest of the body and the
  next request line and headers must come within 10 s of it, or the connection is closed (one that
  gets nothing at all after the answer is closed earlier, at 5 s, by `timeout_keep_alive`). An
  upload still coming at 10 s is cut; this API takes small JSON bodies.
- A WebSocket message of more than 64 fragments, or over `ws_max_size` with the charge per
  fragment, is closed with 1009 and counted in `cv_ws_closes_total{reason="frame_too_big"}`, as
  the gateway counts its own refusal (no `bye`).
- Past 1 024 messages queued for the app, the WebSocket protocol leaves the rest of a read
  unparsed, and reading paused, until the app has read the queue: nothing is refused or lost.
- Every inbound WebSocket frame (data, continuation, ping, pong) takes one token of a bucket of
  256, refilled at 64 a second; a frame that finds none closes the connection with 4429 and is
  counted in `cv_ws_closes_total{reason="client_rate_limited"}` (no `bye`). While the transport's
  write buffer is over its high-water mark, the client's pings get one pong, for the latest, sent
  once it drains; reading goes on.
- A connection the server has closed, or whose peer has closed its side (FIN), and whose
  transport has not sent what it holds within 5 s is aborted. The bound is on the total drain
  time, not on a stall: it cuts a peer that stopped reading, and also one that reads more slowly
  than what is held over 5 s, a peer that has sent its FIN included.
- Live WebSockets do not count against `limit_concurrency`: with every slot held by them, a REST
  request is still answered, and a request on the 256th HTTP connection gets uvicorn's 503. A
  WebSocket's handler still running after its connection is lost (its close's audit write) counts
  until it returns.

Regression tests: `tests/unit/ws/test_request_header_deadline_real_socket.py`,
`tests/unit/ws/test_server_ws_frames.py` and `tests/unit/ws/test_server_limits.py`.

## Forwarded headers and a reverse proxy (#2275)

uvicorn's proxy-header handling is off (`proxy_headers=False` in `candleviewer.server`): uvicorn
never rewrites the client address or the scheme from `X-Forwarded-For` / `X-Forwarded-Proto`, and
`FORWARDED_ALLOW_IPS` has no effect. The mesh guard (`MeshOnlyMiddleware`) judges the TCP peer, and
logs and audit records carry the address it admitted (`source_ip`, `actor_ip`). Do not pass
`--proxy-headers` or `--forwarded-allow-ips`, and do not start a deployment with the bare `uvicorn`
CLI: its default turns proxy headers back on.

The only forwarded-header setting is the mesh guard's trusted proxy. Behind a reverse proxy (for
example the TLS-terminating app proxy, SR-049):

1. Make the proxy send one `X-Forwarded-For` line that ends with the client's address (the
   right-most hop). Only that hop is read; every hop to its left comes from the client and is
   ignored. A request from the proxy that carries the header more than once is refused (403): the
   line the proxy wrote cannot be told apart from lines the client sent.
2. Set both `CV_MESH_TRUSTED_PROXY_HEADER=x-forwarded-for` and `CV_MESH_TRUSTED_PROXY_ADDRESS` to
   the proxy's address as the API sees it (the TCP peer, as an IP address: `127.0.0.1` for a proxy
   on the same host). The header is read only when the TCP peer is that address. The API refuses
   to start when only one of the two is set, when the address is not an IP address (a hostname,
   `host:port` or a CIDR), or when the header is not a header name.
3. Restart the API, sign in through the proxy, and check that the `auth.login` audit record's
   `actor_ip` is the client's mesh address, not the proxy's.

Without step 2, every request through the proxy is judged and recorded as the proxy's address
(a proxy on loopback is always admitted) and shares one sign-in throttle bucket. With it, the
sign-in throttle, the session record, invites and the audit-read principal use the admitted
address, as the logs and the audit do. A trusted proxy address on loopback is trusted for every
local process, so any process on the host can then name an address through the header; give the
proxy its own address where the deployment allows it. Regression tests:
`tests/unit/net/test_forwarded_header_trust.py` and
`tests/security/auth/test_trusted_proxy_readers.py`.

## Logging

`candleviewer.server` passes `log_config=None`, so uvicorn installs no handlers of its own. Its
`uvicorn`, `uvicorn.error` and `uvicorn.access` loggers propagate to the root handler that
`configure_logging()` sets up: JSON lines on stdout, through the handler-level redaction filter
(SR-121), at `CV_LOG_LEVEL`. The same records reach the support bundle's log buffer
(`LogRingBuffer`), which applies the redaction filter on its own and passes each stdlib record's
rendered message through the same redaction as stdout. What that looks like:

- **Fields.** uvicorn's lines carry `event`, `level` and `ts` (and `exception` or `stack` for a
  record with a traceback or a stack): no `env` and no logger name, as for every stdlib logger.
- **Labelled values.** In message and exception text, a value labelled with a key name of the
  redaction list (`token = …`, `"password": "…"`, `Authorization: Bearer …`, pydantic's
  `input_value=…`) shows the key-name marker (#415): a quoted value to its closing quote, a
  `Cookie` or `Set-Cookie` header's and pydantic's input to the line's end, and any other bare one
  to a space, comma or closing bracket, so a list or a dict is read only as far, and a quote that
  closes an enclosing string is taken as part of the value, to the line's end. A placeholder
  (`***`, `null`, `<omitted>`, a marker) is no value only as the whole value, or right before a
  `...[truncated:oversize]` marker. A dotted id is no label: a name after a `.`, then a `:` and
  neither a space (an escaped line break counts as one) nor a quote, so a WS machine topic such as
  `machines.session:<id>.state` stays readable. The rule reads by form only, so a dotted name whose
  `:` is followed at once by its value (`cfg.token:shortone`) reads as an id too, and only the shape
  pass applies to it. A dotted attribute and its value is a label: `self.password='…'`,
  `obj.api_secret=…` and `cfg.token: …` show the key-name marker. A format string is left as it is,
  so `%` formatting works; the line it renders is redacted.
- **Tracebacks.** A traceback or a stack is rendered first and redacted after (#415), on stdout and
  in the support bundle's buffer (on one line there), where each value stands: a labelled value
  shows the key-name marker, a backup download path (to the end of its token) shows
  `[redacted:download-path]`, and each run of characters that has the shape of a secret shows its
  marker, so the frames and lines stay readable. On the last line, most exception classes with a
  name of 18 or more letters show as a marker (`ConnectionResetError: …` shows
  `[redacted:key-shape]: …`), as does a dotted name of three parts of 10 or more characters each
  (`websockets.exceptions.ConnectionClosedOK`). A text longer than 4096 characters and the marker
  keeps 4096: its start and its last lines (up to 3072), around a `...[truncated:oversize]` marker,
  so the exception's own line stays. A cut that lands inside a backup download token leaves the
  path's marker only, which takes the cut's marker with it. Paths nested in one another, or a cut
  right after a path's `/download/`, make the whole text the marker, as for a message line. An
  exception logged as a value or an argument is turned into its text first: with Python's own
  `__str__`, from its arguments redacted first (a mapping's keys and bytes get their rules); any
  other gets the text rules only, the labels and the shapes.
  Passed for `%r`, it shows as its quoted text, not as `ValueError('…')`. A traceback that uvicorn
  logs as the text of a message, as in a failed start below, is still one marker when a shape
  matches in it (#2868).
- **Support bundle.** The buffer writes each record on one line, a line break as `\n`, as in a
  traceback. The bundle's secret scan refuses a bundle (`BUNDLE_SECRET_DETECTED`) for a line that
  still matches one of its rules.
  The error names the file and the rule, not the value: find the line on
  stdout for the same window, follow the `SupportBundleSecretDetected` alert runbook, and choose a
  window without it meanwhile.
- **Access lines.** The HTTP access line is off whenever the `/metrics` listener runs
  (`CV_METRICS_ENABLED`, on by default): the listener's `access_log=False` clears the shared
  `uvicorn.access` logger. WebSocket handshake lines (`"WebSocket /ws" [accepted]`) are logged on
  `uvicorn.error` at INFO and stay on. A filter on that logger (`UpgradeLineFilter`) cuts the
  request target in those lines and in the websockets server's DEBUG request line to its path, and
  shows a marker for the value of a DEBUG header line named as a secret, whatever `CV_LOG_LEVEL`
  is, on stdout and in the support bundle's buffer; the HTTP access line is unchanged.
- **Process ids.** A six-digit process id turns `Started server process [N]` and
  `Finished server process [N]` into a single `[redacted:totp-shape]` marker, because six digits
  is the shape of a TOTP code. PID 1, as in the container, avoids it.
- **Dev `--reload`.** The reloader's supervisor process never loads the app, so its INFO banners
  (`Will watch for changes...`, `Uvicorn running on...`) are not printed, and its warnings come out
  as plain text on stderr. The served child process logs JSON.
- **Exit.** The log queue is written out when the interpreter exits, so the last line of a failed
  start is not lost. Outside a container's PID 1, a process that uvicorn ends by re-raising SIGTERM
  after its graceful shutdown is killed by the signal: no `atexit` hook runs, and its final line
  can be missing.
- The bare `uvicorn` CLI applies uvicorn's own logging config instead, which is one more reason
  not to start a deployment with it.

Regression tests: `tests/unit/observability/test_uvicorn_log_routing.py`,
`tests/unit/observability/test_exception_text_redaction.py` and
`tests/unit/observability/test_logging_exit_flush.py`.

### A failed start (exit code 3)

A start that fails inside the lifespan exits with code 3. stderr stays empty, the last line is
`Application startup failed. Exiting.`, and the line before it, the cause, is one marker:
`{"event":"[redacted:key-shape]","level":"error",...}`. uvicorn logs the whole traceback as a single
text, and the redaction filter replaces a text by one marker when any token in it has the shape of
a secret. An exception class name such as `ConnectionRefusedError` is enough. (#2868 tracks
token-level redaction, which would keep the cause readable.) Keep redaction on and find the cause
from what the lifespan depends on. `candleviewer/app.py` starts the modules in
`_SUPERVISOR_ORDER` (`storage`, `audit`, `secrets`, `auth`, ..., `rules`, ...) and the first one
that raises ends the start. Check, in this order:

1. **The stores answer.** Postgres at `CV_PG_DSN` (the first module to read it at start, such as
   `rules`, fails if it cannot connect) and, with `CV_STORAGE_BACKEND=real`, QuestDB at
   `CV_QUESTDB_PG` and `CV_QUESTDB_ILP`. In the compose stack `docker compose ps -a` shows the
   `api` container as `Exited (3)` and whether `postgres` and `questdb` are `healthy`, which `api`
   waits for. `pg_isready -h <host> -p <port>` checks Postgres alone.
2. **The schema is at head.** From `services/api`, with `CV_PG_DSN` set to the same database,
   `alembic current` should print the revision that `alembic heads` prints, and
   `alembic upgrade head` applies the rest (AGENTS.md section 4). On a deployed stack run the storage
   migrate step instead (`docs/ops/runbooks/storage-migrate.md`): it applies these revisions and the
   QuestDB DDL together, and nothing else creates the QuestDB tables. An older schema makes the first
   query that needs a newer table or column fail.
3. **The KEK settings are accepted.** `CV_KEK_SOURCE`, `CV_KEK_HANDLE`, `CV_KEK_ACK_PATH` and
   `CV_KEK_VERSION`: the start refuses a live read-once FIFO handle with no `CV_KEK_ACK_PATH`
   (`kek_source_not_permitted`). Any other KEK problem does not fail the start: the app comes up
   read-only and logs `secrets.kek_unavailable` with a reason, see
   `docs/ops/runbooks/kek-custody.md`.

An exit code of 1 with a Python traceback on stderr is a different failure: a setting was refused
before the lifespan began, for example `CV_KEK_SOURCE=file` in live (`kek_source_not_permitted`).
The message names the setting.
