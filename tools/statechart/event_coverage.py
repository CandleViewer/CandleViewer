"""Event-name coverage gate (E50-T05, MUST-10; 29-statechart-adoption-plan.md §1.7).

AST-scans every ``<gateway>.send(key, event)`` / ``.send_threadsafe(key, event)``
call site under ``services/api/candleviewer`` and fails when a *literal* event
name is not declared as a transition event in the target machine's descriptor
(``statechart/machines/BNN.<id>.machine.json``).

Resolution rules (conservative, offline, deterministic):

* machine: a literal key's part before ``:`` (``order:123``); otherwise the
  ``kind=`` the key expression was ``register``-ed under in the same file (or
  the file's sole registered kind). A machine naming no descriptor is a
  finding. Only if unresolvable is the event checked against the union of all
  machines (weakest fallback).
* wrappers: a function forwarding one of its parameters as the event of a send
  (``{"type": event, **p}``), directly or via another wrapper, is detected;
  its call sites with a literal event are checked against the machine the
  wrapper sends to. A wrapper is keyed by its qualified name and a call matches
  it only through the caller's imports, the defining module, ``self`` on the
  defining class or a subclass, or a reviewed ``PORT_WRAPPERS`` entry for an
  injected port object; never by bare function name (#4730).
* event name: a string literal, a ``{"type": "<lit>"}`` dict, or an
  ``Event("<lit>")`` / ``Event(type="<lit>")`` call. Non-literal events cannot
  be checked statically and are skipped.

Exit 0 = clean, 1 = findings, 2 = usage error or a stale ``PORT_WRAPPERS`` entry.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MACHINES = _ROOT / "services/api/candleviewer/statechart/machines"
DEFAULT_SCAN = _ROOT / "services/api/candleviewer"
SEND_METHODS = frozenset({"send", "send_threadsafe"})
#: The gateway implementation itself forwards a variable, never a literal.
EXCLUDE_NAMES = frozenset({"gateway.py"})


@dataclass(frozen=True)
class Site:
    path: str
    line: int
    key: str | None
    event: str


def _walk_events(node: Any, out: set[str]) -> None:
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "on" and isinstance(v, dict):
                out.update(e for e in v if e != "*" and not e.startswith("xstate."))
            _walk_events(v, out)
    elif isinstance(node, list):
        for v in node:
            _walk_events(v, out)


def load_descriptors(machines: Path = DEFAULT_MACHINES) -> dict[str, set[str]]:
    """``{machine id: declared event names}`` from every committed chart."""
    result: dict[str, set[str]] = {}
    for p in sorted(machines.glob("B*.machine.json")):
        chart = json.loads(p.read_text(encoding="utf-8"))
        events: set[str] = set()
        _walk_events(chart, events)
        result[str(chart.get("id", p.name.split(".")[1]))] = events
    return result


def _str(node: ast.expr | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _event_node(node: ast.expr) -> ast.expr | None:
    """The expression carrying the event name (the value of ``type`` for dicts)."""
    if isinstance(node, ast.Dict):
        for k, v in zip(node.keys, node.values, strict=True):
            if _str(k) == "type":
                return v
        return None
    if isinstance(node, ast.Call):
        fn = node.func
        name = fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", None)
        if name == "Event":
            if node.args:
                return node.args[0]
            for kw in node.keywords:
                if kw.arg == "type":
                    return kw.value
        return None
    return node


def _event_name(node: ast.expr) -> str | None:
    inner = _event_node(node)
    return _str(inner) if inner is not None else None


def _is_gateway_send(call: ast.Call) -> bool:
    return (
        isinstance(call.func, ast.Attribute)
        and call.func.attr in SEND_METHODS
        and len(call.args) >= 2
    )


def _registrations(tree: ast.AST) -> dict[str, str]:
    """``{unparsed key expr: machine kind}`` from ``.register(key, ..., kind=lit)``."""
    out: dict[str, str] = {}
    for n in ast.walk(tree):
        if (
            isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == "register"
            and n.args
        ):
            for kw in n.keywords:
                kind = _str(kw.value) if kw.arg == "kind" else None
                if kind is not None:
                    out[ast.unparse(n.args[0])] = kind
    return out


def _machine_for(key: ast.expr, regs: dict[str, str]) -> str | None:
    """Machine id a send key resolves to: literal ``<id>[:inst]``, a key
    expression registered under ``kind=``, else the file's sole registered kind."""
    lit = _str(key)
    if lit is not None:
        return lit.split(":", 1)[0]
    kind = regs.get(ast.unparse(key))
    if kind is None and len(set(regs.values())) == 1:
        kind = next(iter(regs.values()))
    return kind


def _params(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    names = [a.arg for a in fn.args.posonlyargs + fn.args.args]
    return names[1:] if names and names[0] in ("self", "cls") else names


def module_name(path: Path, root: Path) -> str:
    """Dotted module name of ``path`` with ``root``'s parent on ``sys.path``."""
    parts = list(path.relative_to(root.parent).with_suffix("").parts)
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


#: Reviewed calls on an injected port object that reach a wrapper method:
#: ``{(caller module, receiver source, method): wrapper qualified name}``. A call on any
#: other object (``obj.f(...)``) is never resolved, so an unrelated ``x.record(a, b, "LIT")``
#: is no event site (#4730). An entry whose caller module is scanned must name a found
#: wrapper and its call must still occur in that module, else the scan fails (exit 2), so
#: the list cannot go stale silently.
PORT_WRAPPERS: Mapping[tuple[str, str, str], str] = {
    ("candleviewer.api.sessions", "chart", "record"): (
        "candleviewer.auth.session_chart.SessionChart.record"
    ),
    ("candleviewer.auth.step_up", "self._chart", "record"): (
        "candleviewer.auth.session_chart.SessionChart.record"
    ),
    ("candleviewer.oms.exits", "self._d.machines", "command"): (
        "candleviewer.oms.order_machine.OrderMachines.command"
    ),
    ("candleviewer.oms.positions", "self._orders", "push_protection"): (
        "candleviewer.oms.order_machine.OrderMachines.push_protection"
    ),
    ("candleviewer.oms.reconciler", "self._p.machines", "command"): (
        "candleviewer.oms.order_machine.OrderMachines.command"
    ),
    ("candleviewer.oms.reconciler", "self._p.machines", "push"): (
        "candleviewer.oms.order_machine.OrderMachines.push"
    ),
    ("candleviewer.oms.stream_push", "self._target", "push"): (
        "candleviewer.oms.order_machine.OrderMachines.push"
    ),
    ("candleviewer.oms.submit", "self._machines", "command"): (
        "candleviewer.oms.order_machine.OrderMachines.command"
    ),
}

_Fn = ast.FunctionDef | ast.AsyncFunctionDef


@dataclass
class _Module:
    """One parsed module, the names its imports bind (anywhere in the file,
    ``TYPE_CHECKING`` blocks and function-local imports included), its classes and
    its functions keyed by qualified name (``pkg.mod.func``, ``pkg.mod.Class.meth``)."""

    name: str
    path: str
    tree: ast.AST
    is_package: bool = False

    def __post_init__(self) -> None:
        self.regs = _registrations(self.tree)
        #: local name -> dotted target it is bound to by an import
        self.aliases: dict[str, str] = {}
        pkg = self.name if self.is_package else self.name.rpartition(".")[0]
        for n in ast.walk(self.tree):
            if isinstance(n, ast.Import):
                for a in n.names:
                    if a.asname:
                        self.aliases[a.asname] = a.name
                    else:
                        head = a.name.split(".", 1)[0]
                        self.aliases[head] = head
            elif isinstance(n, ast.ImportFrom):
                base = n.module or ""
                if n.level:
                    parts = pkg.split(".") if pkg else []
                    up = parts[: len(parts) - n.level + 1]
                    base = ".".join([*up, *([n.module] if n.module else [])])
                for a in n.names:
                    self.aliases[a.asname or a.name] = (
                        f"{base}.{a.name}" if base else a.name
                    )
        #: class qualified name -> its base-class expressions
        self.class_bases: dict[str, list[ast.expr]] = {}
        #: (function qualified name, node, enclosing class qualified name or None)
        self.defs: list[tuple[str, _Fn, str | None]] = []
        #: (call, enclosing class qualified name or None) for every call in the file
        self.calls: list[tuple[ast.Call, str | None]] = []
        self._index(self.tree, None, None)

    def _index(self, node: ast.AST, cls: str | None, owner: str | None) -> None:
        """``cls``: the class ``self`` refers to here; ``owner``: the class whose
        body directly holds ``node`` (its functions are that class's methods)."""
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                qual = f"{cls or self.name}.{child.name}"
                self.class_bases[qual] = list(child.bases)
                self._index(child, qual, qual)
                continue
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                self.defs.append((f"{owner or self.name}.{child.name}", child, cls))
            elif isinstance(child, ast.Call):
                self.calls.append((child, cls))
            self._index(child, cls, None)

    def dotted(self, node: ast.expr) -> str | None:
        if isinstance(node, ast.Name):
            if node.id in self.aliases:
                return self.aliases[node.id]
            local = f"{self.name}.{node.id}"
            return local if local in self.class_bases else None
        if isinstance(node, ast.Attribute):
            head = self.dotted(node.value)
            return f"{head}.{node.attr}" if head is not None else None
        return None


@dataclass(frozen=True)
class _Index:
    """Package-wide class hierarchy plus the reviewed injected-port calls."""

    bases: Mapping[str, tuple[str, ...]]
    ports: Mapping[tuple[str, str, str], str]

    @classmethod
    def of(
        cls, mods: list[_Module], ports: Mapping[tuple[str, str, str], str]
    ) -> _Index:
        bases: dict[str, tuple[str, ...]] = {}
        for m in mods:
            for qual, exprs in m.class_bases.items():
                bases[qual] = tuple(b for b in map(m.dotted, exprs) if b is not None)
        return cls(bases, ports)

    def mro(self, qual: str) -> list[str]:
        out: list[str] = []
        todo = [qual]
        while todo:
            q = todo.pop(0)
            if q not in out:
                out.append(q)
                todo.extend(self.bases.get(q, ()))
        return out

    def candidates(self, mod: _Module, call: ast.Call, cls: str | None) -> list[str]:
        """Qualified names the callee resolves to; every rule is exact.

        A bare ``f(...)`` is the import that binds ``f``, else this module's own
        ``f``; ``mod.f(...)`` / ``Class.f(...)`` resolve through the imports and
        local classes; ``self.f(...)`` is ``f`` on the enclosing class or a base
        class. Any other ``obj.f(...)`` resolves only through ``PORT_WRAPPERS``.
        """
        fn = call.func
        if isinstance(fn, ast.Name):
            return [mod.aliases.get(fn.id, f"{mod.name}.{fn.id}")]
        if not isinstance(fn, ast.Attribute):
            return []
        target = mod.dotted(fn.value)
        if target is not None:
            return [f"{target}.{fn.attr}"]
        if isinstance(fn.value, ast.Name) and fn.value.id in ("self", "cls"):
            return [f"{c}.{fn.attr}" for c in self.mro(cls)] if cls else []
        port = self.ports.get((mod.name, ast.unparse(fn.value), fn.attr))
        return [port] if port is not None else []


_Found = dict[str, tuple[int, str | None]]


def _lookup(
    mod: _Module, call: ast.Call, cls: str | None, found: _Found, idx: _Index
) -> tuple[int, str | None] | None:
    for qual in idx.candidates(mod, call, cls):
        hit = found.get(qual)
        if hit is not None and len(call.args) > hit[0]:
            return hit
    return None


def _wrappers(mods: list[_Module], idx: _Index) -> _Found:
    """Functions forwarding a *parameter* as the event of a gateway send (directly
    or via another wrapper), keyed by qualified name (``pkg.mod.func`` or
    ``pkg.mod.Class.meth``): ``{qualified name: (call-arg index of the event,
    machine)}``. A wrapper is only ever matched through its defining module or
    class, so an unrelated function that shares its bare name (a private
    ``_record`` elsewhere) is never one (#4730)."""
    found: _Found = {}
    changed = True
    while changed:
        changed = False
        for mod in mods:
            for qual, fn, cls in mod.defs:
                if qual in found:
                    continue
                params = _params(fn)
                for c in ast.walk(fn):
                    if not isinstance(c, ast.Call):
                        continue
                    if _is_gateway_send(c):
                        ev = _event_node(c.args[1])
                        machine = _machine_for(c.args[0], mod.regs)
                    else:
                        hit = _lookup(mod, c, cls, found, idx)
                        if hit is None:
                            continue
                        ev, machine = c.args[hit[0]], hit[1]
                    if isinstance(ev, ast.Name) and ev.id in params:
                        found[qual] = (params.index(ev.id), machine)
                        changed = True
                        break
    return found


def _sites(mod: _Module, wrappers: _Found, idx: _Index) -> list[Site]:
    sites: list[Site] = []
    for node, cls in mod.calls:
        if _is_gateway_send(node):
            event = _event_name(node.args[1])
            if event is not None:
                sites.append(
                    Site(
                        mod.path,
                        node.lineno,
                        _machine_for(node.args[0], mod.regs),
                        event,
                    )
                )
            continue
        hit = _lookup(mod, node, cls, wrappers, idx)
        if hit is not None:
            i, machine = hit
            event = _str(node.args[i])
            if event is not None:
                sites.append(Site(mod.path, node.lineno, machine, event))
    return sites


class StalePortError(ValueError):
    """A ``PORT_WRAPPERS`` entry for a scanned module names no wrapper or matches no call."""


def _scan(mods: list[_Module], ports: Mapping[tuple[str, str, str], str]) -> list[Site]:
    idx = _Index.of(mods, ports)
    wrappers = _wrappers(mods, idx)
    scanned = {m.name for m in mods}
    stale = sorted(
        f"{k[0]}: {k[1]}.{k[2]} -> {v}"
        for k, v in ports.items()
        if k[0] in scanned and v not in wrappers
    )
    if stale:
        raise StalePortError(f"PORT_WRAPPERS entries name no wrapper: {stale}")
    seen = {
        (m.name, ast.unparse(c.func.value), c.func.attr)
        for m in mods
        for c, _ in m.calls
        if isinstance(c.func, ast.Attribute)
    }
    unmatched = sorted(
        f"{k[0]}: {k[1]}.{k[2]} -> {v}"
        for k, v in ports.items()
        if k[0] in scanned and k not in seen
    )
    if unmatched:
        raise StalePortError(f"PORT_WRAPPERS entries match no call: {unmatched}")
    return [s for mod in mods for s in _sites(mod, wrappers, idx)]


def scan_source(
    source: str, path: str, *, ports: Mapping[tuple[str, str, str], str] = PORT_WRAPPERS
) -> list[Site]:
    mod = _Module(
        Path(path).with_suffix("").as_posix().replace("/", "."),
        path,
        ast.parse(source, filename=path),
    )
    return _scan([mod], ports)


def scan_tree(
    root: Path = DEFAULT_SCAN,
    *,
    ports: Mapping[tuple[str, str, str], str] = PORT_WRAPPERS,
) -> list[Site]:
    mods: list[_Module] = []
    for p in sorted(root.rglob("*.py")):
        if p.name in EXCLUDE_NAMES or "__pycache__" in p.parts:
            continue
        mods.append(
            _Module(
                module_name(p, root),
                p.as_posix(),
                ast.parse(p.read_text(encoding="utf-8"), filename=p.as_posix()),
                is_package=p.name == "__init__.py",
            )
        )
    return _scan(mods, ports)


def check(sites: list[Site], descriptors: dict[str, set[str]]) -> list[str]:
    union = set().union(*descriptors.values()) if descriptors else set()
    findings: list[str] = []
    for s in sites:
        where = f"{s.path}:{s.line}"
        if s.key is None:
            if s.event not in union:
                findings.append(f"{where}: event '{s.event}' is declared by no machine")
            continue
        machine = s.key
        events = descriptors.get(machine)
        if events is None:
            findings.append(f"{where}: unknown machine '{machine}' (event '{s.event}')")
        elif s.event not in events:
            findings.append(
                f"{where}: event '{s.event}' is not declared by machine '{machine}'"
            )
    return findings


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--machines", type=Path, default=DEFAULT_MACHINES)
    ap.add_argument("--scan", type=Path, default=DEFAULT_SCAN)
    args = ap.parse_args(argv)
    if not args.machines.is_dir() or not args.scan.is_dir():
        print("event-coverage: machines/scan directory missing", file=sys.stderr)
        return 2
    descriptors = load_descriptors(args.machines)
    try:
        sites = scan_tree(args.scan)
    except StalePortError as exc:
        print(f"event-coverage: {exc}", file=sys.stderr)
        return 2
    findings = check(sites, descriptors)
    for f in findings:
        print(f"event-coverage: {f}")
    print(
        f"event-coverage: {len(sites)} call site(s), {len(descriptors)} machine(s), "
        f"{len(findings)} finding(s)"
    )
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
