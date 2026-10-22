"""#568: the dispatch-only WS load workflow keeps the properties its header names.

Nothing else runs it: it is dispatched by hand on the self-hosted bench runner, so these are the
checks it gets. They pin what the header claims (dispatch only, read-only permissions, inputs reach
scripts through env, actions pinned by SHA, no token kept by the checkout, no session handle in the
artifact, k6 pinned by sha256 twice, a first step that refuses while a 24 h soak runs) and run the
load step under `bash -e`, as the runner does, with a stand-in `uv`: a red run must not end the loop,
and the step exits with the worst code of its runs.
"""

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
WORKFLOW = ROOT / ".github" / "workflows" / "perf-ws-load.yml"
SOAK = ROOT / ".github" / "workflows" / "perf-ingestion-nightly.yml"
#: The bars soak's memory legs (job `leg`, up to 23 h on the same runner); not on main yet.
MEMDIAG = ROOT / ".github" / "workflows" / "perf-bars-memdiag.yml"
#: A stand-in `uv`: logs its arguments, one JSON list per call, and exits with the next code of
#: UV_EXITS (comma separated; the last one repeats).
FAKE_UV = """import json, os, sys
log, codes = os.environ["UV_LOG"], os.environ["UV_EXITS"].split(",")
calls = len(open(log).read().splitlines()) if os.path.exists(log) else 0
with open(log, "a", encoding="utf-8") as fh:
    fh.write(json.dumps(sys.argv[1:]) + "\\n")
sys.exit(int(codes[min(calls, len(codes) - 1)]))
"""


def _doc(path: Path = WORKFLOW) -> dict[Any, Any]:
    doc: dict[Any, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
    return doc


def _steps() -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = _doc()["jobs"]["ws-load"]["steps"]
    return steps


def _uses(prefix: str) -> dict[str, Any]:
    (step,) = [s for s in _steps() if str(s.get("uses", "")).startswith(prefix)]
    return step


def _named(prefix: str) -> dict[str, Any]:
    (step,) = [s for s in _steps() if str(s.get("name", "")).startswith(prefix)]
    return step


def test_it_is_dispatch_only_with_read_only_permissions_on_the_bench_runner() -> None:
    doc = _doc()
    assert set(doc[True]) == {
        "workflow_dispatch"
    }  # YAML 1.1 reads the key `on` as True
    assert doc["permissions"] == {"actions": "read", "contents": "read"}
    assert doc["concurrency"] == {"group": "perf-ws-load", "cancel-in-progress": False}
    assert list(doc["jobs"]) == ["ws-load"]
    job = doc["jobs"]["ws-load"]
    assert job["runs-on"] == ["self-hosted", "Linux", "X64", "bench"]
    assert (
        job["env"]["CV_BENCH_MACHINE_PROFILE"]
        == _soak_job()["env"]["CV_BENCH_MACHINE_PROFILE"]
    )
    assert job["env"]["K6_NO_USAGE_REPORT"] == "true"
    assert job["env"]["K6_AUTO_EXTENSION_RESOLUTION"] == "false"


def test_the_header_claims_no_more_than_the_loopback_bind_and_no_outbound_client() -> (
    None
):
    """The runner has egress (it downloads k6), so the header may not say that no exchange is
    reachable: what holds is the loopback bind and that the fixture builds no outbound client.
    """
    top = WORKFLOW.read_text(encoding="utf-8").split("\non:\n")[0]
    header = " ".join(line.removeprefix("#").strip() for line in top.splitlines())
    assert "no exchange is reachable" not in header
    assert "binds loopback only" in header
    assert "constructs no exchange or other outbound client" in header


def test_no_expression_reaches_a_script_and_every_action_is_pinned_by_sha() -> None:
    for step in _steps():
        assert "${{" not in step.get("run", ""), step.get(
            "name"
        )  # inputs go through env
        if "uses" in step:
            assert re.fullmatch(r"[\w./-]+@[0-9a-f]{40}", step["uses"]), step["uses"]


def test_the_checkout_keeps_no_token_and_the_artifact_holds_no_session_handle() -> None:
    assert _uses("actions/checkout@")["with"] == {"persist-credentials": False}
    paths = _uses("actions/upload-artifact@")["with"]["path"].split()
    assert "!ws-load/**/tokens.json" in paths and "!ws-load/**/bars/**" in paths


def _soak_job() -> dict[str, Any]:
    job: dict[str, Any] = _doc(SOAK)["jobs"]["perf-pack-full"]
    return job


def test_k6_is_pinned_by_sha256_twice_and_the_first_step_refuses_while_the_soak_runs() -> (
    None
):
    env = _doc()["jobs"]["ws-load"]["env"]
    assert env["K6_VERSION"] == "v2.3.0" and re.fullmatch(
        r"[0-9a-f]{64}", env["K6_SHA256"]
    )
    install = _named("Install the pinned k6")["run"]
    assert install.count("sha256sum -c") == 2 and "checksums.txt" in install
    guard = _steps()[0]["run"]  # the soak is the job this one must never overlap
    assert "perf-ingestion-nightly.yml" in guard and "perf-pack-full" in guard
    assert "exit 1" in guard and "in_progress" in guard and "queued" in guard
    assert (
        "bench" in _soak_job()["runs-on"]
    )  # the same runner, so the guard is the only fence
    assert MEMDIAG.name in guard and "(HTTP 404)" in guard
    if MEMDIAG.exists():  # until it lands, the API's 404 for it means none runs (below)
        assert "bench" in _doc(MEMDIAG)["jobs"]["leg"]["runs-on"]


#: A stand-in `gh api <path> --jq <filter>` answering GH_ANSWER (JSON): `fail` maps a workflow file
#: to [exit code, error line] (gh prints the error body, then that line), `runs` maps
#: "file:status" to run ids and `jobs` a run id to [name, status] pairs, counted as the step's
#: filter counts the queued or running jobs of the name it selects.
FAKE_GH = """import json, os, re, sys
path, jq = sys.argv[2], sys.argv[-1]
answer = json.loads(os.environ["GH_ANSWER"])
for wf, (code, line) in answer.get("fail", {}).items():
    if f"/workflows/{wf}/" in path:
        print('{"message": "error"}')
        sys.stderr.write(line + "\\n")
        sys.exit(code)
if path.endswith("/jobs"):
    name = re.search(r'\\.name == "([^"]+)"', jq).group(1)
    jobs = answer.get("jobs", {}).get(path.split("/")[-2], [])
    print(sum(n == name and s in ("queued", "in_progress") for n, s in jobs))
else:
    wf, status = re.search(r"workflows/([^/]+)/runs\\?status=(\\w+)", path).groups()
    print("\\n".join(map(str, answer.get("runs", {}).get(f"{wf}:{status}", []))))
"""
NOT_FOUND = [1, "gh: Not Found (HTTP 404)"]
LEGS, PACK = MEMDIAG.name, SOAK.name


def _guard(tmp_path: Path, answer: dict[str, Any]) -> subprocess.CompletedProcess[str]:
    """The guard step's script under `bash -e` with a stand-in `gh` that answers `answer`."""
    bash = shutil.which("bash") or ""
    if not bash:  # CI runs these fail-closed proofs
        (pytest.fail if os.environ.get("CI") else pytest.skip)("bash runs the step")
    gh = tmp_path / "gh"
    gh.write_text(f"#!{sys.executable}\n{FAKE_GH}", encoding="utf-8")
    gh.chmod(0o755)
    path = f"{tmp_path}{os.pathsep}{os.environ.get('PATH', '')}"
    return subprocess.run(
        [bash, "-e", "-c", _steps()[0]["run"]],
        cwd=tmp_path,
        env={"PATH": path, "GITHUB_REPOSITORY": "o/r", "GH_ANSWER": json.dumps(answer)},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def _held(wf: str, job: str, status: str) -> dict[str, Any]:
    """An answer in which `wf` has one run whose job `job` is `status`."""
    return {"runs": {f"{wf}:{status}": [7]}, "jobs": {"7": [[job, status]]}}


@pytest.mark.parametrize(
    ("answer", "code", "said"),
    [
        ({}, 0, ""),
        ({"fail": {LEGS: NOT_FOUND}}, 0, f"{LEGS}: not on this repository yet (HTTP 404)"),
        (_held(LEGS, "leg", "queued"), 1, f"{LEGS} (job leg)"),
        (_held(LEGS, "leg", "in_progress"), 1, f"{LEGS} (job leg)"),
        (_held(PACK, "perf-pack-full", "queued"), 1, f"{PACK} (job perf-pack-full)"),
        ({"fail": {LEGS: [1, "gh: Server Error (HTTP 500)"]}}, 1, "(HTTP 500)"),
        ({"fail": {PACK: NOT_FOUND}}, 1, "(HTTP 404)"),  # only the legs' workflow may be missing
    ],
)
def test_the_guard_refuses_while_either_soak_holds_the_runner_and_fails_closed_on_errors(
    tmp_path: Path, answer: dict[str, Any], code: int, said: str
) -> None:
    done = _guard(tmp_path, answer)
    assert done.returncode == code, done.stdout + done.stderr
    assert said in done.stdout + done.stderr


def test_the_follow_up_steps_test_the_run_count_they_need() -> None:
    gate, repro = _named("Regression gate")["if"], _named("Reproducibility")["if"]
    assert "steps.load.outputs.runs == '3'" in gate
    assert 'fromJSON(\'["2","3"]\'), steps.load.outputs.runs' in repro
    assert (
        "!= '1'" not in repro
    )  # true on an empty output, which a refused input leaves


def _load(
    tmp_path: Path, exits: str, **env: str
) -> tuple[subprocess.CompletedProcess[str], list[list[str]], str]:
    """The load step's script under `bash -e` with a stand-in `uv` that exits with `exits`."""
    bash = shutil.which("bash") or ""
    if not bash:  # CI runs these fail-closed proofs
        (pytest.fail if os.environ.get("CI") else pytest.skip)("bash runs the step")
    (tmp_path / "bin").mkdir()
    for name, body in (("uv", FAKE_UV), ("systemd-run", "import sys\nsys.exit(1)\n")):
        tool = tmp_path / "bin" / name
        tool.write_text(f"#!{sys.executable}\n{body}", encoding="utf-8")
        tool.chmod(0o755)
    outputs = tmp_path / "output"
    base = {"PROFILE": "A", "FLAG": "on", "RUNS": "3", "DURATION": "", "WS_PATH": "/ws"}
    done = subprocess.run(
        [bash, "-e", "-c", _named("WS load run")["run"]],
        cwd=tmp_path,
        env={
            "PATH": f"{tmp_path / 'bin'}{os.pathsep}{os.environ.get('PATH', '')}",
            "HOME": str(tmp_path),
            "UV_LOG": str(tmp_path / "uv.log"),
            "UV_EXITS": exits,
            "GITHUB_WORKSPACE": str(tmp_path),
            "GITHUB_OUTPUT": str(outputs),
            **base,
            **env,
        },
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    log = tmp_path / "uv.log"
    calls = [
        json.loads(x) for x in (log.read_text().splitlines() if log.exists() else [])
    ]
    return done, calls, outputs.read_text() if outputs.exists() else ""


@pytest.mark.parametrize(
    ("exits", "code"), [("1,0,0", 1), ("0,2,1", 2), ("0,0,0", 0), ("2,2,2", 2)]
)
def test_a_red_run_does_not_end_the_loop_and_the_step_exits_with_the_worst_code(
    tmp_path: Path, exits: str, code: int
) -> None:
    done, calls, outputs = _load(tmp_path, exits)
    assert done.returncode == code, done.stderr
    assert (
        len(calls) == 3 and "runs=3" in outputs
    )  # runs 2 and 3 ran after run 1 failed
    assert all(
        c[-2:] == ["--ws-path", "/ws"] for c in calls
    )  # every run is told the path
    assert [c[c.index("--out-dir") + 1] for c in calls] == [
        f"{tmp_path}/ws-load/run-{i}" for i in (1, 2, 3)
    ]


def test_the_prefix_the_results_pr_dispatches_reaches_every_run(tmp_path: Path) -> None:
    done, calls, _ = _load(tmp_path, "0", WS_PATH="/api/v1/ws")
    assert done.returncode == 0, done.stderr
    assert len(calls) == 3 and all(c[-2:] == ["--ws-path", "/api/v1/ws"] for c in calls)


@pytest.mark.parametrize(("profile", "runs"), [("selfcheck", "1"), ("W5", "1")])
def test_the_self_check_and_w5_run_once(
    tmp_path: Path, profile: str, runs: str
) -> None:
    done, calls, outputs = _load(tmp_path, "0", PROFILE=profile)
    assert done.returncode == 0, done.stderr
    assert len(calls) == 1 and f"runs={runs}" in outputs


@pytest.mark.parametrize(
    "bad",
    [
        {"WS_PATH": "/x"},
        {"WS_PATH": "/ws?a=b"},
        {"RUNS": "4"},
        {"FLAG": "maybe"},
        {"DURATION": "9;ls"},
    ],
)
def test_an_input_that_fails_validation_ends_the_step_before_uv_and_leaves_no_run_count(
    tmp_path: Path, bad: dict[str, str]
) -> None:
    done, calls, outputs = _load(tmp_path, "0", **bad)
    assert done.returncode == 2 and calls == [] and "runs=" not in outputs
