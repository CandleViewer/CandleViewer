"""#3461: the product's exchange clients take their TLS and their route from code.

Clients: every httpx client or transport in `candleviewer/` and `cvdev/` passes `trust_env=False`
and the adapter's context (`verify=exchange_tls_context()`), with no `proxy`, no `mounts` and no
`follow_redirects` but `False`; every `websockets` dial passes `proxy=None` and an `ssl=` that comes
from the builder. Contexts: no module under `candleviewer/exchange/` reads the environment
(`os.environ`, `os.environb`, `getenv`). In `exchange/bybit/`, nothing builds a context from the
environment (CPython's `create_default_context`, httpx's `create_ssl_context`, the platform store's
two loaders), names a key log or uses `CERT_NONE`; outside `tls.py` nothing builds a context or sets
`check_hostname` or `verify_mode`; `tls.py` imports no `os` and loads its roots once, from
`cafile=certifi.where()` alone.

Limits: AST checks, so an alias or a name built at run time is not caught, as in
`test_signed_client_transport.py`.
"""

from __future__ import annotations

import ast
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path

import pytest

import candleviewer
import cvdev

ROOTS = (Path(candleviewer.__file__).resolve().parent, Path(cvdev.__file__).resolve().parent)
EXCHANGE = ROOTS[0] / "exchange"
ADAPTER = EXCHANGE / "bybit"
CLIENTS = frozenset({"AsyncClient", "Client", "AsyncHTTPTransport", "HTTPTransport"})
READS_ENV = frozenset(
    {
        "create_default_context",
        "create_ssl_context",
        "load_default_certs",
        "set_default_verify_paths",
    }
)
CONTEXTS = frozenset({"SSLContext", "_create_unverified_context", "_create_stdlib_context"})
ENVIRON = frozenset({"environ", "environb", "getenv", "getenvb"})
#: The public market-data stream's dial is #5498's, listed here until that lands.
PUBLIC_STREAM = "candleviewer/exchange/bybit/public_ws.py"


def _name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    return node.attr if isinstance(node, ast.Attribute) else None


def _is(node: ast.expr | None, value: object) -> bool:
    return isinstance(node, ast.Constant) and node.value is value


def _from_builder(tree: ast.Module) -> Callable[[ast.expr | None], bool]:
    """Whether an expression is the builder's context: its call, a call of a function that returns
    only one, a name bound only to one, or a conditional whose other arm is None (`ws://`)."""
    calls, names = {"exchange_tls_context"}, set()

    def ours(node: ast.expr | None) -> bool:
        if isinstance(node, ast.IfExp):
            arms = [arm for arm in (node.body, node.orelse) if not _is(arm, None)]
            return len(arms) == 1 and ours(arms[0])
        if isinstance(node, ast.Call):
            return _name(node.func) in calls
        return isinstance(node, ast.Name) and node.id in names

    bound: defaultdict[str, list[ast.expr]] = defaultdict(list)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    bound[target.id].append(node.value)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value:
            bound[node.target.id].append(node.value)
    functions = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)]
    for _ in range(3):  # a function, a name and a conditional: each one step from the builder
        for function in functions:
            returns = [n.value for n in ast.walk(function) if isinstance(n, ast.Return)]
            if returns and all(ours(value) for value in returns):
                calls.add(function.name)
        names |= {name for name, values in bound.items() if all(ours(v) for v in values)}
    return ours


def _dials(tree: ast.Module) -> set[str]:
    """The names a module dials `websockets` through: `connect` imported from it, and subclasses."""
    names = {
        alias.asname or alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("websockets")
        for alias in node.names
        if alias.name == "connect"
    }
    subclasses = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef) and any(_name(base) in names for base in node.bases)
    }
    return names | subclasses


def _dialled(call: ast.Call, dials: set[str]) -> bool:
    """`call` dials `websockets`: through a name `_dials` found, or `websockets.connect` itself."""
    root = call.func
    while isinstance(root, ast.Attribute):
        root = root.value
    return _name(call.func) in dials or (_name(call.func), _name(root)) == ("connect", "websockets")


def _clients(source: str) -> list[str]:
    """Each httpx client or transport and each `websockets` dial: `pinned`, or what it lacks."""
    tree = ast.parse(source)
    ours, dials, found = _from_builder(tree), _dials(tree), []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        given = {keyword.arg: keyword.value for keyword in node.keywords}
        if _name(node.func) in CLIENTS:
            kind = "httpx"
            rules = {
                "trust_env": _is(given.get("trust_env"), False),
                "verify": ours(given.get("verify")),
                "proxy": "proxy" not in given,
                "mounts": "mounts" not in given,
                "follow_redirects": _is(given.get("follow_redirects", ast.Constant(False)), False),
            }
        elif _dialled(node, dials):
            kind = "dial"
            rules = {"proxy": _is(given.get("proxy"), None), "ssl": ours(given.get("ssl"))}
        else:
            continue
        found.append(f"{kind} {','.join(rule for rule, ok in rules.items() if not ok) or 'pinned'}")
    return found


def _env_reads(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Attribute) and node.attr in ENVIRON:
        return ["environ"]
    if isinstance(node, ast.ImportFrom) and node.module == "os":
        return ["environ"] if {alias.name for alias in node.names} & ENVIRON else []
    return []


def _adapter_findings(node: ast.AST, *, builder: bool) -> list[str]:
    if builder and isinstance(node, ast.Import | ast.ImportFrom):
        modules = [node.module or ""] if isinstance(node, ast.ImportFrom) else []
        modules += [alias.name for alias in node.names] if isinstance(node, ast.Import) else []
        return ["os import"] if any(m.split(".")[0] == "os" for m in modules) else []
    if isinstance(node, ast.Call) and _name(node.func) in READS_ENV:
        return ["env context"]
    if isinstance(node, ast.Call) and _name(node.func) in CONTEXTS:
        return [] if builder else ["context"]
    if isinstance(node, ast.Call) and _name(node.func) == "load_verify_locations":
        given = [*map(ast.unparse, node.args), *map(ast.unparse, node.keywords)]
        return [f"roots {', '.join(given)}"]
    if isinstance(node, ast.Name | ast.Attribute) and _name(node) == "CERT_NONE":
        return ["CERT_NONE"]
    if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Store):
        if node.attr == "keylog_filename":
            return ["key log"]
        if node.attr in {"check_hostname", "verify_mode"} and not builder:
            return ["verify store"]
    return []


def _contexts(source: str, *, adapter: bool = True, builder: bool = False) -> list[str]:
    """What reads the environment (any exchange module), or builds, loosens or loads a TLS context
    (an adapter module); `builder` is `tls.py`, the one module that builds one."""
    found = []
    for node in ast.walk(ast.parse(source)):
        found += _env_reads(node) + (_adapter_findings(node, builder=builder) if adapter else [])
    return sorted(found)


_WS = "from websockets.asyncio.client import connect as dial\n"
_PINNED = "httpx.AsyncClient(trust_env=False, verify=exchange_tls_context(){})"


@pytest.mark.parametrize(
    ("source", "found"),
    [
        ("httpx.AsyncClient()", ["httpx trust_env,verify"]),
        (_PINNED.format(""), ["httpx pinned"]),
        ("AsyncClient(trust_env=False, verify=True)", ["httpx verify"]),
        (_PINNED.format(", proxy=None"), ["httpx proxy"]),
        (_PINNED.format(", mounts={}"), ["httpx mounts"]),
        (_PINNED.format(", follow_redirects=True"), ["httpx follow_redirects"]),
        ("httpx.AsyncHTTPTransport(verify=context)", ["httpx trust_env,verify"]),
        ("httpx.Timeout(5.0)", []),
        (_WS + "dial(url)", ["dial proxy,ssl"]),
        (_WS + "dial(url, proxy=None, ssl=True)", ["dial ssl"]),
        ("import websockets\nwebsockets.connect(url, ssl=exchange_tls_context())", ["dial proxy"]),
        (
            _WS + "class Own(dial): ...\ndef tls(): return exchange_tls_context()\nTLS = tls()\n"
            "ssl = TLS if secure else None\nOwn(url, proxy=None, ssl=ssl)",
            ["dial pinned"],
        ),
        ("def connect(url): ...\nconnect(url)", []),
    ],
)
def test_the_scan_reads_each_client_rule(source: str, found: list[str]) -> None:
    assert _clients(source) == found


@pytest.mark.parametrize(
    ("source", "builder", "found"),
    [
        ("os.environ['X']", False, ["environ"]),
        ("from os import getenv", False, ["environ"]),
        ("import os", True, ["os import"]),
        ("import os", False, []),
        (
            "context.load_verify_locations(cafile=certifi.where())",
            True,
            ["roots cafile=certifi.where()"],
        ),
        ("context.load_verify_locations(capath=folder)", True, ["roots capath=folder"]),
        ("ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)", False, ["context"]),
        ("ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)", True, []),
        ("ssl._create_unverified_context()", False, ["context"]),
        ("ssl._create_stdlib_context()", False, ["context"]),
        ("ssl.create_default_context()", True, ["env context"]),
        ("httpx.create_ssl_context(verify=True, trust_env=False)", False, ["env context"]),
        ("context.load_default_certs()", True, ["env context"]),
        ("context.set_default_verify_paths()", True, ["env context"]),
        ("context.check_hostname = False", False, ["verify store"]),
        ("context.verify_mode = ssl.CERT_NONE", True, ["CERT_NONE"]),
        ("context.keylog_filename = path", True, ["key log"]),
        ('"""Never `create_default_context`, `os.environ` or `CERT_NONE`."""', False, []),
    ],
)
def test_the_scan_reads_each_context_rule(source: str, builder: bool, found: list[str]) -> None:
    assert _contexts(source, builder=builder) == found


def test_an_exchange_module_outside_the_adapter_is_scanned_for_environment_reads_only() -> None:
    assert _contexts("os.getenv('X')\nssl.CERT_NONE", adapter=False) == ["environ"]


def test_every_exchange_client_and_context_is_pinned() -> None:
    """The httpx clients are the REST client's and the trade archive's, the dials the two
    private-WS connectors' (listing them shows the scan sees them; a new one fails here until it is
    pinned), beside the public stream's (#5498's). The one context is `tls.py`'s, with its roots
    loaded once, and no exchange module reads the environment."""
    clients, contexts = {}, {}
    for root in ROOTS:
        for path in sorted(root.rglob("*.py")):
            text, name = path.read_text(encoding="utf-8"), path.relative_to(root.parent).as_posix()
            if ("httpx" in text or "websockets" in text) and (found := _clients(text)):
                clients[name] = found
            if path.is_relative_to(EXCHANGE):
                adapter = path.parent == ADAPTER
                found = _contexts(text, adapter=adapter, builder=adapter and path.name == "tls.py")
                contexts.update({name: found} if found else {})
    assert clients == {
        "candleviewer/exchange/bybit/archive.py": ["httpx pinned"],
        "candleviewer/exchange/bybit/key_ws_probe.py": ["dial pinned", "dial pinned"],
        PUBLIC_STREAM: ["dial proxy,ssl"],
        "candleviewer/exchange/bybit/rest.py": ["httpx pinned"],
    }
    assert contexts == {"candleviewer/exchange/bybit/tls.py": ["roots cafile=certifi.where()"]}
