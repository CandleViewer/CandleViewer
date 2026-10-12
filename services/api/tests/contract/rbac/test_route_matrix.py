"""RBAC allow/deny matrix regression pack (E09-Q03, SR-018; threats U3, U4, D1, D5).

Routes are discovered reflectively from the real FastAPI app and topics from the WS registry
(`23-ws-protocol.md` §6.3); `matrix.yaml` holds the reviewed expectation for every
(route or topic) x 5 actors. Adding a route or topic without a matrix row fails here, naming the
rows to add; so does a row whose route no longer exists. Every executed cell uses a real bearer
token for its actor against the real app (identity/backend seams faked, no network, C-13.5).
"""

from __future__ import annotations

import time
from typing import Any

import pytest
import yaml

from candleviewer.api.deny_by_default import (
    DECLARED_WS_ROUTES,
    UndeclaredRouteAtBuildError,
    assert_app_routes_declared,
    served_operations,
)
from candleviewer.auth.generated_permissions import Permission
from candleviewer.ws.permissions import TOPIC_PERMISSIONS
from tests.contract.rbac.rbac_harness import (
    ACTORS,
    HTTP,
    MATRIX_PATH,
    PUBLIC_OPERATIONAL,
    World,
    bearer,
    fill_path,
    load_contract,
    record_cell,
)

with MATRIX_PATH.open(encoding="utf-8") as _fh:
    _MATRIX: dict[str, Any] = yaml.safe_load(_fh)
_OPS: dict[str, dict[str, Any]] = _MATRIX["operations"]
_TOPICS: dict[str, dict[str, Any]] = _MATRIX["topics"]
_OUTCOMES = {"allow", "401", "403"}
_TOPIC_OUTCOMES = {"sub_ok", "not_authenticated", "forbidden", "account_scope_denied"}


def _contract_ops() -> set[str]:
    spec = load_contract()
    return {
        f"{m.upper()} {p}"
        for p, item in spec["paths"].items()
        for m in HTTP
        if isinstance(item.get(m), dict)
    }


def _served_ops(world: World) -> set[str]:
    return {
        f"{m} {p}"
        for m, p in served_operations(world.app)
        if p not in PUBLIC_OPERATIONAL and m.lower() in HTTP
    }


# -- totality (SR-018): both directions ---------------------------------------------------------


def test_matrix_covers_every_contract_operation_and_has_no_orphan_rows() -> None:
    contract = _contract_ops()
    missing = sorted(contract - set(_OPS))
    orphans = sorted(set(_OPS) - contract)
    assert not missing, (
        "operations in 22-api-openapi.yaml with no matrix row; add a row with all 5 actors "
        "to tests/contract/rbac/matrix.yaml for: " + ", ".join(missing)
    )
    assert not orphans, "matrix rows for operations that no longer exist: " + ", ".join(orphans)


def test_every_served_route_has_a_row_and_every_row_state_matches_the_app(world: World) -> None:
    served = _served_ops(world)
    undeclared = sorted(served - set(_OPS))
    missing_rows = "app serves routes with no matrix row; add rows (all 5 actors) for: "
    assert not undeclared, missing_rows + ", ".join(undeclared)
    now_mounted = sorted(k for k, r in _OPS.items() if r["state"] == "not_mounted" and k in served)
    assert not now_mounted, (
        "rows marked not_mounted are now served; change state to `executed` and fill in the "
        "outcomes for: " + ", ".join(now_mounted)
    )
    gone = sorted(k for k, r in _OPS.items() if r["state"] != "not_mounted" and k not in served)
    assert not gone, "rows marked executed/not_executable but not served: " + ", ".join(gone)


def test_every_row_defines_all_five_actors_with_known_outcomes_and_a_reason_when_skipped() -> None:
    vocab = {p.value for p in Permission}
    for key, row in _OPS.items():
        assert set(row["outcomes"]) == set(ACTORS), f"{key}: needs exactly the 5 actors"
        assert set(row["outcomes"].values()) <= _OUTCOMES, f"{key}: unknown outcome"
        assert set(row["permissions"]) <= vocab, f"{key}: permission outside the vocabulary"
        if row["state"] in ("not_mounted", "not_executable"):
            assert row.get("reason"), f"{key}: {row['state']} needs a recorded reason"
        assert row["state"] in ("executed", "not_mounted", "not_executable"), key
    assert _MATRIX["actors"] == list(ACTORS)


def test_matrix_permissions_and_scope_agree_with_the_contract() -> None:
    spec = load_contract()
    for key, row in _OPS.items():
        method, path = key.split(" ", 1)
        rbac = spec["paths"][path][method.lower()]["x-rbac"]
        assert row["permissions"] == list(rbac["permissions"]), f"{key}: permissions drifted"
        assert row["scope"] == rbac["scope"], f"{key}: scope drifted"


def test_topic_matrix_is_total_over_the_ws_registry_and_agrees_with_it() -> None:
    registry = set(TOPIC_PERMISSIONS) | {"system"}
    missing_topics = ", ".join(sorted(registry - set(_TOPICS)))
    topic_msg = f"WS topic families with no matrix row; add all 5 actors: {missing_topics}"
    assert not missing_topics, topic_msg
    assert not (set(_TOPICS) - registry), "orphan topic rows: " + ", ".join(
        sorted(set(_TOPICS) - registry)
    )
    for fam, row in _TOPICS.items():
        assert set(row["outcomes"]) == set(ACTORS), f"topic {fam}: needs the 5 actors"
        assert set(row["outcomes"].values()) <= _TOPIC_OUTCOMES, f"topic {fam}: bad outcome"
        if fam in TOPIC_PERMISSIONS:
            perm, scope = TOPIC_PERMISSIONS[fam]
            assert (row["permission"], row["scope"]) == (perm.value, scope.value), fam
    assert DECLARED_WS_ROUTES == {"/ws"}, "a new WS route needs its own matrix section"


def test_topic_matrix_is_total_over_registry_patterns_both_ways() -> None:
    """E17-S02: every `(topic pattern, permission)` pair in the declarative registry maps to a
    matrix row with the same permission, every row is reached by some pattern, and every row's
    `sample` parses to its own family."""
    from candleviewer.ws.topics import TOPIC_REGISTRY, parse_topic

    families = {pattern.split(".", 1)[0] for pattern, _ in TOPIC_REGISTRY}
    assert families == set(_TOPICS), sorted(families ^ set(_TOPICS))
    for pattern, permission in TOPIC_REGISTRY:
        row = _TOPICS[pattern.split(".", 1)[0]]
        assert row["permission"] == permission, pattern
    for fam, row in _TOPICS.items():
        assert parse_topic(row["sample"]).family.family == fam, fam


def test_vocabulary_single_source_check_exists_and_passes() -> None:
    """Consumes E09-T03's `rbac_vocabulary_single_source`; fails loudly if it is gone."""
    try:
        from candleviewer.api.rbac_conformance import assert_vocabulary_single_source
    except ImportError:  # pragma: no cover - the failure mode is the point
        pytest.fail("E09-T03 rbac_vocabulary_single_source (api/rbac_conformance) is missing")
    assert_vocabulary_single_source()  # raises VocabularyMismatchError on drift


# -- every cell, real session per actor ---------------------------------------------------------


def _group(key: str) -> str:
    first = key.split(" ", 1)[1].strip("/").split("/")[0]
    return first or "root"


def _cells() -> list[Any]:
    out: list[Any] = []
    for key, row in _OPS.items():
        if row["state"] != "executed":
            continue
        for actor in ACTORS:
            marks = []
            if actor in row.get("pending", {}):
                marks.append(
                    pytest.mark.xfail(strict=True, reason=f"pending {row['pending'][actor]}")
                )
            out.append(pytest.param(key, actor, id=f"{key}|{actor}", marks=marks))
    return out


def _classify(status: int) -> str:
    return {401: "401", 403: "403"}.get(status, "allow")


@pytest.mark.parametrize(("key", "actor"), _cells())
def test_cell_outcome_matches_matrix(world: World, key: str, actor: str) -> None:
    row = _OPS[key]
    method, path = key.split(" ", 1)
    req = row.get("request", {})
    started = time.perf_counter()
    body = req.get("json")
    resp = world.client.request(
        method,
        fill_path(path, req.get("path")),
        params=req.get("params"),
        json=body if body is not None else ({} if method in ("POST", "PUT", "PATCH") else None),
        headers={**bearer(actor), **req.get("headers", {})},
    )
    observed = _classify(resp.status_code)
    pending = actor in row.get("pending", {})
    record_cell(_group(key), key, actor, "xfail" if pending else "pass", started)
    # 501/503 after authorisation = backend not wired in the CI app (authz still passed); any
    # other 5xx is an unhandled error and fails the cell.
    unhandled = resp.status_code in range(500, 600) and resp.status_code not in (501, 503)
    assert not unhandled, f"{key} as {actor}: unhandled server error {resp.status_code}"
    cell_msg = f"{key} as {actor}: expected {row['outcomes'][actor]}, got {resp.status_code}"
    assert observed == row["outcomes"][actor], cell_msg


def test_not_executable_rows_still_refuse_the_unauthenticated_caller_or_say_why(
    world: World,
) -> None:
    """A `not_executable` row never hides a missing check: where the contract requires a session
    the unauthenticated caller must not get a 2xx, and the reason names the missing wiring."""
    for key, row in _OPS.items():
        if row["state"] != "not_executable":
            continue
        method, path = key.split(" ", 1)
        resp = world.client.request(
            method,
            fill_path(path),
            json={} if method in ("POST", "PUT", "PATCH") else None,
            headers=bearer("unauthenticated"),  # SR-041 pair only, so the route itself answers
        )
        assert resp.status_code in (401, 422, 501, 503), f"{key}: {resp.status_code}"
        assert resp.status_code < 200 or resp.status_code >= 300, f"{key}: unauthenticated 2xx"


def test_undeclared_served_route_fails_the_build(world: World) -> None:
    """SR-017 / mutation (a): a served route without an RBAC declaration refuses to start."""
    from fastapi import APIRouter

    router = APIRouter()
    router.add_api_route("/__matrix_probe__", lambda: {"ok": True}, methods=["GET"])
    world.app.include_router(router)
    try:
        with pytest.raises(UndeclaredRouteAtBuildError):
            assert_app_routes_declared(world.app, world.spec)
    finally:
        world.app.router.routes[:] = [
            r for r in world.app.router.routes if getattr(r, "path", "") != "/__matrix_probe__"
        ]
