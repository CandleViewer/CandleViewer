"""C-2.8 / SR-030a: withdraw and transfer rights are refused in the value-in-group shape (#2240).

Before #2240, `PermissionSnapshot` only looked at a top-level `Withdraw` group, so
`"Wallet": ["AccountTransfer"]` passed. The refused-case tests below fail on that code.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from candleviewer.accounts._permissions import FORBIDDEN_TOKENS, reject_withdraw
from candleviewer.accounts.errors import WithdrawPermissionError
from candleviewer.accounts.models import PermissionSet, PermissionSnapshot
from tests.unit.accounts._permission_cases import (
    ALLOWED,
    REFUSED,
    SR030A_WALLET_RIGHTS,
    Case,
    non_json_cases,
)

_NON_JSON_IDS = [name for name, _ in non_json_cases()]


def _perms(cases: list[Case]) -> pytest.MarkDecorator:
    return pytest.mark.parametrize("permissions", [c[1] for c in cases], ids=[c[0] for c in cases])


def _non_json() -> pytest.MarkDecorator:
    return pytest.mark.parametrize(
        "permissions", [p for _, p in non_json_cases()], ids=_NON_JSON_IDS
    )


def _snapshot(permissions: object) -> PermissionSnapshot:
    return PermissionSnapshot.model_validate(
        {
            "fetched_at": datetime(2026, 9, 14, tzinfo=UTC),
            "uid": "1000001",
            "permissions": permissions,
        }
    )


@_perms(ALLOWED)
def test_reject_withdraw_allows_grant_free_permissions(permissions: dict[str, Any]) -> None:
    reject_withdraw(permissions)


@_perms(REFUSED)
def test_reject_withdraw_refuses_withdraw_and_transfer_rights(permissions: dict[str, Any]) -> None:
    with pytest.raises(WithdrawPermissionError, match="key_withdraw_permission"):
        reject_withdraw(permissions)


@_non_json()
def test_reject_withdraw_fails_closed_on_non_json(permissions: dict[str, Any]) -> None:
    with pytest.raises(WithdrawPermissionError, match="key_withdraw_permission"):
        reject_withdraw(permissions)


def test_forbidden_tokens_are_the_c28_rights() -> None:
    assert FORBIDDEN_TOKENS == ("withdraw", "transfer")


@_perms(ALLOWED)
def test_snapshot_accepts_grant_free_permissions(permissions: dict[str, Any]) -> None:
    assert _snapshot(permissions).uid == "1000001"


@_perms(REFUSED)
def test_snapshot_refuses_withdraw_and_transfer_rights(permissions: dict[str, Any]) -> None:
    with pytest.raises(ValidationError, match="key_withdraw_permission"):
        _snapshot(permissions)


@pytest.mark.parametrize("right", SR030A_WALLET_RIGHTS)
def test_snapshot_refuses_right_listed_inside_wallet_group(right: str) -> None:
    with pytest.raises(ValidationError, match="key_withdraw_permission"):
        _snapshot({"ContractTrade": ["Order", "Position"], "Wallet": [right], "Withdraw": []})


@_non_json()
def test_snapshot_fails_closed_on_non_json_before_coercion(permissions: dict[str, Any]) -> None:
    with pytest.raises(ValidationError, match="key_withdraw_permission"):
        _snapshot(permissions)


def test_snapshot_checks_a_prebuilt_permission_set() -> None:
    with pytest.raises(ValidationError, match="key_withdraw_permission"):
        _snapshot(PermissionSet(Wallet=("AccountTransfer",)))


def test_snapshot_refuses_non_object_permissions() -> None:
    with pytest.raises(ValidationError, match="permissions"):
        _snapshot(["Order"])
