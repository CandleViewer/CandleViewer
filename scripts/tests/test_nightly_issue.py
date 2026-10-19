"""#1849: fixture-drift.yml, perf-storage-nightly.yml and perf-ingestion-nightly.yml ran
`gh issue create` with a dated title, so a lasting drift or regression opened an issue every red
night (15 duplicates closed on 2026-10-19). The measuring jobs now hold `contents: read` and hand
their verdict and report to one caller job per signal, which calls `_nightly-issue.yml`: its
`report` job alone can write, runs no checkout and no action, reads values from env, and comments
on the newest open issue that github-actions[bot] opened with the signal's title prefix and labels,
or opens one. Other authors' issues never match: no account can take the bot's login.
#3449: a workflow-level group shared by scheduled and manual runs let a pending run replace the
scheduled one, so the per-signal group sits on the seconds-long report job instead."""

from __future__ import annotations

import functools
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
WORKFLOWS = ROOT / ".github" / "workflows"
REUSABLE = "_nightly-issue.yml"
USES = f"./.github/workflows/{REUSABLE}"
NIGHTLIES = ("fixture-drift.yml", "perf-storage-nightly.yml", "perf-ingestion-nightly.yml")
BOT = "github-actions[bot]"
RUN_URL = "${{ github.server_url }}/${{ github.repository }}/actions/runs/${{ github.run_id }}"
#: (workflow, caller job) -> (measuring job, `if:`, signal, title prefix, labels). The prefixes are
#: those of the open issues filed before #1849, byte for byte, so the next red night finds them.
SIGNALS = {
    ("fixture-drift.yml", "drift-issue"): (
        "drift",
        "${{ always() && needs.drift.result == 'failure' }}",
        "fixture-drift",
        "fixture-drift: Bybit payload drift",
        "area/ingestion,priority/p1",
    ),
    ("perf-storage-nightly.yml", "storage-perf-issue"): (
        "storage-perf",
        "${{ always() && needs.storage-perf.outputs.regressed == 'true' }}",
        "perf-storage",
        "perf: storage nightly regression >20%",
        "perf,area/backend-platform",
    ),
    ("perf-ingestion-nightly.yml", "ingestion-soak-issue"): (
        "ingestion-soak",
        "${{ always() && needs.ingestion-soak.outputs.soak-regressed == 'true' }}",
        "perf-ingestion-soak",
        "perf: ingestion nightly soak/burst regression",
        "perf,area/ingestion",
    ),
    ("perf-ingestion-nightly.yml", "perf-pack-issue"): (
        "ingestion-soak",
        "${{ always() && needs.ingestion-soak.outputs.pack-regressed == 'true' }}",
        "perf-e08-q04-pack",
        "perf: E08-Q04 ingestion perf pack regression",
        "perf,area/ingestion,type/bug",
    ),
    ("perf-ingestion-nightly.yml", "perf-pack-full-issue"): (
        "perf-pack-full",
        "${{ always() && needs.perf-pack-full.outputs.failed == 'true' }}",
        "perf-e08-q04-full",
        "perf: E08-Q04 full perf pack failed",
        "perf,area/ingestion,type/bug",
    ),
}
#: The verdicts the measuring jobs hand over: the conditions of the issue steps they replace, less
#: `failure()`, which a failed step implies.
SYNCED = "${{ steps.sync.outcome == 'success' && "
VERDICTS = {
    ("perf-storage-nightly.yml", "storage-perf", "regressed"): SYNCED
    + "(steps.proxy.outcome == 'failure' || steps.real.outcome == 'failure') }}",
    ("perf-ingestion-nightly.yml", "ingestion-soak", "soak-regressed"): SYNCED
    + "(steps.soak.outcome == 'failure' || steps.burst.outcome == 'failure') }}",
    ("perf-ingestion-nightly.yml", "ingestion-soak", "pack-regressed"): SYNCED
    + "(steps.pack.outcome == 'failure' || steps.pack_tests.outcome == 'failure') }}",
    ("perf-ingestion-nightly.yml", "perf-pack-full", "failed"): (
        "${{ steps.pack.outcome == 'failure' }}"
    ),
}
GATE_DIFF = "services/api/bench/reports/gate-diff.md"
#: (workflow, measuring job) -> the report its `handoff` step passes on, and the caller it is for.
HANDOFFS = {
    ("fixture-drift.yml", "drift"): ("${{ runner.temp }}/drift.txt", "drift-issue"),
    ("perf-ingestion-nightly.yml", "ingestion-soak"): (GATE_DIFF, "perf-pack-issue"),
    ("perf-ingestion-nightly.yml", "perf-pack-full"): (GATE_DIFF, "perf-pack-full-issue"),
}
#: A stand-in `gh`: logs [argv, the --body-file's text] per call; `api` prints GH_PAGES' text and
#: exits GH_EXIT, so a failed listing can still print a page that parses.
FAKE_GH = """import json, os, sys
args = sys.argv[1:]
body = None
if "--body-file" in args:
    with open(args[args.index("--body-file") + 1], encoding="utf-8") as text:
        body = text.read()
with open(os.environ["GH_LOG"], "a", encoding="utf-8") as log:
    log.write(json.dumps([args, body]) + "\\n")
if args[0] == "api":
    with open(os.environ["GH_PAGES"], encoding="utf-8") as pages:
        sys.stdout.write(pages.read())
    sys.exit(int(os.environ["GH_EXIT"]))
"""
PREFIX, LABELS = "perf: storage nightly regression >20%", "perf,area/backend-platform"
LISTING = ["api", "-X", "GET", "repos/owner/repo/issues", "-f", "state=open"]
LISTING += ["-f", f"labels={LABELS}", "-f", "per_page=100", "--paginate", "--slurp"]
TRUNCATED = "\n\n(Truncated at 60000 bytes: the run has the rest.)\n"


@functools.cache
def _load(name: str) -> dict[Any, Any]:
    """A workflow's YAML; its keys are strings except `on`, which YAML 1.1 reads as True."""
    doc: dict[Any, Any] = yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))
    return doc


def test_nightly_issue_is_only_called_with_four_required_string_inputs() -> None:
    doc = _load(REUSABLE)
    assert list(doc[True]) == ["workflow_call"] and list(doc[True]["workflow_call"]) == ["inputs"]
    inputs = doc[True]["workflow_call"]["inputs"]
    assert list(inputs) == ["signal", "title-prefix", "labels", "body"]
    assert [(i["type"], i["required"]) for i in inputs.values()] == [("string", True)] * 4
    assert doc["permissions"] == {}


def test_report_job_alone_writes_runs_only_runner_tools_and_queues_per_signal() -> None:
    (name, job), *others = _load(REUSABLE)["jobs"].items()
    assert (name, others, job["name"], job["runs-on"]) == ("report", [], "report", "ubuntu-latest")
    assert (job["timeout-minutes"], job["permissions"]) == (5, {"issues": "write"})
    # Not cancel-in-progress: a second report of one signal waits, then finds the first's issue.
    group = "nightly-issue-${{ inputs.signal }}"
    assert job["concurrency"] == {"group": group, "cancel-in-progress": False}
    (step,) = job["steps"]  # no checkout and no action share the job with the write token
    assert set(step) == {"name", "env", "run"} and "${{" not in step["run"]
    assert step["env"] == {
        "GH_TOKEN": "${{ github.token }}",
        "GH_REPO": "${{ github.repository }}",
        "SIGNAL": "${{ inputs.signal }}",
        "TITLE_PREFIX": "${{ inputs.title-prefix }}",
        "LABELS": "${{ inputs.labels }}",
        "BODY": "${{ inputs.body }}",
    }


def test_nightlies_file_nothing_themselves_and_only_their_callers_can_write() -> None:
    writers, signals = set(), {}
    for name in NIGHTLIES:
        assert "gh issue" not in (WORKFLOWS / name).read_text(encoding="utf-8")
        doc = _load(name)
        # #3449: no workflow-level group; the per-signal one is on the report job.
        assert doc["permissions"] == {"contents": "read"} and "concurrency" not in doc
        for job_id, job in doc["jobs"].items():
            held = job.get("permissions")
            if held != {"contents": "read"} and held is not None:
                writers.add((name, job_id))
    assert writers == set(SIGNALS)
    for path in sorted(WORKFLOWS.glob("*.y*ml")):  # no other caller, and one caller per signal
        for job_id, job in (_load(path.name).get("jobs") or {}).items():
            if job.get("uses") == USES:
                signals[(path.name, job_id)] = job["with"]["signal"]
    assert set(signals) == set(SIGNALS) and len(set(signals.values())) == len(SIGNALS)


@pytest.mark.parametrize(("workflow", "caller"), sorted(SIGNALS))
def test_each_signal_reports_through_the_reusable_workflow(workflow: str, caller: str) -> None:
    needs, condition, signal, prefix, labels = SIGNALS[(workflow, caller)]
    job = _load(workflow)["jobs"][caller]
    # A job that calls a workflow takes no runs-on, timeout-minutes or steps of its own. always():
    # it runs after its measuring job failed; the verdict decides.
    assert set(job) == {"needs", "if", "permissions", "uses", "with"}
    assert (job["needs"], job["if"], job["uses"]) == (needs, condition, USES)
    assert job["permissions"] == {"issues": "write"}  # caps the report job's token
    assert set(job["with"]) == {"signal", "title-prefix", "labels", "body"}
    assert (job["with"]["signal"], job["with"]["title-prefix"]) == (signal, prefix)
    assert job["with"]["labels"] == labels and RUN_URL in job["with"]["body"]
    report = f"${{{{ needs.{needs}.outputs.report }}}}"
    carries = (workflow, needs) in HANDOFFS and HANDOFFS[(workflow, needs)][1] == caller
    assert (report in job["with"]["body"]) is carries


@pytest.mark.parametrize(("workflow", "job", "output"), sorted(VERDICTS))
def test_measuring_jobs_hand_over_the_conditions_of_the_steps_they_replace(
    workflow: str, job: str, output: str
) -> None:
    assert _load(workflow)["jobs"][job]["outputs"][output] == VERDICTS[(workflow, job, output)]


def _bash(tmp_path: Path, run: str, env: dict[str, str]) -> tuple[int, str]:
    """Run a step's script as the runner does (`bash -e`) in tmp_path, with a stand-in `gh` first
    on PATH and HOME in tmp_path (no stored gh auth, no network): exit code and output."""
    if not shutil.which("bash"):  # CI must run these fail-closed proofs
        (pytest.fail if os.environ.get("CI") else pytest.skip)("bash runs the step")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    (bin_dir / "gh").write_text(f"#!{sys.executable}\n{FAKE_GH}", encoding="utf-8")
    (bin_dir / "gh").chmod(0o755)
    base = {"PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}", "HOME": str(tmp_path)}
    proc = subprocess.run(
        ["bash", "-e", "-c", run],
        cwd=tmp_path,
        env=base | env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    return proc.returncode, proc.stdout + proc.stderr


@pytest.mark.parametrize(("workflow", "job"), sorted(HANDOFFS))
def test_handoff_passes_the_capped_report_under_a_random_delimiter(
    tmp_path: Path, workflow: str, job: str
) -> None:
    spec = _load(workflow)["jobs"][job]
    assert spec["outputs"]["report"] == "${{ steps.handoff.outputs.report }}"
    (step,) = [step for step in spec["steps"] if step.get("id") == "handoff"]
    assert (step["if"], step["env"]) == ("failure()", {"REPORT": HANDOFFS[(workflow, job)][0]})
    report, output = tmp_path / "report.md", tmp_path / "output"
    # A line that a fixed delimiter would match cannot end the value or add an output.
    report.write_text("EOF\nstream=x\n" + "y" * 70000, encoding="utf-8")
    env = {"REPORT": str(report), "GITHUB_OUTPUT": str(output)}
    for _ in range(2):  # the second run reads a missing report
        rc, out = _bash(tmp_path, step["run"], env)
        assert rc == 0, out
        report.unlink(missing_ok=True)
    text = output.read_text(encoding="utf-8")
    first, second = re.findall(r"report<<([0-9a-f]{32})\n(.*?)\n\1\n", text, re.S)
    assert first[1] == "EOF\nstream=x\n" + "y" * 59987 and first[0] != second[0]
    assert second[1] == "(no report produced)\n"


def _issue(number: int, title: str, login: str = BOT, pr: bool = False) -> dict[str, Any]:
    issue = {"number": number, "title": title, "user": {"login": login}}
    return issue | ({"pull_request": {"url": "u"}} if pr else {})


def _report(
    tmp_path: Path, pages: list[list[dict[str, Any]]], **values: str
) -> tuple[int, str, list[list[Any]]]:
    """Run the report step's script on these listing pages: exit code, output and gh calls."""
    (step,) = _load(REUSABLE)["jobs"]["report"]["steps"]
    temp, log, listing = tmp_path / "runner-temp", tmp_path / "gh.log", tmp_path / "pages.json"
    temp.mkdir()
    listing.write_text(json.dumps(pages), encoding="utf-8")
    env = {"GH_LOG": str(log), "GH_PAGES": str(listing), "GH_EXIT": values.pop("exit", "0")}
    env |= {"RUNNER_TEMP": str(temp), "GH_REPO": "owner/repo", "SIGNAL": "perf-storage"}
    env |= {"TITLE_PREFIX": PREFIX, "LABELS": LABELS, "BODY": "Run: r."} | values
    rc, out = _bash(tmp_path, step["run"], env)
    lines = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
    return rc, out, [json.loads(line) for line in lines]


def test_report_opens_a_dated_issue_with_the_labels_when_none_is_open(tmp_path: Path) -> None:
    rc, out, calls = _report(tmp_path, [[]])
    assert rc == 0, out
    (listing, _), (create, body) = calls
    assert listing == LISTING and create[:3] == ["issue", "create", "--title"]
    assert re.fullmatch(re.escape(PREFIX) + r" \(\d{4}-\d{2}-\d{2}\)", create[3])
    assert create[4:-2] == ["--label", "perf", "--label", "area/backend-platform"]
    assert (create[-2], body) == ("--body-file", "Run: r.\n")


def test_report_comments_on_the_newest_open_bot_issue_of_the_signal(tmp_path: Path) -> None:
    pages = [[_issue(n, f"{PREFIX} (2026-10-{d})") for n, d in ((2219, 11), (3429, 18), (1, 9))]]
    rc, out, calls = _report(tmp_path, pages)
    assert rc == 0, out
    (_, (comment, body)) = calls
    assert comment[:3] == ["issue", "comment", "3429"] and comment[3] == "--body-file"
    assert body == "Run: r.\n" and "commented on issue #3429" in out


@pytest.mark.parametrize("on_page_two", [False, True])
def test_report_ignores_other_authors_pull_requests_and_other_titles(
    tmp_path: Path, on_page_two: bool
) -> None:
    title = f"{PREFIX} (2026-10-19)"
    # All newer than the bot's issue, none a match: another account, another app's bot (only
    # github-actions[bot] counts), a pull request, the prefix after a word, another signal.
    others = [_issue(9005, title, login="someone"), _issue(9004, title, login="dependabot[bot]")]
    others += [_issue(9003, title, pr=True), _issue(9002, f"Re: {title}")]
    others.append(_issue(9001, "perf: ingestion nightly soak/burst regression (2026-10-19)"))
    pages = [others, [_issue(2219, title)]] if on_page_two else [[*others, _issue(2219, title)]]
    rc, out, calls = _report(tmp_path, pages)
    assert (rc, calls[-1][0][:3]) == (0, ["issue", "comment", "2219"]), out
    (tmp_path / "none").mkdir()  # and with no bot issue of the signal, it opens one
    rc, out, calls = _report(tmp_path / "none", [others])
    assert (rc, calls[-1][0][:2]) == (0, ["issue", "create"]), out


def test_report_files_nothing_when_the_listing_fails(tmp_path: Path) -> None:
    # pipefail: the failed listing's page parses as "none open", yet nothing is opened.
    rc, out, calls = _report(tmp_path, [[]], exit="1")
    assert rc != 0 and [args for args, _ in calls] == [LISTING], out


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("SIGNAL", "Perf Storage"),
        ("SIGNAL", "perf\n::warning::cv-mark"),
        ("TITLE_PREFIX", ""),
        ("TITLE_PREFIX", "perf: x\n::warning::cv-mark"),
        ("LABELS", ""),
        ("LABELS", "perf, area/backend-platform"),
        ("LABELS", "perf,"),
        ("LABELS", "perf\n::warning::cv-mark"),
    ],
)
def test_report_fails_closed_on_a_bad_input(tmp_path: Path, name: str, value: str) -> None:
    rc, out, calls = _report(tmp_path, [[]], **{name: value})
    assert (rc, calls) == (1, []) and "::error title=nightly-issue::" in out
    # Never echoed, so an input cannot add a workflow command (the cv-mark cases) to the log.
    assert "cv-mark" not in out and (not value or value not in out)


@pytest.mark.parametrize(("size", "cut"), [(59999, False), (60000, True), (70000, True)])
def test_report_caps_an_overlong_body(tmp_path: Path, size: int, cut: bool) -> None:
    # With the step's newline, 60000 bytes pass whole and one more is cut: under GitHub's 65536.
    rc, out, calls = _report(tmp_path, [[]], BODY="z" * size)
    assert rc == 0, out
    assert calls[-1][1] == ("z" * 60000 + TRUNCATED if cut else "z" * size + "\n")
