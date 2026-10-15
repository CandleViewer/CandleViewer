"""E14-Q04 (#431) `/drawings` status x principal matrix and `x-rbac` behaviour, through the real
`create_app()` (conftest). `_drawings_contract` checks every request and response against
`22-api-openapi.yaml` (schema conformance both ways); schema rules: `test_drawings_schema_contract`,
batch: `test_drawings_batch_contract`, generated-document drift: `test_drawings_openapi_drift`.
"""

from __future__ import annotations

from typing import Any

import pytest
from _drawings_contract import MISSING, OPS, SPEC, SYMBOLS, Api, drawing

from tests.contract.rbac.rbac_harness import actor_permissions

OWNER, MANAGER, VIEWER, ANON = "owner", "manager_with_grant", "viewer", "unauthenticated"


def test_the_pack_spans_exactly_the_five_drawings_operations() -> None:
    ops = ["listDrawings", "createDrawing", "batchUpsertDrawings", "updateDrawing", "deleteDrawing"]
    assert sorted(OPS) == sorted(ops)


def test_scope_self_a_viewer_reads_its_own_and_nobody_lists_anothers(api: Api) -> None:
    viewers = api.seed(VIEWER)  # a viewer cannot create one: it lacks workspaces:write
    owners = api.create(OWNER)["id"]
    assert [d["id"] for d in api.listed(VIEWER)] == [viewers]
    assert [d["id"] for d in api.listed(OWNER)] == [owners]
    assert api.listed(MANAGER) == []


#: (operation, actor, target, status, code). Targets: `own` the actor's live drawing (the owner's
#: for the anonymous caller), `foreign` the owner's, `deleted` the owner's soft-deleted one, `bad`
#: an invalid request, `stale` a bad cursor/If-Match, `huge` 70 kB. An unsafe call with no session
#: meets SR-041 first: the documented 403 `csrf_token_invalid` (bare router 401: tests/drawings).
MATRIX: list[tuple[str, str, str, int, str | None]] = [
    ("listDrawings", OWNER, "own", 200, None),
    ("listDrawings", VIEWER, "own", 200, None),
    ("listDrawings", ANON, "own", 401, "unauthenticated"),
    ("listDrawings", OWNER, "stale", 400, "invalid_cursor"),
    ("listDrawings", OWNER, "bad", 422, "validation_failed"),
    ("createDrawing", OWNER, "own", 201, None),
    ("createDrawing", MANAGER, "own", 201, None),
    ("createDrawing", VIEWER, "own", 403, "forbidden"),
    ("createDrawing", ANON, "own", 403, "csrf_token_invalid"),
    ("createDrawing", OWNER, "huge", 413, "payload_too_large"),
    ("createDrawing", OWNER, "bad", 422, "validation_failed"),
    ("batchUpsertDrawings", MANAGER, "own", 200, None),
    ("batchUpsertDrawings", VIEWER, "own", 403, "forbidden"),
    ("batchUpsertDrawings", ANON, "own", 403, "csrf_token_invalid"),
    ("batchUpsertDrawings", OWNER, "bad", 422, "validation_failed"),
    ("updateDrawing", OWNER, "stale", 412, "version_conflict"),
    *[
        (op, actor, target, status or ok, code)
        for op, ok in (("updateDrawing", 200), ("deleteDrawing", 204))
        for actor, target, status, code in (
            (OWNER, "own", 0, None), (MANAGER, "own", 0, None),
            (VIEWER, "own", 403, "forbidden"), (ANON, "own", 403, "csrf_token_invalid"),
            (OWNER, "deleted", 404, "not_found"), (OWNER, "missing", 404, "not_found"),
            (MANAGER, "foreign", 404, "not_found"), (OWNER, "bad", 422, "validation_failed"),
        )
    ],
]  # fmt: skip


def _call(api: Api, op: str, actor: str, target: str) -> dict[str, Any]:
    """Seeds one live drawing per actor and one soft-deleted owner drawing; builds the request."""
    own = {a: api.seed(a) for a in (OWNER, MANAGER, VIEWER)}
    deleted = api.seed(OWNER)
    assert api.send(OWNER, "deleteDrawing", drawing_id=deleted).status_code == 204
    ids = {"foreign": own[OWNER], "deleted": deleted, "missing": MISSING, "bad": "not-a-uuid"}
    batch = {"operations": [{"op": "create", "drawing": drawing()}]}
    bodies = {"createDrawing": drawing(), "updateDrawing": drawing(), "batchUpsertDrawings": batch}
    variants: dict[str, dict[str, dict[str, Any]]] = {
        "bad": {"listDrawings": {"params": {}},
                "createDrawing": {"body": drawing(symbol="x"), "invalid": True},
                "batchUpsertDrawings": {"body": {"operations": []}, "invalid": True}},
        "stale": {"listDrawings": {"params": {"symbol": SYMBOLS[0], "cursor": "x"}},
                  "updateDrawing": {"headers": {"If-Match": '"2020-01-01T00:00:00.000000Z"'}}},
        "huge": {"createDrawing": {"body": None, "content": b"{" + b" " * 70_000 + b"}"}},
    }  # fmt: skip
    call = {
        "drawing_id": ids.get(target, own.get(actor, own[OWNER])), "body": bodies.get(op),
        "params": {"symbol": SYMBOLS[0]} if op == "listDrawings" else None,
    }  # fmt: skip
    return call | variants.get(target, {}).get(op, {})


@pytest.mark.parametrize(
    ("op", "actor", "target", "status", "code"), MATRIX, ids=[" ".join(m[:3]) for m in MATRIX]
)
def test_status_matrix(
    api: Api, op: str, actor: str, target: str, status: int, code: str | None
) -> None:
    call = _call(api, op, actor, target)
    before = (dict(api.repo.rows), dict(api.repo.deleted))
    r = api.send(actor, op, **call)
    assert r.status_code == status, r.text
    if code is None:
        return
    assert r.json()["code"] == code
    assert (api.repo.rows, api.repo.deleted) == before, "a refused call changed the store"
    if status == 404:  # foreign, soft-deleted and missing ids are indistinguishable (no oracle)
        assert r.json() == api.send(actor, op, **(call | {"drawing_id": MISSING})).json()


def test_the_matrix_refuses_exactly_the_actors_lacking_the_x_rbac_permission() -> None:
    for op, actor, _target, _status, code in MATRIX:
        method, path = OPS[op]
        rbac = SPEC["paths"][path][method.lower()]["x-rbac"]
        assert rbac["scope"] == "self", op
        if actor != ANON:
            lacking = not set(rbac["permissions"]) <= actor_permissions(actor, SPEC)
            assert lacking is (code == "forbidden"), (op, actor)
