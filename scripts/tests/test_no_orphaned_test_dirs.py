"""#4361: every test file under infra/, tools/ and scripts/ is run by a workflow.

`infra/scripts/tests`, `infra/alertmanager/tests` and `infra/grafana/tests/test_dashboards.py` pin
the scripts, alert rules and dashboards that CI and the deploy path rely on, and no workflow ran
them, so one assertion stayed red unseen (`test_obs_security_checks.py`, once `ingestion.yml` added
labels its allow-list lacked). These tests read what CI runs, from `git ls-files`, and name every
test file that nothing runs, so a new `tests/` directory cannot land without a runner.

A test file is `test_*.py` or `*_test.py` (pytest's default) or promtool's `*.test.yml`.
A runner is:
  - governance: the files of `governance_shards.SUITES` less `EXCLUDED`, which its shards hand to
    pytest (`governance.yml` runs on every pull request, with no path filter);
  - a pytest command in a workflow `run:` naming the file or a directory above it, less its
    `--ignore`s, read as bash does: the step's or job's `working-directory`, `cd`, `../` paths,
    `file::node` ids;
  - a `python FILE` command (`scripts/gov_self_test.py` is a canary whose name ends in `_test`);
  - `promtool test rules FILE`, in docker too (`-v $PWD/infra/prometheus:/p`, `/p/tests/x.test.yml`
    for infra/prometheus/tests/x.test.yml).
What a command runs is what it names: `-k`, `-m`, `--deselect` and `--ignore-glob` are not modelled.
A command that runs no test or gates nothing does not count: pytest with `--collect-only`,
`--setup-plan`, `--version` or the like, a step or job with `if: false`, or with
`continue-on-error: true` (pr.yml's `gates` steps use it with a resolver, so a test run only there
needs another runner too). Not read: shell masks (`|| true`, a pipe without pipefail, `set +e`),
`PYTEST_ADDOPTS`, clustered short flags such as `-qV`, and a caller's `if: false` outside the
exclusion check.
A path with a `$variable` or a glob, a no-argument pytest and `bash -c` are not read, so such a
reference shows as an orphan: fix the workflow, or this reader. Any other `if:` and the triggers
are not read either: a step that runs only on a label or in the merge queue counts like one on every
pull request, and a scheduled workflow counts too, except for an exclusion, which has to be run in
`pr.yml` or a `_job-*.yml` it calls, the runs a merge waits for.
"""

from __future__ import annotations

import functools
import itertools
import posixpath
import re
import shlex
import shutil
import subprocess
import sys
from collections.abc import Iterator, Sequence
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any, NamedTuple

import pytest
import yaml

try:  # libyaml reads the workflows ten times as fast, and to the same result
    from yaml import CSafeLoader as SafeLoader
except ImportError:
    from yaml import SafeLoader

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.ci import governance_shards as gs  # noqa: E402 - the repo root is on sys.path above

WORKFLOWS = ROOT / ".github" / "workflows"
GOVERNANCE = "governance.yml"
SHARDER = "tools/ci/governance_shards.py"
ROOTS = ("infra", "tools", "scripts")
PROMTOOL_FILES = ("*.test.yml", "*.test.yaml")
PYTEST = ("pytest", "py.test")
ENV = re.compile(r"[A-Za-z_]\w*=.*")
PUNCTUATION = re.compile(r"[();|&]+")  # ends a simple command, or opens or closes a subshell
REDIRECT = {"<", ">", ">>", ">&", "<&", "&>", "&>>", ">|", "<>", "<<", "<<<"}  # takes one word
PYTHON = re.compile(r"(?:\S*/)?python[\d.]*")
UV_RUN = re.compile(r"(?:uv run(?: -\S+)* )?")  # what may stand before `python FILE`
PYTEST_LAUNCH = re.compile(r"(?:uv run(?: -\S+)* )?(?:(?:\S*/)?python[\d.]* -m )?")
WORKSPACE = re.compile(  # a `-v` host path that starts at $PWD or at the checkout
    r"(?:(?P<pwd>\$PWD|\$\{PWD\})|\$GITHUB_WORKSPACE|\$\{GITHUB_WORKSPACE\}"
    r"|\$\{\{ github\.workspace \}\})(?:/(?P<rest>.*))?"
)
#: pytest options whose separate value is not a test path (`--cov scripts` names a coverage source).
VALUE_OPTIONS = frozenset({
    "-k", "-m", "-n", "-p", "-o", "-W", "-r", "-c", "--cov", "--cov-config", "--cov-report",
    "--cov-fail-under", "--config-file", "--rootdir", "--confcutdir", "--basetemp", "--junitxml",
    "--ignore-glob", "--deselect", "--maxfail", "--durations", "--dist", "--tb",
})  # fmt: skip
#: The spellings of pytest's options that stop before any test runs: a command that carries one
#: executes nothing, so it is no runner.
NO_RUN = frozenset({
    "--collect-only", "--collectonly", "--co", "--setup-only", "--setuponly", "--setup-plan",
    "--setupplan", "--fixtures", "--funcargs", "--fixtures-per-test", "--markers", "--version",
    "-V", "-VV", "--cache-show", "-h", "--help",
})  # fmt: skip
KNOWN = (  # an empty or shrunken derivation proves nothing: these exist today
    "infra/alertmanager/tests/test_alerting_config.py",
    "infra/grafana/tests/test_live_render.py",
    "infra/prometheus/tests/ws_alerts.test.yml",
    "infra/scripts/tests/test_lint_compose.py",
    "scripts/gov_self_test.py",
    "scripts/tests/test_governance_shards.py",
)


class Step(NamedTuple):
    workflow: str
    job: str
    cwd: str | None  # repo-relative; None when the working directory is an expression
    script: str


class Call(NamedTuple):
    runner: str  # "pytest", "python" or "promtool"
    raw: list[str]  # the words that name what it runs, as written
    files: list[str]  # those words as repo-relative paths (a `$` word or a glob is dropped)
    ignored: list[str]  # pytest's `--ignore` paths, repo-relative


def _tracked() -> list[str]:
    """Every file git tracks under ROOTS, sorted: the tree CI checks out."""
    result = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--", *ROOTS],
        cwd=ROOT,
        capture_output=True,
        check=False,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    return sorted(set(result.stdout.decode("utf-8").split("\0")) - {""})


def _is_test_file(path: str) -> bool:
    name = posixpath.basename(path)
    return any(fnmatchcase(name, pattern) for pattern in (*gs.PYTHON_FILES, *PROMTOOL_FILES))


def _resolve(word: str, cwd: str | None) -> str | None:
    """`word` as a repo-relative path from `cwd`, or None when it is not one this reader follows."""
    if cwd is None or not word or word.startswith(("/", "-", "~")) or re.search(r"[$`*?\[]", word):
        return None
    path = posixpath.normpath(posixpath.join(cwd, word))
    return None if path == ".." or path.startswith("../") else path


def _load(path: Path) -> Any:
    return yaml.load(path.read_text(encoding="utf-8"), Loader=SafeLoader) or {}


def _within(path: str, base: str) -> bool:
    return base == "." or path == base or path.startswith(base + "/")


def _inert(node: dict[str, Any]) -> bool:
    """A job or step that never runs (`if: false`) or whose failure is ignored."""
    flat = {
        key: re.sub(r"[\s${}]", "", str(node.get(key))).lower()
        for key in ("if", "continue-on-error")
    }
    return flat["if"] == "false" or flat["continue-on-error"] == "true"


@functools.cache
def _steps(folder: Path = WORKFLOWS) -> tuple[Step, ...]:
    """Every `run:` step of the workflows in `folder` that runs and can fail its job, with the
    directory it starts in."""

    def default(node: dict[str, Any]) -> Any:
        return ((node.get("defaults") or {}).get("run") or {}).get("working-directory")

    steps: list[Step] = []
    for path in sorted(folder.glob("*.y*ml")):
        doc = _load(path)
        for job, spec in (doc.get("jobs") or {}).items():
            if _inert(spec):
                continue
            fallback = default(spec) or default(doc)
            for step in spec.get("steps") or []:
                if isinstance(step.get("run"), str) and not _inert(step):
                    declared = str(step.get("working-directory") or fallback or ".").strip()
                    here = "." if declared == "${{ github.workspace }}" else declared
                    steps.append(Step(path.name, job, _resolve(here, "."), step["run"]))
    return tuple(steps)


def _commands(script: str, cwd: str | None) -> Iterator[tuple[list[str], str | None]]:
    """The simple commands of a `run:` script, each with the directory it runs in.

    `cd DIR` moves the rest of its shell; `( ... )` and `$( ... )` run in a copy of the directory.
    A line shlex cannot read (an unbalanced quote) gives no command: fewer references, never more.
    """
    stack = [cwd]
    for line in script.replace("\\\n", " ").splitlines():
        try:
            lexer = shlex.shlex(line, posix=True, punctuation_chars=True)
            lexer.whitespace_split = True
            tokens = list(lexer)
        except ValueError:
            continue
        words: list[str] = []
        skip = False
        for token in [*tokens, ";"]:
            if skip:
                skip = False
            elif token in REDIRECT:
                skip = True  # the word after `>` is a file, not an argument
            elif not PUNCTUATION.fullmatch(token):
                words.append(token)
            else:
                if words:
                    yield words, stack[-1]
                    if words[0] == "cd":
                        operands = [w for w in words[1:] if not w.startswith("-")]
                        stack[-1] = _resolve(operands[0], stack[-1]) if len(operands) == 1 else None
                    words = []
                for char in token:
                    if char == "(":
                        stack.append(stack[-1])
                    elif char == ")" and len(stack) > 1:
                        stack.pop()


def _joined(words: list[str]) -> str:
    return "".join(f"{word} " for word in words)


def _paths(words: list[str], cwd: str | None) -> list[str]:
    found = (_resolve(word.split("::", 1)[0], cwd) for word in words)  # `file::node` runs the file
    return [path for path in found if path]


def _pytest_call(words: list[str], cwd: str | None) -> Iterator[Call]:
    for index, word in enumerate(words):
        if posixpath.basename(word) in PYTEST and PYTEST_LAUNCH.fullmatch(_joined(words[:index])):
            raw: list[str] = []
            ignored: list[str] = []
            args = iter(words[index + 1 :])
            for arg in args:
                if arg in NO_RUN:
                    return
                if arg == "--ignore":
                    ignored.append(next(args, ""))
                elif arg.startswith("--ignore="):
                    ignored.append(arg.partition("=")[2])
                elif arg in VALUE_OPTIONS:
                    next(args, None)
                elif not arg.startswith("-"):
                    raw.append(arg)
            yield Call("pytest", raw, _paths(raw, cwd), _paths(ignored, cwd))
            return


def _python_call(words: list[str], cwd: str | None) -> Iterator[Call]:
    for index, word in enumerate(words):
        if PYTHON.fullmatch(word) and UV_RUN.fullmatch(_joined(words[:index])):
            args = iter(words[index + 1 :])
            for arg in args:
                if arg in ("-m", "-c"):  # a module or code, not a file
                    break
                if arg in ("-W", "-X"):
                    next(args, None)
                elif not arg.startswith("-"):
                    yield Call("python", [arg], _paths([arg], cwd), [])
                    break
            return


def _mounts(words: list[str], cwd: str | None) -> dict[str, str]:
    """{container directory: repo-relative host directory} of the `-v HOST:CONTAINER[:MODE]` words.

    `$PWD` is the command's directory; the workspace variables are the checkout's root."""
    mounts: dict[str, str] = {}
    for flag, value in itertools.pairwise(words):
        host, _, rest = value.partition(":")
        if flag not in ("-v", "--volume") or not rest.startswith("/"):
            continue
        named = WORKSPACE.fullmatch(host)
        here = _resolve(host, cwd)
        if named:
            here = _resolve(named["rest"] or ".", cwd if named["pwd"] else ".")
        if here is not None:
            mounts[rest.partition(":")[0]] = here
    return mounts


def _promtool_call(words: list[str], cwd: str | None) -> Iterator[Call]:
    at = next((i for i in range(len(words) - 1) if words[i : i + 2] == ["test", "rules"]), None)
    if at is None or not any(posixpath.basename(word) == "promtool" for word in words):
        return
    mounts = _mounts(words, cwd)
    raw = [word for word in words[at + 2 :] if not word.startswith("-")]
    files: list[str | None] = []
    for word in raw:  # a container path maps back through its mount; any other is the host's
        inside = [dest for dest in mounts if word.startswith(dest + "/")]
        files.append(
            _resolve(word[len(inside[0]) + 1 :], mounts[inside[0]])
            if inside
            else _resolve(word, cwd)
        )
    yield Call("promtool", raw, [f for f in files if f], [])


def _calls(words: list[str], cwd: str | None) -> Iterator[Call]:
    """The test runners a simple command is: pytest, `python FILE` or `promtool test rules`."""
    lead = next((i for i, word in enumerate(words) if not ENV.fullmatch(word)), len(words))
    for detect in (_pytest_call, _python_call, _promtool_call):
        yield from detect(words[lead:], cwd)


def _runs(call: Call, path: str) -> bool:
    if any(_within(path, ignored) for ignored in call.ignored):
        return False
    if call.runner == "pytest":  # a directory runs every file below it
        return any(_within(path, target) for target in call.files)
    return path in call.files


def _gating(folder: Path = WORKFLOWS) -> set[str]:
    """`pr.yml` and the `_job-*.yml` workflows it calls: the runs a merge waits for."""
    doc = _load(folder / "pr.yml")
    jobs = [job for job in (doc.get("jobs") or {}).values() if not _inert(job)]
    called = {posixpath.basename(str(job["uses"])) for job in jobs if "uses" in job}
    return {"pr.yml", *(name for name in called if name.startswith("_job-"))}


def _runners(
    tracked: list[str], folder: Path = WORKFLOWS, only: set[str] | None = None
) -> dict[str, list[str]]:
    """{tracked file: the `workflow:job` of each command in `folder` that runs it}; with `only`,
    the commands of those workflow files alone."""
    runners: dict[str, list[str]] = {path: [] for path in tracked}
    for step in _steps(folder):
        if only is not None and step.workflow not in only:
            continue
        for words, cwd in _commands(step.script, step.cwd):
            for call in _calls(words, cwd):
                for path in tracked:
                    if _runs(call, path):
                        runners[path].append(f"{step.workflow}:{step.job}")
    return runners


def _exclusion_problems(
    excluded: dict[str, str],
    tracked: list[str],
    suites: Sequence[str] = gs.SUITES,
    folder: Path = WORKFLOWS,
) -> list[str]:
    """What is wrong with `excluded`: a path git does not track, that is under no suite, that
    pytest would not collect, that no run in `pr.yml` or a `_job-*.yml` it calls runs, or whose
    reason names no workflow that does."""
    runners = _runners(tracked, folder, only=_gating(folder))
    problems = []
    for path, reason in excluded.items():
        if path not in tracked:
            problems.append(f"{path}: git tracks no such file")
        elif not any(path.startswith(suite + "/") for suite in suites):
            problems.append(f"{path}: not under a suite, so nothing to exclude")
        elif not any(fnmatchcase(posixpath.basename(path), p) for p in gs.PYTHON_FILES):
            problems.append(f"{path}: pytest would not collect it, so nothing to exclude")
        elif not runners[path]:
            problems.append(f"{path}: no run in pr.yml or a _job-*.yml it calls runs it (orphan)")
        elif not any(run.split(":")[0] in reason for run in runners[path]):
            problems.append(
                f"{path}: the reason must name the workflow that runs it {runners[path]}"
            )
    return problems


def _test_dirs(tracked: list[str]) -> dict[str, list[str]]:
    """{outermost directory named `tests` or `test`: the tracked files below it}."""
    found: dict[str, list[str]] = {}
    for path in tracked:
        parts = path.split("/")
        for depth, part in enumerate(parts[:-1], 1):
            if part in ("tests", "test"):
                found.setdefault("/".join(parts[:depth]), []).append(path)
                break
    return found


def test_governance_gates_every_pull_request_with_its_shard_listing() -> None:
    # The orphan test counts governance_shards.suite_files() as run. That holds while governance
    # starts on every pull request (no paths, paths-ignore or branches filter), and a step of a job
    # with no `if` or `continue-on-error` lists the shard and hands it to pytest as a variable.
    doc = _load(WORKFLOWS / GOVERNANCE)
    on = doc[True]  # PyYAML reads the key `on` as True
    assert isinstance(on, dict) and "pull_request" in on and on["pull_request"] is None, on
    wired = []
    for job, spec in doc["jobs"].items():
        for step in spec.get("steps") or []:
            calls = [
                c for w, cwd in _commands(str(step.get("run", "")), ".") for c in _calls(w, cwd)
            ]
            lists = any(c.runner == "python" and c.files == [SHARDER] for c in calls)
            runs = any(
                c.runner == "pytest" and any(w.startswith("$") for w in c.raw) for c in calls
            )
            if lists and runs:
                wired.append((job, spec.keys() | step.keys()))
    assert wired, f"no {GOVERNANCE} step runs {SHARDER} and gives its output to pytest (#4361)"
    for job, keys in wired:
        assert not {"if", "continue-on-error"} & keys, f"{job} may skip its run or ignore it"


def test_every_test_file_is_run_by_a_workflow() -> None:
    tracked = _tracked()
    units = [path for path in tracked if _is_test_file(path)]
    assert set(KNOWN) <= set(units), f"the derivation broke: {sorted(set(KNOWN) - set(units))}"
    governed = set(gs.suite_files())
    runners = _runners(tracked)
    orphans = [path for path in units if path not in governed and not runners[path]]
    assert not orphans, (
        "no workflow runs these test files (#4361): add their directory to "
        "tools/ci/governance_shards.py SUITES, or run them in a lane's pytest command:\n  "
        + "\n  ".join(orphans)
    )


def test_each_governance_exclusion_is_run_by_a_gating_workflow() -> None:
    problems = _exclusion_problems(gs.EXCLUDED, _tracked())
    live = "infra/grafana/tests/test_live_render.py"  # fails by design under CI=true: no Grafana
    assert live not in gs.suite_files(), f"{live} needs the integration lane's Grafana"
    assert not problems, "\n".join(problems)


def test_every_tests_directory_holds_a_file_this_reader_recognises() -> None:
    # A tests directory with no test_*.py, *_test.py or *.test.yml (say, node tests) would be
    # skipped by the orphan test, so it fails here until this reader learns its runner.
    unread = [
        directory
        for directory, files in _test_dirs(_tracked()).items()
        if not any(_is_test_file(path) for path in files)
    ]
    assert not unread, f"test directories this guard cannot tell are run (#4361): {unread}"


TREE = [
    "infra/a/tests/test_a.py",
    "infra/a/tests/test_b.py",
    "infra/a/tests_extra/test_c.py",
    "infra/prometheus/tests/x.test.yml",
    "infra/prometheus/tests/y.test.yml",
    "scripts/canary_test.py",
]
AB = {"test_a.py", "test_b.py"}
PROM = 'docker run --entrypoint promtool -v "$PWD/infra/prometheus:/p:ro" $P'
RUN = "pytest infra/a/tests"
LIVE = "infra/grafana/tests/test_live_render.py"
PROMTOOL = [f"infra/prometheus/tests/{n}_alerts.test.yml" for n in ("ingestion", "system", "ws")]
NO_RUN_FLAGS = (  # written out, not read from NO_RUN, so that a spelling the reader lacks fails
    "--collect-only", "--co", "--collectonly", "--setup-only", "--setuponly", "--setup-plan",
    "--setupplan", "--fixtures", "--funcargs", "--fixtures-per-test", "--markers", "--version",
    "-V", "-VV", "--cache-show", "-h", "--help",
)  # fmt: skip


class Case(NamedTuple):
    script: str  # a workflow `run:`, written as the repository's workflows write them
    ran: set[str]  # the basenames of TREE it runs
    cwd: str = ""  # the step's working-directory
    job_cwd: str = ""  # the job's defaults.run.working-directory
    step: dict[str, Any] | None = None  # more keys of the step: `if`, `continue-on-error`
    job: dict[str, Any] | None = None  # more keys of the job


CASES = {
    "file": Case("pytest infra/a/tests/test_a.py", {"test_a.py"}),
    "directory-not-its-sibling": Case("pytest infra/a/tests", AB),
    "node-id": Case("pytest infra/a/tests/test_a.py::t -k y", {"test_a.py"}),
    "step-cwd": Case("uv run pytest ../../infra/a/tests", AB, cwd="services/api"),
    "job-cwd": Case("uv run pytest ../../infra/a/tests", AB, job_cwd="services/api"),
    "cd": Case("cd services/api\npython -m pytest ../../infra/a/tests", AB),
    "subshell-cd-does-not-leak": Case(
        "(cd services/api && pytest tests)\npytest infra/a/tests/test_b.py", {"test_b.py"}
    ),
    "substitution": Case("x=$(cd infra && pytest a/tests/test_a.py)", {"test_a.py"}),
    "ignore": Case("pytest infra/a --ignore=infra/a/tests/test_b.py", {"test_a.py", "test_c.py"}),
    "ignore-directory": Case("pytest infra/a --ignore infra/a/tests_extra", AB),
    "coverage-source": Case("pytest -n auto --cov infra/a tests", set()),
    "not-a-pytest-call": Case("pip install pytest infra/a/tests", set()),
    "echo-and-comment": Case("echo pytest infra/a/tests # pytest infra/a", set()),
    "unknown-cwd": Case("pytest infra/a/tests", set(), cwd="${{ matrix.dir }}"),
    "not-followed": Case('pytest ${files[@]} "$X/test_a.py" infra/a/*/test_b.py', set()),
    "python-file": Case("python scripts/canary_test.py --self-test", {"canary_test.py"}),
    "python-module": Case("python -m scripts.canary_test", set()),
    "python-options": Case("python -W error -X dev scripts/canary_test.py", {"canary_test.py"}),
    # /p is infra/prometheus: the container path maps back to the host file
    "promtool-mounted": Case(f"{PROM} test rules /p/tests/x.test.yml", {"x.test.yml"}),
    "promtool-check-rules": Case(f"{PROM} check rules /p/tests/y.test.yml", set()),
    "promtool-not-mounted": Case(f"{PROM} test rules /q/tests/x.test.yml", set()),
    "promtool-host": Case(
        "promtool test rules infra/prometheus/tests/x.test.yml infra/prometheus/tests/y.test.yml",
        {"x.test.yml", "y.test.yml"},
    ),
    # a command that stops before any test, or a step that never runs or fails unnoticed, runs none
    **{f"no-run{flag}": Case(f"pytest {flag} infra/a/tests", set()) for flag in NO_RUN_FLAGS},
    "no-run-after-the-paths": Case("pytest infra/a/tests -q --co", set()),
    "setup-show-runs": Case("pytest --setup-show infra/a/tests", AB),
    "continue-on-error": Case(RUN, set(), step={"continue-on-error": True}),
    "continue-on-error-false": Case(RUN, AB, step={"continue-on-error": False}),
    "job-continue-on-error": Case(RUN, set(), job={"continue-on-error": True}),
    "if-false": Case(RUN, set(), step={"if": False}),
    "if-false-expression": Case(RUN, set(), step={"if": "${{ false }}"}),
    "job-if-false": Case(RUN, set(), job={"if": False}),
    "if-expression-is-not-read": Case(RUN, AB, step={"if": "${{ github.event_name == 'push' }}"}),
}


@pytest.mark.parametrize("name", CASES)
def test_the_reader_follows_what_a_workflow_line_runs(tmp_path: Path, name: str) -> None:
    # The orphan test's negative controls: each line runs the files of TREE it should, and no other.
    case = CASES[name]
    step: dict[str, Any] = {
        "run": case.script,
        **({"working-directory": case.cwd} if case.cwd else {}),
        **(case.step or {}),
    }
    job: dict[str, Any] = {"runs-on": "ubuntu-latest", "steps": [step], **(case.job or {})}
    if case.job_cwd:
        job["defaults"] = {"run": {"working-directory": case.job_cwd}}
    (tmp_path / "w.yml").write_text(yaml.safe_dump({"jobs": {"j": job}}), encoding="utf-8")
    ran = {posixpath.basename(path) for path, jobs in _runners(TREE, tmp_path).items() if jobs}
    assert ran == case.ran


def test_an_exclusion_must_be_run_in_pr_yml_or_a_job_workflow_it_calls(tmp_path: Path) -> None:
    def write(name: str, jobs: dict[str, Any]) -> None:
        (tmp_path / name).write_text(yaml.safe_dump({"jobs": jobs}), encoding="utf-8")

    def runs(command: str) -> dict[str, Any]:
        return {"j": {"runs-on": "ubuntu-latest", "steps": [{"run": command}]}}

    calls = "./.github/workflows/"
    write(  # what pr.yml calls: a job workflow, one under `if: false`, one that is no `_job-*.yml`
        "pr.yml",
        {
            "a": {"uses": calls + "_job-a.yml"},
            "b": {"uses": calls + "_job-b.yml", "if": False},
            "c": {"uses": calls + "other.yml"},
        },
    )
    write("_job-a.yml", runs("pytest infra/a/tests/test_a.py"))
    write("_job-b.yml", runs("pytest infra/a/tests/test_b.py"))
    write("other.yml", runs("pytest infra/a/tests_extra/test_c.py"))
    write("nightly.yml", runs("python scripts/canary_test.py"))  # pr.yml never calls it
    assert _gating(tmp_path) == {"pr.yml", "_job-a.yml"}
    tracked, suites = [*TREE, "docs/x/test_x.py"], ("infra/a", "infra/prometheus", "scripts")
    assert (
        _exclusion_problems({"infra/a/tests/test_a.py": "by _job-a.yml"}, tracked, suites, tmp_path)
        == []
    )
    for path, reason, problem in [
        ("infra/a/missing/test_m.py", "by _job-a.yml", "git tracks no such file"),
        ("docs/x/test_x.py", "by _job-a.yml", "not under a suite"),
        ("infra/prometheus/tests/x.test.yml", "by _job-a.yml", "would not collect"),
        ("infra/a/tests/test_b.py", "by _job-b.yml", "orphan"),  # called under `if: false`
        ("infra/a/tests_extra/test_c.py", "by other.yml", "orphan"),  # not a `_job-*.yml`
        ("scripts/canary_test.py", "by nightly.yml", "orphan"),  # pr.yml never calls it
        ("infra/a/tests/test_a.py", "in the merge queue", "must name the workflow"),
    ]:
        found = _exclusion_problems({path: reason}, tracked, suites, tmp_path)
        assert len(found) == 1 and found[0].startswith(path) and problem in found[0], found


MUTATIONS = {  # a reference in a real workflow, how to remove it, and the files it ran
    "a-promtool-file": (
        "_job-py.yml", " /p/tests/ws_alerts.test.yml", "",
        ["infra/prometheus/tests/ws_alerts.test.yml"],
    ),
    "the-cd": (
        "_job-integration.yml", "cd services/api\n          uv run pytest ../../infra/grafana",
        "uv run pytest ../../infra/grafana", [LIVE],
    ),
    "the-mount": (
        "_job-py.yml", '-v "$PWD/infra/prometheus:/p:ro" $P test rules',
        '-v "$PWD/infra/prom:/p:ro" $P test rules', PROMTOOL,
    ),
    "the-live-render-line": (
        "_job-integration.yml",
        'uv run pytest ../../infra/grafana/tests/test_live_render.py -m "integration and not flaky"'
        " --no-cov -p no:cacheprovider\n",
        "", [LIVE],
    ),
}  # fmt: skip


@pytest.mark.parametrize("name", MUTATIONS)
def test_removing_one_reference_leaves_exactly_the_files_it_ran_without_a_runner(
    tmp_path: Path, name: str
) -> None:
    # AC3, kept in the tree: the real workflows, copied, with one reference removed.
    workflow, old, new, lost = MUTATIONS[name]
    shutil.copytree(WORKFLOWS, tmp_path / "workflows")
    target = tmp_path / "workflows" / workflow
    text = target.read_text(encoding="utf-8")
    assert text.count(old) == 1, f"{workflow} no longer holds {old!r}: update MUTATIONS"
    target.write_text(text.replace(old, new), encoding="utf-8")
    tracked = _tracked()
    before, after = _runners(tracked), _runners(tracked, tmp_path / "workflows")
    assert {path for path in tracked if before[path] and not after[path]} == set(lost)
