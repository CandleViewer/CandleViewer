"""Seeded mutants of the M2 allow-list gate (#2270), each killed by its real oracle test.

Repo convention (`test_mutations.py`; AGENTS.md section 6 rule 9 for safety-critical modules):
inject one plausible defect, run an oracle case the suite itself runs, and assert it fails. No
mutation tool is pinned in `uv.lock`, so this is not a tool run.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Callable, Mapping
from types import MappingProxyType

import pytest

from candleviewer.secrets import _permissions as perms
from tests.unit.accounts._permission_cases import KNOWN_GAPS
from tests.unit.credentials_m2 import test_allow_list as oracle

_KILLED = (AssertionError, pytest.fail.Exception)
_REAL = perms.require_allow_listed
_INNER_SPACE = KNOWN_GAPS[0][1]
_Gate = Callable[[Mapping[str, object]], None]


def _install(monkeypatch: pytest.MonkeyPatch, gate: _Gate) -> None:
    monkeypatch.setattr(perms, "require_allow_listed", gate)
    monkeypatch.setattr(oracle, "require_allow_listed", gate)


def _nfkc(value: object) -> object:
    return unicodedata.normalize("NFKC", value).strip() if isinstance(value, str) else value


def _lenient(permissions: Mapping[str, object]) -> None:
    """Mutant: names are NFKC-normalised and stripped before the real check."""
    _REAL(
        {
            str(_nfkc(group)): [_nfkc(r) for r in rights] if isinstance(rights, list) else rights
            for group, rights in permissions.items()
        }
    )


def _empty_grants_nothing(permissions: Mapping[str, object]) -> None:
    """Mutant: the deny-list's exemption; any group holding `[]`, `null` or `""` is skipped."""
    _REAL({g: v for g, v in permissions.items() if v not in ([], None, "")})


def _round_tripped(permissions: Mapping[str, object]) -> None:
    """Mutant: the raw-name check is lost; names are checked only after the JSON round trip."""
    _REAL(json.loads(json.dumps(dict(permissions))))


def test_mutant_widened_allow_list_killed(monkeypatch: pytest.MonkeyPatch) -> None:
    widened = {**perms.ALLOWED_RIGHTS, "Wallet": frozenset({"AccountTransfer"})}
    monkeypatch.setattr(perms, "ALLOWED_RIGHTS", MappingProxyType(widened))
    with pytest.raises(_KILLED):
        oracle.test_gate_refuses_documented_fund_rights({"Wallet": ["AccountTransfer"]})


def test_mutant_group_agnostic_rights_killed(monkeypatch: pytest.MonkeyPatch) -> None:
    every = frozenset().union(*perms.ALLOWED_RIGHTS.values())
    monkeypatch.setattr(perms, "ALLOWED_RIGHTS", dict.fromkeys(perms.ALLOWED_RIGHTS, every))
    with pytest.raises(_KILLED):
        oracle.test_gate_refuses_a_right_permitted_only_in_another_group({"Derivatives": ["Order"]})


@pytest.mark.parametrize("spelling", [" Order", "\uff2frder"])
def test_mutant_lenient_right_matching_killed(
    monkeypatch: pytest.MonkeyPatch, spelling: str
) -> None:
    _install(monkeypatch, _lenient)
    with pytest.raises(_KILLED):
        oracle.test_gate_refuses_a_lookalike_of_a_permitted_right(spelling)


def test_mutant_lenient_group_matching_killed(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, _lenient)
    with pytest.raises(_KILLED):
        oracle.test_gate_refuses_a_non_canonical_group_name("\uff23ontractTrade", ["Order"])


def test_mutant_unbounded_group_name_killed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(perms, "_GROUP_NAME", re.compile(r"[A-Za-z][A-Za-z0-9]*"))
    with pytest.raises(_KILLED):
        oracle.test_gate_bounds_a_group_name_at_64_characters()


@pytest.mark.parametrize(
    ("pattern", "spelling"),
    [(r"\S{1,64}", "With-draw"), (r"(?i:[A-Z][A-Z0-9]{0,63})", "Derivative\u017f")],
    ids=["any_visible", "ignorecase_folds_long_s"],
)
def test_mutant_loose_group_name_rule_killed(
    monkeypatch: pytest.MonkeyPatch, pattern: str, spelling: str
) -> None:
    monkeypatch.setattr(perms, "_GROUP_NAME", re.compile(pattern))
    with pytest.raises(_KILLED):
        oracle.test_gate_refuses_a_non_canonical_group_name(spelling, [])


def test_mutant_empty_group_grants_nothing_killed(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, _empty_grants_nothing)
    with pytest.raises(_KILLED):
        oracle.test_gate_refuses_a_group_that_is_not_a_list(None)


def test_mutant_names_checked_after_the_round_trip_killed(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, _round_tripped)
    with pytest.raises(_KILLED):
        oracle.test_project_snapshot_refuses_a_right_hidden_by_json_key_coercion()


def test_mutant_allow_list_unwired_killed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(perms, "require_allow_listed", lambda _permissions: None)
    with pytest.raises(_KILLED):
        oracle.test_project_snapshot_refuses_a_deny_list_gap(_INNER_SPACE)


def test_mutant_deny_list_unwired_killed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(perms, "reject_withdraw", lambda _permissions: None)
    with pytest.raises(_KILLED):
        oracle.test_deny_list_still_refuses_with_the_allow_list_bypassed(
            monkeypatch, {"Wallet": ["AccountTransfer"]}
        )
