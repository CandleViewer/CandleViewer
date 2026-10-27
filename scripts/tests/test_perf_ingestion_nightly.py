"""#399 R4: the full pack can run one scenario, and a stopped pack keeps its log and its reports.

The full pack ran 35 h on the bench runner and was cancelled with nothing logged and no report.
These pin what the workflow's header claims: Python output is unbuffered, a dispatch names one
`scenario` that reaches the runner through env and is checked first (a name with a scenario
file), and the reports are uploaded on a cancel too. The check and pack steps run under `bash -e`,
each in its working directory, with a stand-in `uv`.
#2825: the weekly cron's rest_k6, its guard (under `bash -e`, a stand-in `gh` whose answers go
through the step's own jq filters) and k6's pin.
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
#: #2825: the weekly cron, on which perf-pack-full runs rest_k6 alone.
WEEKLY = "17 5 * * 0"
SCENARIO = "${{ github.event_name == 'schedule' && 'rest_k6' || inputs.scenario }}"
#: #2825: "1" on the weekly run alone, whose Budget #13 rows are reported, not gated.
B13_WEEKLY = "${{ github.event_name == 'schedule' && '1' || '' }}"
WS_LOAD = WORKFLOW.with_name("perf-ws-load.yml")
#: What holds the bench runner, as the guard lists it: (workflow, job).
HOLDERS = [
    ("perf-ingestion-nightly.yml", "perf-pack-full"),
    ("perf-bars-memdiag.yml", "leg"),
    ("perf-ws-load.yml", "ws-load"),
]
#: Names with a letter outside ASCII (ß; a fullwidth "a"), which [a-z] matches in some locales.
NOT_ASCII = ("soak_barß", "\uff41ll")


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
    assert all(
        "PYTHONUNBUFFERED" not in job.get("env", {}) for job in doc["jobs"].values()
    )
    # YAML 1.1 reads the `on` key as True
    scenario = doc[True]["workflow_dispatch"]["inputs"]["scenario"]
    assert scenario["type"] == "string" and scenario["default"] == "all"
    # the check, then the pack it lets run (no `if:`), read the job's SCENARIO (#2825)
    assert _job()["env"]["SCENARIO"] == SCENARIO and "env" not in _step("scenario")
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
    # the check reads scenarios/ from the checkout's root: no working directory moves it
    assert "working-directory" not in _step("scenario") and "defaults" not in _job()
    assert "defaults" not in _doc()
    upload = next(s for s in _job()["steps"] if "upload-artifact@" in s.get("uses", ""))
    assert upload["if"] == "always()"  # a cancelled pack still uploads what it wrote
    # ... from where the pack writes it: services/api + --out-dir bench/reports
    assert _step("pack")["working-directory"] == "services/api"
    assert "--out-dir bench/reports" in _step("pack")["run"]
    assert upload["with"]["path"] == "services/api/bench/reports/"
    export = "bench/reports/rest_k6-k6-summary.json"  # k6's own summary (#2825)
    report_only = {"CV_BENCH_B13_REPORT_ONLY": B13_WEEKLY}
    assert _step("pack")["env"] == {"CV_BENCH_K6_EXPORT": export, **report_only}


def _pack(
    tmp_path: Path, scenario: str, locale: str = "C.UTF-8"
) -> tuple[int, list[list[str]]]:
    """The check step, then the pack step if the check passed, each under `bash -e` in its
    working directory, in a checkout holding the scenario files `soak_bars` and
    `soak_bars_frozen` (the second as vw5's slice adds it), and decoys named like an option or
    too long, so that only the name pattern refuses those."""
    scenarios = tmp_path / "services" / "api" / "bench" / "ingestion" / "scenarios"
    scenarios.mkdir(parents=True)
    for name in ("soak_bars", "soak_bars_frozen", "rest_k6", *DECOYS, *NOT_ASCII):
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


@pytest.mark.parametrize("scenario", NOT_ASCII)
def test_a_letter_outside_ascii_is_refused_whatever_the_runners_locale(
    tmp_path: Path, scenario: str
) -> None:
    # The proof needs a locale where [a-z] matches such a letter (each name has a scenario
    # file, so only the C-locale pattern can refuse it); without one, skip visibly, or fail in CI.
    probe = 'export LC_ALL=en_US.UTF-8; [[ "ß" =~ ^[a-z]$ ]]'
    if subprocess.run(
        [shutil.which("bash") or "bash", "-c", probe], check=False
    ).returncode:
        (pytest.fail if os.environ.get("CI") else pytest.skip)(
            "no en_US.UTF-8 locale here"
        )
    code, calls = _pack(tmp_path, scenario, locale="en_US.UTF-8")  # matches [a-z] there
    assert code == 2 and calls == []


def test_schedule_weekly_cron_sits_beside_the_nightly_one() -> None:
    assert _doc()[True]["schedule"] == [{"cron": "37 3 * * *"}, {"cron": WEEKLY}]


def test_ingestion_soak_on_the_weekly_cron_is_skipped() -> None:
    soak = _doc()["jobs"]["ingestion-soak"]  # nightly and on a dispatch, but not profile=auth
    assert soak["if"] == f"github.event.schedule != '{WEEKLY}' && inputs.profile != 'auth'"


def test_perf_pack_full_weekly_cron_runs_rest_k6(tmp_path: Path) -> None:
    guard = _doc()["jobs"]["bench-free"]["if"]  # never on a smoke dispatch
    full = "(github.event_name == 'workflow_dispatch' && inputs.profile == 'full')"
    assert guard == f"{full} || github.event.schedule == '{WEEKLY}'"
    job = _job()
    assert job["needs"] == "bench-free"
    assert job["env"]["SCENARIO"] == SCENARIO  # rest_k6 on a schedule, else the input
    timeout = "${{ github.event_name == 'schedule' && 90 || 2100 }}"
    assert job["timeout-minutes"] == timeout  # the weekly run takes about 15 minutes
    code, calls = _pack(tmp_path, "rest_k6")  # which the scenario check lets through
    assert code == 0 and [c[4] for c in calls] == ["rest_k6"]


def test_perf_pack_full_rerun_is_skipped() -> None:
    # on bench-free's all-clear, on a run's first attempt only: "re-run failed jobs"
    # re-runs the pack alone on that all-clear, however old, so a re-run skips it
    all_clear = "needs.bench-free.outputs.free == 'true'"
    assert _job()["if"] == f"{all_clear} && github.run_attempt == 1"


def test_perf_pack_full_budget_13_reported_on_the_weekly_run_alone() -> None:
    # "1" on the schedule, "" on a dispatch, which keeps the gate: until #2825's slice 2
    # decides the budget (a known-red weekly job trains everyone to ignore red);
    # services/api's test_e08_budgets runs the pack over both values
    assert _step("pack")["env"]["CV_BENCH_B13_REPORT_ONLY"] == B13_WEEKLY


def test_perf_pack_full_shares_the_bench_group_at_job_level_only() -> None:
    # one soak at a time with the memory legs (#399), and the nightly smoke never waits (#2825)
    group = {"group": "cv-bench-01", "cancel-in-progress": False}
    assert _job()["concurrency"] == group and "concurrency" not in _doc()


def test_bench_free_runs_off_the_bench_runner_and_only_reads_actions() -> None:
    guard = _doc()["jobs"]["bench-free"]
    assert guard["runs-on"] == "ubuntu-latest" and guard["timeout-minutes"] == 5
    assert guard["permissions"] == {"actions": "read"}  # lists runs and their jobs
    (step,) = guard["steps"]  # every value reaches the script through env
    assert set(step["env"]) == {"GH_TOKEN", "EVENT"} and "${{" not in step["run"]


@pytest.mark.parametrize(("wf", "job"), HOLDERS)
def test_bench_free_each_holder_keeps_its_job_id_as_its_name(wf: str, job: str) -> None:
    # the guard matches a job by its display name: a `name:` or a matrix would blind it
    jobs = yaml.safe_load(WORKFLOW.with_name(wf).read_text(encoding="utf-8"))["jobs"]
    assert job in jobs and not {"name", "strategy"} & set(jobs[job])


#: A stand-in `gh` for the guard's calls: it serves the API's JSON for the path and
#: prints what the step's own `--jq` filter makes of it, through jq (`-r`, as gh
#: prints). GH_ANSWER: `runs` maps "file:status" to run ids, `jobs` a run id to
#: [name, status] pairs, and `count`, if set, is what a jobs call prints instead; a
#: path holding `fail` fails as the API's 404 does.
FAKE_GH = """import json, os, re, subprocess, sys
args = sys.argv[1:]
path, jq = next(a for a in args if a.startswith("repos/")), args[args.index("--jq") + 1]
answer = json.loads(os.environ["GH_ANSWER"])
if answer.get("fail", "never") in path:
    sys.exit("gh: Not Found (HTTP 404)")
if m := re.fullmatch(r"repos/o/r/actions/runs/(\\d+)/jobs\\?per_page=100", path):
    if "count" in answer:
        print(answer["count"])
        sys.exit()
    jobs = answer.get("jobs", {}).get(m.group(1), [])
    body = {"jobs": [{"name": n, "status": s} for n, s in jobs]}
elif m := "--paginate" in args and re.search(r"workflows/([^/]+)/runs\\?status=(\\w+)&", path):
    ids = answer.get("runs", {}).get("{}:{}".format(*m.groups()), [])
    body = {"workflow_runs": [{"id": i} for i in ids]}
else:
    sys.exit("unexpected gh call: " + " ".join(args))
run = [os.environ["JQ"], "-r", jq]
sys.exit(subprocess.run(run, input=json.dumps(body), text=True).returncode)
"""


def _guard(tmp_path: Path, event: str, **answer: Any) -> tuple[int, str, str]:
    """bench-free's step under `bash -e` in run 42, a stand-in `gh` answering through jq."""
    bash, jq = shutil.which("bash"), shutil.which("jq")
    assert bash and jq, "bash runs the step, jq its filters"  # never skipped
    gh, out = tmp_path / "gh", tmp_path / "output"
    gh.write_text(f"#!{sys.executable}\n{FAKE_GH}", encoding="utf-8")
    gh.chmod(0o755)
    path = f"{tmp_path}{os.pathsep}{os.environ.get('PATH', '')}"
    env = {"PATH": path, "GITHUB_REPOSITORY": "o/r", "GITHUB_RUN_ID": "42", "JQ": jq}
    env |= {"GITHUB_OUTPUT": str(out), "EVENT": event, "GH_ANSWER": json.dumps(answer)}
    (step,) = _doc()["jobs"]["bench-free"]["steps"]
    cmd = [bash, "-e", "-c", step["run"]]  # it reads no path relative to its cwd
    done = subprocess.run(
        cmd, env=env, capture_output=True, text=True, timeout=60, check=False
    )
    log = done.stdout + done.stderr
    return done.returncode, log, out.read_text() if out.exists() else ""


def _held(wf: str, job: str, status: str, run: int = 7) -> dict[str, Any]:
    """An answer in which `wf` has one run, `run`, whose job `job` is `status`."""
    return {"runs": {f"{wf}:{status}": [run]}, "jobs": {str(run): [[job, status]]}}


@pytest.mark.parametrize("event", ["schedule", "workflow_dispatch"])
def test_bench_free_runner_free_lets_the_pack_start(tmp_path: Path, event: str) -> None:
    # tonight's run holds no runner: its pack was skipped, and its soak runs elsewhere
    jobs = {"8": [["perf-pack-full", "completed"], ["ingestion-soak", "in_progress"]]}
    runs = {"perf-ingestion-nightly.yml:in_progress": [8]}
    code, log, out = _guard(tmp_path, event, runs=runs, jobs=jobs)
    assert (code, out) == (0, "free=true\n"), log


@pytest.mark.parametrize("status", ["queued", "in_progress"])
@pytest.mark.parametrize(("wf", "job"), HOLDERS)
def test_bench_free_busy_on_the_schedule_notices_and_skips_the_pack(
    tmp_path: Path, wf: str, job: str, status: str
) -> None:
    code, log, out = _guard(tmp_path, "schedule", **_held(wf, job, status))
    assert (code, out) == (0, ""), log  # green, and the pack's `if:` wants free=true
    assert "::notice::" in log and f"{wf} (job {job})" in log


def test_bench_free_busy_on_a_dispatch_fails(tmp_path: Path) -> None:
    held = _held("perf-ws-load.yml", "ws-load", "in_progress")
    code, log, out = _guard(tmp_path, "workflow_dispatch", **held)
    assert (code, out) == (1, "") and "::error::" in log, log


def test_bench_free_own_run_holds_nothing(tmp_path: Path) -> None:
    # run 42 is this one: its own perf-pack-full waits for the guard
    held = _held("perf-ingestion-nightly.yml", "perf-pack-full", "queued", run=42)
    code, log, out = _guard(tmp_path, "workflow_dispatch", **held)
    assert (code, out) == (0, "free=true\n"), log


@pytest.mark.parametrize("broken", [*(wf for wf, _ in HOLDERS), "/runs/7/"])
def test_bench_free_api_error_fails_closed(tmp_path: Path, broken: str) -> None:
    # busy on a schedule exits 0, so only the failed call makes it 1: no 404 passes
    held = _held("perf-ws-load.yml", "ws-load", "in_progress")
    code, log, out = _guard(tmp_path, "schedule", fail=broken, **held)
    assert (code, out) == (1, "") and "(HTTP 404)" in log, log


def test_bench_free_empty_job_count_fails_closed(tmp_path: Path) -> None:
    # gh prints `length` as a number: an empty count is no answer, never a 0 (free), and the
    # log names the run whose count it was
    held = _held("perf-ws-load.yml", "ws-load", "in_progress")
    code, log, out = _guard(tmp_path, "schedule", count="", **held)
    errors = [x for x in log.splitlines() if x.startswith("::error::")]
    named = "perf-ws-load.yml run 7 is not a number"
    assert (code, out) == (1, "") and len(errors) == 1 and named in errors[0], log


def test_k6_install_is_the_release_ws_load_pins_put_on_path() -> None:
    ws = yaml.safe_load(WS_LOAD.read_text(encoding="utf-8"))["jobs"]["ws-load"]
    env = _job()["env"]
    assert (env["K6_VERSION"], env["K6_SHA256"]) == ("v2.3.0", ws["env"]["K6_SHA256"])
    name = "Install the pinned k6 (sha256 verified twice)"
    mine = next(s for s in _job()["steps"] if s.get("name") == name)
    theirs = next(s for s in ws["steps"] if s.get("name") == name)
    # ws-load's step, checked twice, but with k6 on PATH for drive_k6's shutil.which
    to_path = ('"K6_BIN=$dir/k6" >> "$GITHUB_ENV"', '"$dir" >> "$GITHUB_PATH"')
    assert mine == {**theirs, "run": theirs["run"].replace(*to_path)} != theirs
    assert "setup-k6-action" not in WORKFLOW.read_text(encoding="utf-8")


def test_k6_on_the_bench_runner_sends_no_usage_report() -> None:
    env = _job()["env"]
    assert env["K6_NO_USAGE_REPORT"] == "true"
    assert env["K6_AUTO_EXTENSION_RESOLUTION"] == "false"  # nor resolves an extension
