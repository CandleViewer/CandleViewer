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
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import tools.ci.check_semgrep_rule_tests as checker
from tools.ci.check_semgrep_rule_tests import (
    FIXTURES_DIR,
    REPO_ROOT,
    RULES_DIR,
    TESTS_DIR,
    _staged_relpath,
    check_tree,
    expected_lines,
    find_fixture,
    find_fixture_tree,
    tree_files,
    tree_lines,
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


def test_bare_create_task_rule_excludes_only_tests_and_the_module_that_implements_spawn() -> None:
    """#1822: `**/observability/**` hid five of the rule's nine first findings; only `context.py`,
    which implements `spawn()` and the thread offloads (`run_in_thread`, `thread_future`,
    `executor_future`), is exempt."""
    text = (REPO_ROOT / ".semgrep" / "cv-bare-create-task.yml").read_text(encoding="utf-8")
    (rule,) = yaml.safe_load(text)["rules"]
    assert rule["paths"]["exclude"] == [
        "**/test_*.py",
        "**/conftest.py",
        "**/observability/context.py",
    ]


# E42-X03 (AC-ADM-14): a fixture tree, `.semgrep/tests/<id>/`, staged at its repo paths.
_RULE = "cv-example"


def _tree(root: Path, files: dict[str, str]) -> Path:
    tree = root / _RULE
    for rel, text in files.items():
        path = tree / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return tree


def test_tree_files_keep_their_repo_paths_and_skip_bytecode(tmp_path: Path) -> None:
    tree = _tree(
        tmp_path,
        {
            "services/api/candleviewer/auth/a.py": "x = 1  # ok: cv-example\n",
            "services/api/candleviewer/oms/b.py": "y = 2  # ruleid: cv-example\n",
            "services/api/candleviewer/oms/__pycache__/b.cpython-312.pyc": "",
        },
    )
    staged = [str(rel) for _, rel in tree_files(tree)]
    assert staged == [
        "services/api/candleviewer/auth/a.py",
        "services/api/candleviewer/oms/b.py",
    ]
    assert all(not Path(rel).is_absolute() and ".." not in Path(rel).parts for rel in staged)


def test_tree_files_refuse_a_symlink(tmp_path: Path) -> None:
    tree = _tree(tmp_path, {"services/api/candleviewer/auth/a.py": "x = 1  # ok: cv-example\n"})
    (tree / "services/api/candleviewer/auth/link.py").symlink_to(tmp_path / "elsewhere.py")
    with pytest.raises(ValueError, match="symlink"):
        tree_files(tree)


def test_find_fixture_tree_finds_the_rules_directory_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(checker, "TESTS_DIR", tmp_path)
    assert find_fixture_tree(_RULE) is None
    (tmp_path / f"{_RULE}.py").write_text("", encoding="utf-8")
    assert find_fixture_tree(_RULE) is None  # a single-file fixture is not a tree
    (tmp_path / _RULE).mkdir()
    assert find_fixture_tree(_RULE) == tmp_path / _RULE


def test_tree_lines_scans_every_file_at_its_repo_path_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tree = _tree(
        tmp_path,
        {
            "services/api/candleviewer/auth/a.py": "a()  # ruleid: cv-example\n",
            "services/api/candleviewer/admin/flags/b.py": "a()  # ok: cv-example\n",
        },
    )
    calls: list[list[str]] = []

    def fake_scan(rule_yaml: Path, targets: list[str], cwd: str) -> list[dict[str, object]]:
        calls.append(list(targets))
        for target in targets:  # each file is staged, unchanged, at its repo path under cwd
            assert (Path(cwd) / target).read_text(encoding="utf-8") == (tree / target).read_text(
                encoding="utf-8"
            )
        return [{"path": "services/api/candleviewer/auth/a.py", "start": {"line": 1}}]

    monkeypatch.setattr(checker, "_scan", fake_scan)
    found = tree_lines(tmp_path / "rule.yml", tree_files(tree))
    assert len(calls) == 1
    assert found == {
        "services/api/candleviewer/admin/flags/b.py": set(),
        "services/api/candleviewer/auth/a.py": {1},
    }


def _check(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    files: dict[str, str],
    fired: dict[str, set[int]],
) -> list[str]:
    tree = _tree(tmp_path, files)

    def fake_lines(rule_yaml: Path, staged: object) -> dict[str, set[int]]:
        return {rel: set() for rel in files} | fired

    monkeypatch.setattr(checker, "tree_lines", fake_lines)
    return check_tree(tmp_path / "rule.yml", _RULE, tree)


_AUTH, _FLAGS = "services/api/candleviewer/auth/a.py", "services/api/candleviewer/admin/flags/b.py"
_FILES = {
    _AUTH: "a()  # ruleid: cv-example\nb()  # ok: cv-example\n",
    _FLAGS: "a()  # ok: cv-example\n",
}


def test_check_tree_passes_when_every_file_fires_where_marked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert _check(tmp_path, monkeypatch, _FILES, {_AUTH: {1}}) == []


def test_check_tree_names_the_file_of_a_missed_line_and_of_a_false_positive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    failures = _check(tmp_path, monkeypatch, _FILES, {_AUTH: set(), _FLAGS: {1}})
    assert failures == [
        f"cv-example: {_FLAGS}: fired on 'ok' lines [1]",
        f"cv-example: {_AUTH}: expected to fire but did not on [1]",
    ]


def test_check_tree_refuses_a_finding_outside_the_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stray = "services/api/candleviewer/oms/c.py"
    failures = _check(tmp_path, monkeypatch, _FILES, {_AUTH: {1}, stray: {3}})
    assert failures == [f"cv-example: fired on {stray}, which the tree does not hold"]


def test_check_tree_needs_a_ruleid_line_and_a_marker_in_every_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    negative_only = {_FLAGS: "a()  # ok: cv-example\n"}
    (only,) = _check(tmp_path / "one", monkeypatch, negative_only, {})
    assert "has no '# ruleid: cv-example' lines" in only
    unmarked = _FILES | {"services/api/candleviewer/risk/c.py": "c()\n"}
    failures = _check(tmp_path / "two", monkeypatch, unmarked, {_AUTH: {1}})
    assert failures == [
        "cv-example: services/api/candleviewer/risk/c.py has no '# ruleid:' or '# ok:' line, "
        "so it tests nothing"
    ]


def test_every_fixture_tree_belongs_to_a_rule_that_has_no_other_fixture() -> None:
    trees = sorted(p for p in TESTS_DIR.glob("cv-*") if p.is_dir())
    assert trees, "the admin rules (E42-X03) keep their fixtures as trees"
    for tree in trees:
        assert (RULES_DIR / f"{tree.name}.yml").is_file(), f"{tree.name}: no rule of that id"
        assert not find_fixture(tree.name).exists(), f"{tree.name}: a tree and a single fixture"
        assert tree_files(tree), f"{tree.name}: an empty fixture tree tests nothing"


# E14-X03 (#549): a rule needs an `ok` line as well as a `ruleid` line.
_NO_OK = "has no '# ok: cv-example' lines -- a rule that is never shown staying quiet is untested"


def test_check_tree_needs_an_ok_line_somewhere(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fires_only = {_AUTH: "a()  # ruleid: cv-example\n", _FLAGS: "b()  # ruleid: cv-example\n"}
    (failure,) = _check(tmp_path, monkeypatch, fires_only, {_AUTH: {1}, _FLAGS: {1}})
    assert _NO_OK in failure
    assert (
        _check(tmp_path / "ok", monkeypatch, _FILES, {_AUTH: {1}}) == []
    )  # one `ok` line is enough


@pytest.mark.parametrize(
    ("text", "code"),
    [("a()  # ruleid: cv-example\n", 1), ("a()  # ruleid: cv-example\nb()  # ok: cv-example\n", 0)],
)
def test_main_needs_an_ok_line_in_a_single_file_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, text: str, code: int
) -> None:
    rules, tests = tmp_path / "rules", tmp_path / "tests"
    rules.mkdir()
    tests.mkdir()
    (rules / "cv-example.yml").write_text("rules: []\n", encoding="utf-8")
    (tests / "cv-example.py").write_text(text, encoding="utf-8")
    monkeypatch.setattr(checker, "RULES_DIR", rules)
    monkeypatch.setattr(checker, "TESTS_DIR", tests)
    monkeypatch.setattr(checker, "FIXTURE_LOCATIONS", ((tests, ".py"),))
    monkeypatch.setattr(checker, "actual_lines", lambda rule_yaml, fixture: {1})
    assert checker.main() == code
