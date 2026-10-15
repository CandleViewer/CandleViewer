"""#2555 guards for the API image's boot path.

`infra/images/Dockerfile.api` installs the package at `/app/candleviewer/` with no repository
around it:

- A module there has only as many parents as its depth. An import-time `….parents[N]` that
  climbs past the filesystem root raises `IndexError`, and an import-time `.parent` chain that
  does so silently names `/`. Either is a repository lookup that cannot work in the image.
- The dev-only contract helpers (`OPENAPI_SPEC_PATH`, `load_openapi_spec` and the
  `rbac_conformance` module) read the checkout's YAML, so no runtime module may import them.
- `contract_conformance` must load with the stdlib alone: the generator loads it by file path,
  and the boot path must need neither PyYAML nor openapi-spec-validator (#2616).
"""

from __future__ import annotations

import ast
import subprocess
import sys
import warnings
from collections.abc import Sequence
from pathlib import Path, PurePosixPath

import pytest

import candleviewer

PACKAGE = Path(candleviewer.__file__).resolve().parent
#: Where `infra/images/Dockerfile.api` installs the package (`WORKDIR /app`).
IMAGE_PACKAGE = PurePosixPath("/app/candleviewer")
CONTRACT_CONFORMANCE = "candleviewer.api.contract_conformance"
RBAC_CONFORMANCE = "candleviewer.api.rbac_conformance"
DEV_ONLY_NAMES = frozenset({"OPENAPI_SPEC_PATH", "load_openapi_spec"})
#: The only modules that may name the dev-only helpers: the one defining them, and the
#: dev-only module built on them.
MAY_USE_DEV_ONLY = frozenset({CONTRACT_CONFORMANCE, RBAC_CONFORMANCE})


class _Module:
    def __init__(self, path: Path) -> None:
        relative = path.relative_to(PACKAGE)
        parts = ["candleviewer", *relative.with_suffix("").parts]
        self.is_package = parts[-1] == "__init__"
        self.name = ".".join(parts[:-1] if self.is_package else parts)
        self.relative = relative
        #: Parents the module has once installed in the image.
        self.image_depth = len((IMAGE_PACKAGE / relative.as_posix()).parents)
        with warnings.catch_warnings():  # an applied migration has an invalid escape (C-5.4)
            warnings.simplefilter("ignore", SyntaxWarning)
            self.tree = ast.parse(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def modules() -> list[_Module]:
    return [_Module(path) for path in sorted(PACKAGE.rglob("*.py"))]


def _levels_up(node: ast.expr) -> int:
    """Directories the path expression `node` climbs: `.parent` climbs one, `.parents[N]`
    climbs N + 1, and `.resolve()` / `.absolute()` climb none."""
    levels = 0
    while True:
        if isinstance(node, ast.Attribute) and node.attr == "parent":
            levels, node = levels + 1, node.value
        elif (
            isinstance(node, ast.Subscript)
            and isinstance(node.value, ast.Attribute)
            and node.value.attr == "parents"
            and isinstance(node.slice, ast.Constant)
            and isinstance(node.slice.value, int)
            and node.slice.value >= 0
        ):
            levels, node = levels + node.slice.value + 1, node.value.value
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in ("resolve", "absolute")
        ):
            node = node.func.value
        else:
            return levels


class _ImportTimeClimbs(ast.NodeVisitor):
    """Lines whose import-time path expressions climb past `/` from a module `depth` parents
    deep. Function and lambda bodies run on call; their decorators and default arguments run
    at import, so only those parts are visited."""

    def __init__(self, depth: int) -> None:
        self.depth = depth
        self.lines: set[int] = set()

    def _climb(self, node: ast.Attribute | ast.Subscript) -> None:
        if _levels_up(node) > self.depth:
            self.lines.add(node.lineno)
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        self._climb(node)

    def visit_Subscript(self, node: ast.Subscript) -> None:
        self._climb(node)

    def _import_time_parts(self, decorators: Sequence[ast.expr], args: ast.arguments) -> None:
        for expr in [*decorators, *args.defaults, *args.kw_defaults]:
            if expr is not None:
                self.visit(expr)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._import_time_parts(node.decorator_list, node.args)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._import_time_parts(node.decorator_list, node.args)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        self._import_time_parts([], node.args)


def _climbs(tree: ast.AST, depth: int) -> list[int]:
    visitor = _ImportTimeClimbs(depth)
    visitor.visit(tree)
    return sorted(visitor.lines)


@pytest.mark.parametrize(
    "source",
    [
        "R = Path(__file__).resolve().parents[4]",
        "R = Path(__file__).parent.parent.parent.parent.parent",
        "R = Path(__file__).resolve().parent.parents[3]",
        "@register(Path(__file__).parents[4])\ndef f(): ...",
        "def f(p=Path(__file__).parents[4]): ...",
        "def f(*, p=Path(__file__).parent.parent.parent.parent.parent): ...",
        "async def f(p=Path(__file__).parents[4]): ...",
        "g = lambda p=Path(__file__).parents[4]: p",
        "class C:\n    root = Path(__file__).parents[4]",
    ],
)
def test_an_import_time_climb_past_the_root_is_found(source: str) -> None:
    assert _climbs(ast.parse(source), depth=4) != []


@pytest.mark.parametrize(
    "source",
    [
        "def f():\n    return Path(__file__).parents[4]",
        "g = lambda: Path(__file__).parent.parent.parent.parent.parent",
        "R = Path(__file__).resolve().parents[3]",
        "R = Path(__file__).parent.parent.parent.parent",
        "R = Path(__file__).parents[-1]",
    ],
)
def test_a_climb_that_runs_on_call_or_stays_within_the_root_is_allowed(source: str) -> None:
    assert _climbs(ast.parse(source), depth=4) == []


def test_no_module_climbs_past_the_image_root_at_import(modules: list[_Module]) -> None:
    """`main` had two: `api/contract_conformance.py:27` and `ingestion/synthetic_feed.py:57`."""
    offenders = [
        f"{module.relative}:{line}"
        for module in modules
        for line in _climbs(module.tree, module.image_depth)
    ]
    assert offenders == []


def _dev_only_uses(name: str, is_package: bool, tree: ast.AST) -> list[str]:
    """Imports of `rbac_conformance`, or of the dev-only names, and attribute uses of them."""
    base = name if is_package else name.rpartition(".")[0]
    uses: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(alias.name == RBAC_CONFORMANCE for alias in node.names):
                uses.append(f"{node.lineno}: import {RBAC_CONFORMANCE}")
        elif isinstance(node, ast.ImportFrom):
            source = node.module or ""
            if node.level:
                anchor = base.rsplit(".", node.level - 1)[0]
                source = f"{anchor}.{source}" if source else anchor
            names = {alias.name for alias in node.names}
            if (
                source == RBAC_CONFORMANCE
                or (source == "candleviewer.api" and "rbac_conformance" in names)
                or (source == CONTRACT_CONFORMANCE and names & (DEV_ONLY_NAMES | {"*"}))
            ):
                uses.append(f"{node.lineno}: from {source} import {', '.join(sorted(names))}")
        elif isinstance(node, ast.Attribute) and node.attr in DEV_ONLY_NAMES:
            uses.append(f"{node.lineno}: .{node.attr}")
    return uses


@pytest.mark.parametrize(
    "source",
    [
        "import candleviewer.api.rbac_conformance",
        "from candleviewer.api.rbac_conformance import assert_vocabulary_single_source",
        "from candleviewer.api import rbac_conformance",
        "from . import rbac_conformance",
        "from .rbac_conformance import find_undeclared_routes",
        "from candleviewer.api.contract_conformance import load_openapi_spec",
        "from candleviewer.api.contract_conformance import OPENAPI_SPEC_PATH",
        "from .contract_conformance import *",
        "from candleviewer.api import contract_conformance as cc\ncc.load_openapi_spec()",
    ],
)
def test_a_dev_only_import_is_found(source: str) -> None:
    assert _dev_only_uses("candleviewer.api.some_router", False, ast.parse(source)) != []


def test_the_runtime_names_of_contract_conformance_are_allowed() -> None:
    source = (
        "from candleviewer.api.contract_conformance import NON_CONTRACT_ROUTES, "
        "load_contract_subset"
    )
    assert _dev_only_uses("candleviewer.app", False, ast.parse(source)) == []


def test_no_runtime_module_imports_the_dev_only_contract_helpers(modules: list[_Module]) -> None:
    offenders = [
        f"{module.relative}:{use}"
        for module in modules
        if module.name not in MAY_USE_DEV_ONLY
        for use in _dev_only_uses(module.name, module.is_package, module.tree)
    ]
    assert offenders == []


def test_contract_conformance_loads_with_the_stdlib_alone() -> None:
    """As the generator loads it, by file path in a fresh isolated interpreter: no package
    `__init__` runs, and nothing outside the stdlib (PyYAML, openapi-spec-validator) loads."""
    probe = (
        "import importlib.util, sys; before = set(sys.modules); "
        "spec = importlib.util.spec_from_file_location('probe', sys.argv[1]); "
        "spec.loader.exec_module(importlib.util.module_from_spec(spec)); "
        "loaded = {name.partition('.')[0] for name in set(sys.modules) - before}; "
        "print(sorted(loaded - set(sys.stdlib_module_names)))"
    )
    module = PACKAGE / "api" / "contract_conformance.py"
    result = subprocess.run(  # noqa: S603 — fixed argv: this interpreter, isolated (#2555)
        [sys.executable, "-I", "-c", probe, str(module)],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr[-4000:]
    assert result.stdout.strip() == "[]"
