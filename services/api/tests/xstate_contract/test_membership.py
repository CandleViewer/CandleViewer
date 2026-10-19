"""Gherkin "Suite membership is complete" (E50-T31, 29 §1.7)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.xstate_contract.membership import (
    _CATALOGUE,
    catalogue_invariants,
    check_ledger,
    missing_contract_modules,
)

_HERE = Path(__file__).resolve().parent
_MACHINES = _HERE.parents[1] / "candleviewer" / "statechart" / "machines"


def _suite(tmp_path: Path, *modules: str) -> Path:
    d = tmp_path / "suite"
    d.mkdir()
    for m in modules:
        (d / m).write_text("", "utf-8")
    return d


def _machines(tmp_path: Path, *charts: str) -> Path:
    d = tmp_path / "machines"
    d.mkdir()
    for c in charts:
        (d / c).write_text("{}", "utf-8")
    return d


def test_membership_new_machine_without_contract_module_is_reported(tmp_path: Path) -> None:
    machines = _machines(tmp_path, "B10.alert.machine.json", "B21.newcomer.machine.json")
    suite = _suite(tmp_path, "test_b10_alert.py")
    assert missing_contract_modules(machines, suite) == ["B21.newcomer.machine.json"]


@pytest.mark.parametrize("module", ["test_b10_alert.py", "test_b10_alert_extra.py", "test_b10.py"])
def test_membership_accepts_module_spellings(tmp_path: Path, module: str) -> None:
    machines = _machines(tmp_path, "B10.alert.machine.json")
    assert missing_contract_modules(machines, _suite(tmp_path, module)) == []


def test_membership_rejects_badly_named_chart(tmp_path: Path) -> None:
    machines = _machines(tmp_path, "alert.machine.json")
    assert missing_contract_modules(machines, _suite(tmp_path)) == [
        "alert.machine.json (name is not BNN.<id>.machine.json)"
    ]


def test_membership_committed_machines_are_all_members() -> None:
    assert missing_contract_modules(_MACHINES, _HERE) == []


def test_membership_collection_hook_raises_usage_error(tmp_path: Path) -> None:
    """The conftest collection hook's check raises a usage error (collection
    fails) rather than producing a failing test."""
    from tests.xstate_contract.conftest import check_membership

    machines = _machines(tmp_path, "B21.newcomer.machine.json")
    with pytest.raises(pytest.UsageError, match=r"B21.newcomer"):
        check_membership(machines, _HERE)
    check_membership(_MACHINES, _HERE)  # the committed suite is complete


def test_catalogue_invariants_parses_every_machine() -> None:
    cat = _HERE.parents[3] / "docs" / "plan" / "28-statechart-catalogue.md"
    assert all(catalogue_invariants(cat, n) for n in range(1, 21))


def _proves_it() -> None: ...


def test_a_ledger_entry_may_name_several_tests_and_each_must_exist() -> None:
    """#3804 DL2: an invariant proven by more than one test lists them all, and renaming or
    deleting any of them fails the ledger."""
    ledger: dict[str, str | tuple[str, ...]]
    ledger = dict.fromkeys(catalogue_invariants(_CATALOGUE, 1), "deferred:E29")
    first = next(iter(ledger))
    ledger[first] = (
        "test_proves_it",
        "test_b01_order.py::test_b01_invariant_ledger_matches_catalogue",
    )
    check_ledger(1, ledger, {"test_proves_it": _proves_it})
    ledger[first] = ("test_proves_it", "test_b01_order.py::test_no_such_test")
    with pytest.raises(AssertionError, match="test_no_such_test"):
        check_ledger(1, ledger, {"test_proves_it": _proves_it})
