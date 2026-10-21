"""`X-Content-Type-Options: nosniff` on every HTTP response of the API (#3990, finding X03-F9,
ZAP 10021).

`NoSniff` is a pure ASGI wrapper that `create_app`'s `_StampedApp` puts outside every user
middleware and Starlette's error middleware, as `NoStoreNoReferrer`: only the outermost layer sees
every answer, a guard's refusal and an unhandled exception's `500` included (that `500` never
passes `CorrelationMiddleware`'s `send` wrapper either). The header is set, not appended: a value a
route already sent (the backup fetch's) is replaced, so a response carries it once. Only `http`
scopes are touched; a WebSocket handshake and the lifespan pass through as they came.
"""

from __future__ import annotations

from typing import Final

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

NOSNIFF_HEADER: Final = "X-Content-Type-Options"
NOSNIFF_VALUE: Final = "nosniff"


class NoSniff:
    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        async def stamped(message: Message) -> None:
            if message["type"] == "http.response.start":
                message.setdefault("headers", [])
                MutableHeaders(scope=message)[NOSNIFF_HEADER] = NOSNIFF_VALUE  # replaces
            await send(message)

        await self._app(scope, receive, stamped)
