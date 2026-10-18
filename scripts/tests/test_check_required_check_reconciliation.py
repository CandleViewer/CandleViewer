"""Unit tests for scripts/check_required_check_reconciliation.py (GOV-005)."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))

import check_required_check_reconciliation as recon

ROOT = SCRIPTS_DIR.parent


def _checks(*names: str) -> dict:
    return {"checks": [{"context": name, "app_id": 15368} for name in names]}


FIXTURE_CONSTITUTION = """\
## 9. Quality gates (required CI checks)

| # | Check name | Gate |
|---|---|---|
| 1 | `lint` | ESLint etc |
| 2 | `typecheck` | tsc etc |
| 3 | `unit-backend` | pytest |

## 10. Something else
"""


def _write_constitution(tmp_path: Path) -> Path:
    path = tmp_path / "CONSTITUTION.md"
    path.write_text(FIXTURE_CONSTITUTION, encoding="utf-8")
    return path


def test_load_constitution_check_names_extracts_all_rows(tmp_path: Path) -> None:
    path = _write_constitution(tmp_path)
    names = recon.load_constitution_check_names(str(path))
    assert names == ["lint", "typecheck", "unit-backend"]


def test_load_constitution_check_names_missing_table_raises(tmp_path: Path) -> None:
    path = tmp_path / "CONSTITUTION.md"
    path.write_text("no table here", encoding="utf-8")
    try:
        recon.load_constitution_check_names(str(path))
        assert False, "expected ReconciliationError"
    except recon.ReconciliationError:
        pass


# Regression: encodes E01-Q01 case 1.11 (originating case id) -- required-check
# reconciliation must stay clean when contexts/pending lists agree with §9.
def test_reconcile_clean_when_fully_covered() -> None:
    desired = {
        "required_status_checks": _checks("lint"),
        "pending_checks": {"typecheck": "why", "unit-backend": "why"},
    }
    errors = recon.reconcile(desired, ["lint", "typecheck", "unit-backend"], {"lint"})
    assert errors == []


def test_reconcile_credits_the_lanes_ci_required_judges_only_while_it_is_required() -> None:
    desired = {"required_status_checks": _checks("ci-required"), "pending_checks": {}}
    assert recon.reconcile(desired, ["lint"], {"ci-required"}, {"lint"}) == []
    desired["required_status_checks"] = _checks("lint")
    assert recon.reconcile(desired, ["lint", "typecheck"], {"lint"}, {"typecheck"}) != []


def test_reconcile_flags_unknown_context_name() -> None:
    desired = {
        "required_status_checks": _checks("not-a-real-check"),
        "pending_checks": {},
    }
    errors = recon.reconcile(desired, ["lint"], {"not-a-real-check"})
    assert any("not-a-real-check" in e for e in errors)


def test_reconcile_flags_missing_check_from_both_lists() -> None:
    desired = {
        "required_status_checks": _checks("lint"),
        "pending_checks": {},
    }
    errors = recon.reconcile(desired, ["lint", "typecheck"], {"lint"})
    assert any("typecheck" in e and "missing" in e for e in errors)


def test_reconcile_flags_an_enforced_or_unexplained_pending_check() -> None:
    desired = {
        "required_status_checks": _checks("lint"),
        "pending_checks": {"lint": "why", "typecheck": " ", "bogus": ""},
    }
    errors = recon.reconcile(desired, ["lint", "typecheck"], {"lint"})
    assert any("'lint' is enforced" in e for e in errors)
    assert any("'typecheck' is missing" in e for e in errors)  # a blank reason does not count
    assert any("'bogus' in branch-protection.json is not a §9 check" in e for e in errors)
    with pytest.raises(recon.ReconciliationError, match="pending_checks must be an object"):
        recon.reconcile({**desired, "pending_checks": ["typecheck"]}, ["lint"], {"lint"})


def test_reconcile_flags_required_context_without_workflow_job() -> None:
    desired = {
        "required_status_checks": _checks("lint"),
        "pending_checks": {},
    }
    errors = recon.reconcile(desired, ["lint"], workflow_job_names={"typecheck"})
    assert any("no check run named 'lint'" in e for e in errors)


def test_reconcile_fails_closed_when_no_workflow_reports_the_check() -> None:
    desired = {"required_status_checks": _checks("lint"), "pending_checks": {}}
    errors = recon.reconcile(desired, ["lint"], workflow_job_names=set())
    assert any("no check run named 'lint'" in e for e in errors)


def test_load_workflow_job_names_extracts_top_level_jobs(tmp_path: Path) -> None:
    wf_dir = tmp_path / "workflows"
    wf_dir.mkdir()
    (wf_dir / "ci.yml").write_text(
        "name: CI\non: [pull_request]\njobs:\n  lint:\n    runs-on: ubuntu-latest\n"
        "  typecheck:\n    runs-on: ubuntu-latest\n",
        encoding="utf-8",
    )
    names = recon.load_workflow_job_names(str(wf_dir / "*.yml"))
    assert names == {"lint", "typecheck"}


def test_load_workflow_job_names_reports_only_names_a_check_run_carries(tmp_path: Path) -> None:
    wf_dir = tmp_path / "workflows"
    wf_dir.mkdir()
    (wf_dir / "pr.yml").write_text(
        "on: [pull_request]\njobs:\n  lane:\n    uses: ./.github/workflows/_job.yml\n"
        "  plain:\n    runs-on: x\n  grid:\n    strategy:\n      matrix:\n        n: [1, 2]\n",
        encoding="utf-8",
    )
    (wf_dir / "_job.yml").write_text(
        "on:\n  workflow_call:\njobs:\n  lint:\n    runs-on: x\n"
        "  shard:\n    name: shard (${{ matrix.n }})\n",
        encoding="utf-8",
    )
    (wf_dir / "docs.yml").write_text(
        "on:\n  pull_request:\n    paths: [docs/**]\njobs:\n  docs:\n    runs-on: x\n",
        encoding="utf-8",
    )
    assert recon.load_workflow_job_names(str(wf_dir / "*.yml")) == {"lane / lint", "plain"}


def test_load_workflow_job_names_empty_when_no_files(tmp_path: Path) -> None:
    names = recon.load_workflow_job_names(str(tmp_path / "*.yml"))
    assert names == set()


# Security review of #3103: a branches or types filter can keep a check from a pull request to main.
def test_load_workflow_job_names_drops_workflows_a_trigger_filter_narrows(tmp_path: Path) -> None:
    triggers = {
        "kept": "types: [opened, synchronize, reopened, edited]\n    branches:\n      - main\n",
        "labelled": "types: [labeled, synchronize]\n",
        "release": "branches: [release]\n",
        "ignore": "branches-ignore: [dev]\n",
    }
    for job, trigger in triggers.items():
        text = f"on:\n  pull_request:\n    {trigger}jobs:\n  {job}:\n    runs-on: x\n"
        (tmp_path / f"{job}.yml").write_text(text, encoding="utf-8")
    assert recon.load_workflow_job_names(str(tmp_path / "*.yml")) == {"kept"}


def test_load_workflow_job_names_skips_reusable_and_unrelated_workflows() -> None:
    names = recon.load_workflow_job_names(str(ROOT / ".github/workflows/*.yml"))
    assert {"ci-required", "pr-metadata", "architecture", "governance", "js / lint"} <= names
    # _job-js.yml's jobs, lanes that call a reusable workflow, a matrix job, a schedule, and
    # docs-spike.yml's job, which does not run when a pull request opens
    unreported = {"lint", "typecheck", "js", "py", "contract", "e2e / e2e-web", "governance-drift"}
    assert not (unreported | {"docs-toolchain-spike"}) & names


# Security review of #3103: a lane's caller name would never arrive while its lane runs.
def test_reconcile_repo_refuses_a_required_lane_caller_name(tmp_path: Path) -> None:
    desired = json.loads((ROOT / ".github/branch-protection.json").read_text(encoding="utf-8"))
    desired["required_status_checks"]["checks"].append({"context": "contract", "app_id": 15368})
    path = tmp_path / "branch-protection.json"
    path.write_text(json.dumps(desired), encoding="utf-8")
    workflows = str(ROOT / ".github/workflows/*.yml")
    errors, _ = recon.reconcile_repo(str(path), str(ROOT / "CONSTITUTION.md"), workflows)
    assert any("no check run named 'contract'" in e for e in errors), errors


# #3103: the file requires only `ci-required`; prove it judges every C-9.1 check.
def test_repo_ci_required_judges_every_c91_check_or_the_file_lists_it_pending() -> None:
    errors, pending = recon.reconcile_repo(
        str(ROOT / ".github/branch-protection.json"),
        str(ROOT / "CONSTITUTION.md"),
        str(ROOT / ".github/workflows/*.yml"),
    )
    assert errors == []
    assert pending == ["bundle-size", "pr-metadata"]  # #3080 and #2280 update this as they land


DUPLICATE_JS_LANE = " js: {applicable: false, result: process.env.RESULT_JS},"
SPREAD = '              ...{ js: { applicable: false, result: "success" } },\n'
FILTER_JS = "FILTER_JS: ${{ needs.changed-paths.outputs.js }}"
COMMITLINT = '!== "false", result: process.env.RESULT_COMMITLINT'
ARCH_IF = "    if: ${{ always() && needs.changed-paths.outputs.py == 'true' }}\n"
JOB_COE = "$&    continue-on-error: true\n"
COE = "        continue-on-error: true\n"
VERDICT = "      - name: Verdict (every gate succeeded or was skipped)\n"
RESOLVE = "      - name: Resolve ci"
PIN_CHECK = "isTrue(process.env.FILTER_INFRA), result: process.env.RESULT_PIN_CHECK"
ARCH_STEP = (
    "      - name: Reflect the py lane's result (its py-checks job runs the architecture "
    "contract)\n        run: |\n"
)
# The same step as an indentless sequence entry, valid YAML that a fixed indentation would miss.
INDENTLESS = ARCH_STEP.replace("      - ", "    - ").replace(
    "        run", "      continue-on-error: true\n      run"
)
FORM = "plain block-style YAML"
FILTER_PY = "          FILTER_PY: ${{ needs.changed-paths.outputs.py }}\n"
RESULT_PY = "          RESULT_PY: ${{ needs.py.result }}\n"
CI_NAME = "    name: ci-required\n"
SETUP_NODE = '          node-version: "20"\n'
SHADOW = "  shadow:\n    name: ci-required\n    runs-on: x\n    steps:\n      - run: echo\n$&"
INSTALL = "    name: install\n"
NODE_CHECK = "    name: node-version-check (CI-JS-001)\n"
UNIT_ENGINE = "    name: unit-engine\n    needs: install\n"
PY_OUT = "      py: ${{ steps.filter.outputs.py }}\n"
JS_OUT = "      js: ${{ steps.filter.outputs.js }}\n"
PR_OUT = "      pr: ${{ steps.change.outputs.pr }}\n"
CONTRACT = "    uses: ./.github/workflows/_job-contract.yml\n"
MIGRATIONS = "    uses: ./.github/workflows/_job-migrations.yml\n"
REMOTE = CONTRACT.replace("./", "o/r/").replace(".yml", ".yml@" + "0" * 40)
ARCH_RUN = "the architecture contract)\n"
ARCH_NAME = "    name: architecture\n"
# The C-9.1 checks credited by the name of the lane that runs them: workflow, a job, the check.
NAMED_LANES = [
    ("_job-contract.yml", "contract", "contract"),
    ("_job-integration.yml", "integration", "integration"),
    ("_job-a11y.yml", "a11y", "a11y"),
    ("_job-engine-bench.yml", "engine-bench-stub", "engine-bench"),
    ("_job-migrations.yml", "migrations", "migrations"),
]
SPARE = "\n  spare:\n    if: false\n    runs-on: x\n    steps:\n      - run: echo$&"
FILTER_STEP = "one step `filter`, which uses dorny/paths-filter pinned"


@pytest.mark.parametrize(
    "workflow,old,new,expected",
    [
        ("pr.yml", "      - contract\n", "", "§9 check 'contract' is missing"),
        ("pr.yml", "result: process.env.RESULT_SECURITY,", "result: process.env.X,", "'sast'"),
        (
            "pr.yml",
            "applicable: isTrue(process.env.FILTER_E2E), result: process.env.RESULT_E2E",
            "applicable: false, result: process.env.RESULT_E2E",
            "'e2e-smoke'",
        ),
        (
            "pr.yml",
            "    if: always()\n    needs:\n      - changed-paths\n      - gates",
            "    needs:\n      - changed-paths\n      - gates",
            "if: always()",
        ),
        ("_job-security.yml", "\n  trivy:\n", "\n  trivy-scan:\n", "'container-scan'] is stale"),
        # Each lane's result must come from its own job or gates output (security review, #3103).
        ("pr.yml", "needs.contract.result", "needs.integration.result", "'contract' is missing"),
        ("pr.yml", "needs.gates.outputs.gen ", "needs.gates.outputs.commitlint ", "no judged gen"),
        ("pr.yml", "gen: ${{ steps.gen.outcome", "gen: ${{ steps.commitlint.outcome", "judged gen"),
        # Code review of #3103: each probe that stayed green.
        ("pr.yml", '"secret-scan": { applicable: true', '"x": { applicable: true', "secret-scan"),
        ("pr.yml", " py: {", DUPLICATE_JS_LANE + " py: {", "lane 'js' repeats"),
        ("pr.yml", "  node scripts/ci_gate", "  true || node scripts/ci_gate", "exit"),
        ("pr.yml", "          ')\"\n", "          ')\" || true\n", "whose exit is the resolver's"),
        ("pr.yml", "conclusion\n", "conclusion\n        continue-on-error: true\n", "continue-on"),
        ("_job-security.yml", "if: ${{ inputs.image_changed }}", "if: ${{ false }}", "trivy"),
        # Review round 2 of #3103: each half of a check that runs in two lanes is required.
        ("_job-py.yml", "\n  py-checks:\n", "\n  py-lint:\n", "'lint'] is stale: no judged py/py"),
        (
            "pr.yml",
            "py: { applicable: isTrue(process.env.FILTER_PY), result: process.env.RESULT_PY }",
            "py: { applicable: false, result: process.env.RESULT_PY }",
            "LANE_ALIASES['typecheck'] is stale",
        ),
        # ... and each way the resolver step, its program or a lane job stops judging lanes.
        ("pr.yml", "conclusion\n", "conclusion\n        if: ${{ false }}\n", "with no `if:`"),
        ("pr.yml", "conclusion\n", "conclusion\n        shell: bash -c true {0}\n", "or shell:"),
        ("pr.yml", "      - name: Resolve ci", "      - uses: ./x\n$&", "with steps checkout"),
        ("pr.yml", "            console.log(", "            delete lanes.js;\n$&", "program"),
        ("pr.yml", "console.log(JSON.stringify(lanes));", 'console.log("{}");', "program"),
        ("pr.yml", '(v) => v === "true"', "(v) => false", "program must be"),
        ("pr.yml", "            };\n            console.log(", SPREAD + "$&", "more than lanes"),
        ("pr.yml", '"secret-scan": { applicable: ', "$&process.exit(0) || ", "more than lanes"),
        ("pr.yml", FILTER_JS, FILTER_JS.replace(".js", ".py"), "lane 'js' reads ['FILTER_JS']"),
        ("pr.yml", COMMITLINT, COMMITLINT.replace("false", "true"), "more than lanes"),
        ("_job-security.yml", "name: trivy\n", "$&    continue-on-error: true\n", "trivy"),
        # Review round 3 of #3103: every job `ci-required` needs fails when its work fails ...
        ("pr.yml", "    name: architecture\n", JOB_COE, "job 'architecture' must fail"),
        ("pr.yml", ARCH_IF, "    if: false\n", "job 'architecture' must fail"),
        ("pr.yml", "the architecture contract)\n", "$&" + COE, "job 'architecture' must fail"),
        ("pr.yml", ARCH_STEP, INDENTLESS, "job 'architecture' must fail"),
        ("pr.yml", "    name: changed-paths\n", JOB_COE, "job 'changed-paths' must fail"),
        ("pr.yml", "        id: filter\n", "$&" + COE, "job 'changed-paths' must fail"),
        ("pr.yml", VERDICT, "$&" + COE, "job 'gates' must fail"),
        # (a `gates` step may continue on error only while its outcome is a judged lane)
        ("pr.yml", PIN_CHECK, "false, result: process.env.RESULT_PIN_CHECK", "job 'gates' must"),
        # ... and its step is the resolver call alone, whatever shell a default or alias sets.
        ("pr.yml", "          ')\"\n", "$&          true\n", "whose exit is the resolver's"),
        ("pr.yml", "          ')\"\n", "$&\n          true\n", "whose exit is the resolver's"),
        ("pr.yml", "\nconcurrency:\n", "\ndefaults:\n  run:\n    shell: bash {0}$&", "or shell:"),
        ("pr.yml", "    name: ci-required\n", "$&    defaults: {run: {shell: sh}}\n", FORM),
        ("pr.yml", RESOLVE, "      - shell: sh\n        name: Resolve ci", "or shell:"),
        ("pr.yml", RESOLVE, "      - *step\n$&", "YAML anchor"),
        ("_job-security.yml", "if: ${{ inputs.image_changed }}", "if: *off", "YAML anchor"),
        # Review round 4 of #3103: a trailing comment or quotes leave a literal false in force ...
        (
            "pr.yml",
            "        id: filter\n",
            "$&        if: ${{ false }} # off\n",
            "'changed-paths' must",
        ),
        (
            "pr.yml",
            "the architecture contract)\n",
            "$&        if: false # off\n",
            "'architecture' must",
        ),
        (
            "pr.yml",
            "the architecture contract)\n",
            "$&        if: 'false'\n",
            "'architecture' must",
        ),
        ("_job-security.yml", "if: ${{ inputs.image_changed }}", "if: false # off", "trivy"),
        # ... and any other spelling of a key, or a value on another line, is refused.
        ("pr.yml", "    name: architecture\n", '$&    "continue-on-error": true\n', FORM),
        ("pr.yml", "        id: filter\n", "$&        'continue-on-error': true\n", FORM),
        ("pr.yml", "    name: architecture\n", "$&    continue-on-error : true\n", FORM),
        ("pr.yml", "    name: architecture\n", "$&    ? continue-on-error\n    : true\n", FORM),
        ("pr.yml", ARCH_STEP, '      - {run: "true", continue-on-error: true}\n$&', FORM),
        ("pr.yml", "the architecture contract)\n", "$&        if: !!str false\n", FORM),
        ("pr.yml", "the architecture contract)\n", "$&        if: >-\n          false\n", "'archi"),
        ("pr.yml", RESOLVE, '      - "shell": sh\n        name: Resolve ci', FORM),
        ("pr.yml", CI_NAME, '$&    "defaults": {run: {shell: sh}}\n', FORM),
        (
            "pr.yml",
            CI_NAME + "    if: always()\n",
            '    name: "ci-required\n    if: always()\n    "\n',
            FORM,
        ),
        ("_job-security.yml", "name: trivy\n", '$&    "continue-on-error": true\n', FORM),
        # `ci-required` reads only its resolver step's own env (a step's env wins at runtime) ...
        (
            "pr.yml",
            (FILTER_PY, CI_NAME),
            ('          FILTER_PY: "false"\n', "$&    env:\n" + FILTER_PY[4:]),
            "no job keys but",
        ),
        (
            "pr.yml",
            (RESULT_PY, CI_NAME),
            ("          RESULT_PY: success\n", "$&    env:\n" + RESULT_PY[4:]),
            "no job keys but",
        ),
        (
            "pr.yml",
            (RESULT_PY, SETUP_NODE + RESOLVE),
            ("          RESULT_PY: success\n", SETUP_NODE + "        env:\n" + RESULT_PY + RESOLVE),
            "the resolver step's env",
        ),
        (
            "pr.yml",
            "        env:\n          FILTER_JS",
            "        env:\n          A: b\n$&",
            "step's env",
        ),
        ("pr.yml", "\nconcurrency:\n", "\nenv:\n  NODE_OPTIONS: --x$&", "may set no env"),
        (
            "pr.yml",
            RESOLVE,
            "      - working-directory: x\n        name: Resolve ci",
            "no keys but",
        ),
        ("pr.yml", CI_NAME, "$&    container: node:20\n", "no job keys but"),
        # ... and no other job may report a check run of its name.
        ("pr.yml", "  ci-required:\n", SHADOW, "the check-run name of 2 jobs"),
        # Review round 5 of #3103: an `if:` that reads no context is a constant (YAML's False and
        # FALSE are false too), so the proof refuses it whatever its value.
        ("_job-security.yml", "if: ${{ inputs.image_changed }}", "if: False", "trivy"),
        ("_job-security.yml", "if: ${{ inputs.image_changed }}", "if: 0", "trivy"),
        ("_job-js.yml", "    name: lint\n", "$&    if: FALSE\n", "no judged js/lint"),
        ("pr.yml", "        id: filter\n", "$&        if: False\n", "'changed-paths' must"),
        ("pr.yml", ARCH_RUN, "$&        if: ${{ 0 }}\n", "'architecture' must"),
        ("pr.yml", ARCH_RUN, "$&        if: null\n", "'architecture' must"),
        ("pr.yml", ARCH_NAME, '$&    defaults: {"run":{"shell":"sh"}}\n', "a flow mapping"),
        # ... and a called job that needs a job that never runs is skipped, which passes its lane.
        ("_job-js.yml", INSTALL, "$&    if: false\n", "§9 check 'unit-frontend' is missing"),
        ("_job-js.yml", NODE_CHECK, "$&    if: false\n", "§9 check 'unit-engine' is missing"),
        (
            "_job-js.yml",
            (INSTALL, UNIT_ENGINE),
            ("$&    if: false\n", "    name: unit-engine\n    needs:\n    - install # a list\n"),
            "§9 check 'unit-engine' is missing",
        ),
        ("_job-js.yml", UNIT_ENGINE, UNIT_ENGINE.replace(" i", " >-\n      i"), "'unit-engine' is"),
        # ... and changed-paths, which decides which lanes apply: each output a FILTER_ name reads
        # comes from the step that sets it, and nothing in the job runs on a condition.
        ("pr.yml", PY_OUT, "      py: 'false'\n", "lane 'py' reads ['FILTER_PY']"),
        ("pr.yml", JS_OUT, JS_OUT.replace(".js", ".none"), "lane 'js' reads ['FILTER_JS']"),
        ("pr.yml", PR_OUT, PR_OUT.replace("change", "filter"), "'commitlint' reads ['FILTER_PR']"),
        ("pr.yml", "        id: filter\n", "$&        if: ${{ github.run_id < 0 }}\n", "decides"),
        ("pr.yml", "        id: change\n", "$&        if: ${{ github.run_id < 0 }}\n", "decides"),
        # ... and a lane credited by name calls a workflow of this repository the proof reads.
        ("pr.yml", CONTRACT, REMOTE, "lane 'contract' calls"),
        ("pr.yml", MIGRATIONS, MIGRATIONS.replace("./", '"./').replace("\n", '"\n'), "calls"),
        # Review round 6: a lane's own name counts only while every job it calls can fail it,
        # one of several included (integration's other job, a spare job beside engine-bench's).
        *[
            (workflow, f"\n  {job}:\n", f"$&    {never}\n", f"§9 check '{check}' is missing")
            for workflow, job, check in NAMED_LANES
            for never in ("if: false", "continue-on-error: true")
        ],
        ("_job-engine-bench.yml", "\n  engine-bench-stub:\n", SPARE, "'engine-bench' is missing"),
        # ... and the step whose outputs decide which lanes apply is the pinned paths filter.
        ("pr.yml", "dorny/paths-filter@", "other/paths-filter@", FILTER_STEP),
        ("pr.yml", "filter@ceb8a2b8f2d89434be7ff52d3de7ec3738c5cc9d", "filter@v4", FILTER_STEP),
    ],
)
def test_dropping_a_lane_from_ci_required_fails_the_proof(
    tmp_path, workflow, old, new, expected
) -> None:
    olds, news = (old, new) if isinstance(old, tuple) else ((old,), (new,))
    errors = _prove(tmp_path, workflow, *zip(olds, news, strict=True))
    assert any(expected in e for e in errors), errors


def _prove(tmp_path: Path, workflow: str, *edits: tuple[str, str], reindent: str = "") -> list:
    """The proof's errors once each `(old, new)` edit (`$&` is old), then a two-space indent of
    every line after the `reindent` marker, are made to a copy of `workflow`."""
    workflows = tmp_path / "workflows"
    shutil.copytree(ROOT / ".github/workflows", workflows)
    text = (workflows / workflow).read_text(encoding="utf-8")
    for old, new in edits:
        assert text.count(old) == 1, old
        text = text.replace(old, new.replace("$&", old))
    if reindent:
        head, _, tail = text.partition(reindent)
        text = head + reindent + "".join(f"  {line}" for line in tail.splitlines(True))
    (workflows / workflow).write_text(text, encoding="utf-8")
    errors, _ = recon.reconcile_repo(
        str(ROOT / ".github/branch-protection.json"),
        str(ROOT / "CONSTITUTION.md"),
        str(workflows / "*.yml"),
    )
    return errors


# Review round 4 of #3103: valid YAML whose shape the proof misread. A resolver call inside an
# action step's block scalar, with no real resolver step; a called job whose keys sit at 6 spaces.
@pytest.mark.parametrize(
    "workflow,edit,reindent,expected",
    [
        (
            "pr.yml",
            (
                RESOLVE + "-required conclusion\n",
                "      - uses: actions/setup-node@949feb2413d6458794dcd2491c4babbbce0c15c1\n"
                "        name: |\n",
            ),
            "c15c1\n        name: |\n",
            "no keys but",
        ),
        (
            "_job-security.yml",
            ("if: ${{ inputs.image_changed }}", "if: false"),
            "\n  trivy:\n",
            "'container-scan'] is stale",
        ),
        # Round 6: jobs at 4 spaces, valid YAML, where the proof reads no job of the lane.
        ("_job-contract.yml", ("\njobs:\n", "$&"), "\njobs:\n", "§9 check 'contract' is missing"),
    ],
)
def test_a_shape_the_proof_cannot_read_fails_it(tmp_path, workflow, edit, reindent, expected):
    errors = _prove(tmp_path, workflow, edit, reindent=reindent)
    assert any(expected in e for e in errors), errors


# Review round 5 of #3103: a job of any workflow, `.yaml` too, whose name may read `ci-required`.
@pytest.mark.parametrize(
    "file,job",
    [
        ("shadow.yaml", "    name: ci-required\n    runs-on: x\n"),
        ("shadow.yml", "    name: 'ci-required' # quoted\n    runs-on: x\n"),
        ("shadow.yml", '    name: "ci-required"\n    runs-on: x\n'),
        ("shadow.yml", '    name: "ci\\x2drequired"\n    runs-on: x\n'),
        ("shadow.yml", "    name: >-\n      ci-required\n    runs-on: x\n"),
        ("shadow.yml", "    name: ${{ 'ci-required' }}\n    runs-on: x\n"),
        ("shadow.yml", "    name: ci-${{ 'required' }} # any text\n    runs-on: x\n"),
        ("shadow.yml", "      name: ci-required\n      runs-on: x\n"),
    ],
)
def test_a_job_that_may_report_as_ci_required_fails_the_proof(tmp_path, file, job) -> None:
    workflows = tmp_path / "workflows"
    shutil.copytree(ROOT / ".github/workflows", workflows)
    (workflows / file).write_text(f"on: [push]\njobs:\n  shadow:\n{job}", encoding="utf-8")
    errors, _ = recon.reconcile_repo(
        str(ROOT / ".github/branch-protection.json"),
        str(ROOT / "CONSTITUTION.md"),
        str(workflows / "*.yml"),
    )
    assert any("the check-run name of 2 jobs" in e for e in errors), errors
