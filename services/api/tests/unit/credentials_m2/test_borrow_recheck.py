"""SR-E27-14 (#836 2b3): a borrow re-checks C-2.8 on the stored row before it decrypts.

`store()` gates the snapshot once; the database CHECK keeps only the deny-list. A row edited since
(KV-T03) must not sign: the borrow refuses it before its audit record and before any decrypt, and
flushes its cached DEK. Fixed vectors only (`_vectors`).
"""

from __future__ import annotations

from typing import Any

import pytest

from candleviewer.secrets import KEY_ID_SLOT
from candleviewer.secrets import broker as broker_mod
from candleviewer.secrets.broker import CredentialBroker
from candleviewer.secrets.errors import WithdrawPermissionRejected
from tests.unit.credentials_m2._helpers import _borrow, _h, _Spy, _store
from tests.unit.credentials_m2._vectors import SNAPSHOT, AuditLog, kek


def _rights(permissions: object) -> dict[str, Any]:
    return {"permission_snapshot": {**SNAPSHOT, "permissions": permissions}}


@pytest.mark.parametrize(
    "tamper",
    [
        _rights({"ContractTrade": ["Order", "Position"], "FiatP2P": ["FiatP2POrder"]}),
        _rights({"ContractTrade": ["Order"], "Wallet": ["AccountTransfer"]}),
        _rights({"Withdraw": ["Withdraw"]}),
        _rights(["ContractTrade"]),
        {"permission_snapshot": []},
        {"can_withdraw": True},
        {"can_transfer": True},
    ],
    ids=["fiat", "transfer", "withdraw", "rights_list", "snapshot_list", "can_withdraw", "can_tr"],
)
async def test_a_row_failing_c28_is_refused_before_its_audit_and_any_decrypt(
    store: Any, monkeypatch: pytest.MonkeyPatch, tamper: dict[str, Any]
) -> None:
    audit = AuditLog()
    b = CredentialBroker(store, audit, kek())
    meta = await _store(b)
    await _borrow(b, meta.key_id)  # its DEK is cached now
    store.rows[meta.key_id].update(tamper)
    spy, before = _Spy(monkeypatch), len(audit.records)
    with pytest.raises(WithdrawPermissionRejected):
        await _h(b).sign(meta.key_id, (KEY_ID_SLOT,), purpose="key_verify")
    assert (spy.bufs, len(audit.records), len(b._cache)) == ([], before, 0)


async def test_the_deny_list_still_refuses_with_the_allow_list_bypassed(
    store: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    b = CredentialBroker(store, AuditLog(), kek())
    meta = await _store(b)
    store.rows[meta.key_id].update(_rights({"ContractTrade": ["Order", "Withdraw"]}))
    monkeypatch.setattr(broker_mod, "require_allow_listed", lambda rights: None)
    with pytest.raises(WithdrawPermissionRejected):
        await _h(b).sign(meta.key_id, (KEY_ID_SLOT,), purpose="sign_rest")


async def test_the_fund_right_check_comes_before_the_status_check(store: Any) -> None:
    """C-2.8 first: a row that also fails the status check reports the fund right."""
    b = CredentialBroker(store, AuditLog(), kek())
    meta = await _store(b)
    store.rows[meta.key_id].update(status="pending", can_withdraw=True)
    with pytest.raises(WithdrawPermissionRejected):
        await _h(b).sign(meta.key_id, (KEY_ID_SLOT,), purpose="sign_rest")


async def test_a_compliant_stored_row_still_signs(store: Any) -> None:
    b = CredentialBroker(store, AuditLog(), kek())
    meta = await _store(b)
    assert store.rows[meta.key_id]["can_withdraw"] is False
    assert (await _h(b).sign(meta.key_id, (KEY_ID_SLOT,), purpose="sign_rest")).signature


@pytest.mark.parametrize("flag", ["can_withdraw", "can_transfer"])
async def test_a_row_read_without_a_fund_flag_is_refused(store: Any, flag: str) -> None:
    """A flag the store did not return is never taken as false (fail closed)."""
    b = CredentialBroker(store, AuditLog(), kek())
    meta = await _store(b)
    del store.rows[meta.key_id][flag]
    with pytest.raises(WithdrawPermissionRejected):
        await _h(b).sign(meta.key_id, (KEY_ID_SLOT,), purpose="sign_rest")


async def test_one_signing_re_checks_c28_once(store: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """The post-audit fence checks the same row object again, without the C-2.8 re-check."""
    b = CredentialBroker(store, AuditLog(), kek())
    meta = await _store(b)
    checked: list[object] = []
    monkeypatch.setattr(broker_mod, "reject_withdraw", checked.append)
    await _h(b).sign(meta.key_id, (KEY_ID_SLOT,), purpose="sign_rest")
    assert len(checked) == 1
