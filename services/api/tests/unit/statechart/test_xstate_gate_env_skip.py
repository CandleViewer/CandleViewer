"""tests/unit/statechart/test_xstate_gate_env_skip.py (#1928, E50-C17 #579).

The xstate nightly gate must be environment-independent:

* ``docs/research/xstate/gate/_paths.py`` resolves the upstream source tree
  from ``XSTATE_SRC`` -> the CI ``_upstream`` checkout -> a local ``_ref``
  checkout (only if it exists), never a hard-coded home directory;
* a check script that needs an upstream dev venv it cannot find exits 77,
  which ``run_gate.classify_exit`` records as ``SKIP-ENV`` ("skipped
  (environment)"), and ``tools/statechart/nightly_gate.py`` never counts it
  as a regression (nor as a fix);
* the nightly workflow builds the two upstream dev venvs those scripts look
  for, and ``run_gate`` can read BENCH-6's bare-JSON wrapper output (#579).
"""

from __future__ import annotations

import ast
import importlib
import json
import re
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[5]
_GATE_DIR = _REPO_ROOT / "docs" / "research" / "xstate" / "gate"
for _p in (_REPO_ROOT, _GATE_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

# These live outside the `candleviewer` package (docs/research + tools), so they
# are loaded dynamically; mypy sees them as plain ModuleType handles.
_paths: ModuleType = importlib.import_module("_paths")
run_gate: ModuleType = importlib.import_module("run_gate")
nightly_gate: ModuleType = importlib.import_module("tools.statechart.nightly_gate")


def test_classify_exit_zero_is_pass() -> None:
    assert run_gate.classify_exit(0, "", "real FAIL")[0] == run_gate.PASS


def test_classify_exit_one_is_fail_with_given_detail() -> None:
    assert run_gate.classify_exit(1, "", "real FAIL") == (run_gate.FAIL, "real FAIL")


def test_classify_exit_skip_env_code_is_skipped_environment() -> None:
    out = "noise\nskipped (environment): requires the upstream dev venv X\n"
    status, detail = run_gate.classify_exit(_paths.SKIP_ENV_EXIT, out, "real FAIL")
    assert status == run_gate.SKIP_ENV
    assert detail.startswith("skipped (environment)")


def test_classify_exit_skip_env_reason_is_the_skip_line_not_trailing_noise() -> None:
    out = "skipped (environment): requires the upstream dev venv X\nlater log line\n"
    _, detail = run_gate.classify_exit(_paths.SKIP_ENV_EXIT, out, "real FAIL")
    assert detail == "skipped (environment): requires the upstream dev venv X"


def test_classify_exit_other_code_is_error() -> None:
    status, detail = run_gate.classify_exit(2, "FileNotFoundError: x", "real FAIL")
    assert status == run_gate.ERROR
    assert "exit 2" in detail


def test_skip_env_status_string_agrees_between_gate_and_verdict() -> None:
    assert run_gate.SKIP_ENV == nightly_gate.SKIP_ENV


def _result(*checks: tuple[str, str, str]) -> dict[str, Any]:
    return {"checks": [{"kind": k, "id": i, "status": s} for k, i, s in checks]}


def test_nightly_gate_skip_env_is_not_a_regression() -> None:
    baseline = _result(("verifyM3", "142", "PASS"))
    result = _result(("verifyM3", "142", "SKIP-ENV"))
    assert nightly_gate.regressions(result, baseline) == []
    assert nightly_gate.skipped_env(result) == ["verifyM3:142"]


def test_nightly_gate_skip_env_is_not_counted_as_fixed() -> None:
    baseline = _result(("verifyM", "LC-52", "FAIL"))
    result = _result(("verifyM", "LC-52", "SKIP-ENV"))
    assert nightly_gate.fixed(result, baseline) == []


def test_nightly_gate_real_fail_is_still_a_regression() -> None:
    baseline = _result(("verify", "LC-39", "PASS"))
    result = _result(("verify", "LC-39", "FAIL"))
    assert nightly_gate.regressions(result, baseline) == ["verify:LC-39"]


def test_render_lists_skipped_environment_section() -> None:
    report = nightly_gate.render(
        mode="pinned",
        date="2026-10-07",
        result={},
        new=[],
        gone=[],
        bench_ok=None,
        p99=None,
        threshold=100.0,
        skipped=["verifyM3:142"],
    )
    assert "Skipped (environment)" in report
    assert "- verifyM3:142" in report
    assert "**GREEN**" in report


def test_nightly_gate_flags_baseline_pass_now_skipped_as_coverage_loss() -> None:
    baseline = _result(("verifyM3", "142", "PASS"), ("verifyM", "N-8", "FAIL"))
    result = _result(("verifyM3", "142", "SKIP-ENV"), ("verifyM", "N-8", "SKIP-ENV"))
    assert nightly_gate.coverage_lost(result, baseline) == ["verifyM3:142"]


def test_render_skip_ratio_warning_stays_non_blocking() -> None:
    report = nightly_gate.render(
        mode="pinned",
        date="2026-10-07",
        result={},
        new=[],
        gone=[],
        bench_ok=None,
        p99=None,
        threshold=100.0,
        skipped=["verifyM3:142"],
        ratio=0.5,
    )
    assert "WARNING: 50% of checks skipped" in report
    assert "**GREEN**" in report


def test_skip_ratio_below_threshold_has_no_warning() -> None:
    result = _result(("a", "1", "SKIP-ENV"), *[("a", str(i), "PASS") for i in range(2, 10)])
    assert nightly_gate.skip_ratio(result) < nightly_gate.SKIP_WARN_RATIO
    assert nightly_gate.skip_ratio({}) == 0.0


def test_resolve_xstate_src_env_var_wins(tmp_path: Path) -> None:
    ci, ref = tmp_path / "ci", tmp_path / "ref"
    ci.mkdir()
    ref.mkdir()
    (tmp_path / "x").mkdir()
    got = _paths.resolve_xstate_src({"XSTATE_SRC": str(tmp_path / "x")}, ci, ref)
    assert got == tmp_path / "x"


def test_resolve_xstate_src_prefers_ci_upstream(tmp_path: Path) -> None:
    ci, ref = tmp_path / "ci", tmp_path / "ref"
    ci.mkdir()
    ref.mkdir()
    assert _paths.resolve_xstate_src({}, ci, ref) == ci


def test_resolve_xstate_src_local_ref_only_when_present(tmp_path: Path) -> None:
    ci, ref = tmp_path / "ci", tmp_path / "ref"
    assert _paths.resolve_xstate_src({}, ci, ref) is None
    ref.mkdir()
    assert _paths.resolve_xstate_src({}, ci, ref) == ref


def test_require_xstate_src_nonexistent_env_var_exits_skip_env(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ci = tmp_path / "ci"
    ci.mkdir()
    with pytest.raises(SystemExit) as exc:
        _paths.require_xstate_src({"XSTATE_SRC": str(tmp_path / "nope")}, ci, tmp_path / "r")
    assert exc.value.code == _paths.SKIP_ENV_EXIT
    assert "is not a directory" in capsys.readouterr().out


def test_require_xstate_src_nothing_resolves_exits_skip_env(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exc:
        _paths.require_xstate_src({}, tmp_path / "ci", tmp_path / "ref")
    assert exc.value.code == _paths.SKIP_ENV_EXIT
    assert "skipped (environment)" in capsys.readouterr().out


def test_ci_upstream_default_matches_workflow_checkout_path() -> None:
    workflow = (_REPO_ROOT / ".github" / "workflows" / "xstate-nightly.yml").read_text(
        encoding="utf-8"
    )
    assert "path: _upstream" in workflow
    assert _paths.CI_UPSTREAM == _REPO_ROOT / "_upstream"


def test_nightly_workflow_builds_the_upstream_dev_venvs_the_env_rows_need() -> None:
    # #579: without these the 13 env rows (e.g. verifyM3:142, verify:LC-53) are SKIP-ENV.
    workflow = (_REPO_ROOT / ".github" / "workflows" / "xstate-nightly.yml").read_text(
        encoding="utf-8"
    )
    for venv in (".venv-main", ".venv-gate"):
        assert f"_upstream/{venv}" in workflow, venv


def test_parse_bare_json_reads_the_bench6_wrapper_output() -> None:
    # bench_c_timers_v2.py prints one bare JSON document, never `=== name ===` blocks (#579).
    out = json.dumps({"summary_by_busy_level": {"500": {"p99": 28.7}}}, indent=2) + "\nlog\n"
    spec = next(s for s in run_gate.THRESHOLDS if s["id"] == "BENCH-6")
    assert run_gate.parse_bench_blocks(out) == {}
    assert run_gate.dig(run_gate.parse_bare_json(out), spec["path"]) == 28.7


def test_parse_bare_json_without_a_json_object_is_empty() -> None:
    for text in ("no json here", "{ broken", "[1, 2]", ""):
        assert run_gate.parse_bare_json(text) == {}, text


def test_upstream_dev_python_missing_venv_exits_skip_env(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exc:
        _paths.upstream_dev_python(".venv-main", tmp_path)
    assert exc.value.code == _paths.SKIP_ENV_EXIT
    assert "skipped (environment)" in capsys.readouterr().out


def test_upstream_dev_python_finds_posix_layout(tmp_path: Path) -> None:
    py = tmp_path / ".venv-main" / "bin" / "python"
    py.parent.mkdir(parents=True)
    py.write_text("", encoding="utf-8")
    assert _paths.upstream_dev_python(".venv-main", tmp_path) == str(py)


_HOME_DIR = re.compile(r"(C:[\\/]+Users|/home/[A-Za-z]|(?<![\w.])~/|(?<![\w.])/Users/)")


def _code_string_literals(src: str) -> list[tuple[int, str]]:
    """``(line, value)`` of every string literal that is code, not a docstring/comment."""
    tree = ast.parse(src)
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
        and isinstance(node.body[0].value.value, str)
    }
    return [
        (node.lineno, node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    ]


def test_home_dir_pattern_catches_every_owner_path_shape() -> None:
    for shape in ("C:/Users/x", r"C:\Users\x", "/home/runner", "~/x", "/Users/x"):
        assert _HOME_DIR.search(shape), shape
    assert not _HOME_DIR.search("docs/research/xstate/issues/x.py")


def test_no_gate_script_hard_codes_a_home_directory() -> None:
    # Scope: what run_gate.py executes (gate modules, issues/**, BENCH-6). The ad-hoc
    # research runners elsewhere in gate/ are tracked by the purge follow-up (#1928).
    xs = _REPO_ROOT / "docs" / "research" / "xstate"
    scripts = [
        _GATE_DIR / "_paths.py",
        _GATE_DIR / "run_gate.py",
        *xs.glob("issues/**/*.py"),
        xs / "bench" / "bench_c_timers_v2.py",
    ]
    offenders = [
        f"{script.relative_to(xs)}:{line}"
        for script in scripts
        for line, value in _code_string_literals(script.read_text(encoding="utf-8"))
        if _HOME_DIR.search(value)
    ]
    assert offenders == []


_OWNER_PATH = re.compile(
    rb"(?i)(?:[A-Za-z]:[\\/]+Users[\\/]+\w|(?<![\w.])/Users/\w|(?<![\w.])/home/\w)"
)
_MAX_SCAN_BYTES = 8 * 1024 * 1024


def _tracked_research_files(xs: Path) -> list[Path]:
    try:
        out = subprocess.run(  # noqa: S603 - fixed argv, no user input
            ["git", "ls-files", "-z", "--", str(xs)],  # noqa: S607
            cwd=_REPO_ROOT,
            capture_output=True,
            check=True,
        ).stdout
        files = [_REPO_ROOT / name.decode() for name in out.split(b"\0") if name]
    except (OSError, subprocess.CalledProcessError):
        files = [p for p in xs.rglob("*") if p.is_file()]
    return [p for p in files if p.is_file()]


def test_owner_path_pattern_catches_every_shape() -> None:
    for shape in (rb"C:\Users\x\y", rb"C:\\Users\\x", b"C:/Users/x", b"/home/x", b"/Users/x"):
        assert _OWNER_PATH.search(shape), shape
    assert not _OWNER_PATH.search(b"docs/research/xstate/<home>/x")


def test_no_research_file_contains_an_owner_specific_path() -> None:
    # #1963: every tracked file under docs/research/xstate (results, logs, write-ups)
    # must use <workspace>/<home> placeholders, never a developer's absolute path.
    xs = _REPO_ROOT / "docs" / "research" / "xstate"
    offenders = []
    for path in _tracked_research_files(xs):
        assert path.stat().st_size <= _MAX_SCAN_BYTES, f"{path} too large to scan"
        data = path.read_bytes()
        if (b"sers" in data or b"SERS" in data or b"/home/" in data) and _OWNER_PATH.search(data):
            offenders.append(str(path.relative_to(xs)))
    assert offenders == []
