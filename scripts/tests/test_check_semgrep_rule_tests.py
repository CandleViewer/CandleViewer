"""Unit tests for tools/ci/check_semgrep_rule_tests.py (QA #1559 defect #3).

Regression coverage for replacing the documented `semgrep --test .semgrep/tests`
verification command, which hangs/mis-locates matches against a directory
config on this toolchain (semgrep 1.178.0, Windows). These tests exercise the
fixture-parsing helpers directly (no real semgrep invocation), so they run
with no network and no installed scanner.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.ci.check_semgrep_rule_tests import expected_lines


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
        "danger()  # ruleid: some-other-rule\n" "safe()  # ok: some-other-rule\n",
        encoding="utf-8",
    )
    must_fire, must_not_fire = expected_lines(fixture, "cv-example")
    assert must_fire == set()
    assert must_not_fire == set()


def test_semgrep_config_dir_yaml_files_all_have_rules_key() -> None:
    """Every YAML directly under .semgrep/ and .semgrep/tests/ is loaded as a config by
    `semgrep --config .semgrep`, so it must have a top-level `rules:` key (fixtures go in
    .semgrep-fixtures/)."""
    import re

    root = Path(__file__).resolve().parents[2] / ".semgrep"
    files = [
        f for d in (root, root / "tests") for ext in ("*.yml", "*.yaml") for f in d.glob(ext)
    ]
    assert files
    bad = [
        f.name for f in files if not re.search(r"^rules:", f.read_text(encoding="utf-8"), re.M)
    ]
    assert not bad, f"not semgrep configs (move to .semgrep-fixtures/): {bad}"
