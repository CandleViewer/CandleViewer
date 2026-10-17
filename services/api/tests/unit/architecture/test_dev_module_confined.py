"""#2893 S3 (ADR-0036 "Enforcement"): the dev-only `cvdev` package stays behind its one door.

- In `candleviewer/`, only `account_fixture_wiring.py` names `cvdev`, and never in an import
  statement: it holds the module it imports lazily and the package name its refusal matches, as
  strings. No other module imports it or holds an import string for it
  (`importlib.import_module`, `__import__`, `find_spec`, a constant passed to one, or an entry
  point such as `pkgutil.resolve_name("cvdev.mod:attr")`). A release
  image has no `cvdev`, so any other reference either breaks boot or opens a second way in.
- `cvdev` never imports `candleviewer.secrets` (C-3.2) or `candleviewer.audit` (C-3.3), directly
  or by an import string. With `cvdev` a root package of `services/api/.importlinter`, the
  `protected` contracts hold the direct imports too; only this test sees the strings.

The Semgrep rule `cv-dev-module-confined` holds the first ban in the product scan as well.
Limits: these are AST checks, so a name built at run time (`"cv" + "dev"`, an f-string) is not
caught.
"""

from __future__ import annotations

import ast
import configparser
import warnings
from collections.abc import Iterator
from pathlib import Path

import pytest

import candleviewer
import cvdev

PACKAGE = Path(candleviewer.__file__).resolve().parent
DEV_PACKAGE = Path(cvdev.__file__).resolve().parent
#: The composition root's one door to `cvdev` (#2893 ruling 1).
WIRING = PACKAGE / "account_fixture_wiring.py"
DEV = ("cvdev",)
#: What `cvdev` may never import (C-3.2, C-3.3).
PROTECTED = ("candleviewer.secrets", "candleviewer.audit")


def _imported_modules(tree: ast.AST) -> Iterator[tuple[int, str]]:
    """(line, dotted name) for each absolute import statement, `TYPE_CHECKING` ones included.
    A relative import stays inside its own top-level package, so it never names another one."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, alias.name
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            for alias in node.names:
                yield node.lineno, f"{node.module}.{alias.name}"


def _named_modules(tree: ast.AST) -> Iterator[tuple[int, str]]:
    """(line, dotted name) for each absolute import and each string that reads as a module path,
    an entry point's (`pkgutil.resolve_name("pkg.mod:attr")` imports `pkg.mod`) included."""
    yield from _imported_modules(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            module, _, attribute = node.value.partition(":")
            dotted = module.split(".") + (attribute.split(".") if attribute else [])
            if all(part.isidentifier() for part in dotted):
                yield node.lineno, module


def _parse(source: str) -> ast.AST:
    with warnings.catch_warnings():
        # Applied migrations, which must never be edited (C-5.4), may carry a SyntaxWarning.
        warnings.simplefilter("ignore", SyntaxWarning)
        return ast.parse(source)


def _references(source: str, modules: tuple[str, ...], *, imports_only: bool = False) -> list[str]:
    """`line: name` for each name in `source` that is one of `modules` or inside one."""
    names = (_imported_modules if imports_only else _named_modules)(_parse(source))
    return [
        f"{line}: {name}"
        for line, name in names
        if any(name == module or name.startswith(f"{module}.") for module in modules)
    ]


@pytest.mark.parametrize(
    ("source", "modules"),
    [
        ("import cvdev", DEV),
        ("import cvdev.account_fixture.wiring as w", DEV),
        ("from cvdev import account_fixture", DEV),
        ("from cvdev.account_fixture.wiring import build", DEV),
        ("importlib.import_module('cvdev.account_fixture.wiring')", DEV),
        ("__import__('cvdev')", DEV),
        ("importlib.util.find_spec('cvdev')", DEV),
        ("_DOOR = 'cvdev.account_fixture'", DEV),
        ("pkgutil.resolve_name('cvdev.account_fixture.wiring:build')", DEV),
        ("pkgutil.resolve_name('cvdev:')", DEV),
        ("from candleviewer import secrets", PROTECTED),
        ("import candleviewer.secrets.broker", PROTECTED),
        ("from candleviewer.audit.writer import AuditWriter", PROTECTED),
        ("importlib.import_module('candleviewer.audit')", PROTECTED),
    ],
)
def test_a_reference_is_found(source: str, modules: tuple[str, ...]) -> None:
    assert _references(source, modules) != []


@pytest.mark.parametrize(
    ("source", "modules"),
    [
        ("import cvdevtools", DEV),
        ("from candleviewer.account_fixture_wiring import build_account_fixture", DEV),
        ("'''The cvdev package is dev-only.'''", DEV),
        ("pkgutil.resolve_name('candleviewer.app:create_app')", DEV),
        ("_NOTE = 'cvdev: dev-only'", DEV),
        ("from candleviewer import settings", PROTECTED),
        ("import candleviewer.secretsmanager", PROTECTED),
        ("from . import secrets", PROTECTED),
    ],
)
def test_a_non_reference_is_allowed(source: str, modules: tuple[str, ...]) -> None:
    assert _references(source, modules) == []


@pytest.mark.parametrize(
    ("source", "is_import"),
    [
        ("import cvdev.account_fixture.wiring", True),
        ("from cvdev.account_fixture import wiring", True),
        ("if TYPE_CHECKING:\n    from cvdev import account_fixture", True),
        ("_DEV_WIRING = 'cvdev.account_fixture.wiring'", False),
        ("importlib.import_module('cvdev')", False),
    ],
)
def test_only_an_import_statement_is_a_static_import(source: str, is_import: bool) -> None:
    assert _references(source, DEV) != []
    assert (_references(source, DEV, imports_only=True) != []) is is_import


def _offenders(root: Path, modules: tuple[str, ...], skip: Path | None = None) -> list[str]:
    return [
        f"{path.relative_to(root.parent)}:{reference}"
        for path in sorted(root.rglob("*.py"))
        if path != skip
        for reference in _references(path.read_text(encoding="utf-8"), modules)
    ]


def test_only_the_wiring_module_names_cvdev() -> None:
    offenders = _offenders(PACKAGE, DEV, skip=WIRING)
    assert offenders == [], (
        f"product modules name the dev-only package: {offenders}. Only "
        "`candleviewer.account_fixture_wiring` may; call `build_account_fixture` instead."
    )


def test_the_wiring_module_never_imports_cvdev_statically() -> None:
    """A static import would break every release image's boot; the module is imported only when
    `CV_ACCOUNT_FIXTURE` is set. The Semgrep rule skips this file, so this test is its guard."""
    assert _references(WIRING.read_text(encoding="utf-8"), DEV, imports_only=True) == []


def test_the_wiring_module_names_cvdev_only_in_its_two_strings() -> None:
    """`_DEV_WIRING`, the module imported lazily, and `_DEV_PACKAGE`, the name its refusal matches
    in `ModuleNotFoundError.name`. Counted, not a set, so a third reference fails. This also shows
    the scan sees a real reference."""
    references = _references(WIRING.read_text(encoding="utf-8"), DEV)
    assert sorted(ref.split(": ")[1] for ref in references) == [
        "cvdev",
        "cvdev.account_fixture.wiring",
    ]


def test_cvdev_never_imports_secrets_or_audit() -> None:
    offenders = _offenders(DEV_PACKAGE, PROTECTED)
    assert offenders == [], (
        f"the dev-only package names a protected module: {offenders} (C-3.2, C-3.3). Take what it "
        "needs through an injected sink, as `auth/testnet_clock.py` does."
    )


def test_cvdev_is_an_import_linter_root_under_the_protected_contracts() -> None:
    """Generated by `scripts/gen_importlinter_contracts.py`: as a root package, `cvdev`'s direct
    imports are in the graph that the C-3.2 and C-3.3 `protected` contracts check."""
    config = configparser.ConfigParser(interpolation=None)
    config.read(PACKAGE.parent / ".importlinter", encoding="utf-8")
    assert config["importlinter"]["root_packages"].split() == ["candleviewer", "cvdev"]
    for name in ("protected-secrets", "protected-audit"):
        contract = config[f"importlinter:contract:{name}"]
        assert contract["type"] == "protected"
        assert not [m for m in contract["allowed_importers"].split() if m.startswith("cvdev")]
