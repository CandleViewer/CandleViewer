"""SR-030 / SR-030a allow-list at the M2 key gate (#2270, C-2.8).

The substring deny-list misses inner spacing or punctuation, invisible separators, lookalike
letters and fund rights named without `withdraw` or `transfer` (#2262 review). The gate accepts
only the allow-listed rights, spelled exactly, with every other group empty or absent, and keeps
the deny-list as its second line. No recorded, redacted key-info capture exists yet (#2240), so
the cases are structural: names come from SR-030a, the E27 threat model (section 5 item 2) and
the synthetic accounts fixture.
"""

from __future__ import annotations

from typing import Any

import pytest

from candleviewer.secrets import _permissions as perms
from candleviewer.secrets._permissions import ALLOWED_RIGHTS, project_snapshot, require_allow_listed
from candleviewer.secrets.broker import CredentialBroker
from candleviewer.secrets.errors import SnapshotInvalid, WithdrawPermissionRejected
from candleviewer.secrets.secret import Secret
from candleviewer.secrets.store import InMemoryCredentialStore
from tests.unit.accounts._permission_cases import (
    EXACT_WITHDRAW,
    GATE_ALLOWS,
    JSON_CASES,
    KNOWN_GAPS,
    REFUSED,
    Case,
)
from tests.unit.credentials_m2._vectors import ACCOUNT, API_KEY, API_SECRET, ENV, SNAPSHOT, AuditLog

_TRADE: dict[str, Any] = {
    "ContractTrade": ["Order", "Position"],
    "Derivatives": ["DerivativesTrade"],
}
#: SR-030a: empty for trading keys.
_NON_TRADING = ("Spot", "Wallet", "Options", "Exchange", "NFT", "Affiliate")
#: E27 threat model section 5 item 2: fund-moving groups named without either word.
_FUND_GROUPS = ("FiatP2P", "FiatBitPay", "FiatConvertBroker", "BitCard")
#: The #2270 Context spellings: none is a canonical ASCII name, so each is refused anywhere.
_BYPASSES = (
    "With draw",
    "With-draw",
    "With.draw",
    "With_draw",
    "With\u200bdraw",  # zero-width space
    "With\u00addraw",  # soft hyphen
    "W\u0456thdraw",  # Cyrillic i
    "\uff37ithdraw",  # fullwidth W
    "AccountTran\u017ffer",  # long s
    " Withdraw",
    "Withdraw ",
)
#: Non-canonical spellings of the permitted rights and groups.
_RIGHT_LOOKALIKES = (
    *("order", "ORDER", " Order", "Order ", "Ord er", "Ord\u200ber"),
    *("Ord\u0435r", "\uff2frder"),  # Cyrillic e, fullwidth O
)
_GROUP_LOOKALIKES = (
    " ContractTrade",
    "ContractTrade ",
    "Contract Trade",
    "Contract\u200bTrade",
    "C\u043entractTrade",  # Cyrillic o
    "\uff23ontractTrade",  # fullwidth C
    "Derivative\u017f",  # long s
)
#: Malformed group names: empty, or not led by a letter.
_MALFORMED_NAMES = ("", "1Withdraw", "9")


def _ids(cases: list[Case]) -> list[str]:
    return [c[0] for c in cases]


def _refused(permissions: Any) -> None:
    with pytest.raises(WithdrawPermissionRejected) as refused:
        require_allow_listed(permissions)
    assert str(refused.value) == "key_withdraw_permission"


def test_allow_list_is_the_sr030_minimum_trade_scope() -> None:
    assert ALLOWED_RIGHTS == {
        "ContractTrade": frozenset({"Order", "Position"}),
        "Derivatives": frozenset({"DerivativesTrade"}),
    }


def test_allow_list_cannot_be_widened_at_run_time() -> None:
    writable: Any = ALLOWED_RIGHTS
    with pytest.raises(TypeError):
        writable["Wallet"] = frozenset({"AccountTransfer"})


@pytest.mark.parametrize(
    ("group", "right"),
    [
        ("ContractTrade", "Order"),
        ("ContractTrade", "Position"),
        ("Derivatives", "DerivativesTrade"),
    ],
)
def test_gate_accepts_each_permitted_right(group: str, right: str) -> None:
    require_allow_listed({group: [right]})


@pytest.mark.parametrize(
    "permissions", [{}, _TRADE, SNAPSHOT["permissions"]], ids=["none", "trade", "fixture"]
)
def test_gate_accepts_a_compliant_trade_key(permissions: dict[str, Any]) -> None:
    require_allow_listed(permissions)


def test_gate_accepts_every_other_group_when_empty() -> None:
    other = (*_NON_TRADING, *_FUND_GROUPS, "Withdraw", "withdraw", "contracttrade", "Later2")
    require_allow_listed({**_TRADE, **{group: [] for group in other}})


@pytest.mark.parametrize("spelling", _BYPASSES)
def test_gate_refuses_a_bypass_spelling_as_a_right(spelling: str) -> None:
    _refused({**_TRADE, "Wallet": [spelling]})


@pytest.mark.parametrize("spelling", _BYPASSES + _GROUP_LOOKALIKES + _MALFORMED_NAMES)
@pytest.mark.parametrize("rights", [["Order"], []], ids=["granting", "empty"])
def test_gate_refuses_a_non_canonical_group_name(spelling: str, rights: list[str]) -> None:
    _refused({**_TRADE, spelling: rights})


@pytest.mark.parametrize("spelling", _RIGHT_LOOKALIKES)
def test_gate_refuses_a_lookalike_of_a_permitted_right(spelling: str) -> None:
    _refused({"ContractTrade": ["Order", spelling]})


@pytest.mark.parametrize("group", ["contracttrade", "CONTRACTTRADE", "Contracttrade"])
def test_gate_refuses_rights_in_a_case_variant_of_a_permitted_group(group: str) -> None:
    _refused({group: ["Order"]})


@pytest.mark.parametrize("group", _NON_TRADING + _FUND_GROUPS + ("Withdraw", "Later2"))
def test_gate_refuses_any_right_in_a_group_outside_the_allow_list(group: str) -> None:
    _refused({**_TRADE, group: ["Order"]})


@pytest.mark.parametrize(
    "permissions",
    [
        {"Wallet": ["AccountTransfer"]},
        {"Wallet": ["SubMemberTransfer"]},
        {"Wallet": ["SubMemberTransferList"]},
        {"Wallet": ["Withdraw"]},
        {"FiatP2P": ["FiatP2POrder", "Advertising"]},
        {"FiatBitPay": ["FaitPayOrder"]},
    ],
    ids=["account_transfer", "sub_transfer", "sub_transfer_list", "withdraw", "p2p", "bitpay"],
)
def test_gate_refuses_documented_fund_rights(permissions: dict[str, Any]) -> None:
    _refused({**_TRADE, **permissions})


@pytest.mark.parametrize(
    "permissions",
    [{"Derivatives": ["Order"]}, {"ContractTrade": ["DerivativesTrade"]}],
    ids=["order_in_derivatives", "derivatives_trade_in_contract"],
)
def test_gate_refuses_a_right_permitted_only_in_another_group(permissions: dict[str, Any]) -> None:
    _refused(permissions)


@pytest.mark.parametrize("value", [None, "", 0, False, {}, "Order"], ids=repr)
def test_gate_refuses_a_group_that_is_not_a_list(value: object) -> None:
    _refused({**_TRADE, "Spot": value})


@pytest.mark.parametrize("right", [1, None, True, ["Order"], {"Order": []}], ids=repr)
def test_gate_refuses_a_right_that_is_not_a_string(right: object) -> None:
    _refused({"ContractTrade": [right]})


@pytest.mark.parametrize("group", [1, None, 1.5], ids=repr)
def test_gate_refuses_a_group_name_that_is_not_a_string(group: object) -> None:
    permissions: dict[Any, Any] = {group: []}
    _refused(permissions)


def test_gate_bounds_a_group_name_at_64_characters() -> None:
    require_allow_listed({"G" * 64: []})
    _refused({"G" * 65: []})


@pytest.mark.parametrize(
    "permissions",
    [{"ContractTrade": [b"Order"]}, {"Spot": iter([])}, {"Spot": [float("nan")]}],
    ids=["bytes", "iterator", "nan"],
)
def test_gate_fails_closed_on_non_json(permissions: dict[str, Any]) -> None:
    with pytest.raises(SnapshotInvalid, match="snapshot_invalid"):
        require_allow_listed(permissions)


_GATE_ALLOWED = [c for c in JSON_CASES if c[0] in GATE_ALLOWS]
_GATE_REFUSED = [c for c in JSON_CASES if c[0] not in GATE_ALLOWS]


@pytest.mark.parametrize("permissions", [c[1] for c in _GATE_ALLOWED], ids=_ids(_GATE_ALLOWED))
def test_gate_accepts_the_corpus_cases_it_allows(permissions: dict[str, Any]) -> None:
    require_allow_listed(permissions)


@pytest.mark.parametrize("permissions", [c[1] for c in _GATE_REFUSED], ids=_ids(_GATE_REFUSED))
def test_gate_refuses_every_other_corpus_case(permissions: dict[str, Any]) -> None:
    _refused(permissions)


def test_gate_allows_a_strict_subset_of_what_the_deny_list_layers_allow() -> None:
    assert GATE_ALLOWS < {c[0] for c in JSON_CASES if c[2]}


@pytest.mark.parametrize("permissions", [c[1] for c in KNOWN_GAPS], ids=_ids(KNOWN_GAPS))
def test_gate_refuses_every_deny_list_gap(permissions: dict[str, Any]) -> None:
    _refused(permissions)


@pytest.mark.parametrize(
    "permissions", [c[1] for c in EXACT_WITHDRAW], ids=[c[0] for c in EXACT_WITHDRAW]
)
def test_gate_refuses_every_non_list_legacy_withdraw_group(permissions: dict[str, Any]) -> None:
    _refused(permissions)


@pytest.mark.parametrize("permissions", [c[1] for c in KNOWN_GAPS], ids=_ids(KNOWN_GAPS))
def test_project_snapshot_refuses_a_deny_list_gap(permissions: dict[str, Any]) -> None:
    with pytest.raises(WithdrawPermissionRejected, match="key_withdraw_permission"):
        project_snapshot({**SNAPSHOT, "permissions": permissions})


def test_project_snapshot_refuses_a_right_hidden_by_json_key_coercion() -> None:
    """`{None: [...], "null": []}` round-trips through JSON as `{"null": []}`, which hides the
    right from both lines unless the raw group names are checked first."""
    hidden: dict[Any, Any] = {**_TRADE, None: ["Withdraw"], "null": []}
    with pytest.raises(WithdrawPermissionRejected, match="key_withdraw_permission"):
        project_snapshot({**SNAPSHOT, "permissions": hidden})


@pytest.mark.parametrize("permissions", [c[1] for c in REFUSED], ids=_ids(REFUSED))
def test_deny_list_still_refuses_with_the_allow_list_bypassed(
    monkeypatch: pytest.MonkeyPatch, permissions: dict[str, Any]
) -> None:
    """Second line: with the allow-list a no-op, the deny-list alone still refuses."""
    monkeypatch.setattr(perms, "require_allow_listed", lambda _permissions: None)
    with pytest.raises(WithdrawPermissionRejected, match="key_withdraw_permission"):
        project_snapshot({**SNAPSHOT, "permissions": permissions})


@pytest.mark.parametrize(
    "permissions",
    [c[1] for c in KNOWN_GAPS] + [{**_TRADE, "Spot": ["Order"]}],
    ids=[*_ids(KNOWN_GAPS), "spot_right"],
)
async def test_store_refuses_a_key_outside_the_allow_list_before_any_write(
    broker: CredentialBroker,
    store: InMemoryCredentialStore,
    audit: AuditLog,
    permissions: dict[str, Any],
) -> None:
    snapshot = {**SNAPSHOT, "permissions": permissions}
    with pytest.raises(WithdrawPermissionRejected, match="key_withdraw_permission"):
        await broker.store(ENV, ACCOUNT, "k", Secret(API_KEY), Secret(API_SECRET), snapshot)
    assert not store.rows
    assert not audit.records
