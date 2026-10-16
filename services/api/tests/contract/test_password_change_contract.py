"""Password-change contract (#2330, for the E09-D05 spec #188): contract only (C-6.1).

Pins the three codes `PUT /auth/password` adds to the generic ones. SCR-004 and its SCR-112
variant can then tell a breached new password from a reused one, and a wrong current password
from an expired session. Also pins the check order that stops either code from being an oracle,
and the `04-security-program.md` section 6.3.1 strings that the example `detail` values quote.
The route itself ships in #2110. The answers that already ship run here for real: the SR-041
guard mounted before routing, and the shared validation handler on the generated body model.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from candleviewer.api._generated.openapi_models import ChangePasswordRequest
from candleviewer.api.contract_conformance import OPENAPI_SPEC_PATH, load_openapi_spec
from candleviewer.api.csrf import CsrfMiddleware
from candleviewer.api.error_redaction import install_error_redaction
from candleviewer.auth.csrf import CsrfCodec
from candleviewer.ws._generated.error_codes import ERROR_META, WS_ERROR_CODES, ErrorCode
from tests.csrf_helpers import FakeBearerSessions, csrf_headers

_BASE = "urn:cv:openapi"
_SECURITY_DOC = OPENAPI_SPEC_PATH.parent / "04-security-program.md"
_CODEC = CsrfCodec(b"\x05" * 32)
#: The one bearer the fake session store resolves (an expired access token, as far as the
#: guard cares: it binds the CSRF token to the session and leaves the 401 to the route).
_KNOWN_BEARER = "known-session-bearer"
#: code -> (HTTP status, the section 6.3.1 message that the example `detail` quotes).
_CODES = {
    "current_password_invalid": (403, "The current password is incorrect."),
    "password_breached": (422, "This password appears in a known breach list."),
    "password_reused": (422, "You cannot reuse any of your last 5 passwords."),
}
#: Section 6.3.1 rows, in order: requirement listed before typing -> [message, answer].
_POLICY_ROWS = {
    "At least 12 characters": ["Use at least 12 characters.", "`422 validation_failed`"],
    "Not a known breached or easily guessed password": [
        _CODES["password_breached"][1],
        "`422 password_breached`",
    ],
    "Not one of your last 5 passwords": [_CODES["password_reused"][1], "`422 password_reused`"],
    "Passwords match": ["Passwords don't match.", "none, never sent"],
}


@pytest.fixture(scope="module")
def spec() -> dict[str, Any]:
    return load_openapi_spec()


def _op(spec: dict[str, Any]) -> dict[str, Any]:
    op: dict[str, Any] = spec["paths"]["/auth/password"]["put"]
    return op


def _examples(spec: dict[str, Any], status: str) -> dict[str, dict[str, Any]]:
    response = _op(spec)["responses"][status]
    if "$ref" in response:
        response = spec["components"]["responses"][response["$ref"].rsplit("/", 1)[-1]]
    media = response["content"]["application/problem+json"]
    return {name: example["value"] for name, example in media["examples"].items()}


def _conforms_to_problem(spec: dict[str, Any], value: dict[str, Any]) -> None:
    resource = Resource.from_contents(spec, default_specification=DRAFT202012)
    Draft202012Validator(
        {"$ref": f"{_BASE}#/components/schemas/Problem"},
        registry=Registry().with_resource(_BASE, resource),
        format_checker=Draft202012Validator.FORMAT_CHECKER,
    ).validate(value)


def _flat(text: str) -> str:
    """Collapse line wrapping so prose pins survive a re-wrap."""
    return " ".join(text.split())


def _policy_section() -> str:
    text = _SECURITY_DOC.read_text(encoding="utf-8")
    start = text.index("#### 6.3.1 Password policy strings (SR-028)")
    return text[start : text.index("\n### ", start)]


class _Audit:
    async def emit(self, action: str, **kwargs: Any) -> None:
        return None


def _guarded_route() -> TestClient:
    """The shipped SR-041 guard in front of a stub route that answers its session check's 401."""
    app = FastAPI()

    @app.put("/auth/password")
    async def change_password() -> JSONResponse:
        return JSONResponse({"code": "unauthenticated"}, status_code=401)

    app.add_middleware(
        CsrfMiddleware,
        codec=_CODEC,
        sessions=lambda: FakeBearerSessions(_KNOWN_BEARER),
        audit=_Audit(),
        allowed_origins=frozenset(),
    )
    return TestClient(app)


@pytest.mark.parametrize("code", sorted(_CODES))
def test_password_code_is_registered_rest_only_and_generated(
    spec: dict[str, Any], code: str
) -> None:
    entry = {e["code"]: e for e in spec["x-error-codes"]}[code]
    assert (entry["status"], entry["retryable"]) == (_CODES[code][0], False)
    assert entry.get("surface", ["rest"]) == ["rest"]  # no WS frame carries a password
    member = ErrorCode(code)  # regenerated from the registry by tools/errorcodes/generate.py
    assert ERROR_META[member].surfaces == ("rest",) and member not in WS_ERROR_CODES


def test_change_password_401_is_only_the_expired_session(spec: dict[str, Any]) -> None:
    # #2330: on SCR-112 a 401 reads as an expired session, so a wrong current password is a 403.
    assert {e["code"] for e in _examples(spec, "401").values()} == {"unauthenticated"}


@pytest.mark.parametrize(
    ("status", "codes"),
    [
        ("403", {"current_password_invalid", "csrf_token_invalid"}),
        ("422", {"password_breached", "password_reused", "validation_failed"}),
    ],
)
def test_change_password_refusal_examples_are_problems(
    spec: dict[str, Any], status: str, codes: set[str]
) -> None:
    examples = _examples(spec, status)
    assert {e["code"] for e in examples.values()} == codes
    for example in examples.values():
        _conforms_to_problem(spec, example)
        assert example["status"] == int(status)
        assert example["type"].endswith(f"/errors/{example['code']}")


@pytest.mark.parametrize("code", sorted(_CODES))
def test_change_password_example_quotes_the_policy_string(spec: dict[str, Any], code: str) -> None:
    status, message = _CODES[code]
    (example,) = [e for e in _examples(spec, str(status)).values() if e["code"] == code]
    assert example["detail"] == message
    assert example["title"] == {e["code"]: e for e in spec["x-error-codes"]}[code]["title"]


def test_policy_strings_section_lists_the_four_requirements() -> None:
    rows = [line for line in _policy_section().splitlines() if line.startswith("|")][2:]
    cells = [[cell.strip() for cell in row.strip("|").split("|")] for row in rows]
    assert {row[0]: row[-2:] for row in cells} == _POLICY_ROWS
    assert [row[0] for row in cells] == list(_POLICY_ROWS)


def test_policy_strings_section_states_the_current_password_rule() -> None:
    section = _flat(_policy_section())
    assert "`403 current_password_invalid`" in section
    assert f'"{_CODES["current_password_invalid"][1]}"' in section
    assert "the answer is `429 rate_limited` with `Retry-After`" in section


def test_policy_strings_section_is_normative_not_a_description_of_today() -> None:
    # SCR-004, E09-D05 and the web client do not quote the table yet; the section says they must.
    section = _flat(_policy_section())
    assert "must list these four requirements before the first keystroke" in section
    assert "clients must key on that `code`, never on `detail`" in section
    assert "#2110 or #188 replaces that with a match on `code`" in section


def test_sr028_is_verified_by_this_contract_test() -> None:
    lines = _SECURITY_DOC.read_text(encoding="utf-8").splitlines()
    (row,) = [line for line in lines if line.startswith("| SR-028 |")]
    assert row.rstrip(" |").rsplit("|", 1)[-1].strip() == "contract, unit"


def test_change_password_takes_no_user_identifier(spec: dict[str, Any]) -> None:
    # SR-026: a self-service route names no target user, so its codes reveal no other account.
    op = _op(spec)
    assert op["x-rbac"] == {"permissions": [], "scope": "self"}
    assert op["parameters"] == [{"$ref": "#/components/parameters/CsrfToken"}]
    body = spec["components"]["schemas"]["ChangePasswordRequest"]
    assert set(body["properties"]) == {"current_password", "new_password"}
    assert body["additionalProperties"] is False


def test_change_password_verifies_the_current_password_first(spec: dict[str, Any]) -> None:
    description = _flat(_op(spec)["description"])
    order = [
        "`403 csrf_token_invalid`",  # the SR-041 guard, mounted before routing
        "`401 unauthenticated`",
        "`422 validation_failed`",
        "`429 rate_limited`",
        "`403 current_password_invalid`",
        "`422 password_breached`",
        "`422 password_reused`",
    ]
    positions = [description.index(answer) for answer in order]
    assert positions == sorted(positions)
    assert "The SR-041 guard runs before the route" in description
    assert "the current password is not checked while either holds" in description
    assert "verified before any rule on the new password runs" in description
    assert "per-account failure and lockout counters as login and `/auth/step-up`" in description
    assert "Policy: SR-028" in description and "section 6.3.1" in description


@pytest.mark.parametrize(
    ("bearer", "with_token", "answer"),
    [
        (None, False, (403, "csrf_token_invalid")),  # no session and no token
        (None, True, (403, "csrf_token_invalid")),  # a token, but no bearer to bind it to
        ("unknown-bearer", True, (403, "csrf_token_invalid")),  # a bearer with no session
        (_KNOWN_BEARER, True, (401, "unauthenticated")),  # its token verifies: the route answers
    ],
)
def test_change_password_meets_the_sr041_guard_before_the_session_check(
    bearer: str | None, with_token: bool, answer: tuple[int, str]
) -> None:
    headers = csrf_headers(_CODEC) if with_token else {}
    if bearer is not None:
        headers["Authorization"] = f"Bearer {bearer}"
    out = _guarded_route().put("/auth/password", headers=headers)
    assert (out.status_code, out.json()["code"]) == answer


def test_change_password_csrf_example_is_the_guard_answer_to_an_unknown_bearer(
    spec: dict[str, Any],
) -> None:
    headers = {**csrf_headers(_CODEC), "Authorization": "Bearer unknown-bearer"}
    out = _guarded_route().put("/auth/password", headers=headers)
    assert out.json() == _examples(spec, "403")["csrfTokenInvalid"]


def test_change_password_too_short_example_is_what_the_shared_handler_emits(
    spec: dict[str, Any],
) -> None:
    # The generated body model behind the shared validation handler, as #2110 will mount it.
    app = FastAPI()
    install_error_redaction(app)

    @app.put("/auth/password", status_code=204)
    async def change_password(body: ChangePasswordRequest) -> None:
        return None

    out = TestClient(app).put(
        "/auth/password", json={"current_password": "x", "new_password": "short"}
    )
    assert (out.status_code, out.json()) == (422, _examples(spec, "422")["tooShort"])


def test_change_password_fixed_detail_claim_covers_only_the_password_codes(
    spec: dict[str, Any],
) -> None:
    # The guard has a detail per refusal reason, and the shared validation handler sends none.
    description = _flat(_op(spec)["description"])
    claim = (
        "For `current_password_invalid`, `password_breached` and `password_reused`, `detail` is"
        " the fixed section 6.3.1 text."
    )
    assert claim in description
    assert "fixed text per code" not in description


def test_change_password_declares_the_backoff_and_lock_answer(spec: dict[str, Any]) -> None:
    # SR-015/SR-016: the shared login counters throttle or lock the route with a 429.
    assert _op(spec)["responses"]["429"] == {"$ref": "#/components/responses/RateLimited"}
    assert "Retry-After" in spec["components"]["responses"]["RateLimited"]["headers"]
    entry = {e["code"]: e for e in spec["x-error-codes"]}["rate_limited"]
    assert (entry["status"], entry["retryable"]) == (429, True)


def test_change_password_is_not_step_up_gated(spec: dict[str, Any]) -> None:
    # SR-025 names no password-change class: the current password is the re-authentication.
    step_up = spec["paths"]["/auth/step-up"]["post"]["requestBody"]["content"]["application/json"]
    classes = step_up["schema"]["properties"]["action_class"]["enum"]
    assert [c for c in classes if "password" in c] == []
    assert "Not step-up gated" in _flat(_op(spec)["description"])
