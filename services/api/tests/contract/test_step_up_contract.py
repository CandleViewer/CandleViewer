"""Step-up session rotation contract (SR-013, #2101).

Pins the `POST /auth/step-up` `200`: the body carries `tokens`, the `TokenBundle` that
`POST /auth/mfa/verify` returns, and the response sets the rotated `cv_refresh` and
`__Host-cv_csrf` cookies and declares the desktop `X-CSRF-Token` header exactly as
`POST /auth/refresh` does (ADR-0038 F5). Also pins the rotation rules the
operation description states (the replacement keeps the absolute expiry and idle timeout, carries
the live grants over and drops the pending challenge; the old session is revoked as `rotated`
inside the session family; its sockets re-authenticate in place; the audit order and the `503` and
`401` refusals of #2101), step-up's place among the CSRF rotation points, its
`x-idempotency`, and the provider check that the router's `200` validates against the schema.
"""

from __future__ import annotations

from typing import Any

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from candleviewer.api.contract_conformance import load_openapi_spec
from tests.unit.api.test_step_up_router import _H, _PW, _build, _code

_BASE = "urn:cv:openapi"
_STEP_UP_OK = "/paths/~1auth~1step-up/post/responses/200/content/application~1json/schema"
_TOKEN_BUNDLE = {"$ref": "#/components/schemas/TokenBundle"}


@pytest.fixture(scope="module")
def spec() -> dict[str, Any]:
    return load_openapi_spec()


def _ok(spec: dict[str, Any], path: str) -> dict[str, Any]:
    response: dict[str, Any] = spec["paths"][path]["post"]["responses"]["200"]
    return response


def _body(spec: dict[str, Any], path: str) -> dict[str, Any]:
    schema: dict[str, Any] = _ok(spec, path)["content"]["application/json"]["schema"]
    return schema


def _validator(spec: dict[str, Any]) -> Draft202012Validator:
    resource = Resource.from_contents(spec, default_specification=DRAFT202012)
    return Draft202012Validator(
        {"$ref": f"{_BASE}#{_STEP_UP_OK}"},
        registry=Registry().with_resource(_BASE, resource),
        format_checker=Draft202012Validator.FORMAT_CHECKER,
    )


def _granted(spec: dict[str, Any]) -> dict[str, Any]:
    """A rotated step-up body; `tokens` reuses the `TokenBundle` of the login example that has one.

    Login no longer mints a full session, so `enrolmentOnly` is its only example with tokens;
    the bundle has the same shape for any session.
    """
    login = _ok(spec, "/auth/login")["content"]["application/json"]["examples"]
    return {
        "elevated_until": "2026-10-15T12:05:00Z",
        "action_class": "users",
        "single_use": False,
        "step_up_expires_at": "2026-10-15T12:05:00Z",
        "tokens": login["enrolmentOnly"]["value"]["tokens"],
    }


def _flat(text: str) -> str:
    """Collapse YAML line wrapping so prose pins survive a re-wrap."""
    return " ".join(text.split())


def test_step_up_ok_requires_the_token_bundle_that_mfa_verify_returns(
    spec: dict[str, Any],
) -> None:
    verify = _body(spec, "/auth/mfa/verify")
    assert verify == {"$ref": "#/components/schemas/AuthenticatedResponse"}
    authenticated = spec["components"]["schemas"]["AuthenticatedResponse"]
    assert authenticated["properties"]["tokens"] == _TOKEN_BUNDLE
    body = _body(spec, "/auth/step-up")
    assert body["properties"]["tokens"] == _TOKEN_BUNDLE
    assert set(body["required"]) == {"elevated_until", "action_class", "single_use", "tokens"}


def test_step_up_ok_sets_the_rotated_cookies_and_token_header_exactly_as_refresh(
    spec: dict[str, Any],
) -> None:
    """ADR-0038 F5 (#2101): step-up issues the CSRF token for the new session, so its `200`
    declares the desktop token header as refresh's does: the eighth issuing operation."""
    headers = _ok(spec, "/auth/step-up")["headers"]
    assert set(headers) == {"Set-Cookie", "X-CSRF-Token"}
    assert headers["X-CSRF-Token"] == {"$ref": "#/components/headers/CsrfTokenIssued"}
    assert headers == _ok(spec, "/auth/refresh")["headers"]


def test_step_up_ok_body_with_rotated_tokens_conforms(spec: dict[str, Any]) -> None:
    _validator(spec).validate(_granted(spec))


def test_step_up_ok_body_without_tokens_no_longer_conforms(spec: dict[str, Any]) -> None:
    pre_rotation = {k: v for k, v in _granted(spec).items() if k != "tokens"}
    with pytest.raises(ValidationError, match="'tokens' is a required property"):
        _validator(spec).validate(pre_rotation)


async def test_step_up_route_ok_body_validates_against_the_contract(spec: dict[str, Any]) -> None:
    """Provider side (C-6.2): the step-up router's `200`, with the rotated session's `tokens`
    (#2101), against the contract schema."""
    client, _emitter, seed, clock, _user = await _build()
    ok = client.post(
        "/auth/step-up",
        headers=_H,
        json={"code": _code(seed, clock), "password": _PW, "action_class": "users"},
    )
    assert ok.status_code == 200
    _validator(spec).validate(ok.json())
    assert ok.json()["tokens"]["refresh_token"] is None  # the refresh token is in the cookie


@pytest.mark.parametrize(
    "rule",
    [
        "A successful step-up also rotates the session",
        "keeps the old session's absolute expiry and idle timeout",
        "carries over the live step-up grants, including the one just granted",
        "drops the pending challenge",
        "revoked as `rotated` and linked into the session family",
        "its access and refresh tokens stop working at once for REST calls and for a new socket "
        "`auth` frame",
        "replaying that refresh token at `POST /auth/refresh` revokes the whole family",
        "the refresh token travels only in the cookie, so `refresh_token` is null",
        "A client that loses the `200` keeps only the old tokens: its next `POST /auth/refresh` "
        "trips reuse detection, so the user must sign in again",
        # C-5 (#2101): the carry list refresh's successor gets, on top of the grants.
        "it also keeps the old session's idle clock, lock, read-only downgrade and view-as context",
        # C-3 (#2101): the step-up's sockets re-authenticate in place, nothing is published.
        "A socket already authenticated on the old session stays open: the rotation is no "
        "revocation, so nothing is published, and the client re-`auth`s the socket in place "
        "with the new access token, as after a refresh (23-ws-protocol.md section 4.1)",
        # C-4 (#2101): the new session's CSRF token, under the desktop flag, never cached.
        "with the new token in the `X-CSRF-Token` response header for a listed `Origin` while "
        "the `desktop.backend_connection` flag is on",
        "it is `Cache-Control: no-store`",
    ],
)
def test_step_up_description_states_the_approved_rotation_rule(
    spec: dict[str, Any], rule: str
) -> None:
    assert rule in _flat(spec["paths"]["/auth/step-up"]["post"]["description"])


@pytest.mark.parametrize(
    "rule",
    [
        # C-7 (#2101): the readiness check comes before any factor.
        "The audit writer's readiness is checked before any factor is verified: a writer that is "
        "not ready answers `503 audit_unavailable`, with nothing checked, counted or elevated.",
        # C-7: the order, each record ahead of the change it records.
        "After `auth.step_up_granted`, each rotation record is written ahead of the change it "
        "records (C-2.9): `auth.session_revoked` (reason `rotated`, the old session) ahead of the "
        "old session's revocation, then `auth.session_created` (the new session, naming the old "
        "one in `rotated_from`) ahead of the mint.",
        "When either record cannot be written, the grant just made is ended and the answer is "
        "`503 audit_unavailable`: nothing is elevated, nothing is rotated and the old tokens keep "
        "working.",
        # C-7: a refused grant record ends the grant too; what stands of a refused rotation is
        # voided, and a lost void is counted (C-2.9).
        "The same holds for a step-up whose `auth.step_up_granted` cannot be recorded once its "
        "grant is stored.",
        "A refused `auth.session_created` comes after the rotation's `auth.session_revoked`, which "
        "then stands: an `auth.step_up_failed` row (reason `unrotated`) voids it and names the "
        "ended grant; when `auth.step_up_granted` is all that stands, the row's reason is "
        "`grant_ended`.",
        "A row the audit writer refuses too is lost, counted and alerted (`AuthAuditOutcomeLost`).",
        # A grant that cannot be ended either stays for its window; the grant is on the old
        # session until the claim; the `200`'s echo is advisory.
        "When the grant cannot be ended either (the session store refuses that too), it stays on "
        "the old session, which is not rotated, for the rest of its window",
        "The grant is stored on the old session first and moves to the new one at that "
        "revocation (the claim)",
        "until the claim, a request with the old access token is elevated for a grace class, "
        "while a no-grace grant serves only the request it is bound to",
        "echo the grant as it was made and are advisory: the server reads the session's row on "
        "every elevated request",
        # C-8: the conditional claim, no grace for the old token.
        "of a step-up and a `POST /auth/refresh` of the same session exactly one rotates it, and "
        "the old token gets no grace period",
        "the answer is `401 unauthenticated`, a record voids the `auth.session_created` that "
        "announced the new session, and the user signs in again",
        "The client holds its refresh lock across the step-up call",
        "the rotation's `auth.session_revoked` and `auth.session_created`",
    ],
)
def test_step_up_description_states_the_rotation_audit_and_refusals(
    spec: dict[str, Any], rule: str
) -> None:
    assert rule in _flat(spec["paths"]["/auth/step-up"]["post"]["description"])


def test_csrf_section_lists_step_up_as_a_rotation_point(spec: dict[str, Any]) -> None:
    info = _flat(spec["info"]["description"])
    start = info.index("**Issue, rotate and re-issue.**")
    bullet = info[start : info.index("**Multi-tab.**", start)]
    assert "A successful `POST /auth/step-up` rotates the session (SR-013)" in bullet


def test_csrf_cookie_scheme_lists_step_up_as_a_rotation_point(spec: dict[str, Any]) -> None:
    scheme = _flat(spec["components"]["securitySchemes"]["csrfCookie"]["description"])
    assert "rotated on every `/auth/refresh` and on a successful `/auth/step-up`" in scheme


@pytest.mark.parametrize("minting", ["/auth/login", "/auth/mfa/verify", "/auth/refresh"])
def test_step_up_ignores_idempotency_keys_like_every_token_minting_operation(
    spec: dict[str, Any], minting: str
) -> None:
    """A replay layer must never store or replay a response that carries a token bundle."""
    step_up = spec["paths"]["/auth/step-up"]["post"]
    assert step_up["x-idempotency"] == spec["paths"][minting]["post"]["x-idempotency"] == "ignored"


def test_step_up_ok_declares_the_optional_consumed_challenge_id(spec: dict[str, Any]) -> None:
    """#2304 (additive, C-6.3): `challenge_id` is an optional uuid, never required."""
    body = _body(spec, "/auth/step-up")
    member = body["properties"]["challenge_id"]
    assert (member["type"], member["format"]) == ("string", "uuid")
    assert "challenge_id" not in body["required"]
    text = _flat(member["description"])
    assert "the challenge this step-up consumed" in text
    assert "never echoes a challenge the grant did not consume" in text
    assert "The `200` echoes the consumed `challenge_id`" in _flat(
        spec["paths"]["/auth/step-up"]["post"]["description"]
    )


def test_step_up_ok_examples_conform_and_show_both_shapes(spec: dict[str, Any]) -> None:
    examples = _ok(spec, "/auth/step-up")["content"]["application/json"]["examples"]
    assert set(examples) == {"noGraceWithChallenge", "graceWithoutChallenge"}
    for example in examples.values():
        _validator(spec).validate(example["value"])
    assert examples["noGraceWithChallenge"]["value"]["single_use"] is True
    assert "challenge_id" in examples["noGraceWithChallenge"]["value"]
    assert "challenge_id" not in examples["graceWithoutChallenge"]["value"]


def test_step_up_ok_rejects_a_challenge_id_that_is_not_a_uuid(spec: dict[str, Any]) -> None:
    with pytest.raises(ValidationError, match="is not a 'uuid'"):
        _validator(spec).validate({**_granted(spec), "challenge_id": "not-a-uuid"})
