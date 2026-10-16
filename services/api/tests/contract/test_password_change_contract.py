"""Password-change contract (#2330, for the E09-D05 spec #188): contract only (C-6.1).

Pins the three codes `PUT /auth/password` adds to the generic ones. SCR-004 and its SCR-112
variant can then tell a breached new password from a reused one, and a wrong current password
from an expired session. Also pins the check order that stops either code from being an oracle,
and the `04-security-program.md` section 6.3.1 strings that the example `detail` values quote.
The route itself ships in #2110.
"""

from __future__ import annotations

from typing import Any

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from candleviewer.api.contract_conformance import OPENAPI_SPEC_PATH, load_openapi_spec
from candleviewer.ws._generated.error_codes import ERROR_META, WS_ERROR_CODES, ErrorCode

_BASE = "urn:cv:openapi"
_SECURITY_DOC = OPENAPI_SPEC_PATH.parent / "04-security-program.md"
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
        "`401 unauthenticated`",
        "`403 csrf_token_invalid`",
        "`422 validation_failed`",
        "`403 current_password_invalid`",
        "`422 password_breached`",
        "`422 password_reused`",
    ]
    positions = [description.index(answer) for answer in order]
    assert positions == sorted(positions)
    assert "verified before any rule on the new password runs" in description
    assert "per-account failure and lockout counters as login and `/auth/step-up`" in description
    assert "Policy: SR-028" in description and "section 6.3.1" in description
