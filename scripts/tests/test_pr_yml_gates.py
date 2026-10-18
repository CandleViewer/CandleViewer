"""#3076: ten gates are steps of one `gates` job, each judged under its old `ci-required` lane
(#2988 semantics); `architecture` mirrors `py` from pr.yml; PRs skip `xstate-sync-parity`.
#3104: `xstate-contract` is an eleventh step, running the one script the nightly runs too, and
`gen` the twelfth, last of all: its full install runs the PR's build scripts."""

from __future__ import annotations

import functools
import json
import math
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
VAR = "${{ fromJSON(vars.CV_CI_TIMEOUT_MINUTES || 20) }}"
# Lane -> timeout-minutes of the job its step replaced (pr.yml and _job-*.yml at 33887603).
GATES: dict[str, int | str] = {
    **dict.fromkeys(["spike-containment", "changelog-fragment", "licence-header"], 5),
    **dict.fromkeys(["docs-link-check", "pin-check", "commitlint"], 5),
    **dict.fromkeys(["statechart-lint", "event-coverage", "machine-hash-lock"], VAR),
    "xstate-pin-attestation": 10,
    "xstate-contract": VAR,  # #3104: _job-xstate-contract.yml:35 at 59bec409
    "gen": 5,  # #3104: _job-gen.yml:27 at 59bec409
}
OTHER_LANES = ["changed-paths", "js", "py", "rule-roundtrip", "contract"]
OTHER_LANES += ["integration", "migrations", "security", "e2e", "a11y", "engine-bench"]
# The blocking statechart contract run, defined once (#3104); it starts with `uv sync`.
SCRIPT = "tools/statechart/run_xstate_contract.sh"
# The script's commands, verbatim: the old job's steps (_job-xstate-contract.yml at 59bec409), so
# no suite, flag (`-W error::RuntimeWarning`, CV-C67) or check drops out unnoticed. Its `uv sync` is
# why INSTALLERS names the script.
SCRIPT_COMMANDS = [
    "set -euo pipefail",
    'cd "$(dirname "${BASH_SOURCE[0]}")/../.."',
    "cd services/api",
    "uv sync --frozen --all-groups",
    'uv run pytest tests/xstate_contract tests/xstate_upstream -q --no-cov -m "not sync_parity" \\',
    "-W error::RuntimeWarning --durations=10 --junitxml=xstate-contract-junit.xml",
    "uv run python ../../tools/statechart/event_coverage.py",
    "uv run pytest ../../scripts/tests/test_event_coverage.py -q --no-cov -W error::RuntimeWarning",
    "cd ../..",
    "python tools/statechart/suite_budget.py services/api/xstate-contract-junit.xml",
]
# Steps that install toolchains or run the PR's own build and lifecycle scripts.
LIFECYCLE = ("pnpm install", "corepack", "actions/setup-node@")
INSTALLERS = ("uv sync", "astral-sh/setup-uv@", SCRIPT, *LIFECYCLE)
FAIL = "CI-GATE-001: %s required and not successful (result: %s)"
SKIP = "CI-GATE-002: gate misconfiguration: %s applicable but skipped"


@functools.cache
def _load(name: str) -> dict[str, Any]:
    path = ROOT / ".github" / "workflows" / name.removeprefix("./.github/workflows/")
    doc: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
    return doc


JOBS: dict[str, Any] = _load("pr.yml")["jobs"]
(RESOLVER,) = [s for s in JOBS["ci-required"]["steps"] if s.get("name", "").startswith("Resolve")]
LANE = r'^\s*"?([\w-]+)"?:\s*\{\s*applicable:\s*(.+?),\s*result:\s*process\.env\.(RESULT_\w+)'
# Lane -> (`applicable` expression, RESULT_* variable), read from the resolver step's script.
LANES = {m[1]: (m[2], m[3]) for m in re.finditer(LANE, RESOLVER["run"], re.MULTILINE | re.DOTALL)}


def test_resolver_keeps_every_lane_and_adds_gates_and_architecture() -> None:
    assert set(LANES) == {*GATES, *OTHER_LANES, "coverage-thresholds", "gates", "architecture"}


def test_ci_required_needs_every_other_job() -> None:
    assert set(JOBS["ci-required"]["needs"]) == set(JOBS) - {"ci-required"}


@pytest.mark.parametrize("lane", sorted(GATES))
def test_each_gate_is_one_step_wired_to_its_lane(lane: str) -> None:
    (step,) = [s for s in JOBS["gates"]["steps"] if s.get("id") == lane]
    applicable, variable = LANES[lane]
    assert (step["continue-on-error"], step["timeout-minutes"]) == (True, GATES[lane])
    assert JOBS["gates"]["outputs"][lane] == "${{ steps." + lane + ".outcome }}"
    assert RESOLVER["env"][variable] == "${{ needs.gates.outputs." + lane + " }}"
    # The step runs exactly when the resolver calls its lane applicable.
    term = re.fullmatch(r"isTrue\(process\.env\.FILTER_(\w+)\)", applicable)
    assert applicable == "true" or term, applicable
    when = f" && needs.changed-paths.outputs.{term[1].lower()} == 'true'" if term else ""
    assert step["if"] == "${{ !cancelled()" + when + " }}"


def test_gates_job_reads_only_contents_and_has_no_services_or_secrets() -> None:
    gates = JOBS["gates"]
    assert set(gates["outputs"]) == set(GATES)
    assert gates["permissions"] == {"contents": "read"}
    assert {"services", "container", "secrets", "strategy"}.isdisjoint(gates)
    assert "secrets." not in json.dumps(gates)
    shape = (gates["needs"], gates["if"], gates["runs-on"], gates["timeout-minutes"])
    assert shape == ("changed-paths", "${{ !cancelled() }}", "ubuntu-latest", 45)


def test_gates_installers_follow_every_tree_reading_gate_and_the_verdict_runs_last() -> None:
    steps = JOBS["gates"]["steps"]
    texts = [json.dumps(step) for step in steps]
    installers = [i for i, text in enumerate(texts) if any(word in text for word in INSTALLERS)]
    readers = [i for i, s in enumerate(steps) if s.get("id") in GATES and i not in installers]
    assert len(readers) == 8 and min(installers) > max(readers)
    assert [step.get("id") for step in steps[-3:-1]] == ["commitlint", "gen"]
    verdict = steps[-1]
    assert verdict["if"] == "${{ !cancelled() }}"
    assert verdict["env"] == {"OUTCOMES": "${{ toJSON(steps) }}"}
    assert 'not in ("success", "skipped")' in verdict["run"]
    # continue-on-error hides a failure from failure(); no cache crosses PR runs.
    assert not any("failure()" in text or "actions/cache@" in text for text in texts)
    nodes = [s for s in steps if "setup-node@" in s.get("uses", "")]
    assert nodes and all("cache" not in s["with"] for s in nodes)


def test_gen_runs_the_old_job_on_a_full_install_and_a_bare_python() -> None:
    steps = JOBS["gates"]["steps"]
    lines = [line.strip() for line in steps[-2]["run"].splitlines()]
    # _job-gen.yml at 59bec409: the full install (commitlint's is `--filter .`), then PyYAML at its
    # pin in a fresh venv, so `pnpm generate`'s python3 sees nothing an earlier gate installed into
    # setup-python's 3.13 (pytest, pypi-attestations). The failure summary is the step's own.
    order = ["pnpm install --frozen-lockfile", 'python -m venv "$RUNNER_TEMP/gen-venv"']
    order += ['export PATH="$RUNNER_TEMP/gen-venv/bin:$PATH"']
    order += ["python -m pip install --quiet -c scripts/requirements-ci.txt PyYAML"]
    # E03-T05's acceptance criterion: the failure summary names the command `make gen`.
    order += ["python tools/ci/check_gen_freshness.py || {", 'echo "make gen"']
    order += ['} >> "$GITHUB_STEP_SUMMARY"', "exit 1"]
    assert [line for line in lines if line in order] == order
    (python,) = [s for s in steps if "actions/setup-python@" in s.get("uses", "")]
    assert python["with"] == {"python-version": "3.13"}  # the old job's; no step activates a venv
    assert not [s for s in steps if "activate-environment" in (s.get("with") or {})]
    assert not (ROOT / ".github" / "workflows" / "_job-gen.yml").exists()


def _resolve(off: set[str], context: dict[str, str]) -> tuple[int, set[str]]:
    """Run the resolver step under the env GitHub builds; an unresolved expression is ''."""
    if not (shutil.which("bash") and shutil.which("node")):  # CI must run these fail-closed proofs
        (pytest.fail if os.environ.get("CI") else pytest.skip)("bash and node run the resolver step")
    values = {f"needs.{job}.result": "success" for job in JOBS}
    values |= {f"needs.gates.outputs.{lane}": "success" for lane in GATES}
    for name in JOBS["changed-paths"]["outputs"]:
        values[f"needs.changed-paths.outputs.{name}"] = "false" if name in off else "true"
    values |= context
    env = {"PATH": os.environ.get("PATH", "")}
    for name, expression in RESOLVER["env"].items():
        path = re.fullmatch(r"\$\{\{ ([\w.-]+) \}\}", expression)
        assert path, expression
        env[name] = values.get(path[1], "")
    run = ["bash", "-c", RESOLVER["run"]]
    proc = subprocess.run(run, cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)
    return proc.returncode, {line for line in proc.stderr.splitlines() if line.startswith("CI-")}


NEVER_RAN = {"needs.gates.result": "skipped"} | {f"needs.gates.outputs.{g}": "" for g in GATES}
GATE_FAILED = {"needs.gates.outputs.licence-header": "failure", "needs.gates.result": "failure"}
# #3104's live proof: a failing contract test fails only its step, so `gates` and that lane.
XSTATE_FAILED = {"needs.gates.outputs.xstate-contract": "failure", "needs.gates.result": "failure"}
XSTATE_RED = {FAIL % ("xstate-contract", "failure"), FAIL % ("gates", "failure")}
# PR3's live proof: generation writes a file the commit lacks (CI-GEN-002); only `gen` fails.
GEN_FAILED = {"needs.gates.outputs.gen": "failure", "needs.gates.result": "failure"}
GEN_RED = {FAIL % ("gen", "failure"), FAIL % ("gates", "failure")}


@pytest.mark.parametrize(
    ("off", "context", "expected"),
    [
        (set(), {}, set()),
        (set(), GATE_FAILED, {FAIL % ("licence-header", "failure"), FAIL % ("gates", "failure")}),
        ({"infra"}, {"needs.gates.outputs.pin-check": "skipped"}, set()),
        (set(), {"needs.gates.outputs.pin-check": "skipped"}, {SKIP % "pin-check"}),
        (set(), NEVER_RAN, {SKIP % "gates", *(FAIL % (lane, "") for lane in GATES)}),
        (set(), {"needs.architecture.result": "failure"}, {FAIL % ("architecture", "failure")}),
        ({"py"}, {"needs.architecture.result": "skipped"}, set()),
        (set(), XSTATE_FAILED, XSTATE_RED),
        ({"py"}, {"needs.gates.outputs.xstate-contract": "skipped"}, set()),
        (set(), GEN_FAILED, GEN_RED),
    ],
    ids=["green", "failed", "filtered", "misconfigured", "never-ran", "arch-failed", "arch-no-py"]
    + ["xstate-failed", "xstate-no-py", "gen-failed"],
)
def test_resolver_step_judges_each_gate_as_its_old_job(
    off: set[str], context: dict[str, str], expected: set[str]
) -> None:
    assert _resolve(off, context) == (1 if expected else 0, expected)


def test_architecture_mirrors_the_py_lane_beside_coverage_thresholds() -> None:
    job = JOBS["architecture"]
    assert (job["needs"], job["permissions"]) == (["changed-paths", "py"], {"contents": "read"})
    assert job["if"] == "${{ always() && needs.changed-paths.outputs.py == 'true' }}"
    assert '[ "${{ needs.py.result }}" = "success" ] || {' in job["steps"][0]["run"]
    assert "architecture" not in _load("_job-py.yml")["jobs"]


def _runs(condition: object, on: set[str], inputs: dict[str, Any]) -> bool:
    """A job `if:` on a feature-branch PR: an input, an OR of filter terms, or neither."""
    text = str(condition)
    if name := re.fullmatch(r"\$\{\{ inputs\.(\w+) \}\}", text):
        return _runs(inputs[name[1]], on, {})
    filters = set(re.findall(r"needs\.changed-paths\.outputs\.(\w+) == 'true'", text))
    return bool(filters & on) if filters else text.lower() != "false" and "github." not in text


def _executed(workflow: str, on: set[str]) -> list[str]:
    """Jobs a PR run puts on a runner, one per matrix leg."""
    ran: list[str] = []
    for job_id, job in _load(workflow)["jobs"].items():
        callee = _load(job["uses"]) if "uses" in job else {"jobs": {"": job}}
        call = (callee.get(True) or {}).get("workflow_call") or {}  # YAML 1.1 reads `on` as True
        inputs = {k: v.get("default") for k, v in (call.get("inputs") or {}).items()}
        inputs |= job.get("with") or {}
        for inner_id, inner in callee["jobs"].items() if _runs(job.get("if", True), on, {}) else ():
            if _runs(inner.get("if", True), on, inputs):
                legs = math.prod(
                    map(len, ((inner.get("strategy") or {}).get("matrix") or {}).values())
                )
                ran += [f"{job_id} / {inner_id}".removesuffix(" / ")] * legs
    return ran


@pytest.mark.parametrize(
    ("change", "count"),
    # On 33887603: 8 / 31 / 32 / 51; after #3076: 4 / 22 / 22 / 41. #3104 folds four security
    # scans into one job and bandit into semgrep's (4 / 18 / 18 / 37), then runs xstate-contract
    # in `gates` (4 / 17 / 17 / 36), then `gen` (3 / 16 / 16 / 35); the third PR's own run is 16.
    [("docs", 3), ("py", 16), ("py,infra", 16), ("all", 35)],
)
def test_executed_job_count_per_change_class(change: str, count: int) -> None:
    on = set(JOBS["changed-paths"]["outputs"]) if change == "all" else set(change.split(","))
    assert len(_executed("pr.yml", on)) == count


def test_pr_runs_neither_xstate_job_and_the_nightly_runs_both_through_the_script() -> None:
    contract, parity = "xstate-contract / xstate-contract", "xstate-contract / xstate-sync-parity"
    every = set(JOBS["changed-paths"]["outputs"])
    assert not [job for job in _executed("pr.yml", every) if job.startswith("xstate-contract")]
    assert _executed("xstate-contract-nightly.yml", set()) == [contract, parity]
    jobs = _load("_job-xstate-contract.yml")["jobs"]
    contract_job, parity_job = jobs["xstate-contract"], jobs["xstate-sync-parity"]
    assert [s["run"] for s in contract_job["steps"] if "run" in s] == [f"bash {SCRIPT}"]
    assert "if" not in parity_job and parity_job["continue-on-error"] is True


def test_gates_runs_the_script_on_the_nightly_toolchain_before_any_lifecycle_install() -> None:
    steps = JOBS["gates"]["steps"]
    at = [step.get("id") for step in steps].index("xstate-contract")
    assert steps[at]["run"] == f"bash {SCRIPT}"
    # Python 3.12 as in the nightly: the same setup-uv step runs first (machine-hash-lock uses it).
    (uv,) = [s for s in steps[:at] if "astral-sh/setup-uv@" in s.get("uses", "")]
    nightly = _load("_job-xstate-contract.yml")["jobs"]["xstate-contract"]["steps"]
    (nightly_uv,) = [s for s in nightly if "astral-sh/setup-uv@" in s.get("uses", "")]
    assert (uv["uses"], uv["with"]) == (nightly_uv["uses"], nightly_uv["with"])
    assert uv["with"]["python-version"] == "3.12"
    # No PR lifecycle script (node, corepack, pnpm install) has run before it.
    texts = [json.dumps(step) for step in steps]
    lifecycle = [i for i, text in enumerate(texts) if any(word in text for word in LIFECYCLE)]
    assert lifecycle and min(lifecycle) > at


def test_the_script_is_the_single_tracked_definition_of_the_contract_run() -> None:
    # The only file under .github/ or tools/ that runs the suite with the gate's marker expression.
    git = ["git", "ls-files", "-s", "--", ".github", "tools"]
    listing = subprocess.run(git, cwd=ROOT, capture_output=True, text=True, check=True, timeout=60)
    runs = []
    for line in listing.stdout.splitlines():
        meta, path = line.split("\t", 1)
        text = (ROOT / path).read_text(encoding="utf-8", errors="replace")
        if "tests/xstate_contract" in text and "not sync_parity" in text:
            runs.append((meta.split()[0], path))
    assert runs == [("100755", SCRIPT)]
    lines = (ROOT / SCRIPT).read_text(encoding="utf-8").splitlines()
    assert lines[0] == "#!/usr/bin/env bash"
    assert [ln.strip() for ln in lines if ln.strip() and not ln.lstrip().startswith("#")] == (
        SCRIPT_COMMANDS
    )
    # SR-146: no tracing. Defence in depth: check_secrets_hygiene.py scans it too (#3274, #3294).
    assert not [ln for ln in lines if re.search(r"\bset\s+-[a-zA-Z]*x|xtrace|\bbash\s+-x\b", ln)]
