"""Contract-conformance tests (E03-T06 acceptance criterion: "Contract drift
between server and OpenAPI fails").

Runs against `docs/plan/22-api-openapi.yaml` and the live `create_app()`
route table so a route added to the FastAPI app without a matching OpenAPI
operation fails this suite before it ever reaches CI's `contract` job.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

from candleviewer.api.contract_conformance import (
    ContractDriftError,
    assert_spec_is_valid,
    find_drift,
    load_openapi_spec,
    spec_paths,
)
from candleviewer.app import create_app
from candleviewer.settings import Settings


@pytest.fixture(scope="module")
def spec() -> dict:
    return load_openapi_spec()


def test_openapi_spec_is_structurally_valid(spec: dict) -> None:
    assert_spec_is_valid(spec)


def test_openapi_spec_has_paths(spec: dict) -> None:
    assert len(spec_paths(spec)) > 0


def _app_routes() -> list[tuple[str, str]]:
    app = create_app(Settings(git_sha="test", version="0.0.0-test"))
    routes: list[tuple[str, str]] = []
    for route in app.routes:
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None)
        if path is None or methods is None:
            continue
        for method in methods:
            if method == "HEAD":
                continue
            routes.append((path, method))
    return routes


def test_app_routes_have_no_contract_drift(spec: dict) -> None:
    """Scenario: contract drift between server and OpenAPI fails.

    Today's app only serves `/healthz`, `/readyz` and `/metrics` (R0
    scaffold) — none of which are declared REST-contract paths, so this
    exercises the allow-list path. Once a real route lands without a
    matching OpenAPI operation, this test fails with the CI-CON-001 message
    naming the exact route and method (the acceptance criterion's "job
    fails identifying the route and the offending field").
    """
    drift = find_drift(_app_routes(), spec)
    assert drift == [], "\n".join(str(d) for d in drift)


def test_contract_drift_error_names_route_and_method() -> None:
    """A synthetic drift case proves the failure message is actionable."""
    spec_with_no_paths: dict = {"paths": {}}
    drift = find_drift([("/orders", "post")], spec_with_no_paths)
    assert len(drift) == 1
    assert isinstance(drift[0], ContractDriftError)
    assert "/orders" in str(drift[0])
    assert "POST" in str(drift[0])


def test_openapi_spec_path_is_where_this_test_expects() -> None:
    from candleviewer.api.contract_conformance import OPENAPI_SPEC_PATH

    assert OPENAPI_SPEC_PATH.name == "22-api-openapi.yaml"
    assert Path(OPENAPI_SPEC_PATH).is_file()


_INVITE_OPS = [
    ("/users", "post"),
    ("/users/invites", "get"),
    ("/users/{userId}/invite", "post"),
    ("/users/{userId}/invite", "delete"),
    ("/invites/{inviteToken}", "get"),
    ("/invites/{inviteToken}", "post"),
    ("/invites/{inviteToken}/confirm", "post"),
]


@pytest.mark.parametrize(("path", "method"), _INVITE_OPS)
def test_invite_operations_declared_in_spec(spec: dict, path: str, method: str) -> None:
    """E09-S05: every invite route is declared in the OpenAPI contract."""
    assert method in spec["paths"][path]


def test_invite_redeem_bodies_forbid_extra_fields(spec: dict) -> None:
    """Role immutability is part of the contract: no free-form invitee body."""
    for path in ("/invites/{inviteToken}", "/invites/{inviteToken}/confirm"):
        schema = spec["paths"][path]["post"]["requestBody"]["content"]["application/json"]["schema"]
        assert schema["additionalProperties"] is False
        assert "role" not in schema["properties"]


# -- E42-T04 S1 (#965): user-lifecycle contract deltas ------------------------------------------

_LIFECYCLE_MUTATIONS = [
    ("/users/{userId}", "patch"),
    ("/users/{userId}", "delete"),
    ("/users/{userId}/roles", "put"),
    ("/users/{userId}/account-access", "put"),
    ("/users/{userId}/sessions/{sessionId}", "delete"),
]
_CITED_CODE = re.compile(r"`(\d{3}) ([a-z_]+)`")


def _registered(spec: dict[str, Any]) -> dict[str, int]:
    return {e["code"]: e["status"] for e in spec["x-error-codes"]}


def _param_names(spec: dict[str, Any], op: dict[str, Any]) -> set[str]:
    params = spec["components"]["parameters"]
    return {
        params[p["$ref"].rsplit("/", 1)[1]]["name"] if "$ref" in p else p["name"]
        for p in op.get("parameters", [])
    }


def test_audit_unavailable_is_a_registered_retryable_503(spec: dict[str, Any]) -> None:
    entry = next(e for e in spec["x-error-codes"] if e["code"] == "audit_unavailable")
    assert (entry["status"], entry["retryable"]) == (503, True)


@pytest.mark.parametrize(("path", "method"), _LIFECYCLE_MUTATIONS)
def test_lifecycle_mutation_declares_csrf_step_up_and_audit_failure(
    spec: dict[str, Any], path: str, method: str
) -> None:
    op = spec["paths"][path][method]
    assert op["x-rbac"] == {"permissions": ["users:write"], "scope": "none"}
    assert {"401", "403", "503"} <= set(op["responses"])
    assert "X-CSRF-Token" in _param_names(spec, op)
    assert "step-up `users`" in op["description"]
    assert "`503 audit_unavailable`" in op["description"]


@pytest.mark.parametrize(("path", "method"), _LIFECYCLE_MUTATIONS)
def test_lifecycle_mutation_cites_only_registered_codes_with_their_status(
    spec: dict[str, Any], path: str, method: str
) -> None:
    cited = _CITED_CODE.findall(spec["paths"][path][method]["description"])
    assert cited
    registered = _registered(spec)
    assert all(registered.get(code) == int(status) for status, code in cited), cited


def test_admin_user_sessions_mirror_me_sessions_without_token_material(
    spec: dict[str, Any],
) -> None:
    listing = spec["paths"]["/users/{userId}/sessions"]["get"]
    assert listing["x-rbac"] == {"permissions": ["users:read"], "scope": "none"}
    items = listing["responses"]["200"]["content"]["application/json"]["schema"]
    assert items["properties"]["items"]["items"] == {"$ref": "#/components/schemas/UserSession"}
    session_fields = spec["components"]["schemas"]["UserSession"]["properties"]
    assert not {f for f in session_fields if "token" in f or "hash" in f}
    revoke = spec["paths"]["/users/{userId}/sessions/{sessionId}"]["delete"]
    assert {"204", "404"} <= set(revoke["responses"])


def test_get_user_returns_an_etag_for_if_match(spec: dict[str, Any]) -> None:
    ok = spec["paths"]["/users/{userId}"]["get"]["responses"]["200"]
    assert ok["headers"]["ETag"] == {"$ref": "#/components/headers/ETag"}


@pytest.mark.parametrize(
    ("path", "method"), [("/users/{userId}", "delete"), ("/users/{userId}/account-access", "put")]
)
def test_disable_and_unbind_take_the_unknown_positions_acknowledgement(
    spec: dict[str, Any], path: str, method: str
) -> None:
    op = spec["paths"][path][method]
    assert "acknowledge_unknown_positions" in _param_names(spec, op)
    assert "`409 positions_unknown`" in op["description"]


def test_account_access_names_the_revoked_frame_not_unsubscribed(spec: dict[str, Any]) -> None:
    text = spec["paths"]["/users/{userId}/account-access"]["put"]["description"]
    assert "`revoked`" in text and "account_scope_changed" in text
    assert "unsubscribed" not in text


def test_set_user_roles_documents_the_shipped_id_and_roles_body(spec: dict[str, Any]) -> None:
    ok = spec["paths"]["/users/{userId}/roles"]["put"]["responses"]["200"]
    schema = ok["content"]["application/json"]["schema"]
    assert schema["required"] == ["id", "roles"] and set(schema["properties"]) == {"id", "roles"}


def test_update_user_refuses_mfa_opt_out_and_non_lifecycle_status(spec: dict[str, Any]) -> None:
    props = spec["components"]["schemas"]["UpdateUserRequest"]["properties"]
    assert props["mfa_required"]["enum"] == [True]
    assert props["status"]["enum"] == ["active", "disabled"]
