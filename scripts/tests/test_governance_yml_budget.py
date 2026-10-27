"""#4666: the governance duration budget (E01-Q02) measures the suite, not the runner.

Each `governance-tests` shard and the `governance` job ended with a blocking budget step that
compared the job's wall time, checkout, installs and artifact transfers included, with
`BUDGET_MS=90000`, so runner contention failed green pull requests on the budget alone: on
2026-10-26 (run 40398652820) shard 1/6 failed at 101 s of job wall time, 66 s of it checkout and
14 s its pytest step. Each shard now budgets its pytest wall time (the pytest step's `pytest_ms`)
and `governance` its combine step (the combine step's `combine_ms`); the job wall time stays in
each summary as an informational row. #4693: `governance-checks` budgets its checks' own span
(the span step's `checks_ms`, from after its installs to its last report), not its job wall time,
which on run 40330181950 was 191 s with 171 s of it checkout.

The cases run the steps' own scripts as the runner does (`bash -e`), with the step outputs in the
environment and stand-ins for `python` and `date` first on PATH; the stand-in clock replays fixed
readings, so every time a step records or reports is exact. Provisioning latency passes, suite
growth still fails with the E01-Q02 error, so does a time too large for bash's integers, and a run
that recorded no time fails instead of passing unmeasured.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any, NamedTuple

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "governance.yml"
BUDGET = "Job duration budget (<=BUDGET_MS, E01-Q02)"
E01_Q02 = "(docs/plan/backlog/testplans/E01-governance-charter.md, E01-Q02)"
JOB_WALL = "job wall time (ms), informational"


class Measured(NamedTuple):
    """What a job's budget step judges: the variable it reads, its summary row, and the name the
    E01-Q02 error gives it."""

    env: str
    row: str
    noun: str


MEASURED = {
    "governance-tests": Measured(
        "PYTEST_MS", "pytest wall time (ms), budgeted", "pytest wall time"
    ),
    "governance": Measured("COMBINE_MS", "combine wall time (ms), budgeted", "combine wall time"),
    "governance-checks": Measured(
        "CHECKS_MS", "checks wall time (ms), budgeted", "checks wall time"
    ),
}

# The steps' `python`, stood in: logs each call, lists a two-file shard, exits as the case says.
FAKE_PYTHON = r"""
printf '%s\n' "$*" >> "$FAKE_LOG"
case "$1 ${2-} ${3-}" in
  "tools/ci/governance_shards.py "*) printf '%s\n' scripts/tests/test_{a,b}.py ;;
  "-m pytest "*) exit "${PYTEST_EXIT:-0}" ;;
  "-m coverage combine") exit "${COMBINE_EXIT:-0}" ;;
  "-m coverage report") exit "${REPORT_EXIT:-0}" ;;
  *) echo "unexpected python call: $*" >&2; exit 99 ;;
esac
"""

# The steps' `date`, stood in: each `date +%s%N` prints the next of the clock's readings, in order.
FAKE_DATE = r"""
[ "$*" = "+%s%N" ] || { echo "unexpected date call: $*" >&2; exit 99; }
reading=$(head -n 1 "$FAKE_CLOCK")
[ -n "$reading" ] || { echo "the stand-in clock has no reading left" >&2; exit 99; }
tail -n +2 "$FAKE_CLOCK" > "$FAKE_CLOCK.rest" && mv "$FAKE_CLOCK.rest" "$FAKE_CLOCK"
printf '%s\n' "$reading"
"""
T0 = 1_793_000_000_000_000_000  # the clock's first reading, ns: 2026-10-26 07:33:20Z
NS_PER_S = 1_000_000_000


class Ran(NamedTuple):
    """A step's script, run: its exit code, its log, the outputs it wrote to $GITHUB_OUTPUT, the
    job summary it wrote and the stand-in python's calls."""

    code: int
    log: str
    outputs: dict[str, str]
    summary: str
    calls: list[str]


def _steps(job: str) -> list[dict[str, Any]]:
    doc: dict[str, Any] = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    steps: list[dict[str, Any]] = doc["jobs"][job]["steps"]
    return steps


def _step(job: str, step_id: str) -> dict[str, Any]:
    (step,) = [step for step in _steps(job) if step.get("id") == step_id]
    return step


def _run(
    tmp_path: Path,
    job: str,
    step: dict[str, Any],
    values: Mapping[str, str | None],
    *,
    clock: tuple[int, ...],
    **fake: str,
) -> Ran:
    """Run `step`'s script as the runner does (`bash -e`) in a new directory under `tmp_path`,
    with the stand-in python and date first on PATH; the step's `date +%s%N` calls read `clock`.
    The step's literal env values come from the workflow and its `${{ }}` ones from `values`,
    which must name exactly those (None leaves one unset); a step output that was never written
    reads ''."""
    bash = shutil.which("bash")
    if bash is None:  # CI must run these fail-closed proofs
        if os.environ.get("CI"):
            pytest.fail("bash runs the step")
        pytest.skip("bash runs the step")
    declared = {key: str(value) for key, value in step.get("env", {}).items()}
    expressions = sorted(key for key, value in declared.items() if "${{" in value)
    assert sorted(values) == expressions, f"{step.get('name')}: feed exactly {expressions}"
    work = tmp_path / f"run{len(list(tmp_path.iterdir()))}"
    (work / "bin").mkdir(parents=True)
    for name, script in (("python", FAKE_PYTHON), ("date", FAKE_DATE)):
        stand_in = work / "bin" / name
        stand_in.write_text(f"#!{bash}{script}", encoding="utf-8")
        stand_in.chmod(0o755)
    (work / "clock").write_text("".join(f"{ns}\n" for ns in clock), encoding="utf-8")
    env = {
        **{key: value for key, value in {**declared, **values}.items() if value is not None},
        "PATH": f"{work / 'bin'}{os.pathsep}{os.environ.get('PATH', '')}",
        "HOME": str(work),
        "GITHUB_JOB": job,
        "GITHUB_OUTPUT": str(work / "output"),
        "GITHUB_STEP_SUMMARY": str(work / "summary"),
        "FAKE_LOG": str(work / "calls"),
        "FAKE_CLOCK": str(work / "clock"),
        **fake,
    }
    proc = subprocess.run(  # noqa: S603 - the workflow's own step text, in a scratch directory
        [bash, "-e", "-c", step["run"]],
        cwd=work,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    def read(name: str) -> str:
        path = work / name
        return path.read_text(encoding="utf-8") if path.exists() else ""

    outputs = dict(re.findall(r"^([^=\n]+)=(.*)$", read("output"), re.M))
    log, calls = proc.stdout + proc.stderr, read("calls").splitlines()
    return Ran(proc.returncode, log, outputs, read("summary"), calls)


def _budget(tmp_path: Path, job: str, *, job_s: int, measured: str = "") -> Ran:
    """`job`'s budget step, last in the job, after `job_s` seconds of job wall time and a run
    that recorded `measured` ms ('' when its step wrote no output)."""
    step = _steps(job)[-1]
    assert step["name"] == BUDGET, job
    values = {"START_NS": str(T0)}
    if job == "governance-tests":
        values |= {"SHARD": "3", "TOTAL": "6", "TEST_FILES": "21"}
    if job in MEASURED:
        values[MEASURED[job].env] = measured
    return _run(tmp_path, job, step, values, clock=(T0 + job_s * NS_PER_S,))


def _row(summary: str, metric: str) -> str:
    """The value in the summary table's one `metric` row."""
    (value,) = re.findall(rf"^\| {re.escape(metric)} \| (.*) \|$", summary, re.M)
    return str(value)


def _errors(log: str) -> list[str]:
    return [line for line in log.splitlines() if line.startswith("::error")]


def _notices(log: str) -> list[str]:
    return [line for line in log.splitlines() if line.startswith("::notice")]


def _notice(job: str, measured: str, job_s: int) -> str:
    """The notice `_budget`'s run of `job` writes once its time is measured: both times."""
    title = f"{job} shard 3/6 duration" if job == "governance-tests" else f"{job} duration"
    budgeted = f"{MEASURED[job].noun} {measured}ms (budget 90000ms)"
    return f"::notice title={title}::{budgeted}; job wall time {job_s * 1000}ms, not budgeted"


@pytest.mark.parametrize("job", list(MEASURED))
def test_budget_provisioning_latency_under_contention_passes_and_reports_both_times(
    tmp_path: Path, job: str
) -> None:
    # Scenario 1: a 60 s run in a job that checkout, installs and transfers stretched to 150 s.
    ran = _budget(tmp_path, job, job_s=150, measured="60000")
    assert ran.code == 0, ran.log
    assert _errors(ran.log) == []
    assert _notices(ran.log) == [_notice(job, "60000", job_s=150)]  # both times, on every run
    assert _row(ran.summary, MEASURED[job].row) == "60000"
    assert _row(ran.summary, JOB_WALL) == "150000"  # reported, not judged
    assert _row(ran.summary, "budget (ms)") == "90000"


@pytest.mark.parametrize("job", list(MEASURED))
@pytest.mark.parametrize("measured", ["90001", str(10**19)], ids=["just-past", "20-digits"])
def test_budget_run_past_budget_ms_fails_with_the_e01_q02_error(
    tmp_path: Path, job: str, measured: str
) -> None:
    # Scenario 2, the canary: a run past the budget fails the job, as the job's own time did. A
    # 20-digit time is past bash's 64-bit integers, so `[` errors on it, and the budget must read
    # that error as a fail: `if [ "$X" -gt "$BUDGET_MS" ]` reads it as false and passes the job.
    ran = _budget(tmp_path, job, job_s=95, measured=measured)
    assert ran.code == 1, ran.log
    assert _notices(ran.log) == [_notice(job, measured, job_s=95)]
    noun = MEASURED[job].noun
    assert _errors(ran.log) == [
        f"::error title={job} job over budget::{noun} {measured}ms exceeds 90000ms {E01_Q02}"
    ]


@pytest.mark.parametrize("job", list(MEASURED))
def test_budget_run_of_exactly_budget_ms_passes(tmp_path: Path, job: str) -> None:
    # The comparison itself is unchanged (past the budget fails, at it passes); the job's 100 s
    # are reported, not judged.
    ran = _budget(tmp_path, job, job_s=100, measured="90000")
    assert (ran.code, _errors(ran.log)) == (0, []), ran.log


@pytest.mark.parametrize("job", list(MEASURED))
@pytest.mark.parametrize("measured", ["", "n/a", "-1"], ids=["unwritten", "text", "negative"])
def test_budget_run_that_recorded_no_time_fails_instead_of_passing_unmeasured(
    tmp_path: Path, job: str, measured: str
) -> None:
    # A step that never ran, or stopped before it measured, wrote no output, which reads ''. The
    # budget fails such a value as unmeasured before its compare, on which `[` could only error.
    ran = _budget(tmp_path, job, job_s=0, measured=measured)
    assert ran.code == 1, ran.log
    assert _row(ran.summary, MEASURED[job].row) == (measured or "n/a")  # still reported
    assert _row(ran.summary, JOB_WALL) == "0"
    (error,) = _errors(ran.log)
    assert error.startswith(f"::error title={job} budget not measured::") and E01_Q02 in error


def test_checks_span_runs_from_after_the_installs_to_the_last_report() -> None:
    # #4693: the span opens once checkout, setup and the installs are done, and closes after the
    # last report and before the reports' upload, so provisioning and transfers stay unjudged.
    names = [str(step.get("name", step.get("uses", ""))) for step in _steps("governance-checks")]
    ids = [step.get("id") for step in _steps("governance-checks")]
    opened, closed = ids.index("checks_start"), ids.index("checks_span")
    assert names[opened - 1].startswith("Install check dependencies")
    assert names[closed - 1] == "Generate backlog per-epic summary (artefact)"
    assert names[closed + 1].startswith("actions/upload-artifact@")
    assert names[closed + 2 :] == [BUDGET]  # the budget step stays last
    last = _steps("governance-checks")[-1]
    assert last["env"]["CHECKS_MS"] == "${{ steps.checks_span.outputs.checks_ms }}"
    assert 'if ! [ "$CHECKS_MS" -le "$BUDGET_MS" ]; then' in last["run"]


@pytest.mark.parametrize(
    ("start", "outputs"),
    [
        pytest.param(str(T0), {"checks_ms": "42500"}, id="measured"),
        pytest.param(None, {}, id="never-started"),
        pytest.param("n/a", {}, id="not-a-time"),
    ],
)
def test_checks_span_step_records_its_wall_time_only_from_a_measured_start(
    tmp_path: Path, start: str | None, outputs: dict[str, str]
) -> None:
    # 42.5 s on the clock since the span opened; a span that never opened writes nothing, which
    # the budget step then fails as unmeasured, and the span step itself never fails the job.
    step = _step("governance-checks", "checks_span")
    assert step["if"] == "always()"
    ran = _run(
        tmp_path,
        "governance-checks",
        step,
        {"START_NS": start},
        clock=(T0 + 42_500_000_000,),
    )
    assert ran.code == 0, ran.log
    assert ran.outputs == outputs


def test_budget_aggregate_reads_the_combine_steps_own_time() -> None:
    steps = _steps("governance")
    assert [step.get("id") for step in steps].count("combine") == 1
    last = steps[-1]
    assert last["env"]["COMBINE_MS"] == "${{ steps.combine.outputs.combine_ms }}"
    assert 'if ! [ "$COMBINE_MS" -le "$BUDGET_MS" ]; then' in last["run"]


@pytest.mark.parametrize("pytest_exit", [0, 1], ids=["green", "red"])
def test_pytest_step_records_its_wall_time_whether_or_not_the_tests_pass(
    tmp_path: Path, pytest_exit: int
) -> None:
    # The shard budget's measurement, taken around the pytest call alone: 14.25 s on the clock.
    step = _step("governance-tests", "pytest")
    values = {"COVERAGE_FILE": "coverage-shard-3", "SHARD": "3", "TOTAL": "6"}
    clock = (T0, T0 + 14_250_000_000)
    ran = _run(
        tmp_path, "governance-tests", step, values, clock=clock, PYTEST_EXIT=str(pytest_exit)
    )
    assert ran.code == pytest_exit, ran.log
    assert ran.outputs == {"pytest_ms": "14250", "test_files": "2"}
    assert [call.split()[:2] for call in ran.calls] == [
        ["tools/ci/governance_shards.py", "3"],
        ["-m", "pytest"],
    ]


@pytest.mark.parametrize(
    ("shard_files", "combine_exit", "report_exit", "code", "verbs"),
    [
        pytest.param(6, 0, 0, 0, ["combine", "report"], id="combined-at-or-over-85"),
        pytest.param(6, 0, 2, 2, ["combine", "report"], id="under-85-still-fails"),
        pytest.param(6, 1, 0, 1, ["combine"], id="combine-failed-no-report"),
        pytest.param(5, 0, 0, 1, [], id="a-shard-missing-refused-first"),
    ],
)
def test_combine_step_records_its_wall_time_on_every_exit_and_keeps_its_gate(
    tmp_path: Path,
    shard_files: int,
    combine_exit: int,
    report_exit: int,
    code: int,
    verbs: list[str],
) -> None:
    # The aggregate budget's measurement, 1.951 s on the clock; the 85% gate's exit status passes
    # through untouched.
    coverage = tmp_path / "coverage"
    coverage.mkdir()
    for shard in range(1, shard_files + 1):
        (coverage / f"coverage-shard-{shard}").write_text("", encoding="utf-8")
    ran = _run(
        tmp_path,
        "governance",
        _step("governance", "combine"),
        {"COV_DIR": str(coverage)},
        clock=(T0, T0 + 1_951_000_000),
        COMBINE_EXIT=str(combine_exit),
        REPORT_EXIT=str(report_exit),
    )
    assert ran.code == code, ran.log
    assert ran.outputs == {"combine_ms": "1951"}
    assert [call.split()[2] for call in ran.calls] == verbs


def test_combine_step_stopped_by_set_u_still_records_its_wall_time(tmp_path: Path) -> None:
    # A shell error stops the step before the gate runs (`set -u`, on an unset COV_DIR); the trap
    # still records the time, and the step still fails.
    step = _step("governance", "combine")
    ran = _run(tmp_path, "governance", step, {"COV_DIR": None}, clock=(T0, T0 + 1_951_000_000))
    assert (ran.code, ran.calls) == (1, []), ran.log
    assert "COV_DIR: unbound variable" in ran.log
    assert ran.outputs == {"combine_ms": "1951"}
