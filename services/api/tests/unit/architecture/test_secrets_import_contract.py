"""C-3.2 for the account delete and the key revoke (E27-S04 B3c/B3d, #898): M2's key destroyer
reaches `accounts` and `api` only as a port the composition root binds (`app.py` hands them
`SecretsBundle.key_destroyer`), so neither package imports `candleviewer.secrets`, at any depth,
in any form; and the `protected-secrets` import-linter contract still admits only the exchange
adapter and `admin`. A plain AST scan, so it holds whether or not `lint-imports` runs."""

from __future__ import annotations

import ast
import configparser
from pathlib import Path

import pytest

PKG = Path(__file__).resolve().parents[3] / "candleviewer"
LINTER = PKG.parent / ".importlinter"
_SCANNED = ("accounts", "api")


def _secrets_imports(path: Path, source: str | None = None) -> list[str]:
    """Every import of `candleviewer.secrets` (or a submodule) in `path` (or `source`, read as
    that file), absolute or relative."""
    found: list[str] = []
    text = path.read_text(encoding="utf-8") if source is None else source
    tree = ast.parse(text, filename=str(path))
    package = ".".join(path.relative_to(PKG.parent).with_suffix("").parts[:-1])
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [a.name for a in node.names if _is_secrets(a.name)]
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                parent = package.split(".")[: len(package.split(".")) - node.level + 1]
                base = ".".join([*parent, base] if base else parent)
            names = [f"{base}.{a.name}" for a in node.names]
            if _is_secrets(base) or any(_is_secrets(n) for n in names):
                found.append(base)
    return found


def _is_secrets(name: str) -> bool:
    return name == "candleviewer.secrets" or name.startswith("candleviewer.secrets.")


@pytest.mark.parametrize(
    "path",
    [p for d in _SCANNED for p in sorted((PKG / d).rglob("*.py"))],
    ids=lambda p: str(p.relative_to(PKG)),
)
def test_accounts_and_api_never_import_m2(path: Path) -> None:
    assert _secrets_imports(path) == [], f"{path}: C-3.2, use the port the root binds"


def test_the_scan_sees_an_absolute_a_from_and_a_relative_import() -> None:
    probe = PKG / "accounts" / "_probe.py"
    for src in (
        "import candleviewer.secrets",
        "from candleviewer.secrets.service import KeyDestroyer",
        "from candleviewer import secrets",
        "from ..secrets import mint_key_destroyer",
    ):
        assert _secrets_imports(probe, src), src
    assert _secrets_imports(probe, "from candleviewer.accounts import lifecycle") == []


def test_the_protected_secrets_contract_admits_only_the_adapter_and_admin() -> None:
    parser = configparser.ConfigParser()
    parser.read(LINTER, encoding="utf-8")
    contract = parser["importlinter:contract:protected-secrets"]
    assert contract["type"] == "protected"
    assert contract["protected_modules"].split() == ["candleviewer.secrets"]
    assert sorted(contract["allowed_importers"].split()) == [
        "candleviewer.admin",
        "candleviewer.exchange.bybit",
    ]


def test_the_root_hands_the_destroyer_over_without_naming_an_m2_type() -> None:
    """`app.py` reads the bundle's field; the lifecycle and the revoke take it as M13's port."""
    app = (PKG / "app.py").read_text(encoding="utf-8")
    assert "key_destroyer = bundle.key_destroyer" in app
    assert _secrets_imports(PKG / "account_lifecycle_wiring.py") == []
