"""E49-Q01 (#1335, BQ-4, BQ-5): the GA pack's nightly report upload and health check.

`_job-e2e.yml` reduces each nightly shard's Playwright JSON report to titles, statuses and
durations and keeps it 14 days; e2e-nightly's read-only `ga-pack-health` job reads this run's and
the last ten scheduled nights' reports and runs `tools/qa/ga_pack_health.py`: CI-E2E-006 (the
2,700 s wall-clock from the first shard's start to the last shard's end), CI-E2E-007 (an unowned
or overdue `@flaky` Playwright test, C-9.3), the flake report and the Monday shard map. Every
input here is built in the test; nothing reaches the network.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Any

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.ci.flaky_quarantine_report import build_report, playwright_problems
from tools.qa.ga_pack_health import (
    load_jobs,
    load_reports,
    main,
    pack_shards,
    parse_report,
    spec_durations,
    wall_clock,
)

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
MONDAY, TUESDAY = "2026-11-02", "2026-11-03"
UPLOAD = {
    "e2e-web": "e2e-web-report-shard-${{ matrix.shard }}",
    "e2e-electron": "e2e-electron-report",
}
REPORT = {"e2e-web": "apps/web", "e2e-electron": "apps/desktop"}
NIGHTLY_IF = "${{ always() && inputs.quarantine }}"


def _workflow(name: str) -> dict[Any, Any]:
    doc: dict[Any, Any] = yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))
    return doc


def _result(status: str, duration: int, retry: int = 0) -> dict[str, Any]:
    return {"status": status, "duration": duration, "retry": retry}


def _report(*specs: tuple[str, str, str, list[dict[str, Any]]]) -> dict[str, Any]:
    """A Playwright JSON report: (file, title, test status, results) per spec, one suite each."""
    suites = []
    for file, title, status, results in specs:
        test = {"projectName": "chromium", "status": status, "results": results}
        spec = {"title": title, "file": file, "tests": [test]}
        suites.append(
            {
                "title": file,
                "file": file,
                "specs": [],
                "suites": [{"title": "group", "file": file, "specs": [spec], "suites": []}],
            }
        )
    return {"suites": suites}


def _write(path: Path, data: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _job(name: str, start: str | None, end: str | None) -> dict[str, Any]:
    return {"name": name, "started_at": start, "completed_at": end}


def _run(tmp_path: Path, jobs: list[dict[str, Any]], today: str, **reports: Any) -> tuple[int, str]:
    """main() over tmp inputs and an empty repository root: exit code and the summary."""
    jobs_file = tmp_path / "jobs.jsonl"
    jobs_file.write_text("".join(json.dumps(j) + "\n" for j in jobs), encoding="utf-8")
    for rel, data in reports.items():
        _write(tmp_path / rel.replace("__", "/") / "results.json", data)
    summary, repo = tmp_path / "summary.md", tmp_path / "repo"
    summary.unlink(missing_ok=True)
    repo.mkdir(exist_ok=True)
    argv = ["--jobs", str(jobs_file), "--current", str(tmp_path / "current")]
    argv += ["--history", str(tmp_path / "history"), "--repo-root", str(repo)]
    argv += ["--today", today, "--summary", str(summary)]
    rc = main(argv)
    return rc, summary.read_text(encoding="utf-8")


SHARDS = [
    _job("e2e-nightly / e2e-web (1)", "2026-11-03T02:55:00Z", "2026-11-03T03:05:00Z"),
    _job("e2e-nightly / e2e-web (2)", "2026-11-03T02:56:00Z", "2026-11-03T03:20:00Z"),
    _job("e2e-nightly / e2e-electron", "2026-11-03T02:57:00Z", "2026-11-03T03:10:00Z"),
    # Not shards: never part of the wall-clock.
    _job("e2e-nightly / a11y-axe", "2026-11-03T02:00:00Z", "2026-11-03T05:00:00Z"),
    _job("e2e-nightly-ga-pack-health", "2026-11-03T03:21:00Z", None),
]


def test_wall_clock_runs_from_the_first_shard_start_to_the_last_shard_end() -> None:
    assert wall_clock(SHARDS) == (25 * 60.0, 3)


def test_wall_clock_is_not_measured_without_shard_timestamps() -> None:
    assert wall_clock([_job("e2e-nightly / e2e-web (1)", None, None), SHARDS[3]]) == (None, 1)
    assert wall_clock([_job("e2e-nightly / e2e-web (1)", "not a time", "")]) == (None, 1)


@pytest.mark.parametrize("shape", ["lines", "page", "list"])
def test_load_jobs_reads_json_lines_an_api_page_or_a_list(shape: str) -> None:
    text = {
        "lines": "\n".join(json.dumps(j) for j in SHARDS) + "\n",
        "page": json.dumps({"total_count": len(SHARDS), "jobs": SHARDS}),
        "list": json.dumps(SHARDS),
    }[shape]
    assert [j["name"] for j in load_jobs(text)] == [j["name"] for j in SHARDS]


def test_check_passes_within_the_budget(tmp_path: Path) -> None:
    rc, summary = _run(tmp_path, SHARDS, TUESDAY)
    assert rc == 0
    assert "Wall-clock: 1500 s over 3 shard job(s), budget 2700 s: within budget." in summary
    assert "CI-E2E-00" not in summary and "Shard map" not in summary


def test_check_fails_ci_e2e_003_over_2700_seconds(tmp_path: Path) -> None:
    jobs = [
        *SHARDS,
        _job("e2e-nightly / e2e-web (4)", "2026-11-03T03:00:00Z", "2026-11-03T03:40:01Z"),
    ]
    rc, summary = _run(tmp_path, jobs, TUESDAY)
    assert rc == 1
    assert "2701 s over 4 shard job(s), budget 2700 s: CI-E2E-006: over budget." in summary


def test_check_reports_an_unmeasured_wall_clock_without_failing(tmp_path: Path) -> None:
    rc, summary = _run(tmp_path, [SHARDS[3]], TUESDAY)
    assert rc == 0 and "Wall-clock: not measured (0 shard job(s)" in summary


def test_check_exits_2_on_an_unreadable_jobs_input(tmp_path: Path) -> None:
    jobs = tmp_path / "jobs.json"
    jobs.write_text('"a string"', encoding="utf-8")
    argv = ["--jobs", str(jobs), "--current", str(tmp_path), "--history", str(tmp_path)]
    assert main([*argv, "--repo-root", str(tmp_path), "--today", TUESDAY, "--summary", ""]) == 2
    assert main(["--jobs", str(tmp_path / "missing"), *argv[2:], "--summary", ""]) == 2


def test_flake_report_counts_retry_passes_and_failures_across_nights(tmp_path: Path) -> None:
    flaky = [_result("failed", 900), _result("passed", 1000, 1)]
    night_1 = _report(
        ("a.spec.ts", "retries", "flaky", flaky),
        ("b.spec.ts", "steady", "expected", [_result("passed", 500)]),
        ("c.spec.ts", "parked", "skipped", [_result("skipped", 0)]),
    )
    night_2 = _report(
        ("a.spec.ts", "retries", "expected", [_result("passed", 1000)]),
        ("b.spec.ts", "steady", "unexpected", [_result("failed", 1), _result("timedOut", 1, 1)]),
    )
    rc, summary = _run(
        tmp_path,
        SHARDS,
        TUESDAY,
        current__e2e_web_report_shard_1=night_1,
        history__41__e2e_web_report_shard_1=night_2,
    )
    assert rc == 0  # the flake report never fails the job
    assert "### Flake report (2 report night(s))" in summary
    lines = [line for line in summary.splitlines() if line.startswith("| a.spec.ts")]
    assert lines == ["| a.spec.ts › group › retries [chromium] | 2 | 1 | 0 | 1 | 50% |"]
    assert "| b.spec.ts › group › steady [chromium] | 2 | 0 | 1 | 2 | 0% |" in summary
    assert "c.spec.ts" not in summary


def test_load_reports_names_the_night_by_run_folder_and_notes_an_unreadable_file(
    tmp_path: Path,
) -> None:
    _write(tmp_path / "41" / "e2e-electron-report" / "results.json", _report())
    bad = tmp_path / "42" / "e2e-web-report-shard-2" / "results.json"
    bad.parent.mkdir(parents=True)
    bad.write_text("{", encoding="utf-8")
    reports, notes = load_reports(tmp_path, None)
    assert [(r.night, r.lane) for r in reports] == [("41", "e2e-electron-report")]
    assert notes == ["unreadable report skipped: 42/e2e-web-report-shard-2/results.json"]
    assert load_reports(tmp_path / "missing", "this run") == ([], [])


@pytest.mark.parametrize(
    "body",
    [
        '{"suites": ["x"]}',
        '{"suites": [{"specs": [{"tests": [{"results": [{"duration": "abc"}]}]}]}]}',
        '{"suites": {"specs": []}}',
    ],
)
def test_load_reports_notes_a_wrong_shaped_report_instead_of_failing(
    tmp_path: Path, body: str
) -> None:
    bad = tmp_path / "43" / "e2e-web-report-shard-1" / "results.json"
    bad.parent.mkdir(parents=True)
    bad.write_text(body, encoding="utf-8")
    assert load_reports(tmp_path, None) == (
        [],
        ["unreadable report skipped: 43/e2e-web-report-shard-1/results.json"],
    )


def test_load_reports_skips_an_oversized_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(tmp_path / "44" / "e2e-web-report-shard-3" / "results.json", _report())
    monkeypatch.setattr("tools.qa.ga_pack_health.MAX_REPORT_BYTES", 1)
    assert load_reports(tmp_path, None) == (
        [],
        ["oversized report skipped: 44/e2e-web-report-shard-3/results.json"],
    )


def test_spec_durations_take_each_files_median_night_from_web_reports_only() -> None:
    def night(name: str, lane: str, ms: int) -> Any:
        data = _report(
            ("a.spec.ts", "t1", "expected", [_result("passed", ms)]),
            ("a.spec.ts", "t2", "expected", [_result("passed", 1000)]),
        )
        return parse_report(data, name, lane)

    reports = [
        night("1", "e2e-web-report-shard-1", 1000),
        night("2", "e2e-web-report-shard-3", 3000),
    ]
    reports += [
        night("3", "e2e-web-report-shard-2", 9000),
        night("1", "e2e-electron-report", 99000),
    ]
    assert spec_durations(reports) == {"a.spec.ts": 4.0}


def test_pack_shards_puts_the_longest_spec_first_on_the_lightest_shard() -> None:
    bins = pack_shards({"a": 10.0, "b": 8.0, "c": 6.0, "d": 5.0, "e": 4.0}, 2)
    assert bins == [(15.0, ["a", "d"]), (18.0, ["b", "c", "e"])]
    assert pack_shards({}, 3) == [(0.0, []), (0.0, []), (0.0, [])]


def test_the_shard_map_is_recomputed_on_mondays_only(tmp_path: Path) -> None:
    web = _report(
        ("a.spec.ts", "t", "expected", [_result("passed", 61000)]),
        ("b.spec.ts", "t", "expected", [_result("passed", 2000)]),
    )
    reports = {"current__e2e-web-report-shard-1": web}
    rc, summary = _run(tmp_path, SHARDS, MONDAY, **reports)
    assert rc == 0
    assert (
        "### Shard map (Monday recompute; predicted longest shard 61 s, test time only)" in summary
    )
    assert "| 1 | 61 | a.spec.ts |" in summary and "| 2 | 2 | b.spec.ts |" in summary
    assert "| 4 | 0 | - |" in summary
    rc, summary = _run(tmp_path, SHARDS, TUESDAY, **reports)
    assert rc == 0 and "Shard map" not in summary


def _spec(repo: Path, line: str, comment: str) -> None:
    path = repo / "apps" / "web" / "e2e" / "x.spec.ts"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'import {{ test }} from "@playwright/test";\n{comment}\n{line}\n', "utf-8")


@pytest.mark.parametrize(
    ("comment", "problem"),
    [
        ("// ticket: E49-1 quarantined: 2026-10-30 owner: @qa-lead", None),
        # Exactly ten working days (Mon-Fri) before 2026-11-04: at the limit, not over it.
        ("// ticket: E49-1 quarantined: 2026-10-21 owner: qa-lead", None),
        ("// ticket: E49-1 quarantined: 2026-10-30", "`@flaky` test has no `owner:` marker"),
        ("// owner: qa-lead", "`@flaky` test has no `ticket:`, `quarantined:` marker"),
        (
            "// ticket: E49-1 quarantined: 2026-13-40 owner: qa",
            "`@flaky` test has no `quarantined:` marker",
        ),
        (
            "// ticket: E49-1 quarantined: 2026-10-16 owner: qa-lead",
            "quarantined since 2026-10-16 (13 working days, over 10), ticket E49-1, owner @qa-lead",
        ),
    ],
)
def test_ci_e2e_004_names_an_unowned_or_overdue_flaky_playwright_test(
    tmp_path: Path, comment: str, problem: str | None
) -> None:
    _spec(tmp_path, 'test("drops the socket @flaky", async () => {});', comment)
    problems = playwright_problems(build_report(tmp_path), date(2026, 11, 4))
    assert problems == ([f"apps/web/e2e/x.spec.ts:3 {problem}"] if problem else [])


@pytest.mark.parametrize(
    ("line", "found"),
    [
        ("test.describe('reconnect @flaky @e17-regression', () => {", True),
        ("test(`renders @flaky`, async ({ page }) => {", True),
        ('test("no tag here", async () => { const t = "@flaky"; });', False),
        ('submit("@flaky");', False),
        ('test("drops the socket @flaky-nightly", async () => {});', False),
        ('test("drops the socket @flaky-x", async () => {});', False),
    ],
)
def test_the_playwright_tag_is_read_from_the_title_only(
    tmp_path: Path, line: str, found: bool
) -> None:
    _spec(tmp_path, line, "// ticket: E49-1 quarantined: 2026-11-04 owner: qa")
    assert len([e for e in build_report(tmp_path).entries if e.playwright]) == int(found)


def test_check_fails_ci_e2e_004_on_an_unowned_quarantine(tmp_path: Path) -> None:
    _spec(
        tmp_path / "repo", 'test("x @flaky", () => {});', "// ticket: E49-1 quarantined: 2026-11-02"
    )
    rc, summary = _run(tmp_path, SHARDS, TUESDAY)
    assert rc == 1
    assert "CI-E2E-007: 1 quarantined test(s) unowned or overdue:" in summary


# --- the workflows ------------------------------------------------------------------------------


def _lane_steps(job: str) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = _workflow("_job-e2e.yml")["jobs"][job]["steps"]
    return steps


def _reduce_step(job: str) -> dict[str, Any]:
    (step,) = [s for s in _lane_steps(job) if str(s.get("name", "")).startswith("Reduce ")]
    return step


@pytest.mark.parametrize("job", sorted(UPLOAD))
def test_the_nightly_uploads_each_reduced_shard_report_for_14_days(job: str) -> None:
    steps = _lane_steps(job)
    names = [str(s.get("name", "")) for s in steps]
    (upload,) = [s for s in steps if s.get("with", {}).get("name") == UPLOAD[job]]
    reduce = _reduce_step(job)
    assert reduce["if"] == upload["if"] == NIGHTLY_IF
    # Never turns the release-blocking nightly red: the only reader does not enforce yet.
    assert reduce["continue-on-error"] is upload["continue-on-error"] is True
    assert reduce["env"] == {"REPORT": f"{REPORT[job]}/playwright-report/results.json"}
    assert upload["with"] == {
        "name": UPLOAD[job],
        "path": "ga-pack-report/results.json",
        "if-no-files-found": "ignore",
        "retention-days": 14,
    }
    # The pin the lane's failure upload already uses, and that upload keeps its 7 days.
    (failure,) = [s for s in steps if s.get("if") == "failure()"]
    assert upload["uses"] == failure["uses"] and failure["with"]["retention-days"] == 7
    # Taken before the quarantine leg rewrites results.json.
    quarantine = next(i for i, n in enumerate(names) if n.startswith("Quarantined @flaky tests"))
    assert names.index(reduce["name"]) < names.index(upload["name"]) < quarantine
    assert _reduce_step("e2e-web")["run"] == _reduce_step("e2e-electron")["run"]


def _reduce(tmp_path: Path, report: object | None) -> tuple[int, str]:
    if not shutil.which("bash") or not shutil.which("python3"):
        (pytest.fail if os.environ.get("CI") else pytest.skip)("bash and python3 run the step")
    source = tmp_path / "playwright-report" / "results.json"
    if report is not None:
        _write(source, report)
    proc = subprocess.run(
        ["bash", "-e", "-c", _reduce_step("e2e-web")["run"]],
        cwd=tmp_path,
        env={"PATH": os.environ.get("PATH", ""), "HOME": str(tmp_path), "REPORT": str(source)},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    return proc.returncode, proc.stdout + proc.stderr


def test_the_reduce_step_keeps_titles_statuses_and_durations_only(tmp_path: Path) -> None:
    raw = _report(("a.spec.ts", "t", "flaky", [_result("failed", 5), _result("passed", 7, 1)]))
    test = raw["suites"][0]["suites"][0]["specs"][0]["tests"][0]
    test["annotations"] = [{"type": "covers", "description": "US-ONB-001"}]
    test["results"][0] |= {
        "errors": [{"message": "Authorization: Bearer canary"}],
        "stdout": [{"text": "canary"}],
        "attachments": [{"name": "trace", "path": "trace.zip", "body": "Y2FuYXJ5"}],
    }
    raw |= {"config": {"webServer": {"command": "canary"}}, "errors": [], "stats": {"flaky": 1}}
    rc, out = _reduce(tmp_path, raw)
    assert rc == 0, out
    text = (tmp_path / "ga-pack-report" / "results.json").read_text(encoding="utf-8")
    assert "canary" not in text and "US-ONB-001" not in text
    reduced = json.loads(text)
    (run,) = parse_report(reduced, "n", "e2e-web-report-shard-1").tests
    assert (run.test_id, run.status, run.failed_attempts, run.duration_ms) == (
        "a.spec.ts › group › t [chromium]",
        "flaky",
        1,
        12,
    )
    kept = reduced["suites"][0]["suites"][0]["specs"][0]["tests"][0]
    assert kept["results"] == [_result("failed", 5), _result("passed", 7, 1)]
    assert set(kept) == {"projectName", "status", "results"}


def test_the_reduce_step_writes_nothing_when_the_suite_left_no_report(tmp_path: Path) -> None:
    rc, out = _reduce(tmp_path, None)
    assert rc == 0 and "no JSON report at" in out
    assert not (tmp_path / "ga-pack-report").exists()


def test_ga_pack_health_is_read_only_not_enforcing_and_capped_by_the_ci_timeout() -> None:
    job = _workflow("e2e-nightly.yml")["jobs"]["ga-pack-health"]
    assert (job["needs"], job["if"], job["continue-on-error"]) == ("e2e", "${{ always() }}", True)
    assert job["permissions"] == {"contents": "read", "actions": "read"}
    assert job["timeout-minutes"] == "${{ fromJSON(vars.CV_CI_TIMEOUT_MINUTES || 20) }}"
    steps = job["steps"]
    assert steps[0]["with"] == {"persist-credentials": False}
    fetch, health = steps[2], steps[3]
    assert fetch["env"] == {
        "GH_TOKEN": "${{ github.token }}",
        "GH_REPO": "${{ github.repository }}",
    }
    assert "env" not in health  # the token reaches only the fetch step
    for step in (fetch, health):
        assert "${{" not in step["run"]
    assert "--limit 11" in fetch["run"] and '[ "$n" -lt 10 ] || break' in fetch["run"]
    assert "--event schedule" in fetch["run"] and "--pattern 'e2e-*-report*'" in fetch["run"]
    assert "python -m tools.qa.ga_pack_health --jobs" in health["run"]
    # No job of the nightly or its lane takes the pack's 45 minutes as a timeout (BQ-4).
    lane = _workflow("_job-e2e.yml")["jobs"]
    caps = {j.get("timeout-minutes") for j in [*lane.values(), job]}
    assert 45 not in caps and "45" not in caps
