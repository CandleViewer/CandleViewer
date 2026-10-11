# Runbook: WebSocket server limits

The API container starts through `python -m candleviewer.server`, which builds the uvicorn
configuration from `candleviewer/ws/limits.py` (single source; protocol `23-ws-protocol.md` §16.2).
Do not pass `--ws-*` flags or override the entrypoint in compose; edit `ws/limits.py` instead.

| Setting | Value | Source |
|---|---|---|
| `ws_max_size` | inbound frame cap + 4 KiB headroom | `SERVER_WS_MAX_SIZE` |
| `ws_per_message_deflate` | on (JSON encoding only; size-capped) | `SERVER_WS_PER_MESSAGE_DEFLATE` |
| `ws_max_queue` | 4 | `SERVER_WS_MAX_QUEUE` |
| `limit_concurrency` | 256 | `SERVER_LIMIT_CONCURRENCY` |
| `ws_ping_interval` / `ws_ping_timeout` | 15 s / 45 s | `ws/lifecycle.py` heartbeat |

`proxy_headers` keeps the uvicorn default. Symptom of a too-small cap: clients closed with 1009.
Regression test: `tests/unit/ws/test_server_limits.py`.
