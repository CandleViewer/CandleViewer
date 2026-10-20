"""The CORS policy for the desktop shell's page (ADR-0038 2b, #3519).

`cors_app` puts Starlette's `CORSMiddleware` in front of an ASGI app, configured from one frozen
`CorsPolicy`: the SR-042 allow-list (`Settings.allowed_origin_set`) matched exactly, with
credentials, and the contract's methods and header lists (`22-api-openapi.yaml`, "Cross-origin
(CORS)"). There is no `allow_origin_regex` and never a `*`, so no origin is reflected, and no
private-network answer (A9, ADR-0038 Amendment 1): a preflight asking for one gets a 400.

Starlette adds `Access-Control-Allow-Credentials` and `Access-Control-Expose-Headers` for any
`Origin`, listed or not. So `cors_app` is mounted only behind the gate that hands it a listed
`Origin` with `desktop.backend_connection` on (ADR-0038 2c, slice S3b), never bare.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from starlette.middleware.cors import CORSMiddleware
from starlette.types import ASGIApp

from candleviewer.observability.correlation import CORRELATION_HEADER

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


@dataclass(frozen=True, slots=True)
class CorsPolicy:
    """What a CORS answer is built from: the allowed origins and the two header lists."""

    origins: frozenset[str]
    allow_headers: tuple[str, ...] = ALLOW_HEADERS
    expose_headers: tuple[str, ...] = EXPOSE_HEADERS


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
