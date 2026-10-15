"""Step-up challenge bound to the refused request (#2304; PR #2290 ruling, rule 4).

Pins the contract:

* every `403 step_up_required` body is a challenge for the one request it refused:
  `challenge_id`, `challenge_expires_at`, `action_class` and the server-composed `action_summary`
  and `target`, which come from a fixed per-route template, never from free text or credential
  material;
* `POST /auth/step-up` takes `challenge_id`: required for a no-grace class (`400
  validation_failed`, rule `challenge_required`, without it) and optional for a grace class; a
  stale one is `400 validation_failed` with rule `challenge_expired`; both are decided before any
  factor is checked;
* a no-grace grant is bound to the challenged request by a stated SHA-256 fingerprint; another
  request of the class is refused `403 step_up_required` and audited `auth.step_up_mismatch`;
* an operation that requires `Idempotency-Key` records it only after authentication, CSRF,
  session state and authorisation pass, so the re-sent held request is a first submission;
* provider side (C-6.2): a dangerous route's real `403 step_up_required` body validates against
  `Problem` and carries the challenge.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from candleviewer.api.contract_conformance import load_openapi_spec
from tests.unit.api.test_step_up_router import _H, _build

_BASE = "urn:cv:openapi"
_PROBLEM = "/components/schemas/Problem"
_STEP_UP_REQUEST = "/paths/~1auth~1step-up/post/requestBody/content/application~1json/schema"
_CHALLENGE_FIELDS = (
    "challenge_id",
    "challenge_expires_at",
    "action_class",
    "action_summary",
    "target",
)
_SPEC = load_openapi_spec()


@pytest.fixture(scope="module")
def spec() -> dict[str, Any]:
    return _SPEC


def _ref(pointer: str) -> dict[str, Any]:
    return {"$ref": f"{_BASE}#{pointer}"}


def _validator(spec: dict[str, Any], schema: dict[str, Any]) -> Draft202012Validator:
    resource = Resource.from_contents(spec, default_specification=DRAFT202012)
    return Draft202012Validator(
        schema,
        registry=Registry().with_resource(_BASE, resource),
        format_checker=Draft202012Validator.FORMAT_CHECKER,
    )


def _flat(text: str) -> str:
    """Collapse YAML line wrapping so prose pins survive a re-wrap."""
    return " ".join(text.split())


def _forbidden_example(spec: dict[str, Any], name: str) -> dict[str, Any]:
    forbidden = spec["components"]["responses"]["Forbidden"]
    value: dict[str, Any] = forbidden["content"]["application/problem+json"]["examples"][name][
        "value"
    ]
    return value


def _step_up(spec: dict[str, Any]) -> dict[str, Any]:
    operation: dict[str, Any] = spec["paths"]["/auth/step-up"]["post"]
    return operation


def _challenge_id_text(spec: dict[str, Any]) -> str:
    schema = _step_up(spec)["requestBody"]["content"]["application/json"]["schema"]
    return _flat(schema["properties"]["challenge_id"]["description"])


def _problem_text(spec: dict[str, Any], field: str) -> str:
    return _flat(spec["components"]["schemas"]["Problem"]["properties"][field]["description"])


def _idempotency_required_operations() -> list[tuple[str, str]]:
    return [
        (method, path)
        for path, item in _SPEC["paths"].items()
        for method, operation in item.items()
        if isinstance(operation, dict) and operation.get("x-idempotency") == "required"
    ]


_IDEMPOTENCY_REQUIRED = _idempotency_required_operations()

#: A `step_up_required` problem body: `Problem`, with that code and status.
_STEP_UP_REQUIRED_BODY = {
    "allOf": [
        _ref(_PROBLEM),
        {
            "required": ["code"],
            "properties": {"status": {"const": 403}, "code": {"const": "step_up_required"}},
        },
    ]
}


def test_step_up_required_is_a_403_in_the_error_catalogue(spec: dict[str, Any]) -> None:
    codes = {entry["code"]: entry for entry in spec["x-error-codes"]}
    assert codes["step_up_required"]["status"] == 403
    assert codes["validation_failed"]["status"] == 400


@pytest.mark.parametrize(
    ("field", "shape"),
    [
        ("challenge_id", {"type": "string", "format": "uuid"}),
        ("challenge_expires_at", {"type": "string", "format": "date-time"}),
        ("action_class", {"type": "string"}),
        ("action_summary", {"type": "string"}),
        ("target", {"type": ["string", "null"]}),
    ],
)
def test_problem_declares_the_step_up_challenge_field(
    spec: dict[str, Any], field: str, shape: dict[str, Any]
) -> None:
    prop = spec["components"]["schemas"]["Problem"]["properties"][field]
    assert {key: prop[key] for key in shape} == shape
    assert _flat(prop["description"]).startswith("`step_up_required` only:")


@pytest.mark.parametrize(
    ("field", "rule"),
    [
        (
            "challenge_id",
            "a random UUIDv4 scoped to the issuing session, so a value from another session is "
            "unknown",
        ),
        ("challenge_id", "a step-up for a no-grace class must send it"),
        ("action_summary", "It comes from a fixed per-route template"),
        (
            "action_summary",
            "Request values appear in it only as validated enum values (bare) or as identifiers "
            "and server-resolved labels (quoted, each bounded by its own schema's `maxLength` or "
            "`format`)",
        ),
        ("action_summary", "never as free text such as a `reason`"),
        (
            "action_summary",
            "never as key material, a password, a token, a TOTP or recovery code or any field the "
            "redaction deny-list names (C-12.6)",
        ),
        (
            "target",
            "it is an identifier or a server-resolved label of the validated request, never free "
            "text or credential material",
        ),
    ],
)
def test_problem_challenge_field_states_its_rule(
    spec: dict[str, Any], field: str, rule: str
) -> None:
    assert rule in _problem_text(spec, field)


def test_kill_switch_release_challenge_restates_what_would_execute(spec: dict[str, Any]) -> None:
    """AC "Challenge restates what will execute" (POST /trading/kill-switch, release, global)."""
    body = _forbidden_example(spec, "stepUpRequired")
    _validator(spec, _STEP_UP_REQUIRED_BODY).validate(body)
    assert body["action_class"] == "killswitch"
    assert body["action_summary"] == "Release kill switch, scope global"
    assert set(_CHALLENGE_FIELDS) <= set(body)


def test_typed_confirmation_challenge_names_its_target(spec: dict[str, Any]) -> None:
    body = _forbidden_example(spec, "stepUpRequiredTypedConfirmation")
    _validator(spec, _STEP_UP_REQUIRED_BODY).validate(body)
    assert body["target"] == "sub_002"
    assert f"'{body['target']}'" in body["action_summary"]


@pytest.mark.parametrize(
    ("field", "bad", "fmt"),
    [
        ("challenge_id", "challenge-1", "uuid"),
        ("challenge_expires_at", "in five minutes", "date-time"),
    ],
)
def test_problem_rejects_a_malformed_challenge_field(
    spec: dict[str, Any], field: str, bad: str, fmt: str
) -> None:
    body = {**_forbidden_example(spec, "stepUpRequired"), field: bad}
    with pytest.raises(ValidationError, match=f"is not a '{fmt}'"):
        _validator(spec, _ref(_PROBLEM)).validate(body)


def test_forbidden_response_documents_step_up_required_bodies(spec: dict[str, Any]) -> None:
    text = _flat(spec["components"]["responses"]["Forbidden"]["description"])
    assert "it may carry `code: step_up_required`" in text
    assert all(f"`{field}`" in text for field in _CHALLENGE_FIELDS)


def test_step_up_request_takes_an_optional_challenge_id(spec: dict[str, Any]) -> None:
    schema = _step_up(spec)["requestBody"]["content"]["application/json"]["schema"]
    assert schema["properties"]["challenge_id"]["format"] == "uuid"
    assert "challenge_id" not in schema["required"]
    assert schema["additionalProperties"] is False


@pytest.mark.parametrize(
    "body",
    [
        {"code": "123456", "password": "pw"},
        {
            "code": "123456",
            "password": "pw",
            "challenge_id": "6f1d2c3b-4a5e-4f60-8a7b-9c0d1e2f3a4b",
        },
    ],
    ids=["without-challenge-id", "with-challenge-id"],
)
def test_step_up_request_body_conforms(spec: dict[str, Any], body: dict[str, str]) -> None:
    _validator(spec, _ref(_STEP_UP_REQUEST)).validate(body)


def test_step_up_request_refuses_a_malformed_challenge_id(spec: dict[str, Any]) -> None:
    body = {"code": "123456", "password": "pw", "challenge_id": "challenge-1"}
    with pytest.raises(ValidationError, match="is not a 'uuid'"):
        _validator(spec, _ref(_STEP_UP_REQUEST)).validate(body)


@pytest.mark.parametrize(
    "rule",
    [
        "Required for a no-grace class (`live_enablement` or `killswitch`, named by the live "
        "challenge or by `action_class`)",
        "omitting it is `400 validation_failed` with "
        "`errors: [{field: challenge_id, rule: challenge_required}]`",
        "Optional for a grace class: without it the server uses the session's live challenge",
        "A value that does not name the live challenge (expired, superseded, already used or "
        "unknown), or that is sent when there is none, gets `400 validation_failed` with "
        "`errors: [{field: challenge_id, rule: challenge_expired}]`",
        "Either `400` is decided before the password and code are checked",
        "no factor is verified, no failure is counted and nothing is elevated",
        "The client then drops the held request without sending it",
    ],
)
def test_step_up_challenge_id_states_when_it_is_required(spec: dict[str, Any], rule: str) -> None:
    """AC "Challenge expiry" (contract half) and the no-grace `challenge_id` requirement."""
    assert rule in _challenge_id_text(spec)


@pytest.mark.parametrize("rule", ["challenge_required", "challenge_expired"])
def test_refused_challenge_answer_is_a_conforming_400(spec: dict[str, Any], rule: str) -> None:
    assert "400" in _step_up(spec)["responses"]
    refused = {
        "type": "https://candleviewer.local/errors/validation_failed",
        "title": "Request body or parameters failed schema validation",
        "status": 400,
        "code": "validation_failed",
        "detail": "The step-up challenge cannot be answered.",
        "errors": [{"field": "challenge_id", "rule": rule, "message": rule}],
    }
    _validator(spec, _ref(_PROBLEM)).validate(refused)


@pytest.mark.parametrize(
    "rule",
    [
        "Every `403 step_up_required` is a challenge for the one request it refused",
        "The server composes `action_summary` from the validated request with a fixed per-route "
        "template",
        "Request values appear in it only as validated enum values or as identifiers and "
        "server-resolved labels, never as free text such as a `reason` and never as credential "
        "material",
        "the client shows it verbatim and never composes its own",
        "A session has at most one live challenge",
        "when the session turns read-only and when it idle-locks (#2301)",
        "`challenge_id`, when sent, must name it",
        "A step-up for a no-grace class (named by the live challenge or by `action_class`) must "
        "send it: without it, or without a live challenge, the answer is `400`",
        "`action_class` alone never elevates a no-grace class",
    ],
)
def test_step_up_description_states_the_challenge_rule(spec: dict[str, Any], rule: str) -> None:
    assert rule in _flat(_step_up(spec)["description"])


@pytest.mark.parametrize(
    "rule",
    [
        "the one-shot grant is bound to the challenged request",
        "its method, its path including any query string, and its canonical JSON body",
        "The fingerprint is the hex SHA-256 of the method, a line feed, the raw request target "
        "(path and query string exactly as received, with no percent-decoding and no "
        "trailing-slash or parameter-order normalisation), a line feed, and the RFC 8785 (JCS) "
        "serialisation of the body as the operation validated it (empty when the operation "
        "takes no body)",
        "`action_summary`, the fingerprint and the executed action all come from that one object",
        "number forms, string escapes and duplicate member names cannot make them disagree",
        "no Unicode normalisation is applied",
        "Headers, `Idempotency-Key` included, are not part of the binding",
        "Any other request of the class is refused with `403 step_up_required`",
        "audited as `auth.step_up_mismatch`",
        "The refusal does not use up the grant",
        "a newer step-up for the class replaces it",
        "A session holds at most one grant per no-grace class",
        "Grace classes keep the unbound 5-minute window",
    ],
)
def test_step_up_description_states_the_binding_rule(spec: dict[str, Any], rule: str) -> None:
    assert rule in _flat(_step_up(spec)["description"])


@pytest.mark.parametrize(
    "rule",
    [
        "`auth.step_up_required` records the `challenge_id`",
        "the bound request's SHA-256 fingerprint",
        "`auth.step_up_mismatch` records the bound and the refused request's fingerprints",
        "No audit record carries `action_summary`, `target`, a request body, the password or the "
        "code",
        "Always audited (`auth.step_up_required`, `auth.step_up_granted`, `auth.step_up_failed`, "
        "`auth.step_up_mismatch`, `auth.session_readonly_downgrade`)",
    ],
)
def test_step_up_description_states_the_audit_rule(spec: dict[str, Any], rule: str) -> None:
    assert rule in _flat(_step_up(spec)["description"])


@pytest.mark.parametrize(
    "rule",
    [
        "re-sends it as is after a successful step-up",
        "the re-send is a first submission and executes once",
        "drops the request without sending it",
    ],
)
def test_step_up_description_states_the_holding_rule(spec: dict[str, Any], rule: str) -> None:
    assert rule in _flat(_step_up(spec)["description"])


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="#2304 runtime slice: `required_problem()` answers with `action_class` only; remove "
    "this marker when the 403 carries the challenge fields",
)
async def test_step_up_required_route_body_carries_the_challenge(spec: dict[str, Any]) -> None:
    """Provider side (C-6.2): a dangerous route's real `403 step_up_required` body.

    A body that is not a `step_up_required` problem conforming to `Problem` raises
    `ValidationError`, a real failure; only the missing challenge fields are expected to fail.
    """
    client, *_ = await _build()
    body = client.put(f"/users/{uuid.uuid4()}/roles", headers=_H).json()
    _validator(spec, _STEP_UP_REQUIRED_BODY).validate(body)
    assert set(_CHALLENGE_FIELDS) <= set(body)


@pytest.mark.parametrize(
    "rule",
    [
        "On every operation that requires the key (parameter `IdempotencyKeyRequired`, which "
        "every `x-idempotency: required` operation takes) the key is recorded only after the "
        "request has passed every admission check",
        "authorisation (RBAC, account scope and `step_up_required`)",
        "A request refused by any of them stores no idempotency record and has no side effect",
        "is therefore a first submission: it executes once and is not answered from the "
        "idempotency store",
    ],
)
def test_idempotency_section_states_the_binding_point(spec: dict[str, Any], rule: str) -> None:
    """AC "Refusal binds no idempotency key", contract half."""
    info = _flat(spec["info"]["description"])
    start = info.index("### Idempotency")
    section = info[start : info.index("### Rate limiting", start)]
    assert rule in section


def test_bound_key_parameter_states_the_binding_point(spec: dict[str, Any]) -> None:
    text = _flat(spec["components"]["parameters"]["IdempotencyKeyRequired"]["description"])
    assert "Recorded only after authentication, CSRF, session state and authorisation" in text
    assert "a refused request binds nothing" in text


def test_idempotency_required_operations_are_enumerated() -> None:
    assert ("put", "/rules/{ruleId}/mode") in _IDEMPOTENCY_REQUIRED
    assert ("post", "/trading/kill-switch") in _IDEMPOTENCY_REQUIRED
    assert ("post", "/orders") in _IDEMPOTENCY_REQUIRED


@pytest.mark.parametrize(
    ("method", "path"),
    _IDEMPOTENCY_REQUIRED,
    ids=[f"{method.upper()} {path}" for method, path in _IDEMPOTENCY_REQUIRED],
)
def test_idempotency_required_operation_takes_the_bound_key(
    spec: dict[str, Any], method: str, path: str
) -> None:
    parameters = spec["paths"][path][method].get("parameters", [])
    refs = {p.get("$ref") for p in parameters if isinstance(p, dict)}
    assert "#/components/parameters/IdempotencyKeyRequired" in refs
