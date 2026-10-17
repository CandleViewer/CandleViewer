"""Enrolment-only session contract (#2295, #2344), slice 1/3: contract only (C-6.1).

Pins main-orchestrator's decisions of 2026-10-15, recorded on #2295, together with ADR-0010
decision 2 (revoke-all on a TOTP change). A user with `mfa_required` and no confirmed MFA method
gets an enrolment-only session from `POST /auth/login` and from every recovery sign-in, which
first revokes the user's MFA methods and other sessions. That session may call five operations,
gets `403 mfa_enrollment_required` from every other one, is refused by the WebSocket, and lives
at most 15 minutes; refresh never extends it. `POST /auth/mfa/enroll/confirm` confirms only the
latest enrolment's method, revokes the user's other TOTP methods and other sessions, rotates the
calling session to a full one and returns 10 new recovery codes, which move there from the enrol
`201`. The routes keep today's behaviour until the enforcement and endpoint slices land;
`tests/unit/api/test_auth_router.py` pins that runtime and this slice leaves it alone.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.audit.actions import AUDIT_ACTIONS
from candleviewer.ws._generated.error_codes import ERROR_META, WS_ERROR_CODES, ErrorCode

_BASE = "urn:cv:openapi"
_CODE = "mfa_enrollment_required"
_PLAN = Path(__file__).resolve().parents[4] / "docs" / "plan"
#: The reviewed RBAC matrix: its `public: false` rows are the operations that need a session.
_MATRIX = Path(__file__).resolve().parent / "rbac" / "matrix.yaml"
#: The only operations an enrolment-only session may call (decision on #2295).
_ALLOWED = {
    ("post", "/auth/mfa/enroll"),
    ("post", "/auth/mfa/enroll/confirm"),
    ("get", "/auth/session"),
    ("post", "/auth/refresh"),
    ("post", "/auth/logout"),
}
_SELF_SERVICE = {"permissions": [], "scope": "self"}
_OPERATION = re.compile(r"`(GET|POST|PUT|PATCH|DELETE) (/[^`]+)`")
#: How the contract cites ADR-0010 decision 2 wherever a TOTP change revokes sessions.
_REVOKE_ALL = "revoke-all on a TOTP change, ADR-0010 decision 2"
#: Responses whose `user` the client routes on (the enrolment-only test needs both flags).
_SESSION_SCHEMAS = {
    "#/components/schemas/LoginResponse",
    "#/components/schemas/AuthenticatedResponse",
    "#/components/schemas/MfaEnrollConfirmResponse",
    "#/components/schemas/SessionInfo",
}


@pytest.fixture(scope="module")
def spec() -> dict[str, Any]:
    return load_openapi_spec()


def _op(spec: dict[str, Any], method: str, path: str) -> dict[str, Any]:
    op: dict[str, Any] = spec["paths"][path][method]
    return op


def _ok(spec: dict[str, Any], path: str) -> dict[str, Any]:
    response: dict[str, Any] = _op(spec, "post", path)["responses"]["200"]
    return response


def _conforms(spec: dict[str, Any], value: Any, pointer: str) -> None:
    resource = Resource.from_contents(spec, default_specification=DRAFT202012)
    Draft202012Validator(
        {"$ref": f"{_BASE}#{pointer}"},
        registry=Registry().with_resource(_BASE, resource),
        format_checker=Draft202012Validator.FORMAT_CHECKER,
    ).validate(value)


def _flat(text: str) -> str:
    """Collapse YAML line wrapping so prose pins survive a re-wrap."""
    return " ".join(text.split())


def _described(spec: dict[str, Any], method: str, path: str) -> str:
    return _flat(_op(spec, method, path)["description"])


def _section(spec: dict[str, Any]) -> str:
    text: str = spec["info"]["description"]
    start = text.index("### Enrolment-only session")
    return _flat(text[start : text.index("\n### ", start)])


def _bullet(section: str, title: str) -> str:
    start = section.index(f"**{title}.**")
    end = section.find("* **", start)
    return section[start : end if end != -1 else None]


def _confirm_example(spec: dict[str, Any]) -> dict[str, Any]:
    examples = _ok(spec, "/auth/mfa/enroll/confirm")["content"]["application/json"]["examples"]
    value: dict[str, Any] = examples["rotated"]["value"]
    return value


def _between(doc: str, start: str, end: str) -> str:
    first = doc.index(start)
    return doc[first : doc.index(end, first)]


def _session_example_users(spec: dict[str, Any]) -> Iterator[tuple[str, dict[str, Any]]]:
    for path, item in spec["paths"].items():
        for method, op in item.items():
            if not isinstance(op, dict) or "responses" not in op:
                continue
            for status, response in op["responses"].items():
                media = response.get("content", {}).get("application/json", {})
                if media.get("schema", {}).get("$ref") not in _SESSION_SCHEMAS:
                    continue
                for name, example in media.get("examples", {}).items():
                    if "user" in example["value"]:
                        yield f"{method} {path} {status} {name}", example["value"]["user"]


def test_error_registry_mfa_enrollment_required_is_a_rest_only_403(spec: dict[str, Any]) -> None:
    entry = {e["code"]: e for e in spec["x-error-codes"]}[_CODE]
    assert (entry["status"], entry["retryable"]) == (403, False)
    assert entry.get("surface", ["rest"]) == ["rest"]  # the WS refuses with a `bye`, not an `err`
    assert ERROR_META[ErrorCode(_CODE)].surfaces == ("rest",)
    assert ErrorCode(_CODE) not in WS_ERROR_CODES


def test_forbidden_response_documents_the_code_with_a_conforming_example(
    spec: dict[str, Any],
) -> None:
    forbidden = spec["components"]["responses"]["Forbidden"]
    assert f"`code: {_CODE}`" in forbidden["description"]
    example = forbidden["content"]["application/problem+json"]["examples"]["mfaEnrollmentRequired"]
    _conforms(spec, example["value"], "/components/schemas/Problem")
    title = {e["code"]: e["title"] for e in spec["x-error-codes"]}[_CODE]
    assert (example["value"]["code"], example["value"]["status"]) == (_CODE, 403)
    assert example["value"]["title"] == title


def test_section_allows_exactly_the_five_operations(spec: dict[str, Any]) -> None:
    bullet = _bullet(_section(spec), "Allowed operations")
    named = {(method.lower(), path) for method, path in _OPERATION.findall(bullet)}
    assert named == _ALLOWED
    for method, path in _ALLOWED:
        assert method in spec["paths"][path]
    assert f"answers `403 {_CODE}` and changes nothing" in bullet
    assert "The WebSocket refuses the session at `auth`" in bullet


@pytest.mark.parametrize(
    "rule",
    [
        "The restriction is derived from the user's state on every request; the session carries "
        "no flag.",
        "an owner TOTP reset (which also sets `mfa_required`) or by any recovery sign-in",
        "that call revokes every other session of the user, so no session minted on the password "
        "alone outlives the enrolment",
        "its `auth.session_created` audit record carries `enrolment_only: true`",
        "it first revokes every MFA method and every other session of the user",
        "Every `user` object in an `AuthenticatedResponse` or a `SessionInfo` carries both "
        "`mfa_required` and `mfa_enabled`.",
        "The client treats the session as enrolment-only exactly when `user.mfa_required` is true "
        "and `user.mfa_enabled` is false",
        "A session minted enrolment-only lives at most 15 minutes from sign-in.",
        "the successor keeps the same absolute expiry, so refresh never extends it",
        "`refresh_expires_in` and the cookies' `Max-Age` count down to that expiry",
        "Only the method created by the user's latest `POST /auth/mfa/enroll` can be confirmed, "
        "once; a method that a recovery sign-in or an owner reset revoked never can.",
        f"The call also revokes every other session of the user ({_REVOKE_ALL}).",
        "It then rotates the session (SR-013): the enrolment-only session is revoked",
        "C-12.2 forbids them (TOTP is mandatory for every user), and #965 refuses "
        "`mfa_required: false`.",
        "The state is outside v1 and fails closed: `POST /auth/login` mints no session",
        "`POST /auth/mfa/recovery` mints none and consumes nothing",
    ],
)
def test_section_states_the_decided_rule(spec: dict[str, Any], rule: str) -> None:
    assert rule in _section(spec)


def test_contract_promises_no_undeclared_status_and_no_production_claim(
    spec: dict[str, Any],
) -> None:
    texts = [
        _section(spec),
        _described(spec, "post", "/auth/login"),
        _described(spec, "post", "/auth/mfa/recovery"),
        _flat(spec["components"]["schemas"]["User"]["properties"]["mfa_required"]["description"]),
    ]
    for text in texts:
        assert "`501`" not in text  # no operation declares a 501 or registers its code (C2)
        assert "production" not in text.lower()  # C-12.2 forbids the state; #965 refuses it
    for path in ("/auth/login", "/auth/mfa/recovery"):
        assert "501" not in _op(spec, "post", path)["responses"]


def _needs_a_session() -> set[tuple[str, str]]:
    rows = yaml.safe_load(_MATRIX.read_text(encoding="utf-8"))["operations"]
    lines = (line.split(" ", 1) for line, row in rows.items() if not row["public"])
    return {(method.lower(), path) for method, path in lines}


def _response(spec: dict[str, Any], method: str, path: str, status: str) -> dict[str, Any]:
    response: dict[str, Any] = _op(spec, method, path)["responses"].get(status, {})
    ref = response.get("$ref", "")
    return spec["components"]["responses"][ref.rsplit("/", 1)[1]] if ref else response


def test_every_operation_that_refuses_an_enrolment_only_session_declares_403(
    spec: dict[str, Any],
) -> None:
    """C-6.2: each operation that needs a session, outside the five, answers such a session
    `403 mfa_enrollment_required`, so it declares the status and its response names the code
    (#2295 review)."""
    refused = _needs_a_session() - _ALLOWED
    undeclared = sorted(
        f"{method.upper()} {path}"
        for method, path in refused
        if _CODE not in _response(spec, method, path, "403").get("description", "")
    )
    assert refused and undeclared == []


def test_every_operation_that_needs_a_session_declares_503(spec: dict[str, Any]) -> None:
    """C-6.2: the guard answers `503 store_unavailable` on each operation that needs a session,
    the five included, when the session or its user cannot be read (#2295 review)."""
    undeclared = sorted(
        f"{method.upper()} {path}"
        for method, path in _needs_a_session()
        if "503" not in _op(spec, method, path)["responses"]
    )
    assert undeclared == []
    example = spec["components"]["responses"]["ServiceUnavailable"]["content"]
    code = example["application/problem+json"]["examples"]["storeUnavailable"]["value"]["code"]
    assert code == "store_unavailable"


def test_login_mints_an_enrolment_only_session_for_a_user_without_a_method(
    spec: dict[str, Any],
) -> None:
    description = _described(spec, "post", "/auth/login")
    assert "the session is **enrolment-only**" in description
    assert "Its `auth.session_created` audit record carries `enrolment_only: true`" in description
    assert "the login fails closed and mints no session" in description
    examples = _ok(spec, "/auth/login")["content"]["application/json"]["examples"]
    assert set(examples) == {"mfaChallenge", "enrolmentOnly"}  # login never mints a full session
    body = examples["enrolmentOnly"]["value"]
    _conforms(spec, body, "/components/schemas/LoginResponse")
    assert (body["user"]["mfa_required"], body["user"]["mfa_enabled"]) == (True, False)
    assert body["tokens"]["refresh_expires_in"] <= 15 * 60


def test_recovery_always_forces_reenrolment_with_an_enrolment_only_session(
    spec: dict[str, Any],
) -> None:
    op = _op(spec, "post", "/auth/mfa/recovery")
    assert op["security"] == []  # pre-session, like `POST /auth/mfa/verify`
    assert op["x-idempotency"] == "ignored"  # it mints tokens, which are never stored for a replay
    assert _ok(spec, "/auth/mfa/recovery")["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/AuthenticatedResponse"
    }
    assert "Set-Cookie" in _ok(spec, "/auth/mfa/recovery")["headers"]
    description = _flat(op["description"])
    assert "Every recovery sign-in forces TOTP re-enrolment, however many codes remain" in (
        description
    )
    assert "mints an **enrolment-only** session" in description
    assert "fewer than three codes" not in description


@pytest.mark.parametrize(
    "rule",
    [
        "It revokes every MFA method of the user, terminally, so no old method can be confirmed "
        "again,",
        f"and every other session of the user ({_REVOKE_ALL}; each audited as "
        "`auth.session_revoked`",
        "the confirmation issues 10 new recovery codes and invalidates what is left of the old set",
        "For a user with `mfa_required` false the call fails closed: no session is minted and "
        "nothing is consumed",
        "`Idempotency-Key` is ignored, as on `POST /auth/mfa/verify`",
    ],
)
def test_recovery_description_states_the_rule(spec: dict[str, Any], rule: str) -> None:
    assert rule in _described(spec, "post", "/auth/mfa/recovery")


def test_enroll_needs_no_permission_and_never_returns_recovery_codes(spec: dict[str, Any]) -> None:
    op = _op(spec, "post", "/auth/mfa/enroll")
    assert op["x-rbac"] == _SELF_SERVICE  # every role enrols its own method
    assert op["x-idempotency"] == "ignored"  # the 201 holds the TOTP seed: never kept for a replay
    assert op["responses"]["409"] == {"$ref": "#/components/responses/Conflict"}
    assert op["responses"]["422"] == {"$ref": "#/components/responses/UnprocessableEntity"}
    assert "recovery_codes" not in spec["components"]["schemas"]["MfaEnrollResponse"]["properties"]
    for example in op["responses"]["201"]["content"]["application/json"]["examples"].values():
        assert "recovery_codes" not in example["value"]


@pytest.mark.parametrize(
    "rule",
    [
        "Each call supersedes the user's earlier pending methods: they are revoked, so at most one "
        "method is pending and only the latest can be confirmed.",
        "with `method: totp` only; any other method answers `422` and nothing changes",
        "`Idempotency-Key` is ignored: the response carries the TOTP provisioning secret, which is "
        "never stored for a replay.",
    ],
)
def test_enroll_description_states_the_rule(spec: dict[str, Any], rule: str) -> None:
    assert rule in _described(spec, "post", "/auth/mfa/enroll")


def test_confirm_returns_the_rotated_session_and_exactly_ten_codes(spec: dict[str, Any]) -> None:
    op = _op(spec, "post", "/auth/mfa/enroll/confirm")
    assert op["x-rbac"] == _SELF_SERVICE
    assert op["x-idempotency"] == "ignored"  # tokens and codes are never stored for a replay
    assert op["responses"]["409"] == {"$ref": "#/components/responses/Conflict"}
    assert op["responses"]["422"] == {"$ref": "#/components/responses/UnprocessableEntity"}
    ok = _ok(spec, "/auth/mfa/enroll/confirm")
    cookies = _flat(ok["headers"]["Set-Cookie"]["description"])
    for name in ("`cv_refresh`", "`__Host-cv_csrf`", "bound to the new session (SR-041)"):
        assert name in cookies
    schema = ok["content"]["application/json"]["schema"]
    assert schema == {"$ref": "#/components/schemas/MfaEnrollConfirmResponse"}
    first, extra = spec["components"]["schemas"]["MfaEnrollConfirmResponse"]["allOf"]
    assert first == {"$ref": "#/components/schemas/AuthenticatedResponse"}
    assert set(extra["required"]) == {"mfa_method", "recovery_codes"}
    codes = extra["properties"]["recovery_codes"]
    assert (codes["minItems"], codes["maxItems"]) == (10, 10)


def test_confirm_example_conforms_and_a_short_code_set_does_not(spec: dict[str, Any]) -> None:
    pointer = "/components/schemas/MfaEnrollConfirmResponse"
    body = _confirm_example(spec)
    _conforms(spec, body, pointer)
    assert body["user"]["mfa_enabled"] is True
    with pytest.raises(ValidationError):
        _conforms(spec, {**body, "recovery_codes": body["recovery_codes"][:9]}, pointer)
    with pytest.raises(ValidationError, match="'tokens' is a required property"):
        _conforms(spec, {k: v for k, v in body.items() if k != "tokens"}, pointer)


@pytest.mark.parametrize(
    "rule",
    [
        "Only the user's pending method can be confirmed: the one their latest "
        "`POST /auth/mfa/enroll` created, never confirmed and not revoked.",
        "Any other `method_id`, such as a method that a recovery sign-in or an owner reset "
        "revoked, answers `422` and nothing changes.",
        "revokes every other TOTP method of the user",
        "replaces the user's recovery codes with 10 new ones",
        "the old method and the old codes stop working at the instant the new ones start",
        f"It also revokes every other session of the user ({_REVOKE_ALL}), so no session minted "
        "on the password alone becomes a full one",
        "It then rotates the session (SR-013)",
        "its access and refresh tokens stop working at once",
        "The `200` sets the rotated `cv_refresh` and `__Host-cv_csrf` cookies, bound to the new "
        "session (SR-041)",
        "the 10 recovery codes, which are shown exactly once",
        "one `auth.session_revoked` per revoked session",
    ],
)
def test_confirm_description_states_the_rotation_rule(spec: dict[str, Any], rule: str) -> None:
    assert rule in _described(spec, "post", "/auth/mfa/enroll/confirm")


@pytest.mark.parametrize(
    "action",
    [
        "auth.mfa_enrolled",
        "auth.recovery_codes_regenerated",
        "auth.session_revoked",
        "auth.session_created",
    ],
)
def test_confirm_audit_actions_are_registered(spec: dict[str, Any], action: str) -> None:
    assert f"`{action}`" in _op(spec, "post", "/auth/mfa/enroll/confirm")["description"]
    assert action in AUDIT_ACTIONS


def test_csrf_section_lists_confirm_as_a_token_issue_point(spec: dict[str, Any]) -> None:
    info = _flat(spec["info"]["description"])
    start = info.index("**Issue, rotate and re-issue.**")
    bullet = info[start : info.index("**Multi-tab.**", start)]
    assert "`POST /auth/mfa/enroll/confirm` (which rotates the session)" in bullet


def test_owner_reset_sets_mfa_required(spec: dict[str, Any]) -> None:
    description = _described(spec, "post", "/users/{userId}/mfa/reset")
    assert "sets the target's `mfa_required`" in description


def test_user_flags_define_the_enrolment_only_state(spec: dict[str, Any]) -> None:
    user = spec["components"]["schemas"]["User"]["properties"]
    assert "confirmed, unrevoked MFA method" in user["mfa_enabled"]["description"]
    required = _flat(user["mfa_required"]["description"])
    assert "enrolment-only" in required
    assert "`mfa_required === true && mfa_enabled === false`" in required
    for flag in ("mfa_enabled", "mfa_required"):
        assert "Always present in `AuthenticatedResponse` and `SessionInfo`." in _flat(
            user[flag]["description"]
        )


def test_every_session_response_example_carries_both_mfa_flags(spec: dict[str, Any]) -> None:
    users = dict(_session_example_users(spec))
    assert len(users) >= 3  # login enrolmentOnly, confirm rotated, session manager
    for where, user in users.items():
        assert {"mfa_required", "mfa_enabled"} <= set(user), where


def test_session_info_of_an_enrolment_only_session_grants_nothing(spec: dict[str, Any]) -> None:
    ok = _op(spec, "get", "/auth/session")["responses"]["200"]
    assert (
        'For an enrolment-only session (see "Enrolment-only session") `permissions`, '
        "`account_scope` and `allowed_environments` are empty and `kill_switch` is omitted"
    ) in _flat(ok["description"])
    assert "kill_switch" not in spec["components"]["schemas"]["SessionInfo"]["required"]
    for field in ("permissions", "account_scope", "allowed_environments"):
        _conforms(spec, [], f"/components/schemas/SessionInfo/properties/{field}")


def test_refresh_never_extends_an_enrolment_only_session(spec: dict[str, Any]) -> None:
    lifetime = spec["components"]["schemas"]["TokenBundle"]["properties"]["refresh_expires_in"]
    assert (
        "For an enrolment-only session it counts down to that session's absolute expiry, at "
        "most 900"
    ) in _flat(lifetime["description"])
    assert (
        "An enrolment-only session's successor keeps the session's absolute expiry, so refresh "
        "never extends it"
    ) in _flat(_ok(spec, "/auth/refresh")["description"])


def test_ws_protocol_refuses_an_enrolment_only_session_at_auth() -> None:
    doc = (_PLAN / "23-ws-protocol.md").read_text(encoding="utf-8")
    auth = _between(doc, "### 4.3 `auth` → `auth_ok`", "### 4.4 Close codes")
    assert f"`bye` with reason `{_CODE}`, close `4403`" in auth
    assert "It does not count as a failed `auth`." in auth
    bundle = json.loads((_PLAN / "ws-schema.json").read_text(encoding="utf-8"))
    bye = bundle["schemas"]["cv://ws/v1/bye.schema.json"]["properties"]
    assert 4403 in bye["code"]["enum"]
    assert len(_CODE) <= bye["reason"]["maxLength"]


def test_ws_close_codes_and_catalogue_explain_the_enrolment_refusal() -> None:
    doc = (_PLAN / "23-ws-protocol.md").read_text(encoding="utf-8")
    close = _between(doc, "### 4.4 Close codes", "## 5. Subscribe / unsubscribe")
    row = next(line for line in close.splitlines() if line.startswith("| `4403`"))
    assert "Return to login (see below); do not retry." in row
    assert (
        "An `auth` or re-`auth` refused because the session is enrolment-only (§4.3) also closes "
        f"with `4403`, reason `{_CODE}`. The client does not return to login: it finishes TOTP "
        "enrolment over REST, then connects with the full session's token, and never "
        "auto-retries."
    ) in close
    catalogue = _between(doc, "### 10.2 Catalogue", "### 10.3")
    assert f"`{_CODE}` is deliberately absent from this table" in catalogue


def test_capability_matrix_names_no_permission_for_self_enrolment(spec: dict[str, Any]) -> None:
    doc = (_PLAN / "04-security-program.md").read_text(encoding="utf-8")
    matrix = _between(doc, "#### 7.2.2 Capability matrix", "### 7.3")
    row = next(line for line in matrix.splitlines() if line.startswith("| 2 "))
    cell = row.split("|")[3].strip()
    assert cell == "— · `authChangePassword`, `authMfaEnroll`, `authMfaEnrollConfirm`"
    operations = {
        op["operationId"]: op
        for item in spec["paths"].values()
        for op in item.values()
        if isinstance(op, dict) and "operationId" in op
    }
    for operation_id in re.findall(r"`(\w+)`", cell):
        assert operations[operation_id]["x-rbac"]["permissions"] == []


def test_security_program_records_the_enrolment_window_with_owner_and_review_date() -> None:
    doc = (_PLAN / "04-security-program.md").read_text(encoding="utf-8")
    area = _between(doc, "### 5.6 Area 6", "### 5.7 Area 7")
    threat = next(line for line in area.splitlines() if line.startswith("| U34 "))
    assert "enrolment window" in threat
    assert "RR-15" in threat
    summary = _between(doc, "### 5.11 Risk summary", "## 6. Security requirements")
    assert "U34" in summary
    register = _between(doc, "### 16.1 Accepted residual risks", "### 16.1a")
    accepted = next(line for line in register.splitlines() if line.startswith("| RR-15 "))
    assert "Owner: @basiltt" in accepted  # C-12.1: an owner and a review date
    assert re.search(r"review-by \d{4}-\d{2}-\d{2}", accepted)
    assert "queued on #2701" in accepted  # the open owner queue, as RR-08..RR-14 say
    assert "#1778" not in accepted  # that decision queue is closed
