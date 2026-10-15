"""Step-up challenge bound to the refused request (#2304), slice 1: contract only (C-6.1).

Pins what the runtime slices implement (PR #2290 ruling, rule 4):

* every `403 step_up_required` body is a challenge for the request it refused: `challenge_id`,
  `challenge_expires_at`, `action_class`, the server-composed `action_summary` and `target`;
* `POST /auth/step-up` takes an optional `challenge_id`; an expired or stale one is `400
  validation_failed` with rule `challenge_expired`, decided before any factor is checked;
* a no-grace grant is bound to the challenged request; another request of the class is refused
  `403 step_up_required` and audited `auth.step_up_mismatch`;
* an `x-idempotency: required` operation records `Idempotency-Key` only after authentication,
  CSRF, session state and authorisation pass, so the re-sent held request is a first submission.

The routes answer as before until the runtime slices land; the router and service tests pin that.
"""

from __future__ import annotations

from typing import Any

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from candleviewer.api.contract_conformance import load_openapi_spec

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


def _validator(spec: dict[str, Any], pointer: str) -> Draft202012Validator:
    resource = Resource.from_contents(spec, default_specification=DRAFT202012)
    return Draft202012Validator(
        {"$ref": f"{_BASE}#{pointer}"},
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


def _idempotency_required_operations() -> list[tuple[str, str]]:
    return [
        (method, path)
        for path, item in _SPEC["paths"].items()
        for method, operation in item.items()
        if isinstance(operation, dict) and operation.get("x-idempotency") == "required"
    ]


_IDEMPOTENCY_REQUIRED = _idempotency_required_operations()


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


def test_kill_switch_release_challenge_restates_what_would_execute(spec: dict[str, Any]) -> None:
    """AC "Challenge restates what will execute" (POST /trading/kill-switch, release, global)."""
    body = _forbidden_example(spec, "stepUpRequired")
    _validator(spec, _PROBLEM).validate(body)
    assert body["status"] == 403
    assert body["code"] == "step_up_required"
    assert body["action_class"] == "killswitch"
    assert body["action_summary"] == "Release kill switch, scope global"
    assert set(_CHALLENGE_FIELDS) <= set(body)


def test_typed_confirmation_challenge_names_its_target(spec: dict[str, Any]) -> None:
    body = _forbidden_example(spec, "stepUpRequiredTypedConfirmation")
    _validator(spec, _PROBLEM).validate(body)
    assert body["code"] == "step_up_required"
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
        _validator(spec, _PROBLEM).validate(body)


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
    _validator(spec, _STEP_UP_REQUEST).validate(body)


def test_step_up_request_refuses_a_malformed_challenge_id(spec: dict[str, Any]) -> None:
    body = {"code": "123456", "password": "pw", "challenge_id": "challenge-1"}
    with pytest.raises(ValidationError, match="is not a 'uuid'"):
        _validator(spec, _STEP_UP_REQUEST).validate(body)


def test_expired_challenge_answer_is_a_conforming_400(spec: dict[str, Any]) -> None:
    """AC "Challenge expiry": `400` with a machine-readable rule; nothing checked or elevated."""
    text = _flat(
        _step_up(spec)["requestBody"]["content"]["application/json"]["schema"]["properties"][
            "challenge_id"
        ]["description"]
    )
    assert (
        "`400 validation_failed` with `errors: [{field: challenge_id, rule: challenge_expired}]`"
        in text
    )
    assert "(expired, superseded, already used or unknown)" in text
    assert "no factor is verified, no failure is counted and nothing is elevated" in text
    assert "drops the held request without sending it" in text
    assert "400" in _step_up(spec)["responses"]
    expired = {
        "type": "https://candleviewer.local/errors/validation_failed",
        "title": "Request body or parameters failed schema validation",
        "status": 400,
        "code": "validation_failed",
        "detail": "The step-up challenge expired.",
        "errors": [{"field": "challenge_id", "rule": "challenge_expired", "message": "expired"}],
    }
    _validator(spec, _PROBLEM).validate(expired)


@pytest.mark.parametrize(
    "rule",
    [
        "Every `403 step_up_required` is a challenge for the one request it refused",
        "The server composes `action_summary` from the validated request",
        "the client shows it verbatim and never composes its own",
        "A session has at most one live challenge",
        "`challenge_id`, when sent, must name it",
        "`action_class` alone never elevates a no-grace class",
        "the one-shot grant is bound to the challenged request",
        "its method, its path including any query string, and its canonical JSON body",
        "Any other request of the class is refused with `403 step_up_required`",
        "audited as `auth.step_up_mismatch`",
        "The refusal does not use up the grant",
        "Grace classes keep the unbound 5-minute window",
        "`auth.step_up_required` records the `challenge_id`",
        "the bound request's SHA-256 fingerprint",
        "No audit record carries a request body, the password or the code",
        "re-sends it as is after a successful step-up",
        "the re-send is a first submission and executes once",
        "drops the request without sending it",
    ],
)
def test_step_up_description_states_the_challenge_rule(spec: dict[str, Any], rule: str) -> None:
    assert rule in _flat(_step_up(spec)["description"])


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
