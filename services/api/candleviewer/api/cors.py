"""The CORS layer for the desktop shell's page (ADR-0038 2b and 2c, #3519).

`cors_app` puts Starlette's `CORSMiddleware` in front of an ASGI app, configured from one frozen
`CorsPolicy`: the SR-042 allow-list (`Settings.allowed_origin_set`) matched exactly, with
credentials, and the contract's methods and header lists (`22-api-openapi.yaml`, "Cross-origin
(CORS)"). There is no `allow_origin_regex` and never a `*`, so no origin is reflected, and no
private-network answer (A9, ADR-0038 Amendment 1): a preflight asking for one gets a 400.

Starlette adds `Access-Control-Allow-Credentials` and `Access-Control-Expose-Headers` for any
`Origin`, listed or not. So `cors_app` is never mounted bare: `CorsGateMiddleware` hands it only a
request `cors_on` admits (a listed `Origin`, `desktop.backend_connection` on); every other request
passes untouched, with no CORS header. The gate sits inside MeshOnly and the CSRF guard and outside
idle-lock (HttpDuration -> Correlation -> MeshOnly -> Csrf -> Cors -> IdleLock), so off-mesh traffic
never reaches it and a preflight (a safe method) passes the guard. The guard's token refusals answer
before the gate, so the guard asks `cors_on` itself and wraps its refusal in `cors_app` from the
same policy, except a `cross_origin` one. No check reads the flag (C-4.14). An unhandled error's
500 comes from Starlette's outermost `ServerErrorMiddleware`, so it has no CORS header and the page
sees a network error (accepted, ADR-0038 2c).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

from starlette.datastructures import Headers
from starlette.middleware.cors import CORSMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send

from candleviewer.observability.correlation import CORRELATION_HEADER
from candleviewer.settings import is_serialised_origin

#: The contract's methods, listed: Starlette would expand a `*` to `ALL_METHODS`, with `QUERY`.
METHODS: Final[tuple[str, ...]] = ("GET", "HEAD", "POST", "PUT", "PATCH", "DELETE")
#: `Authorization`, `Content-Type` and every request header parameter the contract declares. The
#: runtime has only the pruned contract subset, so this and `EXPOSE_HEADERS` are constants;
#: `tests/contract/test_cors_header_lists_contract.py` derives both from every operation.
ALLOW_HEADERS: Final[tuple[str, ...]] = (
    "Authorization",
    "Content-Type",
    "Idempotency-Key",
    "If-Match",
    "X-Arm-Token",
    "X-CSRF-Token",
    "X-Reauth-Password",
)
#: Every response header the contract declares, less the CORS-safelisted ones and `Set-Cookie`,
#: plus the correlation id. `Retry-After` is here because the lockout screen reads it.
EXPOSE_HEADERS: Final[tuple[str, ...]] = (
    "Content-Disposition",
    "ETag",
    "Idempotency-Replayed",
    "RateLimit-Limit",
    "RateLimit-Remaining",
    "RateLimit-Reset",
    "Referrer-Policy",
    "Repr-Digest",
    "Retry-After",
    "Server-Timing",
    "X-CSRF-Token",
    "X-Content-Type-Options",
    CORRELATION_HEADER,
)
MAX_AGE_S: Final[int] = 600
#: `scope["state"]` key of the flag's value for one request: a bool once an `Origin` has matched,
#: absent otherwise. ADR-0038 S4 reads it, so one response's headers and cookies agree.
FLAG_STATE_KEY: Final[str] = "cv_desktop_backend_connection"
#: The flag reader: sync, answers at once from its last value, never raises.
Enabled = Callable[[], bool]


@dataclass(frozen=True, slots=True)
class CorsPolicy:
    """What a CORS answer is built from: the allowed origins and the two header lists."""

    origins: frozenset[str]
    allow_headers: tuple[str, ...] = ALLOW_HEADERS
    expose_headers: tuple[str, ...] = EXPOSE_HEADERS

    def __post_init__(self) -> None:
        # `Settings` checks its allow-list the same way; this holds for any other caller (SR-042).
        # `*` and `null` never qualify, so no entry can match every origin or a sandboxed page.
        for entry in self.origins:
            if not is_serialised_origin(entry):
                raise ValueError(f"CORS origin {entry!r} is not a serialised origin")


def cors_app(policy: CorsPolicy, app: ASGIApp) -> ASGIApp:
    """`app` behind Starlette's CORS middleware, configured from `policy` and nothing else."""
    return CORSMiddleware(
        app,
        allow_origins=policy.origins,
        allow_methods=METHODS,
        allow_headers=policy.allow_headers,
        allow_credentials=True,
        expose_headers=policy.expose_headers,
        max_age=MAX_AGE_S,
    )


def cors_on(scope: Scope, policy: CorsPolicy, enabled: Enabled) -> bool:
    """True when CORS answers this request: its one `Origin` is listed and the flag is on.

    The match is exact, on the header as sent: a repeated `Origin` counts as unlisted, as on the WS
    upgrade, and a trailing `/` or another case never matches. `enabled` is read only after the
    match, once per request: the value stays in `scope["state"]` under `FLAG_STATE_KEY`."""
    origins = Headers(scope=scope).getlist("origin")
    if len(origins) != 1 or origins[0] not in policy.origins:
        return False  # matched on every call: a stored flag never admits another request's origin
    state = scope.setdefault("state", {})
    if FLAG_STATE_KEY not in state:
        state[FLAG_STATE_KEY] = enabled() is True
    return state[FLAG_STATE_KEY] is True


class CorsGateMiddleware:
    """Pure ASGI gate for `cors_app` (module docstring): a request `cors_on` admits goes through
    the layer; every other request, and any websocket or lifespan scope (no flag read), goes
    straight to the app, untouched."""

    def __init__(self, app: ASGIApp, *, policy: CorsPolicy, enabled: Enabled) -> None:
        self._app = app
        self._cors = cors_app(policy, app)
        self._policy = policy
        self._enabled = enabled

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and cors_on(scope, self._policy, self._enabled):
            await self._cors(scope, receive, send)
        else:
            await self._app(scope, receive, send)
