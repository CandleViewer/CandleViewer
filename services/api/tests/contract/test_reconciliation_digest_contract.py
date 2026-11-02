"""Contract (E29-S07 #1028, BQ-9): `getReconciliationDigest` as 22 declares it. Every answer the
route gives, on `test_reconciliation_digest_route.py`'s world, is validated against the response 22
declares for that status (the `deref` and JSON Schema 2020-12 the other route contract tests use;
401 is the session layer's, declared once in `info`); the operation's `x-rbac` is the route's
permission pair; and the schema's lists, cap and members are the digest builder's. The RBAC cells
are `tests/contract/rbac/matrix.yaml`'s."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.routing import APIRoute
from jsonschema import Draft202012Validator

from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.api.reconciliation_digest import (
    OPERATION,
    PATH,
    PERMISSIONS,
    make_reconciliation_digest_router,
)
from candleviewer.domain.primitives import AccountId
from candleviewer.oms.reconcile_digest import DIGEST_LISTS, MAX_DIGEST_ITEMS, digest_of
from tests.openapi_helpers import deref
from tests.unit.api.oms_reads_world import ACCOUNT_A, ACCOUNT_B, MISSING
from tests.unit.api.test_reconciliation_digest_route import _seeded, _state, _World

_SPEC: Any = load_openapi_spec()  # a parsed YAML document, walked untyped
_OP: Any = _SPEC["paths"][PATH]["get"]
_SCHEMAS: Any = _SPEC["components"]["schemas"]


def _declared(status: int) -> Any:
    responses = _OP["responses"]
    assert str(status) in responses, f"{OPERATION} answers {status}, which 22 does not declare"
    [media] = deref(_SPEC, responses[str(status)])["content"].values()
    return media["schema"]


def _fail(world: _World) -> None:
    world.principals.fail = True


_CASES: list[tuple[str, int, uuid.UUID | str, str, Callable[[_World], None] | None]] = [
    ("ok", 200, ACCOUNT_A, "manager", None),
    ("forbidden", 403, ACCOUNT_A, "bare", None),
    ("foreign", 404, ACCOUNT_B, "manager", None),
    ("absent", 404, MISSING, "owner", None),
    ("malformed", 400, "x", "owner", None),
    ("session", 503, ACCOUNT_A, "owner", _fail),
]


@pytest.mark.parametrize(
    ("case", "status", "account", "who", "change"), _CASES, ids=[c[0] for c in _CASES]
)
async def test_contract_conformance(
    case: str,
    status: int,
    account: uuid.UUID | str,
    who: str,
    change: Callable[[_World], None] | None,
) -> None:
    world = _seeded()
    if change is not None:
        change(world)
    answer = await world.get(account, who)
    assert answer.status_code == status, (case, answer.text)
    media = answer.headers["content-type"]
    assert media.startswith("application/json" if status < 400 else "application/problem+json")
    validator = Draft202012Validator(
        _declared(status), format_checker=Draft202012Validator.FORMAT_CHECKER
    )
    assert [error.message for error in validator.iter_errors(answer.json())] == [], case
    if status == 200:
        declared = _OP["responses"]["200"]["headers"]["Cache-Control"]["schema"]["const"]
        assert answer.headers["cache-control"] == declared == "no-store"


def test_the_operation_is_the_routes_with_its_permission_pair() -> None:
    routes = make_reconciliation_digest_router(None, _World().digests, audit=_World().audit).routes
    [route] = routes
    assert isinstance(route, APIRoute) and (route.path, route.operation_id) == (PATH, OPERATION)
    assert _OP["operationId"] == OPERATION
    assert _OP["x-rbac"] == {
        "permissions": [p.value for p in PERMISSIONS],
        "scope": "granted_accounts",
    }


def test_the_schemas_lists_cap_and_members_are_the_builders() -> None:
    digest = _SCHEMAS["ReconciliationDigest"]
    body = digest_of(AccountId(ACCOUNT_A), _state(ACCOUNT_A))
    assert set(digest["required"]) == set(digest["properties"]) == set(body)
    ids = {"$ref": "#/components/schemas/ReconciliationDigestIds"}
    assert all(digest["properties"][name] == ids for name in DIGEST_LISTS)
    assert _SCHEMAS["ReconciliationDigestIds"]["maxItems"] == MAX_DIGEST_ITEMS
    assert digest["properties"]["position_drift"]["maxItems"] == MAX_DIGEST_ITEMS
    counts = body["counts"]
    assert isinstance(counts, dict) and set(counts) == {
        *DIGEST_LISTS,
        "position_drift",
        "unprotected",
    }
