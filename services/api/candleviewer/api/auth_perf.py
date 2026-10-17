"""`GET /auth/_perf/argon2-params` and the auth perf switch (#2097, E09-Q05).

Perf instrumentation for `tests/load/k6/auth.js`: this route reports the Argon2id parameters
that new password hashes use, so a run can assert the SR-011 floor, and the login route adds
`Server-Timing: argon2;dur=<ms>` to its 200 challenge (`api/auth.py`). Both exist only while
`CV_AUTH_PERF_ENABLED` is on. `Settings` refuses that switch unless `CV_ENVIRONMENT=testnet`
with no exchange key configured (the #2086 gate); `auth_perf_enabled()` checks the same rule
again when the app is built, before any module starts, so a `Settings` that skipped
validation still never turns it on in live or demo. It logs a boot line whenever it is on.

The route is owner-only (`admin:read`, resolved server-side from the session, C-12.4) and
read-only, so like `/admin/health` it writes no audit record. The parameters are not secret:
every stored hash embeds them. Its refusals are `Problem` bodies carrying the registry's `code`
(`x-error-codes`): 401 `unauthenticated` and 403 `forbidden`, the contract's shared responses,
and 501 `not_implemented` when no principal resolver is wired.
"""

from __future__ import annotations

from typing import Final, Protocol

import structlog
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from candleviewer.auth.hashing import DEFAULT_ARGON2_PARAMS
from candleviewer.settings import Settings

ADMIN_READ = "admin:read"
ARGON2_PARAMS_PATH = "/auth/_perf/argon2-params"
_ERRORS: Final = "https://candleviewer.local/errors/"
#: status -> (`code`, title) of every refusal this route renders.
_REFUSALS: Final = {
    401: ("unauthenticated", "Unauthorized"),
    403: ("forbidden", "Forbidden"),
    501: ("not_implemented", "Not implemented"),
}


class _Principal(Protocol):
    def has(self, permission: str) -> bool: ...


class _PrincipalResolver(Protocol):
    async def resolve(self, request: Request) -> _Principal | None: ...


def auth_perf_enabled(settings: Settings) -> bool:
    """True when the auth perf instrumentation is on, after logging the boot line.

    Raises `ValueError` (as the other build-time config refusals in `create_app`) for a switch
    that is on where the #2086 gate refuses it, which only a `Settings` that skipped validation
    can carry: the app then never builds."""
    if not settings.auth_perf_enabled:
        return False
    refusal = settings.auth_perf_refusal()
    if refusal is not None:
        raise ValueError(refusal)
    structlog.get_logger(__name__).warning(
        "auth.perf_instrumentation_enabled",
        environment=settings.environment.value,
        detail="GET /auth/_perf/argon2-params is mounted; login challenges carry Server-Timing",
    )
    return True


def _problem(status: int, detail: str) -> JSONResponse:
    code, title = _REFUSALS[status]
    return JSONResponse(
        status_code=status,
        content={
            "type": f"{_ERRORS}{code}",
            "title": title,
            "status": status,
            "code": code,
            "detail": detail,
        },
        media_type="application/problem+json",
    )


def make_auth_perf_router(principal_resolver: _PrincipalResolver | None) -> APIRouter:
    """The params route. Mount it only when `auth_perf_enabled()` is True; *principal_resolver*
    `None` (no identity provider wired) fails closed with 501, as on `/admin/health`."""
    router = APIRouter(tags=["perf"])

    @router.get(ARGON2_PARAMS_PATH)
    async def argon2_params(request: Request) -> JSONResponse:
        if principal_resolver is None:
            return _problem(501, "no principal resolver wired")
        principal = await principal_resolver.resolve(request)
        if principal is None:
            return _problem(401, "no verified session for this request")
        if not principal.has(ADMIN_READ):
            return _problem(403, f"missing permission: {ADMIN_READ}")
        return JSONResponse({name: DEFAULT_ARGON2_PARAMS[name] for name in ("m", "t", "p")})

    return router
