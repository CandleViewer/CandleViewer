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

#3182: a lane must start on its own inputs: its job's workflow, the scripts its steps run (derived
below from run lines and `with:` inputs, so a new script or config needs a filter entry) and the
files they read (READ_INPUTS); js also the token formats packages/ui imports, py the a11y gate logic
and the fixture corpus. Every lane's `if:` and resolver entry read the same filters, from
`steps.filter`. Pytest targets are not followed: contract's and migrations' suites, outside their
filters, run in the py and integration lanes too.
"""

from __future__ import annotations

import functools
import json
import posixpath
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
#: The e2e job's own inputs (#3182): its workflow, then the two guards its steps run.
E2E_PATHS = (
    ".github/workflows/_job-e2e.yml",
    "tools/ci/check_demo_rest_only_tag.mjs",
    "tools/ci/check_built_exports.mjs",
)
TOKEN_FORMATS = "tools/style-dictionary/**"
#: Read beyond services/api (#3182): the a11y gate logic, which the security lane's Semgrep scan
#: reads like scripts/**/*.py, and the corpora and account pack the backend suites and cvdev load.
PY_INPUTS = ("tools/a11y/**/*.py", "packages/fixtures/**")
#: Files a lane's steps read through a script or a container that the run-line derivation below
#: cannot follow (#3182): (lane, the file the lane runs that names it, the file read).
READ_INPUTS = (
    ("security", ".github/workflows/_job-security.yml", ".gitleaks.toml"),  # --config=/repo/...
    ("security", ".github/workflows/_job-security.yml", ".trufflehog-exclude"),
    ("security", "tools/ci/security_gate.py", "security/accepted-risks.yaml"),
    ("security", "tools/ci/check_freeze_manifest.py", "security/freeze-manifest.sha256"),
    ("security", "scripts/check_secrets_hygiene.py", ".gitignore"),  # the SR-144 dev-env check
    ("security", "scripts/check_secrets_hygiene.py", ".env.example"),
    ("js", "tools/ci/run-allowed-postinstall.mjs", "tools/ci/allowed-postinstall.json"),
    ("engine-bench", "tools/ci/run-allowed-postinstall.mjs", "tools/ci/allowed-postinstall.json"),
    ("migrations", "tools/ci/migration_lint.py", "tools/ci/security-sensitive-tables.txt"),
)
FILTER_NAMES: tuple[str, ...] = ("js", "py", "engine", "protocol", "infra", "image", "docs")
FILTER_NAMES += ("e2e", "migrations", "rules", "semgrep")
#: Not a path filter: the event's `changed-paths` output, false on a merge group (#3433).
PR_CONTEXT = frozenset({"pr"})
#: Lane -> the filters that make it applicable: its `if:` and the resolver read the same (#3182).
LANE_FILTERS: dict[str, frozenset[str]] = {
    **dict.fromkeys(["changed-paths", "gates", "gen", "spike-containment"], frozenset()),
    **dict.fromkeys(["commitlint", "changelog-fragment"], PR_CONTEXT),
    "licence-header": frozenset(),
    # #3385: every PR, a docs-only one too, gets the secret scans.
    **dict.fromkeys(["docs-link-check", "secret-scan"], frozenset()),
    "backlog-twin-eol": frozenset(),  # #3495: every PR, as validate.py --check cannot see a blob
    "pin-check": frozenset({"infra"}),
    **dict.fromkeys(["py", "architecture", "integration", "statechart-lint"], frozenset({"py"})),
    **dict.fromkeys(["event-coverage", "xstate-pin-attestation"], frozenset({"py"})),
    **dict.fromkeys(["machine-hash-lock", "xstate-contract"], frozenset({"py"})),
    "js": frozenset({"js"}),
    "rule-roundtrip": frozenset({"rules"}),
    "contract": frozenset({"protocol"}),
    "migrations": frozenset({"migrations"}),
    "security": frozenset({"js", "py", "infra", "semgrep"}),
    **dict.fromkeys(["e2e", "a11y"], frozenset({"e2e"})),
    "engine-bench": frozenset({"engine", "protocol"}),
    "coverage-thresholds": frozenset({"js", "py"}),
}


def _jobs() -> dict[str, Any]:
    jobs: dict[str, Any] = yaml.safe_load(PR_YML.read_text(encoding="utf-8"))["jobs"]
    return jobs


def _single(matches: list[dict[str, Any]], what: str) -> dict[str, Any]:
    assert len(matches) == 1, f"expected exactly one {what} in pr.yml, found {len(matches)}"
    return matches[0]


def _filter_step() -> dict[str, Any]:
    steps = _jobs()["changed-paths"]["steps"]
    return _single(
        [s for s in steps if str(s.get("uses", "")).startswith("dorny/paths-filter@")],
        "`dorny/paths-filter` step in `changed-paths`",
    )


def _filters() -> dict[str, list[str]]:
    """The `dorny/paths-filter` rules of the `changed-paths` job (its `filters:` block is YAML)."""
    filters: dict[str, list[str]] = yaml.safe_load(_filter_step()["with"]["filters"])
    return filters


#: The `pr` output fails closed (#3433): a PR-metadata gate skips only where it is false.
_OUTPUT_TERM = re.compile(r"needs\.changed-paths\.outputs\.(?:(\w+) == 'true'|(pr) != 'false')")


def _outputs_in(condition: str) -> set[str]:
    """The `changed-paths` outputs a job `if:` ORs together.

    The expression is split on `||` and each term must be exactly
    `needs.changed-paths.outputs.<name> == 'true'` (`pr`: `!= 'false'`), so an `&&`, any other
    `!=` or a stray operator fails here instead of being skipped over by a search.
    """
    wrapped = re.fullmatch(r"\s*\$\{\{(.*)\}\}\s*", condition, re.DOTALL)
    assert wrapped, f"not a `${{{{ ... }}}}` expression: {condition!r}"
    names: set[str] = set()
    for term in wrapped.group(1).split("||"):
        match = _OUTPUT_TERM.fullmatch(term.strip())
        assert match, f"not a `needs.changed-paths.outputs.<name> == 'true'` term: {term.strip()!r}"
        names.add(match[1] or match[2])
    return names


def _if_filters(condition: object) -> set[str]:
    """The filters a job or `gates` step `if:` ORs together after `always() &&`/`!cancelled() &&`.

    No `if:`, or nothing past the prefix, is an always-on lane: no filter.
    """
    text = str(condition or "true")
    wrapped = re.fullmatch(r"\$\{\{ (.*) \}\}", text, re.DOTALL)
    body = wrapped.group(1) if wrapped else text
    rest = re.sub(r"^(?:always\(\)|!cancelled\(\))(?: && |$)", "", body)
    if rest in ("", "true"):
        return set()
    return _outputs_in("${{ " + rest.removeprefix("(").removesuffix(")") + " }}")


def _lane_if(lane: str) -> object:
    """The `if:` that starts lane `lane`: its job's, or for a gate its `gates` step's."""
    jobs = _jobs()
    if lane in jobs:
        return jobs[lane].get("if")
    steps: list[dict[str, Any]] = jobs["gates"]["steps"]
    return _single([s for s in steps if s.get("id") == lane], f"`gates` step `{lane}`")["if"]


def _resolver_step() -> dict[str, Any]:
    steps: list[dict[str, Any]] = _jobs()["ci-required"]["steps"]
    return _single([s for s in steps if s.get("name") == RESOLVER_STEP], f"`{RESOLVER_STEP}` step")


_RESOLVER_TERM = re.compile(
    r'isTrue\(process\.env\.FILTER_(\w+)\)|process\.env\.FILTER_(PR) !== "false"'
)


def _resolver_security_filters() -> set[str]:
    """The filters the resolver script ORs together when it decides whether `security` applied."""
    return _resolver_lane_filters("security")


def _resolver_lane_filters(name: str) -> set[str]:
    """The filters the resolver ORs together to decide whether lane `name` applied (`true`: none).

    The lane must read its result from `RESULT_<NAME>` (`-` as `_`). `//` comments are stripped
    first, so a name that only a comment mentions does not count. Then each `||` term must be
    exactly `isTrue(process.env.FILTER_<NAME>)` (`pr`: `!== "false"`), so an `&&` or a `!` fails.
    """
    variable = "RESULT_" + name.upper().replace("-", "_")
    lane = re.search(
        rf'(?<![\w-])"?{re.escape(name)}"?:\s*\{{\s*applicable:(.*?)\bresult:\s*process\.env\.{variable}\b',
        _resolver_step()["run"],
        re.DOTALL,
    )
    assert lane, f"the ci-required resolver script has no `{name}` lane reading {variable}"
    expression = re.sub(r"//[^\n]*", "", lane.group(1)).strip().removesuffix(",").strip()
    if expression == "true":
        return set()
    names: set[str] = set()
    for term in expression.split("||"):
        match = _RESOLVER_TERM.fullmatch(term.strip())
        assert match, f"not an `isTrue(process.env.FILTER_<NAME>)` term: {term.strip()!r}"
        names.add((match[1] or match[2]).lower())
    return names


def test_pr_yml_semgrep_filter_covers_every_semgrep_gate_path() -> None:
    covered = set(_filters().get("semgrep") or [])
    assert set(SEMGREP_PATHS) <= covered, sorted(set(SEMGREP_PATHS) - covered)


def test_pr_yml_semgrep_filter_paths_exist_in_the_repo() -> None:
    # A path that was renamed away would leave the filter matching nothing, silently. This checks
    # what pr.yml actually lists, not the pinned constant, so an added or mistyped entry is caught.
    for pattern in _filters().get("semgrep") or []:
        assert any(ROOT.glob(pattern)), pattern


@pytest.mark.parametrize("name", FILTER_NAMES)
def test_pr_yml_changed_paths_exports_each_filter_as_its_own_output(name: str) -> None:
    outputs = _jobs()["changed-paths"]["outputs"]
    assert outputs.get(name) == "${{ steps.filter.outputs." + name + " }}"


def test_pr_yml_changed_paths_exports_every_filter_of_the_step_id_its_outputs_read() -> None:
    # Renaming only the step id would leave every `steps.filter.outputs.*` empty: each filtered lane
    # would skip and the resolver would count it as not applicable, so ci-required passes (#3182).
    assert _filter_step()["id"] == "filter"
    assert (
        set(_jobs()["changed-paths"]["outputs"]) - PR_CONTEXT
        == set(_filters())
        == set(FILTER_NAMES)
    )


def test_pr_yml_security_job_runs_when_only_semgrep_paths_change() -> None:
    assert "semgrep" in _outputs_in(_jobs()["security"]["if"])


def test_pr_yml_resolver_security_lane_names_the_same_filters_as_the_job() -> None:
    # Otherwise a failing `security` run that the job condition let through is "not applicable"
    # to the resolver, and ci-required stays green over it.
    assert _resolver_security_filters() == _outputs_in(_jobs()["security"]["if"])


@pytest.mark.parametrize("lane", sorted(LANE_FILTERS))
def test_pr_yml_resolver_reads_each_lane_filter_from_its_changed_paths_output(lane: str) -> None:
    env = _resolver_step()["env"]
    filters = _resolver_lane_filters(lane)
    assert filters == LANE_FILTERS[lane]
    for name in sorted(filters):
        expected = "${{ needs.changed-paths.outputs." + name + " }}"
        assert env.get("FILTER_" + name.upper()) == expected, name
    # The lane is judged on its own job's result (a gate: its `gates` step's), never another's.
    own = f"gates.outputs.{lane}" if lane in _jobs()["gates"]["outputs"] else f"{lane}.result"
    assert env.get("RESULT_" + lane.upper().replace("-", "_")) == "${{ needs." + own + " }}"


@pytest.mark.parametrize("lane", sorted(LANE_FILTERS))
def test_pr_yml_each_lane_starts_on_the_filters_the_resolver_judges_it_on(lane: str) -> None:
    # Otherwise a lane runs while "not applicable" (a red run leaves ci-required green) or skips
    # while applicable (CI-GATE-002).
    assert _if_filters(_lane_if(lane)) == LANE_FILTERS[lane]


def test_pr_yml_lane_filter_table_names_every_resolver_lane() -> None:
    lane = re.compile(r'^\s*"?([\w-]+)"?:\s*\{\s*applicable:', re.MULTILINE)
    assert set(lane.findall(_resolver_step()["run"])) == set(LANE_FILTERS)


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


def test_pr_yml_e2e_filter_covers_the_e2e_jobs_own_inputs() -> None:
    # A PR that edits only the e2e job or a guard its steps run must start the lane (#3182).
    assert set(E2E_PATHS) <= _lane_runs()["e2e"][1], "not the e2e job's workflow and scripts"
    covered = set(_filters()["e2e"])
    assert set(E2E_PATHS) <= covered, sorted(set(E2E_PATHS) - covered)


def test_pr_yml_js_filter_covers_the_token_formats_packages_ui_imports() -> None:
    # packages/ui's token build and its token-build tests import tools/style-dictionary/formats/,
    # so a formats-only PR must start the lane and, through js, security (#3182).
    sources = [*ROOT.glob("packages/ui/scripts/*.mjs"), *ROOT.glob("packages/ui/test/**/*.ts")]
    assert any("../tools/style-dictionary/" in p.read_text(encoding="utf-8") for p in sources)
    assert TOKEN_FORMATS in _filters()["js"] and any(ROOT.glob(TOKEN_FORMATS))


def test_pr_yml_py_filter_covers_the_a11y_gate_logic_and_the_fixture_corpus() -> None:
    # The security lane's Semgrep scan reads tools/a11y's Python; tests/_corpus.py and cvdev's
    # account pack read packages/fixtures, so a fixtures-only PR must run the backend suites.
    py = _filters()["py"]
    for pattern in PY_INPUTS:
        assert pattern in py and any(ROOT.glob(pattern)), pattern
    corpus = (ROOT / "services" / "api" / "tests" / "_corpus.py").read_text(encoding="utf-8")
    assert re.search(r"^CORPUS_ROOT\b.*\bpackages\W+fixtures\b", corpus, re.MULTILINE)


@pytest.mark.parametrize(("lane", "reader", "path"), READ_INPUTS)
def test_pr_yml_lane_filter_covers_what_its_scripts_read(lane: str, reader: str, path: str) -> None:
    # Each one changes what the lane checks, so a PR that edits only it must start the lane.
    filters, runs = _lane_runs()[lane]
    source = (ROOT / reader).read_text(encoding="utf-8")
    assert reader in runs and posixpath.basename(path) in source, reader
    assert (ROOT / path).is_file(), path
    assert any(_matches(path, rule) for name in sorted(filters) for rule in _filters()[name]), path


# --- What each lane's steps run (#3182) -----------------------------------------------------------

_CALL = re.compile(r"\b(?:python3?|node|bash|sh)\s+(?:-[\w-]+\s+)*([\w./-]+\.(?:py|m?js|sh))\b")
_MODULE = re.compile(r"\bpython3?\s+-m\s+((?:tools|scripts)(?:\.\w+)+)")
#: `make <target>` as a command, not inside an echoed hint.
_MAKE = re.compile(r"(?:^|[;(]|&&|\|\|)\s*make\s+([\w-]+)", re.MULTILINE)
_REQUIREMENTS = re.compile(r"\bpip3?\s+install\b[^\n]*?\s-[rc]\s*([\w./-]+)")
#: pnpm reads the repo's .npmrc on every install, though no run line names it.
_PNPM_INSTALL = re.compile(r"\bpnpm\s+install\b")
#: `with:` keys that name a cache key or an artifact path, not a file the action reads.
_WITH_UNREAD = frozenset({"cache-dependency-glob", "cache-dependency-path", "path"})
_PY_IMPORT = re.compile(
    r"^\s*(?:from\s+((?:tools|scripts)(?:\.\w+)+)\s+import\s+([\w, ]+)"
    r"|import\s+((?:tools|scripts)(?:\.\w+)+))",
    re.MULTILINE,
)
_JS_IMPORT = re.compile(r"""\bfrom\s+["'](\.{1,2}/[^"']+)["']""")
_GLOB = {r"\*\*/": "(?:.*/)?", r"\*\*": ".*", r"\*": "[^/]*", r"\?": "[^/]"}


def _matches(path: str, rule: str) -> bool:
    """Whether `dorny/paths-filter` (picomatch, `dot: true`) matches `path` to `rule`, for the
    glob syntax pr.yml uses: `**/`, `**`, `*` and `?`."""
    regex = re.sub(r"\\\*\\\*/|\\\*\\\*|\\\*|\\\?", lambda m: _GLOB[m.group(0)], re.escape(rule))
    return re.fullmatch(regex, path) is not None


def _repo_file(cwd: str, path: str, *, from_root: bool = True) -> str | None:
    """`path` as run from `cwd`, else (a script that `cd`s first) from the repo root, if a file."""
    candidates = [posixpath.normpath(posixpath.join(cwd, path))]
    candidates += [re.sub(r"^(?:\.\.?/)+", "", path)] if from_root else []
    for candidate in candidates:
        if not candidate.startswith("../") and (ROOT / candidate).is_file():
            return candidate
    return None


def _recipe(target: str) -> str:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    found = re.search(rf"^{re.escape(target)}:.*\n((?:\t.*(?:\n|$))*)", makefile, re.MULTILINE)
    assert found, f"no Makefile target {target!r}"
    return found.group(1)


def _imports(file: str, source: str) -> list[str | None]:
    """The repo modules `source` imports: tools/ or scripts/ ones from Python, relative ones
    from JS."""
    if not file.endswith(".py"):
        folder = posixpath.dirname(file)
        return [_repo_file(folder, m, from_root=False) for m in _JS_IMPORT.findall(source)]
    paths: list[str | None] = []
    for module, names, plain in _PY_IMPORT.findall(source):
        base = (module or plain).replace(".", "/")
        found = [base + ".py", base + "/__init__.py"]
        found += [f"{base}/{name.strip()}.py" for name in names.split(",") if name.strip()]
        paths += [path for path in found if (ROOT / path).is_file()]
    return paths


def _executed(cwd: str, run: str) -> set[str]:
    """Repo files a `run:` executes: the scripts it calls (also through `make` and `bash`), the
    modules those import, the files `pip install -r` reads and the .npmrc `pnpm install` reads.
    Shell comments are skipped."""
    files: set[str] = set()
    shells = [(cwd, run)]
    while shells:
        where, text = shells.pop()
        text = re.sub(r"(?m)(?:^|\s)#.*$", "", text)
        for target in _MAKE.findall(text):
            files.add("Makefile")
            shells.append((".", _recipe(target)))
        files.update(p for p in (_repo_file(where, r) for r in _REQUIREMENTS.findall(text)) if p)
        if _PNPM_INSTALL.search(text):
            files.add(".npmrc")
        modules = [module.replace(".", "/") + ".py" for module in _MODULE.findall(text)]
        pending = [_repo_file(where, call) for call in _CALL.findall(text) + modules]
        while pending:
            file = pending.pop()
            if file is None or file in files:
                continue
            files.add(file)
            source = (ROOT / file).read_text(encoding="utf-8")
            if file.endswith(".sh"):
                shells.append((".", source))
            else:
                pending += _imports(file, source)
    return files


def _with_inputs(step: dict[str, Any]) -> set[str]:
    """Repo files a `uses:` step hands its action in `with:`: a config or a version file."""
    values = [str(v) for key, v in (step.get("with") or {}).items() if key not in _WITH_UNREAD]
    found = (_repo_file(".", word.strip("\"'")) for value in values for word in value.split())
    return {path for path in found if path and not path.startswith("/")}


@functools.cache
def _lane_runs() -> dict[str, tuple[frozenset[str], frozenset[str]]]:
    """Lane -> (the filters its `if:` reads, the repo files its steps run or hand an action). A
    `gates` step is its own lane; a job lane runs its reusable workflow (an input too), all jobs."""
    lanes: dict[str, tuple[frozenset[str], frozenset[str]]] = {}
    for name, job in _jobs().items():
        steps = [(".", step) for step in job.get("steps") or []]
        files: set[str] = set()
        if "uses" in job:
            files.add(job["uses"].removeprefix("./"))
            callee = yaml.safe_load((ROOT / job["uses"]).read_text(encoding="utf-8"))
            for inner in callee["jobs"].values():
                where = ((inner.get("defaults") or {}).get("run") or {}).get("working-directory")
                steps += [(where or ".", step) for step in inner.get("steps") or []]
        for where, step in steps:
            if "run" in step:
                ran = _executed(step.get("working-directory", where), step["run"])
            else:
                ran = _with_inputs(step)
            if name == "gates" and "id" in step:
                lanes[step["id"]] = (frozenset(_if_filters(step.get("if"))), frozenset(ran))
            files |= ran
        lanes.setdefault(name, (frozenset(_if_filters(job.get("if"))), frozenset(files)))
    return lanes


@pytest.mark.parametrize(
    "lane", sorted(lane for lane, filters in LANE_FILTERS.items() if filters - PR_CONTEXT)
)
def test_pr_yml_each_lane_filter_covers_what_its_steps_run(lane: str) -> None:
    # A PR that edits only a lane's workflow, a script its steps run or a file a step hands a tool
    # must start that lane, or it merges with the gate built to check that file skipped (#3182).
    filters, files = _lane_runs()[lane]
    rules = [rule for name in sorted(filters) for rule in _filters()[name]]
    assert sorted(path for path in files if not any(_matches(path, rule) for rule in rules)) == []


@pytest.mark.parametrize(
    ("lane", "path"),
    [
        ("pin-check", "tools/ci/resolve_image_digests.py"),
        ("statechart-lint", "tools/lint_statecharts.py"),
        ("xstate-contract", "tools/statechart/suite_budget.py"),  # through `bash <script>`
        ("e2e", ".github/workflows/_job-e2e.yml"),  # the reusable workflow itself
        ("a11y", "tools/a11y/gates.py"),  # `python -m`
        ("migrations", "tools/ci/migration_lint.py"),  # `../../` from services/api
        ("js", "tools/ci/electron_hardening_checks.py"),  # imported by the gate script
        ("contract", "tools/errorcodes/generate.py"),  # `make contracts`, then an import
        ("security", ".github/codeql/codeql-config.yml"),  # a `with:` config file
        ("security", "scripts/requirements-ci.txt"),  # `pip install -r`
        ("js", ".nvmrc"),  # `node-version-file`
        ("e2e", ".npmrc"),  # `pnpm install` reads it; no run line names it
    ],
)
def test_pr_yml_lane_inputs_are_derived_through_each_way_a_step_runs_a_file(
    lane: str, path: str
) -> None:
    assert path in _lane_runs()[lane][1]


def test_pr_yml_lane_inputs_read_make_only_as_a_command() -> None:
    # `echo "make gen"` prints a hint and runs no recipe; `... && make <target>` runs one.
    assert _executed(".", 'echo "make gen"') == set()
    assert "Makefile" in _executed(".", "set -e && make contracts")
