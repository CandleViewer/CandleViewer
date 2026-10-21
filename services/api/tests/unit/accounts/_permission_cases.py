"""Shared C-2.8 / SR-030a permission corpus (#2240, #2270).

Every JSON case is run through the shared deny-list (`candleviewer.domain.key_permissions`, behind
the M2 and M13 wrappers) and `PermissionSnapshot` (unit tests) and through the `ak_snapshot_shape`
CHECK of migration 0019 (integration test); these deny-list layers must agree. EXACT_WITHDRAW
records the one place where they refuse in different ways, and KNOWN_GAPS the spellings all of
them accept. The M2 gate adds the SR-030 allow-list (#2270) and refuses every KNOWN_GAPS case;
GATE_ALLOWS names the JSON cases it accepts (tests/unit/credentials_m2/test_allow_list.py).

Shape: the exchange's key-info response (`GET /v5/user/query-api`) reports a key's rights as
values inside permission groups. The `docs_*` cases come from its documented reply, transcribed
as the page prints it (`tests/fixtures/key_verification/key_info_docs_example.json`, README
there): `"Wallet": ["AccountTransfer", "SubMemberTransfer"]`. The `docs_table_*` cases add the
Wallet rights only the page's parameter table names (`SubMemberTransferList`, `Withdraw`), and
RECORDED holds the owner's recorded, redacted captures (none yet, #2701). The other DOCUMENTED
cases are structural: the synthetic accounts fixture's groups plus the three SR-030a Wallet
rights. The fixture's top-level `Withdraw` group is the legacy group of 0017 and the schema doc,
not one the exchange reports (#2267 item 10). ROBUSTNESS cases are deliberately not exchange
shapes; they pin case and space handling, the empty-group exemption, recursion and fail-closed
behaviour, mirroring the M2 gate's own tests (E27-T02).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_FX = Path(__file__).resolve().parents[5] / "packages/fixtures/accounts/accounts.json"
#: The key-info fixtures; `recorded/manifest.json` lists the transcription and every capture.
KEY_INFO = Path(__file__).resolve().parents[2] / "fixtures" / "key_verification"
#: The manifest `source` of a transcription from the exchange's documentation (G-8, #2877).
TRANSCRIBED = "docs-transcribed"


def _fixture_permissions() -> dict[str, Any]:
    rows: list[dict[str, Any]] = json.loads(_FX.read_text())["accounts"]
    permissions: dict[str, Any] = rows[0]["permission_snapshot"]["permissions"]
    return permissions


def manifest() -> list[dict[str, Any]]:
    path = KEY_INFO / "recorded" / "manifest.json"
    entries: list[dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))["fixtures"]
    return entries


def captures() -> list[dict[str, Any]]:
    """The owner's recorded captures: every manifest entry that is no transcription."""
    return [entry for entry in manifest() if entry["source"] != TRANSCRIBED]


def reply(entry: dict[str, Any]) -> dict[str, Any]:
    """A manifest entry's reply body (its `path` is relative to the manifest)."""
    path = KEY_INFO / "recorded" / entry["path"]
    body: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return body


#: The documented key-info reply, as transcribed.
DOCS_REPLY = reply(next(entry for entry in manifest() if entry["source"] == TRANSCRIBED))
DOCS_EXAMPLE: dict[str, Any] = DOCS_REPLY["result"]["permissions"]
#: The documented groups, all empty but the two the allow-list permits, which keep the rights the
#: reply prints for them.
DOCS_TRADE_ONLY: dict[str, Any] = {
    group: rights if group in ("ContractTrade", "Derivatives") else []
    for group, rights in DOCS_EXAMPLE.items()
}
#: Wallet rights only the page's parameter table names: table-derived, not printed in the example.
DOCS_TABLE_WALLET_RIGHTS = ("SubMemberTransferList", "Withdraw")


#: The synthetic accounts fixture's groups with an empty `Wallet`: a trade-only key. The fixture
#: as shipped grants `"Wallet": ["AccountTransfer"]`, which C-2.8 / SR-030a refuse (covered in
#: test_account_models.py); the M2 gate's test vectors derive their snapshot the same way.
BASE: dict[str, Any] = {**_fixture_permissions(), "Wallet": []}

#: The fund-movement rights SR-030a lists for `permissions.Wallet`.
SR030A_WALLET_RIGHTS = ("AccountTransfer", "SubMemberTransfer", "Withdraw")

Case = tuple[str, dict[str, Any], bool]


def _with(**groups: Any) -> dict[str, Any]:
    return {**BASE, **groups}


#: The owner's captures: a `trade` key is allowed, a `fund_rights` key refused (README there).
RECORDED: list[Case] = [
    (f"recorded_{Path(e['path']).stem}", reply(e)["result"]["permissions"], e["kind"] == "trade")
    for e in captures()
]

#: (case id, permissions object, allowed)
DOCUMENTED: list[Case] = [
    ("trade_only_fixture", BASE, True),
    ("no_groups", {}, True),
    ("withdraw_group_empty", {"Withdraw": []}, True),
    *[(f"wallet_{r}", _with(Wallet=[r]), False) for r in SR030A_WALLET_RIGHTS],
    ("wallet_all_sr030a_rights", _with(Wallet=list(SR030A_WALLET_RIGHTS)), False),
    ("withdraw_group_granting", _with(Withdraw=["Withdraw"]), False),
    ("docs_example", DOCS_EXAMPLE, False),
    ("docs_trade_only", DOCS_TRADE_ONLY, True),
    *[
        (f"docs_wallet_{r}", {**DOCS_TRADE_ONLY, "Wallet": [r]}, False)
        for r in DOCS_EXAMPLE["Wallet"]
    ],
    *[
        (f"docs_table_wallet_{r}", {**DOCS_TRADE_ONLY, "Wallet": [r]}, False)
        for r in DOCS_TABLE_WALLET_RIGHTS
    ],
    *RECORDED,
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

#: Spellings the substring deny-list misses (#2262 review), at every deny-list layer alike: the
#: predicate, the model and the CHECK all accept them. Pinned so their parity holds and the gap
#: stays visible. The M2 gate's allow-list refuses every one (#2270); M13 and the CHECK keep the
#: deny-list until a new migration moves the CHECK to the allow-list. Fund groups without either
#: word come from the E27 threat model, section 5 item 2.
KNOWN_GAPS: list[Case] = [
    ("gap_inner_space", _with(Wallet=["With draw"]), True),
    ("gap_inner_hyphen", _with(Wallet=["With-draw"]), True),
    ("gap_zero_width_space", _with(Wallet=["With\u200bdraw"]), True),
    ("gap_soft_hyphen", _with(Wallet=["AccountTrans\u00adfer"]), True),
    ("gap_cyrillic_i", _with(Wallet=["W\u0456thdraw"]), True),
    ("gap_fullwidth_w", _with(Wallet=["\uff37ithdraw"]), True),
    ("gap_long_s", _with(Wallet=["AccountTran\u017ffer"]), True),
    ("gap_group_key_inner_space", _with(**{"With draw": ["Order"]}), True),
    ("gap_fund_group_without_either_word", _with(FiatP2P=["FiatP2POrder"]), True),
    # The documented reply without its Wallet rights: its fiat, card and post groups name neither.
    ("gap_docs_example_fund_groups", {**DOCS_EXAMPLE, "Wallet": []}, True),
]

#: The JSON_CASES ids the M2 allow-list gate accepts: canonical group names, every value a list,
#: and no right outside the allow-list. It refuses every other case, including `null`, `""` and
#: scalar groups that the deny-list layers exempt.
GATE_ALLOWS = frozenset(
    {"trade_only_fixture", "no_groups", "withdraw_group_empty", "group_empty_list"}
    | {"docs_trade_only", *(c[0] for c in RECORDED if c[2])}
)


def non_json_cases() -> list[tuple[str, dict[str, Any]]]:
    """Values JSON cannot carry are refused whatever they say (fail closed). Built fresh per call
    because one holds an iterator; unit-only, since jsonb cannot store them."""
    return [
        ("bytes_right", {"Wallet": [b"Withdraw"]}),
        ("bytes_harmless", {"Wallet": [b"Order"]}),
        ("iterator", {"Affiliate": iter(["Order"])}),
        ("nan", {"Affiliate": [float("nan")]}),
    ]


def non_string_key_cases() -> list[tuple[str, dict[Any, Any]]]:
    """A key that is no string, at any depth, is refused whatever it says (fail closed, #2240).
    JSON writes `None` as `"null"`, `1` as `"1"` and `True` as `"true"`, and keeps the last of two
    equal keys, so the round trip would let a later empty group hide an earlier right. Unit-only,
    since jsonb keys are text."""
    return [
        ("none_hidden_by_null", {None: ["Withdraw"], "null": []}),
        ("int_hidden_by_str", {1: ["AccountTransfer"], "1": []}),
        ("nested_hidden", {"Affiliate": {True: ["SubMemberTransfer"], "true": []}}),
        ("hidden_in_a_list", {"Affiliate": [{1.5: "Withdraw", "1.5": ""}]}),
        ("harmless", {1: ["Order"]}),
    ]
