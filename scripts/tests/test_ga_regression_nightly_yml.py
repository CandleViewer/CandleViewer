"""E49-Q01 (#1335): ga-regression-nightly.yml, the GA regression pack's nightly, and the two
Playwright configs' `ga-regression` projects. The nightly is not a required check (C-9.1 is left
alone), reads no secret, holds `contents: read` except where a job names more, scrubs artefacts
before it uploads them, and files a red night through _nightly-issue.yml
(test_nightly_issue.py pins that call)."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
NIGHTLY = WORKFLOWS / "ga-regression-nightly.yml"
TEXT = NIGHTLY.read_text(encoding="utf-8")
DOC: dict[Any, Any] = yaml.safe_load(TEXT)
JOBS: dict[str, dict[str, Any]] = DOC["jobs"]


def _steps(job: str) -> list[dict[str, Any]]:
    return list(JOBS[job].get("steps", []))


def _step(job: str, prefix: str) -> dict[str, Any]:
    (step,) = [s for s in _steps(job) if str(s.get("name", "")).startswith(prefix)]
    return step


def test_runs_nightly_and_on_demand_only() -> None:
    on = DOC[True]
    assert set(on) == {"schedule", "workflow_dispatch"}
    assert re.fullmatch(r"\d+ \d+ \* \* \*", on["schedule"][0]["cron"])


def test_least_privilege_and_no_secrets() -> None:
    assert DOC["permissions"] == {"contents": "read"} and "concurrency" not in DOC
    assert "secrets." not in TEXT
    held = {name: job.get("permissions") for name, job in JOBS.items() if "permissions" in job}
    assert held == {"history": {"actions": "read"}, "ga-regression-issue": {"issues": "write"}}
    # The job that reads the Actions API runs no repository code: no checkout.
    assert not any("actions/checkout" in str(s.get("uses", "")) for s in _steps("history"))


def test_is_not_a_required_check_and_touches_no_pr_lane() -> None:
    for path in (ROOT / "CONSTITUTION.md", WORKFLOWS / "pr.yml", WORKFLOWS / "_job-e2e.yml"):
        assert "ga-regression" not in path.read_text(encoding="utf-8"), path.name


def test_every_checkout_keeps_no_credential() -> None:
    for name in JOBS:
        for s in _steps(name):
            if str(s.get("uses", "")).startswith("actions/checkout@"):
                assert s["with"]["persist-credentials"] is False, name


def test_pack_legs_run_the_planned_files_with_the_pack_switch_on() -> None:
    web = _step("web", "Pack shard")
    assert web["env"]["CV_E2E_GA"] == "1"
    assert "tools/ga/shard_plan.py web-chromium" in web["run"]
    assert "--project=ga-regression" in web["run"] and '"${files[@]}"' in web["run"]
    assert JOBS["web"]["strategy"]["matrix"]["shard"] == [1, 2, 3, 4]
    electron = _step("electron", "Pack, Electron lane")
    assert electron["env"]["CV_E2E_GA"] == "1" and "xvfb-run" in electron["run"]
    assert "tools/ga/shard_plan.py electron 1 1" in electron["run"]
    # The packaged executable is built first, so the packaged project joins the lane.
    names = [s.get("name", "") for s in _steps("electron")]
    assert names.index("Package the shell (electron-builder --dir)") < names.index(electron["name"])


def test_pack_legs_run_with_zero_retries_and_the_global_retry_is_left_alone() -> None:
    """#1335 ruling (a): the pack never retries, so a flake fails its night; the global web
    `retries: 1` vs 03 section 14 is carried to the CI owner (#569 BQ-10), not changed here."""
    for job, prefix in (("web", "Pack shard"), ("electron", "Pack, Electron lane")):
        run = _step(job, prefix)["run"]
        assert re.findall(r"--retries=\d+", run) == ["--retries=0"], job
    web = (ROOT / "apps/web/e2e/playwright.config.ts").read_text(encoding="utf-8")
    assert '{ name: "ga-regression", grep: GA, grepInvert: FLAKY, retries: 0 }' in web
    assert 'retries: process.env["CI"] ? 1 : 0,' in web
    desktop = (ROOT / "apps/desktop/e2e/playwright.config.ts").read_text(encoding="utf-8")
    assert "\n  retries: 0,\n" in desktop and "retries: 1" not in desktop


@pytest.mark.parametrize(("job", "lane"), [("web", "web-chromium"), ("electron", "electron")])
def test_artefacts_are_scrubbed_before_any_upload_and_uploads_fail_closed(
    job: str, lane: str
) -> None:
    steps = _steps(job)
    scrubs = {s["id"]: i for i, s in enumerate(steps) if "scrub_artifacts.py" in str(s.get("run"))}
    assert set(scrubs) == {"scrub-results", "scrub"}
    assert all(steps[i]["if"] == "always()" for i in scrubs.values())
    # Bounded, so an overrun fails the step and skips the uploads deliberately (fail-closed).
    assert all(steps[i]["timeout-minutes"] == 10 for i in scrubs.values())
    assert f"ga-results-{lane}" in steps[scrubs["scrub-results"]]["run"]
    assert "test-results" in steps[scrubs["scrub"]]["run"]
    uploads = [i for i, s in enumerate(steps) if "upload-artifact" in str(s.get("uses", ""))]
    assert len(uploads) == 2 and min(uploads) > max(scrubs.values())
    for i in uploads:
        assert steps[i]["with"]["retention-days"] == 14
    # Each upload is gated on the success of the scrub of exactly what it uploads: a scrub that
    # failed (an unreadable trace, deleted) publishes nothing (#1335 security lens, finding 1).
    (results,) = [steps[i] for i in uploads if steps[i]["with"]["name"].startswith("ga-results-")]
    assert results["with"]["name"].startswith(f"ga-results-{lane}")
    assert results["if"] == "${{ always() && steps.scrub-results.outcome == 'success' }}"
    (failure,) = [steps[i] for i in uploads if steps[i]["with"]["name"].startswith("ga-failure-")]
    assert failure["with"]["name"].startswith(f"ga-failure-{lane}")
    assert failure["if"] == "${{ failure() && steps.scrub.outcome == 'success' }}"
    assert "test-results" in failure["with"]["path"]


def test_history_reads_main_nights_only() -> None:
    run = _step("history", "The run's start time")["run"]
    assert "--branch main" in run and "--status completed" in run


def test_health_job_runs_the_health_check_and_the_scrub_self_test() -> None:
    runs = [str(s.get("run", "")) for s in _steps("health")]
    assert "python3 tools/ga/health.py" in runs
    assert "python3 tools/ga/scrub_artifacts.py --self-test" in runs


def test_report_reads_every_leg_and_hands_a_red_night_to_the_issue_job() -> None:
    job = JOBS["report"]
    assert job["needs"] == ["health", "history", "web", "electron"]
    assert job["if"] == "${{ always() }}"
    run = _step("report", "Per-area report")["run"]
    assert "tools/ga/report.py results --history history" in run and "--fail-on-red" in run
    assert "--fail-on-amber" in run  # the C-9.3 flake gate: a flip across nights fails the night
    assert "--started-at" in run and "$GITHUB_STEP_SUMMARY" in run
    issue = JOBS["ga-regression-issue"]
    assert issue["uses"] == "./.github/workflows/_nightly-issue.yml"
    assert "${{ needs.report.outputs.report }}" in issue["with"]["body"]


def _bash(run: str, env: dict[str, str], cwd: Path) -> int:
    if not shutil.which("bash"):
        (pytest.fail if os.environ.get("CI") else pytest.skip)("bash runs the step")
    proc = subprocess.run(
        ["bash", "-e", "-c", run],
        cwd=cwd,
        env={"PATH": os.environ["PATH"]} | env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    return proc.returncode


@pytest.mark.parametrize(
    ("results", "rc"),
    [
        (("success", "success", "success"), 0),
        (("failure", "success", "success"), 1),
        (("success", "cancelled", "success"), 1),
        (("success", "success", "skipped"), 1),
    ],
)
def test_a_failed_or_cancelled_leg_makes_the_report_red(
    tmp_path: Path, results: tuple[str, str, str], rc: int
) -> None:
    step = _step("report", "A failed or cancelled leg")
    env = dict(zip(("HEALTH", "WEB", "ELECTRON"), results, strict=True))
    assert _bash(step["run"], env, tmp_path) == rc
    if rc:
        assert "ended" in (tmp_path / "ga-report" / "ga-report.md").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "config", ["apps/web/e2e/playwright.config.ts", "apps/desktop/e2e/playwright.config.ts"]
)
def test_configs_add_the_pack_project_only_behind_the_switch(config: str) -> None:
    text = (ROOT / config).read_text(encoding="utf-8")
    assert 'const PACK = process.env["CV_E2E_GA"] === "1";' in text
    assert "const GA = /@ga-regression/u;" in text
    assert re.search(
        r'PACK\s*\?\s*\[\s*\{ name: "ga-regression",[^}]*grep: GA, grepInvert: FLAKY', text
    )


def test_the_pr_projects_ignore_the_packs_own_specs() -> None:
    """The PR lane runs exactly what it ran before the pack (#1335 code lens): the pack's own
    specs (e2e/ga/, ga-*.spec.ts) run only in the pack project."""
    web = (ROOT / "apps/web/e2e/playwright.config.ts").read_text(encoding="utf-8")
    assert '{ name: "chromium", grepInvert: FLAKY, testIgnore: GA_ONLY }' in web
    desktop = (ROOT / "apps/desktop/e2e/playwright.config.ts").read_text(encoding="utf-8")
    assert '{ name: "dist", testIgnore: [PACKAGED, GA_ONLY], grepInvert: FLAKY }' in desktop
    patterns = {}
    for name, text in (("web", web), ("desktop", desktop)):
        (source,) = re.findall(r"const GA_ONLY = /(.+)/u;", text)
        patterns[name] = re.compile(source.replace("\\\\", "\\"))
    for spec in sorted((ROOT / "apps/web/e2e").rglob("*.spec.ts")):
        in_ga = spec.parent.name == "ga"
        assert bool(patterns["web"].search(spec.as_posix())) is in_ga, spec
    for spec in sorted((ROOT / "apps/desktop/e2e").rglob("*.spec.ts")):
        own = spec.name.startswith("ga-")
        assert bool(patterns["desktop"].search(spec.as_posix())) is own, spec


def test_retagged_specs_keep_their_pr_lane_fixture() -> None:
    """Outside the pack run, `packTest` is plain @playwright/test and `test` the shell fixture, so
    joining the pack changes no PR-lane fixture or egress behaviour."""
    fixtures = (ROOT / "apps/web/e2e/ga/fixtures.ts").read_text(encoding="utf-8")
    assert "export const test: typeof guarded = PACK_RUN ? withAxe : guarded;" in fixtures
    assert "export const packTest: typeof base = PACK_RUN ? withAxe : base;" in fixtures
    for rel in (
        "auth/login.spec.ts",
        "hotkeys.spec.ts",
        "invites.spec.ts",
        "motion-reduce.spec.ts",
    ):
        text = (ROOT / "apps/web/e2e" / rel).read_text(encoding="utf-8")
        assert "packTest as test }" in text, rel
