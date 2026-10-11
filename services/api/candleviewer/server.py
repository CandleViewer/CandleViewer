"""Process entrypoint: `python -m candleviewer.server [--reload]`.

Builds the uvicorn configuration from `candleviewer.ws.limits` and
`candleviewer.ws.lifecycle` so server-level WebSocket limits cannot drift from
the protocol (`23-ws-protocol.md` §16.2). Proxy-header handling keeps uvicorn's
defaults.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from typing import Any

import uvicorn

from candleviewer.settings import Settings, get_settings
from candleviewer.ws import limits
from candleviewer.ws.lifecycle import HEARTBEAT_INTERVAL_S, HEARTBEAT_TIMEOUT_S

APP = "candleviewer.main:app"


def uvicorn_kwargs(settings: Settings | None = None) -> dict[str, Any]:
    """Keyword arguments for `uvicorn.run`/`uvicorn.Config`.

    Host/port come from `Settings` (`CV_BIND_HOST` is validated against the wildcard
    address, C-12.9); WS limits from `ws/limits.py` (single source).
    """
    cfg = settings if settings is not None else get_settings()
    return {
        "host": cfg.bind_host,
        "port": cfg.bind_port,
        "ws_max_size": limits.SERVER_WS_MAX_SIZE,
        "ws_per_message_deflate": limits.SERVER_WS_PER_MESSAGE_DEFLATE,
        "ws_max_queue": limits.SERVER_WS_MAX_QUEUE,
        "ws_ping_interval": HEARTBEAT_INTERVAL_S,
        "ws_ping_timeout": HEARTBEAT_TIMEOUT_S,
        "limit_concurrency": limits.SERVER_LIMIT_CONCURRENCY,
    }


def main(argv: Sequence[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    unknown = [a for a in args if a != "--reload"]
    if unknown:
        raise SystemExit(f"unsupported arguments: {unknown}")
    uvicorn.run(APP, reload="--reload" in args, **uvicorn_kwargs())


if __name__ == "__main__":
    main()
