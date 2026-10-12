"""C-2.8 / SR-030a permission gate and snapshot projection (E27-T02)."""

from __future__ import annotations

from typing import Any

import pytest

from candleviewer.secrets._permissions import reject_withdraw
from candleviewer.secrets.errors import (
    WithdrawPermissionRejected,
)
from tests.unit.credentials_m2._vectors import (
    SNAPSHOT,
    fixture_snapshot,
)


def _snap_with(perms: dict[str, Any]) -> dict[str, Any]:
    s = fixture_snapshot()
    s["permissions"] = perms
    return s


def test_reject_withdraw_allows_trade_only_snapshot() -> None:
    reject_withdraw(SNAPSHOT["permissions"])  # fixture shape with an empty Wallet group
    reject_withdraw({"ContractTrade": ["Order", "Position"], "Wallet": []})


@pytest.mark.parametrize(
    "perms",
    [
        {"Wallet": ["AccountTransfer"]},  # SR-030a: transfer right refused (C-2.8)
        {"Wallet": ["SubMemberTransfer"]},
        {"Wallet": [b"Withdraw"]},  # non-JSON type: fail closed
        {"Wallet": {"x": iter(["Withdraw"])}},
    ],
)
def test_reject_withdraw_refuses_transfer_and_non_json(perms: dict[str, Any]) -> None:
    with pytest.raises(WithdrawPermissionRejected):
        reject_withdraw(perms)


def test_reject_withdraw_allows_scalars() -> None:
    reject_withdraw({"readOnly": 0, "Withdraw": None, "x": 1.5})


@pytest.mark.parametrize("perms", [{"Wallet": [b"x"]}, {"ContractTrade": {"x": iter(["Order"])}}])
def test_malformed_snapshot_has_its_own_code(perms: dict[str, Any]) -> None:
    from candleviewer.secrets.errors import SnapshotInvalid

    with pytest.raises(SnapshotInvalid) as ei:
        reject_withdraw(perms)
    assert str(ei.value) == "snapshot_invalid"
