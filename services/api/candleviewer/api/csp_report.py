"""`POST /api/v1/csp-report`: the receiver for CSP violation reports (SR-112, E43-T01).

Browsers send a report with no credential and no CSRF token, so the endpoint is public by
contract (`security: []` in `22-api-openapi.yaml`) and is served by a pure ASGI layer at the
outermost edge of the app, beside `ContentSecurityPolicy`, before any session/RBAC middleware: the
only things it can do are count and log, and it is bounded on every side (C-2.18):

- a body cap (`MAX_BODY_BYTES`, `413`; a declared `Content-Length` over it is refused unread);
- a per-client-IP fixed window (`MAX_REPORTS_PER_WINDOW` per `WINDOW_S`, `429` + `Retry-After`)
  over a bounded table (`MAX_TRACKED_CLIENTS`, expired entries dropped first, then the oldest);
- at most `MAX_ENTRIES_PER_REQUEST` violations read from one body.

A violation is reduced to a closed `directive`, a closed `blocked_type` and, for a network
resource, the blocked scheme's host: never a path, query, fragment, userinfo, port, source file,
sample or any other member of the report. The counter `cv_csp_violations_total{directive,
blocked_type}` and the `security.csp_violation` log line carry only those.
"""

from __future__ import annotations

import json
import re
import time
from collections import OrderedDict
from collections.abc import Callable
from typing import Any, Final, Protocol
from urllib.parse import urlsplit

import structlog
from starlette.types import ASGIApp, Message, Receive, Scope, Send

METRIC_NAME: Final = "cv_csp_violations_total"
REPORT_PATHS: Final = frozenset({"/api/v1/csp-report", "/csp-report"})
MAX_BODY_BYTES: Final = 8 * 1024
MAX_REPORTS_PER_WINDOW: Final = 30
WINDOW_S: Final = 60.0
MAX_TRACKED_CLIENTS: Final = 512
MAX_ENTRIES_PER_REQUEST: Final = 10
ACCEPTED_MEDIA_TYPES: Final = frozenset(
    {"application/csp-report", "application/reports+json", "application/json"}
)
DIRECTIVES: Final = frozenset(
    {
        "default-src", "script-src", "script-src-elem", "script-src-attr", "style-src",
        "style-src-elem", "style-src-attr", "img-src", "font-src", "connect-src", "media-src",
        "object-src", "frame-src", "child-src", "worker-src", "manifest-src", "prefetch-src",
        "base-uri", "form-action", "frame-ancestors", "navigate-to",
    }
)  # fmt: skip
BLOCKED_TYPES: Final = (
    "inline", "eval", "data", "blob", "http", "https", "ws", "wss", "other",
)  # fmt: skip
_HOST_RE: Final = re.compile(r"^[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?$")
_NETWORK_SCHEMES: Final = frozenset({"http", "https", "ws", "wss"})
_KEYWORDS: Final = {
    "inline": "inline",
    "eval": "eval",
    "wasm-eval": "eval",
    "trusted-types-policy": "other",
}


class ViolationCounter(Protocol):
    def labels(self, *values: str) -> Any: ...


def _log() -> Any:
    return structlog.get_logger(__name__)


def normalise_directive(raw: object) -> str:
    """The first token of a directive name, lower-cased, from the closed set, else `other`."""
    token = raw.split(None, 1)[0].lower() if isinstance(raw, str) and raw.strip() else ""
    return token if token in DIRECTIVES else "other"


def classify_blocked(raw: object) -> tuple[str, str | None]:
    """(`blocked_type`, host): the closed type of a blocked resource and, for a network one, its
    scheme-checked host. Nothing else of the URL survives."""
    if not isinstance(raw, str) or not raw or len(raw) > 2048:
        return "other", None
    lowered = raw.strip().lower()
    if lowered in _KEYWORDS:
        return _KEYWORDS[lowered], None
    if lowered.startswith(("data:", "blob:")):
        return lowered.split(":", 1)[0], None
    try:
        parts = urlsplit(raw.strip())
        scheme, host = parts.scheme.lower(), (parts.hostname or "").lower()
    except ValueError:
        return "other", None
    if scheme not in _NETWORK_SCHEMES:
        return "other", None
    return scheme, host if _HOST_RE.fullmatch(host) else None


def extract_violations(payload: object) -> list[tuple[str, str, str | None]]:
    """(directive, blocked_type, host) per violation in a legacy `report-uri` body
    (`{"csp-report": {...}}`) or a Reporting API one (`[{"type": "csp-violation", "body": {}}]`)."""
    bodies: list[dict[str, Any]] = []
    if isinstance(payload, dict) and isinstance(payload.get("csp-report"), dict):
        bodies.append(payload["csp-report"])
    elif isinstance(payload, list):
        for item in payload[:MAX_ENTRIES_PER_REQUEST]:
            if isinstance(item, dict) and item.get("type") == "csp-violation":
                if isinstance(item.get("body"), dict):
                    bodies.append(item["body"])
    out: list[tuple[str, str, str | None]] = []
    for body in bodies[:MAX_ENTRIES_PER_REQUEST]:
        directive = normalise_directive(
            body.get("effective-directive")
            or body.get("effectiveDirective")
            or body.get("violated-directive")
            or body.get("violatedDirective")
        )
        blocked = classify_blocked(body.get("blocked-uri", body.get("blockedURL")))
        out.append((directive, *blocked))
    return out


class _ClientWindows:
    """Per-client fixed windows over a bounded table (oldest first)."""

    def __init__(self, clock: Callable[[], float]) -> None:
        self._clock = clock
        self._windows: OrderedDict[str, tuple[float, int]] = OrderedDict()

    def admit(self, client: str) -> float | None:
        """`None` if the report is admitted, else the seconds until the window reopens."""
        now = self._clock()
        started, count = self._windows.get(client, (now, 0))
        if now - started >= WINDOW_S:
            started, count = now, 0
        if count >= MAX_REPORTS_PER_WINDOW:
            return max(1.0, started + WINDOW_S - now)
        self._windows[client] = (started, count + 1)
        self._windows.move_to_end(client)
        while len(self._windows) > MAX_TRACKED_CLIENTS:
            expired = next((k for k, (s, _) in self._windows.items() if now - s >= WINDOW_S), None)
            self._windows.pop(expired if expired is not None else next(iter(self._windows)))
        return None


async def _respond(
    send: Send, status: int, *, title: str | None = None, retry_after: float | None = None
) -> None:
    body = b""
    headers = [(b"cache-control", b"no-store")]
    if title is not None:
        body = json.dumps({"type": "about:blank", "title": title, "status": status}).encode()
        headers += [
            (b"content-type", b"application/problem+json"),
            (b"content-length", str(len(body)).encode()),
        ]
    if retry_after is not None:
        headers.append((b"retry-after", str(int(retry_after) + 1).encode()))
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": body})


class CspReportReceiver:
    def __init__(
        self,
        app: ASGIApp,
        *,
        counter: ViolationCounter | None,
        enabled: bool = True,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._app = app
        self._counter = counter
        self._enabled = enabled
        self._windows = _ClientWindows(clock)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            not self._enabled
            or scope["type"] != "http"
            or scope["method"] != "POST"
            or scope["path"] not in REPORT_PATHS
        ):
            await self._app(scope, receive, send)
            return
        client = (scope.get("client") or ("unknown", 0))[0]
        if (retry := self._windows.admit(str(client))) is not None:
            await _respond(send, 429, title="Too many reports", retry_after=retry)
            return
        headers = {k.lower(): v for k, v in scope["headers"]}
        media = headers.get(b"content-type", b"").decode("latin-1").split(";")[0].strip().lower()
        if media not in ACCEPTED_MEDIA_TYPES:
            await _respond(send, 415, title="Unsupported media type")
            return
        declared = headers.get(b"content-length", b"0")
        if declared.isdigit() and int(declared) > MAX_BODY_BYTES:
            await _respond(send, 413, title="Report too large")
            return
        body = await self._read_capped(receive)
        if body is None:
            await _respond(send, 413, title="Report too large")
            return
        try:
            payload = json.loads(body)
        except ValueError:  # UnicodeDecodeError is one
            await _respond(send, 400, title="Malformed report")
            return
        for directive, blocked_type, host in extract_violations(payload):
            if self._counter is not None:
                self._counter.labels(directive, blocked_type).inc()
            _log().warning(
                "security.csp_violation",
                directive=directive,
                blocked_type=blocked_type,
                blocked_host=host,
            )
        await _respond(send, 204)

    @staticmethod
    async def _read_capped(receive: Receive) -> bytes | None:
        chunks: list[bytes] = []
        size = 0
        while True:
            message: Message = await receive()
            if message["type"] != "http.request":
                return b""
            chunk = message.get("body", b"")
            size += len(chunk)
            if size > MAX_BODY_BYTES:
                return None
            chunks.append(chunk)
            if not message.get("more_body", False):
                return b"".join(chunks)
