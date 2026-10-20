#!/usr/bin/env python3
"""#3882: `make pr-gate`, the PR workflow's checks run locally on what this branch changes.

Three PR runs on 2026-10-20 went red on rules the lanes' own test subsets left out: the E04 alert
drill matrix, the bars bench pins and CodeQL's clear-text-logging query. This gate diffs the tree
against the merge base with origin/main and runs, one process at a time, CI's governance scripts,
the lane scripts the changed paths switch on, backend lint, types and tests, Semgrep and gitleaks
when installed, and a pattern check for the CodeQL miss. One table; exit 1 on any failure. The
lanes that apply are pr.yml's own `changed-paths` selection (tools/ci/path_filters.py reads it, so
no rule is copied here). No network. Windows and Linux: pathlib, no fcntl. What a machine cannot
run is no pass: a missing tool is SKIP, tests Windows cannot import (fcntl, parts of os) are
PARTIAL, and the verdict line counts both. LEFT_TO_CI says what only CI runs.
"""

from __future__ import annotations

import argparse
import ast
import io
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path, PurePosixPath
from typing import Any, NamedTuple

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# E402: the repo root is put on sys.path just above, which this package import needs.
from tools.ci import path_filters  # noqa: E402

API = "services/api"
UNIT = f"{API}/tests/unit"
BASE_REF = "origin/main"
STEP_TIMEOUT = 1500  # seconds a step may take: CI's py lane is cut off at 30 minutes
RUN: dict[str, Any] = {
    "capture_output": True,
    "text": True,
    "encoding": "utf-8",
    "errors": "replace",
}
#: _job-py.yml's py-tests marker expression (scripts/tests/test_pr_gate.py pins the copy).
PYTEST_MARKERS = (
    "not exchange_smoke and not (chaos and integration) and not roundtrip and not fuzz "
    "and not harness and not perf and not flaky"
)
#: What runs here: CI's selection, less the integration and chaos tests, which need Docker.
LOCAL_MARKERS = f"{PYTEST_MARKERS} and not integration and not chaos"
#: Tests that pin a module from outside its own tests/unit directory: path prefix -> test paths.
#: #3868: the bench lane's tests import the bars modules and pin their limits and budgets. The
#: unit tests that import the module (15 files of unit/ws import candleviewer.bars) run too.
PINNED_TESTS = (
    (f"{API}/candleviewer/bars/", (f"{UNIT}/bench",)),
    (f"{API}/bench/", (f"{UNIT}/bench",)),
)
CODEQL_NOTE = (
    "CodeQL (py/clear-text-logging-sensitive-data) cannot run here: a test must not log a "
    "password-named value, not even a fixed test string. Rename it (#3875)."
)
LOG_METHODS = frozenset("debug info warning warn error exception critical log".split())
GEN_CHECK = "tools/ci/check_gen_freshness.py"
CODE_SUFFIXES = (".py", ".ts", ".tsx", ".js", ".mjs", ".yml", ".yaml")
SEMGREP_FLAGS = ("--error", "--metrics=off", "--disable-version-check", "--quiet")
#: Results that are no failure but no pass either: the verdict line counts them.
CAVEATS = (("SKIP", "skipped"), ("PARTIAL", "partial"))
LEFT_TO_CI = (
    "Left to CI: CodeQL, the js/e2e/contract/integration/migrations lanes, the integration and "
    "chaos tests (Docker), xstate-contract and tests/lint_statecharts, the PR title and body, and "
    "the PR size (over 800 counted LOC fails PR-SIZE-001)."
)
#: Files so many tests name that a name says nothing about which test reads them.
GENERIC_NAMES = frozenset({"README.md", "package.json", "__init__.py"})
#: The lint targets outside services/api that _job-py.yml's ruff and mypy steps also check.
PY_LANE_LINT = re.compile(r"uv run (?:ruff|mypy) .*")  # the lines of _job-py.yml that lint
PY_LANE_EXTRAS = re.compile(r"\.\./\.\./[\w./-]+\.py")  # the targets such a line adds
POSIX_ONLY = re.compile(
    r"No module named '(?:fcntl|termios|resource|pwd|grp)'|module 'os' has no attribute"
)
PASSWORD_NAME = re.compile(r"pass(?:word|wd|code|phrase)", re.IGNORECASE)
# CI's scripts as its workflows write them, run as `python <script>`: ALWAYS on every change (as
# CI's governance does), ON_FILTER on a `changed-paths` filter. The tests pin both to the workflows.
ALWAYS = {
    "spike-containment": "tools/ci/check_spike_containment.py --root .",
    "licence-header": "scripts/check_licence_headers.py",
    "rule-refs": "scripts/check_rule_refs.py",  # GOV-002
    "backlog-twin-eol": "scripts/check_backlog_twin_eol.py",
    "secrets-hygiene": "scripts/check_secrets_hygiene.py all",
    "codeowners": "scripts/check_codeowners_coverage.py",  # GOV-001
    "issue-forms": "scripts/check_issue_forms.py",  # GOV-004
    "required-checks": "scripts/check_required_check_reconciliation.py",  # GOV-005
    "markdown-docs": "scripts/check_markdown_governance_docs.py",  # GOV-006
    "owned-docs": "scripts/check_owned_docs_untouched.py",  # GOV-007
    "threat-models": "scripts/check_threat_model_ticket_map.py",  # GOV-008
    "runbook": "scripts/check_runbook_completeness.py",  # CI-DOC-001
    "bypass-register": "scripts/check_bypass_register.py",
    "accepted-risks": "tools/ci/check_accepted_risk_expiry.py",
    "keymap": "scripts/keymap_lint.py --check-docs",
    "governance-canary": "scripts/gov_self_test.py --self-test",
    "backlog-schema": "scripts/validate-backlog.py --quiet",
    "backlog-twins": "docs/plan/backlog/_tools/validate.py --check",
    "alert-drill-matrix": "scripts/check_e04_test_plan.py",  # E04-Q01: each alert has a row (#3862)
}
ON_FILTER = {  # filter: {gate: script}
    "infra": {
        "pin-check": "tools/ci/check_action_pins.py",
        "pin-digests-offline": "tools/ci/resolve_image_digests.py --check --offline",  # CI: online
    },
    "py": {
        "statechart-lint": "tools/lint_statecharts.py",
        "event-coverage": "tools/statechart/event_coverage.py",
        "alert-rules": "infra/alertmanager/check_alert_rules.py",  # _job-py.yml, E04-T05
        "dashboard-lint": "infra/grafana/lint_dashboards.py --strict",  # _job-py.yml
        "machine-hash-lock": "tools/statechart/check_machine_hash_lock.py",  # CI adds a test
        "rule-ir-schema": "services/api/scripts/generate_rule_ir_schema.py --check",  # _job-py.yml
    },
}
BACKEND_GATES = frozenset({"machine-hash-lock", "rule-ir-schema"})  # run in the services/api env


class Step(NamedTuple):
    gate: str
    scope: str
    # -> (PASS | PARTIAL | FAIL | SKIP, a FAIL's output or a note)
    run: Callable[[], tuple[str, str]]


class Result(NamedTuple):
    gate: str
    scope: str
    status: str
    seconds: float
    detail: str


class Change(NamedTuple):
    root: Path
    paths: tuple[str, ...]  # every changed path vs the merge base, deleted ones too
    base: str  # the merge base's sha
    workflow: dict[str, Any]
    selected: dict[str, bool]  # pr.yml's `changed-paths` outputs for `paths`

    @property
    def present(self) -> list[str]:
        return [p for p in self.paths if (self.root / p).is_file()]

    @property
    def docs_only(self) -> bool:
        others = (on for name, on in self.selected.items() if name != "docs")
        return bool(self.paths) and self.selected["docs"] and not any(others)


def git(root: Path, *args: str) -> str:
    done = subprocess.run(["git", *args], cwd=root, **RUN)  # noqa: S603, S607 - a fixed argv
    if done.returncode:
        raise RuntimeError(f"git {args[0]}: {done.stderr.strip()[:200]}")
    return str(done.stdout)


def changed(root: Path, base_ref: str = BASE_REF) -> Change:
    """What this branch changes vs its merge base with `base_ref`: commits, edits and new files."""
    base = git(root, "merge-base", "HEAD", base_ref).strip()
    tracked = git(root, "diff", "--name-only", "--no-renames", "-z", base).split("\0")
    untracked = set(git(root, "ls-files", "--others", "--exclude-standard", "-z").split("\0"))
    paths = tuple(sorted({*tracked, *untracked} - {""}))
    workflow = path_filters.load_workflow(root / ".github" / "workflows" / "pr.yml")
    selected = path_filters.select(paths, path_filters.load_filters(workflow))
    return Change(root, paths, base, workflow, selected)


def run_command(argv: Sequence[str], cwd: Path) -> tuple[int, str]:
    exe = shutil.which(argv[0])
    if exe is None:
        return 127, f"{argv[0]} is not installed"
    # CI's py lane (HYPOTHESIS_PROFILE); pytest keeps the reason on each summary line (COLUMNS)
    env = {**os.environ, "PYTHONUTF8": "1", "HYPOTHESIS_PROFILE": "ci", "COLUMNS": "240"}
    cmd = [exe, *argv[1:]]  # a fixed argv, no shell
    try:
        done = subprocess.run(cmd, cwd=cwd, env=env, timeout=STEP_TIMEOUT, **RUN)  # noqa: S603
    except subprocess.TimeoutExpired:
        return 124, f"{argv[0]} timed out after {STEP_TIMEOUT // 60} minutes"
    return done.returncode, done.stdout + done.stderr


def command(gate: str, scope: str, argv: Sequence[str], cwd: Path) -> Step:
    def run() -> tuple[str, str]:
        if shutil.which(argv[0]) is None:
            return "SKIP", f"{argv[0]} is not installed"
        code, output = run_command(argv, cwd)
        return ("PASS", "") if code == 0 else ("FAIL", output)

    return Step(gate, scope, run)


def backend(*argv: str) -> list[str]:
    """`argv` as CI runs it from services/api: through `uv run`, else from PATH."""
    return [*(["uv", "run", "--frozen"] if shutil.which("uv") else []), *argv]


def is_test_file(path: str) -> bool:
    return path.endswith(".py") and (
        "/tests/" in f"/{path}" or PurePosixPath(path).name.startswith("test_")
    )


def select_tests(root: Path, paths: Iterable[str]) -> tuple[list[str], list[str]]:
    """The tests a change affects: (paths for pytest inside services/api, files for scripts/tests).

    A backend module runs its tests/unit directory, a changed test itself (a helper or conftest,
    its directory), PINNED_TESTS what pins a module from elsewhere, any other file, root files
    such as AGENTS.md and Makefile too, the governance tests that read it by name (the name in
    quotes: a test that only mentions it reads nothing) and a script the tests that import it.
    GENERIC_NAMES, which too many tests name, select nothing.
    """
    api: set[str] = set()
    gov: set[str] = set()
    modules: set[str] = set()
    files: set[str] = set()
    importers: set[str] = set()
    unit = root / UNIT
    for path in paths:
        pure = PurePosixPath(path)
        if not (root / path).is_file():
            continue
        for prefix, pinned in PINNED_TESTS:
            if path.startswith(prefix):
                api.update(pinned)
                importers.add(prefix.removeprefix(f"{API}/").strip("/").replace("/", "."))
        if path.startswith(f"{API}/candleviewer/"):
            module, _, rest = path.removeprefix(f"{API}/candleviewer/").partition("/")
            if rest and (unit / module).is_dir():
                api.add(f"{UNIT}/{module}")
            elif not rest:
                api.update(
                    p.relative_to(root).as_posix() for p in unit.glob(f"test_{pure.stem}*.py")
                )
        elif path.startswith(f"{API}/tests/") and is_test_file(path):
            where = path if pure.name.startswith("test_") else pure.parent.as_posix()
            if where != f"{API}/tests" and not re.search(r"/(chaos|integration)/", path):
                api.add(where)  # never the whole suite, never the tests that need Docker
        elif path.startswith("scripts/tests/test_"):
            gov.add(path)
        elif not path.startswith(API) and pure.name not in GENERIC_NAMES:
            script = pure.suffix == ".py" and re.search("[_-]", pure.stem)
            (modules if script else files).add(pure.stem if script else pure.name)
    for module in importers:  # the unit tests that import a pinned module, wherever they sit
        imports = re.compile(rf"^\s*(?:from|import)\s+{re.escape(module)}\b", re.MULTILINE)
        api.update(
            t.relative_to(root).as_posix()
            for t in unit.rglob("test_*.py")
            if imports.search(t.read_text(encoding="utf-8", errors="replace"))
        )
    if modules or files:
        imported = [rf"(?<![\w-]){re.escape(m)}(?![\w-])" for m in sorted(modules)]
        read = [rf"""["'](?:[^"'\s]*/)?{re.escape(f)}["']""" for f in sorted(files)]
        names = re.compile("|".join([*imported, *read]))
        for test in sorted((root / "scripts" / "tests").glob("test_*.py")):
            if names.search(test.read_text(encoding="utf-8", errors="replace")):
                gov.add(test.relative_to(root).as_posix())
    api = {a for a in api if not any(a.startswith(f"{d}/") for d in api)}  # a dir covers its files
    return sorted(api), sorted(gov)


def pytest_status(code: int, output: str, windows: bool) -> tuple[str, str]:
    """A pytest run's verdict. Exit 5 (nothing selected) passes. Windows lacks fcntl and parts of
    os: when that is every failure, the run is PARTIAL, naming what did not run, never a PASS.

    The failures are judged before the summary, which repeats them all: the error blocks of the
    report (collection and setup errors) and one `FAILED` or `ERROR` summary line per test, whose
    reason COLUMNS keeps whole. A conftest that cannot import aborts the whole run.
    """
    if code in (0, 5):
        return "PASS", ""
    report, _, summary = output.partition("short test summary info")
    lines = summary.splitlines()
    failed = [ln for ln in lines if ln.startswith("FAILED ") or re.match(r"ERROR \S+::", ln)]
    blocks = re.split(r"^_{3,} .+? _{3,}$", report.partition(" FAILURES ")[0], flags=re.MULTILINE)
    sections = blocks[1:] + failed
    sections = sections or re.findall(r"ImportError while loading conftest.*", report, re.DOTALL)
    if windows and sections and all(POSIX_ONLY.search(section) for section in sections):
        names = [ln[6:].split(" - ")[0] for ln in lines if re.match(r"ERROR [^:]*( - |$)", ln)]
        names += [ln.split(" ", 1)[1].split("::")[0] for ln in failed if "::" in ln]
        names += re.findall(r"loading conftest '([^']+)'", report)
        shown = ", ".join(sorted(set(names))) or f"{len(sections)} section(s)"
        return "PARTIAL", f"not run on Windows (POSIX-only imports): {shown}; run them in WSL or CI"
    notes = []
    if windows:
        notes.append(
            "Windows: tests that need fcntl, resource, POSIX paths or symlinks fail here whatever "
            "the change; confirm such a failure in WSL or CI"
        )
    if "WinError 1314" in output:
        notes.append("WinError 1314: this account may not create symlinks (Developer Mode, or WSL)")
    return "FAIL", "\n".join([output, *notes])


def logged_passwords(source: str) -> list[tuple[int, str]]:
    """(line, name) of each password-named value a logging call receives.

    CodeQL reads such a name as sensitive data whatever it holds: #3875 logged `_PASSWORD`, a
    fixed test string, on purpose, to prove that a filter hides it. A test file is judged whole;
    what CodeQL's config ignores is left out by `check_steps`: .semgrep/tests/ holds fixtures
    that log credentials on purpose, for the rules that must catch them.
    """
    found: set[tuple[int, str]] = set()
    for call in ast.walk(ast.parse(source)):
        if isinstance(call, ast.Call) and getattr(call.func, "attr", "") in LOG_METHODS:
            for arg in [*call.args, *(k.value for k in call.keywords)]:
                for node in ast.walk(arg):
                    if not isinstance(node, ast.Name | ast.Attribute):
                        continue
                    name = node.id if isinstance(node, ast.Name) else node.attr
                    if PASSWORD_NAME.search(name):
                        found.add((node.lineno, name))
    return sorted(found)


def script_steps(change: Change) -> list[Step]:
    due = {gate: (script, "every change") for gate, script in ALWAYS.items()}
    for name, scripts in ON_FILTER.items():
        if change.selected[name]:
            due.update({gate: (script, name) for gate, script in scripts.items()})
    in_backend = ["uv", "run", "--frozen", "--project", API, "python"]
    steps = []
    for gate, (script, scope) in due.items():
        python = in_backend if gate in BACKEND_GATES and shutil.which("uv") else [sys.executable]
        steps.append(command(gate, scope, [*python, *shlex.split(script)], change.root))
    return steps


def py_lane_extras(root: Path) -> list[str]:
    """The files outside services/api that _job-py.yml's ruff and mypy steps also check, as that
    workflow writes them (relative to services/api)."""
    job = root / ".github" / "workflows" / "_job-py.yml"
    text = job.read_text(encoding="utf-8") if job.is_file() else ""
    found = PY_LANE_EXTRAS.findall(" ".join(PY_LANE_LINT.findall(text)))
    return list(dict.fromkeys(found))


def tool_steps(change: Change) -> list[Step]:
    """CI's `py` lint on the changed backend files, Semgrep and gitleaks."""
    root, api = change.root, change.root / API
    backend_files = [p for p in change.present if p.startswith(f"{API}/")]
    py = [p.removeprefix(f"{API}/") for p in backend_files if p.endswith(".py")]
    extras = py_lane_extras(root)
    lint = py + [e for e in extras if e.removeprefix("../../") in change.present]
    steps = []
    if change.selected["protocol"]:  # CI runs `gen` on every PR; here its inputs start it
        gen = command("gen-freshness", "protocol", [sys.executable, GEN_CHECK], root)
        skip = Step(
            gen.gate, gen.scope, lambda: ("SKIP", "run pnpm install --frozen-lockfile first")
        )
        steps.append(
            gen if (root / "node_modules").is_dir() else skip
        )  # it rewrites generated files
    for gate, args in (("ruff", ("check",)), ("ruff-format", ("format", "--check"))):
        steps += [command(gate, f"{len(lint)} file(s)", backend("ruff", *args, *lint), api)] * bool(
            lint
        )
    contracts = {f"{API}/.importlinter", "docs/plan/module-contracts.toml"} & set(change.paths)
    package = bool(contracts) or any(p.startswith(("candleviewer/", "cvdev/")) for p in py)
    if package or len(lint) > len(py):
        mypy = backend("mypy", "--strict", "--platform", "linux", "candleviewer", "cvdev")
        steps.append(command("mypy", "candleviewer cvdev", mypy + extras, api))
    if package:
        steps.append(command("import-linter", "contracts", backend("lint-imports"), api))
    code = [p for p in change.present if p.endswith(CODE_SUFFIXES)]
    rules = [p.relative_to(root).as_posix() for p in sorted((root / ".semgrep").glob("cv-*.yml"))]
    if code and rules:
        configs = [arg for rule in rules for arg in ("--config", rule)]
        argv = ["semgrep", "scan", *SEMGREP_FLAGS, *configs, *code]
        steps.append(command("semgrep", f"{len(code)} file(s)", argv, root))
    leaks = ["--redact", "--no-banner", "--config", ".gitleaks.toml"]
    commits = ["gitleaks", "git", "--log-opts", f"{change.base}..HEAD", *leaks, "."]
    steps.append(command("gitleaks", "branch commits", commits, root))  # the commits are made
    return steps


def codeql_ignored(root: Path) -> list[str]:
    """The `paths-ignore` globs of CodeQL's config: what CodeQL skips, the pattern check skips."""
    config = root / ".github" / "codeql" / "codeql-config.yml"
    loaded = yaml.safe_load(config.read_text(encoding="utf-8")) if config.is_file() else None
    return [str(glob) for glob in (loaded or {}).get("paths-ignore", [])]


def check_steps(change: Change) -> list[Step]:
    """The CodeQL pattern check (#3875), on the changed test files CodeQL does not ignore."""
    root, ignored = change.root, codeql_ignored(change.root)
    tests = [
        p
        for p in change.present
        if is_test_file(p) and not any(path_filters.matches(p, glob) for glob in ignored)
    ]

    def run_codeql() -> tuple[str, str]:
        hits = []
        for path in tests:
            try:
                source = (root / path).read_text(encoding="utf-8")
                found = logged_passwords(source)
            except (SyntaxError, UnicodeDecodeError):
                continue
            hits += [f"{path}:{line}: `{name}` reaches a logger" for line, name in found]
        return ("FAIL", "\n".join([*hits, CODEQL_NOTE])) if hits else ("PASS", "")

    return [Step("codeql-logging", f"{len(tests)} test file(s)", run_codeql)] if tests else []


def test_steps(change: Change, fast: bool) -> list[Step]:
    if fast and change.docs_only:
        return []
    api, gov = select_tests(change.root, change.present)
    windows = os.name == "nt"
    flags = ["-q", "-p", "no:cacheprovider", "--tb=line"]
    flags += ["--continue-on-collection-errors"] * windows

    def pytest_step(gate: str, scope: str, argv: list[str], cwd: Path) -> Step:
        def run() -> tuple[str, str]:
            if shutil.which(argv[0]) is None:
                return "SKIP", f"{argv[0]} is not installed"
            return pytest_status(*run_command(argv, cwd), windows)

        return Step(gate, scope, run)

    steps = []
    if gov:
        argv = [sys.executable, "-m", "pytest", *flags, *gov]
        steps.append(pytest_step("pytest-scripts", f"{len(gov)} file(s)", argv, change.root))
    if api:
        paths = [p.removeprefix(f"{API}/") for p in api]
        argv = backend("pytest", *flags, "--no-cov", "-m", LOCAL_MARKERS, *paths)
        steps.append(pytest_step("pytest-api", f"{len(api)} path(s)", argv, change.root / API))
    return steps


def plan(change: Change, fast: bool = False) -> list[Step]:
    steps = [*script_steps(change), *tool_steps(change), *check_steps(change)]
    return steps + test_steps(change, fast)


def execute(step: Step) -> Result:
    print(f"[pr-gate] {step.gate} ...", file=sys.stderr, flush=True)
    start = time.perf_counter()
    status, detail = step.run()
    return Result(step.gate, step.scope, status, time.perf_counter() - start, detail)


def table(results: Sequence[Result]) -> str:
    rows = [(r.gate, r.scope, r.status, f"{r.seconds:.1f}") for r in results]
    rows.insert(0, ("gate", "scope", "result", "seconds"))
    widths = [max(len(row[i]) for row in rows) for i in range(4)]
    lines = ["  ".join(c.ljust(w) for c, w in zip(row, widths, strict=True)) for row in rows]
    lines.insert(1, "  ".join("-" * w for w in widths))
    return "\n".join(line.rstrip() for line in lines)


def header(change: Change, base_ref: str) -> str:
    lanes = ", ".join(name for name, on in change.selected.items() if on) or "none"
    where = f"{len(change.paths)} changed path(s) vs {base_ref} ({change.base[:9]})"
    return f"pr-gate: {where}; lanes: {lanes}"


def report(change: Change, results: Sequence[Result]) -> str:
    failed = [r for r in results if r.status == "FAIL"]
    notes = [
        f"  {r.gate}: {r.detail.strip()}" for r in results if r.detail.strip() and r not in failed
    ]
    out = [table(results), *(["", "notes:", *notes] if notes else [])]
    for r in failed:
        out += ["", f"--- {r.gate} failed ---", *r.detail.strip().splitlines()[-40:]]
    out += ["", CODEQL_NOTE] if any(is_test_file(p) for p in change.present) else []
    counts = [(sum(r.status == status for r in results), word) for status, word in CAVEATS]
    caveat = ", ".join(f"{n} {word}" for n, word in counts if n)
    note = f" ({caveat})" if caveat else ""
    verdict = f"pr-gate: {'FAIL' if failed else 'PASS'}{note}"
    return "\n".join(
        [*out, "", LEFT_TO_CI, f"{verdict} in {sum(r.seconds for r in results):.0f} s"]
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("--base", default=BASE_REF, help="ref to diff against")
    parser.add_argument("--fast", action="store_true", help="skip the tests of a docs-only change")
    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(errors="replace")
    try:
        change = changed(_REPO_ROOT, args.base)
        steps = plan(change, args.fast)
    except (RuntimeError, ValueError, OSError) as exc:
        print(f"pr-gate: cannot plan: {exc} (git fetch origin main?)", file=sys.stderr)
        return 2
    if not change.paths:
        print(f"pr-gate: no change against {args.base}")
        return 0
    print(header(change, args.base), flush=True)
    results = [execute(step) for step in steps]
    print(report(change, results))
    return 1 if any(r.status == "FAIL" for r in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
