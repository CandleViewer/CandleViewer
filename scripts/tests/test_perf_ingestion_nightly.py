"""#399 R4: the full pack can run one scenario, and a stopped pack keeps its log and its reports.

The full pack ran 35 h on the bench runner and was cancelled with nothing logged and no report.
These pin what the workflow's header claims: Python output is unbuffered, a dispatch names one
`scenario` that reaches the runner through env and is checked first (a name with a scenario
file), and the reports are uploaded on a cancel too. The check and pack steps run under `bash -e`,
each in its working directory, with a stand-in `uv`.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "perf-ingestion-nightly.yml"
FAKE_UV = """import json, os, sys
with open(os.environ["UV_LOG"], "a", encoding="utf-8") as fh:
    fh.write(json.dumps(sys.argv[1:]) + "\\n")
"""
#: Scenario files no dispatch may name: an option, and a name too long for the pattern.
DECOYS = ("-h", "--record-baseline", "a" * 65)


def _doc() -> dict[Any, Any]:
    doc: dict[Any, Any] = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return doc


def _job() -> dict[str, Any]:
    job: dict[str, Any] = _doc()["jobs"]["perf-pack-full"]
    return job


def _step(sid: str) -> dict[str, Any]:
    return next(s for s in _job()["steps"] if s.get("id") == sid)


def test_unbuffered_output_and_the_scenario_input_through_env() -> None:
    doc = _doc()
    assert doc["env"]["PYTHONUNBUFFERED"] == "1"
    # YAML 1.1 reads the `on` key as True
    scenario = doc[True]["workflow_dispatch"]["inputs"]["scenario"]
    assert scenario["type"] == "string" and scenario["default"] == "all"
    for sid in ("scenario", "pack"):  # the check, then the pack it lets run (no `if:`)
        assert _step(sid)["env"] == {"SCENARIO": "${{ inputs.scenario }}"}
    assert "if" not in _step("pack")
    # no input is interpolated into a script or a step's title
    assert all("${{" not in s.get("run", "") for s in _job()["steps"])
    assert all("inputs." not in s.get("name", "") for s in _job()["steps"])
    # a refused name fails the check, not the pack, so no "pack failed" issue is filed
    assert _job()["outputs"]["failed"] == "${{ steps.pack.outcome == 'failure' }}"
    ids = [s.get("id") for s in _job()["steps"]]
    assert ids.index("scenario") < ids.index(
        "pack"
    )  # the check runs first, and must pass
    assert "continue-on-error" not in _step("scenario")
    upload = next(s for s in _job()["steps"] if "upload-artifact@" in s.get("uses", ""))
    assert upload["if"] == "always()"  # a cancelled pack still uploads what it wrote
    # ... from where the pack writes it: services/api + --out-dir bench/reports
    assert _step("pack")["working-directory"] == "services/api"
    assert "--out-dir bench/reports" in _step("pack")["run"]
    assert upload["with"]["path"] == "services/api/bench/reports/"


def _pack(
    tmp_path: Path, scenario: str, locale: str = "C.UTF-8"
) -> tuple[int, list[list[str]]]:
    """The check step, then the pack step if the check passed, each under `bash -e` in its
    working directory, in a checkout holding the scenario files `soak_bars` and
    `soak_bars_frozen` (the second as vw5's slice adds it), and decoys named like an option or
    too long, so that only the name pattern refuses those."""
    scenarios = tmp_path / "services" / "api" / "bench" / "ingestion" / "scenarios"
    scenarios.mkdir(parents=True)
    for name in ("soak_bars", "soak_bars_frozen", *DECOYS):
        (scenarios / f"{name}.json").write_text("{}", encoding="utf-8")
    bash = shutil.which("bash") or ""
    if not bash:  # CI runs these fail-closed proofs
        (pytest.fail if os.environ.get("CI") else pytest.skip)("bash runs the step")
    (tmp_path / "bin").mkdir()
    uv = tmp_path / "bin" / "uv"
    uv.write_text(f"#!{sys.executable}\n{FAKE_UV}", encoding="utf-8")
    uv.chmod(0o755)
    log = tmp_path / "uv.log"
    env = {
        "PATH": f"{tmp_path / 'bin'}{os.pathsep}{os.environ.get('PATH', '')}",
        "UV_LOG": str(log),
        "SCENARIO": scenario,
        "LC_ALL": locale,  # the runner's own locale may not be C
    }
    code = 0
    for sid in ("scenario", "pack"):
        step = _step(sid)
        cwd = tmp_path / step.get("working-directory", "")
        run = [bash, "-e", "-c", step["run"]]
        code = subprocess.run(run, cwd=cwd, env=env, timeout=60, check=False).returncode
        if code:
            break
    calls = [
        json.loads(x) for x in (log.read_text().splitlines() if log.exists() else [])
    ]
    return code, calls


@pytest.mark.parametrize("scenario", ["all", "soak_bars", "soak_bars_frozen"])
def test_a_scenario_name_reaches_the_runner_as_one_argument(
    tmp_path: Path, scenario: str
) -> None:
    code, calls = _pack(tmp_path, scenario)
    runner = ["run", "python", "-m", "bench.ingestion.runner", scenario]
    assert code == 0 and calls == [
        [*runner, "--profile", "full", "--out-dir", "bench/reports"]
    ]


@pytest.mark.parametrize(
    "scenario",
    [
        *(
            "",
            "soak_bars --record-baseline",
            "soak_bars;id",
            "$(id)",
            "../x",
            "ALL",
            "a\nb",
        ),
        *DECOYS,  # each has a scenario file: the name pattern alone refuses it
        "soak_barz",  # well formed, but no scenario has that name
    ],
)
def test_anything_but_a_name_is_refused_before_the_runner_starts(
    tmp_path: Path, scenario: str
) -> None:
    code, calls = _pack(tmp_path, scenario)
    assert code == 2 and calls == []


@pytest.mark.parametrize("scenario", ["soak_barß", "\uff41ll"])  # ß; a fullwidth "a"
def test_a_letter_outside_ascii_is_refused_whatever_the_runners_locale(
    tmp_path: Path, scenario: str
) -> None:
    # The proof needs a locale where [a-z] matches such a letter; skip, visibly, without one.
    probe = 'export LC_ALL=en_US.UTF-8; [[ "ß" =~ ^[a-z]$ ]]'
    if subprocess.run(
        [shutil.which("bash") or "bash", "-c", probe], check=False
    ).returncode:
        pytest.skip("no en_US.UTF-8 locale here, so [a-z] cannot match ß")
    code, calls = _pack(tmp_path, scenario, locale="en_US.UTF-8")  # matches [a-z] there
    assert code == 2 and calls == []
