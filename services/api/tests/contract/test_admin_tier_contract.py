"""Contract (E42-T01, contract slice b): `PUT /admin/capacity/subaccount-tier` records the
system-scope setting `accounts.subaccount_tier` that `GET /admin/capacity` reports as
`SubaccountCapacity` (US-ADMIN-014: "the tier is an explicit recorded fact, never inferred").
It is owner-only (`admin:write`), CSRF-protected, takes a closed body, and is audited with an
action that exists in the audit vocabulary."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.audit.actions import AUDIT_ACTIONS

_SPEC = load_openapi_spec()
_MATRIX_PATH = Path(__file__).parent / "rbac" / "matrix.yaml"
_OP: dict[str, Any] = _SPEC["paths"]["/admin/capacity/subaccount-tier"]["put"]
_BODY = _OP["requestBody"]["content"]["application/json"]


def test_operation_is_owner_only_with_no_account_scope() -> None:
    assert _OP["operationId"] == "setSubaccountTier"
    assert _OP["x-rbac"] == {"permissions": ["admin:write"], "scope": "none"}


def test_operation_requires_the_csrf_token() -> None:
    assert {"$ref": "#/components/parameters/CsrfToken"} in _OP["parameters"]


def test_body_is_closed_and_only_records_a_known_tier() -> None:
    assert _OP["requestBody"]["required"] is True
    assert _BODY["schema"] == {
        "type": "object",
        "additionalProperties": False,
        "required": ["tier"],
        "properties": {"tier": {"type": "string", "enum": ["regular", "business_kyc"]}},
    }
    assert _BODY["examples"]["businessKyc"]["value"] == {"tier": "business_kyc"}


@pytest.mark.parametrize(
    ("status", "ref"),
    [
        ("200", None),
        ("401", "#/components/responses/Unauthorized"),
        ("403", "#/components/responses/Forbidden"),
        ("422", "#/components/responses/UnprocessableEntity"),
    ],
)
def test_responses_follow_the_contract_conventions(status: str, ref: str | None) -> None:
    response = _OP["responses"][status]
    if ref is None:
        schema = response["content"]["application/json"]["schema"]
        assert schema == {"$ref": "#/components/schemas/SubaccountCapacity"}
    else:
        assert response == {"$ref": ref}


def test_tier_change_is_audited_with_an_existing_action() -> None:
    assert "`settings.change`" in _OP["description"]
    assert "settings.change" in AUDIT_ACTIONS


def test_rbac_matrix_row_denies_every_non_owner() -> None:
    matrix = yaml.safe_load(_MATRIX_PATH.read_text(encoding="utf-8"))
    row = matrix["operations"]["PUT /admin/capacity/subaccount-tier"]
    assert row["permissions"] == ["admin:write"]
    assert row["outcomes"] == {
        "owner": "allow",
        "manager_with_grant": "403",
        "manager_without_grant": "403",
        "viewer": "403",
        "unauthenticated": "401",
    }
