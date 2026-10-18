"""SR-188 (#3125): `_Connection.push_system` is the one place a `system` frame is queued.

It asks `ws/system_filter.system_view` what the socket's principal may receive, so a producer that
queued a frame of its own on the channel, or named `push_system` outside its senders, would
skip the per-role filter (`23-ws-protocol.md` §15.9, S15). Over every module of `candleviewer`:

- a frame on the `system` channel (a dict literal whose `"ch"` is the topic, whatever its other
  keys, or a `ch=` argument) is built only by `_Connection.push_system` in `ws/gateway.py`. A
  `sub_ok` result row names the topic without being a frame: it has no `"t"`, and has `"ok"` or
  `"sub_id"`. The topic is `"system"`, `SYSTEM_TOPIC` (as an import alias too), a name a module
  copies it to (`TOPIC = SYSTEM_TOPIC`, at any scope) and `getattr(m, "SYSTEM_TOPIC")`;
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
see a channel or method name built at run time (`"sys" + "tem"`, an f-string), a channel passed
positionally or through a parameter, a return value or a container, a frame filled in key by key
(`frame["ch"] = ...`, `update`), a copy of the topic imported from another module, or code outside
`candleviewer`.
"""

from __future__ import annotations

import ast
import warnings
from collections.abc import Iterator
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


def _is_system(node: ast.expr | None, names: set[str]) -> bool:
    """The system topic: the string, a name in `names`, an attribute spelled `SYSTEM_TOPIC`, or
    `getattr(m, "SYSTEM_TOPIC")`."""
    if isinstance(node, ast.Constant):
        return bool(node.value == "system")
    if isinstance(node, ast.Call):
        args = node.args
        return (
            isinstance(node.func, ast.Name)
            and node.func.id == "getattr"
            and len(args) > 1
            and isinstance(args[1], ast.Constant)
            and args[1].value == "SYSTEM_TOPIC"
        )
    return (isinstance(node, ast.Name) and node.id in names) or (
        isinstance(node, ast.Attribute) and node.attr == "SYSTEM_TOPIC"
    )


def _topic_names(tree: ast.AST) -> set[str]:
    """The names that hold the topic in a module: `SYSTEM_TOPIC`, what it is imported as, and each
    name assigned it or such a name, at any scope, to a fixed point (`B = A` after `A = ...`)."""
    names = {"SYSTEM_TOPIC"}
    while True:
        found = set(names)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                found |= {a.asname or a.name for a in node.names if a.name == "SYSTEM_TOPIC"}
            elif isinstance(node, ast.Assign | ast.AnnAssign) and _is_system(node.value, names):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                found |= {t.id for t in targets if isinstance(t, ast.Name)}
        if found == names:
            return names
        names = found


def _builds_frame(node: ast.AST, names: set[str]) -> bool:
    if isinstance(node, ast.Dict):  # a `ch` of the topic, unless it is a `sub_ok` result row
        keys = {
            k.value: v
            for k, v in zip(node.keys, node.values, strict=True)
            if isinstance(k, ast.Constant)
        }
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
    names = _topic_names(tree)
    for node, scope in _scoped(tree):
        if _builds_frame(node, names):
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
    ],
)
def test_a_frame_built_on_the_system_channel_is_found(source: str) -> None:
    assert _sites(source)[0] == {"<module>"}


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
