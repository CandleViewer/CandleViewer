"""#3099: `changelog-preview` reads pull requests for `--pr-labels-json`, so it holds a token.

Ruling 2026-11-02 (a): it runs only the base ref's committed tools against the PR's checkout, never
the PR's own code with a token in reach (the gate the #5422 lens asked for in `pr.yml`,
`test_no_pr_script_runs_before_the_secret_scanners`). The token lives in the one step that runs
`gh pr list` and no repo code; every checkout keeps `persist-credentials: false`.
"""

from __future__ import annotations

import copy
import os
import posixpath
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
DOC: dict[Any, Any] = yaml.safe_load(
    (ROOT / ".github" / "workflows" / "changelog.yml").read_text(encoding="utf-8")
)
BASE_REF = "${{ github.event.pull_request.base.sha || github.sha }}"
TOKEN_RE = re.compile(r"github\.token|secrets\.|GITHUB_TOKEN|GH_TOKEN")
# Anything that executes a file from a checkout: an interpreter, a build tool or a relative path.
EXEC_RE = re.compile(r"\b(python3?|node|bash|sh|make|pnpm|npm|npx|uv|pip)\b|(^|\s)\.{0,2}/")


def _offences(doc: dict[Any, Any]) -> list[str]:
    """Steps of changelog-preview that could run PR-controlled code or leak the token."""
    job = doc["jobs"]["changelog-preview"]
    steps: list[dict[str, Any]] = job["steps"]
    found: list[str] = []
    if TOKEN_RE.search(str(job.get("env", "")) + str(doc.get("env", ""))):
        found.append("token in job/workflow env")
    checkouts = [s for s in steps if "actions/checkout@" in s.get("uses", "")]
    base = [s for s in checkouts if s["with"].get("ref") == BASE_REF]
    base_path = base[0]["with"]["path"] if len(base) == 1 else None
    for step in checkouts:
        if step["with"].get("persist-credentials") is not False:
            found.append(f"checkout {step['with'].get('path')!r} persists credentials")
    if base_path is None:
        found.append("no single checkout of the base ref")
    for step in steps:
        run = str(step.get("run", ""))
        if not run:
            continue
        name = step.get("name", run)
        token = TOKEN_RE.search(str(step.get("env", "")) + run)
        if token and EXEC_RE.search(run.replace("$RUNNER_TEMP/", "")):
            found.append(f"{name}: runs repo code with the token")
        for script in re.findall(r"(\S*tools/ci/\S+\.py)", run):
            workdir = step.get("working-directory", ".")
            resolved = posixpath.normpath(posixpath.join(workdir, script))
            if base_path is None or not resolved.startswith(f"{base_path}/"):
                found.append(f"{name}: runs {script} from {workdir!r}, not the base checkout")
    return found


def test_changelog_preview_runs_only_the_base_tools_with_the_token_out_of_reach() -> None:
    job = DOC["jobs"]["changelog-preview"]
    assert DOC["permissions"] == {"contents": "read"}
    assert job["permissions"] == {"contents": "read", "pull-requests": "read"}
    assert _offences(DOC) == []
    (labels,) = [s for s in job["steps"] if "GH_TOKEN" in (s.get("env") or {})]
    assert labels["env"] == {"GH_TOKEN": "${{ github.token }}"}
    assert labels["run"].startswith('gh pr list --repo "$GITHUB_REPOSITORY" --state merged')
    assert "--json number,labels" in labels["run"]
    (preview,) = [s for s in job["steps"] if "update_changelog.py" in str(s.get("run", ""))]
    assert preview["working-directory"] == "pr"
    assert '--pr-labels-json "$RUNNER_TEMP/pr-labels.json"' in preview["run"]
    assert "--preview" in preview["run"] and "GH_TOKEN" not in str(preview.get("env"))


def test_changelog_preview_gate_fails_on_a_job_running_the_prs_own_tools() -> None:
    # The pre-#3099 shape: one checkout of the PR, its own tools/ci run from the workspace root.
    old = copy.deepcopy(DOC)
    steps = old["jobs"]["changelog-preview"]["steps"]
    steps[:] = [s for s in steps if s.get("with", {}).get("ref") != BASE_REF]
    for step in steps:
        step.pop("working-directory", None)
        if "run" in step:
            step["run"] = step["run"].replace("../base/tools/ci/", "tools/ci/")
    assert any("not the base checkout" in o for o in _offences(old))
    assert "no single checkout of the base ref" in _offences(old)
    # The token moved into the step that runs the tools.
    leaked = copy.deepcopy(DOC)
    preview = leaked["jobs"]["changelog-preview"]["steps"][-1]
    preview["env"]["GH_TOKEN"] = "${{ github.token }}"
    assert any("with the token" in o for o in _offences(leaked))
    # A checkout that keeps the token in .git/config.
    persisted = copy.deepcopy(DOC)
    persisted["jobs"]["changelog-preview"]["steps"][0]["with"]["persist-credentials"] = True
    assert _offences(persisted) == ["checkout 'pr' persists credentials"]


# #3099 (release contract (3)): the advisory verify on release-prep PRs, the untagged candidate.
ADVISORY = "Advisory release verification of a release-prep PR (warnings only)"
FAKE_TOOLS = """import json, os, sys
with open(os.environ["PY_LOG"], "a", encoding="utf-8") as fh:
    fh.write(json.dumps(sys.argv[1:]) + "\\n")
print("::error::CI-REL-005: version 0.1.1 != expected 0.2.0")
sys.exit(1)
"""
FAKE_GIT = """import os
print(os.environ.get("CHANGED", ""))
"""


def _advisory(tmp_path: Path, title: str, changed: str) -> tuple[int, str, list[str]]:
    step = next(s for s in DOC["jobs"]["changelog-preview"]["steps"] if s.get("name") == ADVISORY)
    tool = tmp_path / "base" / "tools" / "ci" / "prepare_release.py"
    tool.parent.mkdir(parents=True)
    tool.write_text("", encoding="utf-8")
    (tmp_path / "pr").mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, source in {"python": FAKE_TOOLS, "git": FAKE_GIT}.items():
        (bin_dir / name).write_text(f"#!{sys.executable}\n{source}", encoding="utf-8")
        (bin_dir / name).chmod(0o755)
    log, summary = tmp_path / "py.log", tmp_path / "summary.md"
    env = {"PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}", "PY_LOG": str(log)}
    env |= {"TITLE": title, "CHANGED": changed, "RUNNER_TEMP": str(tmp_path)}
    env |= {"GITHUB_STEP_SUMMARY": str(summary), "HOME": str(tmp_path)}
    proc = subprocess.run(
        ["bash", "-e", "-c", step["run"]],
        cwd=tmp_path / step["working-directory"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    calls = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
    return proc.returncode, proc.stdout + proc.stderr, calls


@pytest.mark.parametrize(
    ("title", "changed", "runs"),
    [
        ("chore(infra-devops): prepare release 0.2.0", "CHANGELOG.md", True),
        ("docs(docs): sync unreleased", "CHANGELOG.md\nversion.txt", True),
        ("docs(docs): sync unreleased", "CHANGELOG.md", False),
        ("chore(infra-devops): prepare release 0.2.0 (#5)", "CHANGELOG.md", False),
    ],
)
def test_advisory_verify_runs_on_prep_shaped_prs_and_never_fails(
    tmp_path: Path, title: str, changed: str, runs: bool
) -> None:
    if not shutil.which("bash"):
        pytest.skip("bash runs the step")
    rc, out, calls = _advisory(tmp_path, title, changed)
    assert rc == 0, out
    assert bool(calls) == runs
    if runs:
        assert calls == [
            '["../base/tools/ci/prepare_release.py", "--verify", "--rev", "HEAD", '
            '"--main-ref", "HEAD"]'
        ]
        assert "::warning::CI-REL-005" in out and "::error::" not in out


def test_changelog_runs_on_prs_changing_version_txt_and_names_an_untagged_candidate() -> None:
    assert "version.txt" in DOC[True]["pull_request"]["paths"]
    steps = DOC["jobs"]["changelog-preview"]["steps"]
    (untagged,) = [s for s in steps if "release_run.py untagged" in str(s.get("run", ""))]
    assert untagged["working-directory"] == "pr" and "GH_TOKEN" not in str(untagged.get("env"))
    assert '--summary "$GITHUB_STEP_SUMMARY"' in untagged["run"]
    advisory = next(s for s in steps if s.get("name") == ADVISORY)
    assert advisory["env"] == {"TITLE": "${{ github.event.pull_request.title }}"}
    assert "${{" not in advisory["run"]
