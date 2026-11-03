"""E35-T11 slice 3b: the rule executor's boundaries (24 §11.5 "The principal"; E35-FR-01; the E35
threat model's RE-S1; BQ-16 of #863).

- The executor and its composition-root adapters read no HTTP session: the rule's owner and armer
  are read by user id (the identity read and the trade grants), and a rule's request names the
  owner with no session, address or correlation id. Scanned in the source, so a later import or
  call fails here and names its file.
- `rules` imports neither `oms` nor `accounts`: the order adapter lives at the composition root
  (`rules_oms_*`), as `forbidden-M15` keeps `storage`, `audit`, `auth` and `api` off `rules`.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import candleviewer

PKG = Path(candleviewer.__file__).resolve().parent
RULES = sorted((PKG / "rules").rglob("*.py"))
#: The composition-root adapters of the executor, whatever slice adds one.
ADAPTERS = sorted(PKG.glob("rules_oms_*.py"))
#: Every way the package reads a session or a request: the bearer's session, the view-as stamp
#: and context, the correlation id and the request object itself.
SESSION_NAMES = frozenset(
    {
        "authenticate_access_token", "view_as_subject", "view_as_stamp", "current_view_as",
        "current_request_uuid", "resolve_principal", "SessionTradingPrincipalResolver",
        "SessionRecord", "Request", "headers", "cookies", "sessions",
    }
)  # fmt: skip
SESSION_MODULES = ("fastapi", "starlette", "candleviewer.auth.service", "candleviewer.auth.view_as")
#: What an adapter may take from `candleviewer.api`: the identity read by user id, alone.
API_IMPORTS = frozenset({("candleviewer.api.audit_principal", "identity_snapshot")})


def _imports(tree: ast.AST) -> list[tuple[str, str | None]]:
    found: list[tuple[str, str | None]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [(alias.name, None) for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            found += [(node.module, alias.name) for alias in node.names]
    return found


def _names(tree: ast.AST) -> set[str]:
    return {
        node.id if isinstance(node, ast.Name) else node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Name | ast.Attribute)
    }


@pytest.mark.parametrize("path", RULES + ADAPTERS, ids=lambda p: str(p.relative_to(PKG)))
def test_executor_never_reads_the_http_session(path: Path) -> None:
    """G "The owner is the OMS principal and the armer is recorded (RE-S1, E35-FR-01)", "the
    executor never reads an HTTP session": no module of `rules` or of its adapters imports a
    request or session reader, names one, or takes from `api` anything but the identity read."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports = _imports(tree)
    assert not [m for m, _ in imports if m.startswith(SESSION_MODULES)], path
    assert not [
        (m, n) for m, n in imports if m.startswith("candleviewer.api") and (m, n) not in API_IMPORTS
    ], path
    assert not (_names(tree) & SESSION_NAMES), path


def test_the_scan_covers_the_executor_and_every_adapter() -> None:
    assert PKG / "rules" / "executor" / "engine.py" in RULES
    assert {p.name for p in ADAPTERS} >= {
        "rules_oms_wiring.py", "rules_oms_principals.py", "rules_oms_requests.py"
    }  # fmt: skip


@pytest.mark.parametrize("path", RULES, ids=lambda p: str(p.relative_to(PKG)))
def test_rules_module_imports_no_oms_or_accounts(path: Path) -> None:
    """BQ-16 of #863: the adapter lives at the composition root; `rules` reaches the OMS only
    through the handlers it binds, and imports neither `oms` nor `accounts`, not even by text."""
    text = path.read_text(encoding="utf-8")
    imported = [m for m, _ in _imports(ast.parse(text))]
    assert not [m for m in imported if m.startswith(("candleviewer.oms", "candleviewer.accounts"))]
    assert "candleviewer.oms" not in text and "candleviewer.accounts" not in text
