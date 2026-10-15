"""E27-T01 QA gap: per-table model round-trip and debounce boundaries.

There is no table repository in `accounts/` yet (`repository.py` holds only the debouncer), so
the per-table round-trip is asserted at the model boundary: dump to JSON and validate back.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

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
from candleviewer.accounts.repository import LastUsedDebouncer

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


async def test_debounce_one_write_per_window_with_fake_clock() -> None:
    writes: list[tuple[UUID, datetime]] = []

    async def writer(key: UUID, at: datetime) -> None:
        writes.append((key, at))

    deb = LastUsedDebouncer(writer, interval=timedelta(seconds=10))
    key = uuid4()
    clock = _T0
    results = []
    for _ in range(25):  # one touch per second for 25 s
        results.append(await deb.touch(key, clock))
        clock += timedelta(seconds=1)
    assert [i for i, ok in enumerate(results) if ok] == [0, 10, 20]
    assert [t for _, t in writes] == [_T0 + timedelta(seconds=s) for s in (0, 10, 20)]


async def test_debounce_boundary_just_inside_and_at_window() -> None:
    count = 0

    async def writer(key: UUID, at: datetime) -> None:
        nonlocal count
        count += 1

    deb = LastUsedDebouncer(writer, interval=timedelta(seconds=60))
    key = uuid4()
    assert await deb.touch(key, _T0)
    assert not await deb.touch(key, _T0 + timedelta(seconds=60) - timedelta(microseconds=1))
    assert count == 1
    assert await deb.touch(key, _T0 + timedelta(seconds=60))
    assert count == 2
