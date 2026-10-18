"""#3104: the security lane folds jobs that hold the same permissions. Each scan is a step judged as
its old job was (`continue-on-error`, its old time budget), a verdict step fails the job unless every
scan succeeded or was skipped, and `ci-required` still judges one `security` lane (#2988)."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
JOBS: dict[str, Any] = yaml.safe_load(
    (WORKFLOWS / "_job-security.yml").read_text(encoding="utf-8")
)["jobs"]
READ = {"contents": "read"}
SARIF = {"contents": "read", "security-events": "write"}
# Job -> (permissions, timeout-minutes).
LANE = {
    "codeql": (SARIF, 25),
    "semgrep-bandit": (SARIF, 30),
    "gitleaks": (READ, 10),
    "read-only-scans": (READ, 45),
    "trivy": (SARIF, 15),
}
# Folded job -> scan step id -> the old job whose budget it spends. license-scan's old job is
# three steps: backend install + package scope, the freeze assertion, the licence gate.
SCANS = {
    "semgrep-bandit": {"semgrep": "semgrep", "bandit": "bandit"},
    "read-only-scans": {
        **{scan: scan for scan in ("security-auth", "pip-audit", "npm-audit", "license-scan")},
        **dict.fromkeys(["license-scope", "freeze"], "license-scan"),
    },
}
# Old job -> its timeout-minutes before #3104.
OLD_BUDGETS = {"semgrep": 15, "bandit": 10, "security-auth": 10, "pip-audit": 10}
OLD_BUDGETS |= {"npm-audit": 10, "license-scan": 10}
INSTALLERS = ("pnpm install", "uv sync", "corepack", "actions/setup-node@")
# A node package-manager word anywhere in a line: quoted, path-qualified, in `sh -c`, backticks or
# `$(...)`, or before `)` or `;`; not part of a longer name such as `pnpm-lock.yaml` or `npm-audit`.
NODE_TOOL = re.compile(r"(?<![\w.-])(?:pnpm|pnpx|npm|npx|yarn|yarnpkg|corepack)(?![\w.-])")
PNPM = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))["packageManager"]
# Job -> the node command lines it may run; every other job runs none. Any other line (an install
# under another spelling or with options before the verb, `pnpm rebuild`, a bare `yarn`, `npx`, a
# wrapper) fails the pin (C-12.3).
NODE_COMMANDS = {
    "read-only-scans": {
        f"corepack enable && corepack prepare {PNPM.split('+')[0]} --activate",
        "pnpm install --frozen-lockfile --ignore-scripts",
        "pnpm audit --json > npm-audit.json || true",
        "pnpm licenses list --json --prod > pnpm-licenses.json",
    },
}
# Job -> the actions it uses (SHA pins aside), so no install action joins a job unnoticed.
BASE_ACTIONS = {"actions/checkout", "actions/setup-python"}
CODEQL_ACTION = "github/codeql-action/"
ACTIONS = {
    "codeql": BASE_ACTIONS | {CODEQL_ACTION + a for a in ("init", "analyze", "upload-sarif")},
    "semgrep-bandit": BASE_ACTIONS | {CODEQL_ACTION + "upload-sarif"},
    "gitleaks": BASE_ACTIONS,
    "read-only-scans": BASE_ACTIONS | {"actions/setup-node", "actions/upload-artifact"},
    "trivy": BASE_ACTIONS | {"aquasecurity/trivy-action", CODEQL_ACTION + "upload-sarif"},
}
SCANNERS = ('"semgrep==', '"pip-audit==', '"bandit[sarif]==')
FILTERS = " || ".join(f"needs.changed-paths.outputs.{f} == 'true'" for f in ("js", "py", "infra"))
# The pr.yml caller as it stood before the fold; #3104 leaves it and the resolver lane alone.
CALLER = {
    "name": "security",
    "needs": "changed-paths",
    "if": "${{ " + FILTERS + " || needs.changed-paths.outputs.semgrep == 'true' }}",
    "with": {"image_changed": "${{ needs.changed-paths.outputs.image == 'true' }}"},
    "permissions": SARIF,
    "uses": "./.github/workflows/_job-security.yml",
}


def _steps(job: str) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = JOBS[job]["steps"]
    return steps


def _ids(job: str) -> list[str | None]:
    return [step.get("id") for step in _steps(job)]


def test_the_unchanged_caller_runs_five_jobs_with_exact_permissions() -> None:
    pr = yaml.safe_load((WORKFLOWS / "pr.yml").read_text(encoding="utf-8"))
    assert pr["jobs"]["security"] == CALLER
    shape = {job: (spec["permissions"], spec["timeout-minutes"]) for job, spec in JOBS.items()}
    assert shape == LANE


@pytest.mark.parametrize("job", sorted(SCANS))
def test_scan_steps_keep_their_old_budgets_and_the_job_adds_five_minutes(job: str) -> None:
    assert sorted(i for i in _ids(job) if i) == sorted(SCANS[job])
    spent: dict[str, int] = {}
    for step in _steps(job):
        if "id" in step:
            assert (step["if"], step["continue-on-error"]) == ("${{ !cancelled() }}", True)
            old = SCANS[job][step["id"]]
            spent[old] = spent.get(old, 0) + step["timeout-minutes"]
    assert spent == {old: OLD_BUDGETS[old] for old in SCANS[job].values()}
    assert JOBS[job]["timeout-minutes"] == sum(spent.values()) + 5


def test_tree_readers_run_before_the_first_install_and_semgrep_before_bandit() -> None:
    ids = _ids("read-only-scans")
    texts = [json.dumps(step) for step in _steps("read-only-scans")]
    first = min(i for i, text in enumerate(texts) if any(word in text for word in INSTALLERS))
    assert max(ids.index("security-auth"), ids.index("pip-audit")) < first
    after = ["npm-audit", "license-scope", "freeze", "license-scan"]
    assert first < ids.index(after[0]) and after == sorted(after, key=ids.index)
    # Semgrep scans the whole tree, so it runs before bandit writes its report into it.
    assert _ids("semgrep-bandit").index("semgrep") < _ids("semgrep-bandit").index("bandit")


@pytest.mark.parametrize("job", sorted(SCANS))
def test_each_scanner_installs_into_its_own_venv_under_runner_temp(job: str) -> None:
    venvs = []
    for step in _steps(job):
        run = step.get("run", "")
        if any(tool in run for tool in SCANNERS):
            (venv,) = re.findall(r'python -m venv "(\$RUNNER_TEMP/[\w-]+)"', run)
            assert run.index(f'export PATH="{venv}/bin:$PATH"') < run.index("pip install")
            venvs.append(venv)
    assert len(venvs) == len(set(venvs)) == 2
    assert "/tmp/" not in json.dumps(JOBS[job])


@pytest.mark.parametrize("job", sorted(SCANS))
def test_verdict_runs_last_and_no_folded_step_uses_failure(job: str) -> None:
    verdict = _steps(job)[-1]
    assert (verdict["if"], verdict["shell"]) == ("${{ !cancelled() }}", "python")
    assert verdict["env"] == {"OUTCOMES": "${{ toJSON(steps) }}"}
    # continue-on-error keeps the job status at success, so failure() would never fire.
    assert "failure()" not in json.dumps(JOBS[job])


def test_every_node_command_line_is_a_known_one() -> None:
    # read-only-scans installs once for four scans, so no package script may run there (C-12.3).
    lines = {
        (job, line.strip())
        for job in JOBS
        for step in _steps(job)
        for line in step.get("run", "").splitlines()
        if NODE_TOOL.search(line) and not line.strip().startswith("#")
    }
    assert lines == {(job, line) for job, known in NODE_COMMANDS.items() for line in known}


def test_each_security_job_uses_only_its_pinned_actions() -> None:
    # No install action, or any other, joins a job unnoticed; SHA bumps don't change the set.
    uses = {job: {s["uses"].split("@")[0] for s in _steps(job) if "uses" in s} for job in JOBS}
    assert uses == ACTIONS


def test_freeze_proposal_upload_keys_on_the_freeze_step_outcome() -> None:
    (upload,) = [s for s in _steps("read-only-scans") if "upload-artifact@" in s.get("uses", "")]
    assert upload["if"].startswith("${{ !cancelled() && steps.freeze.outcome == 'failure' && (")


def test_uploads_never_gate_and_sarif_categories_stay_distinct() -> None:
    uploads = [(job, s) for job in JOBS for s in _steps(job) if "/upload-" in s.get("uses", "")]
    # The verdict reads only steps with an id, so an upload outage never fails a scan.
    assert all("id" not in s and s.get("continue-on-error") is True for _, s in uploads)
    sarif = {s["with"]["category"]: job for job, s in uploads if "upload-sarif@" in s["uses"]}
    assert len(sarif) == len([s for _, s in uploads if "upload-sarif@" in s["uses"]])
    assert sarif == {"codeql": "codeql", "trivy": "trivy"} | dict.fromkeys(
        ["semgrep", "bandit"], "semgrep-bandit"
    )


def _verdict(job: str, outcomes: dict[str, str], summary: Path) -> tuple[int, str]:
    """Run the verdict on the `steps` context GitHub builds: only steps with an `id` are in it."""
    context = {}
    for step in _steps(job)[:-1]:
        if "id" in step:  # an upload given an id would be judged on the "upload" outcome
            kind = "upload" if "/upload-" in step.get("uses", "") else step["id"]
            context[step["id"]] = {"outputs": {}, "outcome": outcomes.get(kind, "success")}
    env = {"OUTCOMES": json.dumps(context), "GITHUB_STEP_SUMMARY": str(summary)}
    env["PATH"] = os.environ.get("PATH", "")
    run = [sys.executable, "-c", _steps(job)[-1]["run"]]
    proc = subprocess.run(run, env=env, capture_output=True, text=True, timeout=60, check=False)
    return proc.returncode, proc.stderr.strip()


@pytest.mark.parametrize("job", sorted(SCANS))
def test_verdict_fails_on_any_red_scan_and_ignores_a_failed_upload(
    job: str, tmp_path: Path
) -> None:
    scans = [i for i in _ids(job) if i]
    summary = tmp_path / "summary.md"
    assert _verdict(job, {}, summary) == (0, "")
    rows = "".join(f"| {scan} | success |\n" for scan in scans)
    assert summary.read_text(encoding="utf-8") == "| scan | outcome |\n| --- | --- |\n" + rows
    assert _verdict(job, dict.fromkeys(scans, "skipped"), summary) == (0, "")
    assert _verdict(job, {"upload": "failure"}, summary) == (0, "")
    for scan in scans:
        for outcome in ("failure", "cancelled"):
            assert _verdict(job, {scan: outcome}, summary) == (1, f"scans not successful: {scan}")


# #3261: CV_CODEQL_LANGUAGES entry -> the SARIF analyze writes for it (the codeql job log of
# run 39070557384 shows javascript.sarif and python.sarif for these two languages).
WRITES = {"javascript-typescript": "javascript.sarif", "python": "python.sarif"}
LANGUAGES = ",".join(WRITES)
RESULTS = "${{ runner.temp }}/codeql-results"
CLEAN = json.dumps({"version": "2.1.0", "runs": [{"tool": {"driver": {"name": "CodeQL"}}}]})
# A CodeQL High: CodeQL scores the rule descriptor, not the result (#1715).
HIGH = """{"version": "2.1.0", "runs": [{"tool": {"driver": {"name": "CodeQL",
  "rules": [{"id": "x", "properties": {"security-severity": "7.5"}}]}},
  "results": [{"ruleId": "x", "message": {"text": "x"}}]}]}"""
NO_SARIF = re.compile(r"^CI-SEC-005: codeql produced no SARIF for (\S+) \(", re.MULTILINE)


def _codeql(marker: str) -> dict[str, Any]:
    """The one codeql step whose action or script contains `marker`."""
    (step,) = [s for s in _steps("codeql") if marker in s.get("uses", "") + s.get("run", "")]
    return step


def _run(
    marker: str,
    tmp_path: Path,
    temp: dict[str, str],
    langs: str | None = LANGUAGES,
    checkout: str = CLEAN,
    **env: str,
) -> subprocess.CompletedProcess[str]:
    """Run a codeql step's script as the runner does (`bash -e`), with `temp` under $RUNNER_TEMP
    and, in the checkout's own codeql-results/, a file per language whose body is `checkout`."""
    ws, runner_temp, bin_dir = tmp_path / "ws", tmp_path / "runner-temp", tmp_path / "bin"
    for d in (ws / "codeql-results", ws / "security", runner_temp / "codeql-results", bin_dir):
        d.mkdir(parents=True)
    (ws / "tools").symlink_to(ROOT / "tools")
    (ws / "security" / "accepted-risks.yaml").write_text("entries: []\n", encoding="utf-8")
    for d, files in ((ws, dict.fromkeys(WRITES.values(), checkout)), (runner_temp, temp)):
        for name, body in files.items():
            path = d / "codeql-results" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body, encoding="utf-8")
    python = bin_dir / "python"  # this interpreter (with PyYAML); -B: no bytecode in the repo
    python.write_text(f'#!/bin/sh\nexec "{sys.executable}" -B "$@"\n', encoding="utf-8")
    python.chmod(0o755)
    env["PATH"] = f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"
    env["RUNNER_TEMP"] = str(runner_temp)
    if langs is not None:
        env["CV_CODEQL_LANGUAGES"] = langs
    run = ["bash", "-e", "-c", _codeql(marker)["run"]]
    return subprocess.run(
        run, cwd=ws, env=env, capture_output=True, encoding="utf-8", timeout=120, check=False
    )


def test_codeql_languages_have_one_source_that_init_and_the_gate_read() -> None:
    assert JOBS["codeql"]["env"] == {"CV_CODEQL_LANGUAGES": LANGUAGES}
    assert _codeql("/init@")["with"]["languages"] == "${{ env.CV_CODEQL_LANGUAGES }}"
    assert '"${CV_CODEQL_LANGUAGES:-}"' in _codeql("security_gate.py")["run"]
    assert LANGUAGES not in json.dumps(_steps("codeql"))  # no step restates the list


def test_codeql_sarif_is_read_only_from_runner_temp() -> None:
    # A file a PR commits under the checkout's codeql-results/ must never count; hashFiles() sees
    # only the workspace, so it can no longer pick the upload either.
    analyze, upload = _codeql("/analyze@"), _codeql("/upload-sarif@")
    assert (analyze["with"]["output"], upload["with"]["sarif_file"]) == (RESULTS, RESULTS)
    for marker in ("security_gate.py", "found="):
        assert "$RUNNER_TEMP/codeql-results" in _codeql(marker)["run"]
    text = json.dumps(JOBS["codeql"])
    assert "hashFiles" not in text
    assert not re.findall(r"(?<!runner\.temp }}/)(?<!\$RUNNER_TEMP/)codeql-results", text)


def test_codeql_upload_keys_on_the_sarif_finder_and_never_gates() -> None:
    finder, upload = _codeql("found="), _codeql("/upload-sarif@")
    assert (finder["if"], finder["continue-on-error"]) == ("always()", True)
    assert upload["if"] == f"always() && steps.{finder['id']}.outputs.found == 'true'"
    assert "id" not in upload and upload["continue-on-error"] is True


@pytest.mark.parametrize("present", [("javascript.sarif",), ("python.sarif",), ()])
def test_codeql_gate_fails_naming_each_language_without_a_sarif_from_this_run(
    tmp_path: Path, present: tuple[str, ...]
) -> None:
    # The checkout's codeql-results/ holds every file; only runner temp counts.
    proc = _run("security_gate.py", tmp_path, dict.fromkeys(present, CLEAN))
    missing = {lang for lang, name in WRITES.items() if name not in present}
    assert (proc.returncode, set(NO_SARIF.findall(proc.stderr))) == (1, missing)


def test_codeql_gate_passes_when_every_language_has_a_clean_sarif(tmp_path: Path) -> None:
    # Invalid files in the checkout's codeql-results/ are never read either.
    sarif = dict.fromkeys(WRITES.values(), CLEAN)
    proc = _run("security_gate.py", tmp_path, sarif, checkout="{not sarif")
    assert (proc.returncode, proc.stdout.count("security_gate[codeql]: OK")) == (0, len(WRITES))


@pytest.mark.parametrize("high", [*WRITES.values(), ".extra/javascript.quality.sarif"])
def test_codeql_gate_blocks_a_high_in_any_sarif_it_uploads(tmp_path: Path, high: str) -> None:
    # Every language has a SARIF, so only security_gate.py can fail the step. The upload walks the
    # whole tree, so a file of another analysis kind, even in a hidden directory, is judged too.
    sarif = dict.fromkeys(WRITES.values(), CLEAN) | {high: HIGH}
    proc = _run("security_gate.py", tmp_path, sarif)
    assert (proc.returncode, proc.stdout.count("security_gate[codeql]: OK")) == (1, len(sarif) - 1)
    assert "security_gate[codeql]: BLOCKED (CI-SEC-001)" in proc.stderr


def test_codeql_gate_judges_each_language_so_a_bad_sarif_hides_no_missing_one(
    tmp_path: Path,
) -> None:
    proc = _run("security_gate.py", tmp_path, {"javascript.sarif": "{not sarif"})
    assert (proc.returncode, set(NO_SARIF.findall(proc.stderr))) == (1, {"python"})
    assert "CI-SEC-005: codeql: unreadable/invalid SARIF" in proc.stderr


@pytest.mark.parametrize("langs", ["", None, LANGUAGES.replace(",", ",,"), f"{LANGUAGES},"])
def test_codeql_gate_refuses_a_bad_language_list(tmp_path: Path, langs: str | None) -> None:
    proc = _run("security_gate.py", tmp_path, dict.fromkeys(WRITES.values(), CLEAN), langs)
    message = f"CI-SEC-005: CV_CODEQL_LANGUAGES='{langs or ''}' is not a language list"
    assert (proc.returncode, proc.stderr.strip()) == (1, message)


# The upload walks the whole tree, so the finder looks there too, and only there.
@pytest.mark.parametrize("present", [(), ("python.sarif",), (".extra/javascript.quality.sarif",)])
def test_codeql_finder_ignores_the_workspace(tmp_path: Path, present: tuple[str, ...]) -> None:
    out = tmp_path / "github-output"
    proc = _run("found=", tmp_path, dict.fromkeys(present, CLEAN), GITHUB_OUTPUT=str(out))
    assert proc.returncode == 0
    found = out.read_text(encoding="utf-8") if out.exists() else ""
    assert found == "found=true\n" * len(present)
