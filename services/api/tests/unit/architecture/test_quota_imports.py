"""E21-X02 (#652, BQ-5): the subscription quota (`ws/quota.py`) is an admission check of the
gateway: it imports nothing from the exchange adapter and names no rate-limit governor, so it can
never read or spend a governor token, and it takes no upstream reference itself (`ws/upstream.py`
is the gateway's, after the quota). AST checks of the module's own imports and names, as in
`test_governor_injection.py`: an alias built at run time is not caught."""

from __future__ import annotations

import ast
from pathlib import Path

from candleviewer.ws import quota

SOURCE = Path(quota.__file__).read_text(encoding="utf-8")


def _imported(tree: ast.AST) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            found |= {node.module, *(f"{node.module}.{alias.name}" for alias in node.names)}
    return found


def test_the_quota_imports_nothing_from_exchange() -> None:
    imported = _imported(ast.parse(SOURCE))
    assert imported, "no import found: the scan is broken"
    assert sorted(m for m in imported if m.startswith("candleviewer.exchange")) == []
    assert sorted(m for m in imported if m.startswith("candleviewer.ws.upstream")) == []


def test_the_quota_names_no_governor_or_rate_limit() -> None:
    names = {
        n.id if isinstance(n, ast.Name) else n.attr
        for n in ast.walk(ast.parse(SOURCE))
        if isinstance(n, ast.Name | ast.Attribute)
    }
    assert sorted(n for n in names if "governor" in n.lower() or "rate_limit" in n.lower()) == []


def test_the_scan_sees_an_exchange_import() -> None:
    probe = "from candleviewer.exchange.bybit.rate_limit import TokenBucketGovernor\n"
    assert "candleviewer.exchange.bybit.rate_limit" in _imported(ast.parse(probe))
