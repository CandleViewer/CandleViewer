"""#3555: a `$`-anchored validation pattern is applied with `fullmatch`, never `match`.

`$` also matches just before a trailing newline, so `re.compile(r"^[A-Z]+$").match("BTC\\n")`
succeeds and a newline-carrying value slips past validation. `fullmatch` refuses it. The guard
parses every backend module and flags `<anchored regex>.match(...)`, where the regex is a name
bound to `re.compile(<literal ending in "$">)` (in the module, or imported from one that binds
it), or a pattern given inline to `re.match` / `re.compile(...).match`. Unanchored patterns,
`fullmatch` and `search` are never flagged.
"""

from __future__ import annotations

import ast
from pathlib import Path

import candleviewer

ROOT = Path(candleviewer.__file__).resolve().parent


def _is_re_call(node: ast.AST, func: str) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == func
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "re"
    )


def _anchored_literal(node: ast.expr) -> bool:
    """True when the pattern literal (plain or f-string) ends in an unescaped `$`."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        text = node.value
    elif isinstance(node, ast.JoinedStr) and node.values:
        last = node.values[-1]
        if not (isinstance(last, ast.Constant) and isinstance(last.value, str)):
            return False
        text = last.value
    else:
        return False
    if not text.endswith("$"):
        return False
    backslashes = len(text) - 1 - len(text[:-1].rstrip("\\"))
    return backslashes % 2 == 0


def _anchored_compile(node: ast.AST | None) -> bool:
    return (
        node is not None
        and _is_re_call(node, "compile")
        and bool(node.args)  # type: ignore[attr-defined]  # _is_re_call proved this is a Call
        and _anchored_literal(node.args[0])  # type: ignore[attr-defined]  # same
    )


def _terminal(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _bindings(tree: ast.AST) -> tuple[set[str], set[str]]:
    """Names bound to an anchored `re.compile`, and names bound to any other value."""
    anchored: set[str] = set()
    other: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        else:
            continue
        for target in targets:
            name = _terminal(target)
            if name is not None:
                (anchored if _anchored_compile(value) else other).add(name)
    return anchored, other


def find_violations(source: str, imported_anchored: frozenset[str] = frozenset()) -> list[int]:
    """Line numbers of `.match` calls on an anchored pattern in `source`."""
    tree = ast.parse(source)
    anchored, other = _bindings(tree)
    imported = {
        (alias.asname or alias.name)
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
        if alias.name in imported_anchored
    }
    names = (anchored - other) | imported
    lines: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if _is_re_call(node, "match") and node.args and _anchored_literal(node.args[0]):
            lines.append(node.lineno)
        elif isinstance(node.func, ast.Attribute) and node.func.attr == "match":
            receiver = node.func.value
            if _anchored_compile(receiver) or (
                (name := _terminal(receiver)) is not None and name in names
            ):
                lines.append(node.lineno)
    return sorted(lines)


def _module_files() -> list[Path]:
    return sorted(p for p in ROOT.rglob("*.py") if "__pycache__" not in p.parts)


def test_anchored_patterns_use_fullmatch() -> None:
    sources = {p: p.read_text(encoding="utf-8") for p in _module_files()}
    exported = frozenset(
        name
        for text in sources.values()
        for name in _bindings(ast.parse(text))[0]
        if not name.startswith("__")
    )
    offenders = [
        f"{path.relative_to(ROOT.parent).as_posix()}:{line}"
        for path, text in sources.items()
        for line in find_violations(text, exported)
    ]
    message = "anchored (`$`) pattern applied with .match; use .fullmatch (#3555): "
    assert not offenders, message + ", ".join(offenders)


def test_guard_flags_match_on_anchored_compiled_name() -> None:
    src = 'import re\n_R = re.compile(r"^[A-Z]+$")\ndef f(v):\n    return _R.match(v)\n'
    assert find_violations(src) == [4]


def test_guard_flags_attribute_and_class_bound_names() -> None:
    src = (
        'import re\nclass C:\n    _R = re.compile(r"^a$")\n'
        "    def f(self, v):\n        return self._R.match(v)\n"
    )
    assert find_violations(src) == [5]


def test_guard_flags_inline_re_match_and_inline_compile() -> None:
    src = 'import re\nre.match(r"^a$", "x")\nre.compile(r"^a$").match("x")\n'
    assert find_violations(src) == [2, 3]


def test_guard_flags_fstring_pattern_ending_in_dollar() -> None:
    src = 'import re\nn = 3\n_R = re.compile(rf"^a{{1,{n}}}$")\n_R.match("x")\n'
    assert find_violations(src) == [4]


def test_guard_flags_imported_anchored_name() -> None:
    src = "from candleviewer.ws.topics import SYMBOL_RE\nSYMBOL_RE.match('x')\n"
    assert find_violations(src, frozenset({"SYMBOL_RE"})) == [2]
    assert find_violations(src) == []


def test_guard_allows_fullmatch_and_search() -> None:
    src = (
        'import re\n_R = re.compile(r"^[A-Z]+$")\n_R.fullmatch("x")\n_R.search("x")\n'
        're.fullmatch(r"^a$", "x")\n'
    )
    assert find_violations(src) == []


def test_guard_allows_match_on_unanchored_patterns() -> None:
    src = (
        'import re\n_P = re.compile(r"^part-")\n_P.match("part-1")\n'
        're.match(r"abc", "abcd")\n_E = re.compile(r"cost\\$")\n_E.match("cost$")\n'
    )
    assert find_violations(src) == []


def test_guard_ignores_name_rebound_to_unanchored_pattern() -> None:
    src = (
        'import re\nclass A:\n    _R = re.compile(r"^a$")\nclass B:\n'
        '    _R = re.compile(r"^b")\n    def f(self):\n        return self._R.match("b")\n'
    )
    assert find_violations(src) == []
