"""Unit tests for tools/ci/run_security_local.py (E02-X02).

Focus: the aggregation/reporting logic and the "unrunnable tool is SKIPPED,
never silently treated as clean" behaviour required by the ticket. Actual
scanner invocation is exercised via monkeypatched `shutil.which` /
`subprocess.run` -- no real semgrep/bandit/gitleaks/pnpm process is spawned,
so this suite needs no network and no installed scanners.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.ci.run_security_local import (
    ToolResult,
    main,
    run_bandit,
    run_gitleaks,
    run_license_check,
    run_npm_audit,
    run_pip_audit,
    run_semgrep,
)
from tools.ci.run_security_local import _run as real_run

PNPM_CLEAN = Path(__file__).resolve().parent / "fixtures" / "pnpm-audit" / "pnpm-12.5.1-clean.json"


def _npm_audit_with_pnpm_output(tmp_path: Path, rc: int, stdout: str, stderr: str) -> ToolResult:
    """run_npm_audit with pnpm faked (no network); the gate on its report runs for real."""

    def fake_run(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
        if cmd[0] == "pnpm":
            return subprocess.CompletedProcess(cmd, rc, stdout, stderr)
        return real_run(cmd, cwd)

    with (
        patch("tools.ci.run_security_local._which", return_value="/usr/bin/pnpm"),
        patch("tools.ci.run_security_local._run", side_effect=fake_run),
    ):
        return run_npm_audit(tmp_path)


def test_run_semgrep_skips_when_binary_missing(tmp_path: Path) -> None:
    with patch("tools.ci.run_security_local._which", return_value=None):
        result = run_semgrep(tmp_path)
    assert result.status == "SKIPPED"
    assert "semgrep" in result.name
    assert "not installed" in result.detail


def test_run_bandit_skips_when_binary_missing(tmp_path: Path) -> None:
    with patch("tools.ci.run_security_local._which", return_value=None):
        result = run_bandit(tmp_path)
    assert result.status == "SKIPPED"
    assert "bandit" in result.detail


def test_run_pip_audit_skips_when_uv_missing(tmp_path: Path) -> None:
    def fake_which(name: str) -> str | None:
        return "/usr/bin/pip-audit" if name == "pip-audit" else None

    with patch("tools.ci.run_security_local._which", side_effect=fake_which):
        result = run_pip_audit(tmp_path)
    assert result.status == "SKIPPED"
    assert "uv" in result.detail


def test_run_npm_audit_skips_when_pnpm_missing(tmp_path: Path) -> None:
    with patch("tools.ci.run_security_local._which", return_value=None):
        result = run_npm_audit(tmp_path)
    assert result.status == "SKIPPED"


def test_run_npm_audit_hands_the_gate_pnpms_empty_report_verbatim(tmp_path: Path) -> None:
    # pnpm prints no report when the registry gives it no answer (#3494). The gate must judge
    # that empty file as it does in CI (CI-SEC-005, "is empty"), not a stand-in document, and
    # the result carries pnpm's stderr, which says why.
    result = _npm_audit_with_pnpm_output(tmp_path, 1, "", "ERR_PNPM_AUDIT_BAD_RESPONSE\n")
    assert (tmp_path / "npm-audit.json").read_text(encoding="utf-8") == ""
    assert result.status == "FAIL"
    assert "CI-SEC-005: npm-audit: " in result.detail
    assert "is empty: pnpm audit wrote no report" in result.detail
    assert result.detail.endswith("ERR_PNPM_AUDIT_BAD_RESPONSE\n")


def test_run_npm_audit_passes_pnpms_clean_report_to_the_gate(tmp_path: Path) -> None:
    clean = PNPM_CLEAN.read_text(encoding="utf-8")
    result = _npm_audit_with_pnpm_output(tmp_path, 0, clean, "")
    assert (tmp_path / "npm-audit.json").read_text(encoding="utf-8") == clean
    assert (result.status, result.detail) == ("PASS", "security_gate[npm-audit]: OK\n")


def test_run_gitleaks_skips_when_no_binary_and_no_docker(tmp_path: Path) -> None:
    with patch("tools.ci.run_security_local._which", return_value=None):
        result = run_gitleaks(tmp_path)
    assert result.status == "SKIPPED"
    assert "not run: no docker" in result.detail


def test_run_license_check_skips_when_venv_missing(tmp_path: Path) -> None:
    # Regression (originating case: QA defect #1563 P1): this must not depend
    # on whether services/api/.venv happens to exist on the machine running
    # the suite -- CI runners that have already run `uv sync` (e.g. a prior
    # backend job step) leave a real venv behind, which previously made this
    # test flip from SKIPPED to PASS/FAIL depending on execution order instead
    # of exercising the "venv missing" branch it claims to cover. Patch
    # `Path.exists` so the assertion is deterministic regardless of the real
    # filesystem state.
    def fake_which(name: str) -> str | None:
        return "/usr/bin/pnpm" if name == "pnpm" else None

    # Use an isolated REPO_ROOT with no services/api/.venv so this test is not
    # sensitive to whether the developer/CI machine happens to have a real
    # backend venv checked out (regression for E02-X02-B1 defect #2).
    with (
        patch("tools.ci.run_security_local._which", side_effect=fake_which),
        patch("tools.ci.run_security_local.REPO_ROOT", tmp_path),
    ):
        result = run_license_check(tmp_path)
    assert result.status == "SKIPPED"
    assert ".venv" in result.detail


def test_main_returns_zero_when_all_tools_skipped() -> None:
    skip = ToolResult("stub", "SKIPPED", "not installed")
    with (
        patch("tools.ci.run_security_local.run_semgrep", return_value=skip),
        patch("tools.ci.run_security_local.run_bandit", return_value=skip),
        patch("tools.ci.run_security_local.run_pip_audit", return_value=skip),
        patch("tools.ci.run_security_local.run_npm_audit", return_value=skip),
        patch("tools.ci.run_security_local.run_gitleaks", return_value=skip),
        patch("tools.ci.run_security_local.run_license_check", return_value=skip),
    ):
        assert main([]) == 0


def test_main_returns_nonzero_when_any_tool_fails() -> None:
    ok = ToolResult("stub-ok", "PASS")
    bad = ToolResult("stub-bad", "FAIL", "CI-SEC-001: blocking finding")
    with (
        patch("tools.ci.run_security_local.run_semgrep", return_value=bad),
        patch("tools.ci.run_security_local.run_bandit", return_value=ok),
        patch("tools.ci.run_security_local.run_pip_audit", return_value=ok),
        patch("tools.ci.run_security_local.run_npm_audit", return_value=ok),
        patch("tools.ci.run_security_local.run_gitleaks", return_value=ok),
        patch("tools.ci.run_security_local.run_license_check", return_value=ok),
    ):
        assert main([]) == 1
