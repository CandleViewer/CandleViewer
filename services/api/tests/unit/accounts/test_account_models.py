"""E27-T01 domain models and debounce."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from candleviewer.accounts.models import (
    ApiKeyMetadata,
    ApiKeyRotation,
    ExchangeAccount,
    PermissionSnapshot,
)
from candleviewer.accounts.repository import LastUsedDebouncer

_FX = Path(__file__).resolve().parents[5] / "packages/fixtures/accounts/accounts.json"
_NOW = datetime(2026, 9, 14, tzinfo=UTC)
_SECRET = {"secret_enc", "key_id_enc", "enc_nonce", "dek_ref"}


def _fixtures() -> list[dict[str, Any]]:
    return json.loads(_FX.read_text())["accounts"]  # type: ignore[no-any-return]


def _account(row: dict[str, Any]) -> ExchangeAccount:
    keys = {"id", "env", "kind", "exchange_uid", "parent_account_id", "label"}
    return ExchangeAccount(**{k: row[k] for k in keys}, created_at=_NOW, updated_at=_NOW)


def _key(snapshot: dict[str, Any], **kw: Any) -> ApiKeyMetadata:
    return ApiKeyMetadata(
        id=uuid4(),
        exchange_account_id=uuid4(),
        label="k",
        key_id_last4="AbC1",
        permission_snapshot=PermissionSnapshot(**snapshot),
        permission_snapshot_at=_NOW,
        created_at=_NOW,
        **kw,
    )


def test_fixtures_load_and_are_compliant() -> None:
    rows = _fixtures()
    assert [(r["kind"], r["env"]) for r in rows] == [
        ("main", "live"),
        ("sub", "live"),
        ("main", "demo"),
    ]
    for row in rows:
        _account(row)
        assert PermissionSnapshot(**row["permission_snapshot"]).permissions.Withdraw == ()


def test_models_never_expose_secret_columns() -> None:
    acct = _account(_fixtures()[0]).model_dump()
    key = _key(_fixtures()[0]["permission_snapshot"]).model_dump()
    assert not _SECRET & set(acct)
    assert not _SECRET & set(key)
    assert not _SECRET & set(ApiKeyMetadata.model_fields)


def test_snapshot_rejects_withdraw() -> None:
    snap = _fixtures()[0]["permission_snapshot"]
    snap["permissions"]["Withdraw"] = ["Withdraw"]
    with pytest.raises(ValidationError, match="key_withdraw_permission"):
        PermissionSnapshot(**snap)


def test_account_parent_shape_and_utc() -> None:
    row = _fixtures()[1]
    with pytest.raises(ValidationError):
        _account({**row, "parent_account_id": None})
    with pytest.raises(ValidationError):
        _account({**_fixtures()[0], "parent_account_id": str(uuid4())})
    with pytest.raises(ValidationError):
        ExchangeAccount(**{**_account(row).model_dump(), "created_at": datetime(2026, 1, 1)})
    with pytest.raises(ValidationError):
        ExchangeAccount(**{**_account(row).model_dump(), "id": row["parent_account_id"]})


def test_key_readonly_excl_and_withdraw_flag() -> None:
    snap = _fixtures()[0]["permission_snapshot"]
    with pytest.raises(ValidationError):
        _key(snap, read_only=True, can_trade=True)
    with pytest.raises(ValidationError):
        _key(snap, can_withdraw=True)
    assert _key(snap).key_id_masked == "...AbC1"


def test_rotation_validators() -> None:
    a, b = uuid4(), uuid4()
    ok = ApiKeyRotation(id=uuid4(), old_api_key_id=a, new_api_key_id=b, started_at=_NOW)
    assert ok.grace_seconds == 900
    with pytest.raises(ValidationError):
        ApiKeyRotation(id=uuid4(), old_api_key_id=a, new_api_key_id=a, started_at=_NOW)
    with pytest.raises(ValidationError):
        ApiKeyRotation(
            id=uuid4(),
            old_api_key_id=a,
            new_api_key_id=b,
            started_at=_NOW,
            completed_at=_NOW,
            failed_at=_NOW,
        )


async def test_last_used_debounce_window() -> None:
    writes: list[tuple[UUID, datetime]] = []

    async def writer(k: UUID, t: datetime) -> None:
        writes.append((k, t))

    deb = LastUsedDebouncer(writer)
    k = uuid4()
    assert await deb.touch(k, _NOW)
    assert not await deb.touch(k, _NOW + timedelta(seconds=59))
    assert await deb.touch(k, _NOW + timedelta(seconds=60))
    assert await deb.touch(uuid4(), _NOW)
    assert len(writes) == 3
    with pytest.raises(ValueError, match="timezone"):
        await deb.touch(k, datetime(2026, 1, 1))
