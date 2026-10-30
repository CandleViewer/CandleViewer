"""#270 (E05-T04): the visual-regression job, `_job-a11y.yml`'s `vr`, beside `a11y` and `storybook`.

These tests pin its wiring (it fails the required `a11y` check as its neighbours do), its ten
compare shards (`VR_SHARD`), the `vr_update` dispatch that alone writes baselines, and its uploads;
and they run its compare and budget steps under bash with stand-in `pnpm`, `fc-match` and `date`, as
test_storybook_job.py does for the storybook job."""

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
RUN = "Compare every story x theme x density with its baseline (CI-A11Y-006)"
FONTS = "Install the pinned fonts, Inter and JetBrains Mono (CI-A11Y-008)"
BUDGET = "Budget: a compare shard finishes within 6 minutes (CI-A11Y-007)"
UPDATE = "${{ inputs.vr_update }}"
#: A stand-in: logs its arguments and VR_SHARD, prints <NAME>_OUT, exits with <NAME>_EXIT.
FAKE = """import json, os, sys
name = os.path.basename(sys.argv[0]).upper().replace("-", "_")
with open(os.environ["CALLS"], "a", encoding="utf-8") as log:
    log.write(json.dumps([name, sys.argv[1:], os.environ.get("VR_SHARD")]) + "\\n")
print(os.environ.get(name + "_OUT", ""))
sys.exit(int(os.environ.get(name + "_EXIT", "0")))
"""


def _doc() -> dict[Any, Any]:
    doc: dict[Any, Any] = yaml.safe_load((ROOT / ".github/workflows/_job-a11y.yml").read_text())
    return doc


def _job() -> dict[str, Any]:
    job: dict[str, Any] = _doc()["jobs"]["vr"]
    return job


def _step(name: str) -> dict[str, Any]:
    (step,) = [s for s in _job()["steps"] if s.get("name") == name]
    return step


def test_vr_job_runs_beside_the_others_hardened_and_able_to_fail_the_a11y_check() -> None:
    job = _job()
    # No needs and no continue-on-error, so a red cell fails the lane, the required `a11y` check;
    # skipped only where the nightly runs the storybook job alone.
    assert not {"needs", "continue-on-error", "env"} & set(job)
    # A pinned image release, not ubuntu-latest: the baselines are drawn by its fonts and libraries.
    assert (job["if"], job["runs-on"]) == ("${{ !inputs.storybook_only }}", "ubuntu-24.04")
    assert job["permissions"] == {"contents": "read"}
    assert job["timeout-minutes"] == "${{ inputs.vr_update && 40 || 12 }}"
    shards = "${{ fromJSON(inputs.vr_update && '[0]' || '[1, 2, 3, 4, 5, 6, 7, 8, 9, 10]') }}"
    assert job["strategy"] == {"fail-fast": False, "matrix": {"shard": shards}}
    steps = job["steps"]
    assert steps[0] == {
        "name": "Start the budget clock",
        "run": 'date +%s > "$RUNNER_TEMP/vr-start"',
    }
    assert not any("continue-on-error" in step for step in steps)
    uses = [step["uses"] for step in steps if "uses" in step]
    pinned = re.compile(r"[\w.-]+/[\w.-]+(?:/[\w.-]+)?@[0-9a-f]{40}")
    assert all(pinned.fullmatch(use) for use in uses), uses
    assert [s["with"] for s in steps if "checkout@" in s.get("uses", "")] == [
        {"persist-credentials": False}
    ]
    assert all("${{" not in step.get("run", "") for step in steps)
    assert "secrets." not in json.dumps(job)


def test_only_the_dispatch_input_turns_the_job_into_an_update_and_uploads_baselines() -> None:
    on = _doc()[True]
    assert set(on) == {"workflow_call", "workflow_dispatch"}
    assert "vr_update" not in on["workflow_call"]["inputs"]  # no caller workflow can ask for one
    (only,) = on["workflow_dispatch"]["inputs"].items()
    assert (only[0], only[1]["type"], only[1]["default"]) == ("vr_update", "boolean", False)
    assert _step(RUN)["env"] == {
        "SHARD": "${{ matrix.shard }}",
        "TOTAL": "${{ strategy.job-total }}",
        "VR_UPDATE": "${{ inputs.vr_update && '1' || '' }}",
    }
    assert _step(BUDGET)["if"] == "${{ !inputs.vr_update }}"
    steps = _job()["steps"]
    uploads = [(s.get("if"), s["with"]) for s in steps if "upload-artifact@" in s.get("uses", "")]
    diffs = {"name": "vr-diffs-${{ matrix.shard }}", "path": "packages/ui/test-results/vr/"}
    baselines = {"name": "vr-baselines", "path": "packages/ui/vr/baselines/"}
    assert uploads == [
        ("failure()", diffs | {"retention-days": 14}),
        (UPDATE, baselines | {"if-no-files-found": "error", "retention-days": 14}),
    ]


def _bash(
    tmp_path: Path, script: str, **env: str
) -> tuple[subprocess.CompletedProcess[str], list[Any]]:
    """Run a step's script as the runner runs `shell: bash`, with stand-ins first on PATH."""
    if not shutil.which("bash"):  # CI must run these fail-closed proofs
        (pytest.fail if os.environ.get("CI") else pytest.skip)("bash runs the step")
    (tmp_path / "bin").mkdir(exist_ok=True)
    for fake in ("pnpm", "fc-match", "fc-list", "sudo", "dpkg-query", "date"):
        (tmp_path / "bin" / fake).write_text(f"#!{sys.executable}\n{FAKE}", encoding="utf-8")
        (tmp_path / "bin" / fake).chmod(0o755)
    calls, summary = tmp_path / "calls", tmp_path / "summary"
    base = {"PATH": f"{tmp_path / 'bin'}{os.pathsep}{os.environ.get('PATH', '')}"}
    base |= {"CALLS": str(calls), "GITHUB_STEP_SUMMARY": str(summary), "RUNNER_TEMP": str(tmp_path)}
    args = ["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", script]
    proc = subprocess.run(
        args, env=base | env, capture_output=True, text=True, timeout=60, check=False
    )
    logged = [json.loads(line) for line in calls.read_text().splitlines()] if calls.exists() else []
    return proc, logged


@pytest.mark.parametrize(
    ("shard", "update", "script", "cells"),
    [("1", "", "vr", "1/10"), ("10", "", "vr", "10/10"), ("0", "1", "vr:update", None)],
)
def test_run_step_compares_its_shard_or_updates_the_whole_matrix(
    tmp_path: Path, shard: str, update: str, script: str, cells: str | None
) -> None:
    env = {"SHARD": shard, "TOTAL": "10", "VR_UPDATE": update, "DATE_OUT": "1000"}
    proc, calls = _bash(tmp_path, _step(RUN)["run"], **env)
    assert proc.returncode == 0, proc
    # The spec picks the shard's cells itself (packages/ui/vr/matrix.ts), not Playwright's --shard.
    assert [(args, picked) for name, args, picked in calls if name == "PNPM"] == [
        (["--filter", "@candleviewer/ui", "run", script], cells)
    ]
    # The compare step stamps its own start, so the budget line can name the step's seconds.
    assert (tmp_path / "vr-step-start").read_text() == "1000\n"
    # fc-match names fontconfig's substitute, not the face Chromium draws: the spec reports that.
    assert not [name for name, _, _ in calls if name == "FC_MATCH"]


def test_fonts_step_installs_the_pinned_packages_before_the_compare_and_names_them(
    tmp_path: Path,
) -> None:
    steps = _job()["steps"]
    names = [step.get("name") for step in steps]
    assert names.index(FONTS) < names.index(RUN)
    step = _step(FONTS)
    # Pinned to the image's own archive (noble's release pocket), never best-effort.
    assert step["env"] == {"INTER": "4.0+ds-1", "JETBRAINS_MONO": "2.304+ds-4"}
    assert "continue-on-error" not in step and "if" not in step
    installed = "fonts-inter 4.0+ds-1\nfonts-jetbrains-mono 2.304+ds-4"  # dpkg-query: one per line
    env = {**step["env"], "DPKG_QUERY_OUT": installed}
    proc, calls = _bash(tmp_path, step["run"], **env)
    assert proc.returncode == 0, proc
    sudo = [args for name, args, _ in calls if name == "SUDO"]
    assert sudo[-1][:2] == ["apt-get", "install"]
    assert {"fonts-inter=4.0+ds-1", "fonts-jetbrains-mono=2.304+ds-4"} <= set(sudo[-1])
    assert [args for name, args, _ in calls if name == "FC_LIST"] == [
        ["-q", "Inter"],
        ["-q", "JetBrains Mono"],
    ]
    summary = (tmp_path / "summary").read_text()
    assert "- Fonts installed: fonts-inter 4.0+ds-1, fonts-jetbrains-mono 2.304+ds-4\n" in summary


@pytest.mark.parametrize("failing", ["SUDO_EXIT", "FC_LIST_EXIT"])
def test_fonts_step_fails_the_job_with_its_code_when_a_family_is_missing(
    tmp_path: Path, failing: str
) -> None:
    step = _step(FONTS)
    proc, _ = _bash(tmp_path, step["run"], **step["env"], **{failing: "1"})
    assert proc.returncode == 1 and "::error::CI-A11Y-008 " in proc.stdout, proc


def test_run_step_fails_with_its_code_when_a_cell_fails(tmp_path: Path) -> None:
    proc, _ = _bash(tmp_path, _step(RUN)["run"], SHARD="2", VR_UPDATE="", PNPM_EXIT="1")
    assert proc.returncode == 1 and "::error::CI-A11Y-006 " in proc.stdout


@pytest.mark.parametrize(("start", "red"), [("640", False), ("639", True)])
def test_budget_step_fails_a_shard_over_360_seconds(tmp_path: Path, start: str, red: bool) -> None:
    (tmp_path / "vr-start").write_text(start)
    (tmp_path / "vr-step-start").write_text("820")
    proc, _ = _bash(tmp_path, _step(BUDGET)["run"], SHARD="3", DATE_OUT="1000")
    assert (proc.returncode != 0, "::error::CI-A11Y-007 " in proc.stdout) == (red, red), proc
    budget = f"- VR shard 3: {1000 - int(start)} s of its 360 s budget (the compare step: 180 s)"
    assert budget in proc.stdout
