"""`pr.yml` path filters: a PR that edits only what a gate checks still runs that gate.

#2915: the `security` job runs when only a Semgrep gate path changes.

`.semgrep/**` (the cv-* rules and their rule-test fixtures), `.semgrep-fixtures/**`,
`.semgrepignore` and `tools/ci/check_semgrep_rule_tests.py` are what the Semgrep rule-test checker
and the product scan read. No `changed-paths` filter named them and `security` ran only on
js/py/infra changes, so a PR that edited just a rule, a fixture or the ignore file skipped the
gates built to check exactly that change.

The `ci-required` resolver restates the `security` condition by hand, and
scripts/ci_gate_resolver.mjs treats a lane that ran while "not applicable" as fine. A Semgrep-only
run that failed would therefore stay green in `ci-required` unless the resolver names the same
filters as the job, so these tests pin the filter, the job condition and the resolver together.

#2963: the tests that pin `.github/workflows/xstate-nightly.yml` (#2807) run in the `py` lane, but
its filter did not name the workflow, so a PR that edited only the workflow skipped them.

#3175: the required `a11y` job runs on the `e2e` filter, which did not name the design system
(`packages/ui/**`, its Storybook included) or the job's other inputs (`tools/contrast/**` and the
token formats it imports for the contrast gate, `tools/a11y/**` for the axe baseline and gates, the
job's workflow and its meta-tests), so a PR that changed only those skipped the axe sweep.

#3230: the `js` filter, which gates `lint`, `typecheck`, `unit-frontend`, `unit-engine` and, through
`js`, the `security` and `coverage-thresholds` jobs, did not name `packages/chart-engine` or
`packages/protocol`, so a PR that changed only one of them merged without any of those checks.

#3104: the `py` filter named only `tools/statechart/nightly_gate.py`, so a PR that changed only a
script a `py`-filtered `gates` step runs from `tools/statechart/` (event coverage, the suite budget,
the machine-hash lock, the xstate-contract script) skipped the gate built to check it.
"""

from __future__ import annotations

import json
import re
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
PR_YML = ROOT / ".github" / "workflows" / "pr.yml"
SEMGREP_PATHS = (
    ".semgrep/**",
    ".semgrep-fixtures/**",
    ".semgrepignore",
    "security/semgrep/**",
    "tools/ci/check_semgrep_rule_tests.py",
)
RESOLVER_STEP = "Resolve ci-required conclusion"
XSTATE_NIGHTLY = ".github/workflows/xstate-nightly.yml"
STATECHART_TOOLS = "tools/statechart/**"
XSTATE_CONTRACT_SCRIPT = "tools/statechart/run_xstate_contract.sh"
WORKSPACE = ROOT / "pnpm-workspace.yaml"
#: The package.json scripts the js lane runs for a workspace package (_job-js.yml).
JS_LANE_SCRIPTS = frozenset({"lint", "typecheck", "test", "test:cov", "build"})
A11Y_PATHS = (
    "packages/ui/**",
    "tools/contrast/**",
    "tools/style-dictionary/**",
    "tools/a11y/**",
    ".github/workflows/_job-a11y.yml",
    "scripts/tests/test_a11y_gates.py",
)


def _jobs() -> dict[str, Any]:
    jobs: dict[str, Any] = yaml.safe_load(PR_YML.read_text(encoding="utf-8"))["jobs"]
    return jobs


def _single(matches: list[dict[str, Any]], what: str) -> dict[str, Any]:
    assert len(matches) == 1, f"expected exactly one {what} in pr.yml, found {len(matches)}"
    return matches[0]


def _filters() -> dict[str, list[str]]:
    """The `dorny/paths-filter` rules of the `changed-paths` job (its `filters:` block is YAML)."""
    steps = _jobs()["changed-paths"]["steps"]
    step = _single(
        [s for s in steps if str(s.get("uses", "")).startswith("dorny/paths-filter@")],
        "`dorny/paths-filter` step in `changed-paths`",
    )
    filters: dict[str, list[str]] = yaml.safe_load(step["with"]["filters"])
    return filters


_OUTPUT_TERM = re.compile(r"needs\.changed-paths\.outputs\.(\w+) == 'true'")


def _outputs_in(condition: str) -> set[str]:
    """The `changed-paths` outputs a job `if:` ORs together.

    The expression is split on `||` and each term must be exactly
    `needs.changed-paths.outputs.<name> == 'true'`, so an `&&`, a `!=` or a stray operator fails
    here instead of being skipped over by a search.
    """
    wrapped = re.fullmatch(r"\s*\$\{\{(.*)\}\}\s*", condition, re.DOTALL)
    assert wrapped, f"not a `${{{{ ... }}}}` expression: {condition!r}"
    names: set[str] = set()
    for term in wrapped.group(1).split("||"):
        match = _OUTPUT_TERM.fullmatch(term.strip())
        assert match, f"not a `needs.changed-paths.outputs.<name> == 'true'` term: {term.strip()!r}"
        names.add(match.group(1))
    return names


def _resolver_step() -> dict[str, Any]:
    steps: list[dict[str, Any]] = _jobs()["ci-required"]["steps"]
    return _single([s for s in steps if s.get("name") == RESOLVER_STEP], f"`{RESOLVER_STEP}` step")


_RESOLVER_TERM = re.compile(r"isTrue\(process\.env\.FILTER_(\w+)\)")


def _resolver_security_filters() -> set[str]:
    """The filters the resolver script ORs together when it decides whether `security` applied."""
    return _resolver_lane_filters("security")


def _resolver_lane_filters(name: str) -> set[str]:
    """The filters the resolver ORs together to decide whether lane `name` (unquoted key) applied.

    `//` comments are stripped first, so a name that only a comment mentions does not count. Then
    each `||` term must be exactly `isTrue(process.env.FILTER_<NAME>)`, so an `&&` or a `!` fails.
    """
    lane = re.search(
        rf"\b{re.escape(name)}:\s*\{{\s*applicable:(.*?)\bresult:\s*process\.env\.RESULT_{name.upper()}\b",
        _resolver_step()["run"],
        re.DOTALL,
    )
    assert lane, f"the ci-required resolver script has no `{name}` lane"
    expression = re.sub(r"//[^\n]*", "", lane.group(1)).strip().removesuffix(",")
    names: set[str] = set()
    for term in expression.split("||"):
        match = _RESOLVER_TERM.fullmatch(term.strip())
        assert match, f"not an `isTrue(process.env.FILTER_<NAME>)` term: {term.strip()!r}"
        names.add(match.group(1).lower())
    return names


def test_pr_yml_semgrep_filter_covers_every_semgrep_gate_path() -> None:
    covered = set(_filters().get("semgrep") or [])
    assert set(SEMGREP_PATHS) <= covered, sorted(set(SEMGREP_PATHS) - covered)


def test_pr_yml_semgrep_filter_paths_exist_in_the_repo() -> None:
    # A path that was renamed away would leave the filter matching nothing, silently. This checks
    # what pr.yml actually lists, not the pinned constant, so an added or mistyped entry is caught.
    for pattern in _filters().get("semgrep") or []:
        assert any(ROOT.glob(pattern)), pattern


@pytest.mark.parametrize("name", ["semgrep", "e2e"])
def test_pr_yml_changed_paths_exports_each_filter_as_its_own_output(name: str) -> None:
    outputs = _jobs()["changed-paths"]["outputs"]
    assert outputs.get(name) == "${{ steps.filter.outputs." + name + " }}"


def test_pr_yml_security_job_runs_when_only_semgrep_paths_change() -> None:
    assert "semgrep" in _outputs_in(_jobs()["security"]["if"])


def test_pr_yml_resolver_security_lane_names_the_same_filters_as_the_job() -> None:
    # Otherwise a failing `security` run that the job condition let through is "not applicable"
    # to the resolver, and ci-required stays green over it.
    assert _resolver_security_filters() == _outputs_in(_jobs()["security"]["if"])


@pytest.mark.parametrize("lane", ["security", "a11y", "js"])
def test_pr_yml_resolver_reads_each_lane_filter_from_its_changed_paths_output(lane: str) -> None:
    env = _resolver_step()["env"]
    for name in sorted(_resolver_lane_filters(lane)):
        expected = "${{ needs.changed-paths.outputs." + name + " }}"
        assert env.get("FILTER_" + name.upper()) == expected, name
    # The lane is judged on its own job's result, never another job's.
    assert env.get("RESULT_" + lane.upper()) == "${{ needs." + lane + ".result }}"


def test_pr_yml_py_filter_covers_the_xstate_nightly_workflow() -> None:
    # services/api/tests/unit/statechart/test_xstate_gate_env_skip.py pins that workflow (#2807)
    # and runs in the `py` lane, so a PR that edits only the workflow must start the lane.
    assert (ROOT / XSTATE_NIGHTLY).is_file()
    assert XSTATE_NIGHTLY in _filters()["py"]


def test_pr_yml_py_filter_covers_every_statechart_tool_a_py_gate_runs() -> None:
    # What the `gates` steps the py filter starts run from tools/statechart/, scripts followed.
    steps = [s for s in _jobs()["gates"]["steps"] if "outputs.py ==" in str(s.get("if", ""))]
    text = "\n".join(str(s.get("run", "")) for s in steps)
    for script in re.findall(r"tools/statechart/[\w.]+\.sh", text):
        text += (ROOT / script).read_text(encoding="utf-8")
    used = set(re.findall(r"tools/statechart/[\w.]+", text))
    assert XSTATE_CONTRACT_SCRIPT in used and len(used) >= 4, sorted(used)
    py = _filters()["py"]
    assert STATECHART_TOOLS in py and any(ROOT.glob(STATECHART_TOOLS))
    for path in sorted(used):
        assert (ROOT / path).is_file() and any(fnmatch(path, rule) for rule in py), path


def test_pr_yml_e2e_filter_covers_every_a11y_input() -> None:
    covered = set(_filters()["e2e"])
    assert set(A11Y_PATHS) <= covered, sorted(set(A11Y_PATHS) - covered)


def test_pr_yml_e2e_filter_paths_exist_in_the_repo() -> None:
    # What pr.yml lists, not the pinned constant, so an added or mistyped entry is caught.
    for pattern in _filters()["e2e"]:
        assert any(ROOT.glob(pattern)), pattern


def test_pr_yml_a11y_job_and_resolver_lane_read_the_same_filters() -> None:
    # The a11y job runs on the e2e filter; the resolver must judge it on the same filter, or a
    # failing run the job condition let through is "not applicable" and ci-required stays green.
    job = _outputs_in(_jobs()["a11y"]["if"])
    assert "e2e" in job
    assert _resolver_lane_filters("a11y") == job


def _js_workspace_packages() -> list[str]:
    """Workspace packages (pnpm-workspace.yaml) whose package.json has a script the js lane runs."""
    patterns: list[str] = yaml.safe_load(WORKSPACE.read_text(encoding="utf-8"))["packages"]
    found: list[str] = []
    for pattern in patterns:
        for manifest in sorted(ROOT.glob(pattern + "/package.json")):
            scripts = json.loads(manifest.read_text(encoding="utf-8")).get("scripts") or {}
            if JS_LANE_SCRIPTS & set(scripts):
                found.append(manifest.parent.relative_to(ROOT).as_posix())
    return found


def test_pr_yml_js_filter_covers_every_workspace_package_the_js_lane_checks() -> None:
    # A package the js lane lints, type-checks or tests must start the lane when only it changes.
    packages = _js_workspace_packages()
    assert {"packages/chart-engine", "packages/protocol"} <= set(packages)
    covered = set(_filters()["js"])
    assert [p for p in packages if p + "/**" not in covered] == []


def test_pr_yml_js_job_and_resolver_lane_read_the_same_filters() -> None:
    job = _outputs_in(_jobs()["js"]["if"])
    assert "js" in job
    assert _resolver_lane_filters("js") == job
