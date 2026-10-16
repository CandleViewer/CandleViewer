"""MFA fails closed with `503 auth_unavailable` (#2152 S1): contract and design only (C-6.1).

Pins main-orchestrator's rulings D1-D7 of 2026-10-16 on #2152. When the KEK or the needed auth key
is unavailable, the eight operations that check or seal a second factor answer
`503 auth_unavailable`: seven through the shared `AuthUnavailable` response, and `POST /auth/login`
through a 503 that keeps every `ServiceUnavailable` meaning and adds this one (C-6.3). Login
answers it only for a user with a confirmed MFA method and only after the password verified; the
answer counts, consumes and changes nothing and stores no idempotency record (D4). The response
states, per operation, where the 503 sits among the other checks; step-up decides it before either
factor. The registry title names no cause. The code is a new REST-only registry entry, regenerated
into the Python and TypeScript enums. The design the later slices build on is ADR-0009 Amendment 4,
the `auth_keys` table of `21-database-schema.md` section 3.1.5a (byte formats, privileges and
triggers), its section 12 rows, SR-022 and `e27-kek.md` section 6. No route emits the code yet: the
switch-over slice (S5b) maps it, audits it and adds the provider test.
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
_PROBLEM = "application/problem+json"
_PLAN = Path(__file__).resolve().parents[4] / "docs" / "plan"
_ADR = "ADR-0009-secrets-and-key-management.md"
_LOGIN = ("post", "/auth/login")
#: The eight operations that check or seal a second factor (ruling D4 on #2152).
_MFA_OPERATIONS = {
    _LOGIN: "authLogin",
    ("post", "/auth/mfa/verify"): "authMfaVerify",
    ("post", "/auth/mfa/recovery"): "authMfaRecovery",
    ("post", "/auth/mfa/enroll"): "authMfaEnroll",
    ("post", "/auth/mfa/enroll/confirm"): "authMfaEnrollConfirm",
    ("post", "/auth/step-up"): "authStepUp",
    ("post", "/invites/{inviteToken}"): "redeemInvite",
    ("post", "/invites/{inviteToken}/confirm"): "confirmInvite",
}
#: Every one of them but login, whose 503 also keeps the generic meanings (C-6.3).
_REF_OPERATIONS = {key: op for key, op in _MFA_OPERATIONS.items() if key != _LOGIN}
#: One pinned clause per operation from the "Order of checks" list (review Low 3 on #2152 S1).
_ORDER = {
    "authLogin": "the failed-login count is neither incremented nor reset",
    "authMfaVerify": "before the code. The challenge keeps its attempt count and its expiry.",
    "authMfaRecovery": "before the recovery-code pool and the code, so a `503` says nothing about "
    "how many codes are left.",
    "authMfaEnroll": "before a seed is generated; no method is created.",
    "authMfaEnrollConfirm": "it needs the method's TOTP key and the recovery key; without either "
    "it answers `503` and the method stays pending.",
    "authStepUp": "before either factor. Whatever password was sent is not verified, so no step-up "
    "failure, failed-login count, lockout or read-only downgrade is recorded",
    "redeemInvite": "before the password is hashed or the token consumed. The invite stays open",
    "confirmInvite": "No failed attempt is recorded, and the enrolment window keeps running.",
}
_OPERATION = re.compile(r"`(GET|POST|PUT|PATCH|DELETE) (/[^`]+)`")
_BULLET = re.compile(r"^- `(POST) (/[^`]+)`(.*?)(?=^- `|\Z)", re.MULTILINE | re.DOTALL)


@pytest.fixture(scope="module")
def spec() -> dict[str, Any]:
    return load_openapi_spec()


def _flat(text: str) -> str:
    """Collapse YAML and Markdown line wrapping so prose pins survive a re-wrap."""
    return " ".join(text.split())


def _response(spec: dict[str, Any], name: str = "AuthUnavailable") -> dict[str, Any]:
    response: dict[str, Any] = spec["components"]["responses"][name]
    return response


def _examples(response: dict[str, Any]) -> dict[str, Any]:
    examples: dict[str, Any] = response["content"][_PROBLEM]["examples"]
    return examples


def _example(spec: dict[str, Any]) -> dict[str, Any]:
    value: dict[str, Any] = _examples(_response(spec))["mfaUnavailable"]["value"]
    return value


def _login_503(spec: dict[str, Any]) -> dict[str, Any]:
    response: dict[str, Any] = spec["paths"]["/auth/login"]["post"]["responses"]["503"]
    return response


def _title(spec: dict[str, Any]) -> str:
    return str({e["code"]: e["title"] for e in spec["x-error-codes"]}[_CODE])


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


def _order_of_checks(spec: dict[str, Any]) -> dict[tuple[str, str], str]:
    """The "Order of checks" bullets of `AuthUnavailable`, keyed by (method, path)."""
    description = _response(spec)["description"]
    section = description[description.index("**Order of checks.**") :]
    return {
        (match.group(1).lower(), match.group(2)): _flat(match.group(3))
        for match in _BULLET.finditer(section)
    }


def _schema_doc() -> str:
    return (_PLAN / "21-database-schema.md").read_text(encoding="utf-8")


def _auth_keys_section() -> str:
    return _between(_schema_doc(), "#### 3.1.5a `auth_keys`", "\n### 3.2 ")


def test_registry_auth_unavailable_is_a_retryable_rest_only_503(spec: dict[str, Any]) -> None:
    entry = {e["code"]: e for e in spec["x-error-codes"]}[_CODE]
    assert (entry["status"], entry["retryable"]) == (503, True)
    assert entry.get("surface", ["rest"]) == ["rest"]  # MFA is a REST flow; no WS frame carries it
    meta = ERROR_META[ErrorCode(_CODE)]
    assert (meta.surfaces, meta.retryable, meta.title) == (("rest",), True, _title(spec))
    assert ErrorCode(_CODE) not in WS_ERROR_CODES


def test_title_names_no_cause(spec: dict[str, Any]) -> None:
    title = _title(spec).lower()
    assert "unavailable" in title
    for word in ("kek", "key", "loaded", "missing", "mismatch", "stranded", "version"):
        assert word not in title


def test_response_is_a_problem_with_retry_after_and_a_conforming_example(
    spec: dict[str, Any],
) -> None:
    response = _response(spec)
    assert response["headers"] == {"Retry-After": {"$ref": "#/components/headers/RetryAfter"}}
    assert response["content"][_PROBLEM]["schema"] == {"$ref": "#/components/schemas/Problem"}
    example = _example(spec)
    _conforms(spec, example, "/components/schemas/Problem")
    assert (example["code"], example["status"], example["title"]) == (_CODE, 503, _title(spec))
    assert example["type"] == f"https://candleviewer.local/errors/{_CODE}"
    assert example["retry_after_seconds"] > 0


@pytest.mark.parametrize(("method", "path"), sorted(_REF_OPERATIONS))
def test_mfa_operation_declares_the_503(spec: dict[str, Any], method: str, path: str) -> None:
    operation = spec["paths"][path][method]
    assert operation["operationId"] == _REF_OPERATIONS[(method, path)]
    assert operation["responses"]["503"] == _RESPONSE


def test_only_the_mfa_operations_use_the_response(spec: dict[str, Any]) -> None:
    users = {
        (method, path)
        for path, item in spec["paths"].items()
        for method, operation in item.items()
        if isinstance(operation, dict) and _RESPONSE in operation.get("responses", {}).values()
    }
    assert users == set(_REF_OPERATIONS)


def test_login_503_keeps_every_generic_meaning_and_adds_auth_unavailable(
    spec: dict[str, Any],
) -> None:
    login, generic = _login_503(spec), _response(spec, "ServiceUnavailable")
    assert spec["paths"]["/auth/login"]["post"]["operationId"] == "authLogin"
    assert login["headers"] == generic["headers"]
    assert login["content"][_PROBLEM]["schema"] == generic["content"][_PROBLEM]["schema"]
    description = _flat(login["description"])
    assert _flat(generic["description"]) in description  # C-6.3: the meaning does not narrow
    assert "`code: auth_unavailable` (see `AuthUnavailable`), answered only after the password" in (
        description
    )
    examples = _examples(login)
    for name, example in _examples(generic).items():
        assert examples[name] == example
    assert examples["mfaUnavailable"] == _examples(_response(spec))["mfaUnavailable"]
    assert set(examples) == {*_examples(generic), "mfaUnavailable"}


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
        "still `401 unauthenticated`. Its `503` also keeps every meaning of `ServiceUnavailable`.",
        "The answer counts, consumes and changes nothing: no session or `mfa_token` is minted, "
        "nothing is revoked, and no MFA attempt, failed-login count, lockout, recovery-code use, "
        "invite redemption or enrolment is recorded.",
        "It stores no idempotency record either, so an `Idempotency-Key` sent with it stays "
        "unused: the client may send the same request, with the same key, again after "
        "`Retry-After`, and that request is a first submission that executes once, never a replay "
        "of the `503` (no `Idempotency-Replayed`).",
        'A method this process cannot open never counts as "no method": it never leads to an '
        "enrolment-only session or a new enrolment.",
        "Users without an MFA method still sign in, and existing sessions keep working.",
        "`title` and `detail` are generic: they name no cause, key, key reference or KEK version",
        "Audited as `auth.mfa_unavailable`.",
        "The `503` comes next, before anything else is examined: no password is verified except at "
        "login, no TOTP code, recovery code or recovery-code pool is examined, and no seed is "
        "generated, opened or sealed.",
        "One confirmed TOTP method that this process cannot open is enough: a code is never "
        "checked against some of the user's methods and then answered `503`.",
    ],
)
def test_response_states_the_ruled_rule(spec: dict[str, Any], rule: str) -> None:
    assert rule in _flat(_response(spec)["description"])


def test_order_of_checks_covers_exactly_the_eight_operations(spec: dict[str, Any]) -> None:
    assert set(_order_of_checks(spec)) == set(_MFA_OPERATIONS)


@pytest.mark.parametrize(("method", "path"), sorted(_MFA_OPERATIONS))
def test_order_of_checks_places_the_503_for_the_operation(
    spec: dict[str, Any], method: str, path: str
) -> None:
    assert _ORDER[_MFA_OPERATIONS[(method, path)]] in _order_of_checks(spec)[(method, path)]


def test_step_up_decides_the_503_before_either_factor_and_says_why(spec: dict[str, Any]) -> None:
    step_up = _order_of_checks(spec)[("post", "/auth/step-up")]
    for reason in (
        "Step-up never reveals which factor failed (any wrong factor is the same "
        "`401 mfa_invalid`), and a password verified before a `503` would turn an outage into a "
        "password check for whoever holds the session.",
        "a `503` verifies no password, so there is nothing to count (ruling D4: nothing counted or "
        "consumed), as with the `challenge_id` `400`s.",
    ):
        assert reason in step_up


def test_example_detail_names_no_cause_and_no_key(spec: dict[str, Any]) -> None:
    detail = _example(spec)["detail"].lower()
    for word in ("kek", "key", "version", "missing", "mismatch", "stranded"):
        assert word not in detail


def test_schema_doc_defines_the_kek_wrapped_auth_keys_table() -> None:
    section = _auth_keys_section()
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


@pytest.mark.parametrize(
    "rule",
    [
        "each part is preceded by its length as a u16 big-endian",
        "`id` and `user_id` are the 16 raw bytes of the UUID (RFC 9562 byte order, Python "
        "`UUID.bytes`), never its text.",
        "`kek_version` is its decimal digits in ASCII, with no sign and no leading zero.",
        "`dek_ref` is `ak1:` plus the lower-case hex of `nonce(12) ‖ ciphertext(32) ‖ tag(16)` "
        "(120 hex digits)",
        "It stores `secret_key_ref = 'akey:<id>'`, the `auth_keys` row id as canonical lower-case "
        "hyphenated text (36 characters).",
        "stored as 64 lower-case hex digits (`sha256_hex`), where `user_id` is the code row's "
        "`user_id`.",
        "The normalised code is the presented code with leading and trailing whitespace stripped, "
        "then upper-cased, then with every `-` and space removed",
    ],
)
def test_schema_doc_pins_the_persisted_byte_formats(rule: str) -> None:
    assert rule in _flat(_auth_keys_section())


def test_schema_doc_states_the_auth_keys_privileges_and_triggers() -> None:
    section = _auth_keys_section()
    ddl = _flat(_between(section, "```sql", "\n```"))
    assert "updated_at timestamptz NOT NULL DEFAULT now()," in ddl
    assert (
        "CREATE TRIGGER trg_auth_keys_touch BEFORE UPDATE ON auth_keys FOR EACH ROW EXECUTE "
        "FUNCTION set_updated_at();"
    ) in ddl
    prose = _flat(section)
    for rule in (
        "After that only `dek_ref` and `kek_version` change, together, at a re-wrap",
        "refuses an UPDATE that changes `id`, `env`, `purpose`, `key_version`, `origin` or "
        "`created_at` with SQLSTATE 23514",
        "revokes DELETE on `auth_keys` from `cv_app` where the role exists",
    ):
        assert rule in prose


def test_schema_doc_names_auth_keys_in_the_kcv_and_select_star_rules() -> None:
    doc = _schema_doc()
    kcv = _flat(_between(doc, "#### 3.2.3a `kek_versions`", "```sql"))
    assert "no unrevoked `api_keys` row and no `auth_keys` row (§3.1.5a)" in kcv
    enforcement = _flat(_between(doc, "Enforcement:", "### 12.1"))
    assert "`SELECT *` on `users`, `api_keys`, `auth_keys`," in enforcement


def test_classification_fixes_the_code_hash_drift_and_classes_the_wrap() -> None:
    table = _between(_schema_doc(), "## 12. PII / secret classification per column", "### 12.1")
    code_hash = _row(table, "`recovery_codes`", "`code_hash`")
    assert code_hash[2:4] == ["S", "HMAC-SHA256 under the KEK-wrapped recovery key"]
    assert _row(table, "`auth_keys`", "`dek_ref`")[2] == "S"
    seed = _row(table, "`mfa_methods`", "`secret_enc`")
    assert seed[3] == "AES-256-GCM under the KEK-wrapped TOTP key"
    assert "never logged, snapshotted, returned or exported" in seed[4]


def test_kek_degraded_mode_lists_mfa() -> None:
    spike = (_PLAN / "spikes" / "e27-kek.md").read_text(encoding="utf-8")
    degraded = _flat(_between(spike, "## 6. Degraded mode", "\n## 7. "))
    assert (
        "MFA: the eight operations that check or seal a second factor answer "
        "`503 auth_unavailable` and count or consume nothing"
    ) in degraded


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
        "S5b removes that fallback, so from then on no environment has MFA without a keyring",
        "**Operator recovery.** S6 of #2152 owns the operator path",
    ):
        assert decision in amendment
