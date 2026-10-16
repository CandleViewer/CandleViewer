"""RBAC allow/deny matrix regression pack (E09-Q03, SR-018; threats U3, U4, D1, D5).

Routes are discovered reflectively from the real FastAPI app and topics from the WS registry
(`23-ws-protocol.md` §6.3); `matrix.yaml` holds the reviewed expectation for every
(route or topic) x 5 actors. Adding a route or topic without a matrix row fails here, naming the
rows to add; so does a row whose route no longer exists. Every executed cell uses a real bearer
token for its actor against the real app (identity/backend seams faked, no network, C-13.5).
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient

from candleviewer.api.deny_by_default import (
    DECLARED_WS_ROUTES,
    UndeclaredRouteAtBuildError,
    assert_app_routes_declared,
    served_operations,
)
from candleviewer.auth.generated_permissions import Permission
from candleviewer.ws.permissions import TOPIC_PERMISSIONS
from candleviewer.ws.topics import MACHINE_KINDS
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
_ROW_INDEX: dict[str, int] = {k: i for i, k in enumerate(_OPS)}
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


def test_world_keeps_the_bars_builders_state_root_under_the_session_tmp_dir(
    world: World, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """A `bars.*` cell runs `register()`, which loads (and, on a bad blob, deletes) files under the
    bars state root, whose default is the production `/data/bars/state`. Pin the root the app's
    builders were wired with, as its own settings hold it (not the env var, not a literal)."""
    assert getattr(world.app.state, "bars_runtime", None) is not None, "bars must be wired"
    root = Path(world.app.state.app_context.settings.bars_state_root)
    assert root.is_relative_to(tmp_path_factory.getbasetemp().resolve()), f"bars state in {root}"


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


#: §6.4: one `machines.{kind}` row per entity kind, with that kind's read rule.
_MACHINE_ROWS = {f"machines.{k}": (m.permission, m.scope) for k, m in MACHINE_KINDS.items()}


def _row_of(pattern: str) -> str:
    """The matrix row a registry pattern belongs to: its family, or `machines.{kind}`."""
    family, _, rest = pattern.partition(".")
    return f"machines.{rest.split('.')[0].split(':')[0]}" if family == "machines" else family


def test_topic_matrix_is_total_over_the_ws_registry_and_agrees_with_it() -> None:
    registry = set(TOPIC_PERMISSIONS) | {"system"} | set(_MACHINE_ROWS)
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
        if fam in _MACHINE_ROWS:
            kind_perm, scope = _MACHINE_ROWS[fam]
            value = kind_perm.value if kind_perm else None
            assert (row["permission"], row["scope"]) == (value, scope.value), fam
    assert DECLARED_WS_ROUTES == {"/ws"}, "a new WS route needs its own matrix section"


def test_topic_matrix_is_total_over_registry_patterns_both_ways() -> None:
    """E17-S02: every `(topic pattern, permission)` pair in the declarative registry maps to a
    matrix row with the same permission, every row is reached by some pattern, and every row's
    `sample` parses to its own family."""
    from candleviewer.ws.topics import TOPIC_REGISTRY, parse_topic

    families = {_row_of(pattern) for pattern, _ in TOPIC_REGISTRY}
    assert families == set(_TOPICS), sorted(families ^ set(_TOPICS))
    for pattern, permission in TOPIC_REGISTRY:
        row = _TOPICS[_row_of(pattern)]
        assert row["permission"] == permission, pattern
    for fam, row in _TOPICS.items():
        assert _row_of(parse_topic(row["sample"]).ch) == fam, fam


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


def _is_csrf_refusal(resp: Any) -> bool:
    if resp.status_code != 403:
        return False
    try:
        return bool(resp.json().get("code") == "csrf_token_invalid")
    except ValueError:
        return False


def _anon_client_ip(key: str) -> tuple[str, int]:
    """One loopback source per matrix row for the unauthenticated actor, so the
    guard's per-IP refusal throttle (anti audit-flood, #2090) never turns a cell
    into a 429; the throttle itself is covered by test_csrf_double_submit.py."""
    return (f"127.0.{_ROW_INDEX[key] // 250}.{_ROW_INDEX[key] % 250 + 1}", 50000)


def _observe(method: str, actor: str, resp: Any) -> str:
    """SR-041 (#2090): an unsafe call with no session is refused by the CSRF guard before
    any route runs (contract: a session-unbound token is 403 `csrf_token_invalid`), which
    is stricter than the matrix's reviewed `401`, so that exact refusal satisfies it.
    A CSRF refusal never counts as an RBAC outcome for any other cell: every
    authenticated cell carries a session-bound token, so one here means the harness
    stopped exercising RBAC."""
    if _is_csrf_refusal(resp):
        unsafe_anon = actor == "unauthenticated" and method not in ("GET", "HEAD", "OPTIONS")
        return "401" if unsafe_anon else "csrf_token_invalid"
    return _classify(resp.status_code)


@pytest.mark.parametrize(("key", "actor"), _cells())
def test_cell_outcome_matches_matrix(world: World, key: str, actor: str) -> None:
    row = _OPS[key]
    method, path = key.split(" ", 1)
    req = row.get("request", {})
    started = time.perf_counter()
    body = req.get("json")
    client = world.client
    if actor == "unauthenticated":
        client = TestClient(world.app, client=_anon_client_ip(key), raise_server_exceptions=False)
    resp = client.request(
        method,
        fill_path(path, req.get("path")),
        params=req.get("params"),
        json=body if body is not None else ({} if method in ("POST", "PUT", "PATCH") else None),
        headers={**bearer(actor), **req.get("headers", {})},
    )
    observed = _observe(method, actor, resp)
    pending = actor in row.get("pending", {})
    # 501/503 after authorisation = backend not wired in the CI app (authz still passed); any
    # other 5xx is an unhandled error and fails the cell.
    unhandled = resp.status_code in range(500, 600) and resp.status_code not in (501, 503)
    cell_msg = f"{key} as {actor}: expected {row['outcomes'][actor]}, got {resp.status_code}"
    try:
        assert not unhandled, f"{key} as {actor}: unhandled server error {resp.status_code}"
        assert observed == row["outcomes"][actor], cell_msg
    except AssertionError:
        # Recorded AFTER the checks so a failing cell is red in the HTML artefact (#294).
        record_cell(_group(key), key, actor, "fail", started)
        raise
    record_cell(_group(key), key, actor, "xfail" if pending else "pass", started)


def test_not_executable_rows_still_refuse_the_unauthenticated_caller_or_say_why(
    world: World,
) -> None:
    """A `not_executable` row never hides a missing check: where the contract requires a session
    the unauthenticated caller must not get a 2xx, and the reason names the missing wiring."""
    for key, row in _OPS.items():
        if row["state"] != "not_executable":
            continue
        method, path = key.split(" ", 1)
        client = TestClient(world.app, client=_anon_client_ip(key), raise_server_exceptions=False)
        resp = client.request(
            method,
            fill_path(path),
            json={} if method in ("POST", "PUT", "PATCH") else None,
            headers=bearer("unauthenticated"),  # well-formed SR-041 pair, no session
        )
        refused = resp.status_code in (401, 422, 501, 503) or (
            method != "GET" and _is_csrf_refusal(resp)  # SR-041: no session, unsafe method
        )
        assert refused, f"{key}: {resp.status_code}"
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


# -- tripwire: not_executable rows for every logged-in actor (D1) -------------------------------

#: Status the fail-closed stub returns today, identical for every actor. A route that becomes
#: reachable changes a status here and turns the pack red; update a value only together with the
#: matrix row (and a Security review of matrix.yaml). Every value must stay inside
#: `_REFUSAL_STATUSES`: a pin can never be bumped to a success status, so a route that becomes
#: reachable without authorisation cannot be parked here (it must move to `executed`).
_REFUSAL_STATUSES: frozenset[int] = frozenset({401, 422, 501, 503})

_STUB_STATUS: dict[str, int] = {
    "GET /admin/health": 501,
    "PUT /admin/log-level": 501,
    "POST /auth/login": 422,
    "POST /auth/mfa/enroll": 422,
    "POST /auth/mfa/enroll/confirm": 422,
    "POST /auth/mfa/recovery": 422,
    "POST /auth/mfa/verify": 422,
    "POST /auth/refresh": 401,
    "GET /market/bars": 422,
    "GET /market/data-coverage": 422,  # required query params are validated before the 501/503
    "GET /market/klines": 422,
    "GET /onboarding/checklist": 501,
    "POST /onboarding/checklist/dismiss": 501,
}


def test_stub_status_table_covers_exactly_the_not_executable_rows() -> None:
    declared = {k for k, r in _OPS.items() if r["state"] == "not_executable"}
    assert declared == set(_STUB_STATUS), (
        f"not_executable rows without a stub status: {sorted(declared - set(_STUB_STATUS))}; "
        f"stale stub statuses: {sorted(set(_STUB_STATUS) - declared)}"
    )


def test_stub_statuses_are_refusals_never_successes() -> None:
    """A parked route may only pin a pre-authorisation refusal; pinning a success status would let
    a route that is reachable without authorisation hide in this table."""
    offenders = {k: v for k, v in _STUB_STATUS.items() if v not in _REFUSAL_STATUSES}
    assert not offenders, f"stub statuses outside {sorted(_REFUSAL_STATUSES)}: {offenders}"


@pytest.mark.parametrize("actor", [a for a in ACTORS if a != "unauthenticated"])
def test_not_executable_rows_keep_their_stub_status_for_every_logged_in_actor(
    world: World, actor: str
) -> None:
    """Silent exclusions are not permitted: each not_executable route must still answer its stub
    status as every logged-in actor, so a route that becomes reachable (or widens its permission,
    so a manager/viewer passes authorisation) fails the pack instead of hiding."""
    drifted: list[str] = []
    for key, expected in _STUB_STATUS.items():
        method, path = key.split(" ", 1)
        resp = world.client.request(
            method,
            fill_path(path),
            json={} if method in ("POST", "PUT", "PATCH") else None,
            headers=bearer(actor),
        )
        if resp.status_code != expected:
            drifted.append(f"{key}: expected {expected}, got {resp.status_code}")
    assert not drifted, f"{actor}: not_executable rows changed behaviour: {drifted}"
