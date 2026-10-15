"""Contract (E42-T01, contract slice b): `PUT /admin/capacity/subaccount-tier` records the
system-scope setting `accounts.subaccount_tier` that `GET /admin/capacity` reports as
`SubaccountCapacity` (US-ADMIN-014: "the tier is an explicit recorded fact, never inferred").
It is owner-only (`admin:write`), CSRF-protected, takes a closed body, and is audited with an
action that exists in the audit vocabulary. The tier is committed before capacity is read, so a
failing `used` source still answers `200`; the write is visible to the next capacity read, ignores
`Idempotency-Key` and needs no step-up. `used` counts the process environment (C-2.11)."""

from __future__ import annotations

from typing import Any

import pytest
import yaml

from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.audit.actions import AUDIT_ACTIONS
from tests.contract.rbac.rbac_harness import MATRIX_PATH

_SPEC = load_openapi_spec()
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
        ("503", "#/components/responses/ServiceUnavailable"),
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


def _description() -> str:
    """The operation prose with line breaks collapsed, so a wrapped sentence still matches."""
    return " ".join(_OP["description"].split())


def test_tier_is_committed_and_audited_before_capacity_is_read() -> None:
    # A failing `used` source degrades the slice; it never un-records the tier.
    text = _description()
    assert "committed and audited before capacity is read" in text
    assert "still returns `200` with `status: error`" in text
    assert "`tier`, `cap`, `tier_source` and `recorded_at` are populated" in text


def test_a_successful_write_is_visible_to_the_next_capacity_read() -> None:
    assert "invalidates the cached `subaccounts` slice" in _description()


def test_idempotency_key_is_ignored_and_a_repeat_is_still_audited() -> None:
    assert _OP["x-idempotency"] == "ignored"
    assert "a repeat with the same tier returns `200` and is still audited" in _description()


def test_no_step_up_is_required_and_the_reason_is_stated() -> None:
    text = _description()
    assert "No step-up" in text
    assert "SR-025" in text


def test_used_counts_the_process_environment_not_a_hard_coded_live() -> None:
    # C-2.11: a demo process reports its demo sub-accounts; production is live.
    used = _SPEC["components"]["schemas"]["SubaccountCapacity"]["properties"]["used"]
    text = " ".join(used["description"].split())
    scope = "non-deleted sub-accounts in the process environment (live in production; C-2.11)"
    assert scope in text
    assert "env = live" not in text


def test_rbac_matrix_row_denies_every_non_owner() -> None:
    matrix = yaml.safe_load(MATRIX_PATH.read_text(encoding="utf-8"))
    row = matrix["operations"]["PUT /admin/capacity/subaccount-tier"]
    assert row["permissions"] == ["admin:write"]
    assert row["outcomes"] == {
        "owner": "allow",
        "manager_with_grant": "403",
        "manager_without_grant": "403",
        "viewer": "403",
        "unauthenticated": "401",
    }
