"""24-internal-schemas §2.9 (E26-T03): no production subscriber uses a wildcard `env`.

A bus topic's `env` is `live`, `demo`, `testnet` or one replay session's `replay-<uuid>`. A
`TopicPattern` whose `env` is the wildcard matches every one of them, so its subscriber would see
every replay session's events next to the live ones (C-2.11). None exists, and this keeps it so.
Over every module of `candleviewer` it flags:

- `TopicPattern(...)`, `TopicPattern.model_construct(...)` or `TopicPattern.model_validate({...})`
  whose `env` (keyword, first positional argument or dict key) is the wildcard: the string `"*"`,
  the name `WILDCARD` or any attribute named `WILDCARD`;
- a pattern string whose first segment is the wildcard, passed to `TopicPattern.parse(...)` or to
  any `.subscribe(...)` call (positionally or as `pattern=`): a literal like `"*.md.X.trade"`, an
  f-string that starts with `*` or `{WILDCARD}`, a `+` concatenation whose leftmost operand is
  one of those, or `".".join([...])` whose first element is the wildcard.

Limits: a tripwire for an accident, not a proof. It does not follow a pattern, or a string, built
in one place and passed or returned to another, a name bound to the wildcard under another name,
`%` or `str.format` formatting, or code outside `candleviewer`. Tests may subscribe with a
wildcard `env` (they observe everything on purpose); production code never does.
"""

from __future__ import annotations

import ast
import warnings
from pathlib import Path

import pytest

import candleviewer
from candleviewer.bus.models import WILDCARD

PKG = Path(candleviewer.__file__).resolve().parent


def _wild(node: ast.expr | None) -> bool:
    """The wildcard itself: `"*"`, `WILDCARD` or `<anything>.WILDCARD`."""
    if isinstance(node, ast.Constant):
        return node.value == WILDCARD
    return (isinstance(node, ast.Name) and node.id == "WILDCARD") or (
        isinstance(node, ast.Attribute) and node.attr == "WILDCARD"
    )


def _wild_first_segment(node: ast.expr) -> bool:
    """A dotted pattern string whose first segment (the `env`) is the wildcard."""
    if isinstance(node, ast.Constant):
        return isinstance(node.value, str) and node.value.split(".", 1)[0] == WILDCARD
    if isinstance(node, ast.JoinedStr):
        first = node.values[0] if node.values else None
        if isinstance(first, ast.FormattedValue):
            return _wild(first.value)
        return isinstance(first, ast.Constant) and _wild_first_segment(first)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _wild(node.left) or _wild_first_segment(node.left)
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "join"
        and node.args
        and isinstance(node.args[0], ast.List | ast.Tuple)
        and node.args[0].elts
    ):
        return _wild(node.args[0].elts[0])
    return False


def _names_pattern(func: ast.expr) -> bool:
    return (isinstance(func, ast.Name) and func.id == "TopicPattern") or (
        isinstance(func, ast.Attribute) and func.attr == "TopicPattern"
    )


def _env_argument(call: ast.Call) -> ast.expr | None:
    for kw in call.keywords:
        if kw.arg == "env":
            return kw.value
    return call.args[0] if call.args else None


def _dict_env(node: ast.expr | None) -> ast.expr | None:
    if isinstance(node, ast.Dict):
        for key, value in zip(node.keys, node.values, strict=True):
            if isinstance(key, ast.Constant) and key.value == "env":
                return value
    return None


def violations(source: str, name: str) -> list[str]:
    """`name:line` of each wildcard-`env` subscription in `source`."""
    found: list[str] = []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", SyntaxWarning)  # an applied migration may carry one
        tree = ast.parse(source, name)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func, bad = node.func, False
        if _names_pattern(func):
            bad = _wild(_env_argument(node))
        elif isinstance(func, ast.Attribute) and _names_pattern(func.value):
            if func.attr == "model_construct":
                bad = _wild(_env_argument(node))
            elif func.attr == "model_validate":
                bad = _wild(_dict_env(node.args[0] if node.args else None))
            elif func.attr == "parse":
                bad = bool(node.args) and _wild_first_segment(node.args[0])
        elif isinstance(func, ast.Attribute) and func.attr == "subscribe":
            args = [*node.args, *(kw.value for kw in node.keywords if kw.arg == "pattern")]
            bad = any(_wild_first_segment(arg) for arg in args)
        if bad:
            found.append(f"{name}:{node.lineno}")
    return found


def scan(root: Path) -> list[str]:
    """Every wildcard-`env` subscription under `root`, as `relative/path.py:line`."""
    found: list[str] = []
    for path in sorted(root.rglob("*.py")):
        found += violations(path.read_text(encoding="utf-8"), str(path.relative_to(root)))
    return found


def test_no_production_subscriber_uses_a_wildcard_env() -> None:
    assert scan(PKG) == [], "a wildcard env would see every replay session (24 §2.9, C-2.11)"


BAD = {
    "kw.py": 'p = TopicPattern(env="*", domain="md", symbol="BTCUSDT", detail="trade")\n',
    "name.py": "p = TopicPattern(env=WILDCARD, domain='md')\n",
    "attr.py": "p = models.TopicPattern(env=bus_models.WILDCARD, domain='md')\n",
    "positional.py": "p = TopicPattern('*', 'md', 'BTCUSDT', 'book')\n",
    "construct.py": "p = TopicPattern.model_construct(env='*', domain='md')\n",
    "validate.py": "p = TopicPattern.model_validate({'env': WILDCARD, 'domain': 'md'})\n",
    "parse.py": "p = TopicPattern.parse('*.md.BTCUSDT.trade')\n",
    "subscribe.py": "s = bus.subscribe('x', '*.md.BTCUSDT.trade', QueuePolicy.NEVER_DROP)\n",
    "keyword.py": "s = self._bus.subscribe(name='x', pattern='*.md.*.book', policy=p)\n",
    "fstring.py": "s = bus.subscribe('x', f'{WILDCARD}.md.{sym}.trade', p)\n",
    "fconst.py": "s = bus.subscribe('x', f'*.md.{sym}.trade', p)\n",
    "concat.py": "s = bus.subscribe('x', WILDCARD + '.md.' + sym, p)\n",
    "join.py": "s = bus.subscribe('x', '.'.join([WILDCARD, 'md', sym]), p)\n",
}
GOOD = (
    'p = TopicPattern(env=env, domain="md", symbol=WILDCARD, detail="trade")\n'
    "s = bus.subscribe('x', 'live.md.*.trade', QueuePolicy.NEVER_DROP)\n"
    "s = bus.subscribe('x', f'{env}.md.{sym}.trade', p)\n"
    "s = bus.subscribe('x', topic.key, p)\n"
    "gate.subscribe(listener)\n"
    "hub.subscribe({'ch': 'positions', 'sym': '*'})\n"
    "p = TopicPattern.parse(f'{self._env}.health.*')\n"
)


@pytest.mark.parametrize("name", sorted(BAD))
def test_the_scan_flags_each_kind_of_wildcard_env(name: str) -> None:
    assert violations(BAD[name], name) == [f"{name}:1"]


def test_the_scan_walks_every_module_under_a_root_and_spares_a_concrete_env(
    tmp_path: Path,
) -> None:
    """The negative fixture as files: a package whose modules each break the rule once, beside
    one that subscribes properly. The scan names exactly the bad ones."""
    pkg = tmp_path / "pkg" / "sub"
    pkg.mkdir(parents=True)
    for name, source in BAD.items():
        (pkg / name).write_text(source, encoding="utf-8")
    (tmp_path / "pkg" / "fine.py").write_text(GOOD, encoding="utf-8")
    assert scan(tmp_path / "pkg") == sorted(f"sub/{name}:1" for name in BAD)
