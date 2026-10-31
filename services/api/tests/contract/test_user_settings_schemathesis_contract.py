"""E02-T13 (#5181): Schemathesis over `getSettings` and `updateSettings`, in process (C-6.2 names
Schemathesis for a REST provider test). The two operations come from 22 itself with every component
kept; each case reaches the real `create_app()` of the RBAC pack's world (identity, sessions and an
in-memory settings store faked) through Schemathesis's ASGI client, with no socket (the network
guard stays on). The only hook is the session: the Owner's bearer and its SR-041 double-submit pair,
which a write needs; no hook maps or filters a body. `ignored_auth` resends a request without its
token after a 2xx, which both operations give.

Every built-in check runs but those `_EXCLUDED` names, each left out for a reason outside this
route, recorded on #5181:

- `positive_data_acceptance`: `SettingsPatch` is `additionalProperties: true`, so 22's schema
  accepts any object while the route stores only the leaves 22's `Settings` declares and refuses
  the rest `422` (E02-T13's scope).
- `allow_header_conformance`: Starlette answers a method no route of a path serves (`OPTIONS`)
  from the first route that matched the path, so its `405` names that route's method alone
  (`Allow: GET`). It holds app-wide for a path whose methods are separate routes (`/watchlists`
  too): the app's routing, not this route's answer.
- `missing_required_header`, on `updateSettings` only: SR-041's CSRF guard refuses an unsafe
  request with no session `403 csrf_token_invalid` before authentication (22 "CSRF"), so a write
  that drops `Authorization` never reaches the `401` that check hard-codes. `GET` keeps it.

`negative_data_rejection` expects 400, 401, 403 or 422: a write whose `Authorization` header a
negative case drops or mangles meets the CSRF guard's `403` first, since its token is bound to the
session that header named. The examples, coverage and fuzzing phases run, 25 fuzzed examples per
operation, derandomized with a fixed seed.
"""

from __future__ import annotations

import copy
from collections.abc import Iterator
from typing import Any, Final

import pytest
import schemathesis
from hypothesis import settings
from schemathesis.specs.openapi.checks import (
    allow_header_conformance,
    missing_required_header,
    positive_data_acceptance,
)
from starlette.types import ASGIApp, Receive, Scope, Send

from tests.contract._generated_contract import SPEC
from tests.contract.rbac.rbac_harness import bearer, build_world
from tests.unit.storage.fakes_user_settings import FakeUserSettings

_OPERATIONS: Final = ("getSettings", "updateSettings")
_EXCLUDED: Final = {
    "GET": [positive_data_acceptance, allow_header_conformance],
    "PATCH": [positive_data_acceptance, allow_header_conformance, missing_required_header],
}
_CONFIG: Final = schemathesis.Config.from_str(
    "seed = 5181\n[checks]\nnegative_data_rejection.expected-statuses = [400, 401, 403, 422]\n"
)


def _two_operations() -> dict[str, Any]:
    """22, copied once (Schemathesis rewrites what it loads) and cut to `/settings`."""
    spec: dict[str, Any] = copy.deepcopy(SPEC)
    spec["paths"] = {"/settings": spec["paths"]["/settings"]}
    return spec


class _LateApp:
    """The ASGI app every case and probe reaches, bound at import as Schemathesis requires; it
    forwards to the world the module fixture builds, never at import, so the world's patches never
    reach another module's collection. It presents the loopback peer every other client of this
    world uses (`TestClient(client=("127.0.0.1", 50000))`): Schemathesis's ASGI client names itself
    `testclient`, which no mesh allow-list admits, so `MeshOnlyMiddleware` would refuse every case
    with its generic off-mesh 403 before any guard of this route ran."""

    target: ASGIApp | None = None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        assert self.target is not None, "the module fixture binds the world first"
        await self.target({**scope, "client": ("127.0.0.1", 50000)}, receive, send)


_APP: Final = _LateApp()
schema: Final = schemathesis.openapi.from_dict(_two_operations(), config=_CONFIG).include(
    operation_id=list(_OPERATIONS)
)
schema.app = _APP
#: The world's routes sit at the root, not under 22's `/api/v1` servers, hence the base URL.
_BASE_URL: Final = "http://testserver"


@pytest.fixture(scope="module", autouse=True)
def _world() -> Iterator[None]:
    """The RBAC pack's world, built for this module only; its patches are undone after it."""
    mp = pytest.MonkeyPatch()
    try:
        world = build_world(mp)
        world.app.state.user_settings_repository = FakeUserSettings()
        _APP.target = world.app
        yield
    finally:
        _APP.target = None
        mp.undo()


@schema.auth()
class _Owner:
    """The Owner's session: its bearer, and the double-submit pair bound to it (SR-041)."""

    def get(self, case: schemathesis.Case[Any], ctx: schemathesis.AuthContext) -> dict[str, str]:
        return bearer("owner")

    def set(
        self, case: schemathesis.Case[Any], data: dict[str, str], ctx: schemathesis.AuthContext
    ) -> None:
        case.headers.update(data)


@schema.parametrize()
@settings(max_examples=25, derandomize=True, deadline=None, database=None)
def test_contract_settings_schemathesis_fuzz(case: schemathesis.Case[Any]) -> None:
    """Each generated request is answered with a status the operation declares, in its declared
    media type and schema, and a request outside the schema is refused (400, 401, 403 or 422)."""
    case.call_and_validate(
        base_url=_BASE_URL, excluded_checks=_EXCLUDED[case.operation.method.upper()]
    )
