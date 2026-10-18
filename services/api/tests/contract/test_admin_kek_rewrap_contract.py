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


def test_operation_declares_exactly_its_statuses_rbac_and_idempotency() -> None:
    assert (_OP["operationId"], _OP["tags"]) == ("rewrapKek", ["admin"])
    assert set(SPEC["paths"][_PATH]) == {"post"}
    assert set(_OP["responses"]) == {"200", "401", "403", "409", "422", "503"}
    assert _OP["x-rbac"] == {"permissions": ["keys:manage"], "scope": "none"}
    assert _OP["x-idempotency"] == "optional"  # a re-run resumes, so no key is needed
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
        (503, "store_unavailable"),
    ):
        assert f"`{status} {code}`" in _DESC and registered[code] == status, code
    audited = "Each of these refusals is audited as `security.kek_rotation_refused`"
    assert f"{audited}, latches nothing and moves no row." in _DESC


@pytest.mark.parametrize(
    "rule",
    [
        "Only that environment's rows are read or changed; every other environment's rows and "
        "KEK lineage are untouched.",
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
