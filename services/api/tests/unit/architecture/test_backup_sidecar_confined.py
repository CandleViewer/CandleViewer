"""#3319 B1a (ADR-0041 section 1): the backup sidecar `cvbackup` and `candleviewer` stay apart.

- `cvbackup` imports the standard library and itself only: no `candleviewer` module and none of
  the API's third-party packages, so its image carries neither. `services/api/.importlinter`
  holds both rules (`independence-backup-sidecar`, `forbidden-cvbackup-thirdparty`) for the
  imports import-linter sees; this AST scan holds every top-level name, a third-party package the
  forbidden list does not name included.
- Nothing in `candleviewer` or `cvdev` imports `cvbackup` or holds an import string for it: the
  API reaches the sidecar over its socket only.
- No distribution or API image carries it: the wheel names only `candleviewer`, the sdist
  excludes it and `infra/images/Dockerfile.api` copies only `candleviewer`.
"""

from __future__ import annotations

import ast
import configparser
import sys
import tomllib
import warnings
from collections.abc import Iterator
from pathlib import Path

import pytest

import candleviewer
import cvbackup
import cvdev

API = Path(candleviewer.__file__).resolve().parents[1]
SIDECAR = Path(cvbackup.__file__).resolve().parent
OTHERS = (
    Path(candleviewer.__file__).resolve().parent,
    Path(cvdev.__file__).resolve().parent,
)


def _parse(path: Path) -> ast.AST:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", SyntaxWarning)  # an applied migration's `\:` (C-5.4)
        return ast.parse(path.read_text(encoding="utf-8"))


def _imports(tree: ast.AST) -> Iterator[tuple[int, str]]:
    """(line, dotted name) of each absolute import, `TYPE_CHECKING` ones included."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from ((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            yield node.lineno, node.module


def _strings(tree: ast.AST) -> Iterator[tuple[int, str]]:
    """(line, text) of each string that reads as a dotted module path or an entry point."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            module = node.value.partition(":")[0]
            if module and all(part.isidentifier() for part in module.split(".")):
                yield node.lineno, module


def test_the_sidecar_imports_the_standard_library_and_itself_only() -> None:
    allowed = set(sys.stdlib_module_names) | {"cvbackup"}
    files = sorted(SIDECAR.rglob("*.py"))
    assert files, "the sidecar package exists"
    found = [
        f"{path.relative_to(API)}:{line}: {name}"
        for path in files
        for line, name in _imports(_parse(path))
        if name.split(".", 1)[0] not in allowed
    ]
    assert found == []


@pytest.mark.parametrize("package", OTHERS, ids=lambda p: p.name)
def test_no_api_or_dev_module_names_the_sidecar(package: Path) -> None:
    found = []
    for path in sorted(package.rglob("*.py")):
        tree = _parse(path)
        found += [
            f"{path.relative_to(API)}:{line}: {name}"
            for line, name in (*_imports(tree), *_strings(tree))
            if name == "cvbackup" or name.startswith("cvbackup.")
        ]
    assert found == []


def test_the_import_contracts_hold_both_directions_and_the_third_party_ban() -> None:
    config = configparser.ConfigParser()
    config.read(API / ".importlinter", encoding="utf-8")
    assert "cvbackup" in config["importlinter"]["root_packages"].split()
    independence = config["importlinter:contract:independence-backup-sidecar"]
    assert independence["type"] == "independence"
    assert independence["modules"].split() == ["candleviewer", "cvbackup"]
    forbidden = config["importlinter:contract:forbidden-cvbackup-thirdparty"]
    assert (forbidden["type"], forbidden["source_modules"].split()) == (
        "forbidden",
        ["cvbackup"],
    )
    banned = set(forbidden["forbidden_modules"].split())
    assert {
        "pydantic",
        "sqlalchemy",
        "asyncpg",
        "cryptography",
        "structlog",
        "fastapi",
    } <= banned
    assert not banned & set(sys.stdlib_module_names)


def test_no_distribution_or_api_image_carries_the_sidecar() -> None:
    project = tomllib.loads((API / "pyproject.toml").read_text(encoding="utf-8"))
    targets = project["tool"]["hatch"]["build"]["targets"]
    assert targets["wheel"]["packages"] == ["candleviewer"]
    assert "/cvbackup" in targets["sdist"]["exclude"]
    dockerfile = (API.parents[1] / "infra" / "images" / "Dockerfile.api").read_text("utf-8")
    copies = [line for line in dockerfile.splitlines() if line.startswith("COPY")]
    assert copies and not any("cvbackup" in line for line in copies)
    assert not any(
        line.rstrip().endswith(("services/api ./", "services/api/ ./")) for line in copies
    )
