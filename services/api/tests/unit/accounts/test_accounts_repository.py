"""`AccountsRepository` facade against an in-memory fake `AccountsStore` (E27-T01)."""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest

from candleviewer.accounts.errors import (
    AccountConflictError,
    AccountNotFoundError,
    AccountRuleError,
    AccountScopeDeniedError,
    AccountsError,
    AccountVersionConflictError,
)
from candleviewer.accounts.models import AccountKind, ExchangeEnv, KeyStatus
from candleviewer.accounts.repository import AccountsRepository
from candleviewer.storage.repositories.accounts import (
    AccountKey,
    AccountsPage,
    AccountsStoreConflictError,
    AccountsStoreError,
    AccountsStoreRuleError,
    AccountsStoreScopeDeniedError,
    AccountsStoreStaleError,
    ApiKeyRotationRow,
    ApiKeyRow,
    ExchangeAccountPatch,
    ExchangeAccountRow,
    NewKeyRotation,
    OwnerScope,
)

_T = datetime(2026, 10, 1, tzinfo=UTC)
_S = OwnerScope(uuid4())


def _acct(**over: Any) -> ExchangeAccountRow:
    # A dict literal, not dict(...) keywords: ruff S106 reads a keyword argument ending in
    # `_token` as a password, and colour_token is only a design-system colour name.
    d: dict[str, Any] = {
        "id": uuid4(), "exchange": "x", "env": "demo", "kind": "main", "exchange_uid": "12",
        "parent_account_id": None, "label": "a", "colour_token": "accent.neutral",
        "is_enabled": True, "trading_enabled": False, "position_mode": "one_way",
        "margin_mode": "cross", "account_type": "UNIFIED", "quote_ccy": "USDT",
        "equity_cached_usd": None, "equity_cached_at": None, "max_sub_accounts_hint": 5,
        "last_reconciled_at": None, "created_at": _T, "updated_at": _T, "deleted_at": None,
    }  # fmt: skip
    d.update(over)
    return ExchangeAccountRow(**d)


def _key(snapshot: dict[str, object] | None = None) -> ApiKeyRow:
    snap = snapshot or {
        "fetched_at": "2026-10-01T00:00:00+00:00",
        "uid": "1",
        "permissions": {"ContractTrade": ["Order"]},
    }
    return ApiKeyRow(
        id=uuid4(), exchange_account_id=uuid4(), label="k", key_id_last4="abcd", kek_version=1,
        permission_snapshot=snap, permission_snapshot_at=_T, can_trade=True, can_withdraw=False,
        can_transfer=False, read_only=False, status="active", expires_at=None,
        last_used_at=None, rotation_due_at=None, created_at=_T, revoked_at=None,
    )  # fmt: skip


def _rot() -> ApiKeyRotationRow:
    return ApiKeyRotationRow(
        id=uuid4(), old_api_key_id=uuid4(), new_api_key_id=uuid4(), started_at=_T,
        validated_at=None, cutover_at=None, completed_at=None, failed_at=None,
        failure_reason=None, grace_seconds=900,
    )  # fmt: skip


class _Fake:
    """Structural `AccountsStore` (the Protocol is satisfied through `__getattr__`): every
    method returns `ret` or raises `exc`; records the last call."""

    def __init__(self, ret: Any = None, exc: Exception | None = None) -> None:
        self.ret, self.exc = ret, exc
        self.last: tuple[str, tuple[Any, ...], dict[str, Any]] | None = None

    def __getattr__(self, name: str) -> Any:
        async def call(*args: Any, **kw: Any) -> Any:
            self.last = (name, args, kw)
            if self.exc is not None:
                raise self.exc
            return self.ret

        return call


def _repo(fake: _Fake) -> AccountsRepository:
    return AccountsRepository(fake)


async def test_account_round_trip_maps_row_to_model() -> None:
    row = _acct()
    repo = _repo(_Fake(row))
    got = await repo.get_account(_S, row.id)
    assert got.id == row.id and got.env is ExchangeEnv.DEMO and got.kind is AccountKind.MAIN
    made = await repo.create_account(
        _S, id=row.id, exchange="x", env=ExchangeEnv.DEMO, kind=AccountKind.MAIN,
        exchange_uid="12", label="a",
    )  # fmt: skip
    assert made.id == row.id
    upd = await repo.update_account(_S, row.id, ExchangeAccountPatch(label="b"), if_match=_T)
    assert upd.id == row.id


async def test_list_accounts_maps_items_and_passes_enum_values() -> None:
    row = _acct()
    nxt = AccountKey(_T, row.id)
    fake = _Fake(AccountsPage((row,), nxt))
    page = await _repo(fake).list_accounts(_S, env=ExchangeEnv.LIVE, kind=AccountKind.SUB, limit=7)
    assert page.next_after == nxt and page.items[0].id == row.id
    assert fake.last is not None and fake.last[2]["env"] == "live" and fake.last[2]["kind"] == "sub"
    fake2 = _Fake(AccountsPage((), None))
    await _repo(fake2).list_accounts(_S)
    assert fake2.last is not None and fake2.last[2]["env"] is None


async def test_key_and_rotation_models_have_no_secret_fields() -> None:
    repo = _repo(_Fake(_key()))
    meta = await repo.get_key(_S, uuid4(), uuid4())
    dumped = meta.model_dump()
    for bad in ("secret_enc", "key_id_enc", "enc_nonce", "dek_ref", "enc_alg"):
        assert bad not in dumped
    assert meta.key_id_masked == "...abcd"
    keys = await _repo(_Fake((_key(),))).list_keys(_S, uuid4())
    assert len(keys) == 1
    moved = await _repo(_Fake(_key())).transition_key_status(
        _S, uuid4(), uuid4(), expected=KeyStatus.PENDING, new=KeyStatus.ACTIVE
    )
    assert moved.status is KeyStatus.ACTIVE


async def test_rotation_methods_map_rows() -> None:
    r = _rot()
    repo = _repo(_Fake(r))
    nr = NewKeyRotation(uuid4(), uuid4(), r.old_api_key_id, r.new_api_key_id)
    assert (await repo.start_rotation(_S, nr)).id == r.id
    assert (await repo.get_rotation(_S, uuid4(), r.id)).id == r.id
    assert (await repo.record_rotation_step(_S, uuid4(), r.id, "validated")).id == r.id
    many = await _repo(_Fake((r,))).list_rotations(_S, uuid4(), limit=3)
    assert many[0].id == r.id


async def test_snapshot_with_transfer_permission_fails_closed() -> None:
    bad: dict[str, object] = {
        "fetched_at": "2026-10-01T00:00:00+00:00",
        "uid": "1",
        "permissions": {"Wallet": ["AccountTransfer"]},
    }
    with pytest.raises(ValueError):
        await _repo(_Fake(_key(bad))).get_key(_S, uuid4(), uuid4())


async def test_every_none_is_the_same_not_found_with_right_entity() -> None:
    repo = _repo(_Fake(None))
    cases: list[tuple[str, Any]] = [
        ("account", repo.get_account(_S, uuid4())),
        ("account", repo.update_account(_S, uuid4(), ExchangeAccountPatch(label="b"))),
        ("key", repo.get_key(_S, uuid4(), uuid4())),
        (
            "key",
            repo.transition_key_status(
                _S, uuid4(), uuid4(), expected=KeyStatus.PENDING, new=KeyStatus.ACTIVE
            ),
        ),
        ("key", repo.start_rotation(_S, NewKeyRotation(uuid4(), uuid4(), uuid4(), uuid4()))),
        ("rotation", repo.get_rotation(_S, uuid4(), uuid4())),
        ("rotation", repo.record_rotation_step(_S, uuid4(), uuid4(), "cutover")),
    ]
    messages = set()
    for entity, coro in cases:
        with pytest.raises(AccountNotFoundError) as ei:
            await coro
        assert ei.value.entity == entity
        messages.add(str(ei.value))
    assert messages == {"not found"}


async def test_soft_delete_false_is_not_found_true_is_ok() -> None:
    await _repo(_Fake(True)).soft_delete_account(_S, uuid4())
    with pytest.raises(AccountNotFoundError):
        await _repo(_Fake(False)).soft_delete_account(_S, uuid4())


@pytest.mark.parametrize(
    ("raised", "expected"),
    [
        (AccountsStoreScopeDeniedError(), AccountScopeDeniedError),
        (AccountsStoreConflictError("ux_ea_uid"), AccountConflictError),
        (AccountsStoreRuleError("ea_uid_fmt"), AccountRuleError),
        (AccountsStoreStaleError(), AccountVersionConflictError),
        (AccountsStoreError(), AccountsError),
    ],
)
async def test_store_errors_map_to_domain_errors_for_every_method(
    raised: Exception, expected: type[Exception]
) -> None:
    repo = _repo(_Fake(exc=raised))
    nr = NewKeyRotation(uuid4(), uuid4(), uuid4(), uuid4())
    calls = [
        repo.create_account(
            _S,
            id=uuid4(),
            exchange="x",
            env=ExchangeEnv.DEMO,
            kind=AccountKind.MAIN,
            exchange_uid="1",
            label="a",
        ),
        repo.get_account(_S, uuid4()),
        repo.list_accounts(_S),
        repo.update_account(_S, uuid4(), ExchangeAccountPatch(label="b")),
        repo.soft_delete_account(_S, uuid4()),
        repo.get_key(_S, uuid4(), uuid4()),
        repo.list_keys(_S, uuid4()),
        repo.transition_key_status(
            _S, uuid4(), uuid4(), expected=KeyStatus.PENDING, new=KeyStatus.ACTIVE
        ),
        repo.start_rotation(_S, nr),
        repo.get_rotation(_S, uuid4(), uuid4()),
        repo.list_rotations(_S, uuid4()),
        repo.record_rotation_step(_S, uuid4(), uuid4(), "failed", failure_reason="x"),
    ]
    for coro in calls:
        with pytest.raises(expected) as ei:
            await coro
        assert ei.value.__cause__ is None


def test_rows_expose_no_envelope_field() -> None:
    names = {f.name for f in dataclasses.fields(ApiKeyRow)}
    assert names.isdisjoint({"secret_enc", "key_id_enc", "enc_nonce", "dek_ref", "enc_alg"})
