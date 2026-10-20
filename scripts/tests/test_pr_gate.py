"""Tests for tools/ci/pr_gate.py (#3882). The three PR runs that went red on 2026-10-20 are
fixtures, each as the hunk that caused it, not as a checkout: an alert without a drill matrix row
(#3862), a bars change whose bench pins no lane ran (#3868), a test that logs a password-named
constant (#3875). Each runs through `plan()`, as `make pr-gate` does, with the tools faked so the
argv of every step can be pinned. No real scanner runs and nothing reaches the network."""

from __future__ import annotations

import functools
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.ci import path_filters, pr_gate  # noqa: E402 - the repo root must be importable first

API, UNIT = pr_gate.API, pr_gate.UNIT
WORKFLOWS = ROOT / ".github" / "workflows"
#: #3875's hunk: a password-named constant, logged on purpose to prove that a filter hides it.
LOGGED = "import logging\n\n\n_PASSWORD = 'x'\n\n\ndef f() -> None:\n"
LOGGED += "    logging.warning('%s', _PASSWORD)\n"
#: #3862's hunk: a page alert, and a drill matrix that has no row for it.
ALERT = "groups:\n- name: g\n  rules:\n  - {alert: GuardFailed, labels: {severity: page}}\n"
ROW = "| E04-TC-{0} | a | b | c | US-OBS-{0:03d} / E04-T01 | Auto |\n"
PLAN = "".join(ROW.format(n) for n in (1, 2, 3, 4, 5, 7))
#: #3868's hunk: a bars module; the bench tests pin it, and so do the ws tests that import it.
BARS = f"{API}/candleviewer/bars/a.py"


def _change(root: Path, paths: list[str], base: str = "HEAD") -> Any:
    workflow = path_filters.load_workflow()
    selected = path_filters.select(paths, path_filters.load_filters(workflow))
    return pr_gate.Change(root, tuple(paths), base, workflow, selected)


def _write(root: Path, rel: str, text: str = "x = 1\n") -> str:
    (root / rel).parent.mkdir(parents=True, exist_ok=True)
    (root / rel).write_text(text, encoding="utf-8")
    return rel


def _git(cwd: Path, *args: str) -> str:
    config = ["-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false"]
    done = subprocess.run(
        ["git", *config, *args], cwd=cwd, check=True, capture_output=True, text=True
    )
    return done.stdout.strip()


def _fake_tools(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """Every tool exists and passes, and each run's argv is logged."""
    calls: list[list[str]] = []

    def run_command(argv: Sequence[str], cwd: Path) -> tuple[int, str]:
        calls.append(list(argv))
        return 0, ""

    monkeypatch.setattr(pr_gate.shutil, "which", lambda name: name)
    monkeypatch.setattr(pr_gate, "run_command", run_command)
    return calls


def _argv(calls: list[list[str]], step: Any) -> list[str]:
    calls.clear()
    step.run()
    return calls[-1]


def _with_filters(text: str) -> dict[str, Any]:
    workflow = path_filters.load_workflow()
    path_filters.filter_step(workflow)["with"]["filters"] = text
    return workflow


def _verdict(status: str) -> tuple[str, str]:
    return status, ""


def test_selection_reads_the_rules_pr_yml_declares_and_keeps_no_copy() -> None:
    workflow = path_filters.load_workflow()
    declared = yaml.safe_load(path_filters.filter_step(workflow)["with"]["filters"])
    assert path_filters.load_filters() == declared
    assert set(declared) == set(workflow["jobs"]["changed-paths"]["outputs"]) - {"pr"}
    assert pr_gate.path_filters is path_filters


@pytest.mark.parametrize(
    ("paths", "on"),
    [
        (["services/api/x.py"], {"py"}),
        (["docs/a.md"], {"docs"}),
        (["Makefile"], {"protocol"}),
        (["a.txt"], set()),
        (["a.txt", "services/api/x.py"], {"py"}),
        (["docs/a.md", "a.txt"], {"docs"}),
    ],
)
def test_select_marks_the_filters_the_changed_paths_match(paths: list[str], on: set[str]) -> None:
    selected = path_filters.select(paths, path_filters.load_filters())
    assert {name for name, hit in selected.items() if hit} == on


@pytest.mark.parametrize(
    ("path", "rule", "hit"),
    [
        ("a/b.py", "a/*.py", True),
        ("a/b/c.py", "a/*.py", False),
        ("a/b/c.py", "a/**", True),
        ("c.py", "**/*.py", True),
        ("x/y/c.py", "**/*.py", True),
        ("a.pyc", "*.py", False),
        (".github/x.yml", ".github/**", True),
        ("Dockerfile.dev", "Dockerfile*", True),
        ("a-b", "a?b", True),
    ],
)
def test_matches_follows_picomatch_for_the_syntax_pr_yml_uses(
    path: str, rule: str, hit: bool
) -> None:
    assert path_filters.matches(path, rule) is hit


@pytest.mark.parametrize(
    "rule", ["'!docs/**'", "'{a,b}/**'", "'[ab]/**'", "{added: 'a/**'}", "'./docs/**'"]
)
def test_a_rule_the_matcher_does_not_know_is_refused_not_matched_wrongly(rule: str) -> None:
    with pytest.raises(ValueError, match="syntax matches"):
        path_filters.load_filters(_with_filters(f"py:\n  - {rule}\n"))


@pytest.mark.parametrize("filters", ["py: 'docs/**'\n", "py:\n", "- py\n", "py: [a\n", "plain\n"])
def test_a_filters_block_that_is_no_mapping_of_lists_is_a_value_error_not_a_traceback(
    filters: str,
) -> None:
    with pytest.raises(ValueError, match=r"filter 'py'|filters"):
        path_filters.load_filters(_with_filters(filters))


def test_a_workflow_or_step_of_another_shape_is_a_value_error_with_a_message(
    tmp_path: Path,
) -> None:
    workflow = path_filters.load_workflow()
    step = path_filters.filter_step(workflow)
    step["with"]["predicate-quantifier"] = "every"  # changes what a rule matches: not modelled
    with pytest.raises(ValueError, match="predicate-quantifier"):
        path_filters.load_filters(workflow)
    del step["with"]["predicate-quantifier"]
    del step["with"]["filters"]
    steps = {"jobs": {"changed-paths": {"steps": [1]}}}  # a step that is no mapping
    for broken in (
        workflow,
        {},
        {"jobs": {"changed-paths": {}}},
        {"jobs": {"changed-paths": 1}},
        steps,
    ):
        with pytest.raises(ValueError, match="cannot be read"):
            path_filters.load_filters(broken)
    for text, message in (("a: [b\n", "is not YAML"), ("- a\n", "is not a workflow")):
        (tmp_path / "pr.yml").write_text(text, encoding="utf-8")
        with pytest.raises(ValueError, match=message):
            path_filters.load_workflow(tmp_path / "pr.yml")


def test_the_filter_step_must_be_exactly_one_dorny_step_of_changed_paths() -> None:
    workflow = path_filters.load_workflow()
    steps = workflow["jobs"]["changed-paths"]["steps"]
    dorny = path_filters.filter_step(workflow)
    workflow["jobs"]["changed-paths"]["steps"] = [s for s in steps if s is not dorny]
    with pytest.raises(ValueError, match="found 0"):
        path_filters.filter_step(workflow)
    workflow["jobs"]["changed-paths"]["steps"] = [*steps, dorny]
    with pytest.raises(ValueError, match="found 2"):
        path_filters.filter_step(workflow)


def test_changed_reads_the_pr_yml_of_its_tree_and_lists_commits_edits_and_new_files(
    tmp_path: Path,
) -> None:
    (tmp_path / ".github").mkdir()
    shutil.copytree(WORKFLOWS, tmp_path / ".github" / "workflows")
    pr_yml = tmp_path / ".github" / "workflows" / "pr.yml"
    text = pr_yml.read_text(encoding="utf-8")
    assert text.count("- 'docs/**'") == 1
    pr_yml.write_text(
        text.replace("- 'docs/**'", "- 'edited'"), encoding="utf-8"
    )  # a doctored rule
    _git(tmp_path, "init", "-q", "-b", "main")
    for name in ("kept", "edited", "staged", "gone", "committed"):
        _write(tmp_path, name, "one\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-q", "-m", "base")
    base = _git(tmp_path, "rev-parse", "HEAD")
    _git(tmp_path, "checkout", "-q", "-b", "feat")
    _write(tmp_path, "committed", "two\n")
    _git(tmp_path, "commit", "-q", "-am", "branch")
    _write(tmp_path, "staged", "two\n")
    _git(tmp_path, "add", "staged")
    _write(tmp_path, "edited", "two\n")
    (tmp_path / "gone").unlink()
    _write(tmp_path, "new")
    change = pr_gate.changed(tmp_path, "main")
    assert change.paths == ("committed", "edited", "gone", "new", "staged")
    assert change.base == base
    assert change.present == ["committed", "edited", "new", "staged"]
    assert change.selected["docs"], "the selection must follow the pr.yml of the tree it runs in"
    assert not path_filters.select(["edited"], path_filters.load_filters())["docs"]
    with pytest.raises(RuntimeError, match="merge-base"):
        pr_gate.changed(tmp_path, "no/such/ref")


def test_the_header_names_the_base_and_the_lanes(tmp_path: Path) -> None:
    change = _change(tmp_path, ["docs/a.md", "services/api/x.py"], base="0123456789abcdef")
    head = pr_gate.header(change, "origin/main")
    assert head == "pr-gate: 2 changed path(s) vs origin/main (012345678); lanes: py, docs"


def test_a_filter_the_gate_maps_to_nothing_is_named_as_one_that_runs_nothing(
    tmp_path: Path,
) -> None:
    workflow = path_filters.load_workflow()
    path_filters.filter_step(workflow)["with"]["filters"] += "newlane:\n  - 'lane/**'\n"
    paths = ("lane/a", "tools/ci/x.py", "apps/web/x.ts", "docs/a.md")
    selected = path_filters.select(paths, path_filters.load_filters(workflow))
    head = pr_gate.header(pr_gate.Change(tmp_path, paths, "abc", workflow, selected), "main")
    first, note = head.splitlines()
    assert first.startswith("pr-gate: 4 changed path(s) vs main (abc);")
    assert note.startswith("pr-gate: unmapped filter, runs nothing here: ")
    unmapped = set(note.rpartition(": ")[2].split(", "))
    assert {"newlane", "js"} <= unmapped and not unmapped & {"py", "docs", "infra"}
    assert len(pr_gate.header(_change(tmp_path, ["tools/ci/x.py"]), "main").splitlines()) == 1


def test_main_passes_fast_on_prints_the_header_first_and_exits_on_failures(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    change = _change(tmp_path, ["docs/a.md"])
    seen: list[bool] = []

    def spy(c: Any, fast: bool) -> list[Any]:
        seen.append(fast)
        return []

    monkeypatch.setattr(pr_gate, "changed", lambda root, base: change)
    monkeypatch.setattr(pr_gate, "plan", spy)
    assert [pr_gate.main(["--fast"]), pr_gate.main([])] == [0, 0]
    assert seen == [True, False]
    assert "lanes: docs" in capsys.readouterr().out
    for status, code in (("PASS", 0), ("SKIP", 0), ("PARTIAL", 0), ("FAIL", 1)):
        step = pr_gate.Step("g", "s", functools.partial(_verdict, status))
        monkeypatch.setattr(pr_gate, "plan", lambda c, fast, step=step: [step])
        assert pr_gate.main([]) == code
    monkeypatch.undo()
    assert pr_gate.main(["--base", "no/such/ref"]) == 2


def test_fast_skips_the_tests_of_a_docs_only_change_shows_them_as_skipped_and_only_of_that(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _fake_tools(monkeypatch)
    _write(tmp_path, "docs/a.md")
    _write(tmp_path, "scripts/tests/test_docs.py", "Path('docs/a.md').read_text()\n")
    docs = _change(tmp_path, ["docs/a.md"])
    assert docs.docs_only and not _change(tmp_path, ["docs/a.md", "tools/ci/x.py"]).docs_only
    assert not _change(tmp_path, ["docs/plan/22-api-openapi.yaml"]).docs_only  # the protocol filter
    assert not _change(tmp_path, []).docs_only

    def tests(change: Any, fast: bool) -> dict[str, Any]:
        return {s.gate: s for s in pr_gate.plan(change, fast) if s.gate.startswith("pytest")}

    assert _argv(calls, tests(docs, fast=False)["pytest-scripts"])[1:3] == ["-m", "pytest"]
    calls.clear()
    row = tests(docs, fast=True)["pytest-scripts"]  # the row stays in the table, as a SKIP
    assert row.run() == ("SKIP", "--fast: the change is docs only") and not calls
    assert row.scope == "1 file(s)"
    assert "rule-refs" in {s.gate for s in pr_gate.plan(docs, fast=True)}  # never the scripts
    code = _change(tmp_path, ["docs/a.md", "tools/ci/x.py"])
    assert _argv(calls, tests(code, fast=True)["pytest-scripts"])[1:3] == ["-m", "pytest"]


def test_a_change_no_test_follows_gets_a_row_that_says_so(tmp_path: Path) -> None:
    for fast in (False, True):
        steps = pr_gate.test_steps(_change(tmp_path, [_write(tmp_path, "a.txt")]), fast)
        assert [(s.gate, s.scope) for s in steps] == [("pytest", "none selected")]
        assert steps[0].run() == ("SKIP", "no tests selected for the changed files")


def test_an_alert_without_a_drill_matrix_row_fails_the_gate_and_a_row_clears_it(
    tmp_path: Path,
) -> None:
    (tmp_path / "scripts").mkdir()
    shutil.copy(ROOT / "scripts" / "check_e04_test_plan.py", tmp_path / "scripts")
    alert = _write(tmp_path, "infra/prometheus/alerts/recorder_alerts.yml", ALERT)
    _write(tmp_path, "qa/plans/e04-observability-test-plan.md", PLAN)
    matrix = tmp_path / _write(
        tmp_path, "qa/plans/e04-alert-drill-matrix.md", "| PostgresDown | x |\n"
    )

    def alert_gate() -> tuple[str, str]:
        steps = {s.gate: s for s in pr_gate.plan(_change(tmp_path, [alert]))}
        return steps["alert-drill-matrix"].run()

    status, detail = alert_gate()
    assert status == "FAIL"
    assert "GuardFailed: missing from alert drill matrix" in detail
    matrix.write_text("| GuardFailed | x |\n", encoding="utf-8")
    assert alert_gate() == ("PASS", "")


@pytest.mark.parametrize(
    ("path", "paths"),
    [
        (
            "candleviewer/bars/a.py",
            ["tests/unit/bars", "tests/unit/bench", "tests/unit/ws/test_h.py"],
        ),
        ("bench/b.py", ["tests/unit/bench", "tests/unit/journal/test_j.py"]),
    ],
)
def test_a_bars_or_bench_change_runs_the_bench_pins_and_the_tests_that_import_the_module(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, path: str, paths: list[str]
) -> None:
    calls = _fake_tools(monkeypatch)
    for unit in ("bars", "bench"):
        (tmp_path / UNIT / unit).mkdir(parents=True)
    _write(tmp_path, f"{UNIT}/ws/test_h.py", "from candleviewer.bars.models import BarSpec\n")
    _write(tmp_path, f"{UNIT}/ws/test_t.py", "from candleviewer.barstool import x\n")  # not bars
    _write(tmp_path, f"{UNIT}/journal/test_j.py", "import bench.journal_analytics\n")
    changed = _change(tmp_path, [_write(tmp_path, f"{API}/{path}")])
    argv = _argv(calls, {s.gate: s for s in pr_gate.plan(changed)}["pytest-api"])
    marks = argv.index("-m") + 1
    assert argv[marks] == pr_gate.LOCAL_MARKERS
    assert {"--tb=line", "--no-cov"} <= set(argv)
    assert argv[marks + 1 :] == paths


def test_a_changed_test_that_logs_a_password_name_fails_the_gate_and_the_reminder_prints(
    tmp_path: Path,
) -> None:
    rel = _write(tmp_path, f"{UNIT}/observability/test_redaction.py", LOGGED)
    change = _change(tmp_path, [rel])
    step = {s.gate: s for s in pr_gate.plan(change)}["codeql-logging"]
    status, detail = step.run()
    assert status == "FAIL"
    assert f"{rel}:8: `_PASSWORD` reaches a logger" in detail
    out = pr_gate.report(change, [pr_gate.Result(step.gate, step.scope, status, 0.1, detail)])
    assert out.count(pr_gate.CODEQL_NOTE) == 2  # in the failure and as the reminder
    clean = _change(tmp_path, [_write(tmp_path, f"{UNIT}/test_ok.py")])
    assert pr_gate.report(clean, []).count(pr_gate.CODEQL_NOTE) == 1


@pytest.mark.parametrize(
    "method", ["debug", "info", "warning", "warn", "error", "exception", "critical", "log"]
)
@pytest.mark.parametrize(
    "name", ["password", "PASSWD", "passcode", "passphrase", "user_password", "self.password"]
)
def test_a_password_named_value_that_reaches_a_logger_is_found_by_line(
    name: str, method: str
) -> None:
    source = f"import logging\n\n\ndef f() -> None:\n    logging.{method}('x', {name})\n"
    assert pr_gate.logged_passwords(source) == [(5, name.rpartition(".")[2])]


def test_a_password_in_a_message_a_raise_or_another_call_is_no_finding() -> None:
    fstring = LOGGED.replace("'%s', _PASSWORD", 'f"{_PASSWORD}"')
    keyword = LOGGED.replace("'%s', _PASSWORD", '"op", error=ValueError(f"{_PASSWORD}")')
    for source in (LOGGED, fstring, keyword):
        assert pr_gate.logged_passwords(source) == [(8, "_PASSWORD")]
        assert pr_gate.logged_passwords(source.replace("_PASSWORD", "_VALUE")) == []
    quiet = "import logging\nlogging.info('password policy')\nx.append(password)\nprint(password)\n"
    assert pr_gate.logged_passwords(quiet) == []
    assert pr_gate.logged_passwords("raise ValueError(f'{password}')\n") == []


def test_the_pattern_check_leaves_out_what_codeqls_own_config_ignores(tmp_path: Path) -> None:
    config = "paths-ignore:\n  - docs/research/**\n  - .semgrep/tests/**\n"
    _write(tmp_path, ".github/codeql/codeql-config.yml", config)
    fixture = _write(tmp_path, ".semgrep/tests/cv-storage-log-credential.py", LOGGED)
    kept = _write(tmp_path, f"{UNIT}/observability/test_redaction.py", LOGGED)
    assert "codeql-logging" not in {s.gate for s in pr_gate.plan(_change(tmp_path, [fixture]))}
    steps = {s.gate: s for s in pr_gate.plan(_change(tmp_path, [fixture, kept]))}
    assert steps["codeql-logging"].scope == "1 test file(s)"
    assert steps["codeql-logging"].run()[0] == "FAIL"
    assert pr_gate.codeql_ignored(tmp_path) == ["docs/research/**", ".semgrep/tests/**"]
    assert pr_gate.codeql_ignored(tmp_path / "nowhere") == []
    real = pr_gate.codeql_ignored(ROOT)  # the shipped config skips the semgrep rule fixtures
    assert any(path_filters.matches(".semgrep/tests/x.py", glob) for glob in real)


def test_a_test_file_the_pattern_check_cannot_read_is_named_and_never_passed_in_silence(
    tmp_path: Path,
) -> None:
    broken = _write(tmp_path, f"{UNIT}/test_broken.py", "def f(:\n")
    binary = f"{UNIT}/test_binary.py"
    (tmp_path / binary).write_bytes(b"\xff\xfe")

    def codeql(paths: list[str]) -> tuple[str, str]:
        return {s.gate: s for s in pr_gate.plan(_change(tmp_path, paths))}["codeql-logging"].run()

    status, detail = codeql([broken, binary])
    assert status == "PARTIAL"  # counted in the verdict, never a PASS
    assert f"{broken}: not checked, SyntaxError" in detail
    assert f"{binary}: not checked, UnicodeDecodeError" in detail
    hit = _write(tmp_path, f"{UNIT}/test_hit.py", LOGGED)
    status, detail = codeql([broken, hit])
    assert status == "FAIL" and f"{hit}:8:" in detail and "not checked, SyntaxError" in detail


def test_plan_has_every_family_of_steps_and_each_tool_gets_its_argv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _fake_tools(monkeypatch)
    _write(
        tmp_path, ".github/workflows/_job-py.yml", (WORKFLOWS / "_job-py.yml").read_text("utf-8")
    )
    _write(tmp_path, ".semgrep/cv-x.yml", "rules: []\n")
    (tmp_path / UNIT / "bars").mkdir(parents=True)
    extra = _write(tmp_path, "tools/statechart/nightly_gate.py")
    test = _write(tmp_path, f"{UNIT}/observability/test_redaction.py", LOGGED)
    _write(tmp_path, "scripts/tests/test_nightly.py", "from nightly_gate import main\n")
    changed = _change(tmp_path, [_write(tmp_path, BARS), test, extra], base="abc1234")
    steps = {s.gate: s for s in pr_gate.plan(changed)}
    extras = pr_gate.py_lane_extras(tmp_path)
    assert len(extras) == 3 and f"../../{extra}" in extras  # the three targets of _job-py.yml
    # governance and lane scripts
    assert {"rule-refs", "alert-drill-matrix", "statechart-lint", "alert-rules"} <= steps.keys()
    assert _argv(calls, steps["rule-refs"])[0] == sys.executable
    uv_python = ["uv", "run", "--frozen", "--project", API, "python"]
    assert _argv(calls, steps["machine-hash-lock"])[:6] == uv_python
    assert _argv(calls, steps["rule-ir-schema"])[:6] == uv_python
    # lint, types, contracts, Semgrep, gitleaks
    ruff = _argv(calls, steps["ruff"])
    assert ruff[:6] == ["uv", "run", "--frozen", "ruff", "check", "--"]  # `--`: a name is no option
    assert ruff[6:] == ["candleviewer/bars/a.py", test.removeprefix(f"{API}/"), f"../../{extra}"]
    assert _argv(calls, steps["ruff-format"])[3:7] == ["ruff", "format", "--check", "--"]
    mypy = _argv(calls, steps["mypy"])
    assert mypy[3:7] == ["mypy", "--strict", "--platform", "linux"]
    assert mypy[7:] == ["candleviewer", "cvdev", *extras]
    assert _argv(calls, steps["import-linter"]) == ["uv", "run", "--frozen", "lint-imports"]
    semgrep = _argv(calls, steps["semgrep"])
    assert semgrep[:2] == ["semgrep", "scan"] and "--error" in semgrep
    assert semgrep[semgrep.index("--config") + 1] == ".semgrep/cv-x.yml"
    files = semgrep[semgrep.index("--") + 1 :]  # after `--` only: a name is no option
    assert BARS in files and extra in files
    gitleaks = _argv(calls, steps["gitleaks"])
    assert gitleaks[:4] == ["gitleaks", "git", "--log-opts", "abc1234..HEAD"]
    # the CodeQL pattern check and the tests
    assert steps["codeql-logging"].run()[0] == "FAIL"
    assert _argv(calls, steps["pytest-scripts"])[1:3] == ["-m", "pytest"]
    assert "--tb=line" in _argv(calls, steps["pytest-api"])
    assert list(steps)[-1] == "gen-freshness"  # last: it deletes the tracked generated files


def test_gen_freshness_runs_on_every_change_as_ci_does_and_skips_visibly_without_its_toolchain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _fake_tools(monkeypatch)
    for paths in (["docs/a.md"], ["packages/protocol/x.json"], ["tools/gen/export_x.py"], []):
        gates = [s.gate for s in pr_gate.plan(_change(tmp_path, paths))]
        assert gates.count("gen-freshness") == 1 and gates[-1] == "gen-freshness"
    gen = pr_gate.plan(_change(tmp_path, ["docs/a.md"]))[-1]
    calls.clear()
    status, why = gen.run()  # tmp_path has no node_modules
    assert status == "SKIP" and "pnpm install --frozen-lockfile" in why and not calls
    (tmp_path / "node_modules").mkdir()
    assert gen.run() == ("PASS", "") and calls == [[sys.executable, pr_gate.GEN_CHECK]]
    monkeypatch.setattr(pr_gate.shutil, "which", lambda name: None if name == "pnpm" else name)
    calls.clear()
    assert gen.run()[0] == "SKIP" and not calls  # node_modules is there, pnpm is not


def test_a_file_the_py_lane_checks_beyond_services_api_alone_runs_ruff_and_mypy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _fake_tools(monkeypatch)
    _write(
        tmp_path, ".github/workflows/_job-py.yml", (WORKFLOWS / "_job-py.yml").read_text("utf-8")
    )
    extra = _write(tmp_path, "docs/research/xstate/gate/run_gate.py")
    steps = {s.gate: s for s in pr_gate.plan(_change(tmp_path, [extra]))}
    assert _argv(calls, steps["ruff"])[6:] == [f"../../{extra}"]
    assert "mypy" in steps and "import-linter" not in steps  # contracts follow candleviewer only


def test_tests_follow_the_changed_files(tmp_path: Path) -> None:
    paths = [
        _write(tmp_path, f"{API}/candleviewer/oms/order.py"),
        _write(tmp_path, f"{API}/candleviewer/settings.py"),
        _write(tmp_path, f"{UNIT}/oms/test_order.py"),
        _write(tmp_path, f"{UNIT}/test_settings_fx.py"),
        _write(tmp_path, f"{UNIT}/oms/conftest.py"),
        _write(tmp_path, f"{API}/tests/conftest.py"),  # a root conftest would run the whole suite
        _write(tmp_path, f"{API}/tests/integration/audit/test_pg.py"),  # Docker: left to CI
        _write(tmp_path, f"{API}/tests/chaos/test_kill.py"),
        _write(tmp_path, "scripts/check_foo_bar.py"),
        _write(tmp_path, "docs/guide.md"),
        _write(tmp_path, "AGENTS.md"),
        _write(tmp_path, "CONSTITUTION.md"),
        _write(tmp_path, "Makefile"),
        _write(tmp_path, "README.md"),
        _write(tmp_path, "package.json"),
        f"{API}/candleviewer/gone.py",
    ]
    _write(tmp_path, "scripts/tests/test_check_foo_bar.py", "from check_foo_bar import main\n")
    _write(tmp_path, "scripts/tests/test_guide.py", "Path('docs/guide.md')\n")
    _write(tmp_path, "scripts/tests/test_agents.py", "Path('AGENTS.md').read_text()\n")
    _write(tmp_path, "scripts/tests/test_rules.py", "Path('CONSTITUTION.md').read_text()\n")
    _write(tmp_path, "scripts/tests/test_make.py", "Path('Makefile').read_text()\n")
    _write(tmp_path, "scripts/tests/test_readme.py", "Path('README.md')\nPath('package.json')\n")
    mention = "# AGENTS.md section 3a, CONSTITUTION.md, Makefile and docs/guide.md: prose only\n"
    _write(tmp_path, "scripts/tests/test_mentions.py", mention)
    api, gov = pr_gate.select_tests(tmp_path, paths)
    assert api == [f"{UNIT}/oms", f"{UNIT}/test_settings_fx.py"]  # the oms dir covers its test
    assert gov == [
        f"scripts/tests/test_{name}.py"
        for name in ("agents", "check_foo_bar", "guide", "make", "rules")
    ]


def test_the_pyproject_and_the_lock_of_services_api_run_the_unit_tests_that_name_them(
    tmp_path: Path,
) -> None:
    paths = [_write(tmp_path, f"{API}/pyproject.toml"), _write(tmp_path, f"{API}/uv.lock")]
    _write(tmp_path, f"{UNIT}/exchange/test_pack.py", "p = root / 'pyproject.toml'\n")
    _write(tmp_path, f"{UNIT}/test_lock.py", "Path('services/api/uv.lock')\n")
    _write(tmp_path, f"{UNIT}/test_prose.py", "# the pyproject.toml of services/api: prose only\n")
    _write(tmp_path, "scripts/tests/test_root.py", "Path('pyproject.toml')\n")  # not services/api's
    both = ([f"{UNIT}/exchange/test_pack.py", f"{UNIT}/test_lock.py"], [])
    assert pr_gate.select_tests(tmp_path, paths) == both
    assert pr_gate.select_tests(tmp_path, paths[:1]) == (both[0][:1], [])
    other = _write(tmp_path, f"{API}/alembic.ini", "pyproject.toml\n")  # services/api, no input
    assert pr_gate.select_tests(tmp_path, [other]) == ([], [])


FCNTL = "E   ModuleNotFoundError: No module named 'fcntl'\n"


def _pytest_output(errors: str = "", failures: str = "", summary: str = "") -> str:
    """pytest -q --tb=line: error blocks, then failures, then the summary that repeats them."""
    out = f"==== ERRORS ====\n{errors}" if errors else ""
    out += f"==== FAILURES ====\n{failures}" if failures else ""
    return out + f"==== short test summary info ====\n{summary}1 failed in 1s\n"


def test_on_windows_what_needs_fcntl_is_partial_and_never_a_pass() -> None:
    blocks = f"____ ERROR collecting tests/unit/bench/test_e08_engine.py ____\n{FCNTL}"
    failed = (
        "FAILED tests/unit/bars/test_a.py::test_b - ModuleNotFoundError: No module named 'fcntl'"
    )
    posix = _pytest_output(
        errors=blocks,
        failures=f"{FCNTL}j.py:12: ModuleNotFoundError: No module named 'fcntl'\n",
        summary=f"{failed}\nERROR tests/unit/bench/test_e08_engine.py\n",
    )
    status, note = pr_gate.pytest_status(1, posix, windows=True)
    assert status == "PARTIAL"
    assert "tests/unit/bench/test_e08_engine.py" in note and "tests/unit/bars/test_a.py" in note
    assert pr_gate.pytest_status(1, posix, windows=False)[0] == "FAIL"
    assert pr_gate.pytest_status(0, "", windows=True) == ("PASS", "")
    assert pr_gate.pytest_status(5, "no tests ran", windows=False) == ("PASS", "")


def test_a_genuine_failure_next_to_a_posix_error_is_a_failure() -> None:
    blocks = f"____ ERROR collecting tests/unit/bench/test_e08_engine.py ____\n{FCNTL}"
    assertion = (
        "FAILED tests/t.py::test_x - assert 1 == 2\nERROR tests/unit/bench/test_e08_engine.py\n"
    )
    line_mode = _pytest_output(errors=blocks, failures="t.py:3: assert 1 == 2\n", summary=assertion)
    assert pr_gate.pytest_status(1, line_mode, windows=True)[0] == "FAIL"
    windows_note = pr_gate.pytest_status(1, line_mode, windows=True)[1].splitlines()[-1]
    assert windows_note.startswith("Windows: tests that need fcntl")  # a failure there may be that
    assert "Windows:" not in pr_gate.pytest_status(1, line_mode, windows=False)[1]
    full = _pytest_output(
        errors=blocks, failures="____ test_x ____\nE   assert 1 == 2\n", summary=assertion
    )
    assert pr_gate.pytest_status(1, full, windows=True)[0] == "FAIL"
    setup = "ERROR tests/t.py::test_y - KeyError: 'a'\n"
    assert pr_gate.pytest_status(1, _pytest_output(errors=blocks, summary=setup), True)[0] == "FAIL"
    posix_setup = "ERROR tests/t.py::test_y - ModuleNotFoundError: No module named 'termios'\n"
    assert pr_gate.pytest_status(1, _pytest_output(summary=posix_setup), True)[0] == "PARTIAL"
    # the summary repeats the POSIX failures: it must not be read as part of the last error block
    bad = "____ ERROR collecting tests/t_bad.py ____\nE   SyntaxError: invalid syntax\n"
    summary = "FAILED tests/u.py::test_z - ModuleNotFoundError: No module named 'fcntl'\n"
    assert (
        pr_gate.pytest_status(1, _pytest_output(blocks + bad, summary=summary), True)[0] == "FAIL"
    )


@pytest.mark.parametrize("module", ["fcntl", "termios", "resource", "pwd", "grp"])
def test_each_posix_only_module_is_recognised(module: str) -> None:
    line = f"FAILED tests/t.py::test_x - ModuleNotFoundError: No module named '{module}'\n"
    assert pr_gate.pytest_status(1, _pytest_output(summary=line), windows=True)[0] == "PARTIAL"


def test_a_conftest_that_cannot_import_aborts_the_step_as_partial_not_pass() -> None:
    abort = f"ImportError while loading conftest '/r/tests/conftest.py'.\n{FCNTL}"
    status, note = pr_gate.pytest_status(4, abort, windows=True)
    assert status == "PARTIAL" and "/r/tests/conftest.py" in note
    assert pr_gate.pytest_status(4, abort, windows=False)[0] == "FAIL"
    assert pr_gate.pytest_status(4, "ERROR: file or directory not found: x\n", True)[0] == "FAIL"


def test_a_failure_from_winerror_1314_says_what_it_needs() -> None:
    symlink = "FAILED t.py::test_x - OSError: [WinError 1314] A required privilege is not held\n"
    status, detail = pr_gate.pytest_status(1, _pytest_output(summary=symlink), windows=True)
    assert status == "FAIL"
    assert detail.splitlines()[-1].startswith("WinError 1314: this account may not create symlinks")
    assert "WinError 1314" not in pr_gate.pytest_status(1, "FAILED t.py::t - assert 0\n", True)[1]


#: A step that starts a grandchild, which appends to a file every 50 ms (for 20 s at most, so that
#: a regression fails a test and never hangs it), and then waits: a `uv run pytest` in miniature.
BEAT = (
    "import sys, time\n"
    "for _ in range(400):\n"
    "    open(sys.argv[1], 'a').write('.')\n"
    "    time.sleep(0.05)\n"
)
TREE = (
    "import subprocess, sys, time\n"
    "subprocess.Popen([sys.executable, '-c', sys.argv[1], sys.argv[2]])\n"
    "time.sleep(60)\n"
)


def _tree(tmp_path: Path) -> tuple[list[str], Path]:
    beat = tmp_path / "beat"
    return [sys.executable, "-c", TREE, BEAT, str(beat)], beat


def _beats(beat: Path) -> int:
    return beat.stat().st_size if beat.exists() else 0


def _running(beat: Path) -> None:
    """Wait until the grandchild has beaten a few times."""
    deadline = time.monotonic() + 30
    while _beats(beat) < 3:
        assert time.monotonic() < deadline, "the grandchild never started"
        time.sleep(0.05)


def _stopped(beat: Path) -> bool:
    before = _beats(beat)
    time.sleep(0.5)
    return _beats(beat) == before


def test_kill_tree_ends_a_step_and_the_grandchild_it_started(tmp_path: Path) -> None:
    argv, beat = _tree(tmp_path)
    step = subprocess.Popen(argv, start_new_session=True)  # as run_command starts a step
    try:
        _running(beat)
        pr_gate.kill_tree(step)
        assert step.wait(timeout=10) != 0
        assert _stopped(beat), "the grandchild outlived its step"
    finally:
        step.kill()


def test_a_step_that_outruns_its_timeout_is_killed_with_its_tree_and_fails_with_the_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    argv, beat = _tree(tmp_path)
    monkeypatch.setattr(pr_gate, "STEP_TIMEOUT", 4)
    started = time.monotonic()
    assert pr_gate.run_command(argv, tmp_path) == (
        124,
        f"{sys.executable} timed out after 0 minutes",
    )
    assert time.monotonic() - started < 30  # the 4 s timeout, not the minute the step waits
    assert _beats(beat) > 0 and _stopped(beat), "the grandchild outlived its step"
    monkeypatch.setattr(pr_gate, "run_command", lambda a, c: (124, "x timed out"))
    assert pr_gate.command("g", "s", argv, tmp_path).run() == ("FAIL", "x timed out")


def test_ctrl_c_in_a_step_kills_what_it_started_and_goes_on_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    argv, beat = _tree(tmp_path)
    wait = subprocess.Popen.wait
    asked: list[object] = []

    def interrupt(self: subprocess.Popen[bytes], timeout: float | None = None) -> int:
        if asked:
            return wait(self, timeout)  # the wait that reaps the step once it is killed
        asked.append(timeout)
        _running(beat)
        raise KeyboardInterrupt

    monkeypatch.setattr(subprocess.Popen, "wait", interrupt)
    with pytest.raises(KeyboardInterrupt):
        pr_gate.run_command(argv, tmp_path)
    assert _stopped(beat), "the grandchild outlived its step"


def test_a_steps_output_is_kept_as_its_tail_with_unix_newlines_and_its_exit_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pr_gate, "OUTPUT_LIMIT", 64)  # the summary comes last: keep the end
    code = "import sys; sys.stdout.buffer.write(b'x' * 500 + b'\\r\\nsummary\\n'); sys.exit(3)"
    assert pr_gate.run_command([sys.executable, "-c", code], tmp_path) == (
        3,
        "x" * 54 + "\nsummary\n",
    )


def test_a_scanner_that_is_not_installed_is_skipped_not_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pr_gate.shutil, "which", lambda name: None)
    steps = {s.gate: s for s in pr_gate.tool_steps(_change(ROOT, ["tools/ci/pr_gate.py"]))}
    assert steps["semgrep"].run() == ("SKIP", "semgrep is not installed")
    assert steps["gitleaks"].run() == ("SKIP", "gitleaks is not installed")


def test_the_summary_is_one_table_with_each_failures_output_below_it(tmp_path: Path) -> None:
    results = [
        pr_gate.Result("rule-refs", "every change", "PASS", 0.84, ""),
        pr_gate.Result("ruff", "2 file(s)", "FAIL", 3.0, "x.py:1:1: E501 line too long\n"),
        pr_gate.Result("semgrep", "1 file(s)", "SKIP", 0.0, "semgrep is not installed"),
        pr_gate.Result("pytest-api", "1 path(s)", "PARTIAL", 0.0, "not run on Windows: a.py"),
    ]
    out = pr_gate.report(_change(tmp_path, ["services/api/x.py"]), results).splitlines()
    assert out[0].split() == ["gate", "scope", "result", "seconds"]
    assert out[2].split() == ["rule-refs", "every", "change", "PASS", "0.8"]
    assert out[3].split() == ["ruff", "2", "file(s)", "FAIL", "3.0"]
    assert {"--- ruff failed ---", "x.py:1:1: E501 line too long"} <= set(out)
    assert "  semgrep: semgrep is not installed" in out
    assert "  pytest-api: not run on Windows: a.py" in out
    assert out[-1] == "pr-gate: FAIL (1 skipped, 1 partial) in 4 s"
    assert out[-2] == pr_gate.LEFT_TO_CI


def test_a_skipped_or_partial_gate_is_no_clean_pass_in_the_verdict(tmp_path: Path) -> None:
    change = _change(tmp_path, ["a.txt"])
    clean = [pr_gate.Result("g", "s", "PASS", 1.0, "")]
    skipped = [*clean, pr_gate.Result("h", "s", "SKIP", 0.0, "h is not installed")]
    partial = [*skipped, pr_gate.Result("i", "s", "PARTIAL", 0.0, "not run")]
    assert pr_gate.report(change, clean).splitlines()[-1] == "pr-gate: PASS in 1 s"
    assert pr_gate.report(change, skipped).splitlines()[-1] == "pr-gate: PASS (1 skipped) in 1 s"
    verdict = pr_gate.report(change, partial).splitlines()[-1]
    assert verdict == "pr-gate: PASS (1 skipped, 1 partial) in 1 s"


def test_what_is_left_to_ci_names_the_docker_tests_the_title_the_size_and_the_blind_spots() -> None:
    blind = (
        "tests outside scripts/tests and tests/unit that read a changed file",
        "modules without a tests/unit directory",
    )
    for left in (
        "integration and chaos tests (Docker)",
        "xstate-contract",
        "PR title",
        "PR-SIZE-001",
        "every CI lane or gate not in this table",
        *blind,
        "deletions",
    ):
        assert left in pr_gate.LEFT_TO_CI
    doc = " ".join((pr_gate.__doc__ or "").split())
    for said in ("wants a clean tree", "runs last", "what a deletion breaks", *blind):
        assert said in doc
    assert "not integration" in pr_gate.LOCAL_MARKERS and "not chaos" in pr_gate.LOCAL_MARKERS
    assert pr_gate.LOCAL_MARKERS.startswith(pr_gate.PYTEST_MARKERS)


#: Scripts the workflows run that the gate leaves out, each with its reason.
WAIVED = {
    "tools/ci/check_pin.py --root .",  # the xstate pin attestation downloads the wheel
    "scripts/check_sot_duplication.py",  # GOV-003: a known finding, informative in CI
}
CI_SCRIPT = re.compile(
    r"^\s+(?:run: )?python (?!.*gov-artifacts)"
    r"((?:scripts|tools|docs|infra)/\S+\.py(?: [\w.=/-]+)*)(?: \|\| status=1)?$",
    re.MULTILINE,
)


def _mirrored() -> set[str]:
    return set(pr_gate.ALWAYS.values()) | {
        s for d in pr_gate.ON_FILTER.values() for s in d.values()
    }


def test_every_python_script_line_of_the_pr_governance_and_py_workflows_is_mirrored_or_waived() -> (
    None
):
    """Only `python <script>` lines of pr.yml, governance.yml and _job-py.yml: no `uv run`, `pnpm`
    or docker step, and nothing a script runs inside; LEFT_TO_CI names what the gate leaves out."""
    ci = set()
    for name in ("pr.yml", "governance.yml", "_job-py.yml"):
        ci |= set(CI_SCRIPT.findall((WORKFLOWS / name).read_text(encoding="utf-8")))
    mirrored = {script.replace(" --offline", "") for script in _mirrored()}  # CI asks the registry
    assert sorted(ci - mirrored - WAIVED) == []
    assert {
        "infra/alertmanager/check_alert_rules.py",
        "infra/grafana/lint_dashboards.py --strict",
    } <= ci


def test_each_lane_script_starts_on_the_filter_its_workflow_step_or_job_names() -> None:
    pr = path_filters.load_workflow(WORKFLOWS / "pr.yml")
    gates = {s["id"]: str(s["if"]) for s in pr["jobs"]["gates"]["steps"] if "id" in s}
    py_lane = str(pr["jobs"]["py"]["if"])  # _job-py.yml's py-checks run on the py filter
    started_by = {
        "pin-check": gates["pin-check"],
        "pin-digests-offline": gates["pin-check"],
        "statechart-lint": gates["statechart-lint"],
        "event-coverage": gates["event-coverage"],
        "machine-hash-lock": gates["machine-hash-lock"],
        "alert-rules": py_lane,
        "dashboard-lint": py_lane,
        "rule-ir-schema": py_lane,
    }
    gated = {gate for scripts in pr_gate.ON_FILTER.values() for gate in scripts}
    assert gated == set(started_by)
    for gate, condition in started_by.items():
        named = set(re.findall(r"outputs\.(\w+) == 'true'", condition))
        assert {name for name, scripts in pr_gate.ON_FILTER.items() if gate in scripts} == named
    assert pr_gate.BACKEND_GATES <= gated


def test_the_markers_are_the_py_lanes_the_extras_are_its_three_and_the_tables_name_real_files() -> (
    None
):
    assert pr_gate.PYTEST_MARKERS in (WORKFLOWS / "_job-py.yml").read_text(encoding="utf-8")
    assert [e.rpartition("/")[2] for e in pr_gate.py_lane_extras(ROOT)] == [
        "_paths.py",
        "run_gate.py",
        "nightly_gate.py",
    ]
    assert all(
        (ROOT / f"{e.removeprefix('../../')}").is_file() for e in pr_gate.py_lane_extras(ROOT)
    )
    assert all((ROOT / script.split()[0]).is_file() for script in _mirrored())
    assert pr_gate.py_lane_extras(ROOT / "nowhere") == []


def test_the_gate_is_a_make_target_and_one_row_of_agents_md_with_its_python_form() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert re.search(r"^pr-gate:\n\t.*tools/ci/pr_gate\.py", makefile, re.MULTILINE)
    assert "pr-gate" in makefile.splitlines()[0]  # .PHONY
    assert "$(if $(filter-out 0,$(FAST)),--fast,)" in makefile  # FAST=0 is not fast
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert agents.count("`make pr-gate`") == 1
    assert "`python tools/ci/pr_gate.py [--fast]`" in agents  # Git Bash has no make
    assert "`make pr-gate` (clean tree)" in agents  # gen-freshness regenerates tracked files
