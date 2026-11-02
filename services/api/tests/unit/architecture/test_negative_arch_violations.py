"""Negative tests: each of E02-T06's acceptance-criteria violations must be
caught by the arch gate, citing the correct rule id, and the clean tree must
pass. Every violation is injected into a scratch COPY under `tmp_path` and the
checker is run against that copy (cwd and config inside `tmp_path`, import-linter
with `--no-cache`). No test ever opens a tracked file of the checkout for
writing, so a SIGKILL or timeout mid-test cannot leave the tree dirty and the
checkout's `.import_linter_cache` is never shared or written (C-13.5/C-13.7,
#2902). An autouse guard asserts the checkout is byte-identical afterwards.

Each negative case has a positive control (the unmodified copy passes), so a
copy that silently stopped evaluating a contract cannot make a case pass.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[5]
API_ROOT = REPO_ROOT / "services" / "api"
ARCH_TESTS = Path(__file__).resolve().parent

# Every tracked file a negative case injects into (in its copy).
_GUARDED = (
    API_ROOT / "candleviewer" / "bars" / "service.py",
    API_ROOT / "candleviewer" / "oms" / "routing.py",
    API_ROOT / "candleviewer" / "ws" / "machines.py",
    REPO_ROOT / "packages" / "chart-engine" / "src" / "core" / "handle.ts",
    REPO_ROOT / "packages" / "protocol" / "src" / "index.ts",
    REPO_ROOT / "CONSTITUTION.md",
    API_ROOT / ".importlinter",
)
_CHECKOUT_CACHE = API_ROOT / ".import_linter_cache"

_IGNORE_PY = shutil.ignore_patterns("__pycache__", "*.pyc")
_IGNORE_TS = shutil.ignore_patterns("coverage", "storybook-static", "*.snap")


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


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture(autouse=True)
def _checkout_untouched() -> Iterator[None]:
    """#2902 done-means: the checkout is byte-identical after each test and no
    test wrote the shared `.import_linter_cache`."""
    before = {p: _digest(p) for p in _GUARDED}
    cache_before = _CHECKOUT_CACHE.exists()
    yield
    assert {p: _digest(p) for p in _GUARDED} == before, "a tracked file was modified"
    assert _CHECKOUT_CACHE.exists() == cache_before, "test touched the checkout import-linter cache"


def _lint_imports_cmd() -> list[str]:
    """The lockfile-installed `lint-imports` of this interpreter's venv (no `uv run`,
    which would sync/touch the checkout). `--no-cache`: never read or write a cache."""
    exe = Path(sys.executable).parent / (
        "lint-imports.exe" if sys.platform == "win32" else "lint-imports"
    )
    found = str(exe) if exe.is_file() else shutil.which("lint-imports")
    if found is None:
        pytest.fail("lint-imports is not installed in the test environment")
    return [found, "--no-cache"]


@pytest.fixture
def api_copy(tmp_path: Path) -> Path:
    """Scratch copy of `services/api` holding what import-linter needs: the
    `candleviewer` and `cvdev` packages plus `.importlinter`."""
    root = tmp_path / "api"
    root.mkdir()
    for pkg in ("candleviewer", "cvdev"):
        shutil.copytree(API_ROOT / pkg, root / pkg, ignore=_IGNORE_PY)
    shutil.copy2(API_ROOT / ".importlinter", root / ".importlinter")
    return root


def _lint(root: Path) -> subprocess.CompletedProcess[str]:
    return _run([*_lint_imports_cmd(), "--config", str(root / ".importlinter")], cwd=root)


def _append(root: Path, rel: str, text: str) -> None:
    target = root / rel
    assert target.is_file()
    assert root.is_relative_to(Path(root.anchor)) and REPO_ROOT not in target.parents
    target.write_text(target.read_text(encoding="utf-8") + text, encoding="utf-8")


def _assert_clean_then_violate(root: Path, rel: str, text: str) -> subprocess.CompletedProcess[str]:
    """Positive control on the unmodified copy, then inject into the copy and re-run."""
    control = _lint(root)
    assert control.returncode == 0, control.stdout + control.stderr
    assert "0 broken" in control.stdout
    assert "BROKEN" not in control.stdout
    _append(root, rel, text)
    return _lint(root)


def test_clean_scaffold_passes_import_linter(api_copy: Path) -> None:
    result = _lint(api_copy)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "0 broken" in result.stdout
    # The contracts really evaluated modules from the copy, not an installed checkout.
    assert "Contracts:" in result.stdout and "kept" in result.stdout


def test_lint_runs_against_the_copy_not_the_checkout(api_copy: Path) -> None:
    """An injected import in the copy must be seen; one in the checkout never is."""
    result = _assert_clean_then_violate(
        api_copy, "candleviewer/bars/service.py", "\nimport asyncpg  # noqa\n"
    )
    assert result.returncode != 0
    assert not (api_copy / ".import_linter_cache").exists()


@pytest.fixture
def ts_copy(tmp_path: Path) -> Path:
    """Scratch copy of the TS sources dependency-cruiser needs for `packages`."""
    root = tmp_path / "ts"
    root.mkdir()
    for name in (".dependency-cruiser.js", "tsconfig.json"):
        shutil.copy2(REPO_ROOT / name, root / name)
    packages = root / "packages"
    packages.mkdir()
    # Whatever depcruise follows: every workspace package plus `tools/` and `scripts/`
    # (imported by the ui token build and the config tests). Built output (dist/,
    # ui/build/css) is copied when present, so the copy resolves like the checkout in
    # the same build state. `node_modules` is copied with symlinks=True: workspace
    # links stay relative and resolve inside the copy, while pnpm-store links resolve
    # through the root symlink below.
    for pkg in sorted(p.name for p in (REPO_ROOT / "packages").iterdir() if p.is_dir()):
        shutil.copytree(
            REPO_ROOT / "packages" / pkg, packages / pkg, ignore=_IGNORE_TS, symlinks=True
        )
    for extra in ("tools", "scripts"):
        shutil.copytree(REPO_ROOT / extra, root / extra, ignore=_IGNORE_TS, symlinks=True)
    nm = REPO_ROOT / "node_modules"
    if nm.is_dir():
        (root / "node_modules").symlink_to(nm, target_is_directory=True)
    return root


def _depcruise_in(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    prefix = resolve_depcruise(REPO_ROOT)
    if prefix is None:
        pytest.skip("dependency-cruiser not installed locally; skipping architecture negative test")
    return _run([*prefix, "--config", ".dependency-cruiser.js", *args], cwd=root)


def test_clean_scaffold_passes_dependency_cruiser(ts_copy: Path) -> None:
    result = _depcruise_in(ts_copy, "packages")
    assert result.returncode == 0, result.stdout + result.stderr


def test_ts_copy_is_faithful_to_the_checkout(ts_copy: Path) -> None:
    """The copy reports exactly what the checkout reports (read-only run on both), so
    a green or red clean-scaffold result means the same thing for either."""
    prefix = resolve_depcruise(REPO_ROOT)
    if prefix is None:
        pytest.skip("dependency-cruiser not installed locally; skipping architecture negative test")
    args = [*prefix, "--config", ".dependency-cruiser.js", "--output-type", "err", "packages"]
    real = _run(args, cwd=REPO_ROOT)
    copy = _run(args, cwd=ts_copy)
    assert copy.returncode == real.returncode
    assert copy.stdout.strip() == real.stdout.strip()


def test_secrets_import_violation_caught_by_c_3_2(api_copy: Path) -> None:
    """M8 (bars) is not in C-3.2's allow-list for M2 (secrets)."""
    result = _assert_clean_then_violate(
        api_copy,
        "candleviewer/bars/service.py",
        "\nfrom candleviewer.secrets import SecretsService  # noqa\n",
    )
    assert result.returncode != 0
    assert "BROKEN" in result.stdout
    assert "C-3.2" in result.stdout or "secrets" in result.stdout.lower()


def test_asyncpg_import_outside_storage_caught_by_adr_0003(api_copy: Path) -> None:
    """E07-T01 acceptance criterion 2: a module outside M10 (storage) that
    imports a storage driver package directly must fail CI, citing ADR-0003."""
    result = _assert_clean_then_violate(
        api_copy, "candleviewer/bars/service.py", "\nimport asyncpg  # noqa\n"
    )
    assert result.returncode != 0
    assert "BROKEN" in result.stdout
    assert "ADR-0003" in result.stdout


def test_statechart_import_from_ws_caught_by_c_2_20(api_copy: Path) -> None:
    """#414 AC 2: `candleviewer.ws` never imports the statechart package (no `Interpreter`)."""
    result = _assert_clean_then_violate(
        api_copy,
        "candleviewer/ws/machines.py",
        "\nimport candleviewer.statechart.plugins.state_feed\n",
    )
    assert result.returncode != 0
    line = next(ln for ln in result.stdout.splitlines() if "ws never imports the statechart" in ln)
    assert line.startswith("C-2.20") and line.endswith("BROKEN")


def test_adapter_import_from_oms_caught_by_c_2_2(api_copy: Path) -> None:
    """#913 (E29-T04): `candleviewer.oms` reaches the exchange only through `exchange.base`."""
    result = _assert_clean_then_violate(
        api_copy,
        "candleviewer/oms/routing.py",
        "\nimport candleviewer.exchange.bybit.trading\n",
    )
    assert result.returncode != 0
    line = next(ln for ln in result.stdout.splitlines() if "reaches the exchange only" in ln)
    assert line.startswith("C-2.2 ") and line.endswith("BROKEN")


def test_weakened_contract_in_copy_lets_violation_through(api_copy: Path) -> None:
    """Meta-test: the negative cases bite only because the contract is present.
    Dropping the M8 ADR-0003 contract from the copy's config makes the asyncpg
    injection pass, so a weakened contract would fail the cases above."""
    cfg = api_copy / ".importlinter"
    text = cfg.read_text(encoding="utf-8")
    blocks = text.split("\n[importlinter:contract:")
    kept = [b for b in blocks if not ("ADR-0003" in b and "M8 (" in b)]
    assert len(kept) == len(blocks) - 1, "expected exactly one M8 ADR-0003 contract"
    cfg.write_text("\n[importlinter:contract:".join(kept), encoding="utf-8")
    _append(api_copy, "candleviewer/bars/service.py", "\nimport asyncpg  # noqa\n")
    result = _lint(api_copy)
    assert result.returncode == 0, result.stdout
    assert "BROKEN" not in result.stdout


def _assert_rule_not_reported(root: Path, rule: str) -> None:
    """Positive control: the unmodified copy is cruised (modules counted) and the
    rule under test is silent, so a later hit is caused by the injected import."""
    control = _depcruise_in(root, "--output-type", "err-long", "packages")
    combined = control.stdout + control.stderr
    assert "modules," in combined, combined
    assert rule not in combined


def test_react_in_chart_engine_core_caught_by_c_2_16(ts_copy: Path) -> None:
    _assert_rule_not_reported(ts_copy, "chart-engine-no-react")
    target = ts_copy / "packages" / "chart-engine" / "src" / "core" / "handle.ts"
    target.write_text('import React from "react";\n' + target.read_text(encoding="utf-8"))
    result = _depcruise_in(ts_copy, "--output-type", "err-long", "packages")
    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert "chart-engine-no-react" in combined
    assert "C-2.16" in combined


def test_deep_import_violation_caught(ts_copy: Path) -> None:
    _assert_rule_not_reported(ts_copy, "no-deep-imports-ui")
    target = ts_copy / "packages" / "protocol" / "src" / "index.ts"
    target.write_text(
        target.read_text(encoding="utf-8")
        + '\nexport { Placeholder } from "../../ui/src/primitives/Placeholder";\n'
    )
    result = _depcruise_in(ts_copy, "--output-type", "err-long", "packages")
    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert "no-deep-imports-ui" in combined
    assert "§9 #18" in combined or "Deep import banned" in combined


def test_manifest_table_count_mismatch_fails_drift_test(tmp_path: Path) -> None:
    """Simulates §3 being edited (a module row removed) without updating
    `docs/plan/module-contracts.toml`: the drift test's row-count assertion
    must fail against the edited table. The drift test is copied into a scratch
    tree whose layout makes its `REPO_ROOT` the scratch root."""
    tree_tests = tmp_path / "services" / "api" / "tests" / "unit" / "architecture"
    tree_tests.mkdir(parents=True)
    shutil.copy2(ARCH_TESTS / "test_module_contracts_drift.py", tree_tests)
    (tmp_path / "docs" / "plan").mkdir(parents=True)
    shutil.copy2(
        REPO_ROOT / "docs" / "plan" / "module-contracts.toml",
        tmp_path / "docs" / "plan" / "module-contracts.toml",
    )
    constitution = tmp_path / "CONSTITUTION.md"
    shutil.copy2(REPO_ROOT / "CONSTITUTION.md", constitution)
    (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        "-c",
        str(tmp_path / "pytest.ini"),
        "--rootdir",
        str(tmp_path),
        "-p",
        "no:cacheprovider",
        "-p",
        "no:randomly",
        "-q",
        str(tree_tests / "test_module_contracts_drift.py::test_backend_module_count_matches"),
    ]
    control = _run(cmd, cwd=tmp_path)
    assert control.returncode == 0, control.stdout + control.stderr

    lines = constitution.read_text(encoding="utf-8").splitlines()
    patched = [line for line in lines if not line.startswith("| M24 |")]
    assert len(patched) < len(lines)
    constitution.write_text("\n".join(patched), encoding="utf-8")
    result = _run(cmd, cwd=tmp_path)
    assert result.returncode != 0, result.stdout + result.stderr
    assert "expected 24" in result.stdout
