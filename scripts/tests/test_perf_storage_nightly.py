"""#3429: the storage perf nightly filed a false ">20 % regression" issue every night.

Its real-engine step ran pytest in `services/api`, whose addopts add `--cov-fail-under=85`: four
perf tests cover 3 to 6 percent of the package, so the step failed on coverage (exit 1) with all
four passed, and the ticket step, which fired on any failed harness step, filed a regression
issue for it every night since at least 2026-10-06. This pins the fix:

- the real-engine run is `--no-cov`. Its perf assertions are its check, the normal lanes measure
  coverage, and a coverage miss exits 1 as a failed test does;
- both harness steps record their exit code as the step output `rc` and fail the job with it;
- the ticket step files an issue only for a perf-gate exit: 1 from the proxy harness (a warm p95
  over baseline) or 1 from the real-engine pytest run (a perf test failed), after a `uv sync` that
  succeeded. Any other exit (pytest's 2 to 5, a kill signal) fails the job without one. Its `if:`
  names `failure()`: with no status function GitHub reads `success() && ...`, which skips the
  step after a failed one;
- the rest keeps its shape: triggers, permissions (the workflow's only), `CV_ENV`, no
  `continue-on-error`, no secret in a harness step's env, the pinned actions (their SHAs belong
  to Dependabot and tools/ci/check_action_pins.py) and the artifact upload.

Each rule runs the workflow's own step scripts under `bash -e` with a stand-in `uv`, or evaluates
the ticket step's `if:` over a table of outcomes. MUTANTS proves every rule can still fail, as
governance's canary self-test does for its checks. Not modelled: exit 1 is also what an uncaught
error in the harness, an unset `CV_ENV` and a fixture error (docker not reachable) give."""

from __future__ import annotations

import ast
import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, NamedTuple

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "perf-storage-nightly.yml"
#: The job's steps in order: by id, else by action, else (the one that opens the issue) by role.
LABELS = ["actions/checkout", "astral-sh/setup-uv", "sync", "proxy", "real", "ticket"]
LABELS += ["actions/upload-artifact"]
ARTIFACT_PATHS = ["results.json", "services/api/build/reports/storage-perf.json"]
PROXY_ARGV = [
    *("run", "--project", "services/api", "python", "tests/perf/storage/harness.py"),
    *("--out", "results.json"),
]
PERF_TESTS = "tests/integration/storage/test_storage_perf_harness.py"
#: What a harness command can exit with: pytest's 0 to 5 (1 tests failed, 2 interrupted or a
#: collection error, 3 internal error, 4 usage error, 5 nothing collected) and a SIGKILL.
EXIT_CODES = (0, 1, 2, 3, 4, 5, 137)
#: A stand-in `uv` that logs its arguments, one JSON list per call, and exits with UV_EXIT.
FAKE_UV = """import json, os, sys
with open(os.environ["UV_LOG"], "a", encoding="utf-8") as log:
    log.write(json.dumps(sys.argv[1:]) + "\\n")
sys.exit(int(os.environ["UV_EXIT"]))
"""

Check = Callable[[Path, Path], None]  # (the workflow, a scratch directory for the bash runs)
Mutant = Callable[[dict[Any, Any]], object]
#: A step's outcome and the `rc` it recorded (None: it recorded none).
Result = tuple[str, str | None]
SKIPPED: Result = ("skipped", None)
#: (what happened, the proxy step, the real-engine step, whether the ticket step opens an issue).
#: The real-engine step runs only after a proxy step that passed.
RUNS: list[tuple[str, Result, Result, bool]] = [
    ("nothing failed", ("success", "0"), ("success", "0"), False),
    ("proxy gate: a warm p95 is over baseline", ("failure", "1"), SKIPPED, True),
    ("real-engine gate: a perf test failed", ("success", "0"), ("failure", "1"), True),
    ("proxy: usage error or a failed uv", ("failure", "2"), SKIPPED, False),
    ("proxy: killed", ("failure", "137"), SKIPPED, False),
    ("proxy: failed, no exit code recorded", ("failure", None), SKIPPED, False),
    ("pytest: interrupted or collection error", ("success", "0"), ("failure", "2"), False),
    ("pytest: internal error", ("success", "0"), ("failure", "3"), False),
    ("pytest: usage error", ("success", "0"), ("failure", "4"), False),
    ("pytest: no tests collected", ("success", "0"), ("failure", "5"), False),
    ("pytest: killed", ("success", "0"), ("failure", "137"), False),
]


class Ran(NamedTuple):
    """What running a step's script gave: its exit code, the outputs it wrote to $GITHUB_OUTPUT,
    the arguments of each `uv` call and its output."""

    code: int
    outputs: dict[str, str]
    calls: list[list[str]]
    log: str


def _load(path: Path) -> dict[Any, Any]:
    """A workflow's YAML; its keys are strings except `on`, which YAML 1.1 reads as True."""
    doc: dict[Any, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
    return doc


def _steps(doc: dict[Any, Any]) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = doc["jobs"]["storage-perf"]["steps"]
    return steps


def _step(doc: dict[Any, Any], step_id: str) -> dict[str, Any]:
    (step,) = [step for step in _steps(doc) if step.get("id") == step_id]
    return step


def _ticket(doc: dict[Any, Any]) -> dict[str, Any]:
    """The one step that opens the issue."""
    (step,) = [step for step in _steps(doc) if "gh issue create" in step.get("run", "")]
    return step


def _label(step: dict[str, Any]) -> str:
    if "id" in step:
        return str(step["id"])
    if "uses" in step:
        return str(step["uses"]).partition("@")[0]
    return "ticket" if "gh issue create" in step.get("run", "") else str(step.get("name"))


def _run(tmp: Path, script: str, exit_code: int) -> Ran:
    """Run a step's script as the runner does (`bash -e`) in a new directory under `tmp`, which is
    also HOME, with a stand-in `uv` first on PATH that logs its arguments and exits with
    `exit_code`."""
    bash = shutil.which("bash") or ""
    if not bash:  # CI must run these fail-closed proofs
        (pytest.fail if os.environ.get("CI") else pytest.skip)("bash runs the step")
    work = tmp / f"run{len(list(tmp.iterdir()))}"
    (work / "bin").mkdir(parents=True)
    uv = work / "bin" / "uv"
    uv.write_text(f"#!{sys.executable}\n{FAKE_UV}", encoding="utf-8")
    uv.chmod(0o755)
    env = {
        "PATH": f"{work / 'bin'}{os.pathsep}{os.environ.get('PATH', '')}",
        "HOME": str(work),
        "UV_LOG": str(work / "uv.log"),
        "UV_EXIT": str(exit_code),
        "GITHUB_OUTPUT": str(work / "github-output"),
    }
    proc = subprocess.run(  # noqa: S603 - the workflow's own step text, in a scratch directory
        [bash, "-e", "-c", script],
        cwd=work,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    out, log = work / "github-output", work / "uv.log"
    written = re.findall(r"^([^=\n]+)=(.*)$", out.read_text() if out.exists() else "", re.M)
    calls = [json.loads(line) for line in (log.read_text().splitlines() if log.exists() else [])]
    return Ran(proc.returncode, dict(written), calls, proc.stdout + proc.stderr)


def _holds(condition: str, steps: dict[str, dict[str, Any]]) -> bool:
    """Evaluate a step's `if:` over `steps` ({id: {"outcome", "outputs"}}), for the part of GitHub's
    expression language this workflow uses: `failure()`, `success()`, `steps.<id>.outcome`,
    `steps.<id>.outputs.<name>`, strings, `==`, `!=`, `&&`, `||` and parentheses. As on GitHub, an
    `if:` with no status function (success, failure, always, cancelled) reads `success() && (...)`.
    Anything else raises, so a construct this does not read fails loudly instead of passing. A step
    that wrote no output reads '' here and null there, which differ only for `== '0'`: no `if:`
    here compares with it."""
    wrapped = re.fullmatch(r"\s*\$\{\{(.*)\}\}\s*", condition, re.DOTALL)
    text = (wrapped.group(1) if wrapped else condition).strip()
    tree = ast.parse(text.replace("&&", " and ").replace("||", " or "), mode="eval").body
    failed = any(step["outcome"] == "failure" for step in steps.values())

    def value(node: ast.expr) -> str:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        names: list[str] = []
        while isinstance(node, ast.Attribute):
            names.insert(0, node.attr)
            node = node.value
        if not isinstance(node, ast.Name) or node.id != "steps":
            raise ValueError(f"cannot read an operand of {text!r}: write a string or steps.<id>...")
        match names:
            case [step, "outcome"]:
                return str(steps[step]["outcome"])
            case [step, "outputs", name]:  # a step that did not run, or wrote none, has no output
                return str(steps[step]["outputs"].get(name, ""))
        raise ValueError(f"cannot read steps.{'.'.join(names)} in {text!r}")

    def truth(node: ast.expr) -> bool:
        if isinstance(node, ast.BoolOp):
            parts = [truth(part) for part in node.values]
            return all(parts) if isinstance(node.op, ast.And) else any(parts)
        if isinstance(node, ast.Call) and ast.unparse(node) in ("failure()", "success()"):
            return failed == (ast.unparse(node) == "failure()")
        if (
            isinstance(node, ast.Compare)
            and len(node.ops) == 1
            and isinstance(node.ops[0], ast.Eq | ast.NotEq)
        ):  # GitHub compares strings without regard to case
            same = value(node.left).casefold() == value(node.comparators[0]).casefold()
            return same == isinstance(node.ops[0], ast.Eq)
        raise ValueError(f"cannot read {ast.unparse(node)!r} in {text!r}")

    calls = (ast.unparse(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call))
    implicit_success = not set(calls) & {"success", "failure", "always", "cancelled"}
    return truth(tree) and not (implicit_success and failed)


def _keeps_its_shape(wf: Path, _tmp: Path) -> None:
    """Nothing else changed: the same triggers, permissions, steps, actions and artifact."""
    doc = _load(wf)
    assert doc.get(True) == {"schedule": [{"cron": "17 3 * * *"}], "workflow_dispatch": {}}
    assert doc.get("permissions") == {"contents": "read", "issues": "write"}
    assert list(doc["jobs"]) == ["storage-perf"]
    job = doc["jobs"]["storage-perf"]
    # The harness exits 1, the code of its regression gate, when CV_ENV is not `test`.
    assert job.get("env") == {"CV_ENV": "test"}
    steps = job["steps"]
    assert [_label(step) for step in steps] == LABELS
    # Nothing may quiet a failed harness step or widen what its code reaches: a step that cannot
    # fail the job, a job-level token block (it replaces the workflow's), a secret or the token.
    quiet = [("job" if x is job else _label(x)) for x in (job, *steps) if "continue-on-error" in x]
    assert quiet == [], f"continue-on-error would let a failed harness step pass the job: {quiet}"
    assert "permissions" not in job
    harness_env = str([_step(doc, step_id).get("env") for step_id in ("proxy", "real")])
    assert not re.search(r"secrets\s*[.\[]|github\.token", harness_env), harness_env
    pins = [str(step["uses"]).partition("@") for step in steps if "uses" in step]
    assert all(re.fullmatch(r"[0-9a-f]{40}", sha) for _, _, sha in pins), pins
    # Values reach a script through env, never as an expression expanded into it.
    assert [_label(step) for step in steps if "${{" in step.get("run", "")] == []
    assert _ticket(doc).get("env") == {"GH_TOKEN": "${{ github.token }}"}
    upload = steps[-1]
    assert upload.get("if") == "always()"
    assert upload.get("with", {}).get("name") == "storage-perf-results"
    assert str(upload.get("with", {}).get("path")).split() == ARTIFACT_PATHS


def _real_engine_run_drops_the_coverage_floor(wf: Path, tmp: Path) -> None:
    """The real-engine pytest run carries `--no-cov`, as an argument of pytest, in services/api."""
    step = _step(_load(wf), "real")
    assert step["working-directory"] == "services/api"
    (argv,) = _run(tmp, step["run"], 0).calls
    assert argv[:3] == ["run", "pytest", PERF_TESTS], argv
    assert "--no-cov" in argv[3:], f"the coverage floor applies to the perf run: {argv}"
    assert "-m" in argv and argv[argv.index("-m") + 1] == "integration and perf and not flaky"


def _harness_steps_record_their_exit_code(wf: Path, tmp: Path) -> None:
    """Each harness step runs its command once, writes `rc=<its exit code>` to $GITHUB_OUTPUT and
    exits with that code, so the job fails exactly as before."""
    doc = _load(wf)
    for step_id in ("proxy", "real"):
        script = _step(doc, step_id)["run"]
        for code in EXIT_CODES:
            ran = _run(tmp, script, code)
            got, want = (ran.code, ran.outputs, len(ran.calls)), (code, {"rc": str(code)}, 1)
            assert got == want, f"{step_id}, uv exits {code}: {got}\n{ran.log}"
    assert _run(tmp, _step(doc, "proxy")["run"], 0).calls == [PROXY_ARGV]


def _ticket_only_for_a_perf_gate_exit(wf: Path, _tmp: Path) -> None:
    """The ticket step opens an issue for the proxy harness's exit 1 or the real-engine pytest's
    exit 1, and for nothing else, whatever it was that failed."""
    condition: str = _ticket(_load(wf))["if"]
    for name, proxy, real, filed in RUNS:
        steps = {"sync": {"outcome": "success", "outputs": {}}}
        for step_id, (outcome, rc) in (("proxy", proxy), ("real", real)):
            steps[step_id] = {"outcome": outcome, "outputs": {} if rc is None else {"rc": rc}}
        assert _holds(condition, steps) is filed, f"{name}: the ticket step should be {filed}"
    # A failed `uv sync` is not a regression, even if a later edit let a harness step run after it.
    steps = {
        "sync": {"outcome": "failure", "outputs": {}},
        "proxy": {"outcome": "failure", "outputs": {"rc": "1"}},
        "real": {"outcome": "skipped", "outputs": {}},
    }
    assert not _holds(condition, steps), "a failed uv sync files a ticket"


CHECKS: list[Check] = [
    _keeps_its_shape,
    _real_engine_run_drops_the_coverage_floor,
    _harness_steps_record_their_exit_code,
    _ticket_only_for_a_perf_gate_exit,
]


def _edit(step_id: str, key: str, old: str, new: str) -> Mutant:
    """A mutant: the step's `run` or `if` with every `old` replaced by `new`."""

    def mutate(doc: dict[Any, Any]) -> None:
        step = _ticket(doc) if step_id == "ticket" else _step(doc, step_id)
        assert old in step[key], f"{step_id} {key} has no {old!r}: the mutant would change nothing"
        step[key] = step[key].replace(old, new)

    return mutate


def _put(step_id: str | None, key: str, value: object) -> Mutant:
    """A mutant: the job (None) or the step gets `key: value`."""

    def mutate(doc: dict[Any, Any]) -> None:
        (doc["jobs"]["storage-perf"] if step_id is None else _step(doc, step_id))[key] = value

    return mutate


GATE = "(steps.proxy.outputs.rc == '1' || steps.real.outputs.rc == '1')"
ANY_FAILED = "(steps.proxy.outcome == 'failure' || steps.real.outcome == 'failure')"
REAL_GATE = "steps.real.outputs.rc == '1'"
#: For each check, the ways to break the workflow that it must catch ({name: how to break it}).
MUTANTS: dict[Check, dict[str, Mutant]] = {
    _real_engine_run_drops_the_coverage_floor: {
        "no-cov-removed": _edit("real", "run", " --no-cov", ""),
    },
    _ticket_only_for_a_perf_gate_exit: {
        "any-failed-step": _edit("ticket", "if", GATE, ANY_FAILED),
        "failure-guard-dropped": _edit("ticket", "if", "failure() && ", ""),
        "any-non-zero-exit": _edit("ticket", "if", "== '1'", "!= '0'"),
        "a-failed-real-step": _edit("ticket", "if", REAL_GATE, "steps.real.outcome == 'failure'"),
        "after-a-failed-sync": _edit("ticket", "if", " && steps.sync.outcome == 'success'", ""),
        "proxy-gate-dropped": _edit("ticket", "if", "steps.proxy.outputs.rc == '1' || ", ""),
    },
    _harness_steps_record_their_exit_code: {
        "real-step-swallows-the-failure": _edit("real", "run", 'exit "$rc"', "exit 0"),
        "proxy-records-no-rc": _edit("proxy", "run", 'echo "rc=$rc" >> "$GITHUB_OUTPUT"\n', ""),
        "real-records-another-name": _edit("real", "run", 'echo "rc=', 'echo "code='),
        "real-step-aborts-before-recording": _edit("real", "run", " || rc=$?", ""),
    },
    _keeps_its_shape: {
        "cv-env-removed": lambda doc: doc["jobs"]["storage-perf"]["env"].pop("CV_ENV"),
        "upload-skipped-after-a-failure": lambda doc: _steps(doc)[-1].pop("if"),
        "continue-on-error-on-a-harness-step": _put("real", "continue-on-error", True),
        "job-level-permissions": _put(None, "permissions", {"contents": "write"}),
        "secret-in-a-harness-env": _put("proxy", "env", {"T": "${{ secrets.GITHUB_TOKEN }}"}),
    },
}
MUTANT_CASES = [
    (name, mutate, check) for check, ms in MUTANTS.items() for name, mutate in ms.items()
]


@pytest.mark.parametrize("check", CHECKS, ids=[check.__name__.lstrip("_") for check in CHECKS])
def test_the_workflow_keeps_the_rule(check: Check, tmp_path: Path) -> None:
    check(WORKFLOW, tmp_path)


@pytest.mark.parametrize(
    ("mutate", "check"), [case[1:] for case in MUTANT_CASES], ids=[case[0] for case in MUTANT_CASES]
)
def test_a_workflow_that_breaks_a_rule_fails_its_check(
    tmp_path: Path, mutate: Mutant, check: Check
) -> None:
    doc = _load(WORKFLOW)
    mutate(doc)
    broken = tmp_path / WORKFLOW.name
    broken.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    with pytest.raises(AssertionError):
        check(broken, tmp_path)


def test_each_check_owns_a_mutant() -> None:
    assert set(MUTANTS) == set(CHECKS)


def test_condition_reader_follows_githubs_rules() -> None:
    skipped = {"outcome": "skipped", "outputs": {}}
    failed = {"a": {"outcome": "failure", "outputs": {"rc": "1"}}, "b": skipped}
    passed = {"a": {"outcome": "success", "outputs": {"rc": "1"}}, "b": skipped}
    assert _holds("${{ failure() && steps.a.outputs.rc == '1' }}", failed)  # wrapper is optional
    assert _holds("failure() && steps.a.outcome == 'FAILURE'", failed)  # case does not matter
    assert not _holds("failure() && steps.b.outputs.rc == '1'", failed)  # no output reads ''
    assert _holds("failure() && steps.b.outputs.rc != '1'", failed)
    # With no status function GitHub reads `success() && (...)`: a failed step switches it off.
    assert _holds("steps.a.outputs.rc == '1'", passed)
    assert not _holds("steps.a.outputs.rc == '1'", failed)
    assert not _holds("success() && steps.a.outputs.rc == '1'", failed)


@pytest.mark.parametrize(
    ("condition", "error"),
    [
        ("!failure()", SyntaxError),
        ("always()", ValueError),
        ("contains(steps.a.outputs.rc, '1')", ValueError),
        ("steps.a.conclusion == 'failure'", ValueError),
        ("github.ref == 'refs/heads/main'", ValueError),
        ("steps.a.outputs.rc == 1", ValueError),  # GitHub reads '' == 0: write the code as a string
        ("steps.a.outcome == 'x' == 'y'", ValueError),
        ("steps.nope.outcome == 'failure'", KeyError),
    ],
)
def test_condition_reader_fails_loudly_on_what_it_cannot_read(
    condition: str, error: type[Exception]
) -> None:
    with pytest.raises(error):
        _holds(condition, {"a": {"outcome": "failure", "outputs": {"rc": "1"}}})
