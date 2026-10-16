"""Fixtures for cv-no-debug-probe-in-prod (E12-X03, SR-E12-16 / BR-26).
Run with: python tools/ci/check_semgrep_rule_tests.py
"""

import freezegun  # ruleid: cv-no-debug-probe-in-prod
from tests.helpers import fake_clock  # ruleid: cv-no-debug-probe-in-prod

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


# --- #2755: the environment guard takes no `else:` -------------------------------------------


def mount_env_guarded_seams(router, settings, handler):
    """Semgrep matches an if/else as one block, so an `else:` route (it runs only in LIVE)
    would count as guarded. A guard with an `else:` is therefore not accepted at all."""
    if settings.environment != Environment.LIVE:
        router.add_api_route("/__test/ne", handler)  # ok: cv-no-debug-probe-in-prod

    if settings.environment is not Environment.LIVE:
        router.add_api_route("/__test/is-not-then", handler)  # ruleid: cv-no-debug-probe-in-prod
    else:
        router.add_api_route("/__test/is-not-else", handler)  # ruleid: cv-no-debug-probe-in-prod

    if settings.environment != Environment.LIVE:
        router.add_api_route("/__test/ne-then", handler)  # ruleid: cv-no-debug-probe-in-prod
    else:
        router.add_api_route("/__test/ne-else", handler)  # ruleid: cv-no-debug-probe-in-prod


# --- #2755: perf-only routes (#2097) and the keyless-testnet perf gate -----------------------
#
# The rule accepts an `if` only on a call that Semgrep resolves to
# candleviewer.api.auth_perf.auth_perf_enabled, and Semgrep resolves a name through the imports
# above the call, in file order. The import that makes `auth_perf_enabled` the real gate sits
# further down on purpose, so that the helper defined above it is a different function.


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


def auth_perf_enabled(settings):
    """Shares the gate's name, but is defined here and not imported from the gate module."""
    return True


def mount_with_same_named_helper(router, settings, handler):
    if auth_perf_enabled(settings):
        router.add_api_route("/_perf/local-helper", handler)  # ruleid: cv-no-debug-probe-in-prod


# Load-bearing: the `ok:` gate lines below are exempt only because this import makes
# `auth_perf_enabled` resolve to the real gate, spelled as `create_app` imports it.
from candleviewer.api.auth_perf import auth_perf_enabled


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


def mount_gated_after_other_work(router, resolved, handler, app):
    """`create_app` assigns `auth_perf` early and tests it much later: statements in between
    do not end the propagation."""
    auth_perf = auth_perf_enabled(resolved)
    app.state.resolved = resolved
    app.include_router(router)
    if auth_perf:
        router.add_api_route("/_perf/z", handler)  # ok: cv-no-debug-probe-in-prod


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


def mount_flag_from_raw_field(router, resolved, handler):
    """A local named `auth_perf` is the gate only if `auth_perf_enabled()` returned it: here it
    holds the raw field, so the hoist that a refactor produces is not the gate."""
    auth_perf = resolved.auth_perf_enabled
    if auth_perf:
        router.add_api_route("/_perf/hoisted-raw", handler)  # ruleid: cv-no-debug-probe-in-prod


def mount_flag_from_constant(router, handler):
    """The gate exempts every seam kind, so a flag that is not the gate must not exempt any."""
    auth_perf = True
    if auth_perf:
        router.add_api_route("/_debug/dump", handler)  # ruleid: cv-no-debug-probe-in-prod


def mount_flag_reassigned(router, resolved, handler):
    """Only the value the `if` sees counts: a later assignment replaces the gate's result."""
    auth_perf = auth_perf_enabled(resolved)
    auth_perf = True
    if auth_perf:
        router.add_api_route("/_perf/reassigned", handler)  # ruleid: cv-no-debug-probe-in-prod


def mount_flag_across_loop(router, resolved, handler, hooks):
    """A loop between the assignment and the `if` ends the propagation, so the site is flagged
    (fail closed): call `auth_perf_enabled(...)` in the `if` itself instead."""
    auth_perf = auth_perf_enabled(resolved)
    for hook in hooks:
        hook()
    if auth_perf:
        router.add_api_route("/_perf/across-loop", handler)  # ruleid: cv-no-debug-probe-in-prod


ARGON2_PARAMS_PATH = "/auth/_perf/argon2-params"


def make_auth_perf_router(router):
    """The #2097 route as `api/auth_perf.py` declares it: the path is a module constant and
    `create_app` mounts this factory only under `if auth_perf:`. The rule reads the literal at
    the registration and does not resolve constants, so this route is not flagged."""

    @router.get(ARGON2_PARAMS_PATH)  # ok: cv-no-debug-probe-in-prod
    async def argon2_params() -> dict:
        return {}

    return router


# The two functions below stay last: Semgrep carries a function-local import over to the code
# after it, which would turn the real gate into the other function for anything that follows.


def mount_with_import_from_another_module(router, settings, handler):
    from candleviewer.other_module import auth_perf_enabled

    if auth_perf_enabled(settings):
        router.add_api_route("/_perf/other-module", handler)  # ruleid: cv-no-debug-probe-in-prod


def mount_with_relative_import(router, settings, handler):
    """A relative import is not resolved to the gate module, so spell the import absolutely."""
    from .auth_perf import auth_perf_enabled

    if auth_perf_enabled(settings):
        router.add_api_route("/_perf/relative", handler)  # ruleid: cv-no-debug-probe-in-prod
