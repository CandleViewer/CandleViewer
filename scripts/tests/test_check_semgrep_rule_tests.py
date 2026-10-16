"""Unit tests for tools/ci/check_semgrep_rule_tests.py (QA #1559 defect #3).

Regression coverage for replacing the documented `semgrep --test .semgrep/tests`
verification command, which hangs/mis-locates matches against a directory
config on this toolchain (semgrep 1.178.0, Windows). These tests exercise the
fixture-parsing helpers directly (no real semgrep invocation), so they run
with no network and no installed scanner.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.ci.check_semgrep_rule_tests import (
    FIXTURES_DIR,
    REPO_ROOT,
    TESTS_DIR,
    _staged_relpath,
    expected_lines,
    find_fixture,
)


def test_expected_lines_parses_ruleid_and_ok_markers(tmp_path: Path) -> None:
    fixture = tmp_path / "cv-example.py"
    fixture.write_text(
        "def bad() -> None:\n"
        "    danger()  # ruleid: cv-example\n"
        "\n"
        "def ok() -> None:\n"
        "    safe()  # ok: cv-example\n",
        encoding="utf-8",
    )
    must_fire, must_not_fire = expected_lines(fixture, "cv-example")
    assert must_fire == {2}
    assert must_not_fire == {5}


def test_expected_lines_ignores_other_rule_ids(tmp_path: Path) -> None:
    fixture = tmp_path / "cv-example.py"
    fixture.write_text(
        "danger()  # ruleid: some-other-rule\nsafe()  # ok: some-other-rule\n",
        encoding="utf-8",
    )
    must_fire, must_not_fire = expected_lines(fixture, "cv-example")
    assert must_fire == set()
    assert must_not_fire == set()


def test_semgrep_config_dir_yaml_files_all_have_rules_key() -> None:
    """Every YAML anywhere under .semgrep/ is loaded as a config by `semgrep --config .semgrep`
    (it recurses), so each must have a top-level `rules:` key; fixtures go in .semgrep-fixtures/."""
    root = REPO_ROOT / ".semgrep"
    files = [f for ext in ("*.yml", "*.yaml") for f in root.rglob(ext)]
    assert files
    bad = [
        str(f.relative_to(root))
        for f in files
        if not re.search(r"^rules:", f.read_text(encoding="utf-8"), re.MULTILINE)
    ]
    assert not bad, f"not semgrep configs (move to .semgrep-fixtures/): {bad}"


def test_yaml_fixture_is_staged_under_workflows_by_basename() -> None:
    staged = _staged_relpath(FIXTURES_DIR / "cv-unpinned-action.yml")
    assert staged == Path(".github/workflows/cv-unpinned-action.yml")
    assert not staged.is_absolute()
    assert ".." not in staged.parts


def test_code_fixture_keeps_its_repo_relative_path() -> None:
    staged = _staged_relpath(TESTS_DIR / "cv-example.py")
    assert staged == Path(".semgrep/tests/cv-example.py")
    assert not staged.is_absolute()
    assert ".." not in staged.parts


def test_fixture_outside_the_repo_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        _staged_relpath(tmp_path / "cv-example.py")


def test_find_fixture_prefers_the_code_fixture_and_falls_back_to_yaml(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tests_dir = tmp_path / ".semgrep" / "tests"
    fixtures_dir = tmp_path / ".semgrep-fixtures"
    tests_dir.mkdir(parents=True)
    fixtures_dir.mkdir()
    import tools.ci.check_semgrep_rule_tests as mod

    monkeypatch.setattr(mod, "TESTS_DIR", tests_dir)
    monkeypatch.setattr(
        mod,
        "FIXTURE_LOCATIONS",
        (
            (tests_dir, ".py"),
            (tests_dir, ".ts"),
            (tests_dir, ".tsx"),
            (fixtures_dir, ".yml"),
        ),
    )
    (fixtures_dir / "cv-wf.yml").write_text("on: push  # ruleid: cv-wf\n", encoding="utf-8")
    assert find_fixture("cv-wf") == fixtures_dir / "cv-wf.yml"
    (tests_dir / "cv-wf.py").write_text("x = 1  # ruleid: cv-wf\n", encoding="utf-8")
    assert find_fixture("cv-wf") == tests_dir / "cv-wf.py"
    assert find_fixture("cv-none") == tests_dir / "cv-none.py"


def test_semgrepignore_fixture_entries_are_anchored_to_the_repo_root() -> None:
    """A bare `.semgrep-fixtures/` would also hide `packages/x/.semgrep-fixtures/` from the product
    scan (semgrep matches an unanchored pattern at any depth); the entries must start with `/`."""
    entries = [
        line.strip()
        for line in (REPO_ROOT / ".semgrepignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    fixture_entries = [e for e in entries if "semgrep-fixtures" in e or "semgrep/tests" in e]
    assert fixture_entries, "the fixture directories must be ignored by the product scan"
    assert all(e.startswith("/") for e in fixture_entries), fixture_entries
