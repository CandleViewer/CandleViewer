"""#270 (E05-T04): the visual-regression job, `_job-a11y.yml`'s `vr`, beside `a11y` and `storybook`.

These tests pin its wiring (it fails the required `a11y` check as its neighbours do), its fourteen
compare shards (`VR_SHARD`, ten until #5275), the `vr_update` dispatch that alone writes baselines,
and its uploads; and they run its font, compare and budget steps under bash with stand-in `pnpm`,
`apt-get`, `fuser`, `systemctl`, `sleep`, `fc-match` and `date` (`sudo` runs its arguments), as
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
BUDGET = "Budget: a compare shard runs within its per-cell budget (CI-A11Y-007)"
UPDATE = "${{ inputs.vr_update }}"
#: A stand-in: logs its arguments and VR_SHARD, prints <NAME>_OUT, exits with <NAME>_EXIT.
FAKE = """import json, os, sys
name = os.path.basename(sys.argv[0]).upper().replace("-", "_")
with open(os.environ["CALLS"], "a", encoding="utf-8") as log:
    log.write(json.dumps([name, sys.argv[1:], os.environ.get("VR_SHARD")]) + "\\n")
print(os.environ.get(name + "_OUT", ""))
sys.exit(int(os.environ.get(name + "_EXIT", "0")))
"""
#: `sudo` runs its arguments, so the stand-ins behind it log under their own names.
SUDO = '#!/bin/bash\nexec "$@"\n'
#: `fuser` reports the apt locks held (exit 0) on its first FUSER_HELD calls, then free (exit 1).
FUSER = """import json, os, sys
with open(os.environ["CALLS"], "a", encoding="utf-8") as log:
    log.write(json.dumps(["FUSER", sys.argv[1:], None]) + "\\n")
count = os.path.join(os.environ["RUNNER_TEMP"], "fuser-calls")
n = int(open(count).read()) if os.path.exists(count) else 0
open(count, "w").write(str(n + 1))
sys.exit(0 if n < int(os.environ.get("FUSER_HELD", "0")) else 1)
"""


#: `systemctl`: logs its arguments; `is-active --quiet <unit>` exits 0 only for the units named in
#: SYSTEMCTL_ACTIVE (comma-separated), so by default nothing is running (#5530).
SYSTEMCTL = """import json, os, sys
with open(os.environ["CALLS"], "a", encoding="utf-8") as log:
    log.write(json.dumps(["SYSTEMCTL", sys.argv[1:], None]) + "\\n")
active = set(filter(None, os.environ.get("SYSTEMCTL_ACTIVE", "").split(",")))
if sys.argv[1:2] == ["is-active"]:
    sys.exit(0 if sys.argv[-1] in active else 3)
sys.exit(int(os.environ.get("SYSTEMCTL_EXIT", "0")))
"""
APT_UNITS = [
    "apt-daily.timer",
    "apt-daily-upgrade.timer",
    "apt-daily.service",
    "apt-daily-upgrade.service",
    "unattended-upgrades.service",
]


def _doc() -> dict[Any, Any]:
    doc: dict[Any, Any] = yaml.safe_load(
        (ROOT / ".github/workflows/_job-a11y.yml").read_text()
    )
    return doc


def _job() -> dict[str, Any]:
    job: dict[str, Any] = _doc()["jobs"]["vr"]
    return job


def _step(name: str) -> dict[str, Any]:
    (step,) = [s for s in _job()["steps"] if s.get("name") == name]
    return step


def test_vr_job_runs_beside_the_others_hardened_and_able_to_fail_the_a11y_check() -> (
    None
):
    job = _job()
    # No needs and no continue-on-error, so a red cell fails the lane, the required `a11y` check;
    # skipped only where the nightly runs the storybook job alone.
    assert not {"needs", "continue-on-error", "env"} & set(job)
    # A pinned image release, not ubuntu-latest: the baselines are drawn by its fonts and libraries.
    assert (job["if"], job["runs-on"]) == (
        "${{ !inputs.storybook_only }}",
        "ubuntu-24.04",
    )
    assert job["permissions"] == {"contents": "read"}
    assert job["timeout-minutes"] == "${{ inputs.vr_update && 40 || 12 }}"
    every = ", ".join(str(k) for k in range(1, 15))
    shards = f"${{{{ fromJSON(inputs.vr_update && '[0]' || '[{every}]') }}}}"
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


def test_only_the_dispatch_input_turns_the_job_into_an_update_and_uploads_baselines() -> (
    None
):
    on = _doc()[True]
    assert set(on) == {"workflow_call", "workflow_dispatch"}
    assert (
        "vr_update" not in on["workflow_call"]["inputs"]
    )  # no caller workflow can ask for one
    (only,) = on["workflow_dispatch"]["inputs"].items()
    assert (only[0], only[1]["type"], only[1]["default"]) == (
        "vr_update",
        "boolean",
        False,
    )
    assert _step(RUN)["env"] == {
        "SHARD": "${{ matrix.shard }}",
        "TOTAL": "${{ strategy.job-total }}",
        "VR_UPDATE": "${{ inputs.vr_update && '1' || '' }}",
    }
    assert _step(BUDGET)["if"] == "${{ !inputs.vr_update }}"
    steps = _job()["steps"]
    uploads = [
        (s.get("if"), s["with"])
        for s in steps
        if "upload-artifact@" in s.get("uses", "")
    ]
    diffs = {
        "name": "vr-diffs-${{ matrix.shard }}",
        "path": "packages/ui/test-results/vr/",
    }
    baselines = {"name": "vr-baselines", "path": "packages/ui/vr/baselines/"}
    assert uploads == [
        ("failure()", diffs | {"retention-days": 14}),
        (UPDATE, baselines | {"if-no-files-found": "error", "retention-days": 14}),
    ]


def _bash(
    tmp_path: Path, script: str, *, no_fuser: bool = False, **env: str
) -> tuple[subprocess.CompletedProcess[str], list[Any]]:
    """Run a step's script as the runner runs `shell: bash`, with stand-ins first on PATH.

    With no_fuser, PATH is the stand-ins, `bash` and `paste` alone, so no system `fuser` is found."""
    if not shutil.which("bash"):  # CI must run these fail-closed proofs
        (pytest.fail if os.environ.get("CI") else pytest.skip)("bash runs the step")
    (tmp_path / "bin").mkdir(exist_ok=True)
    for fake in (
        "pnpm",
        "fc-match",
        "fc-list",
        "apt-get",
        "dpkg-query",
        "date",
        "sleep",
    ):
        (tmp_path / "bin" / fake).write_text(
            f"#!{sys.executable}\n{FAKE}", encoding="utf-8"
        )
        (tmp_path / "bin" / fake).chmod(0o755)
    (tmp_path / "bin" / "fuser").write_text(
        f"#!{sys.executable}\n{FUSER}", encoding="utf-8"
    )
    (tmp_path / "bin" / "systemctl").write_text(
        f"#!{sys.executable}\n{SYSTEMCTL}", encoding="utf-8"
    )
    (tmp_path / "bin" / "sudo").write_text(SUDO, encoding="utf-8")
    for fake in ("fuser", "systemctl", "sudo"):
        (tmp_path / "bin" / fake).chmod(0o755)
    calls, summary = tmp_path / "calls", tmp_path / "summary"
    path = os.environ.get("PATH", "")
    if no_fuser:
        (tmp_path / "bin" / "fuser").unlink()
        (tmp_path / "sys").mkdir(exist_ok=True)
        for tool in ("bash", "paste"):  # the shell, and the join of dpkg-query's lines
            found = shutil.which(tool)
            assert found, tool
            (tmp_path / "sys" / tool).symlink_to(found)
        path = str(tmp_path / "sys")
    base = {"PATH": f"{tmp_path / 'bin'}{os.pathsep}{path}"}
    base |= {
        "CALLS": str(calls),
        "GITHUB_STEP_SUMMARY": str(summary),
        "RUNNER_TEMP": str(tmp_path),
    }
    args = ["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", script]
    proc = subprocess.run(
        args, env=base | env, capture_output=True, text=True, timeout=60, check=False
    )
    logged = (
        [json.loads(line) for line in calls.read_text().splitlines()]
        if calls.exists()
        else []
    )
    return proc, logged


@pytest.mark.parametrize(
    ("shard", "update", "script", "cells"),
    [("1", "", "vr", "1/14"), ("14", "", "vr", "14/14"), ("0", "1", "vr:update", None)],
)
def test_run_step_compares_its_shard_or_updates_the_whole_matrix(
    tmp_path: Path, shard: str, update: str, script: str, cells: str | None
) -> None:
    env = {"SHARD": shard, "TOTAL": "14", "VR_UPDATE": update, "DATE_OUT": "1000"}
    env["PNPM_OUT"] = "- VR matrix: 5956 cells (994 stories x 3 themes x 2 densities)"
    proc, calls = _bash(tmp_path, _step(RUN)["run"], **env)
    assert proc.returncode == 0, proc
    # The spec picks the shard's cells itself (packages/ui/vr/matrix.ts), not Playwright's --shard.
    assert [(args, picked) for name, args, picked in calls if name == "PNPM"] == [
        (["--filter", "@candleviewer/ui", "run", script], cells)
    ]
    # The compare step stamps its own start and end and keeps its log, so the budget step can
    # judge the step's seconds per cell from the reporter's matrix line (#5595).
    assert (tmp_path / "vr-step-start").read_text() == "1000\n"
    assert (tmp_path / "vr-step-end").read_text() == "1000\n"
    assert "- VR matrix: 5956 cells" in (tmp_path / "vr-compare.log").read_text()
    assert "- VR matrix: 5956 cells" in proc.stdout
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
    apt = [args for name, args, _ in calls if name == "APT_GET"]
    lock = ["-o", "DPkg::Lock::Timeout=60"]
    assert [args[:3] for args in apt] == [[*lock, "update"], [*lock, "install"]]
    assert {"fonts-inter=4.0+ds-1", "fonts-jetbrains-mono=2.304+ds-4"} <= set(apt[-1])
    # Each apt-get waits for apt's lists lock as well as dpkg's (#5275); free here, so no pause.
    locks = [
        "/var/lib/apt/lists/lock",
        "/var/lib/dpkg/lock",
        "/var/lib/dpkg/lock-frontend",
        "/var/cache/apt/archives/lock",
    ]
    fuser = [args for name, args, _ in calls if name == "FUSER"]
    assert len(fuser) == 2 and all(set(locks) <= set(args) for args in fuser)
    # #5530: the apt background units are stopped (never masked) before the first lock check.
    order = [
        (name, args[:1]) for name, args, _ in calls if name in {"SYSTEMCTL", "FUSER"}
    ]
    stop = order.index(("SYSTEMCTL", ["stop"]))
    assert stop < order.index(("FUSER", fuser[0][:1]))
    assert [
        args for name, args, _ in calls if name == "SYSTEMCTL" and args[0] == "stop"
    ] == [["stop", *APT_UNITS]]
    assert not [
        args for name, args, _ in calls if name == "SYSTEMCTL" and "mask" in args
    ]
    assert not [name for name, _, _ in calls if name == "SLEEP"]
    assert "::warning::" not in proc.stdout
    assert [args for name, args, _ in calls if name == "FC_LIST"] == [
        ["-q", "Inter"],
        ["-q", "JetBrains Mono"],
    ]
    summary = (tmp_path / "summary").read_text()
    assert (
        "- Fonts installed: fonts-inter 4.0+ds-1, fonts-jetbrains-mono 2.304+ds-4\n"
        in summary
    )


@pytest.mark.parametrize("failing", ["APT_GET_EXIT", "FC_LIST_EXIT"])
def test_fonts_step_fails_the_job_with_its_code_when_a_family_is_missing(
    tmp_path: Path, failing: str
) -> None:
    step = _step(FONTS)
    proc, calls = _bash(tmp_path, step["run"], **step["env"], **{failing: "1"})
    assert proc.returncode == 1 and "::error::CI-A11Y-008 " in proc.stdout, proc
    if (
        failing == "APT_GET_EXIT"
    ):  # three tries, 20 s apart (stubbed), a warning for each
        assert len([n for n, _, _ in calls if n == "APT_GET"]) == 3
        assert [args for n, args, _ in calls if n == "SLEEP"] == [["20"], ["20"]]
        assert proc.stdout.count("::warning::CI-A11Y-008 apt attempt") == 3


def test_fonts_step_waits_for_a_held_apt_lock_then_installs(tmp_path: Path) -> None:
    # #5275: an apt-get left by an earlier step held /var/lib/apt/lists/lock, which
    # DPkg::Lock::Timeout does not cover; the step waits it out instead of failing three times.
    step = _step(FONTS)
    installed = "fonts-inter 4.0+ds-1\nfonts-jetbrains-mono 2.304+ds-4"
    env = {**step["env"], "DPKG_QUERY_OUT": installed, "FUSER_HELD": "3"}
    proc, calls = _bash(tmp_path, step["run"], **env)
    assert proc.returncode == 0, proc
    names = [name for name, _, _ in calls if name in {"FUSER", "SLEEP", "APT_GET"}]
    # Held on three polls, 2 s apart, then free: update, then a free poll and the install.
    held = ["FUSER", "SLEEP"] * 3
    assert names == [*held, "FUSER", "APT_GET", "FUSER", "APT_GET"]
    assert [args for name, args, _ in calls if name == "SLEEP"] == [["2"]] * 3
    assert "::warning::CI-A11Y-008 waited 6 s for the apt lock" in proc.stdout


def test_fonts_step_without_fuser_warns_once_and_installs_without_the_wait(
    tmp_path: Path,
) -> None:
    # A quietly skipped lock wait would come back as a mystery CI-A11Y-008; the log names it.
    step = _step(FONTS)
    installed = "fonts-inter 4.0+ds-1\nfonts-jetbrains-mono 2.304+ds-4"
    env = {**step["env"], "DPKG_QUERY_OUT": installed}
    proc, calls = _bash(tmp_path, step["run"], no_fuser=True, **env)
    assert proc.returncode == 0, proc
    warning = "::warning::CI-A11Y-008 fuser is missing, so the step does not wait for the apt lock"
    assert proc.stdout.count(warning) == 1
    assert len([name for name, _, _ in calls if name == "APT_GET"]) == 2
    assert not [name for name, _, _ in calls if name in {"FUSER", "SLEEP"}]


def test_fonts_step_fails_with_its_code_when_the_apt_lock_is_never_released(
    tmp_path: Path,
) -> None:
    step = _step(FONTS)
    proc, calls = _bash(tmp_path, step["run"], **step["env"], FUSER_HELD="1000")
    assert proc.returncode == 1, proc
    assert "::error::CI-A11Y-008 the apt lock was still held after 300 s" in proc.stdout
    # Bounded: 150 two-second polls (#5530: 300 s), then the code; apt-get never ran against a held lock.
    assert [args for name, args, _ in calls if name == "SLEEP"] == [["2"]] * 150
    assert not [name for name, _, _ in calls if name == "APT_GET"]


def test_fonts_step_stops_a_running_unattended_upgrade_and_warns_once(
    tmp_path: Path,
) -> None:
    # #5530: the image's post-boot unattended-upgrades held the lists lock past the wait budget.
    step = _step(FONTS)
    installed = "fonts-inter 4.0+ds-1\nfonts-jetbrains-mono 2.304+ds-4"
    env = {
        **step["env"],
        "DPKG_QUERY_OUT": installed,
        "SYSTEMCTL_ACTIVE": "apt-daily-upgrade.service,unattended-upgrades.service",
    }
    proc, calls = _bash(tmp_path, step["run"], **env)
    assert proc.returncode == 0, proc
    warning = (
        "::warning::CI-A11Y-008 stopped the apt background units: "
        "apt-daily-upgrade.service unattended-upgrades.service"
    )
    assert (
        proc.stdout.count("::warning::CI-A11Y-008 stopped") == 1
        and warning in proc.stdout
    )
    assert ["stop", *APT_UNITS] in [
        args for name, args, _ in calls if name == "SYSTEMCTL"
    ]
    assert len([name for name, _, _ in calls if name == "APT_GET"]) == 2


def test_fonts_step_falls_back_to_the_wait_when_a_unit_will_not_stop(
    tmp_path: Path,
) -> None:
    # A failed stop is not fatal: the 300 s lock wait and the retries still guard the apt-get.
    step = _step(FONTS)
    installed = "fonts-inter 4.0+ds-1\nfonts-jetbrains-mono 2.304+ds-4"
    env = {
        **step["env"],
        "DPKG_QUERY_OUT": installed,
        "SYSTEMCTL_EXIT": "1",
        "FUSER_HELD": "2",
    }
    proc, calls = _bash(tmp_path, step["run"], **env)
    assert proc.returncode == 0, proc
    assert "::warning::CI-A11Y-008 waited 4 s for the apt lock" in proc.stdout
    assert len([name for name, _, _ in calls if name == "APT_GET"]) == 2


def test_run_step_fails_with_its_code_when_a_cell_fails(tmp_path: Path) -> None:
    proc, _ = _bash(tmp_path, _step(RUN)["run"], SHARD="2", VR_UPDATE="", PNPM_EXIT="1")
    assert proc.returncode == 1 and "::error::CI-A11Y-006 " in proc.stdout


def _budget(
    tmp_path: Path,
    *,
    step: int,
    overhead: int = 81,
    matrix: str | None = "5956",
    shard: str = "3",
    end_stamp: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run the budget step after a compare step of `step` s that began `overhead` s into the job.

    The log carries the reporter's "VR matrix: <matrix> cells" line unless matrix is None."""
    (tmp_path / "vr-start").write_text("1000\n")
    (tmp_path / "vr-step-start").write_text(f"{1000 + overhead}\n")
    (tmp_path / "vr-step-end").write_text(end_stamp or f"{1000 + overhead + step}\n")
    line = (
        ""
        if matrix is None
        else f"- VR matrix: {matrix} cells (x stories x 3 themes)\n"
    )
    (tmp_path / "vr-compare.log").write_text(
        f"Running 426 tests\n{line}- VR diffs: 0\n"
    )
    proc, _ = _bash(tmp_path, _step(BUDGET)["run"], SHARD=shard, TOTAL="14")
    return proc


def _codes(proc: subprocess.CompletedProcess[str], kind: str) -> list[str]:
    return [line for line in proc.stdout.splitlines() if line.startswith(f"::{kind}::")]


def test_budget_step_names_its_seconds_and_cells_in_one_summary_line(
    tmp_path: Path,
) -> None:
    # Shard 3 of 14 over 5956 cells takes ceil((5956 - 2) / 14) = 426; 128 s is the norm,
    # 300 ms/cell.
    proc = _budget(tmp_path, step=128)
    line = (
        "- VR shard 3: 209 s to the end of the compare step (overhead 81 s, the compare step 128 s for 426 cells: 300 ms/cell; "
        "fail at 900 ms/cell or 600 s)"
    )
    assert proc.returncode == 0 and not _codes(proc, "warning"), proc
    assert proc.stdout.splitlines() == [line]
    assert (tmp_path / "summary").read_text() == line + "\n"


def test_budget_step_warns_at_twice_the_norm_and_passes(tmp_path: Path) -> None:
    proc = _budget(tmp_path, step=256)  # 256000 / 426 = 600 ms/cell
    assert proc.returncode == 0, proc
    assert _codes(proc, "warning") == [
        (
            "::warning::CI-A11Y-007 VR shard 3 compare step ran at 600 ms/cell over 426 cells "
            "(norm 300, fail at 900; usually a slow runner pool; a code cause is possible above the norm)"
        )
    ]
    assert not _codes(proc, "error")


@pytest.mark.parametrize(
    ("matrix", "step", "ms", "red"),
    # Shard 1 of 14: 5978 cells give 427 (384 s is 899 ms/cell), 6020 give 430 (387 s is 900).
    [("5978", 384, 899, False), ("6020", 387, 900, True)],
)
def test_budget_step_fails_a_compare_step_at_900_ms_a_cell(
    tmp_path: Path, matrix: str, step: int, ms: int, red: bool
) -> None:
    proc = _budget(tmp_path, step=step, matrix=matrix, shard="1")
    assert (
        f"the compare step {step} s for " in proc.stdout
        and f": {ms} ms/cell;" in proc.stdout
    )
    errors = _codes(proc, "error")
    assert (proc.returncode != 0, bool(errors)) == (red, red), proc
    if red:
        assert errors == [
            (
                f"::error::CI-A11Y-007 VR shard 1 compare step ran at {ms} ms/cell over 430 "
                "cells, at or over 900 ms/cell (docs/ci-runbook.md)"
            )
        ]
    else:  # over 450 ms/cell: the slow-pool warning
        assert len(_codes(proc, "warning")) == 1


@pytest.mark.parametrize(("step", "red"), [(599, False), (600, True)])
def test_budget_step_fails_a_compare_step_at_its_600_second_ceiling(
    tmp_path: Path, step: int, red: bool
) -> None:
    # 14000 cells give shard 1 1000, so 600 s is 600 ms/cell, under the per-cell fail.
    proc = _budget(tmp_path, step=step, matrix="14000", shard="1")
    assert (proc.returncode != 0, bool(_codes(proc, "error"))) == (red, red), proc
    if red:
        assert _codes(proc, "error") == [
            (
                "::error::CI-A11Y-007 VR shard 1 compare step took 600 s, at or over its 600 s "
                "ceiling (docs/ci-runbook.md)"
            )
        ]


@pytest.mark.parametrize(("step", "red"), [(59, False), (60, True)])
def test_budget_step_passes_a_compare_step_under_its_60_second_floor(
    tmp_path: Path, step: int, red: bool
) -> None:
    proc = _budget(
        tmp_path, step=step, matrix="14", shard="1"
    )  # 1 cell: 59000+ ms/cell
    assert (proc.returncode != 0, bool(_codes(proc, "error"))) == (red, red), proc
    if not red:
        assert not _codes(proc, "warning")


@pytest.mark.parametrize(("step", "warned"), [(449, False), (450, True)])
def test_budget_step_warns_from_450_ms_a_cell(
    tmp_path: Path, step: int, warned: bool
) -> None:
    # 14000 cells give shard 1 1000, so the step's seconds are ms/cell.
    proc = _budget(tmp_path, step=step, matrix="14000", shard="1")
    assert proc.returncode == 0 and not _codes(proc, "error"), proc
    assert len(_codes(proc, "warning")) == (1 if warned else 0)


@pytest.mark.parametrize("stamp", ["abc\n", "\n", "12 3\n"])
def test_budget_step_fails_closed_with_a_garbled_stamp(
    tmp_path: Path, stamp: str
) -> None:
    proc = _budget(tmp_path, step=128, end_stamp=stamp)
    assert proc.returncode == 1, proc
    errors = _codes(proc, "error")
    assert len(errors) == 1 and errors[0].startswith(
        "::error::CI-A11Y-007 VR shard 3 has a garbled time stamp"
    )


@pytest.mark.parametrize(("overhead", "end_stamp"), [(-5, None), (81, "1000\n")])
def test_budget_step_fails_closed_with_stamps_out_of_order(
    tmp_path: Path, overhead: int, end_stamp: str | None
) -> None:
    proc = _budget(tmp_path, step=128, overhead=overhead, end_stamp=end_stamp)
    assert proc.returncode == 1, proc
    errors = _codes(proc, "error")
    assert len(errors) == 1 and errors[0].startswith(
        "::error::CI-A11Y-007 VR shard 3 has time stamps out of order"
    )


def test_compare_and_budget_steps_run_in_bash_so_pipefail_keeps_the_exit_code() -> None:
    assert _step(RUN).get("shell") == "bash"
    assert _step(BUDGET).get("shell") == "bash"


@pytest.mark.parametrize("matrix", [None, "0"])
def test_budget_step_fails_closed_with_no_cell_count(
    tmp_path: Path, matrix: str | None
) -> None:
    proc = _budget(tmp_path, step=128, matrix=matrix)
    assert proc.returncode == 1, proc
    assert _codes(proc, "error") == [
        (
            "::error::CI-A11Y-007 VR shard 3 has no cell count: the compare step's log has no "
            '"VR matrix: N cells" line (docs/ci-runbook.md)'
        )
    ]


def test_budget_step_fails_closed_with_no_compare_log(tmp_path: Path) -> None:
    (tmp_path / "vr-compare.log").unlink(missing_ok=True)
    (tmp_path / "vr-start").write_text("1000\n")
    (tmp_path / "vr-step-start").write_text("1081\n")
    (tmp_path / "vr-step-end").write_text("1209\n")
    proc, _ = _bash(tmp_path, _step(BUDGET)["run"], SHARD="3", TOTAL="14")
    assert (
        proc.returncode == 1
        and "::error::CI-A11Y-007 VR shard 3 has no cell count" in proc.stdout
    )


@pytest.mark.parametrize(("overhead", "warned"), [(180, False), (181, True)])
def test_budget_step_warns_once_on_setup_over_180_seconds_but_never_fails(
    tmp_path: Path, overhead: int, warned: bool
) -> None:
    proc = _budget(tmp_path, step=128, overhead=overhead)
    assert proc.returncode == 0 and not _codes(proc, "error"), proc
    expected = (
        f"::warning::CI-A11Y-007 VR shard 3 spent {overhead} s before the compare step, over "
        "180 s (setup on a slow runner pool, not cells; never fails)"
    )
    assert _codes(proc, "warning") == ([expected] if warned else [])
