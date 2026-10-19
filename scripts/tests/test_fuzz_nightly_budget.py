"""#415 (E17-X02) slice k: the nightly fuzz time-boxes every WS fuzz target, with a weekend run.

`fuzz-nightly.yml` runs every `fuzz`-marked test of services/api/tests/unit/ws in its python job and
both `test:fuzz` projects in its typescript job. `CV_FUZZ_BUDGET_SECONDS` is how long a job fuzzes
for: 30 minutes on a night from Sunday to Friday, 3 hours on Saturday (decision D2 of #415), whose
cron (or the `weekend` input of a manual run) also picks the timeout that goes with it. Each fuzz
step splits the budget evenly over its targets and hands the share to the suites as
`CV_FUZZ_SECONDS`, how long each target runs: the python step over the fuzz tests pytest collects,
the typescript step over its projects. Static checks of the workflow and of the targets it runs,
then each fuzz step as written, against stand-ins for its launcher."""

from __future__ import annotations

import ast
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
DOC: dict[Any, Any] = yaml.safe_load(
    (ROOT / ".github" / "workflows" / "fuzz-nightly.yml").read_text(encoding="utf-8")
)  # PyYAML reads the key `on` as True
API_TESTS = ROOT / "services" / "api" / "tests"
WS_TESTS = API_TESTS / "unit" / "ws"
JOBS = ("python", "typescript")
BUDGET = {False: 30 * 60, True: 3 * 60 * 60}  # seconds a job fuzzes for: a night's, the weekend's
LOCAL = not os.environ.get("CI")  # off CI a missing tool skips a test; on CI it fails the test
#: `(github.event.schedule == '<cron>' || inputs.weekend) && <long> || <short>`: GitHub's `&&` and
#: `||` return an operand, so a scheduled run of that cron or a manual one with the input takes
#: <long>, any other run <short>. A number is bare in `timeout-minutes`, quoted in an env value.
SELECTOR = re.compile(
    r"\$\{\{ \(github\.event\.schedule == '([^']+)' \|\| inputs\.weekend\)"
    r" && '?(\d+)'? \|\| '?(\d+)'? \}\}"
)
needs_od_tr = pytest.mark.skipif(
    LOCAL and not all(map(shutil.which, ("od", "tr"))), reason="od, tr"
)


def _arms(value: object) -> tuple[str, int, int]:
    found = SELECTOR.fullmatch(str(value))
    assert found, f"not the selector this file reads: {value!r}"
    return found[1], int(found[2]), int(found[3])


def _pick(value: object, schedule: str = "", weekend: bool = False) -> int:
    """What the expression gives a run started by the cron `schedule`, or by hand (`weekend`)."""
    cron, long, short = _arms(value)
    return long if schedule == cron or weekend else short


def _days(cron: str) -> set[int]:
    days: set[int] = set()
    for part in cron.split()[4].split(","):
        first, _, last = part.partition("-")
        days |= set(range(int(first), int(last or first) + 1))
    return days


def _python_targets() -> dict[str, list[str]]:
    """File -> its tests marked `fuzz` and not `flaky`, which the python job's `-m` selects."""
    found: dict[str, list[str]] = {}
    for path in sorted(WS_TESTS.glob("*.py")):
        names = []
        for node in ast.parse(path.read_text(encoding="utf-8")).body:
            if isinstance(node, ast.FunctionDef):
                marks = {ast.unparse(d) for d in node.decorator_list}
                if "pytest.mark.fuzz" in marks and "pytest.mark.flaky" not in marks:
                    names.append(node.name)
        if names:
            found[path.name] = names
    return found


def _fuzz_projects() -> list[str]:
    """The workspace packages with a `test:fuzz` script."""
    manifests = sorted([*ROOT.glob("apps/*/package.json"), *ROOT.glob("packages/*/package.json")])
    packages = [json.loads(m.read_text(encoding="utf-8")) for m in manifests]
    return [p["name"] for p in packages if "test:fuzz" in p.get("scripts", {})]


def _fuzz(job: str) -> dict[str, Any]:
    steps: list[dict[str, Any]] = DOC["jobs"][job]["steps"]
    (step,) = [s for s in steps if "/dev/urandom" in s.get("run", "")]
    return step


def _run(
    job: str, work: Path, weekend: bool = False, targets: int = 9, fail: str = ""
) -> tuple[int, list[list[str]], list[list[str]]]:
    """The job's fuzz step as written, its launcher a stand-in: for a `--collect-only` call it
    lists `targets` fuzz tests and records the arguments; else it records the share it saw and the
    arguments, and fails when they name `fail`. The exit code, each recorded call as
    [share, *args] and each collect call as its arguments."""
    calls, stub = work / "calls", work / "bin" / {"python": "uv", "typescript": "pnpm"}[job]
    stub.parent.mkdir()
    stub.write_text(
        "#!/bin/sh\n"
        'case "$*" in *--collect-only*)\n'
        '  for i in $(seq 1 "$STUB_TARGETS"); do echo "tests/unit/ws/t.py::test_$i"; done\n'
        '  for a in "$@"; do printf "%s|" "$a" >> "$COLLECTS"; done; echo >> "$COLLECTS"\n'
        '  echo; echo "$STUB_TARGETS/3607 tests collected (3598 deselected) in 1.00s"; exit 0;;\n'
        "esac\n"
        '{ printf %s "$CV_FUZZ_SECONDS"; for a in "$@"; do printf "|%s" "$a"; done; echo; }'
        f' >> "{calls}"\n[ -z "$STUB_FAIL" ] || case "$*" in *"$STUB_FAIL"*) exit 1;; esac\n',
        encoding="utf-8",
    )
    stub.chmod(0o755)
    budget = _pick(DOC["env"]["CV_FUZZ_BUDGET_SECONDS"], weekend=weekend)
    env = {**os.environ, "CV_FUZZ_BUDGET_SECONDS": str(budget), "STUB_FAIL": fail}
    env["COLLECTS"] = str(work / "collects")
    env |= {"STUB_TARGETS": str(targets), "PATH": f"{stub.parent}{os.pathsep}{os.environ['PATH']}"}
    done = subprocess.run(  # noqa: S603 -- fixed argv: bash and a workflow step's own text (#415)
        ["bash", "-e", "-c", _fuzz(job)["run"]],  # noqa: S607 -- bash from PATH, as the runner does
        cwd=work,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert (done.stdout, done.stderr) == ("", "")  # the step prints nothing, whatever the suites do

    def read(path: Path) -> list[list[str]]:
        lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
        return [line.rstrip("|").split("|") for line in lines]

    return done.returncode, read(calls), read(work / "collects")


def test_the_python_job_selects_every_fuzz_marked_test_of_the_ws_folder() -> None:
    assert set(_python_targets()) == {"test_cvwb_fuzz.py", "test_ws_parser_fuzz.py"}  # both suites
    # a fuzz test of another folder named `ws` would never run: it needs this job's path
    strays = [
        path.relative_to(ROOT).as_posix()
        for path in API_TESTS.rglob("*.py")
        if "ws" in path.relative_to(API_TESTS).parts[:-1]
        and WS_TESTS not in path.parents
        and "mark.fuzz" in path.read_text(encoding="utf-8")
    ]
    assert strays == []


def test_the_budget_is_set_once_and_the_run_size_stays_its_default() -> None:
    jobs = DOC["jobs"]
    envs = [DOC["env"], *(job.get("env", {}) for job in jobs.values())]
    envs += [step.get("env", {}) for job in jobs.values() for step in job["steps"]]
    assert [e for e in envs if "CV_FUZZ_BUDGET_SECONDS" in e] == [DOC["env"]]
    # the share is the fuzz step's to derive, from the budget and the targets it finds
    assert not [e for e in envs if "CV_FUZZ_SECONDS" in e]
    # a target stops at the first run that ends past its share: a run of 20 000 examples would
    # overshoot it by minutes, so nothing sets the run size and a run is the default 200
    assert not [e for e in envs if "CV_FUZZ_EXAMPLES" in e]
    for weekend, seconds in BUDGET.items():
        assert _pick(DOC["env"]["CV_FUZZ_BUDGET_SECONDS"], weekend=weekend) == seconds


@needs_od_tr
@pytest.mark.parametrize("weekend", BUDGET)
def test_the_python_step_splits_the_budget_over_the_fuzz_tests_it_collects(
    weekend: bool, tmp_path: Path
) -> None:
    real = sum(len(tests) for tests in _python_targets().values())
    assert real > 1  # an empty scan proves nothing
    for i, targets in enumerate((real, real + 1, 1)):  # the tests as they are, one more, one
        work = tmp_path / str(i)
        work.mkdir()
        code, calls, collects = _run("python", work, weekend, targets)
        (call,), (collect,) = calls, collects  # one pytest run, and one count of what it runs
        assert code == 0
        assert call[1:6] == ["run", "pytest", "tests/unit/ws", "-m", "fuzz and not flaky"]
        assert [a for a in collect if a not in ("--collect-only", "-q")] == call[1:]
        assert int(call[0]) == BUDGET[weekend] // targets, targets
    work = tmp_path / "none"  # nothing collected: the whole budget, and pytest fails the job itself
    work.mkdir()
    assert _run("python", work, weekend, 0)[1][0][0] == str(BUDGET[weekend])


@needs_od_tr
@pytest.mark.parametrize("weekend", BUDGET)
def test_the_typescript_step_runs_each_project_on_an_even_share(
    weekend: bool, tmp_path: Path
) -> None:
    projects = _fuzz_projects()
    assert len(projects) > 1  # an empty scan proves nothing
    code, calls, _ = _run("typescript", tmp_path, weekend)
    assert code == 0
    assert sorted(call[1:] for call in calls) == sorted(
        ["--filter", name, "test:fuzz"] for name in projects
    )
    assert {int(call[0]) for call in calls} == {BUDGET[weekend] // len(projects)}


@needs_od_tr
def test_a_failing_project_still_lets_the_other_run_and_fails_the_step(tmp_path: Path) -> None:
    for i, failing in enumerate(_fuzz_projects()):
        work = tmp_path / str(i)
        work.mkdir()
        code, calls, _ = _run("typescript", work, fail=failing)
        assert code == 1 and len(calls) == len(_fuzz_projects()), failing


@pytest.mark.parametrize("job", JOBS)
def test_each_timeout_covers_the_budget_with_setup_headroom(job: str) -> None:
    for weekend, seconds in BUDGET.items():
        timeout = _pick(DOC["jobs"][job]["timeout-minutes"], weekend=weekend)
        assert seconds // 60 + 15 <= timeout <= seconds // 60 + 60, (weekend, timeout)


def test_saturday_runs_the_weekend_budget_and_each_other_night_the_nightly_one() -> None:
    crons = [entry["cron"] for entry in DOC[True]["schedule"]]
    (saturday,) = [cron for cron in crons if _days(cron) == {6}]
    nights = [cron for cron in crons if cron != saturday]
    days = sorted(day for cron in nights for day in _days(cron))
    assert days == list(range(6))  # Sunday to Friday, one run a night
    weekend = DOC[True]["workflow_dispatch"]["inputs"]["weekend"]
    assert (weekend["type"], weekend["default"]) == ("boolean", False)  # a tick, never text
    selectors = [DOC["env"]["CV_FUZZ_BUDGET_SECONDS"]]
    selectors += [DOC["jobs"][job]["timeout-minutes"] for job in JOBS]
    for value in selectors:
        cron, long, short = _arms(value)
        assert cron == saturday
        assert [_pick(value, schedule=night) for night in nights] == [short] * len(nights)
        assert _pick(value, schedule=saturday) == long
        assert (_pick(value, weekend=True), _pick(value)) == (long, short)  # by hand: ticked or not
