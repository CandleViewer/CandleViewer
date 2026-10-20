"""tests/lint_statecharts/test_lint_statecharts.py — E50-T11.

One failing fixture per CV-LINT-* rule (json/ for machine-JSON rules,
ast/ for AST rules), plus the three acceptance-criteria scenarios from the
ticket: each rule rejects its fixture, the warning rule doesn't fail the
run, and a clean tree exits 0.

Run: `python -m pytest tests/lint_statecharts -q` (no network, no I/O
outside this repo's own tree — stdlib + the module under test only).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools"))

import lint_statecharts as lint

FIXTURES = Path(__file__).resolve().parent / "fixtures"
JSON_FIXTURES = FIXTURES / "json"
AST_FIXTURES = FIXTURES / "ast"

# rule -> fixture file name (JSON rules)
JSON_RULE_FIXTURES = {
    "CV-LINT-POLICY": "CV-LINT-POLICY_bad.machine.json",
    "CV-LINT-FALLTHROUGH": "CV-LINT-FALLTHROUGH_bad.machine.json",
    "CV-LINT-ALWAYS": "CV-LINT-ALWAYS_bad.machine.json",
    "CV-LINT-KILL-ANCESTOR": "CV-LINT-KILL-ANCESTOR_bad.machine.json",
    "CV-LINT-REENTER": "CV-LINT-REENTER_bad.machine.json",
    "CV-LINT-TIMER": "CV-LINT-TIMER_bad.machine.json",
}

# rule -> fixture file relative path (AST rules)
AST_RULE_FIXTURES = {
    "CV-LINT-IMPORT": "CV-LINT-IMPORT_bad.py",
    "CV-LINT-REMINT": "CV-LINT-REMINT_bad.py",
    "CV-LINT-PRIORITY": "CV-LINT-PRIORITY_bad.py",
    "CV-LINT-HOTPATH": "candleviewer/book/CV-LINT-HOTPATH_bad.py",
    "CV-LINT-NO-SELF-SEND": "statechart/bindings/CV-LINT-NO-SELF-SEND_bad.py",
    "CV-LINT-SELF-RECEIPT": "CV-LINT-SELF-RECEIPT_bad.py",
    "CV-LINT-CORO": "statechart/bindings/CV-LINT-CORO_bad.py",
    "CV-LINT-SYSTEM-EVENT": "CV-LINT-SYSTEM-EVENT_bad.py",
    "CV-LINT-RESTORE": "CV-LINT-RESTORE_bad.py",
    "CV-LINT-DRAIN": "CV-LINT-DRAIN_bad.py",
    "CV-LINT-ERROREVENT": "statechart/bindings/CV-LINT-ERROREVENT_bad.py",
    "CV-LINT-INSPECTOR": "statechart/bindings/CV-LINT-INSPECTOR_bad.py",
}


@pytest.mark.parametrize("rule,fixture_name", sorted(JSON_RULE_FIXTURES.items()))
def test_json_rule_rejects_its_fixture(rule: str, fixture_name: str) -> None:
    path = JSON_FIXTURES / fixture_name
    findings = lint.lint_machine_file(path)
    matches = [f for f in findings if f.rule == rule]
    assert matches, f"{rule} did not fire on {fixture_name}: {findings}"
    assert matches[0].severity == lint.SEVERITY_ERROR
    assert str(path) in matches[0].file or path.name in matches[0].file


@pytest.mark.parametrize("rule,fixture_name", sorted(AST_RULE_FIXTURES.items()))
def test_ast_rule_rejects_its_fixture(rule: str, fixture_name: str) -> None:
    path = AST_FIXTURES / fixture_name
    findings = lint.lint_python_file(path)
    matches = [f for f in findings if f.rule == rule]
    assert matches, f"{rule} did not fire on {fixture_name}: {findings}"
    assert matches[0].severity == lint.SEVERITY_ERROR


def _statechart_importer(root: Path, relative: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True)
    path.write_text("from candleviewer.statechart import factory\n", encoding="utf-8")
    return path


@pytest.mark.parametrize("module", ["clock", "injector", "pacing", "regroup", "runner"])
def test_hotpath_rejects_a_statechart_import_in_a_replay_per_event_module(
    tmp_path: Path, module: str
) -> None:
    """E26-T03: the replay run, its clock and pacing, the regrouping adapter and the injector
    are on the per-event path, listed one by one as in the import-linter contract."""
    path = _statechart_importer(tmp_path, f"candleviewer/replay/{module}.py")
    assert [f.rule for f in lint.lint_python_file(path)] == ["CV-LINT-HOTPATH"]


def test_hotpath_leaves_the_replay_session_service_free_to_drive_its_chart(
    tmp_path: Path,
) -> None:
    """The replay session service beside them drives B12: it imports the statechart package."""
    path = _statechart_importer(tmp_path, "candleviewer/replay/sessions_service.py")
    assert lint.lint_python_file(path) == []


def test_invoke_cycle_warning_does_not_fail() -> None:
    """CV-LINT-INVOKE-CYCLE (W): fires as a warning only, never an error."""
    path = JSON_FIXTURES / "CV-LINT-INVOKE-CYCLE_warn.machine.json"
    findings = lint.lint_machine_file(path)
    matches = [f for f in findings if f.rule == "CV-LINT-INVOKE-CYCLE"]
    assert matches, "CV-LINT-INVOKE-CYCLE did not fire on its fixture"
    assert all(f.severity == lint.SEVERITY_WARNING for f in matches)
    errors = [f for f in findings if f.severity == lint.SEVERITY_ERROR]
    assert not errors, f"warning-only fixture produced error findings: {errors}"


def test_clean_tree_exits_zero(tmp_path: Path) -> None:
    """Scenario: Clean tree -> lint runs on main -> exits 0."""
    machines_dir = tmp_path / "machines"
    machines_dir.mkdir()
    source_root = tmp_path / "src"
    source_root.mkdir()
    exit_code = lint.main(
        [
            "--machines-dir",
            str(machines_dir),
            "--source-root",
            str(source_root),
            "--quiet",
        ]
    )
    assert exit_code == 0


def test_every_error_rule_has_a_fixture() -> None:
    """Self-check: every error-severity rule named in the ticket has exactly
    one fixture wired into this test module (docs/plan/29-statechart-adoption-plan.md §1.6).
    """
    error_rules = {
        "CV-LINT-IMPORT",
        "CV-LINT-POLICY",
        "CV-LINT-FALLTHROUGH",
        "CV-LINT-ALWAYS",
        "CV-LINT-KILL-ANCESTOR",
        "CV-LINT-REENTER",
        "CV-LINT-TIMER",
        "CV-LINT-NO-SELF-SEND",
        "CV-LINT-SELF-RECEIPT",
        "CV-LINT-CORO",
        "CV-LINT-REMINT",
        "CV-LINT-PRIORITY",
        "CV-LINT-SYSTEM-EVENT",
        "CV-LINT-RESTORE",
        "CV-LINT-DRAIN",
        "CV-LINT-ERROREVENT",
        "CV-LINT-INSPECTOR",
        "CV-LINT-HOTPATH",
    }
    covered = set(JSON_RULE_FIXTURES) | set(AST_RULE_FIXTURES)
    missing = error_rules - covered
    assert not missing, f"rules with no fixture: {missing}"
