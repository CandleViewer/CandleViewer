"""#399 R4: the dispatch-only memory diagnosis workflow keeps the properties its header names.

Nothing else runs it: it is dispatched by hand, one leg at a time, on the self-hosted bench runner.
These pin what the header claims (dispatch only, read-only permissions, actions pinned by SHA, no
token kept by the checkout, the leg's input through env, the concurrency group shared with the 24 h
full pack, legs as memdiag names them) and run the leg step under `bash -e` with a stand-in `uv`
that records its arguments and the allocator environment it was started with.
"""

from __future__ import annotations

import ast
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
WORKFLOW = ROOT / ".github" / "workflows" / "perf-bars-memdiag.yml"
PACK = ROOT / ".github" / "workflows" / "perf-ingestion-nightly.yml"
MEMDIAG = ROOT / "services" / "api" / "bench" / "ingestion" / "memdiag.py"
ALLOCATOR = (
    "PYTHONMALLOC",
    "PYTHONTRACEMALLOC",
    "GLIBC_TUNABLES",
    "MALLOC_ARENA_MAX",
    "MALLOC_MMAP_THRESHOLD_",  # the knob under test, the likeliest inherited one
)
FAKE_UV = f"""import json, os, sys
seen = {{k: os.environ[k] for k in {ALLOCATOR!r} if k in os.environ}}
with open(os.environ["UV_LOG"], "a", encoding="utf-8") as fh:
    fh.write(json.dumps([sys.argv[1:], seen]) + "\\n")
"""
GROUP = {"group": "cv-bench-01", "cancel-in-progress": False}


def _doc(path: Path = WORKFLOW) -> dict[Any, Any]:
    doc: dict[Any, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
    return doc


def _leg_step() -> dict[str, Any]:
    return next(s for s in _doc()["jobs"]["leg"]["steps"] if s.get("id") == "leg")


def _memdiag_legs() -> list[str]:
    """`memdiag.LEG_ENV`'s keys, read from the source (the bench needs the API's dependencies)."""
    for node in ast.walk(ast.parse(MEMDIAG.read_text(encoding="utf-8"))):
        if (
            isinstance(node, ast.AnnAssign)
            and getattr(node.target, "id", "") == "LEG_ENV"
        ):
            assert isinstance(node.value, ast.Dict)
            return [k.value for k in node.value.keys if isinstance(k, ast.Constant)]
    raise AssertionError("memdiag.LEG_ENV not found")


def test_dispatch_only_read_only_pinned_and_one_soak_at_a_time_on_the_bench_runner() -> (
    None
):
    doc = _doc()
    assert set(doc[True]) == {
        "workflow_dispatch"
    }  # YAML 1.1 reads the `on` key as True
    assert doc["permissions"] == {"contents": "read"}
    leg = doc[True]["workflow_dispatch"]["inputs"]["leg"]
    assert leg["type"] == "choice" and leg["options"] == _memdiag_legs() == [
        "default",
        "tracemalloc",
        "malloc",
        "mmap128k",
    ]
    job = doc["jobs"]["leg"]
    assert job["runs-on"] == ["self-hosted", "Linux", "X64", "bench"]
    assert job["env"] == {
        "CV_ENV": "test",
        "CV_BENCH_MACHINE_PROFILE": "bench-runner",
        "PYTHONUNBUFFERED": "1",
    }  # the pack's profile: reading 2 is read beside the legs
    pack_env = _doc(PACK)["jobs"]["perf-pack-full"]["env"]
    assert (
        job["env"]["CV_BENCH_MACHINE_PROFILE"] == pack_env["CV_BENCH_MACHINE_PROFILE"]
    )
    # every leg runs at one commit: the first step refuses a dispatch from anything but a tag
    first = job["steps"][0]
    assert set(first) == {"name", "if", "run"} and "exit 1" in first["run"]
    assert (
        first["if"]
        == "github.ref_type != 'tag' || !startsWith(github.ref_name, 'bench/')"
    )
    # nothing between the refusal and the leg may run past it
    assert all(
        "if" not in s and "continue-on-error" not in s for s in job["steps"][1:-2]
    )
    assert (
        job["concurrency"]
        == GROUP
        == _doc(PACK)["jobs"]["perf-pack-full"]["concurrency"]
    )
    uses = [s["uses"] for s in job["steps"] if "uses" in s]
    assert uses and all(re.fullmatch(r"[\w.-]+/[\w.-]+@[0-9a-f]{40}", u) for u in uses)
    checkout = next(
        s for s in job["steps"] if s.get("uses", "").startswith("actions/checkout@")
    )
    assert checkout["with"] == {"persist-credentials": False}
    assert _leg_step()["env"] == {"LEG": "${{ inputs.leg }}"}
    # no input is interpolated into a script or a step title
    assert all("${{" not in s.get("run", "") for s in job["steps"])
    assert all("inputs." not in s.get("name", "") for s in job["steps"])
    # every uv call installs from the hash-locked uv.lock, never a fresh resolve (C-12.3)
    uv = [s["run"] for s in job["steps"] if s.get("run", "").lstrip().startswith("uv ")]
    leg_run = _leg_step()["run"]
    assert len(uv) == 2 and all(" --frozen " in r for r in [*uv, leg_run])


def test_a_stopped_leg_is_still_judged_and_uploaded_inside_the_job_timeout() -> None:
    """The leg reports at its 22 h deadline (wall time) and exits 1; the job's own timeout
    (never the 360 min default) leaves room for the judge and the upload, which run anyway.
    """
    job = _doc()["jobs"]["leg"]
    assert 22 * 60 < job["timeout-minutes"] <= 24 * 60
    assert "--deadline-h 22" in _leg_step()["run"]
    assert '"$RUNNER_TEMP/memdiag/$LEG"' in _leg_step()["run"]
    assert any(s.get("id") == "sync" for s in job["steps"])
    judge = next(s for s in job["steps"] if " judge " in s.get("run", ""))
    assert judge["if"] == "always() && steps.sync.outcome == 'success'"
    assert judge["run"].rstrip().endswith('judge "$RUNNER_TEMP/memdiag"')
    upload = job["steps"][-1]
    assert upload["uses"].startswith("actions/upload-artifact@")
    assert upload["if"] == "always()" and upload["with"] == {
        "name": "memdiag-${{ inputs.leg }}",
        "path": "${{ runner.temp }}/memdiag/",
        "retention-days": 30,
        "if-no-files-found": "error",
    }


def _leg(tmp_path: Path, leg: str) -> tuple[int, list[Any]]:
    bash = shutil.which("bash") or ""
    if not bash:  # CI runs these fail-closed proofs
        (pytest.fail if os.environ.get("CI") else pytest.skip)("bash runs the step")
    (tmp_path / "bin").mkdir()
    uv = tmp_path / "bin" / "uv"
    uv.write_text(f"#!{sys.executable}\n{FAKE_UV}", encoding="utf-8")
    uv.chmod(0o755)
    log = tmp_path / "uv.log"
    done = subprocess.run(
        [bash, "-e", "-c", _leg_step()["run"]],
        cwd=tmp_path,
        env={
            "PATH": f"{tmp_path / 'bin'}{os.pathsep}{os.environ.get('PATH', '')}",
            "UV_LOG": str(log),
            "RUNNER_TEMP": str(tmp_path / "t"),
            "LEG": leg,
            **{
                k: "planted" for k in ALLOCATOR
            },  # what the runner's own environment might hold
        },
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    calls = [
        json.loads(x) for x in (log.read_text().splitlines() if log.exists() else [])
    ]
    return done.returncode, calls


@pytest.mark.parametrize(
    ("leg", "extra", "env"),
    [
        ("default", [], {}),
        ("tracemalloc", ["--hours", "12", "--tracemalloc", "6"], {}),
        ("malloc", [], {"PYTHONMALLOC": "malloc"}),
        ("mmap128k", [], {"MALLOC_MMAP_THRESHOLD_": "131072"}),
    ],
)
def test_each_leg_starts_with_its_own_allocator_environment_and_nothing_else(
    tmp_path: Path, leg: str, extra: list[str], env: dict[str, str]
) -> None:
    code, calls = _leg(tmp_path, leg)
    out = f"{tmp_path}/t/memdiag/{leg}"
    head = ["run", "--frozen", "python", "-m", "bench.ingestion.memdiag", "leg"]
    argv = [*head, "--label", leg, "--out-dir", out, "--deadline-h", "22", *extra]
    assert code == 0 and calls == [[argv, env]]


@pytest.mark.parametrize("leg", ["", "arena2", "default; id", "$(id)"])
def test_anything_but_a_leg_is_refused_before_the_runner_starts(
    tmp_path: Path, leg: str
) -> None:
    code, calls = _leg(tmp_path, leg)
    assert code == 2 and calls == []
