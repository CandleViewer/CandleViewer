"""Contract (#2266, PR A of the architect ruling): `POST /admin/keys/kek-rewrap` (`rewrapKek`), the
entry point of the KEK re-wrap (`docs/plan/spikes/e27-kek.md` section 5). Owner only
(`keys:manage`), step-up class `keys`; the body confirms the staged rotation boot; the answer is
counts only. Two problem codes are registered here; the `403 kek_unavailable` it cites came with
#3335. The route stays pending until the #2266 entry-point slice (D2) serves it."""

from __future__ import annotations

import json
import re
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from candleviewer.api._generated import openapi_models as api
from candleviewer.api.step_up import DANGEROUS_PATH_PATTERN
from candleviewer.auth.step_up import ACTION_CLASSES, NO_GRACE_ACTION_CLASSES
from candleviewer.ws._generated.error_codes import ERROR_META, WS_ERROR_CODES, ErrorCode
from tests.contract import _admin_support as support
from tests.contract._admin_support import ROOT, SPEC, text

_PATH = "/admin/keys/kek-rewrap"
_OP: dict[str, Any] = SPEC["paths"][_PATH]["post"]
_DESC = text(_OP["description"])
_SCHEMAS: dict[str, Any] = SPEC["components"]["schemas"]
_TESTS = ROOT / "services/api/tests"
_MATRIX = yaml.safe_load((_TESTS / "contract/rbac/matrix.yaml").read_text(encoding="utf-8"))
_ALLOWLIST = _TESTS / "unit/architecture/composition_allowlist.json"
_PENDING = json.loads(_ALLOWLIST.read_text(encoding="utf-8"))["openapi_pending"]
_SHARED = {"401": "Unauthorized", "403": "Forbidden", "422": "UnprocessableEntity"}
_SHARED |= {"503": "ServiceUnavailable"}
#: code -> retryable. Both are REST-only 409s.
_CODES = {"kek_rotation_not_staged": False, "kek_rotation_in_progress": True}
_RESULT = (
    "run_id",
    "environment",
    "from_version",
    "to_version",
    "resumed",
    "rewrapped",
    "remaining",
    "failed",
    "complete",
)
_REQUEST = SPEC["components"]["schemas"]["KekRewrapRequest"]
_BODY = _OP["requestBody"]["content"]["application/json"]
_EXAMPLES = support.example_cases([(_PATH, "post")]) + [
    (f"post request {name}", "/components/schemas/KekRewrapRequest", example["value"])
    for name, example in _BODY["examples"].items()
]
#: The terminal record waits for both kinds of row (ruling item 2; ADR-0009 Amendment 4).
_TERMINAL = (
    "a terminal `security.kek_rotated` when no unrevoked API key row and no auth keyring row of "
    "the environment is left at the previous version and no row failed, else "
    "`security.kek_rotation_incomplete`."
)
#: KekRewrapResult member -> the rows it counts, in the schema and the generated model.
_COUNTS = {
    "rewrapped": "API key rows this run moved to `to_version`.",
    "remaining": "Rows of the environment still at `from_version` after this run: unrevoked API "
    "key rows, failed rows included, plus auth keyring rows, which only the rotation boot moves.",
    "failed": "API key rows this run could not re-wrap.",
    "complete": "True when the run ended with `security.kek_rotated`: no unrevoked API key row "
    "and no auth keyring row is left at `from_version`, and no row failed.",
}


def test_operation_declares_exactly_its_statuses_rbac_and_idempotency() -> None:
    assert (_OP["operationId"], _OP["tags"]) == ("rewrapKek", ["admin"])
    assert set(SPEC["paths"][_PATH]) == {"post"}
    assert set(_OP["responses"]) == {"200", "401", "403", "409", "422", "503"}
    assert _OP["x-rbac"] == {"permissions": ["keys:manage"], "scope": "none"}
    assert _OP["x-idempotency"] == "ignored"  # a stored answer would replay a stale count
    assert _OP["parameters"] == [{"$ref": "#/components/parameters/CsrfToken"}]
    assert _OP["requestBody"]["required"] is True
    assert _BODY["schema"] == {"$ref": "#/components/schemas/KekRewrapRequest"}
    for status, name in _SHARED.items():
        assert _OP["responses"][status] == {"$ref": f"#/components/responses/{name}"}, status
    ok = _OP["responses"]["200"]["content"]["application/json"]["schema"]
    assert ok == {"$ref": "#/components/schemas/KekRewrapResult"}


def test_text_names_step_up_class_keys_only_and_the_path_is_swept() -> None:
    """The registry test reads the backticked classes; D2 registers the path with `keys`."""
    step_up = SPEC["paths"]["/auth/step-up"]["post"]["requestBody"]["content"]
    enum = step_up["application/json"]["schema"]["properties"]["action_class"]["enum"]
    named = {c for c in enum if f"`{c}`" in f"{_OP['summary']}\n{_OP['description']}"}
    assert named == {"keys"} and "keys" in ACTION_CLASSES
    assert "keys" not in NO_GRACE_ACTION_CLASSES and "no-grace" not in _OP["description"]
    cite = "(`POST /auth/step-up` defines the step-up rules)."
    assert _DESC.startswith(f"Owner only (`keys:manage`), with step-up class `keys` {cite}")
    assert DANGEROUS_PATH_PATTERN.match(_PATH)  # mounting it ungated fails the registry test


def test_operation_is_pending_and_has_its_not_mounted_rbac_matrix_row() -> None:
    key = f"POST {_PATH}"
    assert _PENDING[key]["ticket"] == "#2266"
    row = _MATRIX["operations"][key]
    assert (row["state"], row["outcomes"]) == ("not_mounted", support.OWNER_ONLY)
    assert (row["permissions"], row["scope"]) == (["keys:manage"], "none")


@pytest.mark.parametrize("code", sorted(_CODES))
def test_new_problem_codes_are_registered_rest_only_409s(code: str) -> None:
    (entry,) = [e for e in SPEC["x-error-codes"] if e["code"] == code]
    assert (entry["status"], entry["retryable"]) == (409, _CODES[code])
    assert entry.get("surface", ["rest"]) == ["rest"]
    meta = ERROR_META[ErrorCode(code)]
    assert (meta.surfaces, meta.retryable) == (("rest",), _CODES[code])
    assert ErrorCode(code) not in WS_ERROR_CODES
    assert f'"{code}"' in (ROOT / "packages/protocol/src/errorCodes.ts").read_text("utf-8")


def test_description_names_each_refusal_with_its_registered_status() -> None:
    registered = {e["code"]: e["status"] for e in SPEC["x-error-codes"]}
    for status, code in (
        (403, "kek_unavailable"),
        (409, "kek_rotation_not_staged"),
        (409, "kek_rotation_in_progress"),
        (503, "audit_unavailable"),
        (503, "store_unavailable"),
    ):
        assert f"`{status} {code}`" in _DESC and registered[code] == status, code
    audited = "Each of these refusals is audited as `security.kek_rotation_refused`"
    assert f"{audited}, latches nothing and moves no row." in _DESC
    unrecorded = "A refusal whose record cannot be written is answered `503 audit_unavailable`"
    assert f"{unrecorded} instead, and nothing is latched or moved either." in _DESC


def test_a_failed_run_tells_an_audit_outage_from_a_store_outage() -> None:
    """C-2.9: an audit outage is answered as one, never folded into `store_unavailable`."""
    assert (
        "A run that fails part-way is answered `503 audit_unavailable` when a write-ahead record "
        "(the opening, a failed-row or the terminal record) cannot be written, and "
        "`503 store_unavailable` when the credential store fails; each moved row's record shares "
        "its compare-and-set transaction, so a failure there is a store failure. Either way the "
        "rows moved so far stay moved, the latch stays, and calling again resumes." in _DESC
    )


def test_idempotency_key_is_not_used_so_a_repeat_resumes() -> None:
    assert _OP["x-idempotency"] == "ignored"
    assert (
        "`Idempotency-Key` is not used: every call reads the rows afresh, so a repeat resumes the "
        "run and never replays an earlier answer." in _DESC
    )


def test_only_the_retryable_conflict_carries_retry_after() -> None:
    conflict = _OP["responses"]["409"]
    assert conflict["headers"] == {"Retry-After": {"$ref": "#/components/headers/RetryAfter"}}
    examples = conflict["content"]["application/problem+json"]["examples"]
    assert examples["inProgress"]["value"]["retry_after_seconds"] >= 1
    assert "retry_after_seconds" not in examples["notStaged"]["value"]
    assert (
        "Only `kek_rotation_in_progress` carries `Retry-After` and `retry_after_seconds`; no wait "
        "clears `kek_rotation_not_staged`." in text(conflict["description"])
    )


def test_not_staged_is_cleared_by_a_corrected_body_or_a_staged_restart() -> None:
    """Each cause of `kek_rotation_not_staged` has its own remedy; neither is a wait."""
    conflict = text(_OP["responses"]["409"]["description"])
    assert (
        "When the body differs from the boot, a corrected body clears it; when no previous KEK "
        "is loaded, only a restart into the staged boot does." in conflict
    )
    assert "a restart, not a wait" not in conflict
    cause = "`409 kek_rotation_not_staged` when no previous KEK is loaded or the body differs"
    assert f"{cause} from the boot" in _DESC


@pytest.mark.parametrize(
    "rule",
    [
        "Only that environment's rows are read or changed; every other environment's rows and "
        "KEK lineage are untouched.",
        "An API key row that is revoked (`revoked_at` set or status `revoked`) is never "
        "re-wrapped, and a key revoked while the run is under way is fenced too, unless its row "
        "has already moved. A fenced row stays at the previous version, is not counted in "
        "`remaining`, and becomes unreadable once that version is destroyed.",
        "Before the first row, the call latches order entry read-only (gate reason "
        "`secrets.kek_rotation`), and only the restart that ends the rotation clears the latch.",
        "cancels and stop-loss amendments keep signing (C-2.6)",
        "each moved row writes its `security.credential_rewrapped` record in the same transaction",
        "Every record of a run carries its `run_id` and the acting Owner, and none carries key "
        "material.",
        "The response holds counts only: no key id and no key check value (KCV).",
    ],
)
def test_description_states_the_ruled_rule(rule: str) -> None:
    assert rule in _DESC


def _assert_result_member_says(name: str, rule: str) -> None:
    schema = _SCHEMAS["KekRewrapResult"]["properties"][name]["description"]
    generated = api.KekRewrapResult.model_fields[name].description or ""
    assert rule in text(schema) and rule in text(generated), name


def test_revoked_rows_neither_move_nor_hold_back_completion() -> None:
    """Ruling item 2 (the round-5 fence): nothing revoked is re-wrapped to reach `complete`, so
    destroying the previous KEK still makes every revoked credential unreadable."""
    scope = (
        "every API key of `environment` that is not revoked and whose data-encryption key (DEK) "
        "is wrapped under the previous KEK version (`to_version - 1`) is re-wrapped under "
        "`to_version`."
    )
    assert scope in _DESC and _TERMINAL in _DESC
    for name in ("remaining", "complete"):
        _assert_result_member_says(name, _COUNTS[name])


def test_auth_keyring_rows_hold_back_completion_and_move_only_at_the_rotation_boot() -> None:
    """ADR-0009 Amendment 4 (#2152): M2 re-wraps the environment's `auth_keys` rows at the
    rotation boot, and `security.kek_rotated` waits until none is left at the previous version
    (`docs/plan/spikes/e27-kek.md` section 5)."""
    boot = (
        "The environment's auth keyring rows (`auth_keys`) are not re-wrapped here: M2 re-wraps "
        "them at the rotation boot (ADR-0009 Amendment 4, #2152). The call counts them, and the "
        "rotation is complete only once none of them is left at the previous version."
    )
    assert boot in _DESC and _TERMINAL in _DESC
    assert (
        "Calling again moves API key rows only: an auth keyring row left at `from_version` "
        "moves at the next rotation boot (ADR-0009 Amendment 4)."
        in text(_OP["responses"]["200"]["description"])
    )
    for name, rule in _COUNTS.items():
        _assert_result_member_says(name, rule)


def test_resumed_is_true_only_when_an_earlier_run_moved_rows_and_rows_are_left() -> None:
    """The ruling's opening record: `kek_rotation_resumed` only if rows are left and an earlier
    run moved some, else `kek_rotation_started` (an abort that moved no row reads as started)."""
    opening = (
        "The opening record is `security.kek_rotation_resumed` (`resumed: true`) only when an "
        "earlier run had already moved rows and unrevoked API key rows are still left at the "
        "previous version; otherwise it is `security.kek_rotation_started` (`resumed: false`), "
        "so a run after an earlier one that moved no row, or after the last row moved, reads as "
        "started."
    )
    assert opening in _DESC and "resumes (`resumed: true`)" not in _DESC
    _assert_result_member_says(
        "resumed",
        "True when this run opened with `security.kek_rotation_resumed`: an earlier run had "
        "already moved rows of this rotation and unrevoked API key rows were still left at "
        "`from_version`. False when it opened with `security.kek_rotation_started`: no earlier "
        "run had moved a row, or no row was left to move.",
    )


def test_request_confirms_the_boot_and_forbids_any_other_member() -> None:
    assert _REQUEST["additionalProperties"] is False
    assert _REQUEST["required"] == ["environment", "to_version"] == list(_REQUEST["properties"])
    env = _REQUEST["properties"]["environment"]
    assert env == {"$ref": "#/components/schemas/Environment"}
    version = _REQUEST["properties"]["to_version"]
    assert (version["type"], version["minimum"], version["maximum"]) == ("integer", 2, 2**31 - 1)
    api.KekRewrapRequest.model_validate({"environment": "demo", "to_version": 2})
    for bad in (
        {"environment": "demo", "to_version": 1},
        {"environment": "mainnet", "to_version": 2},
        {"environment": "demo"},
        {"environment": "demo", "to_version": 2, "from_version": 1},
    ):
        with pytest.raises(ValidationError):
            api.KekRewrapRequest.model_validate(bad)


def test_result_is_counts_only() -> None:
    result = _SCHEMAS["KekRewrapResult"]
    assert result["additionalProperties"] is False
    assert tuple(result["required"]) == _RESULT
    assert set(result["properties"]) == set(_RESULT) == set(api.KekRewrapResult.model_fields)
    assert not [name for name in _RESULT if re.search(r"key|kcv", name)]
    for count in ("rewrapped", "remaining", "failed"):
        bounds = {k: v for k, v in result["properties"][count].items() if k != "description"}
        assert bounds == {"type": "integer", "minimum": 0}, count
    value = _OP["responses"]["200"]["content"]["application/json"]["examples"]["complete"]
    with pytest.raises(ValidationError):
        api.KekRewrapResult.model_validate({**value["value"], "key_ids": []})


@pytest.mark.parametrize("name", ["notStaged", "inProgress"])
def test_conflict_examples_carry_their_registered_code_title_and_status(name: str) -> None:
    body = _OP["responses"]["409"]["content"]["application/problem+json"]
    value = body["examples"][name]["value"]
    (entry,) = [e for e in SPEC["x-error-codes"] if e["code"] == value["code"]]
    assert value["code"] in _CODES and (value["status"], value["title"]) == (409, entry["title"])
    assert value["type"] == f"https://candleviewer.local/errors/{value['code']}"


@pytest.mark.parametrize(("case", "pointer", "value"), _EXAMPLES, ids=[c[0] for c in _EXAMPLES])
def test_every_example_validates_against_its_schema(case: str, pointer: str, value: Any) -> None:
    support.validate_example(pointer, value)
