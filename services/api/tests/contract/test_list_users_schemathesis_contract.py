"""#5478: Schemathesis over `listUsers` (`GET /users`), in process (C-6.2 names Schemathesis for a
REST provider test). The operation comes from 22 itself with every component kept; each case
reaches the real `create_app()` of the RBAC pack's world (identity and sessions faked), its user
admin store an in-memory one of three users built through `build_user_admin_store`, through
Schemathesis's ASGI client, with no socket (the network guard stays on). The only hook is the
session, the Owner's bearer; `ignored_auth` resends a request without its token after a 2xx.

Every built-in check runs but those `_EXCLUDED` names, each left out for a reason that lies
outside this route's answer:

- `positive_data_acceptance`: 22's `cursor` is any string of at most 512 characters, but a cursor
  is valid only as the server issued it, for the caller and the filters it was issued for (22's
  description of the operation), so a generated one is refused `400 invalid_cursor`; and a `q`
  holding a NUL character, which the schema does not exclude, is refused `400 validation_failed`.
- `allow_header_conformance`: `/users` is shared with `POST /users`, on the invites router, which
  is registered first. Starlette answers a method no route of a path serves from the first route
  that matched the path, so its `405` names that route's method alone (`Allow: POST`): the app's
  routing, not this route's answer.

`negative_data_rejection` expects 400, 401 or 403, and runs as `_rejects_negative_data`, which
passes over one case only: a request whose declared parameters are valid and which also names an
undeclared one. 22 has `listUsers` ignore such a parameter, as every list does (BQ-3), so that
request is served. The check exempts this case itself, but it validates the other values as the
wire carries them, so a `limit` of `"100"` fails `type: integer` and the exemption never applies.
The examples, coverage and fuzzing phases run, 25 fuzzed examples, derandomized with a fixed seed.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Iterator
from typing import Any, Final

import jsonschema
import pytest
import schemathesis
from hypothesis import settings
from schemathesis.specs.openapi.checks import (
    allow_header_conformance,
    negative_data_rejection,
    positive_data_acceptance,
)
from starlette.types import ASGIApp, Receive, Scope, Send

import candleviewer.app as appmod
from tests.contract._generated_contract import SPEC
from tests.contract.rbac.rbac_harness import bearer, build_world
from tests.unit.api.user_list_world import UserRows, rows

_EXCLUDED: Final = [positive_data_acceptance, allow_header_conformance, negative_data_rejection]
_CONFIG: Final = schemathesis.Config.from_str(
    "seed = 5478\n[checks]\nnegative_data_rejection.expected-statuses = [400, 401, 403]\n"
)


def _one_path() -> dict[str, Any]:
    """22, copied once (Schemathesis rewrites what it loads) and cut to `/users`."""
    spec: dict[str, Any] = copy.deepcopy(SPEC)
    spec["paths"] = {"/users": spec["paths"]["/users"]}
    return spec


def _query_schema() -> dict[str, Any]:
    """22's query parameters of `listUsers` as one closed object, its `$ref`s resolvable."""
    op, params = SPEC["paths"]["/users"]["get"], SPEC["components"]["parameters"]
    found = [params[x["$ref"].rsplit("/", 1)[1]] if "$ref" in x else x for x in op["parameters"]]
    properties = {x["name"]: x["schema"] for x in found}
    return {"type": "object", "properties": properties, "additionalProperties": False} | {
        "components": SPEC["components"]
    }


_QUERY: Final = _query_schema()
_DIGITS: Final = re.compile("[0-9]{1,4}")
_DECLARED: Final = jsonschema.Draft202012Validator(_QUERY)
_NAMES: Final = frozenset(_QUERY["properties"])


def _rejects_negative_data(ctx: Any, response: Any, case: schemathesis.Case[Any]) -> bool | None:
    """`negative_data_rejection` but for a request whose declared parameters are valid, read as
    22 types them, and which also names an undeclared one (module docstring)."""
    query = dict(case.query or {})
    # As the route reads `limit` (`user_list_params`): ASCII digits, at most four of them.
    read = {
        k: int(v) if k == "limit" and _DIGITS.fullmatch(str(v)) else v for k, v in query.items()
    }
    if set(query) - _NAMES and _DECLARED.is_valid({k: v for k, v in read.items() if k in _NAMES}):
        return None
    result: bool | None = negative_data_rejection(ctx, response, case)
    return result


class _LateApp:
    """The ASGI app every case and probe reaches, bound at import as Schemathesis requires; it
    forwards to the world the module fixture builds, never at import, so the world's patches never
    reach another module's collection. It presents the loopback peer the world's other clients
    use, which the mesh allow-list admits (`MeshOnlyMiddleware`)."""

    target: ASGIApp | None = None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        assert self.target is not None, "the module fixture binds the world first"
        await self.target({**scope, "client": ("127.0.0.1", 50000)}, receive, send)


_APP: Final = _LateApp()
schema: Final = schemathesis.openapi.from_dict(_one_path(), config=_CONFIG).include(
    operation_id=["listUsers"]
)
schema.app = _APP
#: The world's routes sit at the root, not under 22's `/api/v1` servers, hence the base URL.
_BASE_URL: Final = "http://testserver"


@pytest.fixture(scope="module", autouse=True)
def _world() -> Iterator[None]:
    """The RBAC pack's world with a seeded user admin store, for this module only."""
    mp = pytest.MonkeyPatch()
    try:
        store = UserRows(rows(3))
        mp.setattr(appmod, "build_user_admin_store", lambda _settings: store)
        _APP.target = build_world(mp).app
        yield
    finally:
        _APP.target = None
        mp.undo()


@schema.auth()
class _Owner:
    """The Owner's session: its bearer."""

    def get(self, case: schemathesis.Case[Any], ctx: schemathesis.AuthContext) -> dict[str, str]:
        return bearer("owner")

    def set(
        self, case: schemathesis.Case[Any], data: dict[str, str], ctx: schemathesis.AuthContext
    ) -> None:
        case.headers.update(data)


@schema.parametrize()
@settings(max_examples=25, derandomize=True, deadline=None, database=None)
def test_list_users_conforms_under_schemathesis(case: schemathesis.Case[Any]) -> None:
    """Each generated request is answered with a status `listUsers` declares, in its declared
    media type and schema, and a request outside the schema is refused (400, 401 or 403)."""
    case.call_and_validate(
        base_url=_BASE_URL, excluded_checks=_EXCLUDED, additional_checks=[_rejects_negative_data]
    )
