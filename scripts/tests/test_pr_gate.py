"""Tests for tools/ci/pr_gate.py (#3882). The three PR runs that went red on 2026-10-20 are
fixtures, each as the hunk that caused it, not as a checkout: an alert without a drill matrix row
(#3862), a bars change whose bench pins no lane ran (#3868), a test that logs a password-named
constant (#3875). No real scanner runs and nothing reaches the network."""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
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


def _change(root: Path, paths: list[str]) -> Any:
    workflow = path_filters.load_workflow()
    selected = path_filters.select(paths, path_filters.load_filters(workflow))
    return pr_gate.Change(root, tuple(paths), "HEAD", workflow, selected)


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


def test_selection_reads_the_rules_pr_yml_declares_and_keeps_no_copy() -> None:
    workflow = path_filters.load_workflow()
    declared = yaml.safe_load(path_filters.filter_step(workflow)["with"]["filters"])
    assert path_filters.load_filters() == declared
    assert set(declared) == set(workflow["jobs"]["changed-paths"]["outputs"]) - {"pr"}
    assert pr_gate.path_filters is path_filters


@pytest.mark.parametrize(
    ("path", "on"),
    [
        ("services/api/x.py", {"py"}),
        ("docs/a.md", {"docs"}),
        ("Makefile", {"protocol"}),
        ("a.txt", set()),
    ],
)
def test_select_marks_the_filters_the_changed_paths_match(path: str, on: set[str]) -> None:
    selected = path_filters.select([path], path_filters.load_filters())
    assert {name for name, hit in selected.items() if hit} == on


def test_fast_skips_the_tests_of_a_docs_only_change_and_only_of_that(tmp_path: Path) -> None:
    _write(tmp_path, "docs/a.md")
    _write(tmp_path, "scripts/tests/test_docs.py", "# reads docs/a.md\n")
    docs = _change(tmp_path, ["docs/a.md"])
    assert docs.docs_only and not _change(tmp_path, ["docs/a.md", "tools/ci/x.py"]).docs_only
    assert not _change(tmp_path, ["docs/plan/22-api-openapi.yaml"]).docs_only  # the protocol filter
    assert [s.gate for s in pr_gate.test_steps(docs, fast=False)] == ["pytest-scripts"]
    assert pr_gate.test_steps(docs, fast=True) == []


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
        steps = {s.gate: s for s in pr_gate.script_steps(_change(tmp_path, [alert]))}
        return steps["alert-drill-matrix"].run()

    status, detail = alert_gate()
    assert status == "FAIL"
    assert "GuardFailed: missing from alert drill matrix" in detail
    matrix.write_text("| GuardFailed | x |\n", encoding="utf-8")
    assert alert_gate() == ("PASS", "")


@pytest.mark.parametrize(
    ("path", "tests"),
    [
        ("candleviewer/bars/a.py", [f"{UNIT}/bars", f"{UNIT}/bench"]),
        ("bench/b.py", [f"{UNIT}/bench"]),
    ],
)
def test_a_bars_or_bench_change_selects_the_bench_pins(
    tmp_path: Path, path: str, tests: list[str]
) -> None:
    for unit in ("bars", "bench"):
        (tmp_path / UNIT / unit).mkdir(parents=True)
    assert pr_gate.select_tests(tmp_path, [_write(tmp_path, f"{API}/{path}")]) == (tests, [])


def test_a_password_named_value_that_reaches_a_logger_is_found_by_line() -> None:
    fstring = LOGGED.replace("'%s', _PASSWORD", 'f"{_PASSWORD}"')
    keyword = LOGGED.replace("'%s', _PASSWORD", '"op", error=ValueError(f"{_PASSWORD}")')
    for source in (LOGGED, fstring, keyword):
        assert pr_gate.logged_passwords(source) == [(8, "_PASSWORD")]
        assert pr_gate.logged_passwords(source.replace("_PASSWORD", "_VALUE")) == []
    assert pr_gate.logged_passwords('import logging\nlogging.info("password policy")\n') == []


def test_a_changed_test_that_logs_a_password_name_fails_the_gate_and_the_reminder_prints(
    tmp_path: Path,
) -> None:
    rel = _write(tmp_path, f"{UNIT}/observability/test_redaction.py", LOGGED)
    change = _change(tmp_path, [rel])
    step = {s.gate: s for s in pr_gate.check_steps(change)}["codeql-logging"]
    status, detail = step.run()
    assert status == "FAIL"
    assert f"{rel}:8: `_PASSWORD` reaches a logger" in detail
    out = pr_gate.report(change, [pr_gate.Result(step.gate, step.scope, status, 0.1, detail)])
    assert out.count(pr_gate.CODEQL_NOTE) == 2  # in the failure and as the reminder
    clean = _change(tmp_path, [_write(tmp_path, f"{UNIT}/test_ok.py")])
    assert pr_gate.report(clean, []).count(pr_gate.CODEQL_NOTE) == 1


def test_changed_lists_commits_edits_and_new_files_against_the_merge_base(tmp_path: Path) -> None:
    (tmp_path / ".github").mkdir()
    shutil.copytree(WORKFLOWS, tmp_path / ".github" / "workflows")
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


def test_tests_follow_the_changed_files(tmp_path: Path) -> None:
    paths = [
        _write(tmp_path, f"{API}/candleviewer/oms/order.py"),
        _write(tmp_path, f"{API}/candleviewer/settings.py"),
        _write(tmp_path, f"{UNIT}/oms/test_order.py"),
        _write(tmp_path, f"{UNIT}/test_settings_fx.py"),
        _write(tmp_path, f"{UNIT}/oms/conftest.py"),
        _write(tmp_path, f"{API}/tests/conftest.py"),  # a root conftest would run the whole suite
        _write(tmp_path, "scripts/check_foo_bar.py"),
        _write(tmp_path, "docs/guide.md"),
        _write(tmp_path, "Makefile"),
        f"{API}/candleviewer/gone.py",
    ]
    _write(tmp_path, "scripts/tests/test_check_foo_bar.py", "from check_foo_bar import main\n")
    _write(tmp_path, "scripts/tests/test_guide.py", "Path('docs/guide.md')\n")
    _write(tmp_path, "scripts/tests/test_other.py", "Path('Makefile')\n")  # a root file: no signal
    api, gov = pr_gate.select_tests(tmp_path, paths)
    assert api == [f"{UNIT}/oms", f"{UNIT}/test_settings_fx.py"]  # the oms dir covers its test
    assert gov == ["scripts/tests/test_check_foo_bar.py", "scripts/tests/test_guide.py"]


def test_on_windows_failures_that_are_only_missing_posix_modules_are_reported_not_failed() -> None:
    fcntl = "____ ERROR collecting a.py ____\nE   ModuleNotFoundError: No module named 'fcntl'\n"
    geteuid = "____ test_b ____\nE   AttributeError: module 'os' has no attribute 'geteuid'\n"
    posix = fcntl + geteuid
    assert pr_gate.pytest_status(1, posix, windows=True)[0] == "PASS"
    assert pr_gate.pytest_status(1, posix, windows=False)[0] == "FAIL"
    assert pr_gate.pytest_status(1, posix + "____ test_c ____\nE   assert 0\n", True)[0] == "FAIL"
    assert pr_gate.pytest_status(5, "no tests ran", windows=False) == ("PASS", "")


def test_a_scanner_that_is_not_installed_is_skipped_not_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pr_gate.shutil, "which", lambda name: None)
    steps = {s.gate: s for s in pr_gate.tool_steps(_change(ROOT, ["tools/ci/pr_gate.py"]))}
    assert steps["semgrep"].run() == ("SKIP", "semgrep is not installed")
    assert steps["gitleaks-staged"].run() == ("SKIP", "gitleaks is not installed")


def test_the_summary_is_one_table_with_each_failures_output_below_it(tmp_path: Path) -> None:
    results = [
        pr_gate.Result("rule-refs", "every change", "PASS", 0.84, ""),
        pr_gate.Result("ruff", "2 file(s)", "FAIL", 3.0, "x.py:1:1: E501 line too long\n"),
        pr_gate.Result("semgrep", "1 file(s)", "SKIP", 0.0, "semgrep is not installed"),
    ]
    out = pr_gate.report(_change(tmp_path, ["services/api/x.py"]), results).splitlines()
    assert out[0].split() == ["gate", "scope", "result", "seconds"]
    assert out[2].split() == ["rule-refs", "every", "change", "PASS", "0.8"]
    assert out[3].split() == ["ruff", "2", "file(s)", "FAIL", "3.0"]
    assert {"--- ruff failed ---", "x.py:1:1: E501 line too long"} <= set(out)
    assert "  semgrep: semgrep is not installed" in out
    assert out[-1] == "pr-gate: FAIL (4 s)"


def test_main_exits_non_zero_on_any_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    change = _change(tmp_path, ["a.txt"])
    monkeypatch.setattr(pr_gate, "changed", lambda root, base: change)
    for status, code in (("PASS", 0), ("SKIP", 0), ("FAIL", 1)):
        step = pr_gate.Step("g", "s", lambda status=status: (status, ""))  # type: ignore[misc]
        monkeypatch.setattr(pr_gate, "plan", lambda c, fast, step=step: [step])
        assert pr_gate.main([]) == code
    monkeypatch.undo()
    assert pr_gate.main(["--base", "no/such/ref"]) == 2


#: Scripts the workflows run that the gate leaves out, each with its reason.
WAIVED = {
    "tools/ci/check_pin.py --root .",  # the xstate pin attestation downloads the wheel
    "scripts/check_sot_duplication.py",  # GOV-003: a known finding, informative in CI
}
CI_SCRIPT = re.compile(
    r"^\s+(?:run: )?python (?!.*gov-artifacts)((?:scripts|tools|docs)/\S+\.py(?: [\w.=/-]+)*)"
    r"(?: \|\| status=1)?$",
    re.MULTILINE,
)


def _mirrored() -> set[str]:
    return set(pr_gate.ALWAYS.values()) | {
        s for d in pr_gate.ON_FILTER.values() for s in d.values()
    }


def test_the_gate_mirrors_every_script_the_workflows_run_and_starts_them_on_their_filters() -> None:
    ci = set()
    for name in ("pr.yml", "governance.yml"):
        ci |= set(CI_SCRIPT.findall((WORKFLOWS / name).read_text(encoding="utf-8")))
    mirrored = {
        script.replace(" --offline", "") for script in _mirrored()
    }  # CI asks the registry too
    assert sorted(ci - mirrored - WAIVED) == []
    gates = {
        s["id"]: s["if"]
        for s in path_filters.load_workflow(WORKFLOWS / "pr.yml")["jobs"]["gates"]["steps"]
        if "id" in s
    }
    for gate, step in (
        ("pin-check", "pin-check"),
        ("pin-digests", "pin-check"),
        ("statechart-lint", "statechart-lint"),
        ("event-coverage", "event-coverage"),
    ):
        named = set(re.findall(r"outputs\.(\w+) == 'true'", gates[step]))
        assert {name for name, scripts in pr_gate.ON_FILTER.items() if gate in scripts} == named


def test_the_markers_are_the_py_lanes_and_everything_the_tables_name_exists() -> None:
    assert pr_gate.PYTEST_MARKERS in (WORKFLOWS / "_job-py.yml").read_text(encoding="utf-8")
    assert all((ROOT / script.split()[0]).is_file() for script in _mirrored())


def test_the_gate_is_a_make_target_and_one_row_of_agents_md() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert re.search(r"^pr-gate:\n\t.*tools/ci/pr_gate\.py", makefile, re.MULTILINE)
    assert "pr-gate" in makefile.splitlines()[0]  # .PHONY
    assert (ROOT / "AGENTS.md").read_text(encoding="utf-8").count("`make pr-gate`") == 1
