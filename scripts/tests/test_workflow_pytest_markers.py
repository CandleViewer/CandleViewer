"""#3478: a workflow pytest call that sets its own `-m` keeps the addopts marker exclusions.

pytest keeps the last `-m`, so a call's own `-m` replaces the addopts `-m` of
`services/api/pyproject.toml`. cold-cache's py jobs did that and ran the fuzz, perf and harness
tests in one ~26k-test process, where their wall-clock and RSS budgets measure the whole session.
Rule, per marker the addopts `-m` deselects: a test carrying only that marker stays deselected,
unless the call names it outside a `not` (its own lane: `-m harness`, `-m "perf and not flaky"`)
or `ON_PURPOSE` lists it. Not modelled: a heavy test that also carries a marker the call selects
(an integration+perf test under `-m integration`).
#3091 (C-9.3): QUARANTINE is stricter, as a quarantined test keeps its lane markers: no mix of the
markers a call names may select it, naming it is not a lane, and no ON_PURPOSE entry may exempt it.
A call without its own -m, and a local run, read the addopts of the nearest pytest config at or
above their paths. Every tracked config's addopts -m keeps QUARANTINE out under every mix of
markers, and the root pytest.ini is that config for every suite outside services/api and scripts.
The scan reads each step's `run:` as bash does (a comment starts only at a word that begins with
`#`), the command lines quoted in it (`bash -c "..."`) and the SCRIPTS a step runs. It fails
loudly on the other ways to set or replace addopts' -m: a pytest command word in a string other
than a `run:`, `name:` or `id:` (an env, matrix or action input), a `$` in a pytest call that
`EXPANSIONS` does not list, PYTEST_ADDOPTS or UV_ENV_FILE anywhere in a workflow or a SCRIPTS
file, `--env-file`, `pytest.main`, a `-qm` cluster, `-c`/`--config-file`, an `addopts` override
and `@file`.
Not read: pytest that any other script runs."""

from __future__ import annotations

import ast
import re
import shlex
import subprocess
import tomllib
from collections.abc import Iterator
from itertools import combinations
from pathlib import Path

import iniconfig
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
PYTEST = ("pytest", "py.test")
OPERATOR = re.compile(r"[();<>|&]+")  # a run of shell punctuation that shlex splits off
SEPARATOR = re.compile(r"[();|&]+")  # ends a simple command: `a && b`, `a || s=$?`, `a | tee`
REDIRECT = {"<", ">", ">>", ">&", "<&", "&>", "&>>", ">|", "<>", "<<", "<<<"}  # takes one word
ENV = re.compile(r"[A-Za-z_]\w*=.*")
WORD = re.compile(r"[^\s'\"();|&<>]+")  # a shell word with its quotes and operators cut off
# A line and its comment, which starts at a `#` that begins a word outside quotes. shlex would also
# start one inside a word (`$#`, `${#x}`) and drop the rest of the line, so it gets no commenters.
COMMENT = re.compile(
    r"""^((?:[^'"\\#]|\\.|'[^']*'|"(?:[^"\\]|\\.)*"|(?<=[^\s;&|()<>])#)*)(?<![^\s;&|()<>])#.*"""
)
# What may stand before `pytest`: `uv run [--flags]`, then `python -m`; anything else fails loudly.
LAUNCHER = re.compile(r"(?:uv run(?: -\S+)* )?(?:(?:\S*/)?python[\d.]* -m )?")
# Arguments that swap or drop addopts' -m: `-c FILE`, `--config-file`, `-o addopts=`, `@argsfile`.
SWAPS_ADDOPTS = re.compile(r"-[A-Za-z]*c|--config-file|@|.*addopts")
CARRIERS = ("PYTEST_ADDOPTS", "UV_ENV_FILE")  # in an env map, a prefix, export or $GITHUB_ENV
UNSEEN = ("--env-file", "pytest.main")  # on a pytest line: an env file, arguments built in Python
EXPRESSION = (ast.Name, ast.Load, ast.BoolOp, ast.And, ast.Or, ast.UnaryOp, ast.Not)
# Markers a job runs on purpose without naming them in its `-m`: (workflow, job) -> markers.
ON_PURPOSE = {
    # Every perf test in tests/contract runs here and in py-perf, as before #3478: S7 in
    # ws/test_ws_s2_s9.py (its note says so) and the parse budget in bybit/test_contract_leakage.py.
    ("_job-contract.yml", "contract"): {"perf"},
}
# `$` words a job's pytest call may carry, and why none can hold a -m: (workflow, job) -> words.
EXPANSIONS = {
    # tools/ci/py_test_lanes.py pytest-args prints paths and --ignore= only: its collects() raises
    # on any other option, and test_py_test_lanes runs it on every lane.
    ("_job-py.yml", "py-tests"): frozenset({"${lane_paths[@]}"}),
}
QUARANTINE = "flaky"  # C-9.3 quarantines a test by adding it on top of the test's lane markers
# Shell scripts a workflow step runs, read like a `run:` (#3091): the blocking xstate-contract gate.
SCRIPTS = ("tools/statechart/run_xstate_contract.sh",)
# The files pytest reads as its config, in the order its findpaths.locate_config tries them.
CONFIG_NAMES = (
    *("pytest.toml", ".pytest.toml", "pytest.ini", ".pytest.ini"),
    *("pyproject.toml", "tox.ini", "setup.cfg"),
)


def _parse(expr: str) -> ast.expr:
    """A `-m` expression of marker names, `not`, `and`, `or` and parentheses; else ValueError.
    ASCII only: Python folds fullwidth letters into marker names (NFKC), pytest does not."""
    tree: ast.expr | None
    try:
        tree = ast.parse(expr.strip(), mode="eval").body if expr.isascii() else None
    except SyntaxError:
        tree = None
    if tree is None or not all(isinstance(node, EXPRESSION) for node in ast.walk(tree)):
        raise ValueError(f"cannot read the -m expression {expr!r}")
    return tree


def _selects(tree: ast.expr, markers: set[str]) -> bool:
    """Whether the expression selects a test that carries exactly `markers`."""
    if isinstance(tree, ast.Name):
        return tree.id in markers
    if isinstance(tree, ast.UnaryOp):  # `not`: _parse lets no other operator through
        return not _selects(tree.operand, markers)
    assert isinstance(tree, ast.BoolOp)
    hits = [_selects(value, markers) for value in tree.values]
    return all(hits) if isinstance(tree.op, ast.And) else any(hits)


def _named(tree: ast.expr, negated: bool = False) -> set[str]:
    """The markers the expression names outside an odd number of `not`s: its own lanes."""
    if isinstance(tree, ast.Name):
        return set() if negated else {tree.id}
    if isinstance(tree, ast.UnaryOp):
        return _named(tree.operand, not negated)
    assert isinstance(tree, ast.BoolOp)
    return {name for value in tree.values for name in _named(value, negated)}


def _lets_through(expr: str, deselected: set[str]) -> set[str]:
    """The deselected markers whose tests this `-m` runs without naming them (the #3478 defect).
    A lane marker is tried alone; QUARANTINE with every mix of the names, and naming it is not a
    lane."""
    tree = _parse(expr)
    names = sorted({node.id for node in ast.walk(tree) if isinstance(node, ast.Name)})
    through: set[str] = set()
    for marker in deselected - (_named(tree) - {QUARANTINE}):
        sizes = range(len(names) + 1) if marker == QUARANTINE else range(1)
        if any(_selects(tree, {marker, *mix}) for n in sizes for mix in combinations(names, n)):
            through.add(marker)
    return through


def _marker_expression(args: list[str]) -> str | None:
    """The `-m` that pytest applies (it keeps the last one), or None when the call sets none.
    Raises on an argument that sets or swaps it in a way this reader does not follow."""
    found: str | None = None
    words = iter(args)
    for word in words:
        if word == "-m":
            found = next(words, None)
            if found is None:
                raise ValueError("-m without an expression")
        elif word.startswith("-m="):
            found = word.removeprefix("-m=")
        elif re.match(r"-[A-Za-z]*m", word):  # `-mX` and `-qm X`: argparse reads both as -m
            raise ValueError(f"cannot read {word!r}: write -m EXPR or -m=EXPR")
        elif SWAPS_ADDOPTS.match(word):
            raise ValueError(f"cannot read {word!r}: it can replace addopts' -m")
    return found


def _deselected_by(addopts: str) -> set[str]:
    """The markers an addopts `-m` deselects (an addopts without `-m` fails loudly)."""
    tree = _parse(_marker_expression(shlex.split(addopts)) or "")
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    return {name for name in names if not _selects(tree, {name})}


def _runs_pytest(text: str) -> bool:
    """Whether a text holds a pytest command word (`pytest-report.xml`, `.pytest_cache` do not)."""
    return any(Path(word).name in PYTEST for word in WORD.findall(text))


def _nested(word: str) -> bool:
    """A word that holds a command line running pytest, as in `bash -c "uv run pytest -m x"`."""
    return len(word.split()) > 1 and _runs_pytest(word)


def _call(command: list[str], expansions: frozenset[str]) -> Iterator[str]:
    """The `-m` of a simple command that runs pytest, and of the command lines quoted in it."""
    for word in filter(_nested, command):
        yield from _marker_expressions(word, expansions)
    at = next((i for i, w in enumerate(command) if Path(w).name in PYTEST and not _nested(w)), None)
    if at is None:
        return
    prefix = [w for w in command[:at] if not ENV.fullmatch(w)]
    for word in [*prefix, *command[at:]]:
        if "$" in word and word not in expansions:
            raise ValueError(f"cannot read the expansion {word!r}: it can carry a -m (EXPANSIONS)")
    expr = _marker_expression(command[at + 1 :])
    if expr is not None:
        if not LAUNCHER.fullmatch("".join(f"{w} " for w in prefix)):
            raise ValueError(f"cannot read the pytest launcher {prefix!r}")
        yield expr


def _marker_expressions(run: str, expansions: frozenset[str] = frozenset()) -> Iterator[str]:
    """The `-m` of every pytest call in a step's `run:` that sets one."""
    # YAML has already folded `>` blocks; join the backslash continuations of `|` blocks.
    for line in run.replace("\\\n", " ").splitlines():
        code = COMMENT.sub(r"\1", line)  # unchanged when there is no comment or a quote is open
        if not any(name in code for name in PYTEST):
            continue
        unseen = next((word for word in UNSEEN if word in code), None)
        if unseen is not None:
            raise ValueError(f"cannot read {unseen}: it hides pytest's arguments")
        lexer = shlex.shlex(code, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        lexer.commenters = ""  # COMMENT has cut the comment where bash starts one
        command: list[str] = []
        words = iter([*lexer, ";"])  # shlex raises ValueError on unbalanced quotes
        for word in words:
            if word in REDIRECT and not OPERATOR.fullmatch(next(words, ";")):
                continue  # `2>&1 -m x`: pytest still gets the words after the redirection's target
            if not OPERATOR.fullmatch(word):
                command.append(word)
                continue
            if not SEPARATOR.fullmatch(word):  # `>(`, or a redirection without a target
                raise ValueError(f"cannot read the shell operator {word!r}")
            yield from _call(command, expansions)
            command = []


def _refuse_carriers(text: str) -> None:
    """Raise when a text names a variable that can replace addopts' -m (CARRIERS)."""
    carrier = next((name for name in CARRIERS if name in text), None)
    if carrier is not None:
        raise ValueError(f"cannot read {carrier}: it can replace addopts' -m")


def _strings(node: object, key: str = "") -> Iterator[tuple[str, str]]:
    """(key, value) for every string in a YAML tree; a list item keeps its list's key."""
    if isinstance(node, str):
        yield key, node
    for name, value in node.items() if isinstance(node, dict) else []:
        yield from _strings(value, str(name))
    for value in node if isinstance(node, list) else []:
        yield from _strings(value, key)


def _marker_calls(folder: Path = ROOT / ".github" / "workflows") -> list[tuple[str, str, str]]:
    """(workflow, job, `-m` expression) for every pytest call in a workflow that sets its own."""
    calls: list[tuple[str, str, str]] = []
    for path in sorted(folder.glob("*.y*ml")):
        text = path.read_text(encoding="utf-8")
        try:
            _refuse_carriers(text)
        except ValueError as err:
            raise ValueError(f"{path.name}: {err}") from err
        doc = yaml.safe_load(text) or {}
        for job, spec in (doc.get("jobs") or {}).items():
            expansions = EXPANSIONS.get((path.name, job), frozenset())
            for step in spec.get("steps") or []:
                try:  # pop: a run read here is not a string that names pytest out of sight below
                    found = list(_marker_expressions(str(step.pop("run", "")), expansions))
                except ValueError as err:
                    raise ValueError(f"{path.name} job {job}: {err}") from err
                calls += [(path.name, job, expr) for expr in found]
        for key, value in _strings(doc):
            if key not in ("name", "id") and _runs_pytest(value):
                raise ValueError(f"{path.name}: cannot read pytest in {key}: {value!r}; use run:")
    return calls


def _script_calls(root: Path = ROOT) -> list[tuple[str, str, str]]:
    """(script, "script", `-m` expression) for every pytest call in SCRIPTS that sets its own."""
    calls: list[tuple[str, str, str]] = []
    for script in SCRIPTS:
        text = (root / script).read_text(encoding="utf-8")
        try:  # an export or a $GITHUB_ENV line in the script reaches its pytest and later steps
            _refuse_carriers(text)
            found = list(_marker_expressions(text))
        except ValueError as err:
            raise ValueError(f"{script}: {err}") from err
        calls += [(script, "script", expr) for expr in found]
    return calls


def _keeps_quarantine_out(addopts: str) -> bool:
    """Whether the addopts -m deselects a quarantined test whatever else it carries (#3091).
    An addopts without -m deselects nothing."""
    expr = _marker_expression(shlex.split(addopts))
    return expr is not None and not _lets_through(expr, {QUARANTINE})


def _config_addopts(path: Path) -> str | None:
    """The addopts of a file that pytest reads as its config ("" when it sets none), or None when
    pytest skips the file. Raises on a TOML-mode config, which this reader does not read. An INI
    config is read with iniconfig, as pytest reads it: case-sensitive keys, no [DEFAULT] merge."""
    text = path.read_text(encoding="utf-8")
    if path.name in ("pytest.toml", ".pytest.toml"):
        raise ValueError("cannot read a TOML mode config: write pytest.ini")
    if path.name == "pyproject.toml":
        table = tomllib.loads(text).get("tool", {}).get("pytest")
        if table is None:
            return None  # pytest skips it: the root pytest.ini is above it
        if set(table) != {"ini_options"}:
            raise ValueError("cannot read TOML mode [tool.pytest]: use [tool.pytest.ini_options]")
        addopts = table["ini_options"].get("addopts", "")
        return addopts if isinstance(addopts, str) else shlex.join(addopts)
    sections = iniconfig.IniConfig(path, data=text).sections
    section = "tool:pytest" if path.suffix == ".cfg" else "pytest"
    if section in sections:
        return sections[section].get("addopts", "")
    return "" if path.name in ("pytest.ini", ".pytest.ini") else None  # read even when empty


def _configs(root: Path = ROOT) -> dict[str, str]:
    """{path: addopts} for every tracked file that pytest reads as its config."""
    git = ["git", "ls-files", "-z", "--", *(f"*{name}" for name in CONFIG_NAMES)]
    listing = subprocess.run(git, cwd=root, capture_output=True, text=True, check=True, timeout=60)
    configs: dict[str, str] = {}
    for path in filter(None, listing.stdout.split("\0")):
        if Path(path).name not in CONFIG_NAMES:
            continue
        try:
            addopts = _config_addopts(root / path)
        except (ValueError, iniconfig.ParseError) as err:
            raise ValueError(f"{path}: {err}") from err
        if addopts is not None:
            configs[path] = addopts
    return configs


PYPROJECT = tomllib.loads((ROOT / "services/api/pyproject.toml").read_text(encoding="utf-8"))
ADDOPTS: str = PYPROJECT["tool"]["pytest"]["ini_options"]["addopts"]
DESELECTED = _deselected_by(ADDOPTS)
try:
    CALLS, SCAN_ERROR = _marker_calls() + _script_calls(), ""
except ValueError as err:  # an unreadable call fails a test below, not the lane's collection
    CALLS, SCAN_ERROR = [], str(err)
try:
    CONFIGS, CONFIG_ERROR = _configs(), ""
except (ValueError, OSError, subprocess.SubprocessError) as err:  # fails a test below as well
    CONFIGS, CONFIG_ERROR = {}, str(err)
# An empty scan proves nothing: these jobs set their own -m today.
KNOWN = {
    ("cold-cache.yml", "cold-py"),
    ("cold-cache.yml", "explore-py"),
    ("_job-py.yml", "py-tests"),
    ("_job-py.yml", "py-perf"),
    ("_job-contract.yml", "contract"),
    ("fuzz-nightly.yml", "python"),
    (SCRIPTS[0], "script"),
}


def test_addopts_deselects_the_markers_the_pin_reads() -> None:
    assert DESELECTED and all(f"not {marker}" in ADDOPTS for marker in DESELECTED)


def test_addopts_keeps_quarantined_tests_out() -> None:
    """#3091 (C-9.3): a call without its own -m (pr.yml's golden-upcaster run) inherits it."""
    assert QUARANTINE in DESELECTED, f"add `and not {QUARANTINE}` to the addopts -m"
    assert _keeps_quarantine_out(ADDOPTS), "a mix of markers lets a quarantined test through"


@pytest.mark.parametrize(
    ("addopts", "out"),
    [
        ('-m "not fuzz and not flaky" -q', True),
        ('-m "not fuzz and (not flaky or integration)" -q', False),  # a flaky integration test
        ('-m "not fuzz" -q', False),
        ("-q", False),  # no -m: the call runs every test it collects
    ],
)
def test_addopts_rule_tries_every_mix_of_markers(addopts: str, out: bool) -> None:
    assert _keeps_quarantine_out(addopts) is out


def test_config_scan_reads_every_config() -> None:
    assert not CONFIG_ERROR, CONFIG_ERROR


def test_a_root_config_covers_every_other_suite() -> None:
    """pytest reads the nearest config at or above a call's paths. With one at the root, a call
    into tests/lint_statecharts (pr.yml) or infra/*/tests reads one of CONFIGS as well."""
    assert {"pytest.ini", "scripts/pytest.ini", "services/api/pyproject.toml"} <= set(CONFIGS)


@pytest.mark.parametrize(("config", "addopts"), sorted(CONFIGS.items()))
def test_every_pytest_config_keeps_quarantined_tests_out(config: str, addopts: str) -> None:
    """#3091 (C-9.3): a call without its own -m (governance's scripts/tests run) inherits it."""
    assert _keeps_quarantine_out(addopts), f'{config}: add -m "not {QUARANTINE}" to its addopts'


@pytest.mark.parametrize(
    ("name", "text", "addopts"),
    [
        ("pytest.ini", '[pytest]\naddopts = -m "not flaky"\n', '-m "not flaky"'),
        ("pytest.ini", "", ""),  # pytest reads a pytest.ini even when it is empty
        ("tox.ini", "[tox]\nenvlist = py\n", None),
        ("tox.ini", "[pytest]\naddopts = -q\n", "-q"),
        ("setup.cfg", "[tool:pytest]\naddopts = -q\n", "-q"),
        ("setup.cfg", "[metadata]\nname = x\n", None),
        ("pyproject.toml", '[tool.pytest.ini_options]\naddopts = ["-m", "not x"]\n', "-m 'not x'"),
        ("pyproject.toml", '[project]\nname = "x"\n', None),
    ],
)
def test_config_reader_returns_the_addopts_pytest_reads(
    tmp_path: Path, name: str, text: str, addopts: str | None
) -> None:
    (tmp_path / name).write_text(text, encoding="utf-8")
    assert _config_addopts(tmp_path / name) == addopts


@pytest.mark.parametrize(
    "text",
    [
        '[pytest]\nAddopts = -m "not flaky"\n',  # keys are case-sensitive: not an addopts
        '[DEFAULT]\naddopts = -m "not flaky"\n\n[pytest]\n',  # DEFAULT is a plain section
    ],
)
def test_config_reader_reads_an_ini_config_as_pytest_does(tmp_path: Path, text: str) -> None:
    """pytest reads an INI config with iniconfig: it matches an option name as written and does
    not merge [DEFAULT] into [pytest]. Each config here lets a quarantined test run."""
    (tmp_path / "pytest.ini").write_text(text, encoding="utf-8")
    addopts = _config_addopts(tmp_path / "pytest.ini")
    assert addopts == ""
    assert not _keeps_quarantine_out(addopts)


@pytest.mark.parametrize(
    ("name", "text"),
    [
        ("pytest.toml", ""),
        (".pytest.toml", '[pytest]\naddopts = ["-q"]\n'),
        ("pyproject.toml", '[tool.pytest]\naddopts = ["-q"]\n'),
    ],
)
def test_config_reader_fails_loudly_on_a_toml_mode_config(
    tmp_path: Path, name: str, text: str
) -> None:
    (tmp_path / name).write_text(text, encoding="utf-8")
    with pytest.raises(ValueError, match="TOML mode"):
        _config_addopts(tmp_path / name)


def test_config_scan_reads_tracked_configs_and_names_an_unreadable_one(tmp_path: Path) -> None:
    files = {
        "pytest.ini": '[pytest]\naddopts = -m "not flaky"\n',
        "a/pytest.ini": "",  # pytest reads it even when it is empty
        "b/tox.ini": "[tox]\n",  # no [pytest]: pytest skips it
        "c/my_pytest.ini": "[pytest]\n",  # a name pytest does not look for
        "d/pytest.toml": "",
    }
    for name, text in files.items():
        (tmp_path / name).parent.mkdir(exist_ok=True)
        (tmp_path / name).write_text(text, encoding="utf-8")
    (tmp_path / "e").mkdir()
    (tmp_path / "e" / "pytest.ini").write_text("", encoding="utf-8")  # untracked
    git = ["git", "-C", str(tmp_path)]
    subprocess.run([*git, "init", "-q"], check=True, timeout=60)
    subprocess.run([*git, "add", *list(files)[:4]], check=True, timeout=60)
    assert _configs(tmp_path) == {"pytest.ini": '-m "not flaky"', "a/pytest.ini": ""}
    subprocess.run([*git, "add", "d/pytest.toml"], check=True, timeout=60)
    with pytest.raises(ValueError, match=r"^d/pytest\.toml: cannot read a TOML mode config"):
        _configs(tmp_path)
    (tmp_path / "b" / "tox.ini").write_text("[pytest]\n  -q\n", encoding="utf-8")  # pytest fails
    with pytest.raises(ValueError, match=r"^b/tox\.ini: .*unexpected value continuation"):
        _configs(tmp_path)


def test_on_purpose_never_exempts_a_quarantined_test() -> None:
    """C-9.3 keeps a quarantined test out of every blocking lane, with no exemption."""
    assert all(QUARANTINE not in markers for markers in ON_PURPOSE.values())


def test_scan_reads_every_workflow() -> None:
    assert not SCAN_ERROR, SCAN_ERROR


def test_scan_finds_the_known_calls() -> None:
    assert KNOWN <= {(workflow, job) for workflow, job, _ in CALLS}


@pytest.mark.parametrize(("workflow", "job", "expr"), CALLS)
def test_workflow_call_keeps_the_addopts_exclusions(workflow: str, job: str, expr: str) -> None:
    through = _lets_through(expr, DESELECTED) - ON_PURPOSE.get((workflow, job), set())
    assert not through, f"{workflow} job {job}: -m {expr!r} runs {sorted(through)}; add `and not`"


@pytest.mark.parametrize(("workflow", "job"), sorted(ON_PURPOSE))
def test_on_purpose_entry_is_still_needed(workflow: str, job: str) -> None:
    runs = {
        m for w, j, e in CALLS if (w, j) == (workflow, job) for m in _lets_through(e, DESELECTED)
    }
    assert ON_PURPOSE[(workflow, job)] <= runs, "the job no longer runs it: drop the entry"


@pytest.mark.parametrize(
    ("run", "expected"),
    [
        ('uv run --no-cache pytest -p no:cacheprovider -m "not a" --no-cov', ["not a"]),
        ("python -m pytest tests -m 'perf and not flaky' -q", ["perf and not flaky"]),
        ("python3.12 -m pytest -m=harness -q", ["harness"]),
        ('cd x && CV=1 uv run python -m pytest -m="a or b" 2>&1 | tee log', ["a or b"]),
        ('uv run pytest tests 2>&1 -m "not a" >> log', ["not a"]),  # a redirection keeps the call
        ("py.test < in -m b", ["b"]),
        ('uv run pytest tests \\\n  -m "c and i" \\\n  -k s2', ["c and i"]),
        ('s=0\nuv run pytest -m x "${p[@]}" || s=$?\nexit "$s"', ["x"]),
        (".venv/bin/pytest -m a -m b", ["b"]),
        ("pytest tests -q  # don't read -m x", []),
        ('[ $# -eq 0 ] && uv run pytest -m "not a"', ["not a"]),  # `#` inside a word: no comment
        ('n=${#L}; pytest -k "t#1" -m "not a" || true', ["not a"]),
        ("timeout 900 bash -c \"uv run pytest -m 'not a'\"", ["not a"]),
        ('echo "::error::pytest failed"', []),
        ("pip install pytest && python -m pytest scripts/tests -q", []),
        ('lane=$(python t.py pytest-args "$L")', []),
    ],
)
def test_reader_extracts_the_marker_expression(run: str, expected: list[str]) -> None:
    assert list(_marker_expressions(run, frozenset({"${p[@]}"}))) == expected


@pytest.mark.parametrize(
    ("run", "error"),
    [
        ("uv run pytest tests -m", "-m without an expression"),
        ("uv run pytest -mperf", "write -m EXPR"),
        ("timeout 600 uv run pytest -m perf", "launcher"),
        ('uv run pytest -m "it', "No closing quotation"),
        ('pytest -m "$MARKERS"', "cannot read the expansion '$MARKERS'"),
        ('pytest -m "${{ inputs.markers }}"', "cannot read the expansion"),
        ("uv run pytest $ARGS", "cannot read the expansion '$ARGS'"),
        ('uv run pytest tests "${extra[@]}"', "cannot read the expansion '${extra[@]}'"),
        ("uv run pytest ${{ matrix.args }}", "cannot read the expansion '${{'"),
        ('pytest -m ""', "cannot read the -m expression"),
        ("pytest -m a-b", "cannot read the -m expression"),
        ("pytest -m None", "cannot read the -m expression"),
        ('pytest -m "f(x=1)"', "cannot read the -m expression"),
        ('pytest -m "not \uff50\uff45\uff52\uff46"', "cannot read the -m expression"),
        ("uv run pytest -qm perf", "write -m EXPR"),
        ("pytest -vxm 'not a'", "write -m EXPR"),
        ("uv run pytest -o addopts= tests", "replace addopts"),
        ("pytest --override-ini=addopts=-q", "replace addopts"),
        ("pytest -c other.toml", "replace addopts"),
        ("pytest --config-file=x.ini", "replace addopts"),
        ("pytest @args.txt", "replace addopts"),
        ("pytest tests >(tee log) -m a", "shell operator '>('"),
        ("pytest tests -m a >", "shell operator '>'"),
        ("uv run --env-file=ci.env pytest tests", "cannot read --env-file"),
        ("python -c \"import pytest; pytest.main(['-m', 'a'])\"", "cannot read pytest.main"),
    ],
)
def test_reader_and_rule_fail_loudly_on_what_they_cannot_read(run: str, error: str) -> None:
    with pytest.raises(ValueError, match=re.escape(error)):
        for expr in _marker_expressions(run):
            _lets_through(expr, {"a"})


@pytest.mark.parametrize(
    ("expr", "through"),
    [
        ("not x and not y", {"a", "b"}),  # the #3478 shape: a filter that drops addopts'
        ("not x and not a", {"b"}),
        ("not (a or b) and not x", set()),
        ("not (x and y)", {"a", "b"}),
        ("not x or a", {"b"}),  # names `a`, its lane; `b` still slips through
        ("a and not flaky", set()),
        ("not not b", set()),
        ("x and not a", set()),
    ],
)
def test_rule_flags_what_a_call_lets_through(expr: str, through: set[str]) -> None:
    assert _lets_through(expr, {"a", "b"}) == through


@pytest.mark.parametrize(
    ("expr", "through"),
    [
        ("integration", {QUARANTINE}),  # a quarantined integration test keeps `integration`
        ("chaos and integration", {QUARANTINE}),
        ("not (flaky and perf)", {QUARANTINE}),
        ("perf or chaos and not flaky", {QUARANTINE}),  # `and` binds first: a flaky perf test runs
        ("flaky", {QUARANTINE}),  # naming it is not a lane
        ("integration and not perf and not flaky", set()),
        ("(perf or chaos) and not flaky", set()),
        ("not (chaos or flaky) and not perf", set()),
    ],
)
def test_rule_keeps_a_quarantined_test_out_whatever_else_it_carries(
    expr: str, through: set[str]
) -> None:
    assert _lets_through(expr, {QUARANTINE}) == through


@pytest.mark.parametrize(
    ("text", "error"),
    [
        ("uv run pytest -mx\n", "cannot read '-mx'"),
        *[(f"export {c}=-q\nuv run pytest tests\n", f"cannot read {c}") for c in CARRIERS],
        ('echo "PYTEST_ADDOPTS=-q" >> "$GITHUB_ENV"\n', "cannot read PYTEST_ADDOPTS"),
    ],
)
def test_script_error_names_the_script(tmp_path: Path, text: str, error: str) -> None:
    (tmp_path / SCRIPTS[0]).parent.mkdir(parents=True)
    (tmp_path / SCRIPTS[0]).write_text(text, encoding="utf-8")
    with pytest.raises(ValueError, match=re.escape(f"{SCRIPTS[0]}: {error}")):
        _script_calls(tmp_path)


def test_scan_reads_folded_and_literal_blocks(tmp_path: Path) -> None:
    folded = "  f:\n    steps:\n      - run: >\n          uv run pytest\n          -m 'not x'\n"
    literal = '  l:\n    steps:\n      - run: |\n          pytest \\\n            -m "y"\n'
    (tmp_path / "a.yml").write_text(f"jobs:\n{folded}{literal}", encoding="utf-8")
    (tmp_path / "b.yaml").write_text("on: push\n", encoding="utf-8")
    assert _marker_calls(tmp_path) == [("a.yml", "f", "not x"), ("a.yml", "l", "y")]


def test_scan_error_names_the_workflow_and_job(tmp_path: Path) -> None:
    bad = "jobs:\n  c:\n    steps:\n      - run: pytest -mx\n"
    (tmp_path / "c.yml").write_text(bad, encoding="utf-8")
    with pytest.raises(ValueError, match=re.escape("c.yml job c: cannot read '-mx'")):
        _marker_calls(tmp_path)


@pytest.mark.parametrize("carrier", CARRIERS)
def test_scan_fails_loudly_on_an_addopts_carrier(tmp_path: Path, carrier: str) -> None:
    (tmp_path / "e.yml").write_text(f"env:\n  {carrier}: x\n", encoding="utf-8")
    with pytest.raises(ValueError, match=re.escape(f"e.yml: cannot read {carrier}")):
        _marker_calls(tmp_path)


@pytest.mark.parametrize(
    ("job", "key"),
    [
        ("steps:\n      - uses: x/y@v1\n        with:\n          command: pytest -m x", "command"),
        ("env:\n      CMD: uv run pytest -m x\n    steps:\n      - run: $CMD", "CMD"),
        ("strategy:\n      matrix:\n        cmd: [pytest -m x]\n    steps:\n      - run: x", "cmd"),
    ],
)
def test_scan_fails_loudly_on_pytest_outside_run(tmp_path: Path, job: str, key: str) -> None:
    (tmp_path / "o.yml").write_text(f"jobs:\n  j:\n    {job}\n", encoding="utf-8")
    with pytest.raises(ValueError, match=re.escape(f"o.yml: cannot read pytest in {key}:")):
        _marker_calls(tmp_path)


def test_scan_reads_no_call_in_a_name_an_id_or_a_path(tmp_path: Path) -> None:
    step = "      - id: pytest\n        name: pytest\n        uses: x/y@v1\n"
    with_path = "        with:\n          path: .pytest_cache\n"
    (tmp_path / "p.yml").write_text(f"jobs:\n  j:\n    steps:\n{step}{with_path}", encoding="utf-8")
    assert _marker_calls(tmp_path) == []


def test_addopts_reader_returns_the_markers_its_expression_deselects() -> None:
    assert _deselected_by('-m "not a and not (b or c)" -q') == {"a", "b", "c"}
