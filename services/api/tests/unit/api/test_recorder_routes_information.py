"""E16 recorder and recording routes: no problem response names a host path or a DSN.

A static check over the routes' problem helpers: every string literal passed to one of them is
a fixed, host-independent message. The handlers' runtime refusals are covered per route; this
keeps a new literal from carrying a filesystem location or a connection string into a response
a non-owner can read."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

import candleviewer.api as api_pkg

_ROUTES = (
    "recorder_purge.py",
    "recorder_admin.py",
    "recording_common.py",
    "recording_writes.py",
    "recording_retention.py",
    "recording_symbols.py",
    "recording_reports.py",
    "recording_status.py",
)
_HELPERS = frozenset(
    {"_problem", "problem", "limited", "_invalid", "bad", "_missing", "unavailable"}
)
_HOSTY = re.compile(r"(/[A-Za-z0-9_.-]+){2,}|[A-Za-z]:\\|\b[a-z][a-z0-9+.-]*://")


def _helper_literals(source: str) -> tuple[int, list[tuple[int, str]]]:
    """(helper calls seen, [(line, literal)] of every string constant in their arguments)."""
    calls, literals = 0, []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
        if name.lower() not in _HELPERS:
            continue
        calls += 1
        for arg in [*node.args, *(k.value for k in node.keywords)]:
            for sub in ast.walk(arg):
                if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                    literals.append((node.lineno, sub.value))
    return calls, literals


@pytest.mark.parametrize("route", _ROUTES)
def test_recorder_route_problem_literals_name_no_host_path_or_dsn(route: str) -> None:
    source = (Path(api_pkg.__file__).parent / route).read_text(encoding="utf-8")
    calls, literals = _helper_literals(source)
    assert calls > 0, f"{route}: no problem helper call found; the scan would be vacuous"
    hits = [(line, text) for line, text in literals if _HOSTY.search(text)]
    assert hits == []


@pytest.mark.parametrize(
    "literal",
    ["read /srv/cv/data failed", "C:\\cv\\data is full", "postgresql://cv@db/cv refused"],
)
def test_the_scan_flags_a_host_path_or_dsn_literal(literal: str) -> None:
    calls, literals = _helper_literals(f"_problem(500, 'Error', {literal!r})")
    assert calls == 1 and any(_HOSTY.search(text) for _, text in literals)
