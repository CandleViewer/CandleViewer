"""SR-188 (#3125): `_Connection.push_system` is the one place a `system` frame is queued.

It asks `ws/system_filter.system_view` what the socket's principal may receive, so a producer that
queued a frame of its own on the channel, or named `push_system` outside its senders, would
skip the per-role filter (`23-ws-protocol.md` §15.9, S15). Over every module of `candleviewer`:

- a frame on the `system` channel (a dict literal whose `"ch"` is the topic, whatever its other
  keys, or a `ch=` argument) is built only by `_Connection.push_system` in `ws/gateway.py`. A
  `sub_ok` result row names the topic without being a frame: it has no `"t"`, and has `"ok"` or
  `"sub_id"`. The topic is `"system"`, `SYSTEM_TOPIC` (as an import alias too), a name or an
  attribute a module copies it to, at any scope (`TOPIC = SYSTEM_TOPIC`, `self.chan = ...`,
  `A, B = 1, SYSTEM_TOPIC`, `(t := SYSTEM_TOPIC)`, a parameter default `def f(ch=SYSTEM_TOPIC)`)
  and `getattr(m, "SYSTEM_TOPIC")`. Names and attributes are one namespace per module: a class
  attribute `TOPIC` is read as `K.TOPIC` or `self.TOPIC`, and so is the `TOPIC` of any other
  object, and a plain `TOPIC`. The key may be a name that holds `"ch"`;
- `push_system` is named, called or passed on, only by `GatewayHub.broadcast_system`,
  `GatewayHub.shutdown`, `run_auth` (the notices after the first `auth_ok`),
  `GatewayHub.system_sessions` (E42-T03: it hands each socket's `push_system` to the flag push) and
  `_send` in `admin/flags/push.py` (E42-T03: `FlagPush.flag_changed` and `notify_maintenance`
  resolve each session's frame, so there is no one body to broadcast; `push_system` still
  filters it, the path B3's review asked for). A new caller of `_send` is an RBAC change too.
  The string "push_system" counts as a name (`getattr(conn, "push_system")`).

A new producer calls `GatewayHub.broadcast_system`. Any other reference fails here and must be
reviewed as an RBAC change first (C-12.4), as for `test_key_selfcheck_store_callers.py`.
Limits: a tripwire for an accident, not a proof, and it reads each module on its own. It does not
see a channel or method name built at run time (`"sys" + "tem"`, an f-string), a channel a
caller passes in (a parameter default is followed), a return value or a container, a frame filled
in key by key (`frame["ch"] = ...`, `update`), built from pairs or sent already encoded, a copy of
the topic or of the `ch` key imported from another module, a `ch` key bound by `:=` in the key
position, a `getattr` of a copy, a copy made by a conditional or boolean expression, a loop,
`with` or `match` target, `setattr` or a subscript, a frame whose `t` key is a name and that also
has `ok` or `sub_id` (it reads as a result row), or code outside `candleviewer`. It reports a
frame it should not for a result row whose `ok` or `sub_id` key is a name, for a name and an
attribute of one spelling, which are one name, for a name rebound to another value, and for the
same name in another function (one name per module). A starred unpacking is read position by
position, so one that does not line up is missed or reported wrongly.
"""

from __future__ import annotations

import ast
import warnings
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

import candleviewer

PKG = Path(candleviewer.__file__).resolve().parent
BUILDERS = {("ws/gateway.py", "_Connection.push_system")}
SENDERS = {
    ("ws/gateway.py", "GatewayHub.broadcast_system"),
    ("ws/gateway.py", "GatewayHub.shutdown"),
    ("ws/gateway.py", "GatewayHub.system_sessions"),
    ("ws/gateway.py", "run_auth"),
    ("admin/flags/push.py", "_send"),
}
#: A `sub_ok` result row has no `t` and one of these.
RESULT_ROW = frozenset({"ok", "sub_id"})


def _scoped(node: ast.AST, scope: str = "<module>") -> Iterator[tuple[ast.AST, str]]:
    """Each node under `node` with its innermost enclosing function: `Class.method` for a method,
    the bare name for any other function, `<module>` outside both."""
    for child in ast.iter_child_nodes(node):
        inner = scope
        if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
            inner = f"{node.name}.{child.name}" if isinstance(node, ast.ClassDef) else child.name
        yield child, inner
        yield from _scoped(child, inner)


def _holds(node: ast.expr | None, names: set[str], text: str) -> bool:
    """The string `text`, or a name, or an attribute of any object, that `names` holds."""
    if isinstance(node, ast.Constant):
        return bool(node.value == text)
    return (isinstance(node, ast.Name) and node.id in names) or (
        isinstance(node, ast.Attribute) and node.attr in names
    )


def _is_system(node: ast.expr | None, names: set[str]) -> bool:
    """The system topic: the string, a name or attribute in `names` (`SYSTEM_TOPIC` and its
    copies), an assignment expression of one, or `getattr(m, "SYSTEM_TOPIC")`."""
    if isinstance(node, ast.NamedExpr):
        return _is_system(node.value, names)
    if isinstance(node, ast.Call):
        args = node.args
        return (
            isinstance(node.func, ast.Name)
            and node.func.id == "getattr"
            and len(args) > 1
            and isinstance(args[1], ast.Constant)
            and args[1].value == "SYSTEM_TOPIC"
        )
    return _holds(node, names, "system")


def _is_ch(node: ast.expr | None, names: set[str]) -> bool:
    """The key `"ch"`: the string, or a name or attribute in `names` (`CH = "ch"`)."""
    return _holds(node, names, "ch")


def _pairs(target: ast.expr, value: ast.expr) -> list[tuple[ast.expr, ast.expr]]:
    """`(target, value)`; for a tuple or list on both sides, each element against the one in its
    position, as deep as both go."""
    if isinstance(target, ast.Tuple | ast.List) and isinstance(value, ast.Tuple | ast.List):
        return [p for t, v in zip(target.elts, value.elts, strict=False) for p in _pairs(t, v)]
    return [(target, value)]


def _defaults(args: ast.arguments) -> list[tuple[ast.expr, ast.expr]]:
    """Each parameter with its default (`def f(ch=SYSTEM_TOPIC)`, a lambda's too): the positional
    ones right-aligned with `defaults`, the keyword-only ones with `kw_defaults` (`None`: none)."""
    positional = [*args.posonlyargs, *args.args]
    both: list[tuple[ast.arg, ast.expr | None]] = [
        *zip(positional[len(positional) - len(args.defaults) :], args.defaults, strict=True),
        *zip(args.kwonlyargs, args.kw_defaults, strict=True),
    ]
    return [(ast.Name(id=a.arg, ctx=ast.Store()), d) for a, d in both if d is not None]


def _bindings(tree: ast.AST) -> list[tuple[ast.expr, ast.expr]]:
    """Each (target, value) a module binds, at any scope: `a = v`, `a: T = v`, `(a := v)`, a
    parameter with its default and the elements of a tuple or list unpacked (`a, b = v, w`)."""
    found: list[tuple[ast.expr, ast.expr]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            found += [p for target in node.targets for p in _pairs(target, node.value)]
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            found += _pairs(node.target, node.value)
        elif isinstance(node, ast.NamedExpr):
            found.append((node.target, node.value))
        elif isinstance(node, ast.arguments):
            found += _defaults(node)
    return found


def _held(
    tree: ast.AST, names: set[str], holds: Callable[[ast.expr | None, set[str]], bool]
) -> set[str]:
    """`names` and each name, or attribute of any object, assigned a value that `holds` accepts,
    at any scope, to a fixed point (`B = A` after `A = ...`)."""
    pairs = _bindings(tree)
    while True:
        found = set(names)
        for target, value in pairs:
            if not holds(value, names):
                continue
            if isinstance(target, ast.Name):
                found.add(target.id)
            elif isinstance(target, ast.Attribute):
                found.add(target.attr)
        if found == names:
            return names
        names = found


def _topic_names(tree: ast.AST) -> set[str]:
    """The names that hold the topic in a module: `SYSTEM_TOPIC`, what it is imported as, and what
    `_held` finds assigned it or one of these (`B = A` after `A = ...`)."""
    imported = {
        a.asname or a.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for a in node.names
        if a.name == "SYSTEM_TOPIC"
    }
    return _held(tree, {"SYSTEM_TOPIC"} | imported, _is_system)


def _spelled(key: ast.expr | None, chs: set[str]) -> object:
    """A dict key as the constant it spells: `"ch"` for the string or a name that holds it."""
    if _is_ch(key, chs):
        return "ch"
    return key.value if isinstance(key, ast.Constant) else None


def _builds_frame(node: ast.AST, names: set[str], chs: set[str]) -> bool:
    if isinstance(node, ast.Dict):  # a `ch` of the topic, unless it is a `sub_ok` result row
        keys = {_spelled(k, chs): v for k, v in zip(node.keys, node.values, strict=True)}
        is_row = "t" not in keys and not RESULT_ROW.isdisjoint(keys)
        return _is_system(keys.get("ch"), names) and not is_row
    # `_reply("d", ch="system")`, `dict(t="d", ch=SYSTEM_TOPIC)`
    return isinstance(node, ast.keyword) and node.arg == "ch" and _is_system(node.value, names)


def _names_push_system(node: ast.AST) -> bool:
    if isinstance(node, ast.Constant):  # getattr(conn, "push_system")
        return bool(node.value == "push_system")
    return isinstance(node, ast.Attribute) and node.attr == "push_system"


def _sites(source: str) -> tuple[set[str], set[str]]:
    """(functions that build a frame on the system channel, functions that name `push_system`)."""
    built: set[str] = set()
    named: set[str] = set()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", SyntaxWarning)  # an applied migration may carry one
        tree = ast.parse(source)
    names, chs = _topic_names(tree), _held(tree, set(), _is_ch)
    for node, scope in _scoped(tree):
        if _builds_frame(node, names, chs):
            built.add(scope)
        elif _names_push_system(node):
            named.add(scope)
    return built, named


def _scan(root: Path = PKG) -> tuple[set[tuple[str, str]], set[tuple[str, str]]]:
    built: set[tuple[str, str]] = set()
    named: set[tuple[str, str]] = set()
    for path in root.rglob("*.py"):
        found_built, found_named = _sites(path.read_text(encoding="utf-8"))
        module = path.relative_to(root).as_posix()
        built |= {(module, scope) for scope in found_built}
        named |= {(module, scope) for scope in found_named}
    return built, named


def test_a_frame_on_the_system_channel_is_built_only_by_push_system() -> None:
    built, _ = _scan()
    assert built == BUILDERS, "a frame built beside push_system skips the SR-188 filter (C-12.4)"


def test_push_system_is_named_only_by_its_senders() -> None:
    _, named = _scan()
    assert named == SENDERS, "push_system named outside its senders skips the SR-188 filter"


@pytest.mark.parametrize(
    "source",
    [
        'conn.push({"t": "d", "ch": "system", "s": 1, "p": body})',
        'conn.push({"t": "snap", "ch": SYSTEM_TOPIC})',
        'conn.push({"t": "d", "ch": gateway.SYSTEM_TOPIC})',
        'conn.push(_reply("d", None, ch="system"))',
        'conn.push(dict(t="d", ch=SYSTEM_TOPIC))',
        # whatever its other keys, however it is spelled
        'conn.push({"ch": SYSTEM_TOPIC, "p": body})',
        'conn.push({**base, "ch": "system"})',
        'conn.push({"t": "d"} | {"ch": SYSTEM_TOPIC})',
        "conn.push(dict(base, ch=SYSTEM_TOPIC))",
        'conn.push(**{"ch": "system"})',
        'conn.push({"t": "d", "ch": "system", "ok": True})',  # a frame has `t`: not a result row
        'conn.push({"t": "d", "ch": "sys" "tem"})',
        'conn.push({"t": "d", "ch": "\\x73ystem"})',
        # the topic under another name
        "from gateway import SYSTEM_TOPIC as TOPIC\nconn.push({'t': 'd', 'ch': TOPIC})",
        "TOPIC = SYSTEM_TOPIC\nconn.push({'t': 'd', 'ch': TOPIC})",
        "TOPIC: Final = 'system'\nconn.push({'t': 'd', 'ch': TOPIC})",
        "A = SYSTEM_TOPIC\nB = A\nconn.push({'t': 'd', 'ch': B})",
        "conn.push({'t': 'd', 'ch': getattr(gateway, 'SYSTEM_TOPIC')})",
        # the topic held as an attribute or a lambda default, taken out of a tuple, bound by `:=`
        "self.chan = SYSTEM_TOPIC\nconn.push({'t': 'd', 'ch': self.chan})",
        "class K:\n    TOPIC = SYSTEM_TOPIC\nconn.push({'t': 'd', 'ch': K.TOPIC})",
        "push = lambda c, ch=SYSTEM_TOPIC: c.push({'t': 'd', 'ch': ch})",
        # by design a name and an attribute of one spelling are one name, whoever holds it, and a
        # starred unpacking that does not line up is read by position (B is 2)
        "self.chan = SYSTEM_TOPIC\nconn.push({'t': 'd', 'ch': chan})",
        "chan = SYSTEM_TOPIC\nconn.push({'t': 'd', 'ch': other.chan})",
        "*A, B = 1, SYSTEM_TOPIC, 2\nconn.push({'t': 'd', 'ch': B})",
        "A, B = 1, SYSTEM_TOPIC\nconn.push({'t': 'd', 'ch': B})",
        "[A, B] = [SYSTEM_TOPIC, 1]\nconn.push({'t': 'd', 'ch': A})",
        "A, (B, C) = 1, (SYSTEM_TOPIC, 2)\nconn.push({'t': 'd', 'ch': B})",
        "A, *B = SYSTEM_TOPIC, 1, 2\nconn.push({'t': 'd', 'ch': A})",
        "if (t := SYSTEM_TOPIC):\n    conn.push({'t': 'd', 'ch': t})",
        "conn.push({'t': 'd', 'ch': (t := SYSTEM_TOPIC)})",
        # the `ch` key spelled through a name
        "CH = 'ch'\nconn.push({'t': 'd', CH: SYSTEM_TOPIC})",
    ],
)
def test_a_frame_built_on_the_system_channel_is_found(source: str) -> None:
    assert _sites(source)[0] == {"<module>"}


_K = "class K:\n    %s\n    def send(self, c):\n        c.push({'t': 'd', 'ch': self.%s})"
_PUSH = "    conn.push({'t': 'd', 'ch': ch, 'p': body})"


@pytest.mark.parametrize(
    ("source", "scope"),
    [
        (_K % ("def __init__(self):\n        self.chan = SYSTEM_TOPIC", "chan"), "K.send"),
        (_K % ("TOPIC = SYSTEM_TOPIC", "TOPIC"), "K.send"),
        ("def _push(conn, body, ch=SYSTEM_TOPIC):\n" + _PUSH, "_push"),
        ("def _push(conn, ch=SYSTEM_TOPIC, /, *, body):\n" + _PUSH, "_push"),
        ("def _push(conn, *, body, ch=SYSTEM_TOPIC):\n" + _PUSH, "_push"),
        ("async def _push(conn, ch=SYSTEM_TOPIC, /, body=None, retries=3):\n" + _PUSH, "_push"),
    ],
    ids=[
        "instance-attribute",
        "class-attribute",
        "default",
        "positional-only",
        "keyword-only",
        "async-positional-only",
    ],
)
def test_a_copy_of_the_topic_held_by_a_class_or_a_default_is_found_where_the_frame_is_built(
    source: str, scope: str
) -> None:
    assert _sites(source)[0] == {scope}


def test_a_copy_of_the_topic_made_in_a_function_is_found_there() -> None:
    assert _sites("def f(c):\n    t = SYSTEM_TOPIC\n    c.push({'t': 'd', 'ch': t})")[0] == {"f"}


def test_a_file_is_parsed_whatever_text_it_holds(tmp_path: Path) -> None:
    """No text prefilter: `"sys" "tem"` holds none of the words a search for the topic finds."""
    (tmp_path / "ws").mkdir()
    (tmp_path / "ws" / "x.py").write_text("def f(c):\n    c.push({'t': 'd', 'ch': 'sys' 'tem'})\n")
    assert _scan(tmp_path) == ({("ws/x.py", "f")}, set())


@pytest.mark.parametrize(
    "source",
    [
        'row = {"ch": SYSTEM_TOPIC, "ok": True, "sub_id": SYSTEM_TOPIC}',  # a `sub_ok` result row
        'row = {"ch": "system", "ok": True}',  # a result row: no `t`, an `ok`
        'conn.push({"t": "d", "ch": "book.BTCUSDT.50"})',
        'conn.push({"t": "d", "ch": ch})',
        'body = {"kind": "system"}',
        "from elsewhere import TOPIC\nconn.push({'t': 'd', 'ch': TOPIC})",  # not this topic
        "TOPIC = 'book'\nconn.push({'t': 'd', 'ch': TOPIC})",
        # a copy that is not the topic: another value, another element, a key that is not `ch`
        "self.chan = 'book'\nconn.push({'t': 'd', 'ch': self.chan})",
        "A, B = SYSTEM_TOPIC, 'book'\nconn.push({'t': 'd', 'ch': B})",
        "CH = 'x'\nconn.push({'t': 'd', CH: SYSTEM_TOPIC})",
        "CH = 'ch'\nrow = {CH: SYSTEM_TOPIC, 'ok': True}",  # a result row, whatever its key spells
        "def _push(c, ch='book'):\n    c.push({'t': 'd', 'ch': ch})",  # another default
        "def _push(c, ch, topic=SYSTEM_TOPIC):\n    c.push({'t': 'd', 'ch': ch})",  # `ch` has none
        # nor has a keyword-only `ch`; a `:=` of another value, in an `if` and in the frame
        "def _push(c, *, ch, topic=SYSTEM_TOPIC):\n    c.push({'t': 'd', 'ch': ch})",
        "if (t := 'book'):\n    conn.push({'t': 'd', 'ch': t})",
        "conn.push({'t': 'd', 'ch': (t := 'book')})",
    ],
)
def test_a_frame_on_another_channel_or_a_result_row_is_not_found(source: str) -> None:
    assert _sites(source)[0] == set()


@pytest.mark.parametrize(
    ("source", "scope"),
    [
        ("conn.push_system(body)", "<module>"),
        ("def f(c):\n    c.push_system(1)", "f"),
        ("class A:\n    def m(self, c):\n        c.push_system(1)", "A.m"),
        ("class A:\n    async def m(self, c):\n        [x.push_system(1) for x in c]", "A.m"),
        ("def outer():\n    def inner(c):\n        c.push_system(1)", "inner"),
        ("sinks.append(conn.push_system)", "<module>"),  # passed on, not called
        ("send = getattr(conn, 'push_system')", "<module>"),  # by name
    ],
)
def test_a_reference_to_push_system_is_found_in_its_function(source: str, scope: str) -> None:
    assert _sites(source)[1] == {scope}


def test_the_definition_and_the_hubs_own_door_are_not_references() -> None:
    source = (
        "class C:\n    def push_system(self):\n        'Calls push_system.'\n"
        "hub.broadcast_system(b)"
    )
    assert _sites(source)[1] == set()
