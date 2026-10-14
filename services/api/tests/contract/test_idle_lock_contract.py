"""Idle-lock HTTP contract (#2300; E09-D06 ruling on PR #2290), slice 1/2: contract only (C-6.1).

Pins `POST /auth/unlock`, `POST /auth/session/extend`, the three new 401 codes and the
`SessionInfo.session` deadlines that SCR-005 and CMP-098 build on; routes ship in slice 2/2.
Also pins three rules from the PR #2389 reviews: only extend and unlock record activity (refresh
carries `last_seen_at` over), unlock checks a password only while the session is locked, and a
locked session's logout ends only that session (`all_sessions: true` is refused).
"""

from __future__ import annotations

from typing import Any

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.audit.actions import AUDIT_ACTIONS
from candleviewer.auth.session_service import MAX_IDLE_TIMEOUT_S, MIN_IDLE_TIMEOUT_S

_BASE = "urn:cv:openapi"
_SESSION_FIELDS = {"id", "issued_at", "expires_at", "idle_deadline", "idle_timeout_s", "locked"}


@pytest.fixture(scope="module")
def spec() -> dict[str, Any]:
    return load_openapi_spec()


def _op(spec: dict[str, Any], method: str, path: str) -> dict[str, Any]:
    op: dict[str, Any] = spec["paths"][path][method]
    return op


def _schema(spec: dict[str, Any], name: str) -> dict[str, Any]:
    schema: dict[str, Any] = spec["components"]["schemas"][name]
    return schema


def _examples(response: dict[str, Any]) -> dict[str, Any]:
    content = response["content"]
    media = content.get("application/json") or content["application/problem+json"]
    return {name: example["value"] for name, example in media["examples"].items()}


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


def _idle_lock_section(spec: dict[str, Any]) -> str:
    text: str = spec["info"]["description"]
    start = text.index("### Idle lock")
    return _flat(text[start : text.index("\n### ", start)])


@pytest.mark.parametrize("code", ["session_idle_locked", "unlock_invalid", "session_revoked"])
def test_error_registry_idle_lock_code_is_rest_only_401_not_retryable(
    spec: dict[str, Any], code: str
) -> None:
    entry = {e["code"]: e for e in spec["x-error-codes"]}[code]
    assert (entry["status"], entry["retryable"]) == (401, False)
    # REST only: no WS change, frames keep flowing while locked (ADR-0020 section 4).
    assert entry.get("surface", ["rest"]) == ["rest"]


def test_unlock_contract_takes_the_password_only(spec: dict[str, Any]) -> None:
    op = _op(spec, "post", "/auth/unlock")
    assert op["x-rbac"] == {"permissions": [], "scope": "self"}
    assert {"$ref": "#/components/parameters/CsrfToken"} in op["parameters"]
    body = op["requestBody"]["content"]["application/json"]["schema"]
    assert body == {"$ref": "#/components/schemas/UnlockRequest"}
    request = _schema(spec, "UnlockRequest")
    # No TOTP field: unlock requires the password only (US-ONB-004, E09-S03).
    assert set(request["properties"]) == {"password"} and request["required"] == ["password"]
    assert request["additionalProperties"] is False
    assert request["properties"]["password"]["writeOnly"] is True


def test_unlock_contract_answers_session_info_or_a_named_refusal(spec: dict[str, Any]) -> None:
    op = _op(spec, "post", "/auth/unlock")
    ok = op["responses"]["200"]["content"]["application/json"]["schema"]
    assert ok == {"$ref": "#/components/schemas/SessionInfo"}
    assert {"401", "403", "409", "422", "429", "503"} <= set(op["responses"])
    assert "x-rate-limit" in op  # throttled like login
    refusals = _examples(op["responses"]["401"])
    assert {e["code"] for e in refusals.values()} >= {"unlock_invalid", "session_revoked"}
    for example in refusals.values():
        _conforms(spec, example, "/components/schemas/Problem")


def test_unlock_contract_checks_the_password_only_while_locked(spec: dict[str, Any]) -> None:
    # PR #2389 review: a password check on a live, unlocked session is an oracle whose
    # per-session failure count a refresh resets (it mints a new session id). Only a locked
    # session, which cannot refresh, gets a password check; any other live session is a 409.
    op = _op(spec, "post", "/auth/unlock")
    not_locked = _examples(op["responses"]["409"])
    assert [e["code"] for e in not_locked.values()] == ["conflict"]
    for example in not_locked.values():
        _conforms(spec, example, "/components/schemas/Problem")
    assert {e["code"]: e["status"] for e in spec["x-error-codes"]}["conflict"] == 409
    description = _flat(op["description"])
    assert "The password is checked only while the session is idle-locked." in description
    assert "not locked gets `409 conflict`: no password is checked, no failure is counted" in (
        description
    )
    assert "a locked session cannot rotate, so refreshing cannot reset the count" in description


def test_unlock_contract_session_revoked_carries_the_reason(spec: dict[str, Any]) -> None:
    refusals = _examples(_op(spec, "post", "/auth/unlock")["responses"]["401"])
    reasons = {e["revoked_reason"] for e in refusals.values() if e["code"] == "session_revoked"}
    assert "expired" in reasons  # absolute lifetime elapsed while locked: full sign-in
    enum = set(_schema(spec, "Problem")["properties"]["revoked_reason"]["enum"])
    assert {"expired", "unlock_attempts_exceeded"} <= enum


def test_unlock_contract_audit_actions_are_registered(spec: dict[str, Any]) -> None:
    description = _op(spec, "post", "/auth/unlock")["description"]
    for action in ("auth.session_unlocked", "auth.unlock_failed"):
        assert f"`{action}`" in description
        assert action in AUDIT_ACTIONS


def test_extend_contract_returns_the_server_truth_deadline(spec: dict[str, Any]) -> None:
    op = _op(spec, "post", "/auth/session/extend")
    assert op["x-rbac"] == {"permissions": [], "scope": "self"}
    assert {"$ref": "#/components/parameters/CsrfToken"} in op["parameters"]
    assert "requestBody" not in op
    ok = op["responses"]["200"]["content"]["application/json"]["schema"]
    assert ok == {"$ref": "#/components/schemas/SessionExtendResponse"}
    response = _schema(spec, "SessionExtendResponse")
    assert set(response["required"]) == {"session", "server_time"}
    assert response["properties"]["session"] == {"$ref": "#/components/schemas/SessionState"}


def test_idle_lock_activity_is_recorded_only_by_extend_and_unlock(spec: dict[str, Any]) -> None:
    # PR #2389 review (ruling rule 5e): every implicit activity source is a background call
    # that can keep an unattended terminal unlocked, so the contract names exactly two.
    section = _idle_lock_section(spec)
    only = "Only `POST /auth/session/extend` and a successful `POST /auth/unlock` record activity"
    assert only in section
    assert "No other operation moves it, whatever it reads or writes" in section
    for method, path in (("post", "/auth/session/extend"), ("post", "/auth/unlock")):
        assert method in spec["paths"][path]
    extend = _flat(_op(spec, "post", "/auth/session/extend")["description"])
    assert "it is the only operation that records activity" in extend


def test_refresh_contract_carries_the_idle_deadline_over(spec: dict[str, Any]) -> None:
    # PR #2389 review: clients refresh about every 11 min (23-ws-protocol.md section 4.3), so a
    # refresh that re-stamped activity would stop the default 15 min lock from ever engaging.
    inherits = "the rotated session inherits `last_seen_at`"
    assert f"`POST /auth/refresh` is not activity: {inherits}" in _idle_lock_section(spec)
    refresh = _flat(_op(spec, "post", "/auth/refresh")["description"])
    assert f"Refresh is not activity: {inherits}" in refresh
    assert "`session.idle_deadline` is unchanged" in refresh
    deadline = _schema(spec, "SessionState")["properties"]["idle_deadline"]["description"]
    assert "`POST /auth/refresh` carries it over unchanged" in _flat(deadline)


def test_logout_from_a_locked_session_ends_only_the_calling_session(spec: dict[str, Any]) -> None:
    # PR #2389 review round 2: logout is allowed while locked only as SCR-005 "Sign out
    # instead". Revoke-all is a write (#2290 ruling, rule 3b): with a bearer copied from a
    # locked tab, whoever is at the desk could sign the owner out of every other machine.
    allowed = (
        "Only `POST /auth/unlock`, `POST /auth/logout` and `GET /auth/session` are allowed"
        " while locked, and logout ends only the calling session"
    )
    refused = "`all_sessions: true` from a locked session answers `401 session_idle_locked`"
    section = _idle_lock_section(spec)
    assert allowed in section
    assert f"{refused} and revokes nothing" in section
    op = _op(spec, "post", "/auth/logout")
    description = _flat(op["description"])
    assert "Allowed while the session is idle-locked, for the calling session only" in description
    assert "`all_sessions: true` answers `401 session_idle_locked` and revokes nothing" in (
        description
    )
    assert "no `auth.logout` or `auth.session_revoked` record is written" in description
    body = op["requestBody"]["content"]["application/json"]["schema"]
    flag = _flat(body["properties"]["all_sessions"]["description"])
    assert "Refused from an idle-locked session (`401 session_idle_locked`" in flag
    # The refusal is the documented idle-lock 401 (`Unauthorized` carries the example).
    assert op["responses"]["401"] == {"$ref": "#/components/responses/Unauthorized"}


def test_session_info_requires_the_session_state(spec: dict[str, Any]) -> None:
    info = _schema(spec, "SessionInfo")
    assert "session" in info["required"]
    assert info["properties"]["session"] == {"$ref": "#/components/schemas/SessionState"}
    state = _schema(spec, "SessionState")
    assert set(state["required"]) == _SESSION_FIELDS == set(state["properties"])
    assert state["properties"]["locked"]["type"] == "boolean"


def test_session_state_idle_timeout_bounds_match_the_service(spec: dict[str, Any]) -> None:
    timeout = _schema(spec, "SessionState")["properties"]["idle_timeout_s"]
    assert (timeout["minimum"], timeout["maximum"]) == (MIN_IDLE_TIMEOUT_S, MAX_IDLE_TIMEOUT_S)


def test_get_session_examples_conform_and_carry_the_lock_state(spec: dict[str, Any]) -> None:
    examples = _examples(_op(spec, "get", "/auth/session")["responses"]["200"])
    for example in examples.values():
        _conforms(spec, example, "/components/schemas/SessionInfo")
        assert example["session"]["locked"] is False


def test_unauthorized_response_documents_session_idle_locked(spec: dict[str, Any]) -> None:
    examples = _examples(spec["components"]["responses"]["Unauthorized"])
    locked = [e for e in examples.values() if e["code"] == "session_idle_locked"]
    assert len(locked) == 1 and "idle_locked_at" in locked[0]
    _conforms(spec, locked[0], "/components/schemas/Problem")
