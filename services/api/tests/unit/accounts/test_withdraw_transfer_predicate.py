"""C-2.8 / SR-030a: withdraw and transfer rights are refused in the value-in-group shape (#2240).

Before #2240, `PermissionSnapshot` only looked at a top-level `Withdraw` group, so
`"Wallet": ["AccountTransfer"]` passed. The refused-case tests below fail on that code.

Shape source: Bybit v5 "Get API Key Information" (`GET /v5/user/query-api`,
https://bybit-exchange.github.io/docs/v5/user/apikey-info) returns the key's `permissions` as
groups whose values are the granted rights; SR-030a names the `Wallet` rights to refuse:
`AccountTransfer`, `SubMemberTransfer`, `Withdraw`. No recorded, redacted capture exists yet, so
the cases in `_permission_cases.py` are structural.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from pydantic import BaseModel, ConfigDict, ValidationError

from candleviewer.accounts._permissions import FORBIDDEN_TOKENS, reject_withdraw
from candleviewer.accounts.errors import WithdrawPermissionError
from candleviewer.accounts.models import ApiKeyMetadata, PermissionSet, PermissionSnapshot
from tests.unit.accounts._permission_cases import (
    ALLOWED,
    EXACT_WITHDRAW,
    KNOWN_GAPS,
    REFUSED,
    SR030A_WALLET_RIGHTS,
    Case,
    non_json_cases,
)

_NOW = datetime(2026, 9, 14, tzinfo=UTC)
_NON_JSON_IDS = [name for name, _ in non_json_cases()]


def _perms(cases: list[Case]) -> pytest.MarkDecorator:
    return pytest.mark.parametrize("permissions", [c[1] for c in cases], ids=[c[0] for c in cases])


def _non_json() -> pytest.MarkDecorator:
    return pytest.mark.parametrize(
        "permissions", [p for _, p in non_json_cases()], ids=_NON_JSON_IDS
    )


def _snapshot(permissions: object) -> PermissionSnapshot:
    return PermissionSnapshot.model_validate(
        {"fetched_at": _NOW, "uid": "1000001", "permissions": permissions}
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


def test_snapshot_accepts_a_prebuilt_clean_permission_set() -> None:
    snapshot = _snapshot(PermissionSet(ContractTrade=("Order", "Position")))
    assert snapshot.permissions.ContractTrade == ("Order", "Position")


def test_snapshot_refuses_non_object_permissions() -> None:
    with pytest.raises(ValidationError, match="key_withdraw_permission"):
        _snapshot(["Order"])


def _allows(permissions: dict[str, Any]) -> bool:
    try:
        reject_withdraw(permissions)
    except WithdrawPermissionError:
        return False
    return True


@pytest.mark.parametrize(
    ("permissions", "predicate_allows"),
    [(c[1], c[2]) for c in EXACT_WITHDRAW],
    ids=[c[0] for c in EXACT_WITHDRAW],
)
def test_reject_withdraw_exempts_only_null_and_empty_on_the_legacy_withdraw_key(
    permissions: dict[str, Any], predicate_allows: bool
) -> None:
    assert _allows(permissions) is predicate_allows


@pytest.mark.parametrize(
    ("permissions", "model_error"),
    [(c[1], c[3]) for c in EXACT_WITHDRAW],
    ids=[c[0] for c in EXACT_WITHDRAW],
)
def test_snapshot_refuses_every_non_list_legacy_withdraw_group(
    permissions: dict[str, Any], model_error: str
) -> None:
    with pytest.raises(ValidationError, match=model_error):
        _snapshot(permissions)


@_perms(KNOWN_GAPS)
def test_deny_list_gaps_pass_the_predicate_and_the_model_alike(
    permissions: dict[str, Any],
) -> None:
    reject_withdraw(permissions)
    assert _snapshot(permissions).uid == "1000001"


@dataclass(frozen=True)
class _SnapshotRow:
    """An attribute object (adapter DTO, ORM row) read with `from_attributes=True`."""

    fetched_at: datetime
    uid: str
    permissions: object


def _from_attributes(permissions: object) -> PermissionSnapshot:
    row = _SnapshotRow(_NOW, "1000001", permissions)
    return PermissionSnapshot.model_validate(row, from_attributes=True)


@_perms(ALLOWED)
def test_snapshot_from_attributes_accepts_grant_free_permissions(
    permissions: dict[str, Any],
) -> None:
    assert _from_attributes(permissions).uid == "1000001"


@_perms(REFUSED)
def test_snapshot_from_attributes_refuses_withdraw_and_transfer_rights(
    permissions: dict[str, Any],
) -> None:
    with pytest.raises(ValidationError, match="key_withdraw_permission"):
        _from_attributes(permissions)


@pytest.mark.parametrize(
    "permissions",
    [SimpleNamespace(Wallet=("AccountTransfer",)), SimpleNamespace(Withdraw=("Withdraw",))],
    ids=["wallet_right", "withdraw_group"],
)
def test_snapshot_refuses_rights_on_attribute_object_permissions(permissions: object) -> None:
    with pytest.raises(ValidationError, match="key_withdraw_permission"):
        PermissionSnapshot.model_validate(
            {"fetched_at": _NOW, "uid": "1000001", "permissions": permissions},
            from_attributes=True,
        )


class _ForeignPermissions(BaseModel):
    """Another module's model: pydantic keeps its extra groups as attributes."""

    model_config = ConfigDict(extra="allow")


@dataclass(frozen=True)
class _PermissionsRow:
    ContractTrade: tuple[str, ...]
    FiatP2P: tuple[str, ...]  # not a PermissionSet group


@pytest.mark.parametrize(
    "permissions",
    [
        SimpleNamespace(Earn=["Withdraw"]),
        _PermissionsRow(ContractTrade=("Order",), FiatP2P=("Transfer",)),
        _ForeignPermissions.model_validate({"Earn": ["Withdraw"]}),
    ],
    ids=["namespace_extra_group", "dataclass_extra_group", "foreign_model_extra_group"],
)
def test_snapshot_refuses_attribute_permissions_whose_groups_would_be_dropped(
    permissions: object,
) -> None:
    """`from_attributes` reads only the declared groups, so an undeclared one would vanish
    unchecked; attribute-object permissions therefore fail closed."""
    with pytest.raises(ValidationError, match="key_withdraw_permission"):
        PermissionSnapshot.model_validate(
            {"fetched_at": _NOW, "uid": "1000001", "permissions": permissions},
            from_attributes=True,
        )


def test_api_key_metadata_from_attributes_checks_the_snapshot() -> None:
    row = SimpleNamespace(
        id=uuid4(),
        exchange_account_id=uuid4(),
        label="k",
        key_id_last4="AbC1",
        permission_snapshot=_SnapshotRow(_NOW, "1000001", {"Wallet": ["SubMemberTransfer"]}),
        permission_snapshot_at=_NOW,
        created_at=_NOW,
    )
    with pytest.raises(ValidationError, match="key_withdraw_permission"):
        ApiKeyMetadata.model_validate(row, from_attributes=True)
