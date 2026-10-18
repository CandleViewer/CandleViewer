"""#3076: ten gates are steps of one `gates` job, each judged under its old `ci-required` lane
(#2988 semantics); `architecture` mirrors `py` from pr.yml; PRs skip `xstate-sync-parity`.
#3104: `xstate-contract` is an eleventh step, running the one script the nightly runs too, and
`gen` the twelfth, last of all: its full install runs the PR's build scripts.
#3385: `secret-scan` is the thirteenth, first of all and on every PR: gitleaks and trufflehog over
the PR's commits, then the credential-hygiene gate, so a docs-only PR gets the secret scans too.
#3495: `backlog-twin-eol` is the fourteenth, on every PR: each backlog twin blob is LF."""

from __future__ import annotations

import functools
import json
import math
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
VAR = "${{ fromJSON(vars.CV_CI_TIMEOUT_MINUTES || 20) }}"
# Lane -> timeout-minutes of the job its step replaced (pr.yml and _job-*.yml at 33887603).
GATES: dict[str, int | str] = {
    **dict.fromkeys(["spike-containment", "changelog-fragment", "licence-header"], 5),
    **dict.fromkeys(["docs-link-check", "pin-check", "commitlint"], 5),
    **dict.fromkeys(["statechart-lint", "event-coverage", "machine-hash-lock"], VAR),
    "xstate-pin-attestation": 10,
    "xstate-contract": VAR,  # #3104: _job-xstate-contract.yml:35 at 59bec409
    "gen": 5,  # #3104: _job-gen.yml:27 at 59bec409
    "secret-scan": 10,  # #3385: the budget of the security lane's gitleaks job
    "backlog-twin-eol": 5,  # #3495: one `git ls-files --eol` over the twins
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
    # The step runs exactly when the resolver calls its lane applicable. A PR-metadata gate fails
    # closed: it skips only where `pr` is false, on a merge group (#3433).
    term = re.fullmatch(r"isTrue\(process\.env\.FILTER_(\w+)\)", applicable)
    pr_only = applicable == 'process.env.FILTER_PR !== "false"'
    assert applicable == "true" or term or pr_only, applicable
    when = f" && needs.changed-paths.outputs.{term[1].lower()} == 'true'" if term else ""
    when = " && needs.changed-paths.outputs.pr != 'false'" if pr_only else when
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
    assert len(readers) == 10 and min(installers) > max(readers)
    # #3385: the secret scans read the checkout and its history before any gate runs a PR script.
    assert steps[min(readers)]["id"] == "secret-scan"
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
    # #3299: and `make gen-check`, the only command that reproduces CI-GEN-005.
    gen_check = (
        'echo "Reproduce the whole gate locally with \\`make gen-check\\`. '
        'To regenerate and review:"'
    )
    order += ["python tools/ci/check_gen_freshness.py || {", gen_check, 'echo "make gen"']
    order += ['} >> "$GITHUB_STEP_SUMMARY"', "exit 1"]
    assert [line for line in lines if line in order] == order
    # #3299: the step name lists every code the gate reports.
    gate = (ROOT / "tools" / "ci" / "check_gen_freshness.py").read_text(encoding="utf-8")
    last = max(re.findall(r"CI-GEN-(\d{3})", gate))
    assert steps[-2]["name"].endswith(f", CI-GEN-001..{last})")
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
# #3385: a docs-only PR (no filter but `docs`) is still judged on the secret scans; the live proof
# plants a secret-shaped string in a docs file, which fails only that step, so `gates` and its lane.
DOCS_ONLY = set(JOBS["changed-paths"]["outputs"]) - {"docs"}
SECRET_FAILED = {"needs.gates.outputs.secret-scan": "failure", "needs.gates.result": "failure"}
SECRET_RED = {FAIL % ("secret-scan", "failure"), FAIL % ("gates", "failure")}


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
        (DOCS_ONLY, {}, set()),
        (DOCS_ONLY, SECRET_FAILED, SECRET_RED),
        (DOCS_ONLY, {"needs.gates.outputs.secret-scan": "skipped"}, {SKIP % "secret-scan"}),
    ],
    ids=["green", "failed", "filtered", "misconfigured", "never-ran", "arch-failed", "arch-no-py"]
    + ["xstate-failed", "xstate-no-py", "gen-failed", "docs-only", "docs-secret", "docs-no-scan"],
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
    # #3385 runs the secret scans as a `gates` step, so a docs-only PR still starts three jobs.
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


# --- #3385: the secret scans on every PR ---------------------------------------------------------
# A fake `docker` logs each call and plays the scanners: exit codes, the gitleaks report, output.
FAKE_DOCKER = """\
import json, os, subprocess, sys
args = sys.argv[1:]
with open(os.environ["DOCKER_LOG"], "a", encoding="utf-8") as log:
    log.write(json.dumps(args) + "\\n")
if args[0] == "pull":
    sys.exit(0)
i, mounts, entrypoint = 1, {}, None
while args[i].startswith("-"):
    if args[i] == "-v":
        host, path = args[i + 1].split(":")[:2]
        mounts[path] = host
    entrypoint = args[i + 1] if args[i] == "--entrypoint" else entrypoint
    i += 1 if args[i] == "--rm" else 2
image, rest = args[i], args[i + 1 :]
if entrypoint == "git":
    git = ["git", "-C", mounts["/repo"], *rest[2:]]
    print(os.environ.get("SEEN") or subprocess.run(git, capture_output=True, text=True).stdout)
    sys.exit(0)
tool = "GITLEAKS" if "gitleaks" in image else "TRUFFLEHOG"
report = os.environ.get(tool + "_REPORT", "[]")
code = int(os.environ.get(tool + "_EXIT", "0"))
find = os.environ.get("GITLEAKS_FIND") if tool == "GITLEAKS" else None
if find:  # gitleaks 8.30.1 reads `git log -p -U0` plus --log-opts split on spaces
    (opts,) = [a.split("=", 1)[1] for a in rest if a.startswith("--log-opts=")]
    git = ["git", "-C", mounts["/repo"], "log", "-p", "-U0", *opts.split(" ")]
    log = subprocess.run(git, capture_output=True, text=True, check=True).stdout.splitlines()
    if any(line[:1] == "+" and find in line for line in log):
        report, code = json.dumps([{"RuleID": "github-pat", "File": "README.md"}]), 3
if tool == "GITLEAKS" and report != "none":
    with open(os.path.join(mounts["/out"], "gitleaks.json"), "w", encoding="utf-8") as f:
        f.write(report)
print(os.environ.get(tool + "_OUT", ""))
sys.exit(code)
"""
# No venv or pip in a test; -B: no bytecode written into the repository's scripts.
FAKE_PYTHON = '#!/bin/sh\ncase "$1 $2" in "-m venv"|"-m pip") exit 0 ;; esac\nexec "%s" -B "$@"\n'
GIT = ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid"]
GIT += ["-c", "commit.gpgsign=false"]
LEAK = json.dumps([{"RuleID": "github-pat", "File": "docs/x.md", "StartLine": 3}])
ANNOTATION = "::warning file=docs/x.md,line=3,endLine=3::Found unverified Github result"
BLOCKS = "::error title=Committed secret blocks merge::"
MERGE_LINE = "a line only the merge commit adds"


def _scan() -> dict[str, Any]:
    (step,) = [s for s in JOBS["gates"]["steps"] if s.get("id") == "secret-scan"]
    return step


def _scan_run(
    tmp_path: Path,
    base: str | None = None,
    *,
    merged: bool = False,
    gitignore: str = ".env\n",
    **fake: str,
) -> tuple[int, str, list[Any]]:
    """Run the step's script as the runner does, in a checkout of two commits (the base, then a
    docs commit), with the fakes first on PATH: its exit code, its output and the docker calls.
    `merged`: the PR then merges a later base commit, adding MERGE_LINE only while resolving it."""
    if not (shutil.which("bash") and shutil.which("git")):  # CI must run these fail-closed proofs
        (pytest.fail if os.environ.get("CI") else pytest.skip)("bash and git run the step")
    ws, temp, bin_dir = tmp_path / "ws", tmp_path / "runner-temp", tmp_path / "bin"
    for d in (ws / "security", temp, bin_dir):
        d.mkdir(parents=True)
    env = {"PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}", "HOME": str(tmp_path)}
    env |= {"GIT_CONFIG_NOSYSTEM": "1", "RUNNER_TEMP": str(temp)}

    def git(*args: str) -> str:
        done = subprocess.run([*GIT, *args], cwd=ws, env=env, capture_output=True, check=False)
        assert done.returncode == 0, done.stderr
        return done.stdout.decode().strip()

    (ws / "README.md").write_text("docs\n", encoding="utf-8")
    git("init", "-q")
    git("commit", "-q", "--allow-empty", "-m", "base")
    first = git("rev-parse", "HEAD")
    git("add", "README.md")
    git("commit", "-q", "-m", "docs")
    head = git("rev-parse", "HEAD")
    if merged:
        git("checkout", "-q", "-b", "base-moved", first)
        (ws / "NEWS.md").write_text("base\n", encoding="utf-8")
        git("add", "NEWS.md")
        git("commit", "-q", "-m", "base moved")
        first = git("rev-parse", "HEAD")
        git("checkout", "-q", head)
        git("merge", "-q", "--no-ff", "--no-commit", "base-moved")
        (ws / "README.md").write_text(f"docs\n{MERGE_LINE}\n", encoding="utf-8")
        git("add", "README.md")
        git("commit", "-q", "-m", "merge the base")
        head = git("rev-parse", "HEAD")
    # What security_gate.py and the hygiene gate read beside the repository's own scripts.
    (ws / ".gitignore").write_text(gitignore, encoding="utf-8")
    (ws / ".env.example").write_text("# no settings\n", encoding="utf-8")
    (ws / "security" / "accepted-risks.yaml").write_text("entries: []\n", encoding="utf-8")
    for name in ("tools", "scripts"):
        (ws / name).symlink_to(ROOT / name)
    for name, body in (("docker", f"#!{sys.executable}\n{FAKE_DOCKER}"), ("python", FAKE_PYTHON)):
        (bin_dir / name).write_text(body.replace("%s", sys.executable), encoding="utf-8")
        (bin_dir / name).chmod(0o755)
    step_env = _scan()["env"]
    env |= {name: step_env[name] for name in ("GITLEAKS_IMAGE", "TRUFFLEHOG_IMAGE")}
    env |= {"BASE_SHA": first if base is None else base, "HEAD_SHA": head}
    env |= {"DOCKER_LOG": str(tmp_path / "docker.log"), **fake}
    run = ["bash", "-e", "-c", _scan()["run"]]
    proc = subprocess.run(
        run, cwd=ws, env=env, capture_output=True, text=True, timeout=120, check=False
    )
    log = tmp_path / "docker.log"
    lines = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
    return proc.returncode, proc.stdout + proc.stderr, [json.loads(line) for line in lines]


def test_secret_scan_reads_the_prs_commits_with_the_security_lanes_scanners() -> None:
    step, checkout = _scan(), JOBS["gates"]["steps"][0]
    assert checkout["with"] == {"fetch-depth": 0, "persist-credentials": False}
    # The scanner versions of the security lane's gitleaks job, pinned by digest here.
    lane = json.dumps(_load("_job-security.yml")["jobs"]["gitleaks"])
    for name in ("GITLEAKS_IMAGE", "TRUFFLEHOG_IMAGE"):
        image, digest = step["env"][name].split("@")
        assert image in lane and re.fullmatch(r"sha256:[0-9a-f]{64}", digest), name
    assert step["env"]["TRUFFLEHOG_IMAGE"] in lane
    # The range commitlint reads, from the event and through env only; on a merge group, the
    # group's own commit (#3433).
    event = "${{ github.event.pull_request.%s.sha || github.event.merge_group.%s_sha }}"
    base, head = event % ("base", "base"), event % ("head", "head")
    assert (step["env"]["BASE_SHA"], step["env"]["HEAD_SHA"]) == (base, head)
    assert "${{" not in step["run"]


def test_secret_scan_runs_both_scanners_offline_over_the_prs_commits(tmp_path: Path) -> None:
    code, output, calls = _scan_run(tmp_path)
    assert (code, BLOCKS in output) == (0, False), output
    gitleaks, trufflehog = _scan()["env"]["GITLEAKS_IMAGE"], _scan()["env"]["TRUFFLEHOG_IMAGE"]
    git = [*GIT, "-C", str(tmp_path / "ws"), "rev-list", "--reverse", "HEAD"]
    base, head = subprocess.run(git, capture_output=True, text=True, check=True).stdout.split()
    ro = ["run", "--rm", "--network", "none", "-v", f"{os.path.realpath(tmp_path / 'ws')}:/repo:ro"]
    out = f"{tmp_path / 'runner-temp' / 'secret-scan'}:/out"
    # gitleaks diffs a merge commit against its first parent, and the image's git proves first
    # that it reads the range with that option (a git without it would make gitleaks pass blind).
    merges = "--diff-merges=first-parent"
    assert calls == [
        ["pull", "--quiet", gitleaks],
        ["pull", "--quiet", trufflehog],
        [*ro, "--entrypoint", "git", gitleaks, "-C", "/repo", "rev-list", "--count", merges]
        + [f"{base}..{head}"],
        [*ro, "-v", out, gitleaks, "git", "/repo", f"--log-opts={merges} {base}..{head}"]
        + ["--config=/repo/.gitleaks.toml", "--redact", "--no-banner", "--no-color"]
        + ["--exit-code=3", "--report-format=json", "--report-path=/out/gitleaks.json"],
        # --github-actions prints file:line annotations, never a value. The image's entrypoint
        # re-splits its last argument through bash, so that one is a constant.
        [*ro, trufflehog, "git", "file:///repo", f"--since-commit={base}", f"--branch={head}"]
        + ["--no-update", "--no-verification", "--github-actions", "--fail-on-scan-errors"]
        + ["--exclude-paths=/repo/.trufflehog-exclude", "--fail"],
    ]


@pytest.mark.parametrize(
    ("fake", "codes"),
    [
        ({"GITLEAKS_EXIT": "3", "GITLEAKS_REPORT": LEAK}, ["CI-SEC-001: gitleaks f"] * 2),
        ({"GITLEAKS_EXIT": "3"}, ["CI-SEC-001: gitleaks found"]),  # its own verdict, report or not
        ({"TRUFFLEHOG_EXIT": "183", "TRUFFLEHOG_OUT": ANNOTATION}, ["CI-SEC-001: trufflehog"]),
        ({"GITLEAKS_EXIT": "1", "GITLEAKS_REPORT": "none"}, ["CI-SEC-005: gitleaks"] * 2),
        ({"TRUFFLEHOG_EXIT": "2"}, ["CI-SEC-005: trufflehog exited 2"]),
        # A scanner that failed is never a clean scan, even beside a clean (empty) report.
        ({"GITLEAKS_EXIT": "1"}, ["CI-SEC-005: gitleaks exited 1"]),
        # gitleaks' exit code is not the only verdict: security_gate.py reads its report too.
        ({"GITLEAKS_EXIT": "0", "GITLEAKS_REPORT": LEAK}, ["CI-SEC-001: gitleaks finding"]),
        ({"GITLEAKS_EXIT": "0", "GITLEAKS_REPORT": "none"}, ["CI-SEC-005: gitleaks: unread"]),
    ],
    ids=["gitleaks-finding", "gitleaks-exit", "trufflehog-finding", "gitleaks-failed"]
    + ["trufflehog-failed", "gitleaks-failed-empty-report", "gitleaks-clean-exit-finding"]
    + ["gitleaks-clean-exit-no-report"],
)
def test_secret_scan_fails_on_any_finding_or_scanner_failure(
    tmp_path: Path, fake: dict[str, str], codes: list[str]
) -> None:
    code, output, _ = _scan_run(tmp_path, **fake)
    lines = [line for line in output.splitlines() if line.startswith("CI-SEC-")]
    assert (code, len(lines)) == (1, len(codes)), output
    assert all(line.startswith(prefix) for line, prefix in zip(lines, codes, strict=True)), lines
    # A finding is a committed secret: rotate it first (IR-02). Its file is named, never its value.
    # The step's own annotation follows the scanners' exit codes; the gate's hint, any finding.
    finding = codes[0].startswith("CI-SEC-001")
    flagged = fake.get("GITLEAKS_EXIT") == "3" or fake.get("TRUFFLEHOG_EXIT") == "183"
    assert (BLOCKS in output, "IR-02" in output) == (flagged, finding)
    named = finding and ("GITLEAKS_REPORT" in fake or "TRUFFLEHOG_OUT" in fake)
    assert ("docs/x.md" in output) == named


@pytest.mark.parametrize(
    ("base", "fake", "message"),
    [
        ("", {}, "CI-SEC-005: no PR commit range"),
        ("0" * 40, {}, "CI-SEC-005: the checkout lacks the PR's commits"),
        (None, {"SEEN": "0"}, "CI-SEC-005: the gitleaks image reads '0' of the PR's 1 commit(s)"),
    ],
    ids=["no-base", "base-not-fetched", "image-git-blind"],
)
def test_secret_scan_never_calls_a_range_it_could_not_read_clean(
    tmp_path: Path, base: str | None, fake: dict[str, str], message: str
) -> None:
    # gitleaks 8.30.1 exits 0 with an empty report on any git failure (an unknown commit, a bad
    # log option, no repository), so the step proves the range readable before either scanner.
    code, output, calls = _scan_run(tmp_path, base, **fake)
    assert (code, message in output) == (1, True), output
    assert not [call for call in calls if call[0] == "run" and "--entrypoint" not in call]


def test_secret_scan_checks_what_the_scanners_print_for_secret_shapes(tmp_path: Path) -> None:
    shaped = "gh" + "p_" + "Ab1" * 12  # built here, so this file holds no secret shape
    code, output, _ = _scan_run(tmp_path, TRUFFLEHOG_OUT=shaped)
    assert (code, "token-shape in log/artefact (SR-146)" in output) == (1, True), output


def test_secret_scan_reads_a_line_only_a_merge_commit_adds(tmp_path: Path) -> None:
    # A PR that merged its base instead of rebasing (C-4.12) can add a line only while resolving
    # the merge, and `git log -p` prints no patch for a merge commit. The fake gitleaks reads the
    # `git log` the real one runs, so the step must ask for merges diffed against a parent.
    code, output, _ = _scan_run(tmp_path, merged=True, GITLEAKS_FIND=MERGE_LINE)
    assert (code, "CI-SEC-001: gitleaks found" in output, BLOCKS in output) == (1, True, True)
    clean, output, _ = _scan_run(tmp_path / "clean", merged=True, GITLEAKS_FIND="not added")
    assert clean == 0, output


def test_secret_scan_fails_on_a_credential_hygiene_violation(tmp_path: Path) -> None:
    # SR-144 to SR-146: the step runs check_secrets_hygiene.py all, so a docs-only PR is held to
    # the hygiene gate too; here the checkout no longer ignores `.env`.
    code, output, _ = _scan_run(tmp_path, gitignore="")
    assert (code, "FAIL .gitignore: '.env' is not ignored" in output) == (1, True), output
    assert (BLOCKS in output, "CI-SEC-" in output) == (False, False), output
