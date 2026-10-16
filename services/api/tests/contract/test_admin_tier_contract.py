"""Contract (E42-T01, contract slice b): `PUT /admin/capacity/subaccount-tier` records the
system-scope setting `accounts.subaccount_tier` that `GET /admin/capacity` reports as
`SubaccountCapacity` (US-ADMIN-014: "the tier is an explicit recorded fact, never inferred").
It is owner-only (`admin:write`), CSRF-protected, takes a closed body, and is audited with an
action that exists in the audit vocabulary. The tier is committed before capacity is read, so a
failing `used` source still answers `200`; the write is visible to the next capacity read, ignores
`Idempotency-Key` and needs no step-up. `used` counts the process environment, `CV_ENV` (C-2.11).
The prose is pinned by whole sentences, so a negated or truncated one fails."""

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
_USED: dict[str, Any] = _SPEC["components"]["schemas"]["SubaccountCapacity"]["properties"]["used"]


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


def _prose(text: str) -> str:
    """Prose with line breaks collapsed, so a wrapped sentence still matches."""
    return " ".join(text.split())


def _states(prose: str, sentence: str) -> bool:
    """True when `prose` holds `sentence` whole and as a sentence of its own. A fragment does not
    count: "never invalidates the cache" must not satisfy "invalidates the cache"."""
    return prose.startswith(sentence) or f". {sentence}" in prose


def _description() -> str:
    return _prose(_OP["description"])


def test_tier_is_committed_and_audited_before_capacity_is_read() -> None:
    # A failing `used` source degrades the slice; it never un-records the tier.
    text = _description()
    assert _states(text, "The tier is committed and audited before capacity is read.")
    assert _states(
        text,
        "If the `used` source then fails, the call still returns `200` with `status: error`, "
        "and `tier`, `cap`, `tier_source` and `recorded_at` are populated.",
    )


def test_a_failing_store_answers_503_and_changes_nothing() -> None:
    text = _description()
    assert _states(
        text,
        "`503 store_unavailable` when storage fails: the tier is unchanged and no "
        "`settings.change` row is written.",
    )
    assert _states(text, "Its `detail` is a fixed reason, never the driver error.")


def test_a_successful_write_is_visible_to_the_next_capacity_read() -> None:
    assert _states(
        _description(),
        "A successful write invalidates the cached `subaccounts` slice, so the next "
        "`GET /admin/capacity` shows the new tier at once (E42-T01 AC3).",
    )


def test_idempotency_key_is_ignored_and_a_repeat_is_still_audited() -> None:
    assert _OP["x-idempotency"] == "ignored"
    assert _states(
        _description(),
        "`Idempotency-Key` is not used: a repeat with the same tier returns `200` and is still "
        "audited (before == after).",
    )


def test_no_step_up_is_required_and_the_reason_is_stated() -> None:
    # SR-E27-02 *requires* step-up on `createExchangeAccount` but does not enforce it yet (the
    # route is not in DANGEROUS_ROUTES), so the contract must say "requires", not "is gated".
    assert _states(
        _description(),
        "No step-up: `admin:write` is not an SR-025 action class, and a higher tier only widens a "
        "local cap on `createExchangeAccount`, which SR-E27-02 requires to be step-up gated; its "
        "accounts are inert until keys are attached via the step-up-gated key routes (SR-025).",
    )


def test_used_counts_the_process_environment_not_a_hard_coded_live() -> None:
    # C-2.11: a demo process reports its demo sub-accounts; production is live.
    text = _prose(_USED["description"])
    assert _states(
        text,
        "Most non-deleted sub-accounts in the process environment (live in production; C-2.11) "
        "under any one main account (`exchange_accounts.kind = sub`): the cap binds exchange "
        "UIDs, per main.",
    )
    assert "env = live" not in text


def test_the_process_environment_is_cv_env_not_the_session_switch() -> None:
    assert _states(
        _prose(_USED["description"]),
        "The process environment is `CV_ENV`, the process-scope key (`20-architecture.md` §7.2), "
        "not the per-session `/session/environment` switch.",
    )


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
