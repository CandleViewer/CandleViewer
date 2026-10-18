"""#3478: a workflow pytest call that sets its own `-m` keeps the addopts marker exclusions.

pytest keeps the last `-m`, so a call's own `-m` replaces the addopts `-m` of
`services/api/pyproject.toml`. cold-cache's py jobs did that and ran the fuzz, perf and harness
tests in one ~26k-test process, where their wall-clock and RSS budgets measure the whole session.
Rule, per marker the addopts `-m` deselects: a test carrying only that marker stays deselected,
unless the call names it outside a `not` (its own lane: `-m harness`, `-m "perf and not flaky"`)
or `ON_PURPOSE` lists it. A positive selection (`-m integration`) reaches a heavy test only if the
test carries both markers; that pairing is not modelled (the integration lanes drop `perf`)."""

from __future__ import annotations

import ast
import re
import shlex
import tomllib
from collections.abc import Iterator
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
OPERATOR = re.compile(r"[();<>|&]+")  # ends a simple command: `a && b`, `a || s=$?`, `a | tee`
ENV = re.compile(r"[A-Za-z_]\w*=.*")
# What may stand before `pytest`: `uv run [--flags]`, then `python -m`; anything else fails loudly.
LAUNCHER = re.compile(r"(?:uv run(?: -\S+)* )?(?:(?:\S*/)?python[\d.]* -m )?")
EXPRESSION = (ast.Name, ast.Load, ast.BoolOp, ast.And, ast.Or, ast.UnaryOp, ast.Not)
# Markers a job runs on purpose without naming them in its `-m`: (workflow, job) -> markers.
ON_PURPOSE = {
    # tests/contract/ws/test_ws_s2_s9.py: "the `py-perf` job and the contract job run it".
    ("_job-contract.yml", "contract"): {"perf"},
}


def _parse(expr: str) -> ast.expr:
    """A `-m` expression of marker names, `not`, `and`, `or` and parentheses; else ValueError."""
    tree: ast.expr | None
    try:
        tree = ast.parse(expr.strip(), mode="eval").body
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
    """The deselected markers whose tests this `-m` runs without naming them (the #3478 defect)."""
    tree = _parse(expr)
    return {marker for marker in deselected - _named(tree) if _selects(tree, {marker})}


def _marker_expression(args: list[str]) -> str | None:
    """The `-m` that pytest applies (it keeps the last one), or None when the call sets none."""
    found: str | None = None
    words = iter(args)
    for word in words:
        if word == "-m":
            found = next(words, None)
            if found is None:
                raise ValueError("-m without an expression")
        elif word.startswith("-m="):
            found = word.removeprefix("-m=")
        elif word.startswith("-m"):
            raise ValueError(f"cannot read {word!r}: write -m EXPR or -m=EXPR")
    return found


def _deselected_by(addopts: str) -> set[str]:
    """The markers an addopts `-m` deselects (an addopts without `-m` fails loudly)."""
    tree = _parse(_marker_expression(shlex.split(addopts)) or "")
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    return {name for name in names if not _selects(tree, {name})}


def _marker_expressions(run: str) -> Iterator[str]:
    """The `-m` of every pytest call in a step's `run:` that sets one."""
    # YAML has already folded `>` blocks; join the backslash continuations of `|` blocks.
    for line in run.replace("\\\n", " ").splitlines():
        if "pytest" not in line:
            continue
        lexer = shlex.shlex(line, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        command: list[str] = []
        for word in [*lexer, ";"]:  # shlex raises ValueError on unbalanced quotes
            if not OPERATOR.fullmatch(word):
                command.append(word)
                continue
            at = next((i for i, w in enumerate(command) if Path(w).name == "pytest"), None)
            expr = None if at is None else _marker_expression(command[at + 1 :])
            if at is not None and expr is not None:
                prefix = [w for w in command[:at] if not ENV.fullmatch(w)]
                if not LAUNCHER.fullmatch("".join(f"{w} " for w in prefix)):
                    raise ValueError(f"cannot read the pytest launcher {prefix!r}")
                yield expr
            command = []


def _marker_calls(folder: Path = ROOT / ".github" / "workflows") -> list[tuple[str, str, str]]:
    """(workflow, job, `-m` expression) for every pytest call in a workflow that sets its own."""
    calls: list[tuple[str, str, str]] = []
    for path in sorted(folder.glob("*.y*ml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for job, spec in (doc.get("jobs") or {}).items():
            for step in spec.get("steps") or []:
                try:
                    found = list(_marker_expressions(str(step.get("run", ""))))
                except ValueError as err:
                    raise ValueError(f"{path.name} job {job}: {err}") from err
                calls += [(path.name, job, expr) for expr in found]
    return calls


PYPROJECT = tomllib.loads((ROOT / "services/api/pyproject.toml").read_text(encoding="utf-8"))
ADDOPTS: str = PYPROJECT["tool"]["pytest"]["ini_options"]["addopts"]
DESELECTED = _deselected_by(ADDOPTS)
CALLS = _marker_calls()
# An empty scan proves nothing: these jobs set their own -m today.
KNOWN = {
    ("cold-cache.yml", "cold-py"),
    ("cold-cache.yml", "explore-py"),
    ("_job-py.yml", "py-tests"),
    ("_job-py.yml", "py-perf"),
    ("_job-contract.yml", "contract"),
    ("fuzz-nightly.yml", "python"),
}


def test_scan_finds_the_addopts_markers_and_the_known_calls() -> None:
    assert DESELECTED and all(f"not {marker}" in ADDOPTS for marker in DESELECTED)
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
        ('uv run pytest tests \\\n  -m "c and i" \\\n  -k s2', ["c and i"]),
        ('s=0\nuv run pytest -m x "${p[@]}" || s=$?\nexit "$s"', ["x"]),
        (".venv/bin/pytest -m a -m b", ["b"]),
        ("pytest tests -q  # -m x", []),
        ("pip install pytest && python -m pytest scripts/tests -q", []),
        ('lane=$(python t.py pytest-args "$L")', []),
    ],
)
def test_reader_extracts_the_marker_expression(run: str, expected: list[str]) -> None:
    assert list(_marker_expressions(run)) == expected


@pytest.mark.parametrize(
    ("run", "error"),
    [
        ("uv run pytest tests -m", "-m without an expression"),
        ("uv run pytest -mperf", "write -m EXPR"),
        ("timeout 600 uv run pytest -m perf", "launcher"),
        ('uv run pytest -m "it', "No closing quotation"),
        ('pytest -m "$MARKERS"', "cannot read the -m expression"),
        ('pytest -m "${{ inputs.markers }}"', "cannot read the -m expression"),
        ('pytest -m ""', "cannot read the -m expression"),
        ("pytest -m a-b", "cannot read the -m expression"),
        ("pytest -m None", "cannot read the -m expression"),
        ('pytest -m "f(x=1)"', "cannot read the -m expression"),
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


def test_scan_reads_folded_and_literal_blocks_and_names_the_failing_job(tmp_path: Path) -> None:
    folded = "  f:\n    steps:\n      - run: >\n          uv run pytest\n          -m 'not x'\n"
    literal = '  l:\n    steps:\n      - run: |\n          pytest \\\n            -m "y"\n'
    (tmp_path / "a.yml").write_text(f"jobs:\n{folded}{literal}", encoding="utf-8")
    (tmp_path / "b.yaml").write_text("on: push\n", encoding="utf-8")
    assert _marker_calls(tmp_path) == [("a.yml", "f", "not x"), ("a.yml", "l", "y")]
    bad = "jobs:\n  c:\n    steps:\n      - run: pytest -mx\n"
    (tmp_path / "c.yml").write_text(bad, encoding="utf-8")
    with pytest.raises(ValueError, match=re.escape("c.yml job c: cannot read '-mx'")):
        _marker_calls(tmp_path)
    assert _deselected_by('-m "not a and not (b or c)" -q') == {"a", "b", "c"}
