"""E12-Q04 (#420): Schemathesis over `GET /market/klines` and `GET /market/bars`, in process (C-6.2
names Schemathesis for a REST provider test): the partial run of 22's `schemathesis_fuzz` gate
(23 §16.5). The two operations come from 22 itself with every component kept; each case reaches
`_market_world`'s app through Schemathesis's ASGI client, with no socket (the network guard stays
on). The only hook is the session `x-rbac` grants (`Bearer reader`), so `ignored_auth` probes the
401 path; no hook maps or filters a query.

Every built-in check runs but `positive_data_acceptance`: a request 22's schema accepts is often,
and correctly, refused, since 22 cannot express what a served request also needs (a listed symbol,
the per-type `param`, the window caps, an issued cursor); that exclusion is recorded on #420.
`negative_data_rejection` expects the refusals the operations declare. The examples, coverage and
fuzzing phases run, 25 fuzzed examples per operation, derandomized with a fixed seed.
"""

from __future__ import annotations

import copy
from typing import Any, Final

import schemathesis
from hypothesis import settings
from schemathesis.specs.openapi.checks import positive_data_acceptance

from tests.contract._generated_contract import SPEC
from tests.contract._market_world import OPERATIONS, READER, MarketWorld, operation

#: In code, never a `schemathesis.toml` beside the suite: a fixed seed, and the refusals a
#: request outside the schema may get (each declared by both operations).
_CONFIG: Final = schemathesis.Config.from_str(
    "seed = 420\n[checks]\nnegative_data_rejection.expected-statuses = [400, 401, 403, 422]\n"
)
_PATHS: Final = [operation(op)[0] for op in OPERATIONS]
#: Schemathesis rewrites what it loads: it gets its own copy of 22, cut to the two paths.
schema: Final = schemathesis.openapi.from_dict(
    {**copy.deepcopy(SPEC), "paths": {path: copy.deepcopy(SPEC["paths"][path]) for path in _PATHS}},
    config=_CONFIG,
).include(operation_id=list(OPERATIONS))
#: The server, as `from_asgi` would bind it: every case and every check's probe (`ignored_auth`
#: resends one without the token) reaches it in process. Its routes sit at the root, not under
#: 22's `/api/v1` servers, hence the base URL.
schema.app = MarketWorld().app
_BASE_URL: Final = "http://testserver"


@schema.auth()
class _Reader:
    """The session that holds exactly what `x-rbac` names (`_market_world`)."""

    def get(self, case: schemathesis.Case[Any], ctx: schemathesis.AuthContext) -> str:
        return READER["Authorization"].removeprefix("Bearer ")

    def set(self, case: schemathesis.Case[Any], data: str, ctx: schemathesis.AuthContext) -> None:
        case.headers["Authorization"] = f"Bearer {data}"


@schema.parametrize()
@settings(max_examples=25, derandomize=True, deadline=None, database=None)
def test_contract_market_schemathesis_fuzz(case: schemathesis.Case[Any]) -> None:
    """Each generated request is answered with a status the operation declares, in its declared
    media type and schema, and a request outside the schema is refused (400, 401, 403 or 422)."""
    case.call_and_validate(base_url=_BASE_URL, excluded_checks=[positive_data_acceptance])
