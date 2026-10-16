"""MFA fails closed with `503 auth_unavailable` (#2152 S1): contract and design only (C-6.1).

Pins main-orchestrator's rulings D1-D7 of 2026-10-16 on #2152. When the KEK or the needed auth key
is unavailable, the eight operations that check or seal a second factor answer
`503 auth_unavailable` through one `AuthUnavailable` response: `POST /auth/login` only for a user
with a confirmed MFA method and only after the password verified, and the answer counts, consumes
and changes nothing (D4). The code is a new REST-only registry entry, regenerated into the Python
and TypeScript enums. The design the later slices build on is ADR-0009 Amendment 4, the `auth_keys`
table of `21-database-schema.md` section 3.1.5a, its section 12 rows and SR-022. No route emits the
code yet: the switch-over slice (S5b) maps it, audits it and adds the provider test.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.ws._generated.error_codes import ERROR_META, WS_ERROR_CODES, ErrorCode

_BASE = "urn:cv:openapi"
_CODE = "auth_unavailable"
_RESPONSE = {"$ref": "#/components/responses/AuthUnavailable"}
_PLAN = Path(__file__).resolve().parents[4] / "docs" / "plan"
_ADR = "ADR-0009-secrets-and-key-management.md"
#: The eight operations that check or seal a second factor (ruling D4 on #2152).
_MFA_OPERATIONS = {
    ("post", "/auth/login"): "authLogin",
    ("post", "/auth/mfa/verify"): "authMfaVerify",
    ("post", "/auth/mfa/recovery"): "authMfaRecovery",
    ("post", "/auth/mfa/enroll"): "authMfaEnroll",
    ("post", "/auth/mfa/enroll/confirm"): "authMfaEnrollConfirm",
    ("post", "/auth/step-up"): "authStepUp",
    ("post", "/invites/{inviteToken}"): "redeemInvite",
    ("post", "/invites/{inviteToken}/confirm"): "confirmInvite",
}
_OPERATION = re.compile(r"`(GET|POST|PUT|PATCH|DELETE) (/[^`]+)`")


@pytest.fixture(scope="module")
def spec() -> dict[str, Any]:
    return load_openapi_spec()


def _flat(text: str) -> str:
    """Collapse YAML and Markdown line wrapping so prose pins survive a re-wrap."""
    return " ".join(text.split())


def _response(spec: dict[str, Any]) -> dict[str, Any]:
    response: dict[str, Any] = spec["components"]["responses"]["AuthUnavailable"]
    return response


def _example(spec: dict[str, Any]) -> dict[str, Any]:
    examples = _response(spec)["content"]["application/problem+json"]["examples"]
    value: dict[str, Any] = examples["mfaUnavailable"]["value"]
    return value


def _conforms(spec: dict[str, Any], value: Any, pointer: str) -> None:
    resource = Resource.from_contents(spec, default_specification=DRAFT202012)
    Draft202012Validator(
        {"$ref": f"{_BASE}#{pointer}"},
        registry=Registry().with_resource(_BASE, resource),
        format_checker=Draft202012Validator.FORMAT_CHECKER,
    ).validate(value)


def _between(doc: str, start: str, end: str) -> str:
    first = doc.index(start)
    return doc[first : doc.index(end, first + len(start))]


def _row(table: str, *cells: str) -> list[str]:
    """The cells of the one Markdown table row whose leading cells are `cells`."""
    rows = [
        [cell.strip() for cell in line.strip().strip("|").split("|")]
        for line in table.splitlines()
        if line.startswith("|")
    ]
    matches = [row for row in rows if tuple(row[: len(cells)]) == cells]
    assert len(matches) == 1, cells
    return matches[0]


def test_registry_auth_unavailable_is_a_retryable_rest_only_503(spec: dict[str, Any]) -> None:
    entry = {e["code"]: e for e in spec["x-error-codes"]}[_CODE]
    assert (entry["status"], entry["retryable"]) == (503, True)
    assert entry.get("surface", ["rest"]) == ["rest"]  # MFA is a REST flow; no WS frame carries it
    meta = ERROR_META[ErrorCode(_CODE)]
    assert (meta.surfaces, meta.retryable) == (("rest",), True)
    assert ErrorCode(_CODE) not in WS_ERROR_CODES


def test_response_is_a_problem_with_retry_after_and_a_conforming_example(
    spec: dict[str, Any],
) -> None:
    response = _response(spec)
    assert response["headers"] == {"Retry-After": {"$ref": "#/components/headers/RetryAfter"}}
    assert response["content"]["application/problem+json"]["schema"] == {
        "$ref": "#/components/schemas/Problem"
    }
    example = _example(spec)
    _conforms(spec, example, "/components/schemas/Problem")
    title = {e["code"]: e["title"] for e in spec["x-error-codes"]}[_CODE]
    assert (example["code"], example["status"], example["title"]) == (_CODE, 503, title)
    assert example["type"] == f"https://candleviewer.local/errors/{_CODE}"
    assert example["retry_after_seconds"] > 0


@pytest.mark.parametrize(("method", "path"), sorted(_MFA_OPERATIONS))
def test_mfa_operation_declares_the_503(spec: dict[str, Any], method: str, path: str) -> None:
    operation = spec["paths"][path][method]
    assert operation["operationId"] == _MFA_OPERATIONS[(method, path)]
    assert operation["responses"]["503"] == _RESPONSE


def test_only_the_eight_mfa_operations_use_the_response(spec: dict[str, Any]) -> None:
    users = {
        (method, path)
        for path, item in spec["paths"].items()
        for method, operation in item.items()
        if isinstance(operation, dict) and _RESPONSE in operation.get("responses", {}).values()
    }
    assert users == set(_MFA_OPERATIONS)


def test_description_names_exactly_the_eight_operations(spec: dict[str, Any]) -> None:
    description = _flat(_response(spec)["description"])
    named = {(method.lower(), path) for method, path in _OPERATION.findall(description)}
    assert named == set(_MFA_OPERATIONS)


@pytest.mark.parametrize(
    "rule",
    [
        "the KEK is unavailable (any reason in `docs/plan/spikes/e27-kek.md` section 6)",
        "this environment's auth keyring is missing, mismatched or stranded",
        "the user's TOTP method is sealed under a key this process does not hold",
        "`POST /auth/login` answers it only for a user with a confirmed MFA method and only after "
        "the password verified, in place of the `mfa_required` challenge; a wrong password is "
        "still `401 unauthenticated`.",
        "The answer counts, consumes and changes nothing: no session or `mfa_token` is minted, "
        "nothing is revoked, and no MFA attempt, failed-login count, lockout, recovery-code use, "
        "invite redemption or enrolment is recorded",
        'A method this process cannot open never counts as "no method": it never leads to an '
        "enrolment-only session or a new enrolment.",
        "Users without an MFA method still sign in, and existing sessions keep working.",
        "`detail` is generic: it names no cause, key, key reference or KEK version",
        "Audited as `auth.mfa_unavailable`.",
    ],
)
def test_response_states_the_ruled_rule(spec: dict[str, Any], rule: str) -> None:
    assert rule in _flat(_response(spec)["description"])


def test_example_detail_names_no_cause_and_no_key(spec: dict[str, Any]) -> None:
    detail = _example(spec)["detail"].lower()
    for word in ("kek", "key", "version", "missing", "mismatch", "stranded"):
        assert word not in detail


def test_schema_doc_defines_the_kek_wrapped_auth_keys_table() -> None:
    doc = (_PLAN / "21-database-schema.md").read_text(encoding="utf-8")
    section = _between(doc, "#### 3.1.5a `auth_keys`", "\n### 3.2 ")
    ddl = _flat(_between(section, "```sql", "\n```"))
    for fragment in (
        "env exchange_env NOT NULL",
        "CHECK (purpose IN ('totp_seal','recovery_hmac'))",
        "CHECK (origin IN ('generated','imported_env'))",
        "UNIQUE (env, purpose, key_version)",
        "CREATE INDEX ix_auth_keys_env_kek ON auth_keys (env, kek_version);",
        "COMMENT ON COLUMN auth_keys.dek_ref IS 'SECRET:",
    ):
        assert fragment in ddl
    prose = _flat(section)
    for binding in (
        "cv-akey-v1 ‖ environment ‖ purpose ‖ id ‖ kek_version",
        "cv-totp-v1 ‖ environment ‖ user_id",
        "cv-rc-v2 ‖ user_id ‖ normalised code",
    ):
        assert binding in prose
    assert "The downgrade refuses while any `auth_keys` row exists (C-5.2)" in prose


def test_classification_fixes_the_code_hash_drift_and_classes_the_wrap() -> None:
    doc = (_PLAN / "21-database-schema.md").read_text(encoding="utf-8")
    table = _between(doc, "## 12. PII / secret classification per column", "### 12.1")
    code_hash = _row(table, "`recovery_codes`", "`code_hash`")
    assert code_hash[2:4] == ["S", "HMAC-SHA256 under the KEK-wrapped recovery key"]
    assert _row(table, "`auth_keys`", "`dek_ref`")[2] == "S"
    seed = _row(table, "`mfa_methods`", "`secret_enc`")
    assert seed[3] == "AES-256-GCM under the KEK-wrapped TOTP key"
    assert "never logged, snapshotted, returned or exported" in seed[4]


def test_sr_022_requires_the_recovery_key_from_the_auth_keyring() -> None:
    doc = (_PLAN / "04-security-program.md").read_text(encoding="utf-8")
    requirement = next(line for line in doc.splitlines() if line.startswith("| SR-022 "))
    assert (
        "That key MUST be the environment's recovery key from the auth keyring, generated inside "
        "M2 (imported once from the env setting on `demo`/`testnet` only) and stored only wrapped "
        "under the KEK; new digests also bind the user (ADR-0009 Amendment 4)."
    ) in requirement


def test_adr_0009_amendment_4_records_the_injected_capability() -> None:
    adr = (_PLAN / "27-adrs" / _ADR).read_text(encoding="utf-8")
    amendment = _flat(adr[adr.index("## Amendment 4 (2026-10-16, #2152;") :])
    for decision in (
        "**One auth keyring per environment.**",
        "**Injected capability, no import edge (C-3.4).**",
        "the import-linter contracts do not change",
        "Key bytes never leave M2.",
        "An opened TOTP seed exists only inside the M18 MFA verifier",
        "answer `503 auth_unavailable` (`22-api-openapi.yaml`, `AuthUnavailable`)",
    ):
        assert decision in amendment
