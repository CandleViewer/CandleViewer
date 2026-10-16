"""Properties of the M2 allow-list gate (#2270) and its parity with M13 (C-2.8, SR-030, C-3.2).

Generated permission maps mix documented group and right names, the #2270 bypass spellings and
arbitrary text. The gate must equal SR-030 / SR-030a read straight from the spec; a compliant map
passes and any one foreign right fails it; whatever the gate accepts, M13's predicate and
`PermissionSnapshot` accept too, so a stored snapshot always reads back; and M2's deny-list and
its M13 restatement (C-3.2 bars M13 from importing M2) give the same verdict on every input.
"""

from __future__ import annotations

import string
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from candleviewer.accounts import _permissions as m13
from candleviewer.accounts.errors import WithdrawPermissionError
from candleviewer.accounts.models import PermissionSnapshot
from candleviewer.secrets import _permissions as m2
from candleviewer.secrets.errors import WithdrawPermissionRejected
from tests.unit.accounts._permission_cases import EXACT_WITHDRAW, JSON_CASES, KNOWN_GAPS, Case

#: SR-030 / SR-030a as #2270 states them, kept apart from the gate's own table.
_SPEC: dict[str, tuple[str, ...]] = {
    "ContractTrade": ("Order", "Position"),
    "Derivatives": ("DerivativesTrade",),
}
_GROUPS = (
    *_SPEC,
    *("Spot", "Wallet", "Options", "Exchange", "NFT", "Affiliate", "Withdraw", "withdraw"),
    *("FiatP2P", "FiatBitPay", "FiatConvertBroker", "BitCard", "contracttrade", "With draw"),
    *("With\u200bdraw", " ContractTrade", "C\u043entractTrade", "\uff23ontractTrade"),
)
_RIGHTS = (
    *("Order", "Position", "DerivativesTrade", "Withdraw", "AccountTransfer", "SubMemberTransfer"),
    *("SubMemberTransferList", "FiatP2POrder", "Advertising", "FaitPayOrder", "With draw"),
    *("With\u00addraw", "W\u0456thdraw", "\uff37ithdraw", "AccountTran\u017ffer"),
    *(" Order", "order", "Ord\u0435r"),
)
_NOW = datetime(2026, 10, 16, tzinfo=UTC)
_PROPERTY = settings(max_examples=300, deadline=None, derandomize=True)  # the same maps every run

_names = st.sampled_from(_GROUPS) | st.text(max_size=8)
_rights = st.sampled_from(_RIGHTS) | st.text(max_size=8)
_malformed: list[object] = [[], None, "", 0, True, {}]
_values: st.SearchStrategy[object] = st.one_of(
    st.lists(_rights, max_size=3), st.sampled_from(_malformed)
)
_wild = st.dictionaries(_names, _values, max_size=5)
_canonical = st.builds(
    str.__add__,
    st.sampled_from(string.ascii_letters),
    st.text(string.ascii_letters + string.digits, max_size=15),
)
_compliant = st.builds(
    lambda empty, trade: {**empty, **trade},
    st.dictionaries(_canonical, st.just([]), max_size=4),
    st.fixed_dictionaries(
        {},
        optional={
            "ContractTrade": st.lists(st.sampled_from(_SPEC["ContractTrade"]), max_size=3),
            "Derivatives": st.lists(st.sampled_from(_SPEC["Derivatives"]), max_size=2),
        },
    ),
)
_json = st.recursive(
    st.none() | st.booleans() | st.integers() | st.floats() | _rights,
    lambda inner: st.lists(inner, max_size=3) | st.dictionaries(_names, inner, max_size=3),
    max_leaves=8,
)


@st.composite
def _one_foreign_right(draw: st.DrawFn) -> dict[str, Any]:
    """A compliant map plus one right that its group does not permit."""
    permissions: dict[str, Any] = draw(_compliant)
    group = draw(_names)
    right = draw(_rights.filter(lambda r: r not in _SPEC.get(group, ())))
    permissions[group] = [*permissions.get(group, []), right]
    return permissions


def _spec_allows(permissions: Mapping[str, Any]) -> bool:
    """The rule from the spec, written apart from the gate: canonical ASCII group names of at
    most 64 characters, list values, and only the permitted rights of a permitted group."""
    for group, granted in permissions.items():
        canonical = group.isascii() and group.isalnum() and group[:1].isalpha()
        if not canonical or len(group) > 64 or not isinstance(granted, list):
            return False
        if any(not isinstance(r, str) or r not in _SPEC.get(group, ()) for r in granted):
            return False
    return True


def _accepts(
    check: Callable[[Mapping[str, object]], None], permissions: Any, refusal: type[Exception]
) -> bool:
    try:
        check(permissions)
    except refusal:
        return False
    return True


def _gate(permissions: Any) -> bool:
    return _accepts(m2.require_allow_listed, permissions, WithdrawPermissionRejected)


def _m2_deny_list(permissions: Any) -> bool:
    return _accepts(m2.reject_withdraw, permissions, WithdrawPermissionRejected)


def _m13_deny_list(permissions: Any) -> bool:
    return _accepts(m13.reject_withdraw, permissions, WithdrawPermissionError)


@_PROPERTY
@given(permissions=st.one_of(_wild, _compliant, _one_foreign_right()))
def test_gate_equals_the_sr030_rule_on_generated_maps(permissions: dict[str, Any]) -> None:
    assert _gate(permissions) is _spec_allows(permissions)


@_PROPERTY
@given(permissions=_compliant)
def test_gate_accepts_every_compliant_map(permissions: dict[str, Any]) -> None:
    assert _gate(permissions)


@_PROPERTY
@given(permissions=_one_foreign_right())
def test_gate_refuses_every_map_with_one_foreign_right(permissions: dict[str, Any]) -> None:
    assert not _gate(permissions)


@_PROPERTY
@given(permissions=st.one_of(_compliant, _wild))
def test_m13_reads_back_every_map_the_gate_accepts(permissions: dict[str, Any]) -> None:
    assume(_gate(permissions))
    assert _m13_deny_list(permissions)
    snapshot = PermissionSnapshot.model_validate(
        {"fetched_at": _NOW, "uid": "1", "permissions": permissions}
    )
    stored = snapshot.permissions.model_dump()
    assert {group: list(stored[group]) for group in permissions} == permissions


@_PROPERTY
@given(permissions=st.dictionaries(_names, _json, max_size=4))
def test_m2_and_m13_deny_lists_agree_on_generated_maps(permissions: dict[str, Any]) -> None:
    assert _m2_deny_list(permissions) is _m13_deny_list(permissions)


_DENY_LIST_CASES: list[Case] = [
    *JSON_CASES,
    *KNOWN_GAPS,
    *((c[0], c[1], c[2]) for c in EXACT_WITHDRAW),
]


@pytest.mark.parametrize(
    ("permissions", "allowed"),
    [(c[1], c[2]) for c in _DENY_LIST_CASES],
    ids=[c[0] for c in _DENY_LIST_CASES],
)
def test_m2_and_m13_deny_lists_agree_on_the_shared_corpus(
    permissions: dict[str, Any], allowed: bool
) -> None:
    assert _m2_deny_list(permissions) is allowed
    assert _m13_deny_list(permissions) is allowed
