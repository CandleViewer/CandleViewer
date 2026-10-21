"""The shared C-2.8 / SR-030a deny-list kernel (#2240): one predicate behind M2 and M13.

`grants_fund_right` gives the bare predicate's verdict on the shared corpus, the one the M13 model,
the M2 gate and migration 0019's CHECK are held to. It refuses, before its JSON round trip, what
that round trip would silently change: a key that is no string (`{None: ["Withdraw"], "null": []}`
would read as `{"null": []}`) and nesting past its bound.
"""

from __future__ import annotations

import ast
import sys
from collections.abc import Callable
from functools import reduce
from pathlib import Path
from typing import Any

import pytest

from candleviewer.accounts import _permissions as m13
from candleviewer.accounts.errors import WithdrawPermissionError
from candleviewer.domain import key_permissions as kernel
from candleviewer.domain.key_permissions import (
    FORBIDDEN_TOKENS,
    MAX_DEPTH,
    PermissionsUnreadable,
    grants_fund_right,
)
from candleviewer.secrets import _permissions as m2
from candleviewer.secrets.errors import WithdrawPermissionRejected
from tests.unit.accounts._permission_cases import (
    EXACT_WITHDRAW,
    JSON_CASES,
    KNOWN_GAPS,
    Case,
    non_json_cases,
    non_string_key_cases,
)

_CASES: list[Case] = [*JSON_CASES, *KNOWN_GAPS, *((c[0], c[1], c[2]) for c in EXACT_WITHDRAW)]


def _nested(depth: int, leaf: object, wrap: str = "list") -> dict[str, object]:
    """A permissions object whose deepest container sits `depth` levels below it."""
    if wrap == "list":
        return {"Affiliate": reduce(lambda inner, _: [inner], range(depth), leaf)}
    return {"Affiliate": reduce(lambda inner, _: {"Affiliate": inner}, range(depth), leaf)}


def _cycle() -> dict[str, object]:
    permissions: dict[str, object] = {}
    permissions["Affiliate"] = [permissions]
    return permissions


_UNREADABLE: list[tuple[str, Any]] = [
    *non_json_cases(),
    *non_string_key_cases(),
    ("too_deep_lists", _nested(MAX_DEPTH + 1, "Order")),
    ("too_deep_objects", _nested(MAX_DEPTH + 1, [], wrap="object")),
    ("cycle", _cycle()),
]


def test_forbidden_tokens_are_the_c28_rights() -> None:
    assert FORBIDDEN_TOKENS == ("withdraw", "transfer")


@pytest.mark.parametrize(
    ("permissions", "allowed"), [(c[1], c[2]) for c in _CASES], ids=[c[0] for c in _CASES]
)
def test_grants_fund_right_matches_the_shared_corpus(
    permissions: dict[str, Any], allowed: bool
) -> None:
    assert grants_fund_right(permissions) is not allowed


@pytest.mark.parametrize(
    "permissions", [c[1] for c in _UNREADABLE], ids=[c[0] for c in _UNREADABLE]
)
def test_unreadable_permissions_are_refused_whatever_they_say(permissions: Any) -> None:
    with pytest.raises(PermissionsUnreadable) as refused:
        grants_fund_right(permissions)
    assert str(refused.value) == "permissions_unreadable"  # never a part of the input


@pytest.mark.parametrize(("right", "granted"), [("Withdraw", True), ("Order", False)])
def test_nesting_at_the_bound_is_judged_and_one_deeper_is_refused(
    right: str, granted: bool
) -> None:
    assert grants_fund_right(_nested(MAX_DEPTH, right)) is granted
    with pytest.raises(PermissionsUnreadable):
        grants_fund_right(_nested(MAX_DEPTH + 1, right))


def _verdict(outcome: bool | None) -> Callable[[object], bool]:
    """A stand-in kernel predicate: `True`/`False` as its verdict, `None` as unreadable."""

    def grants(permissions: object) -> bool:
        seen.append(permissions)
        if outcome is None:
            raise PermissionsUnreadable
        return outcome

    seen: list[object] = []
    return grants


@pytest.mark.parametrize(
    ("outcome", "m13_error", "m2_error"),
    [
        (True, "key_withdraw_permission", "key_withdraw_permission"),
        (None, "key_withdraw_permission", "snapshot_invalid"),
        (False, None, None),
    ],
    ids=["grants", "unreadable", "grants_nothing"],
)
def test_m2_and_m13_follow_the_one_kernel(
    monkeypatch: pytest.MonkeyPatch,
    outcome: bool | None,
    m13_error: str | None,
    m2_error: str | None,
) -> None:
    """Neither module keeps a copy of the rule: with the kernel's predicate replaced, both
    wrappers follow it, each mapping its verdict to its own error."""
    monkeypatch.setattr(kernel, "grants_fund_right", _verdict(outcome))
    for wrapper, refusal, code in (
        (m13.reject_withdraw, WithdrawPermissionError, m13_error),
        (m2.reject_withdraw, WithdrawPermissionRejected, m2_error),
    ):
        if code is None:
            wrapper({"ContractTrade": ["Order"]})
            continue
        with pytest.raises(refusal) as refused:
            wrapper({"ContractTrade": ["Order"]})
        assert str(refused.value) == code
    assert m13.FORBIDDEN_TOKENS is kernel.FORBIDDEN_TOKENS


def test_the_kernel_imports_only_the_standard_library() -> None:
    """`candleviewer.domain` imports no other `candleviewer` module (its package docstring), so
    M2 and M13 may both import the kernel without importing each other (C-3.2)."""
    tree = ast.parse(Path(kernel.__file__).read_text(encoding="utf-8"))
    roots = {
        a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names
    }
    froms = [n for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
    assert all(n.level == 0 and n.module for n in froms)
    roots |= {str(n.module).split(".")[0] for n in froms}
    assert roots <= sys.stdlib_module_names
