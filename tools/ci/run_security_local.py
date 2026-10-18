#!/usr/bin/env python3
"""E02-X02: `make security` / `pnpm security` local entry point.

Runs every scanner that is runnable on the developer's machine (no CI-only
infrastructure, no docker requirement) and reduces each one's native output
through the same `tools/ci/security_gate.py` policy that CI uses, so a clean
local run and a green CI `security` lane mean the same thing.

Scope per the ticket ("A single `make security` / `pnpm security` entry
point running everything runnable locally"):
  - semgrep (registry packs + .semgrep/ custom rule pack + rule --test)
  - bandit (services/api/candleviewer)
  - pip-audit (services/api locked deps)
  - npm audit / pnpm audit
  - gitleaks (working tree; full-history scan is CI-only, needs the
    pinned container image -- see .github/workflows/_job-security.yml)
  - license-check (pnpm licenses + python env licences)

Any tool that cannot run in the current environment (e.g. semgrep does not
ship Windows wheels, docker not installed) is reported as SKIPPED with the
reason, never silently treated as passing (mirrors CI-SEC-005: an unrunnable
scanner is not a clean scanner). The process exits non-zero if any *runnable*
tool fails or is blocked by security_gate.py.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
GATE = REPO_ROOT / "tools" / "ci" / "security_gate.py"


@dataclass
class ToolResult:
    name: str
    status: str  # "PASS" | "FAIL" | "SKIPPED"
    detail: str = ""


def _run(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    # Windows CreateProcess cannot exec a .cmd/.bat shim directly (pnpm/npm
    # on Windows resolve to pnpm.CMD via shutil.which); resolve the
    # executable's full path so subprocess can invoke the shim without a
    # shell, keeping argv a list on every platform (no shell=True anywhere).
    resolved = shutil.which(cmd[0]) or cmd[0]
    return subprocess.run(
        [resolved, *cmd[1:]],
        cwd=str(cwd or REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )


def _which(name: str) -> str | None:
    return shutil.which(name)


def run_semgrep(tmpdir: Path) -> ToolResult:
    if _which("semgrep") is None:
        return ToolResult(
            "semgrep",
            "SKIPPED",
            "semgrep not installed in this environment (no Windows wheel; "
            "install via WSL/Linux/macOS or CI) -- rule pack lives at .semgrep/",
        )
    # Rule-pack self-test first: a rule that never fires on its own fixtures
    # is worse than no rule (ticket "Technical notes / design"). `semgrep
    # --test` hangs/misattributes lines against a directory config on this
    # toolchain (QA bug #1559 defects #1/#3), so the fixtures are checked via
    # `semgrep scan --json` instead (tools/ci/check_semgrep_rule_tests.py).
    test_proc = _run([sys.executable, "tools/ci/check_semgrep_rule_tests.py"])
    if test_proc.returncode != 0:
        return ToolResult("semgrep (rule-tests)", "FAIL", test_proc.stdout + test_proc.stderr)

    sarif = tmpdir / "semgrep.sarif"
    scan_proc = _run(
        [
            "semgrep",
            "scan",
            "--config",
            "p/python",
            "--config",
            "p/secrets",
            "--config",
            "p/sql-injection",
            "--config",
            ".semgrep",
            "--sarif",
            "--output",
            str(sarif),
        ]
    )
    if scan_proc.returncode > 1:
        return ToolResult("semgrep", "FAIL", f"engine error (exit {scan_proc.returncode})")
    if not sarif.exists():
        return ToolResult("semgrep", "FAIL", "CI-SEC-005: no SARIF produced")
    gate_proc = _run([sys.executable, str(GATE), "--tool", "semgrep", "--report", str(sarif)])
    status = "PASS" if gate_proc.returncode == 0 else "FAIL"
    return ToolResult("semgrep", status, gate_proc.stdout + gate_proc.stderr)


def run_bandit(tmpdir: Path) -> ToolResult:
    if _which("bandit") is None:
        return ToolResult("bandit", "SKIPPED", "bandit not installed (pip install bandit[sarif])")
    sarif = tmpdir / "bandit.sarif"
    _run(
        [
            "bandit",
            "-c",
            "services/api/pyproject.toml",
            "-r",
            "services/api/candleviewer",
            "-f",
            "sarif",
            "-o",
            str(sarif),
            "-ll",
        ]
    )
    if not sarif.exists():
        return ToolResult("bandit", "FAIL", "CI-SEC-005: no SARIF produced")
    gate_proc = _run([sys.executable, str(GATE), "--tool", "bandit", "--report", str(sarif)])
    status = "PASS" if gate_proc.returncode == 0 else "FAIL"
    return ToolResult("bandit", status, gate_proc.stdout + gate_proc.stderr)


def run_pip_audit(tmpdir: Path) -> ToolResult:
    if _which("pip-audit") is None:
        return ToolResult("pip-audit", "SKIPPED", "pip-audit not installed (pip install pip-audit)")
    if _which("uv") is None:
        return ToolResult(
            "pip-audit",
            "SKIPPED",
            "uv not installed -- cannot export locked requirements",
        )
    req = tmpdir / "api-requirements.txt"
    export_proc = _run(
        [
            "uv",
            "export",
            "--frozen",
            "--no-hashes",
            "--all-groups",
            "--no-emit-project",
            "--project",
            "services/api",
            "-o",
            str(req),
        ]
    )
    if export_proc.returncode != 0:
        return ToolResult("pip-audit", "FAIL", export_proc.stdout + export_proc.stderr)
    report = tmpdir / "pip-audit.json"
    _run(
        [
            "pip-audit",
            "-r",
            str(req),
            "--no-deps",
            "--format",
            "json",
            "--output",
            str(report),
            "--progress-spinner",
            "off",
        ]
    )
    if not report.exists():
        return ToolResult("pip-audit", "FAIL", "CI-SEC-005: no report produced")
    gate_proc = _run([sys.executable, str(GATE), "--tool", "pip-audit", "--report", str(report)])
    status = "PASS" if gate_proc.returncode == 0 else "FAIL"
    return ToolResult("pip-audit", status, gate_proc.stdout + gate_proc.stderr)


def run_npm_audit(tmpdir: Path) -> ToolResult:
    if _which("pnpm") is None:
        return ToolResult("npm-audit", "SKIPPED", "pnpm not installed")
    report = tmpdir / "npm-audit.json"
    proc = _run(["pnpm", "audit", "--json"])
    # Verbatim, as CI's step writes it (#3494): pnpm prints no report when the registry gives it
    # no answer, and the gate fails that empty file (CI-SEC-005) and points at pnpm's stderr,
    # which CI's step log shows and this result carries.
    report.write_text(proc.stdout, encoding="utf-8")
    gate_proc = _run([sys.executable, str(GATE), "--tool", "npm-audit", "--report", str(report)])
    status = "PASS" if gate_proc.returncode == 0 else "FAIL"
    detail = gate_proc.stdout + gate_proc.stderr
    if not proc.stdout.strip():
        detail += proc.stderr
    return ToolResult("npm-audit", status, detail)


def run_gitleaks(tmpdir: Path) -> ToolResult:
    docker = _which("docker")
    gitleaks = _which("gitleaks")
    report = tmpdir / "gitleaks.json"
    if gitleaks is not None:
        _run(
            [
                "gitleaks",
                "detect",
                "--source=.",
                "--no-git",
                "--config=.gitleaks.toml",
                "--redact",
                "-f",
                "json",
                "-r",
                str(report),
            ]
        )
    elif docker is not None:
        _run(
            [
                "docker",
                "run",
                "--rm",
                "-v",
                f"{REPO_ROOT}:/repo",
                "zricethezav/gitleaks:v8.21.2",
                "detect",
                "--source=/repo",
                "--no-git",
                "--config=/repo/.gitleaks.toml",
                "--redact",
                "-f",
                "json",
                "-r",
                "/repo/gitleaks.json",
            ]
        )
        moved = REPO_ROOT / "gitleaks.json"
        if moved.exists():
            report.write_text(moved.read_text(encoding="utf-8"), encoding="utf-8")
            moved.unlink()
    else:
        return ToolResult(
            "gitleaks",
            "SKIPPED",
            "neither the gitleaks binary nor docker is installed locally -- not run: no docker",
        )
    if not report.exists():
        report.write_text("[]", encoding="utf-8")
    gate_proc = _run([sys.executable, str(GATE), "--tool", "gitleaks", "--report", str(report)])
    status = "PASS" if gate_proc.returncode == 0 else "FAIL"
    return ToolResult("gitleaks", status, gate_proc.stdout + gate_proc.stderr)


def run_license_check(tmpdir: Path) -> ToolResult:
    if _which("pnpm") is None:
        return ToolResult("license-check", "SKIPPED", "pnpm not installed")
    py_bin = REPO_ROOT / "services" / "api" / ".venv" / "Scripts" / "python.exe"
    if not py_bin.exists():
        py_bin = REPO_ROOT / "services" / "api" / ".venv" / "bin" / "python"
    if not py_bin.exists():
        return ToolResult(
            "license-check",
            "SKIPPED",
            "services/api/.venv missing -- run `uv sync --project services/api` first",
        )
    pnpm_licenses = tmpdir / "pnpm-licenses.json"
    proc = _run(["pnpm", "licenses", "list", "--json", "--prod"])
    pnpm_licenses.write_text(proc.stdout or "[]", encoding="utf-8")
    combined = tmpdir / "licenses.json"
    collect_proc = _run(
        [
            str(py_bin),
            "tools/ci/collect_licenses.py",
            "--python-env",
            "--pnpm-licenses",
            str(pnpm_licenses),
            "--out",
            str(combined),
        ]
    )
    if collect_proc.returncode != 0:
        return ToolResult("license-check", "FAIL", collect_proc.stdout + collect_proc.stderr)
    gate_proc = _run(
        [sys.executable, str(GATE), "--tool", "license-scan", "--report", str(combined)]
    )
    status = "PASS" if gate_proc.returncode == 0 else "FAIL"
    return ToolResult("license-check", status, gate_proc.stdout + gate_proc.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)

    results: list[ToolResult] = []
    with tempfile.TemporaryDirectory(prefix="cv-security-") as tmp:
        tmpdir = Path(tmp)
        results.append(run_semgrep(tmpdir))
        results.append(run_bandit(tmpdir))
        results.append(run_pip_audit(tmpdir))
        results.append(run_npm_audit(tmpdir))
        results.append(run_gitleaks(tmpdir))
        results.append(run_license_check(tmpdir))

    print()
    print("=" * 72)
    print("security_gate local summary")
    print("=" * 72)
    failed = False
    for r in results:
        print(f"{r.status:8s} {r.name}")
        if r.detail:
            for line in r.detail.strip().splitlines():
                print(f"         {line}")
        if r.status == "FAIL":
            failed = True

    skipped = [r.name for r in results if r.status == "SKIPPED"]
    if skipped:
        print()
        print(f"not run locally (unrunnable on this machine): {', '.join(skipped)}")

    print()
    if failed:
        print("security: BLOCKED -- see failures above")
        return 1
    print(
        "security: OK (skipped tools are not evidence of a clean scan -- see CI for full coverage)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
