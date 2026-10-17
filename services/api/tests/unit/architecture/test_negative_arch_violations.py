"""Negative tests: each of E02-T06's acceptance-criteria violations must be
caught by the arch gate, citing the correct rule id, and the clean tree must
pass. Each test patches exactly one file in-place, runs the relevant checker
as a subprocess, asserts a non-zero exit + expected rule id in the output,
then restores the file in a `finally` block — never leaving the tree dirty.

No network; filesystem changes are scoped to files already tracked in the
repo and are always restored (C-13.5/C-13.7).
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[5]


def _run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        shell=sys.platform == "win32",
        timeout=120,
    )


def resolve_depcruise(repo_root: Path) -> list[str] | None:
    """Return a command prefix that runs the *locally installed, lockfile-pinned*
    dependency-cruiser, or None if it is not installed.

    Never returns a bare `npx` form: `npx <pkg>` can fetch an arbitrary
    registry package (typosquat risk + network in tests, C-13.5). Resolution
    order: explicit `node_modules/.bin/depcruise[.cmd]` path, then
    `pnpm exec depcruise` only if that local bin exists (pnpm exec does not
    download).
    """
    bin_dir = repo_root / "node_modules" / ".bin"
    names = ["depcruise.cmd", "depcruise"] if sys.platform == "win32" else ["depcruise"]
    for name in names:
        candidate = bin_dir / name
        if candidate.is_file():
            return [str(candidate)]
    pnpm = shutil.which("pnpm")
    if pnpm and (repo_root / "node_modules" / "dependency-cruiser").is_dir():
        return [pnpm, "exec", "depcruise"]
    return None


def _depcruise(*args: str) -> subprocess.CompletedProcess[str]:
    prefix = resolve_depcruise(REPO_ROOT)
    if prefix is None:
        pytest.skip("dependency-cruiser not installed locally; skipping architecture negative test")
    return _run([*prefix, "--config", ".dependency-cruiser.js", *args], cwd=REPO_ROOT)


class _PatchedFile:
    """Context manager: back up a tracked file, restore it on exit."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._raw = path.read_bytes()
        self.backup = self._raw.decode("utf-8")

    def write(self, content: str) -> None:
        self.path.write_text(content, encoding="utf-8")

    def __enter__(self) -> _PatchedFile:
        return self

    def __exit__(self, *exc: object) -> None:
        # Byte-exact restore: a text round-trip rewrites LF as CRLF on Windows.
        self.path.write_bytes(self._raw)


def test_clean_scaffold_passes_import_linter() -> None:
    result = _run(["uv", "run", "lint-imports"], cwd=REPO_ROOT / "services" / "api")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "0 broken" in result.stdout


def test_clean_scaffold_passes_dependency_cruiser() -> None:
    result = _depcruise("packages")
    assert result.returncode == 0, result.stdout + result.stderr


def test_secrets_import_violation_caught_by_c_3_2() -> None:
    """M8 (bars) is not in C-3.2's allow-list for M2 (secrets)."""
    target = REPO_ROOT / "services" / "api" / "candleviewer" / "bars" / "service.py"
    with _PatchedFile(target) as f:
        f.write(f.backup + "\nfrom candleviewer.secrets import SecretsService  # noqa\n")
        result = _run(["uv", "run", "lint-imports"], cwd=REPO_ROOT / "services" / "api")
    assert result.returncode != 0
    assert "BROKEN" in result.stdout
    assert "C-3.2" in result.stdout or "secrets" in result.stdout.lower()


def test_asyncpg_import_outside_storage_caught_by_adr_0003() -> None:
    """E07-T01 acceptance criterion 2: a module outside M10 (storage) that
    imports a storage driver package directly must fail CI, citing ADR-0003."""
    target = REPO_ROOT / "services" / "api" / "candleviewer" / "bars" / "service.py"
    with _PatchedFile(target) as f:
        f.write(f.backup + "\nimport asyncpg  # noqa\n")
        result = _run(["uv", "run", "lint-imports"], cwd=REPO_ROOT / "services" / "api")
    assert result.returncode != 0
    assert "BROKEN" in result.stdout
    assert "ADR-0003" in result.stdout


def test_statechart_import_from_ws_caught_by_c_2_20() -> None:
    """#414 AC 2: `candleviewer.ws` never imports the statechart factory (no `Interpreter`)."""
    target = REPO_ROOT / "services" / "api" / "candleviewer" / "ws" / "machines.py"
    with _PatchedFile(target) as f:
        f.write(f.backup + "\nimport candleviewer.statechart.factory\n")
        result = _run(["uv", "run", "lint-imports"], cwd=REPO_ROOT / "services" / "api")
    assert result.returncode != 0
    line = next(ln for ln in result.stdout.splitlines() if "ws never imports the statechart" in ln)
    assert line.startswith("C-2.20") and line.endswith("BROKEN")


def test_react_in_chart_engine_core_caught_by_c_2_16() -> None:
    target = REPO_ROOT / "packages" / "chart-engine" / "src" / "core" / "handle.ts"
    with _PatchedFile(target) as f:
        f.write('import React from "react";\n' + f.backup)
        result = _depcruise("--output-type", "err-long", "packages")
    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert "chart-engine-no-react" in combined
    assert "C-2.16" in combined


def test_deep_import_violation_caught() -> None:
    target = REPO_ROOT / "packages" / "protocol" / "src" / "index.ts"
    with _PatchedFile(target) as f:
        f.write(f.backup + '\nexport { Placeholder } from "../../ui/src/primitives/Placeholder";\n')
        result = _depcruise("--output-type", "err-long", "packages")
    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert "no-deep-imports-ui" in combined
    assert "§9 #18" in combined or "Deep import banned" in combined


def test_manifest_table_count_mismatch_fails_drift_test() -> None:
    """Simulates §3 being edited (a module row removed) without updating
    `docs/plan/module-contracts.toml`: the drift test's row-count assertion
    must fail against the edited table."""
    target = REPO_ROOT / "CONSTITUTION.md"
    with _PatchedFile(target) as f:
        backup = f.backup
        # Delete the M24 row only (last backend table row) to simulate an
        # un-mirrored §3 edit.
        lines = backup.splitlines()
        patched = [line for line in lines if not line.startswith("| M24 |")]
        f.write("\n".join(patched))
        result = _run(
            [
                "uv",
                "run",
                "pytest",
                "tests/unit/architecture/test_module_contracts_drift.py::test_backend_module_count_matches",
                "--no-cov",
                "-q",
            ],
            cwd=REPO_ROOT / "services" / "api",
        )
    assert result.returncode != 0, result.stdout + result.stderr
    assert "expected 24" in result.stdout
