"""Fixtures for cv-no-debug-probe-in-prod (E12-X03, SR-E12-16 / BR-26).
Run with: python tools/ci/check_semgrep_rule_tests.py
"""

import freezegun  # ruleid: cv-no-debug-probe-in-prod
from tests.helpers import fake_clock  # ruleid: cv-no-debug-probe-in-prod

from candleviewer.api.auth_perf import auth_perf_enabled
from candleviewer.settings import Environment


def make_router(router, settings):
    @router.get("/market/_probe")  # ruleid: cv-no-debug-probe-in-prod
    async def probe() -> dict:
        return {}

    router.add_api_route("/bars/debug/dump", probe)  # ruleid: cv-no-debug-probe-in-prod

    @router.get("/market/bars")  # ok: cv-no-debug-probe-in-prod
    async def bars() -> dict:
        return {}

    if settings.environment is not Environment.LIVE:
        router.add_api_route("/__test/clock", probe)  # ok: cv-no-debug-probe-in-prod

    return router


def builder_step(bar):
    breakpoint()  # ruleid: cv-no-debug-probe-in-prod
    return bar


# --- #2755: perf-only routes (#2097) and the keyless-testnet perf gate -----------------------


def make_perf_routes(router, app, handler):
    """`_perf` is a probe segment: an ungated perf route is flagged, a longer word is not."""

    @router.get("/_perf/x")  # ruleid: cv-no-debug-probe-in-prod
    async def perf_x() -> dict:
        return {}

    router.add_api_route("/auth/_perf/argon2-params", handler)  # ruleid: cv-no-debug-probe-in-prod

    @app.get("/perf")  # ruleid: cv-no-debug-probe-in-prod
    def perf_root() -> dict:
        return {}

    @router.get("/auth/performance")  # ok: cv-no-debug-probe-in-prod
    async def performance() -> dict:
        return {}

    router.add_api_route("/perf-tests", handler)  # ok: cv-no-debug-probe-in-prod


def mount_gated_perf_routes(router, resolved, handler):
    """The #2097 gate: `auth_perf` holds what `auth_perf_enabled(resolved)` returned."""
    auth_perf = auth_perf_enabled(resolved)
    if auth_perf:
        router.add_api_route("/auth/_perf/argon2-params", handler)  # ok: cv-no-debug-probe-in-prod

        @router.get("/_perf/x")  # ok: cv-no-debug-probe-in-prod
        async def gated_perf_x() -> dict:
            return {}

    if auth_perf_enabled(resolved):
        router.add_api_route("/_perf/y", handler)  # ok: cv-no-debug-probe-in-prod


def mount_not_the_gate(router, resolved, handler):
    """Shapes that look like the gate but are not it stay flagged (the rule fails closed)."""
    auth_perf = auth_perf_enabled(resolved)

    # The raw settings field skips the build-time re-check that `auth_perf_enabled()` repeats.
    if resolved.auth_perf_enabled:
        router.add_api_route("/_perf/raw", handler)  # ruleid: cv-no-debug-probe-in-prod

    if not auth_perf:
        router.add_api_route("/_perf/inverted", handler)  # ruleid: cv-no-debug-probe-in-prod

    # Semgrep treats an if/else as one block, so an `else:` would exempt the branch where the
    # switch is OFF; the gate clauses therefore accept only an `if` with no `else:`.
    if auth_perf:
        router.add_api_route("/_perf/then", handler)  # ruleid: cv-no-debug-probe-in-prod
    else:
        router.add_api_route("/_perf/else", handler)  # ruleid: cv-no-debug-probe-in-prod

    if auth_perf_enabled(resolved):
        router.add_api_route("/_perf/call-then", handler)  # ruleid: cv-no-debug-probe-in-prod
    else:
        router.add_api_route("/_perf/call-else", handler)  # ruleid: cv-no-debug-probe-in-prod


ARGON2_PARAMS_PATH = "/auth/_perf/argon2-params"


def make_auth_perf_router(router):
    """The #2097 route as `api/auth_perf.py` declares it: the path is a module constant and
    `create_app` mounts this factory only under `if auth_perf:`. The rule reads the literal at
    the registration and does not resolve constants, so this route is not flagged."""

    @router.get(ARGON2_PARAMS_PATH)  # ok: cv-no-debug-probe-in-prod
    async def argon2_params() -> dict:
        return {}

    return router
