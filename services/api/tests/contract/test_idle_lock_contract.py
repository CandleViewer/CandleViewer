"""Idle-lock HTTP contract (#2300; E09-D06 ruling on PR #2290), slice 1/2: contract only (C-6.1).

Pins `POST /auth/unlock`, `POST /auth/session/extend`, the three new 401 codes and the
`SessionInfo.session` deadlines that SCR-005 and CMP-098 build on; routes ship in slice 2/2.
Also pins the rules from the PR #2389 reviews: only extend and unlock record activity (refresh
carries `last_seen_at` over), unlock checks a password only while the session is locked, a
locked session's logout ends only that session, the operations allowed while locked also accept
`cv_refresh`, and step-up elevation never survives the lock (#2290 ruling, rule 4d).
`POST /auth/lock` (#4743, E09-S03-F1, CMP-098 "Lock now") is pinned at the end, contract first.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.audit.actions import AUDIT_ACTIONS
from candleviewer.auth.session_service import MAX_IDLE_TIMEOUT_S, MIN_IDLE_TIMEOUT_S
from candleviewer.statechart.registry import default_registry
from tests.contract._admin_support import ROOT

_BASE = "urn:cv:openapi"
_SESSION_FIELDS = {"id", "issued_at", "expires_at", "idle_deadline", "idle_timeout_s", "locked"}
_METHODS = {"get", "put", "post", "patch", "delete", "head", "options", "trace"}
#: The operations an idle-locked session may call (#2290 ruling, rule 3a; `POST /auth/lock`, #4743).
_LOCKED_OK = (
    ("post", "/auth/unlock"),
    ("post", "/auth/logout"),
    ("post", "/auth/lock"),
    ("get", "/auth/session"),
)
_BEARER_OR_COOKIE: list[dict[str, list[str]]] = [{"bearerAuth": []}, {"refreshCookie": []}]


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
    for action in ("auth.session_unlocked", "auth.unlock_failed", "auth.account_locked"):
        assert f"`{action}`" in description
        assert action in AUDIT_ACTIONS
    # SR-016: the wrong password that locks the account is recorded as on any other path.
    assert "the wrong password that locks the account (SR-016)" in _flat(description)


def test_unlock_contract_records_unlock_ok_on_b16_never_request(spec: dict[str, Any]) -> None:
    # Catalogue B16.7: the route records `UNLOCK_OK` / `UNLOCK_FAILED`, never `REQUEST`;
    # extend is the only `REQUEST` (#2389 review record, aligned once #2390 merged).
    unlock = _flat(_op(spec, "post", "/auth/unlock")["description"])
    assert "`last_seen_at` is re-stamped (`UNLOCK_OK` on B16)" in unlock
    assert "`REQUEST`" not in unlock
    section = _idle_lock_section(spec)
    assert "unlock's re-stamp is recorded as `UNLOCK_OK` on B16 (extend sends B16 nothing)" in (
        section
    )


def test_extend_re_stamps_the_row_and_sends_b16_nothing(spec: dict[str, Any]) -> None:
    # #2300 slice 2f-B (#4052 follow-up): the route never sent `REQUEST`; the chart reads the
    # deadline from the row on access (INV-B16-e) and no gate reads chart state (C-2.21).
    extend = _flat(_op(spec, "post", "/auth/session/extend")["description"])
    assert "It re-stamps `last_seen_at` on the session row (it sends B16 nothing)" in extend
    assert "`REQUEST`" not in extend


def test_a_read_only_downgrade_never_refuses_extend(spec: dict[str, Any]) -> None:
    # #2300 slice 2f-B, D1 (#4052 follow-up): once activity is explicit, a downgraded session
    # must still be able to extend, or a 5 min idle timeout locks it inside the penalty.
    extend = _flat(_op(spec, "post", "/auth/session/extend")["description"])
    assert "A read-only downgrade does not refuse it: extend acts on no data" in extend
    assert "A read-only downgrade (`POST /auth/step-up`) does not refuse extend" in (
        _idle_lock_section(spec)
    )
    step_up = _flat(_op(spec, "post", "/auth/step-up")["description"])
    assert (
        "(`403 session_read_only` on every write except `POST /auth/logout`, "
        "`POST /auth/session/extend`, `POST /auth/lock` and `DELETE /auth/session/view-as`; "
        "`POST /auth/step-up` answers it itself)"
    ) in step_up


def test_a_rotated_away_cookie_is_audited_outside_refresh(spec: dict[str, Any]) -> None:
    # The uniform 401 changes no session, but probing a stolen refresh token is not silent.
    section = _idle_lock_section(spec)
    assert "`401 unauthenticated` and changes no session" in section
    assert "(`auth.refresh_reuse_detected` with outcome `denied` for a rotated-away cookie" in (
        section
    )
    assert {"auth.refresh_reuse_detected", "auth.session_fixation_attempt"} <= AUDIT_ACTIONS


def test_unlock_contract_checks_the_audit_sink_before_the_password(spec: dict[str, Any]) -> None:
    # Review round 3 (C-2.9): no unaudited password check; a failure counts even if unaudited.
    op = _op(spec, "post", "/auth/unlock")
    assert "503" in op["responses"]
    description = _flat(op["description"])
    assert "If the audit sink is down the answer is `503` and no password is checked." in (
        description
    )
    assert "A failure counts even if its audit record cannot be written." in description


def test_extend_contract_is_audited_write_ahead(spec: dict[str, Any]) -> None:
    # Review round 3 (C-2.9): extend is not a token rotation, so not `auth.session_refreshed`.
    op = _op(spec, "post", "/auth/session/extend")
    assert op["responses"]["503"] == {"$ref": "#/components/responses/ServiceUnavailable"}
    assert "`auth.session_extended`" in op["description"]
    assert "auth.session_extended" in AUDIT_ACTIONS


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


def test_refresh_contract_keeps_the_step_up_penalty(spec: dict[str, Any]) -> None:
    # #2914 (comment 6325457810): since #4060 (#4051, SR-025) a refresh carries the step-up
    # penalty to the rotated session and never a grant; pinned in SessionService.mint().
    refresh = _flat(_op(spec, "post", "/auth/refresh")["description"])
    assert "The rotated session also inherits the step-up penalty" in refresh
    assert "`step_up_failures` and `readonly_until` (SR-025)" in refresh
    assert "never lifts a read-only downgrade or forgets a strike" in refresh
    assert "it never carries a step-up grant or a pending step-up challenge" in refresh


def test_refresh_refused_while_locked_writes_no_refreshed_record(spec: dict[str, Any]) -> None:
    # Review round 3 (gap G): the route answers the lock before its write-ahead record (#3331);
    # the behaviour is pinned in `tests/unit/api/idle_lock/test_refresh.py`.
    refresh = _flat(_op(spec, "post", "/auth/refresh")["description"])
    assert "no `auth.session_refreshed` record is written" in refresh


def test_logout_from_a_locked_session_ends_only_the_calling_session(spec: dict[str, Any]) -> None:
    # PR #2389 review round 2: logout is allowed while locked only as SCR-005 "Sign out
    # instead". Revoke-all is a write (#2290 ruling, rule 3b): with a bearer copied from a
    # locked tab, whoever is at the desk could sign the owner out of every other machine.
    allowed = (
        "Only `POST /auth/unlock`, `POST /auth/logout`, `POST /auth/lock` and `GET /auth/session`"
        " are allowed while locked, and logout ends only the calling session"
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


@pytest.mark.parametrize(("method", "path"), _LOCKED_OK)
def test_operations_allowed_while_locked_accept_the_refresh_cookie(
    spec: dict[str, Any], method: str, path: str
) -> None:
    # Review round 3: the bearer lives in memory for 12 min and refresh is refused while locked,
    # so bearer-only, a long lock or a reload would leave no way to unlock or sign out.
    assert _op(spec, method, path)["security"] == _BEARER_OR_COOKIE


def test_only_refresh_and_the_locked_session_operations_accept_the_refresh_cookie(
    spec: dict[str, Any],
) -> None:
    accepting = {
        (method, path)
        for path, item in spec["paths"].items()
        for method, op in item.items()
        if method in _METHODS
        and any("refreshCookie" in r for r in op.get("security", spec["security"]))
    }
    assert accepting == {("post", "/auth/refresh"), *_LOCKED_OK}
    scheme = _flat(spec["components"]["securitySchemes"]["refreshCookie"]["description"])
    assert all(f"`{method.upper()} {path}`" in scheme for method, path in _LOCKED_OK)
    no_expired = "No other operation accepts the cookie, and none, unlock included, accepts an"
    assert f"{no_expired} expired access token." in _idle_lock_section(spec)


def test_cookie_identified_writes_are_csrf_bound_to_the_cookie_session(
    spec: dict[str, Any],
) -> None:
    for path in ("/auth/unlock", "/auth/logout", "/auth/lock"):  # SR-041 / SR-042, as on refresh
        op = _op(spec, "post", path)
        assert {"$ref": "#/components/parameters/CsrfToken"} in op["parameters"]
        assert op["responses"]["403"] == {"$ref": "#/components/responses/CsrfTokenInvalid"}
    text = spec["info"]["description"]
    bound = (
        "for a `POST /auth/logout`, `POST /auth/unlock` or `POST /auth/lock` identified by the"
        " `cv_refresh` cookie"
    )
    assert bound in _flat(text[text.index("### CSRF") : text.index("### Idle lock")])


def test_unlock_never_accepts_an_expired_access_token(spec: dict[str, Any]) -> None:
    # Review round 3 withdraws decision 1: the cookie identifies a locked session instead.
    op = _op(spec, "post", "/auth/unlock")
    description = _flat(op["description"])
    assert "An expired access token is never accepted" in description
    assert "accepts the token after its 12-minute lifetime" not in description
    # Rotated-away or unknown credentials get the uniform 401, never `session_revoked`.
    assert "unauthenticated" in {e["code"] for e in _examples(op["responses"]["401"]).values()}


def test_a_locked_session_can_always_be_signed_out(spec: dict[str, Any]) -> None:
    op = _op(spec, "post", "/auth/logout")
    assert op["security"] == _BEARER_OR_COOKIE
    # Ending the calling session only reduces privilege; ending every session needs a bearer.
    cookie_only = "With only the cookie, `all_sessions: true` is refused and revokes nothing"
    assert cookie_only in _flat(op["description"])


def test_unlock_restores_no_step_up_elevation(spec: dict[str, Any]) -> None:
    # Review round 3 (High; #2290 ruling, rule 4d): a one-factor unlock must never inherit a
    # two-factor grant, or a password alone could release the kill switch after a lock.
    op = _op(spec, "post", "/auth/unlock")
    unlocked = _examples(op["responses"]["200"]).values()
    assert unlocked
    for example in unlocked:
        _conforms(spec, example, "/components/schemas/SessionInfo")
        assert example["session"]["locked"] is False and example["step_up_expires_at"] is None
    assert "`403 step_up_required`" in _flat(op["description"])
    section = _idle_lock_section(spec)
    assert "Step-up elevation never survives the lock (#2290 ruling, rule 4d" in section
    # The ruling's "lock clears elevation": grants are void from the lock itself, so no
    # password-only unlock can carry one, whenever the row is physically cleaned.
    assert "Step-up grants are cleared at lock:" in section
    assert "A password-only `POST /auth/unlock` therefore never carries elevation" in section
    # Enforced on the session row by synchronous code, not only by B16 (C-2.21).
    assert "The synchronous step-up check enforces this from the session row" in section
    row = "deletes the grants from the row no later than the write that lifts the lock"
    assert row in section and "C-2.21" in section


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
    by_lock = {example["session"]["locked"]: example for example in examples.values()}
    assert set(by_lock) == {False, True}
    # The lock voids elevation at once, so the lock screen never shows a pre-lock grace.
    assert by_lock[True]["step_up_expires_at"] is None


def test_unauthorized_response_documents_session_idle_locked(spec: dict[str, Any]) -> None:
    examples = _examples(spec["components"]["responses"]["Unauthorized"])
    locked = [e for e in examples.values() if e["code"] == "session_idle_locked"]
    assert len(locked) == 1 and "idle_locked_at" in locked[0]
    _conforms(spec, locked[0], "/components/schemas/Problem")


# -- `POST /auth/lock` (#4743, E09-S03-F1): CMP-098 "Lock now", contract first (C-6.1) ----------
# The orchestrator's rulings of 2026-10-29 09:00Z (BQ-1 to BQ-5) each have a test below.

_LOCK = "/auth/lock"


def test_lock_contract_is_a_self_write_with_no_body(spec: dict[str, Any]) -> None:
    op = _op(spec, "post", _LOCK)
    assert op["x-rbac"] == {"permissions": [], "scope": "self"}
    assert op["x-idempotency"] == "ignored"  # idempotent by state: a locked session answers 200
    assert op["parameters"] == [{"$ref": "#/components/parameters/CsrfToken"}]
    assert "requestBody" not in op
    assert set(op["responses"]) == {"200", "401", "403", "422", "503"}
    assert "any query parameter is refused with `422` (SR-026)" in _flat(op["description"])


def test_lock_contract_locks_as_if_the_idle_deadline_fell_due(spec: dict[str, Any]) -> None:
    # L2 (c), 13:40Z: B16 gets nothing at lock time and records the lock on its next read of the
    # row (INV-B16-e), through its existing transition.
    description = _flat(_op(spec, "post", _LOCK)["description"])
    assert "exactly as if its idle deadline fell due now" in description
    assert "nothing is sent to B16 at lock time, as for extend (28 B16.7)" in description
    assert "B16 records the lock on its next read of the row, as if the idle" in description
    auth = default_registry().get("session")["states"]["auth"]["states"]
    assert auth["active"]["on"]["IDLE_DEADLINE"] == {"target": "#session.auth.idle_locked"}
    assert "audit_idle_locked" in auth["idle_locked"]["entry"]
    section = _idle_lock_section(spec)
    assert '`POST /auth/lock` (CMP-098 "Lock now", #4743) locks it at once' in section


def test_lock_contract_never_moves_the_idle_deadline(spec: dict[str, Any]) -> None:
    # BQ-5: `last_seen_at` never moves (SCR-112 would show a false time), so the deadline and a
    # later `idle_locked_at` keep `last_seen_at + idle_timeout_s`; the audit row has the moment.
    description = _flat(_op(spec, "post", _LOCK)["description"])
    assert "The deadline itself does not move" in description
    assert "still give `last_seen_at + idle_timeout_s`" in description
    moment = "the lock moment is the `auth.session_locked` audit row's time"
    assert "The lock moment is the `auth.session_locked` audit row's time." in description
    section = _idle_lock_section(spec)
    assert f"without moving it: {moment}" in section
    # Activity stays the two operations alone: the lock moves no deadline at all.
    assert "so only they move `session.idle_deadline`. No other operation moves it" in section
    state = _schema(spec, "SessionState")["properties"]
    deadline = _flat(state["idle_deadline"]["description"])
    assert "unless `POST /auth/lock` locked the session first: lock never moves it" in deadline
    assert "may be later than `server_time`: read `session.locked`, never this time" in deadline
    assert "lock and unlock never move it." in state["expires_at"]["description"]
    assert "or `POST /auth/lock` locked the session" in _flat(state["locked"]["description"])
    problem = _schema(spec, "Problem")["properties"]["idle_locked_at"]["description"]
    assert "unless `POST /auth/lock` locked it first" in _flat(problem)
    assert "later than `server_time`. Read the problem code or `session.locked`" in _flat(problem)


def test_lock_answers_session_info_locked_without_elevation(spec: dict[str, Any]) -> None:
    ok = _op(spec, "post", _LOCK)["responses"]["200"]
    schema = ok["content"]["application/json"]["schema"]
    assert schema == {"$ref": "#/components/schemas/SessionInfo"}
    locked = _examples(ok).values()
    assert locked
    for example in locked:
        _conforms(spec, example, "/components/schemas/SessionInfo")
        assert example["session"]["locked"] is True and example["step_up_expires_at"] is None
        # Locked before its idle deadline, which the lock does not move.
        deadline = datetime.fromisoformat(example["session"]["idle_deadline"])
        assert datetime.fromisoformat(example["server_time"]) < deadline


def test_lock_contract_writes_one_record_per_lock(spec: dict[str, Any]) -> None:
    # BQ-2: an already-locked call is a 200 that changed nothing, so it writes no second row.
    description = _flat(_op(spec, "post", _LOCK)["description"])
    assert "already idle-locked answers `200` with its `SessionInfo` and changes" in description
    assert "nothing. It writes no second `auth.session_locked`: one record per lock" in description


def test_lock_answers_session_revoked_when_revoked_or_expired(spec: dict[str, Any]) -> None:
    refusals = _examples(_op(spec, "post", _LOCK)["responses"]["401"])
    for example in refusals.values():
        _conforms(spec, example, "/components/schemas/Problem")
    revoked = {e["revoked_reason"] for e in refusals.values() if e["code"] == "session_revoked"}
    assert revoked == {"revoked", "expired"}
    # A rotated-away or never-issued credential keeps the uniform 401, never `session_revoked`.
    assert "unauthenticated" in {e["code"] for e in refusals.values()}
    only = "`session_revoked` is answered only by `POST /auth/unlock` and `POST /auth/lock`"
    assert only in _idle_lock_section(spec)


def test_lock_is_recorded_ahead_and_by_b16_at_its_next_read(spec: dict[str, Any]) -> None:
    # BQ-1, L2 (c): `auth.session_locked` is the lock's record (C-2.9); B16's later
    # `auth.idle_locked` carries the lock moment. 24 is pinned by the test after this one.
    op = _op(spec, "post", _LOCK)
    assert op["responses"]["503"] == {"$ref": "#/components/responses/ServiceUnavailable"}
    description = _flat(op["description"])
    assert "The lock's record is `auth.session_locked`, written ahead (C-2.9)" in description
    assert "carries the lock moment, not the time of that read." in description
    assert "the answer is `503` and the session is not locked." in description


def test_24_lists_the_lock_record_until_the_implementation_registers_it() -> None:
    """24 section 15.5 and its change-log entry; registering the action flips both marker halves."""
    internal = (ROOT / "docs/plan/24-internal-schemas.md").read_text(encoding="utf-8")
    vocabulary = _flat(internal.split("### 15.5 ", 1)[1].split("### 15.6 ", 1)[0])
    assert "`auth.session_locked` (not registered yet, E09-S03-F1)" in vocabulary
    assert "auth.session_locked" not in AUDIT_ACTIONS
    assert "There is one record per lock" in vocabulary
    assert "nothing is sent to B16 at lock time" in vocabulary
    title = r"^### 19\.\d+ .* the `auth\.session_locked` action \(E09-S03-F1, #4743\)$"
    found = re.search(title, internal, re.MULTILINE)
    assert found is not None
    entry = _flat(internal[found.end() :].split("\n### ", 1)[0])
    assert "this contract adds no column; how the lock is stored is the implementation's" in entry


def test_lock_is_one_of_the_viewers_own_operations(spec: dict[str, Any]) -> None:
    # BQ-3: lock acts on the viewer's own session, as the viewer, so view-as never refuses it.
    description = _flat(_op(spec, "post", _LOCK)["description"])
    assert "it is one of the viewer's own operations" in description
    text = spec["info"]["description"]
    own = text.split("**The viewer's own operations.**", 1)[1].split("None of the rules", 1)[0]
    assert "`POST /auth/lock`" in own


def test_a_read_only_downgrade_never_refuses_lock(spec: dict[str, Any]) -> None:
    # BQ-4: lock acts on no data and only reduces risk, as extend acts on none.
    description = _flat(_op(spec, "post", _LOCK)["description"])
    assert "neither a read-only downgrade nor a view-as context refuses it" in description
    read_only = "Nor does it refuse lock, which acts on no data either and only reduces risk."
    assert read_only in _idle_lock_section(spec)
    step_up = _flat(_op(spec, "post", "/auth/step-up")["description"])
    assert "`POST /auth/session/extend`, `POST /auth/lock` and" in step_up
