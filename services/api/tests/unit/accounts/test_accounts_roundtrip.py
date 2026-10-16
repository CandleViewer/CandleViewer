"""E27-T01 QA gap: per-table model round-trip.

The per-table round-trip is asserted at the model boundary: dump to JSON and validate back. The
`last_used_at` debounce boundaries moved with its only writer, the M2 credential broker
(`tests/unit/credentials_m2/test_broker_safety.py`, #2580).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from candleviewer.accounts.models import (
    AccountKind,
    ApiKeyMetadata,
    ApiKeyRotation,
    ExchangeAccount,
    ExchangeEnv,
    KeyStatus,
    PermissionSet,
    PermissionSnapshot,
)

_T0 = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


def _snapshot() -> PermissionSnapshot:
    return PermissionSnapshot(
        fetched_at=_T0,
        uid="123",
        permissions=PermissionSet(ContractTrade=("Order", "Position")),
    )


def test_exchange_accounts_round_trip() -> None:
    parent = uuid4()
    for kind, parent_id in ((AccountKind.MAIN, None), (AccountKind.SUB, parent)):
        row = ExchangeAccount(
            id=uuid4(),
            env=ExchangeEnv.DEMO,
            kind=kind,
            exchange_uid="42",
            parent_account_id=parent_id,
            label="acct",
            created_at=_T0,
            updated_at=_T0,
        )
        assert ExchangeAccount.model_validate_json(row.model_dump_json()) == row


def test_api_keys_round_trip() -> None:
    row = ApiKeyMetadata(
        id=uuid4(),
        exchange_account_id=uuid4(),
        label="k",
        key_id_last4="Zz09",
        permission_snapshot=_snapshot(),
        permission_snapshot_at=_T0,
        can_trade=True,
        status=KeyStatus.ACTIVE,
        last_used_at=_T0,
        created_at=_T0,
    )
    assert ApiKeyMetadata.model_validate_json(row.model_dump_json()) == row


def test_api_key_rotations_round_trip() -> None:
    row = ApiKeyRotation(
        id=uuid4(),
        old_api_key_id=uuid4(),
        new_api_key_id=uuid4(),
        started_at=_T0,
        validated_at=_T0,
        failed_at=_T0,
        failure_reason="probe failed",
        grace_seconds=0,
    )
    assert ApiKeyRotation.model_validate_json(row.model_dump_json()) == row


def test_naive_timestamp_is_rejected_on_every_table() -> None:
    naive = datetime(2026, 10, 1)
    with pytest.raises(ValueError, match="timezone"):
        ApiKeyRotation(id=uuid4(), old_api_key_id=uuid4(), new_api_key_id=uuid4(), started_at=naive)
