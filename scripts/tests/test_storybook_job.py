"""#269 (E05-T03): the Storybook gate, the `storybook` job of `_job-a11y.yml`, beside `a11y`.

These tests pin the job's hardening and steps, run its self-test step under bash with stand-in
`pnpm` and `node`, and run its report script on synthetic Vitest JSON reports."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "packages" / "ui" / "scripts" / "storybook-a11y.mjs"
STEPS = {
    "run": "Run play functions and axe on every story (CI-A11Y-002)",
    "self-test": "Self-test: the gate fails closed on its fixture (CI-A11Y-003)",
    "budget": "Budget: the job finishes within 10 minutes (CI-A11Y-004)",
}
#: A stand-in `pnpm` / `node`: logs its arguments and the fixture switch, exits with <NAME>_EXIT.
FAKE = """import json, os, sys
with open(os.environ["CALLS"], "a", encoding="utf-8") as log:
    log.write(json.dumps([sys.argv[1:], os.environ.get("CV_STORYBOOK_A11Y_FIXTURES")]) + "\\n")
sys.exit(int(os.environ.get(os.path.basename(sys.argv[0]).upper() + "_EXIT", "0")))
"""


def _load(name: str) -> dict[str, Any]:
    doc: dict[str, Any] = yaml.safe_load((ROOT / ".github" / "workflows" / name).read_text())
    return doc


def _job() -> dict[str, Any]:
    job: dict[str, Any] = _load("_job-a11y.yml")["jobs"]["storybook"]
    return job


def _run(step: str) -> str:
    (run,) = [s["run"] for s in _job()["steps"] if s.get("name") == STEPS[step]]
    return str(run)


def _needs(tool: str) -> None:
    if not shutil.which(tool):  # CI must run these fail-closed proofs
        (pytest.fail if os.environ.get("CI") else pytest.skip)(f"{tool} runs this proof")


def test_storybook_job_runs_beside_a11y_hardened_and_uploads_only_the_a11y_report() -> None:
    job = _job()
    assert set(_load("_job-a11y.yml")["jobs"]) == {"a11y", "storybook"}
    # Parallel to `a11y` and able to fail it: no needs, no condition, no continue-on-error, no env.
    assert not {"needs", "if", "continue-on-error", "env"} & set(job)
    assert (job["permissions"], job["timeout-minutes"]) == ({"contents": "read"}, 15)
    steps = job["steps"]
    # Nor at step level: only the report upload has a condition (always()), none fails softly.
    # (plus the browser cache save, which runs only after a green install: test_playwright_browsers).
    conditions = [s.get("if") for s in steps if "if" in s and "cache/save@" not in s["uses"]]
    assert conditions == ["always()"] == [steps[-1].get("if")]
    assert not any("continue-on-error" in step for step in steps)
    uses = [step["uses"] for step in steps if "uses" in step]
    assert all(re.fullmatch(r"[\w.-]+/[\w.-]+@[0-9a-f]{40}", use) for use in uses), uses
    checkouts = [s["with"] for s in steps if "checkout@" in s.get("uses", "")]
    assert checkouts == [{"persist-credentials": False}]
    assert all("${{" not in step.get("run", "") for step in steps)
    assert "secrets." not in json.dumps(job)  # E05 STRIDE B6: no design-system job holds a secret
    names = [step.get("name", step.get("uses", "")) for step in steps]
    assert names[0] == "Start the budget clock"
    assert [names.index(name) for name in STEPS.values()] == sorted(
        map(names.index, STEPS.values())
    )
    uploads = [s["with"] for s in steps if "upload-artifact@" in s.get("uses", "")]
    assert [(u["name"], u["path"]) for u in uploads] == [
        ("storybook-a11y-report", "reports/storybook-a11y/")
    ]
    # The required `a11y` check is the reusable workflow's result, so this job's failure fails it.
    assert _load("pr.yml")["jobs"]["a11y"]["uses"] == "./.github/workflows/_job-a11y.yml"


def test_run_and_budget_steps_fail_with_their_codes() -> None:
    run = _run("run")
    (shell,) = [s.get("shell") for s in _job()["steps"] if s.get("name") == STEPS["run"]]
    assert shell == "bash"  # pipefail: a summary that cannot read the report sets rc too
    assert "storybook:test --reporter=default --reporter=json" in run
    summary = r'storybook-a11y\.mjs summary "\$report/results\.json" \|.* \|\| rc=1\n'
    assert re.search(r"rc=\$\?\n.*\n.*" + summary, run)
    assert re.search(r'if \[ "\$rc" -ne 0 \]; then\n.*CI-A11Y-002.*\n\s+exit 1', run)
    budget = r'if \[ "\$elapsed" -gt 600 \]; then\n.*CI-A11Y-004.*\n\s+exit 1'
    assert re.search(budget, _run("budget"))


def test_the_lanes_and_packages_ui_share_one_playwright_build() -> None:
    """The job installs the browser with apps/web's Playwright and drives it with packages/ui's."""
    lock = (ROOT / "pnpm-lock.yaml").read_text(encoding="utf-8")
    versions = set(re.findall(r"^  '?playwright(?:-core)?@([\d.]+)'?:$", lock, re.MULTILINE))
    assert len(versions) == 1, versions


def _fake_tools(tmp_path: Path, pnpm: int, node: int) -> dict[str, str]:
    """An environment whose `pnpm` and `node` are stand-ins exiting with the given statuses."""
    _needs("bash")
    (tmp_path / "bin").mkdir()
    for fake in ("pnpm", "node"):
        (tmp_path / "bin" / fake).write_text(f"#!{sys.executable}\n{FAKE}", encoding="utf-8")
        (tmp_path / "bin" / fake).chmod(0o755)
    path = f"{tmp_path / 'bin'}{os.pathsep}{os.environ.get('PATH', '')}"
    env = {"PATH": path, "GITHUB_WORKSPACE": str(tmp_path), "CALLS": str(tmp_path / "calls")}
    env |= {"PNPM_EXIT": str(pnpm), "NODE_EXIT": str(node), "GITHUB_STEP_SUMMARY": "/dev/null"}
    return env


@pytest.mark.parametrize(("pnpm", "node"), [(0, 0), (1, 0), (0, 1), (1, 1)])
def test_run_step_fails_with_its_code_on_a_red_run_or_a_red_summary(
    tmp_path: Path, pnpm: int, node: int
) -> None:
    """A red summary (no story passed, or no report) fails the step as a red Vitest run does."""
    env = _fake_tools(tmp_path, pnpm, node)
    script = ["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", _run("run")]  # shell: bash
    proc = subprocess.run(script, env=env, capture_output=True, text=True, timeout=60, check=False)
    red = pnpm != 0 or node != 0
    assert (proc.returncode != 0, "CI-A11Y-002" in proc.stdout) == (red, red), proc
    (run, fixtures), (summary, _) = map(json.loads, (tmp_path / "calls").read_text().splitlines())
    report = f"{tmp_path}/reports/storybook-a11y/results.json"
    assert (run[-1], fixtures) == (f"--outputFile.json={report}", None)  # the stories alone
    assert summary[1:] == ["summary", report]


@pytest.mark.parametrize(("pnpm", "node"), [(1, 0), (1, 1), (0, 1)])
def test_self_test_fails_the_job_unless_the_fixture_failed_the_gate(
    tmp_path: Path, pnpm: int, node: int
) -> None:
    env = _fake_tools(tmp_path, pnpm, node)
    script = ["bash", "-e", "-c", _run("self-test")]
    proc = subprocess.run(script, env=env, capture_output=True, text=True, timeout=60, check=False)
    assert (proc.returncode != 0, "CI-A11Y-003" in proc.stdout) == (node != 0, node != 0), proc
    (run, fixtures), (judge, _) = map(json.loads, (tmp_path / "calls").read_text().splitlines())
    report = f"{tmp_path}/reports/storybook-a11y/fixtures.json"
    assert (run[-1], fixtures) == (f"--outputFile.json={report}", "1")  # the fixture alone
    assert judge[1:] == ["selftest", report, str(pnpm)]  # judged with the run's exit status


def _report(tmp_path: Path, command: str, *tests: Any, status: str = "1") -> tuple[int, str]:
    """Run the report script on a Vitest JSON report of `tests`: (story id, status, impacts, failure)."""
    _needs("node")
    results = [
        {"status": state, "failureMessages": [failure], "meta": {"storyId": story, "reports": [
            {"type": "a11y", "result": {"violations": [{"impact": i} for i in impacts]}},
            {"type": "a11y", "result": {}},  # a failed check's error-only report
        ]}} for story, state, impacts, failure in tests
    ]  # fmt: skip
    (tmp_path / "r.json").write_text(json.dumps({"testResults": [{"assertionResults": results}]}))
    args = ["node", str(SCRIPT), command, str(tmp_path / "r.json"), status]
    proc = subprocess.run(args, capture_output=True, text=True, timeout=60, check=False)
    return proc.returncode, proc.stdout + proc.stderr


#: A failed axe check's text: the element, then each rule as `"<help> (<rule id>)"`, in colour.
NAMED = "$('#a11y-gate-fixture')\nReceived:\n\x1b[31m\"Elements ... (color-contrast)\"\x1b[39m"


def test_summary_counts_the_stories_and_axe_violations_by_impact(tmp_path: Path) -> None:
    tests = [("a--1", "passed", ["serious", "minor"], ""), ("a--2", "failed", [], NAMED * 2)]
    rc, out = _report(tmp_path, "summary", *tests, ("perf", "skipped", [], ""))
    stories, impacts, blocking = out.splitlines()
    assert (rc, stories) == (0, "- Storybook stories: 3 (1 passed, 1 failed, 1 skipped)")
    assert impacts.endswith(" in passed stories: critical 0, serious 1, moderate 0, minor 1")
    assert blocking == "- blocking axe violations in failed stories: 1 (color-contrast)"


def test_summary_fails_closed_when_no_story_passed(tmp_path: Path) -> None:
    """Vitest exits 0 when every story is skipped; the summary does not."""
    rc, out = _report(tmp_path, "summary", ("perf", "skipped", [], ""), ("b--1", "skipped", [], ""))
    assert rc == 1
    assert out.splitlines()[0] == "- Storybook stories: 2 (0 passed, 0 failed, 2 skipped)"
    assert out.splitlines()[-1] == "- no story passed: the gate checked nothing"


@pytest.mark.parametrize(
    ("state", "failure", "status", "closed"),
    [("failed", NAMED, "1", True), ("passed", "", "0", False), ("failed", NAMED, "0", False)]
    + [("failed", NAMED.replace(name, "?"), "1", False) for name in ("color-", "#a11y-")],
)
def test_selftest_passes_only_if_the_fixture_failed_the_gate_naming_rule_and_element(
    tmp_path: Path, state: str, failure: str, status: str, closed: bool
) -> None:
    button = ("foundations-a11y-gate-fixture--low-contrast-button", state, [], failure)
    rc, out = _report(tmp_path, "selftest", button, status=status)
    assert (rc == 0, "a11y gate self-test:" in out) == (closed, not closed), out
