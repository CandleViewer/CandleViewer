# SPDX-License-Identifier: MIT
"""#3076: ten gates are steps of one `gates` job, each judged under its old `ci-required` lane
(#2988 semantics); `architecture` mirrors `py` from pr.yml; PRs skip `xstate-sync-parity`."""

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
}
OTHER_LANES = ["changed-paths", "gen", "js", "py", "rule-roundtrip", "xstate-contract", "contract"]
OTHER_LANES += ["integration", "migrations", "security", "e2e", "a11y", "engine-bench"]
# Steps that install toolchains or run the PR's own build and lifecycle scripts.
INSTALLERS = ("uv sync", "pnpm install", "corepack", "astral-sh/setup-uv@", "actions/setup-node@")
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
    assert steps[-2]["id"] == "commitlint"
    verdict = steps[-1]
    assert verdict["if"] == "${{ !cancelled() }}"
    assert verdict["env"] == {"OUTCOMES": "${{ toJSON(steps) }}"}
    assert 'not in ("success", "skipped")' in verdict["run"]
    # continue-on-error hides a failure from failure(); no cache crosses PR runs.
    assert not any("failure()" in text or "actions/cache@" in text for text in texts)
    nodes = [s for s in steps if "setup-node@" in s.get("uses", "")]
    assert nodes and all("cache" not in s["with"] for s in nodes)


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
    ],
    ids=["green", "failed", "filtered", "misconfigured", "never-ran", "arch-failed", "arch-no-py"],
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
    # On 33887603: 8 / 31 / 32 / 51. This PR's own run is py+infra+docs: 22.
    [("docs", 4), ("py", 22), ("py,infra", 22), ("all", 41)],
)
def test_executed_job_count_per_change_class(change: str, count: int) -> None:
    on = set(JOBS["changed-paths"]["outputs"]) if change == "all" else set(change.split(","))
    assert len(_executed("pr.yml", on)) == count


def test_pr_runs_skip_xstate_sync_parity_and_the_nightly_still_runs_it() -> None:
    contract, parity = "xstate-contract / xstate-contract", "xstate-contract / xstate-sync-parity"
    assert contract in _executed("pr.yml", {"py"}) and parity not in _executed("pr.yml", {"py"})
    assert _executed("xstate-contract-nightly.yml", set()) == [contract, parity]
