"""The OMS's boundary to the exchange (E29-T04 #913; C-2.2), and its one hand-over binding.

C-2.2: all exchange-specific knowledge stays in the adapter package, `candleviewer.exchange.bybit`.
The OMS reaches the exchange only through `exchange.base`'s ports, a trading port per environment
that the composition root wires into `oms.routing.TradingRouter` (C-2.11). So no module under
`candleviewer/oms/` imports the adapter package: not by an import statement (absolute, relative
past `oms`, or under `TYPE_CHECKING`) and not by an import string (`importlib.import_module`, an
entry point). The generated `.importlinter` holds the run-time statements too
(`forbidden-adapter-isolation`, from `docs/plan/module-contracts.toml`), and Semgrep's
`cv-adapter-isolation` the word itself; this walk also sees what import-linter is configured to
skip (`exclude_type_checking_imports`) and the strings.

Limits: an AST check, so a name built at run time (`"exchange." + name`) is not caught.
"""

from __future__ import annotations

import ast
import configparser
import warnings
from collections.abc import Iterator
from pathlib import Path

import pytest

import candleviewer

PACKAGE = Path(candleviewer.__file__).resolve().parent
OMS = PACKAGE / "oms"
#: The adapter package, which only `exchange.base`'s ports stand in for (C-2.2).
ADAPTER = "candleviewer.exchange.bybit"


def _package_of(path: Path) -> list[str]:
    """The dotted package a module at `path` (under `candleviewer/`) belongs to, as parts: its
    directory, for a package's `__init__.py` too."""
    return ["candleviewer", *path.relative_to(PACKAGE).with_suffix("").parts][:-1]


def _imported(tree: ast.AST, package: list[str]) -> Iterator[tuple[int, str]]:
    """(line, dotted name) for each import statement, `TYPE_CHECKING` ones included: a relative
    one resolved against `package`, and each name a `from` import takes, as it may be a module."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, alias.name
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # `.` is the package itself, each further dot one package up
                base = package[: len(package) - node.level + 1]
                module = ".".join([*base, *([node.module] if node.module else [])])
            else:
                module = node.module or ""
            yield node.lineno, module
            for alias in node.names:
                yield node.lineno, f"{module}.{alias.name}"


def _named(tree: ast.AST) -> Iterator[tuple[int, str]]:
    """(line, dotted name) for each string that reads as a module path, an entry point's
    (`pkg.mod:attr` imports `pkg.mod`) included."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            module = node.value.partition(":")[0]
            if module and all(part.isidentifier() for part in module.split(".")):
                yield node.lineno, module


def _parse(source: str) -> ast.AST:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", SyntaxWarning)
        return ast.parse(source)


def _references(source: str, package: list[str]) -> list[str]:
    """`line: name` for each import or import string in `source` naming the adapter package."""
    tree = _parse(source)
    return [
        f"{line}: {name}"
        for line, name in (*_imported(tree, package), *_named(tree))
        if name == ADAPTER or name.startswith(f"{ADAPTER}.")
    ]


IN_OMS = ["candleviewer", "oms"]


@pytest.mark.parametrize(
    "source",
    [
        "import candleviewer.exchange.bybit",
        "import candleviewer.exchange.bybit.trading as t",
        "from candleviewer.exchange import bybit",
        "from candleviewer.exchange.bybit.trading import TradingAdapter",
        "from ..exchange.bybit import trading",
        "from ..exchange import bybit",
        "from ...candleviewer.exchange.bybit import x",
        "if TYPE_CHECKING:\n    from candleviewer.exchange.bybit.rest import RestClient",
        "importlib.import_module('candleviewer.exchange.bybit.trading')",
        "_ADAPTER = 'candleviewer.exchange.bybit'",
        "pkgutil.resolve_name('candleviewer.exchange.bybit.trading:TradingAdapter')",
    ],
)
def test_a_reference_to_the_adapter_package_is_found(source: str) -> None:
    assert _references(source, IN_OMS) != []


@pytest.mark.parametrize(
    "source",
    [
        "from candleviewer.exchange.base.ports import TradingPort",
        "from candleviewer.exchange import base",
        "import candleviewer.exchange.policy",
        "from . import routing",
        "from .ports import RateReading",
        "from ..exchange.base import fakes",
        "import candleviewer.exchange.bybitlike",
        "'''The adapter package is the exchange's.'''",
        "_NOTE = 'exchange adapter: see exchange.base'",
    ],
)
def test_a_non_reference_is_allowed(source: str) -> None:
    assert _references(source, IN_OMS) == []


def test_relative_imports_resolve_against_the_modules_own_package() -> None:
    assert _package_of(OMS / "routing.py") == ["candleviewer", "oms"]
    assert _package_of(OMS / "__init__.py") == ["candleviewer", "oms"]
    assert _references("from .bybit import x", ["candleviewer", "exchange"]) != []


def test_no_oms_module_references_the_adapter_package() -> None:
    """C-2.2: every `candleviewer/oms/` module, `routing` (the trading ports) among them."""
    modules = sorted(OMS.rglob("*.py"))
    assert OMS / "routing.py" in modules
    found = {
        path.relative_to(PACKAGE).as_posix(): refs
        for path in modules
        if (refs := _references(path.read_text(encoding="utf-8"), _package_of(path)))
    }
    assert found == {}


def test_the_generated_import_contract_forbids_the_adapter_package_to_the_oms() -> None:
    """`docs/plan/module-contracts.toml` -> `.importlinter` (`pnpm arch` checks it is current)."""
    config = configparser.ConfigParser()
    config.read(PACKAGE.parent / ".importlinter", encoding="utf-8")
    contract = config["importlinter:contract:forbidden-adapter-isolation"]
    assert contract["type"] == "forbidden"
    assert contract["source_modules"].split() == ["candleviewer.oms"]
    assert contract["forbidden_modules"].split() == [ADAPTER]


def _defining(member: str) -> set[tuple[str, str]]:
    """Every class in `candleviewer` that defines `member`, as (module path, class name)."""
    found = set()
    for path in sorted(PACKAGE.rglob("*.py")):
        for node in ast.walk(_parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ClassDef) and any(
                isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef) and item.name == member
                for item in node.body
            ):
                found.add((path.relative_to(PACKAGE).as_posix(), node.name))
    return found


def test_no_handover_store_is_the_only_bound_order_handovers() -> None:
    """S2-Q3's deviation, until E29-T06 binds `oms_handovers`: the classes in `candleviewer` that
    hand an order over are `NoHandoverStore`, which hands none, so a squatted id goes `unknown`,
    and E29-T06's table writer `StoreHandovers` (its PR 1), which nothing composes yet (the pin
    below). E29-T06's wiring binds the writer and drops the stand-in from this pin."""
    handing = _defining("hand_over_order")
    assert handing == {
        ("oms/ports.py", "OrderHandovers"),
        ("oms/ports.py", "NoHandoverStore"),
        ("oms/handovers.py", "StoreHandovers"),
    }


def test_no_handover_store_is_the_only_bound_execution_handovers() -> None:
    """The same for E29-T05's sibling port (24 Sec.8.3 rule 7: `oms_handovers` is a table, never
    process memory): the classes in `candleviewer` that hand an execution over are
    `NoHandoverStore`, which hands none, so no stand-in keeps a fill a restart would lose, and
    E29-T06's table writer `StoreHandovers`, which nothing composes yet (the pin below)."""
    handing = _defining("hand_over_execution")
    assert handing == {
        ("oms/ports.py", "ExecutionHandovers"),
        ("oms/ports.py", "NoHandoverStore"),
        ("oms/handovers.py", "StoreHandovers"),
    }


def test_the_handover_table_writer_is_composed_nowhere_until_its_wiring() -> None:
    """E29-T06 PR 1 lands `StoreHandovers` unbound: no module in `candleviewer` but its own names
    it, so `NoHandoverStore` stays the composed port until E29-T06's wiring (PR2b) binds the
    writer, re-keys the live refusal and updates the two pins above."""
    naming = {
        path.relative_to(PACKAGE).as_posix()
        for path in sorted(PACKAGE.rglob("*.py"))
        if "StoreHandovers" in path.read_text(encoding="utf-8")
    }
    assert naming == {"oms/handovers.py"}
