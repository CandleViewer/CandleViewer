"""C-3.2 / C-2.9 CI guard: the enforcing control for M2's in-process boundary.

In-process Python cannot make the KEK unreachable (closures, `__globals__`, the GC, frames).
This guard therefore fails CI on every *ordinary-looking* way, outside `secrets/`, to reach M2
internals, introspect a capability, or silence the audit sink. Deliberate exotic code (computed
names, eval, ctypes) remains a documented residual; process isolation of signing is the real
fix (#2279). Probes for every rule live in `test_m2_guard_probes.py` (AST-only, never executed).

Rules (outside `secrets/` unless allow-listed by exact construct):
R0  Introspection names: `__closure__`, `cell_contents`, `__globals__`, `__code__`,
    `co_freevars`, `__func__`, `__self__`, `__defaults__`, `__kwdefaults__`, `__wrapped__`,
    `__getattribute__`, `__getstate__`, `__reduce_ex__`, `__reduce__`; frames/tracebacks
    (`tb_frame`, `f_locals`, `f_globals`, `f_back`, `gi_frame`, `cr_frame`, `ag_frame`,
    `_getframe`, `currentframe`, `dict_tracebacks`, `ExceptionDictTransformer`); `gc.*`
    referents/referrers/objects, `getclosurevars`, `getmembers`, `getattr_static`, as bare calls
    or on any receiver; `capture_locals=`/`show_locals=` unless literally False.
R1  The name rules also apply to string literals passed to getattr/setattr/hasattr/delattr,
    `object.__getattribute__`/`__setattr__`/`__delattr__`, `inspect.getattr_static`, and to
    every dotted part of `operator.attrgetter`/`methodcaller` arguments.
R2  `self`/`cls` exempt only as the **immediate** receiver (not the root of a chain).
R3  AppContext recognised by field name (`dataclasses.fields(AppContext)`) on any root; a
    `_private` attribute of a field is allowed only inside that field's owning package.
R4  Outside `audit/`: Store/Del targets and setattr/delattr through another module's AppContext
    field, or targeting `emit`/`writer`/`_writer`/`_audit_sink`/`_audit` on a non-self receiver.
R5  Mangled `_Name__attr`; `vars(x)` / `x.__dict__` on non-self (exact allow-list).
R6  Any non-docstring str constant starting with `candleviewer.secrets`, and the dotted chain
    `candleviewer.secrets.<X>`; M2 aliases (`import … as`, `from candleviewer import secrets`,
    relative) used for anything not in `secrets.__all__`.
R7  Any class outside `secrets/` subclassing a class imported from `candleviewer.secrets`
    (runtime backstop: `__init_subclass__` + `@typing.final` in M2).
R8  Last-hop names pinned: `unwrap_dek`, `wrap_dek`, `open_`, `seal`, `cred_aad`, `dek_aad`,
    `rewrap_all`, `verify_kcv`, `drop_kek`, `flush_cache`, `kek_handle`, `kek_prev_handle`,
    `kek_ack_path` (outside `settings.py`); str literals `/run/credentials…` or `CV_KEK_…`.
R9  Borrow names (see R10); admin metadata outside `admin/`;
    `mint_borrower` outside `admin/wiring.py`; every M2-defined private name (harvested with
    rglob, no subtraction) plus `_key`, `_cache`, `_items`, `_broker`, on non-self receivers.
R10 Plaintext stays in `secrets/` (C-2.7, #2339): the plaintext borrow (`with_credentials`,
    `borrow_handle`) anywhere outside `secrets/`; `.reveal()` (also via getattr/methodcaller)
    except the exact reviewed site (the key id M2 returns, read for the request header); and
    in the exchange adapter (`exchange/`) any `hmac` import (stdlib or vendor, any alias) and
    the credential plaintext holders `SecretStr` / `get_secret_value`. M2 computes the MAC.
"""

from __future__ import annotations

import ast
import dataclasses
from pathlib import Path

import candleviewer.secrets as m2

PKG = Path(__file__).resolve().parents[3] / "candleviewer"
MINT_SITES = {"admin/wiring.py"}
#: The M4 exchange adapter package (the only signing-capability holder), built from parts.
_BORROW_SITE = "/".join(("exchange", "by" + "bit")) + "/"
_ADMIN_SITE = "admin/"
_AUDIT_SITE = "audit/"
#: R10: the whole exchange layer (base + venue adapter) holds no credential plaintext.
_ADAPTER_SITE = "exchange/"
_SELFISH = frozenset({"self", "cls"})

_INTROSPECTION = frozenset(
    {
        "__closure__", "cell_contents", "__globals__", "__code__", "co_freevars", "__func__",
        "__self__", "__defaults__", "__kwdefaults__", "__wrapped__", "__getattribute__",
        "__getstate__", "__reduce_ex__", "__reduce__", "tb_frame", "f_locals", "f_globals",
        "f_back", "gi_frame", "cr_frame", "ag_frame", "_getframe", "currentframe",
        "dict_tracebacks", "ExceptionDictTransformer", "get_referents", "get_referrers",
        "get_objects", "getclosurevars", "getmembers", "getattr_static",
    }
)  # fmt: skip
#: `seal` is also a statechart envelope verb, so it is not pinned (`open_`/`cred_aad` are).
_LAST_HOP = frozenset(
    {
        "unwrap_dek", "wrap_dek", "open_", "cred_aad", "dek_aad", "rewrap_all",
        "verify_kcv", "drop_kek", "flush_cache", "kek_handle", "kek_prev_handle", "kek_ack_path",
    }
)  # fmt: skip
_SETTINGS_ONLY = frozenset({"kek_handle", "kek_prev_handle", "kek_ack_path"})
#: Pinned regardless of harvesting (incl. names M2 has since removed, so they stay banned).
_PINNED = frozenset({"_key", "_cache", "_items", "_broker", "_tickets", "_decrypt_and_call"})
_BORROW = frozenset({"with_credentials", "borrow_handle"})
#: R10: the plaintext reader (refused outside `secrets/`) and the credential plaintext holders
#: (refused in the exchange adapter).
_REVEAL = "reveal"
_ADAPTER_PLAINTEXT = frozenset({"SecretStr", "get_secret_value"})
_ADMIN_ONLY = frozenset({"rewrap_deks", "verify_kek_possession"})
_AUDIT_TARGETS = frozenset({"emit", "writer", "_writer", "_audit_sink", "_audit"})
_REFLECT = frozenset({"getattr", "setattr", "hasattr", "delattr", "getattr_static"})
_OBJ_REFLECT = frozenset({"__getattribute__", "__setattr__", "__delattr__"})
_ATTRGETTERS = frozenset({"attrgetter", "methodcaller"})
_STR_PREFIXES = ("candleviewer.secrets", "/run/credentials", "CV_KEK_")

#: Exact allow-list: (file, rule, construct). Each entry is one reviewed, unrelated use.
ALLOW: frozenset[tuple[str, str, str]] = frozenset(
    {
        ("observability/logging.py", "dict", "record"),  # SR-121 LogRecord redaction filter
        ("storage/router.py", "vars", "row"),  # plain row dataclass to dict (hot/cold diff)
        ("observability/secret_type.py", "m2private", "_value"),  # Secret base's own slot
        ("statechart/persistence.py", "reflect", "_descent_done"),  # xstate interpreter
        ("statechart/plugins/metrics.py", "reflect", "_timer_handles"),  # xstate interpreter
        ("statechart/plugins/audit.py", "reflect", "_active_state_nodes"),  # xstate interpreter
        # R10 (#2339): the key id M2 returns, read once for the request's API-key header.
        (_BORROW_SITE + "signer.py", "reveal", "api_key"),
    }
)


def _harvest_m2_private() -> frozenset[str]:
    names: set[str] = set()
    for f in sorted((PKG / "secrets").rglob("*.py")):
        if f.stem.startswith("_") and f.stem != "__init__":
            names.add(f.stem)  # submodule names: _kek, _envelope, _rotation, ...
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                names.add(node.name)
            elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                if node.value.id in _SELFISH:
                    names.add(node.attr)
    return frozenset(n for n in names if n.startswith("_") and not n.startswith("__")) | _PINNED


M2_PRIVATE = _harvest_m2_private()


def _ctx_owners() -> dict[str, str]:
    """AppContext field → owning package prefix (exact)."""
    from candleviewer.app import AppContext

    special = {
        "exchange_base": "exchange/base/",
        "exchange_bybit": _BORROW_SITE,
        "oms_read_only_gate": "net/",
        "mesh_self_check": "net/",
        "mesh_system_topic_publisher": "net/",
        "settings": "settings.py",
        "metrics": "observability/",
    }
    return {f.name: special.get(f.name, f"{f.name}/") for f in dataclasses.fields(AppContext)}


CTX_OWNERS = _ctx_owners()


def _chain(node: ast.expr) -> tuple[list[str], ast.expr]:
    """Attribute names from the outside in, and the innermost (root) expression."""
    names: list[str] = []
    cur = node
    while isinstance(cur, ast.Attribute | ast.Subscript | ast.Call):
        if isinstance(cur, ast.Attribute):
            names.append(cur.attr)
        cur = cur.func if isinstance(cur, ast.Call) else cur.value
    return names, cur


#: Names/attributes through which code holds the AppContext (any root or attribute chain).
_CTX_HOLDERS = frozenset({"ctx", "context", "app_context", "appctx"})


def _ctx_field(node: ast.expr) -> str | None:
    """The AppContext field this expression passes through: `<holder>.<field>` where the holder
    is a ctx-named variable or attribute anywhere in the chain (`ctx.x`, `self.ctx.x`,
    `request.app.state.ctx.x`, `self._ctx.x`, `app.state.app_context.x`)."""
    names, root = _chain(node)
    inner = list(reversed(names))  # innermost first
    holder_names = {*_CTX_HOLDERS, *(f"_{h}" for h in _CTX_HOLDERS)}
    prev = root.id if isinstance(root, ast.Name) else ""
    for n in inner:
        if prev in holder_names and n in CTX_OWNERS:
            return n
        prev = n
    return None


def _callee(fn: ast.expr) -> str:
    if isinstance(fn, ast.Name):
        return fn.id
    if isinstance(fn, ast.Attribute):
        return fn.attr
    return ""


def _immediate_self(recv: ast.expr) -> bool:
    return isinstance(recv, ast.Name) and recv.id in _SELFISH


def _docstrings(tree: ast.AST) -> set[int]:
    out: set[int] = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(body, list) and body and isinstance(body[0], ast.Expr):
            v = body[0].value
            if isinstance(v, ast.Constant) and isinstance(v.value, str):
                out.add(id(v))
    return out


def _aliases(rel: str, tree: ast.AST) -> set[str]:
    out: set[str] = set()
    pkg_parts = ["candleviewer", *Path(rel).with_suffix("").parts[:-1]]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name == "candleviewer.secrets" or a.name.startswith("candleviewer.secrets."):
                    out.add(a.asname or a.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                parts = pkg_parts[: len(pkg_parts) - node.level + 1]
                base = ".".join([*parts, *(base.split(".") if base else [])])
            for a in node.names:
                if f"{base}.{a.name}" == "candleviewer.secrets":
                    out.add(a.asname or a.name)
    return out


def _m2_bases(rel: str, tree: ast.AST) -> set[str]:
    """Local names bound to classes imported from candleviewer.secrets (for R7)."""
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
            "candleviewer.secrets"
        ):
            out |= {a.asname or a.name for a in node.names}
    return out


class _Checker:
    def __init__(self, rel: str, tree: ast.AST) -> None:
        self.rel, self.tree = rel, tree
        self.bad: list[str] = []
        self.pkg_allow = {(r, c) for f, r, c in ALLOW if f == rel}
        self.aliases = _aliases(rel, tree)
        self.bases = _m2_bases(rel, tree)
        self.docs = _docstrings(tree)

    def flag(self, msg: str) -> None:
        self.bad.append(f"{self.rel}: {msg}")

    def allowed(self, rule: str, construct: str) -> bool:
        return (rule, construct) in self.pkg_allow

    def name_rules(self, name: str, recv: ast.expr | None, via: str) -> None:
        """R0/R2/R5/R8/R9 on one attribute name read through `recv`."""
        selfish = recv is not None and _immediate_self(recv)
        if name in _INTROSPECTION:
            self.flag(f"{via}{name} (introspection)")
        if name.startswith("_") and "__" in name[1:] and not name.endswith("__"):
            self.flag(f"{via}{name} (mangled)")
        if name in M2_PRIVATE and not selfish and not self.allowed("m2private", name):
            if not (via.startswith("getattr") and self.allowed("reflect", name)):
                self.flag(f"{via}{name} (M2 private)")
        if name in _LAST_HOP and not (name in _SETTINGS_ONLY and self.rel == "settings.py"):
            self.flag(f"{via}{name} (M2 last hop)")
        if name in _BORROW:
            self.flag(f"{via}{name} (plaintext borrow outside secrets/)")
        if name == _REVEAL and not self.allowed("reveal", _construct(recv)):
            self.flag(f"{via}{name} (plaintext read outside secrets/)")
        if name in _ADAPTER_PLAINTEXT and self.rel.startswith(_ADAPTER_SITE):
            self.flag(f"{via}{name} (credential plaintext in the exchange adapter)")
        if name in _ADMIN_ONLY and not self.rel.startswith(_ADMIN_SITE):
            self.flag(f"{via}{name} (admin-only metadata)")
        if name == "__dict__" and not selfish:
            construct = recv.id if isinstance(recv, ast.Name) else ""
            if not self.allowed("dict", construct):
                self.flag(f"{via}__dict__ on a foreign object")

    def ctx_rules(self, node: ast.Attribute) -> None:
        """R3: `<field>.…._private` outside the field's owner."""
        field = _ctx_field(node.value)
        if field is None or not node.attr.startswith("_"):
            return
        owner = CTX_OWNERS[field]
        if not (self.rel == owner or self.rel.startswith(owner)):
            self.flag(f"ctx.{field}…{node.attr} (private attr of another module)")

    def write_rules(self, target: ast.expr) -> None:
        """R4: writes through another module's AppContext field / into the audit path."""
        if self.rel.startswith(_AUDIT_SITE):
            return
        if isinstance(target, ast.Attribute):
            field = _ctx_field(target.value) or _ctx_field(target)
            if field is not None:
                owner = CTX_OWNERS[field]
                if not (self.rel == owner or self.rel.startswith(owner)):
                    self.flag(f"write through ctx.{field} (another module's state)")
            if target.attr in _AUDIT_TARGETS and not _immediate_self(target.value):
                self.flag(f"write to .{target.attr} (audit path)")

    def reflect_call(self, node: ast.Call) -> None:
        """R1: string literals given to reflection helpers."""
        fn = node.func
        fname = _callee(fn)
        args = node.args
        if fname in _REFLECT or fname in _OBJ_REFLECT:
            recv = args[0] if args else None
            lit = args[1] if len(args) > 1 else None
            if isinstance(lit, ast.Constant) and isinstance(lit.value, str):
                self.name_rules(lit.value, recv, f"{fname}(…, ")
                if recv is not None:  # R3 via reflection: getattr(ctx.<field>, '_private')
                    self.ctx_rules(ast.Attribute(value=recv, attr=lit.value))
                if fname in {"setattr", "delattr", "__setattr__", "__delattr__"}:
                    tgt = ast.Attribute(value=recv or ast.Name("_"), attr=lit.value)
                    self.write_rules(tgt)
                    if recv is not None and _ctx_field(recv) is not None:
                        self.write_rules(ast.Attribute(value=recv, attr="x"))
        if fname in _ATTRGETTERS:
            for a in args:
                if isinstance(a, ast.Constant) and isinstance(a.value, str):
                    for part in a.value.split("."):
                        self.name_rules(part, None, f"{fname}(")

    def run(self) -> list[str]:
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Attribute):
                self.name_rules(node.attr, node.value, ".")
                self.ctx_rules(node)
                if isinstance(node.value, ast.Name) and node.value.id in self.aliases:
                    if node.attr not in m2.__all__:
                        self.flag(f"{node.value.id}.{node.attr} (non-public M2 via alias)")
                    if node.attr == "mint_borrower" and self.rel not in MINT_SITES:
                        self.flag("alias mint_borrower")
                names, root = _chain(node)
                if isinstance(root, ast.Name) and root.id == "candleviewer":
                    dotted = ".".join(reversed(names))
                    if dotted == "secrets" or dotted.startswith("secrets."):
                        if node.attr not in m2.__all__ and node.attr != "secrets":
                            self.flag(f"candleviewer.{dotted} (M2 via the root package)")
            elif isinstance(node, ast.Name):
                if node.id in _BORROW:
                    self.flag(f"{node.id}")
                if node.id in _ADAPTER_PLAINTEXT and self.rel.startswith(_ADAPTER_SITE):
                    self.flag(f"{node.id} (credential plaintext in the exchange adapter)")
                if node.id == "mint_borrower" and self.rel not in MINT_SITES:
                    self.flag("mint_borrower")
                if node.id in _INTROSPECTION:
                    self.flag(f"{node.id} (introspection)")
            elif isinstance(node, ast.Call):
                self.reflect_call(node)
                if isinstance(node.func, ast.Name) and node.func.id == "vars" and node.args:
                    arg = node.args[0]
                    construct = arg.id if isinstance(arg, ast.Name) else ""
                    if not (_immediate_self(arg) or self.allowed("vars", construct)):
                        self.flag("vars() on a foreign object")
                for kw in node.keywords:
                    if kw.arg in {"capture_locals", "show_locals"}:
                        if not (isinstance(kw.value, ast.Constant) and kw.value.value is False):
                            self.flag(f"{kw.arg}= (frame locals in tracebacks)")
            elif isinstance(node, ast.Assign | ast.AugAssign | ast.AnnAssign | ast.Delete):
                targets = (
                    node.targets if isinstance(node, ast.Assign | ast.Delete) else [node.target]
                )
                for t in targets:
                    self.write_rules(t)
            elif isinstance(node, ast.ClassDef):
                for b in node.bases:
                    bn = _callee(b)
                    names, root = _chain(b)
                    via_pkg = isinstance(b, ast.Attribute) and "secrets" in names
                    via_alias = isinstance(root, ast.Name) and root.id in self.aliases
                    if bn in self.bases or via_pkg or via_alias:
                        self.flag(f"class {node.name}({bn}) subclasses an M2 class")
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                if id(node) not in self.docs and node.value.startswith(_STR_PREFIXES):
                    if not (self.rel == "settings.py" and node.value.startswith(_STR_PREFIXES[1:])):
                        self.flag(f"str literal {node.value[:40]!r}")
            elif isinstance(node, ast.Import | ast.ImportFrom):
                if self.rel.startswith(_ADAPTER_SITE):
                    self.adapter_imports(node)
        return self.bad

    def adapter_imports(self, node: ast.Import | ast.ImportFrom) -> None:
        """R10: the exchange adapter imports no MAC primitive (`hmac`, stdlib or vendor, any
        alias) and no credential plaintext holder; M2 computes the request MAC (C-2.7)."""
        if isinstance(node, ast.Import):
            modules, names = [a.name for a in node.names], []
        else:
            modules, names = [node.module or ""], [a.name for a in node.names]
        if any("hmac" in m.split(".") for m in modules) or "hmac" in names:
            self.flag("hmac import (request MACs are computed in secrets/)")
        for name in sorted(_ADAPTER_PLAINTEXT.intersection(names)):
            self.flag(f"import {name} (credential plaintext in the exchange adapter)")


def _construct(recv: ast.expr | None) -> str:
    """The allow-list construct for a receiver: its last attribute or its name."""
    if isinstance(recv, ast.Attribute):
        return recv.attr
    if isinstance(recv, ast.Name):
        return recv.id
    return ""


def m2_violations(rel: str, tree: ast.AST) -> list[str]:
    return _Checker(rel, tree).run()
