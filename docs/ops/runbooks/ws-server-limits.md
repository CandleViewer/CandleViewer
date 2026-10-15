# Runbook: WebSocket server limits

The API container starts through `python -m candleviewer.server`, which builds the uvicorn
configuration from `candleviewer/ws/limits.py` (single source; protocol `23-ws-protocol.md` §16.2).
Do not pass `--ws-*` flags or override the entrypoint in compose; edit `ws/limits.py` instead.

| Setting                                | Value                                | Source                          |
| -------------------------------------- | ------------------------------------ | ------------------------------- |
| `ws_max_size`                          | inbound frame cap + 4 KiB headroom   | `SERVER_WS_MAX_SIZE`            |
| `ws_per_message_deflate`               | on (JSON encoding only; size-capped) | `SERVER_WS_PER_MESSAGE_DEFLATE` |
| `ws_max_queue`                         | 4                                    | `SERVER_WS_MAX_QUEUE`           |
| `limit_concurrency`                    | 256                                  | `SERVER_LIMIT_CONCURRENCY`      |
| `ws_ping_interval` / `ws_ping_timeout` | 15 s / 45 s                          | `ws/lifecycle.py` heartbeat     |

`proxy_headers` is off (see below). Symptom of a too-small cap: clients closed with 1009.
Regression test: `tests/unit/ws/test_server_limits.py`.

## Forwarded headers and a reverse proxy (#2275)

uvicorn's proxy-header handling is off (`proxy_headers=False` in `candleviewer.server`): uvicorn
never rewrites the client address or the scheme from `X-Forwarded-For` / `X-Forwarded-Proto`, and
`FORWARDED_ALLOW_IPS` has no effect. The mesh guard (`MeshOnlyMiddleware`) judges the TCP peer, and
logs and audit records carry the address it admitted (`source_ip`, `actor_ip`). Do not pass
`--proxy-headers` or `--forwarded-allow-ips`, and do not start a deployment with the bare `uvicorn`
CLI: its default turns proxy headers back on.

The only forwarded-header setting is the mesh guard's trusted proxy. Behind a reverse proxy (for
example the TLS-terminating app proxy, SR-049):

1. Make the proxy append the client's address as the right-most `X-Forwarded-For` hop. Only that
   hop is read; every hop to its left comes from the client and is ignored.
2. Set both `CV_MESH_TRUSTED_PROXY_HEADER=x-forwarded-for` and `CV_MESH_TRUSTED_PROXY_ADDRESS` to
   the proxy's address as the API sees it (the TCP peer: `127.0.0.1` for a proxy on the same host).
   The header is read only when the TCP peer is that address; with only one of the two set, it is
   never read.
3. Restart the API, sign in through the proxy, and check that the `auth.login` audit record's
   `actor_ip` is the client's mesh address, not the proxy's.

Without step 2, every request through the proxy is judged and recorded as the proxy's address
(a proxy on loopback is always admitted). A trusted proxy address on loopback is trusted for
every local process, so any process on the host can then name an address through the header;
give the proxy its own address where the deployment allows it. Known gap (#2620): the sign-in
throttle, the session record, invites and the audit-read principal still read the TCP peer, so
behind the proxy they see the proxy's address. Regression test:
`tests/unit/net/test_forwarded_header_trust.py`.
