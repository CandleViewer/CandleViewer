"""E10-T05 (#5211): Schemathesis over the five `/settings/hotkeys*` operations, in process (C-6.2
names Schemathesis for a REST provider test). The operations come from 22 itself with every
component kept; each case reaches the real `create_app()` of the RBAC pack's world (identity,
sessions and an in-memory hotkey profile store faked) through Schemathesis's ASGI client, with no
socket (the network guard stays on). The only hook is the session: the Owner's bearer and its
SR-041 double-submit pair, which a write needs; no hook maps or filters a body, and no path
parameter is pinned, so a drawn profile id is one no one holds. `ignored_auth` resends a request
without its token after a 2xx, which the list and the create give.

Every built-in check runs but those `_EXCLUDED` names, each left out for the reason given here,
which lies outside these routes' answers:

- `allow_header_conformance`, on the four operations of `/settings/hotkeys` and
  `/settings/hotkeys/{hotkeyProfileId}`: Starlette answers a method no route of a path serves
  (`OPTIONS`) from the first route that matched the path, so its `405` names that route's method
  alone (`Allow: GET`). It holds app-wide for a path whose methods are separate routes
  (`/watchlists` and `/settings` too): the app's routing, not these routes' answers. The
  activation's path has one route, so it keeps the check.
- `positive_data_acceptance`, on `createHotkeyProfile` and `updateHotkeyProfile`: 22 states the
  `keys` grammar and the action vocabulary in prose, with no pattern (BQ-4), so a body valid
  against `HotkeyProfileInput` can still break a rule of `HotkeyProfileInput.bindings` and is
  refused `422` by contract (`unknown_action`, `invalid_keys`, ...). The other three keep it.
- `missing_required_header`, on the four writes: SR-041's CSRF guard refuses an unsafe request
  with no session `403 csrf_token_invalid` before authentication (22 "CSRF"), so a write that
  drops `Authorization` never reaches the `401` that check hard-codes. The list keeps it.

One answer comes from the app's edge, not these routes, and is checked on its own: a write whose
drawn profile id holds a control character (`api/csrf.py`'s `_CONTROL`, U+0000 to U+001F and DEL)
is the CSRF guard's `400 validation_failed`, answered for any unsafe request with such a path
before any route runs. 22 lists that answer on no operation, so such a case is not validated
against these operations; the test asserts that exact `400` for it instead.

`negative_data_rejection` expects 400, 401, 403, 404 or 422. 401 and 403: a write whose
`Authorization` header a negative case drops or mangles meets the CSRF guard's `403` first, since
its token is bound to the session that header named. 404: 22's refusal order answers a profile id
no one holds before the body is judged, and a path id that is no UUID names no profile. The
examples, coverage and fuzzing phases run, 25 fuzzed examples per operation, derandomized with a
fixed seed.
"""

from __future__ import annotations

import copy
from collections.abc import Iterator
from typing import Any, Final
from urllib.parse import unquote

import pytest
import schemathesis
from hypothesis import settings
from schemathesis.specs.openapi.checks import (
    allow_header_conformance,
    missing_required_header,
    positive_data_acceptance,
)
from starlette.types import ASGIApp, Receive, Scope, Send

from candleviewer.api.csrf import _CONTROL as EDGE_CONTROL
from tests.contract._generated_contract import SPEC
from tests.contract.rbac.rbac_harness import bearer, build_world
from tests.hotkey_profiles._fake_store import FakeHotkeyProfileStore

_PATHS: Final = (
    "/settings/hotkeys",
    "/settings/hotkeys/{hotkeyProfileId}",
    "/settings/hotkeys/{hotkeyProfileId}/activate",
)
_OPERATIONS: Final = (
    "listHotkeyProfiles",
    "createHotkeyProfile",
    "updateHotkeyProfile",
    "deleteHotkeyProfile",
    "activateHotkeyProfile",
)
_EXCLUDED: Final = {
    "listHotkeyProfiles": [allow_header_conformance],
    "createHotkeyProfile": [
        allow_header_conformance, positive_data_acceptance, missing_required_header,
    ],
    "updateHotkeyProfile": [
        allow_header_conformance, positive_data_acceptance, missing_required_header,
    ],
    "deleteHotkeyProfile": [allow_header_conformance, missing_required_header],
    "activateHotkeyProfile": [missing_required_header],
}  # fmt: skip
_CONFIG: Final = schemathesis.Config.from_str(
    "seed = 5211\n[checks]\nnegative_data_rejection.expected-statuses = [400, 401, 403, 404, 422]\n"
)


def _hotkey_operations() -> dict[str, Any]:
    """22, copied once (Schemathesis rewrites what it loads) and cut to `/settings/hotkeys*`."""
    spec: dict[str, Any] = copy.deepcopy(SPEC)
    spec["paths"] = {path: spec["paths"][path] for path in _PATHS}
    return spec


class _LateApp:
    """The ASGI app every case and probe reaches, bound at import as Schemathesis requires; it
    forwards to the world the module fixture builds, never at import, so the world's patches never
    reach another module's collection. It presents the loopback peer every other client of this
    world uses (`TestClient(client=("127.0.0.1", 50000))`): Schemathesis's ASGI client names itself
    `testclient`, which no mesh allow-list admits, so `MeshOnlyMiddleware` would refuse every case
    with its generic off-mesh 403 before any guard of these routes ran."""

    target: ASGIApp | None = None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        assert self.target is not None, "the module fixture binds the world first"
        await self.target({**scope, "client": ("127.0.0.1", 50000)}, receive, send)


_APP: Final = _LateApp()
schema: Final = schemathesis.openapi.from_dict(_hotkey_operations(), config=_CONFIG).include(
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
        world.app.state.hotkey_profiles_repository = FakeHotkeyProfileStore()
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
def test_contract_hotkey_profiles_schemathesis_fuzz(case: schemathesis.Case[Any]) -> None:
    """Each generated request is answered with a status the operation declares, in its declared
    media type and schema, and a request outside the schema is refused (400, 401, 403, 404 or
    422)."""
    operation_id = case.operation.definition.raw["operationId"]
    seen = unquote(case.formatted_path)  # the path the app decodes: drawn values come encoded
    if case.method.upper() != "GET" and EDGE_CONTROL.search(seen):
        edge = case.call(base_url=_BASE_URL)  # the edge's answer: no route of these runs
        assert (edge.status_code, edge.json()["code"]) == (400, "validation_failed"), edge.text
        return
    case.call_and_validate(base_url=_BASE_URL, excluded_checks=_EXCLUDED[operation_id])
