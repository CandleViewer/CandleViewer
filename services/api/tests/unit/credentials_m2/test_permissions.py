"""C-2.8 / SR-030a permission gate and snapshot projection (E27-T02)."""

from __future__ import annotations

from typing import Any

import pytest

from candleviewer.accounts.verification import TRADE_GROUP, TRADE_RIGHTS
from candleviewer.secrets import _permissions as m2
from candleviewer.secrets._permissions import project_snapshot, reject_withdraw
from candleviewer.secrets.errors import (
    SnapshotInvalid,
    WithdrawPermissionRejected,
)
from tests.unit.accounts._permission_cases import non_string_key_cases
from tests.unit.credentials_m2._vectors import (
    SNAPSHOT,
    fixture_snapshot,
)

_TRADE = {"ContractTrade": ["Order", "Position"], "Derivatives": ["DerivativesTrade"]}


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


@pytest.mark.parametrize(
    "permissions",
    [p for _, p in non_string_key_cases()],
    ids=[name for name, _ in non_string_key_cases()],
)
def test_reject_withdraw_refuses_a_non_string_key_as_snapshot_invalid(
    permissions: dict[Any, Any],
) -> None:
    """`{None: ["Withdraw"], "null": []}` round-trips through JSON as `{"null": []}`: a key that
    is no string is refused before the round trip, whatever it says (#2240)."""
    with pytest.raises(SnapshotInvalid) as refused:
        reject_withdraw(permissions)
    assert str(refused.value) == "snapshot_invalid"


#: (id, projected snapshot, `can_trade`)
_TRADE_CAPABLE: list[tuple[str, dict[str, Any], bool]] = [
    ("trade", {"readOnly": 0, "permissions": _TRADE}, True),
    ("read_only", {"readOnly": 1, "permissions": _TRADE}, False),
    (
        "missing_position",
        {"readOnly": 0, "permissions": {**_TRADE, "ContractTrade": ["Order"]}},
        False,
    ),
    ("bool_read_only", {"readOnly": False, "permissions": _TRADE}, False),
    ("no_read_only", {"permissions": _TRADE}, False),
    (
        "rights_not_a_list",
        {"readOnly": 0, "permissions": {"ContractTrade": "Order,Position"}},
        False,
    ),
    ("permissions_not_an_object", {"readOnly": 0, "permissions": ["Order", "Position"]}, False),
]


@pytest.mark.parametrize(
    ("snapshot", "can_trade"),
    [(c[1], c[2]) for c in _TRADE_CAPABLE],
    ids=[c[0] for c in _TRADE_CAPABLE],
)
def test_trade_capable_reads_write_access_and_both_trade_rights(
    snapshot: dict[str, Any], can_trade: bool
) -> None:
    """`api_keys.can_trade` at insert (#2240): write access (`readOnly` the integer 0, and
    `False == 0` in Python) and both trade rights in the trade group."""
    assert m2.trade_capable(snapshot) is can_trade


def test_m2_trade_rights_are_the_m13_trade_scope() -> None:
    """M2 derives `can_trade` at insert from the trade scope M13's verification requires, so the
    flag it writes is the one the verification pass writes again before the key is promoted."""
    assert (m2._TRADE_GROUP, m2._TRADE_RIGHTS) == (TRADE_GROUP, frozenset(TRADE_RIGHTS))


@pytest.mark.parametrize("flag", [0, 1])
def test_project_snapshot_keeps_the_uta_flag_the_verification_found(flag: int) -> None:
    """SR-E27-04: UTA is stored in the snapshot, so the projection keeps it beside `readOnly`."""
    assert project_snapshot({**SNAPSHOT, "uta": flag})["uta"] == flag


def test_project_snapshot_still_drops_the_reply_fields_it_does_not_list() -> None:
    kept = project_snapshot({**SNAPSHOT, "uta": 1, "unified": 1, "apiKey": "x", "parentUid": "9"})
    assert {"unified", "apiKey", "parentUid"}.isdisjoint(kept)
