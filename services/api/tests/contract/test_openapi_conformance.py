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

import jsonschema
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
# SR-055 and AC6: role, status and grant changes never target the acting user.
_SELF_TARGET_REFUSED = [
    ("/users/{userId}", "patch"),
    ("/users/{userId}", "delete"),
    ("/users/{userId}/roles", "put"),
    ("/users/{userId}/account-access", "put"),
]
# O2 and AC7: every disable or unbind path takes the acknowledgement.
_POSITION_ACK_OPS = [
    ("/users/{userId}", "patch"),
    ("/users/{userId}", "delete"),
    ("/users/{userId}/account-access", "put"),
]
_CITED_CODE = re.compile(r"`(\d{3}) ([a-z_]+)`")
_SELF_TARGET_403 = re.compile(r"caller's own [^.]*\(`403 forbidden`\)")
_REFUSAL_AUDITED = re.compile(r"refused for a forbidden role[^.]* is audited too")


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
    """`validation_failed` may also be the `422` of `UnprocessableEntity`, as the market contract
    tests allow: `deleteUser` refuses an undeclared query key so (SR-026, E42-T04 S7)."""
    cited = _CITED_CODE.findall(spec["paths"][path][method]["description"])
    assert cited
    registered = _registered(spec)
    allowed = {(code, registered.get(code)) for _, code in cited} | {("validation_failed", 422)}
    assert all((code, int(status)) in allowed for status, code in cited), cited


@pytest.mark.parametrize(("path", "method"), _LIFECYCLE_MUTATIONS)
def test_lifecycle_mutation_declares_every_status_it_cites(
    spec: dict[str, Any], path: str, method: str
) -> None:
    op = spec["paths"][path][method]
    cited = {status for status, _ in _CITED_CODE.findall(op["description"])}
    assert cited <= set(op["responses"]), cited - set(op["responses"])


@pytest.mark.parametrize(
    ("path", "method", "statuses"),
    [
        ("/users/{userId}", "patch", {"200", "400", "401", "403", "404", "409", "412", "503"}),
        ("/users/{userId}", "delete", {"204", "400", "401", "403", "404", "409", "422", "503"}),
        ("/users/{userId}/roles", "put", {"200", "400", "401", "403", "404", "409", "503"}),
        (
            "/users/{userId}/account-access",
            "put",
            {"200", "400", "401", "403", "404", "409", "503"},
        ),
        ("/users/{userId}/sessions/{sessionId}", "delete", {"204", "401", "403", "404", "503"}),
    ],
)
def test_lifecycle_mutation_declares_exactly_the_planned_statuses(
    spec: dict[str, Any], path: str, method: str, statuses: set[str]
) -> None:
    assert set(spec["paths"][path][method]["responses"]) == statuses


@pytest.mark.parametrize(("path", "method"), _SELF_TARGET_REFUSED)
def test_role_status_and_grant_change_refuses_a_self_target_with_403(
    spec: dict[str, Any], path: str, method: str
) -> None:
    assert _SELF_TARGET_403.search(spec["paths"][path][method]["description"])


@pytest.mark.parametrize(("path", "method"), _LIFECYCLE_MUTATIONS)
def test_lifecycle_mutation_audits_a_refusal_for_a_forbidden_role(
    spec: dict[str, Any], path: str, method: str
) -> None:
    assert _REFUSAL_AUDITED.search(spec["paths"][path][method]["description"])


@pytest.mark.parametrize("method", ["delete", "patch"])
def test_disable_through_delete_or_patch_states_the_sr029_cascade(
    spec: dict[str, Any], method: str
) -> None:
    named = set(re.findall(r"`[^`]+`", spec["paths"]["/users/{userId}"][method]["description"]))
    assert {"`user_disabled`", "`4403`", "`users.disable`"} <= named


def test_admin_user_session_listing_is_owner_read_only(spec: dict[str, Any]) -> None:
    listing = spec["paths"]["/users/{userId}/sessions"]["get"]
    assert listing["x-rbac"] == {"permissions": ["users:read"], "scope": "none"}


def test_admin_user_session_listing_reuses_the_me_sessions_item(spec: dict[str, Any]) -> None:
    ok = spec["paths"]["/users/{userId}/sessions"]["get"]["responses"]["200"]
    items = ok["content"]["application/json"]["schema"]["properties"]["items"]
    assert items["items"] == {"$ref": "#/components/schemas/UserSession"}


def test_user_session_item_carries_no_token_material(spec: dict[str, Any]) -> None:
    session_fields = spec["components"]["schemas"]["UserSession"]["properties"]
    assert not {f for f in session_fields if "token" in f or "hash" in f}


def test_get_user_returns_an_etag_for_if_match(spec: dict[str, Any]) -> None:
    ok = spec["paths"]["/users/{userId}"]["get"]["responses"]["200"]
    assert ok["headers"]["ETag"] == {"$ref": "#/components/headers/ETag"}


@pytest.mark.parametrize(("path", "method"), _POSITION_ACK_OPS)
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


# -- E42-T04 S1 (#965), Q4 ruling on #2648: contract amendments for account access ----------------

_GRANT = {"exchange_account_id": "a1000000-0000-4000-8000-000000000002", "level": "trade"}
_GRANT_READ_ONLY = {
    "account_label": "Main",
    "environment": "demo",
    "granted_at": "2026-10-16T12:00:00Z",
    "granted_by": "a1000000-0000-4000-8000-000000000001",
}
# The freeze and the cap have their own routes (E39); the grantor is the caller, the user the path.
_UNDECLARED_GRANT_FIELDS = ("frozen", "frozen_at", "max_daily_loss_usd", "granted_by", "user_id")
_EVERY_REMOVAL_ACK = re.compile(
    r"every request that removes a live grant[^.]*, not only the last one, must carry "
    r"`acknowledge_unknown_positions=true`, otherwise `409 positions_unknown`"
)


def _flat(text: str) -> str:
    """Collapse YAML line wrapping so a prose pin survives a re-wrap."""
    return " ".join(text.split())


def _schema_errors(spec: dict[str, Any], name: str, body: dict[str, Any]) -> list[str]:
    root = {"$ref": f"#/components/schemas/{name}", "components": spec["components"]}
    return [e.message for e in jsonschema.Draft202012Validator(root).iter_errors(body)]


def test_audit_unavailable_is_registered_exactly_once(spec: dict[str, Any]) -> None:
    codes = [entry["code"] for entry in spec["x-error-codes"]]
    assert codes.count("audit_unavailable") == 1


def test_list_user_account_access_declares_its_auth_lookup_and_availability_failures(
    spec: dict[str, Any],
) -> None:
    op = spec["paths"]["/users/{userId}/account-access"]["get"]
    assert set(op["responses"]) == {"200", "401", "403", "404", "503"}
    assert op["responses"]["401"] == {"$ref": "#/components/responses/Unauthorized"}
    assert op["responses"]["404"] == {"$ref": "#/components/responses/NotFound"}
    assert op["responses"]["503"] == {"$ref": "#/components/responses/ServiceUnavailable"}
    assert "Retry-After" in spec["components"]["responses"]["ServiceUnavailable"]["headers"]
    cited = _CITED_CODE.findall(op["description"])  # the two codes its `503` carries
    assert sorted(cited) == [("503", "audit_unavailable"), ("503", "store_unavailable")]
    assert all(_registered(spec).get(code) == int(status) for status, code in cited), cited


def test_account_access_grant_input_declares_only_the_account_and_the_level(
    spec: dict[str, Any],
) -> None:
    schema = spec["components"]["schemas"]["AccountAccessGrantInput"]
    assert schema["additionalProperties"] is False
    assert set(schema["properties"]) == {"exchange_account_id", "level"}
    assert schema["required"] == ["exchange_account_id", "level"]


@pytest.mark.parametrize("extra", _UNDECLARED_GRANT_FIELDS)
def test_account_access_grant_input_refuses_an_undeclared_field(
    spec: dict[str, Any], extra: str
) -> None:
    assert _schema_errors(spec, "AccountAccessGrantInput", _GRANT) == []
    assert _schema_errors(spec, "AccountAccessGrantInput", {**_GRANT, extra: True})


def test_account_access_grant_response_accepts_its_read_only_fields(spec: dict[str, Any]) -> None:
    assert _schema_errors(spec, "AccountAccessGrant", {**_GRANT, **_GRANT_READ_ONLY}) == []


def test_account_access_put_requires_the_acknowledgement_for_every_removal(
    spec: dict[str, Any],
) -> None:
    text = _flat(spec["paths"]["/users/{userId}/account-access"]["put"]["description"])
    assert _EVERY_REMOVAL_ACK.search(text), text


def test_unknown_positions_acknowledgement_is_an_optional_boolean_query_parameter(
    spec: dict[str, Any],
) -> None:
    param = spec["components"]["parameters"]["AcknowledgeUnknownPositions"]
    assert (param["in"], param["required"]) == ("query", False)
    assert param["schema"] == {"type": "boolean", "default": False}


def test_unknown_positions_acknowledgement_parameter_covers_every_removal(
    spec: dict[str, Any],
) -> None:
    text = _flat(spec["components"]["parameters"]["AcknowledgeUnknownPositions"]["description"])
    assert "removes any live account grant (every removal, not only the last one)" in text


def test_admin_user_session_listing_declares_its_auth_and_lookup_failures(
    spec: dict[str, Any],
) -> None:
    responses = spec["paths"]["/users/{userId}/sessions"]["get"]["responses"]
    assert set(responses) == {"200", "401", "403", "404", "503"}  # 503: #2295 guard


def test_admin_user_session_listing_needs_no_step_up_but_revoking_does(
    spec: dict[str, Any],
) -> None:
    listing = spec["paths"]["/users/{userId}/sessions"]["get"]["description"]
    revoke = spec["paths"]["/users/{userId}/sessions/{sessionId}"]["delete"]["description"]
    assert "listing needs no step-up" in _flat(listing)
    assert _flat(revoke).startswith("Requires step-up `users`.")
