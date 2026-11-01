"""E24-T02 CI guard: no hard-coded 480 / 8-hour funding constant in derivatives code.

Scans numeric constants (AST, so prose in docstrings is fine) of every derivatives
backend module and fails naming file:line. The only allowed literal is the
instruments-table column default, which lives in `db/models.py` / the adapter's
`parse_instrument` fallback and is deliberately NOT in the scanned set.
"""

from __future__ import annotations

import ast
from pathlib import Path

import candleviewer

PKG = Path(candleviewer.__file__).resolve().parent
SCANNED = (
    "domain/funding.py",
    "orderflow/funding.py",
    "orderflow/funding_metrics.py",
    "orderflow/derivatives.py",
    "orderflow/derivatives_metrics.py",
    "exchange/bybit/funding.py",
    "api/funding.py",
    "storage/questdb/funding_store.py",
)
_FORBIDDEN_INTS = {480, 28_800, 28_800_000, 28_800_000_000}


def violations(source: str, name: str) -> list[str]:
    out: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Constant) and not isinstance(node.value, bool):
            if node.value in _FORBIDDEN_INTS and isinstance(node.value, int):
                out.append(f"{name}:{node.lineno}: literal {node.value}")
        if (
            isinstance(node, ast.BinOp)
            and isinstance(node.op, ast.Mult)
            and isinstance(node.left, ast.Constant)
            and node.left.value == 8
            and isinstance(node.right, ast.Constant)
            and node.right.value in (60, 3600, 3_600_000)
        ):
            out.append(f"{name}:{node.lineno}: 8-hour product")
    return out


def test_derivatives_modules_have_no_hardcoded_funding_interval() -> None:
    found: list[str] = []
    for rel in SCANNED:
        path = PKG / rel
        assert path.is_file(), f"guard list is stale: {rel}"
        found += violations(path.read_text(encoding="utf-8"), rel)
    assert not found, "hard-coded funding interval:\n" + "\n".join(found)


def test_guard_detects_a_violation_and_names_file_and_line() -> None:
    bad = "x = 1\ninterval = 480\ny = 8 * 60\n"
    assert violations(bad, "m.py") == ["m.py:2: literal 480", "m.py:3: 8-hour product"]
    assert violations('"""8 h, 480 min in prose"""\n', "m.py") == []
