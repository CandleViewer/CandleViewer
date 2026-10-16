"""Every SQLAlchemy engine the app builds hides bound parameters (C-12.6, #2758 item 4).

Without `hide_parameters=True`, `DBAPIError.__str__` renders `[parameters: ...]`. A write that the
`api_keys` write-once trigger refuses would then carry its SECRET-class ciphertext into any log of
the exception. `test_relational_engine.py` proves the flag's effect on the shared M10 builder. This
tripwire holds every engine-building call under `candleviewer/`, the Alembic engine included, to
the same flag, so a new builder cannot ship without it. Tests may build their own engines.
"""

from __future__ import annotations

import ast
from pathlib import Path

import candleviewer

_PACKAGE = Path(candleviewer.__file__).resolve().parent
_BUILDERS = frozenset(
    {"create_engine", "create_async_engine", "engine_from_config", "async_engine_from_config"}
)


def _name(func: ast.expr) -> str:
    if isinstance(func, ast.Attribute):
        return func.attr
    return func.id if isinstance(func, ast.Name) else ""


def _builder_calls() -> dict[str, ast.Call]:
    """Every engine-building call in the package source, keyed `<path>:<line>`."""
    calls: dict[str, ast.Call] = {}
    for path in sorted(_PACKAGE.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        if not any(builder in source for builder in _BUILDERS):
            continue
        for node in ast.walk(ast.parse(source, filename=str(path))):
            if isinstance(node, ast.Call) and _name(node.func) in _BUILDERS:
                calls[f"{path.relative_to(_PACKAGE).as_posix()}:{node.lineno}"] = node
    return calls


def _hides_parameters(call: ast.Call) -> bool:
    """The call passes the literal `hide_parameters=True` (a `**kwargs` spread does not count)."""
    return any(
        kw.arg == "hide_parameters"
        and isinstance(kw.value, ast.Constant)
        and kw.value.value is True
        for kw in call.keywords
    )


def test_the_scan_finds_the_known_engine_builders() -> None:
    """Keeps the tripwire from passing on an empty scan (wrong root, renamed builder)."""
    files = {site.rsplit(":", 1)[0] for site in _builder_calls()}
    assert {"migrations/env.py", "storage/repositories/relational_sqlalchemy.py"} <= files


def test_every_engine_the_app_builds_hides_bound_parameters() -> None:
    assert [site for site, call in _builder_calls().items() if not _hides_parameters(call)] == []
