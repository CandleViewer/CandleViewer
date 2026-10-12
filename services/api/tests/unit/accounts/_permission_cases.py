"""Shared C-2.8 / SR-030a permission corpus (#2240).

Every JSON case is run through the M13 predicate and `PermissionSnapshot` (unit tests) and through
the `ak_snapshot_shape` CHECK of migration 0019 (integration test); all three must agree.
EXACT_WITHDRAW records the one place where they refuse in different ways, and KNOWN_GAPS the
spellings all three accept (#2270).

Shape: the exchange's key-info response (`GET /v5/user/query-api`) reports a key's rights as
values inside permission groups, e.g. `"Wallet": ["AccountTransfer", "SubMemberTransfer",
"Withdraw"]` (SR-030a in docs/plan/04-security-program.md; the API doc is cited in
test_withdraw_transfer_predicate.py). packages/fixtures has no recorded, redacted query-api
capture yet, so DOCUMENTED is structural: the synthetic accounts fixture's groups plus the three
SR-030a Wallet rights, nothing else. The fixture's top-level `Withdraw` group is the legacy group
of 0017 and the schema doc, not one the exchange reports (#2267 item 10). ROBUSTNESS cases are
deliberately not exchange shapes; they pin case and space handling, the empty-group exemption,
recursion and fail-closed behaviour, mirroring the M2 gate's own tests (E27-T02).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_FX = Path(__file__).resolve().parents[5] / "packages/fixtures/accounts/accounts.json"


def _fixture_permissions() -> dict[str, Any]:
    rows: list[dict[str, Any]] = json.loads(_FX.read_text())["accounts"]
    permissions: dict[str, Any] = rows[0]["permission_snapshot"]["permissions"]
    return permissions


#: The synthetic accounts fixture's groups with an empty `Wallet`: a trade-only key. The fixture
#: as shipped grants `"Wallet": ["AccountTransfer"]`, which C-2.8 / SR-030a refuse (covered in
#: test_account_models.py); the M2 gate's test vectors derive their snapshot the same way.
BASE: dict[str, Any] = {**_fixture_permissions(), "Wallet": []}

#: The fund-movement rights SR-030a lists for `permissions.Wallet`.
SR030A_WALLET_RIGHTS = ("AccountTransfer", "SubMemberTransfer", "Withdraw")

Case = tuple[str, dict[str, Any], bool]


def _with(**groups: Any) -> dict[str, Any]:
    return {**BASE, **groups}


#: (case id, permissions object, allowed)
DOCUMENTED: list[Case] = [
    ("trade_only_fixture", BASE, True),
    ("no_groups", {}, True),
    ("withdraw_group_empty", {"Withdraw": []}, True),
    *[(f"wallet_{r}", _with(Wallet=[r]), False) for r in SR030A_WALLET_RIGHTS],
    ("wallet_all_sr030a_rights", _with(Wallet=list(SR030A_WALLET_RIGHTS)), False),
    ("withdraw_group_granting", _with(Withdraw=["Withdraw"]), False),
]

ROBUSTNESS: list[Case] = [
    ("value_lower_case", _with(Wallet=["withdraw"]), False),
    ("value_upper_case", _with(Wallet=["ACCOUNTTRANSFER"]), False),
    ("value_padded", _with(Wallet=[" SubMemberTransfer "]), False),
    ("value_bare_string", {"Affiliate": "AccountTransfer"}, False),
    ("value_nested_array", {"Affiliate": [["Withdraw"]]}, False),
    ("key_nested_even_if_empty", {"Affiliate": {"Withdraw": []}}, False),
    ("group_lower_case_granting", {"withdraw": ["Order"]}, False),
    ("group_object", {"withdraw": {}}, False),
    ("group_zero", {"withdraw": 0}, False),
    ("group_false", {"withdraw": False}, False),
    ("group_blank", {"withdraw": " "}, False),
    ("group_empty_string_element", {"withdraw": [""]}, False),
    ("group_empty_list", {"withdraw": []}, True),
    ("group_null", {"withdraw": None}, True),
    ("group_empty_string", {"withdraw": ""}, True),
    ("scalars_ignored", {"Affiliate": [1, 2.5, True, None]}, True),
]

JSON_CASES: list[Case] = DOCUMENTED + ROBUSTNESS
ALLOWED: list[Case] = [c for c in JSON_CASES if c[2]]
REFUSED: list[Case] = [c for c in JSON_CASES if not c[2]]

#: The exact key `Withdraw` (the legacy group of 0017 and the schema doc, not an exchange group)
#: keeps a stricter shape than the bare predicate's null/""/[] exemption: `PermissionSnapshot`
#: types it as a list of strings, and 0017's retained conjunct (`jsonb_array_length`) raises
#: SQLSTATE 22023 for any non-array. So the layers refuse these differently, but all refuse:
#: (case id, permissions, bare predicate allows, PermissionSnapshot error text)
EXACT_WITHDRAW: list[tuple[str, dict[str, Any], bool, str]] = [
    ("withdraw_null", {"Withdraw": None}, True, "valid tuple"),
    ("withdraw_empty_string", {"Withdraw": ""}, True, "valid tuple"),
    ("withdraw_scalar", {"Withdraw": 0}, False, "key_withdraw_permission"),
    ("withdraw_object", {"Withdraw": {}}, False, "key_withdraw_permission"),
]

#: Spellings the substring deny-list misses, at every layer alike: the predicate, the model and
#: the CHECK all accept them. Pinned so the parity holds and the gap stays visible; the allow-list
#: in #2270 is the fix.
KNOWN_GAPS: list[Case] = [
    ("gap_inner_space", _with(Wallet=["With draw"]), True),
    ("gap_zero_width_space", _with(Wallet=["With\u200bdraw"]), True),
    ("gap_long_s", _with(Wallet=["AccountTran\u017ffer"]), True),
]


def non_json_cases() -> list[tuple[str, dict[str, Any]]]:
    """Values JSON cannot carry are refused whatever they say (fail closed). Built fresh per call
    because one holds an iterator; unit-only, since jsonb cannot store them."""
    return [
        ("bytes_right", {"Wallet": [b"Withdraw"]}),
        ("bytes_harmless", {"Wallet": [b"Order"]}),
        ("iterator", {"Affiliate": iter(["Order"])}),
        ("nan", {"Affiliate": [float("nan")]}),
    ]
