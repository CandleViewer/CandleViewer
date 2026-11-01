"""`SqlAlchemyKeySelfCheckStore` (E27-T03, #836) against a recording unit of work.

Real-SQL behaviour (`cidr[]`, the jsonb merge, the constraints) is covered by
`tests/integration/storage/test_accounts_store_pg.py` (CI only).
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID

import pytest
import sqlalchemy as sa

from candleviewer.storage.repositories import key_selfcheck_sqlalchemy as mod
from candleviewer.storage.repositories.accounts import (
    AccountsStoreError,
    InvalidKey,
    PolicyDisarm,
    VerifiedKey,
)
from candleviewer.storage.repositories.key_selfcheck_sqlalchemy import SqlAlchemyKeySelfCheckStore
from tests.unit.credentials_m2._write_once import writes_to

T = datetime(2026, 10, 16, tzinfo=UTC)
KEY, ACCT = UUID(int=11), UUID(int=1)
ROW = {
    "key_id": str(KEY), "read_only": False, "verified_at": T, "last_error_code": "key_expired",
    "expires_at": T, "key_status": "rotating", "key_created_at": T, "id": str(ACCT),
    "exchange": "bybit", "env": "live", "kind": "main", "exchange_uid": "1",
    "parent_account_id": None, "label": "a", "colour_token": "c", "is_enabled": True,
    "trading_enabled": True, "position_mode": "one_way", "margin_mode": "cross",
    "account_type": "UNIFIED", "quote_ccy": "USDT", "equity_cached_usd": None,
    "equity_cached_at": None, "max_sub_accounts_hint": 5, "last_reconciled_at": None,
    "created_at": T, "updated_at": T, "deleted_at": None,
}  # fmt: skip
STATEMENTS = (
    mod._TARGETS, mod._PASS, mod._ERROR, mod._DISABLE, mod._OWED, mod._AUDITED, mod._RETIRE,
    mod._INVALID,
)  # fmt: skip
RULE = "key_withdraw_permission"


class _Rel:
    def __init__(self, rows: list[dict[str, Any]] | None = None, rowcount: int = 1) -> None:
        self.rows, self.rowcount = rows or [], rowcount
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.commits = 0

    @asynccontextmanager
    async def unit_of_work(self) -> AsyncIterator[Any]:
        async def execute(stmt: sa.TextClause, params: dict[str, Any]) -> Any:
            self.calls.append((stmt.text, params))
            return SimpleNamespace(mappings=lambda: self.rows, rowcount=self.rowcount)

        async def commit() -> None:
            self.commits += 1

        yield SimpleNamespace(session=SimpleNamespace(execute=execute), commit=commit)


def _store(rel: _Rel, env: str = "demo") -> SqlAlchemyKeySelfCheckStore:
    return SqlAlchemyKeySelfCheckStore(cast(Any, rel), env=env)


def test_an_unknown_environment_is_refused() -> None:
    with pytest.raises(ValueError, match="unknown env"):
        _store(_Rel(), env="prod")


async def test_targets_are_read_for_the_bound_environment_only() -> None:
    rel = _Rel([ROW, {**ROW, "key_id": str(UUID(int=12)), "parent_account_id": str(ACCT)}])
    first, second = await _store(rel, "live").targets()
    assert (first.key_id, first.read_only, first.verified_at) == (KEY, False, T)
    assert (first.last_error_code, first.expires_at) == ("key_expired", T)  # decision 3, SR-034
    assert (first.status, first.created_at) == ("rotating", T)  # key age (#837)
    assert "k.status::text AS key_status, k.created_at AS key_created_at" in mod._TARGETS.text
    assert (first.account.id, first.account.trading_enabled, second.account.parent_account_id) == (
        ACCT, True, ACCT,
    )  # fmt: skip
    assert rel.calls == [(mod._TARGETS.text, {"env": "live", "cap": mod.MAX_TARGETS + 1})]
    assert rel.commits == 0  # a read commits nothing
    where = "WHERE ea.env::text = :env AND ea.deleted_at IS NULL AND k.revoked_at IS NULL"
    assert where in mod._TARGETS.text
    assert "AND k.status IN ('active', 'rotating') ORDER BY k.id LIMIT :cap" in mod._TARGETS.text


async def test_more_keys_than_one_pass_reads_are_refused_never_truncated() -> None:
    rel = _Rel([ROW] * (mod.MAX_TARGETS + 1))
    with pytest.raises(AccountsStoreError):
        await _store(rel).targets()
    assert len(await _store(_Rel([ROW] * mod.MAX_TARGETS)).targets()) == mod.MAX_TARGETS


async def test_writes_bind_the_environment_and_report_whether_a_row_changed() -> None:
    rel = _Rel()
    verified = VerifiedKey({"uid": "1"}, True, False, ("203.0.113.7",), None, T)
    assert await _store(rel).record_pass(KEY, verified) is True
    assert await _store(rel).record_error(KEY, code="10018", at=T) is True
    rel.rowcount = 0
    assert await _store(rel).disable_trading(ACCT, code=RULE, at=T) is False
    (_, passed), (_, error), (_, disable) = rel.calls
    assert passed == {
        "id": str(KEY), "snapshot": json.dumps({"uid": "1"}), "at": T, "can_trade": True,
        "read_only": False, "ips": ["203.0.113.7"], "expires_at": None, "env": "demo",
    }  # fmt: skip
    assert error == {"id": str(KEY), "code": "10018", "at": T, "env": "demo"}
    assert disable == {"id": str(ACCT), "code": RULE, "at": T, "env": "demo"} and rel.commits == 3


async def test_owed_disarms_are_read_for_the_bound_environment_and_marked_one_by_one() -> None:
    rel = _Rel([{"account_id": str(ACCT), "code": RULE, "at": T}])
    owed = await _store(rel, "live").owed_disarms()
    assert owed == (PolicyDisarm(ACCT, RULE, T),) and rel.commits == 0
    later = datetime(2026, 10, 16, 1, tzinfo=UTC)
    assert await _store(rel, "live").mark_disarm_audited(owed[0], at=later) is True
    assert rel.calls == [
        (mod._OWED.text, {"env": "live", "cap": mod.MAX_TARGETS}),
        (mod._AUDITED.text, {"id": str(ACCT), "disarmed_at": T, "at": later, "env": "live"}),
    ]
    assert "WHERE env::text = :env AND policy_disarmed_at IS NOT NULL" in mod._OWED.text
    assert "AND policy_disarm_audited_at IS NULL ORDER BY id LIMIT :cap" in mod._OWED.text


def test_every_write_is_bound_to_the_environment_and_a_live_row() -> None:
    for stmt in (mod._PASS, mod._ERROR, mod._RETIRE):
        assert "ea.env::text = :env AND k.revoked_at IS NULL" in stmt.text
    assert "env::text = :env AND deleted_at IS NULL AND trading_enabled" in mod._DISABLE.text
    owed_only = "AND policy_disarmed_at = :disarmed_at AND policy_disarm_audited_at IS NULL"
    assert f"env::text = :env {owed_only}" in mod._AUDITED.text  # that disarm, while it is owed


def test_statements_write_only_the_verification_columns() -> None:
    """No ciphertext, identity, status or `last_used_at` column (21 §3.2.2, #2336, #2580)."""
    [passed], [error] = writes_to(mod._PASS.text), writes_to(mod._ERROR.text)
    assert passed.targets == {
        "permission_snapshot", "permission_snapshot_at", "can_trade", "read_only",
        "ip_whitelist", "ip_whitelist_verified_at", "expires_at", "updated_at",
        "last_error_code", "last_error_at",
    }  # fmt: skip
    assert "last_error_code = NULL, last_error_at = NULL" in mod._PASS.text  # a pass clears it
    assert error.targets == {"last_error_code", "last_error_at", "updated_at"}
    [disable] = writes_to(mod._DISABLE.text, "exchange_accounts")
    assert disable.targets == {
        "trading_enabled", "policy_disarm_code", "policy_disarmed_at", "policy_disarm_audited_at",
        "updated_at",
    }  # fmt: skip
    [marked] = writes_to(mod._AUDITED.text, "exchange_accounts")
    assert marked.targets == {"policy_disarm_audited_at"}  # bookkeeping: `updated_at` stays
    assert [w for stmt in STATEMENTS for w in writes_to(stmt.text, "exchange_accounts")] == [
        disable, marked,
    ]  # fmt: skip
    assert "policy_disarm_code = :code, policy_disarmed_at = :at" in mod._DISABLE.text
    assert "permission_snapshot || CAST(:snapshot AS jsonb)" in mod._PASS.text
    assert "CAST(:ips AS cidr[])" in mod._PASS.text


def test_no_write_statement_names_an_envelope_or_last_used_column() -> None:
    """No statement names one of them (21 §3.2.2, #2336, #2580)."""
    names = ("secret_enc", "key_id_enc", "enc_nonce", "enc_alg", "dek_ref", "last_used_at")
    assert [n for stmt in STATEMENTS for n in names if n in stmt.text] == []


def test_only_the_retire_writes_status_and_only_from_a_usable_key() -> None:
    """#5281: one write sets `status`, `active` or `rotating` to the bound value, never back and
    never `revoked` (M2's); the reads filter on it."""
    setting = [stmt for stmt in STATEMENTS for w in writes_to(stmt.text) if "status" in w.targets]
    assert setting == [mod._RETIRE]
    [retire] = writes_to(mod._RETIRE.text)
    assert retire.targets == {"status", "updated_at"}
    assert "SET status = CAST(:status AS key_status), updated_at = now()" in mod._RETIRE.text
    assert mod._RETIRE.text.endswith("AND k.status IN ('active', 'rotating')")
    assert "revoked'" not in mod._RETIRE.text


async def test_retire_binds_the_environment_and_refuses_any_other_status() -> None:
    rel = _Rel()
    assert await _store(rel, "live").retire_key(KEY, status="invalid") is True
    rel.rowcount = 0  # revoked meanwhile, or retired already
    assert await _store(rel).retire_key(KEY, status="expired") is False
    assert [params for _, params in rel.calls] == [
        {"id": str(KEY), "status": "invalid", "env": "live"},
        {"id": str(KEY), "status": "expired", "env": "demo"},
    ]
    for status in ("revoked", "active", "rotating", "pending"):
        with pytest.raises(ValueError, match="invalid"):
            await _store(rel).retire_key(KEY, status=cast(Any, status))
    assert len(rel.calls) == 2 and rel.commits == 2  # a refused status runs no SQL


async def test_invalid_keys_are_read_for_the_bound_environment_and_capped() -> None:
    row = {"key_id": str(KEY), "account_id": str(ACCT), "code": RULE, "verified_at": T}
    rel = _Rel([row])
    assert await _store(rel, "live").invalid_keys() == (InvalidKey(KEY, ACCT, RULE, T),)
    assert rel.calls == [(mod._INVALID.text, {"env": "live", "cap": mod.MAX_TARGETS + 1})]
    assert rel.commits == 0
    where = "WHERE ea.env::text = :env AND ea.deleted_at IS NULL AND k.revoked_at IS NULL"
    assert f"{where} AND k.status = 'invalid' ORDER BY k.id LIMIT :cap" in mod._INVALID.text
    with pytest.raises(AccountsStoreError):
        await _store(_Rel([row] * (mod.MAX_TARGETS + 1))).invalid_keys()
