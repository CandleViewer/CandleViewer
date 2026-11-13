"""#3099: `changelog-preview` reads pull requests for `--pr-labels-json`, so it holds a token.

Ruling 2026-11-02 (a): it runs only the base ref's committed tools against the PR's checkout, never
the PR's own code with a token in reach (the gate the #5422 lens asked for in `pr.yml`,
`test_no_pr_script_runs_before_the_secret_scanners`). The token lives in the one step that runs
`gh pr list` and no repo code; every checkout keeps `persist-credentials: false`.
"""

from __future__ import annotations

import copy
import posixpath
import re
from pathlib import Path
from typing import Any

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
