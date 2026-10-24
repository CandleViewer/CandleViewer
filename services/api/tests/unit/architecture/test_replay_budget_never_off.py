"""#2668 G1 (C-4.14): production code never builds a replay clock, run or source without a lane.

`ReplayClock` / `ReplayRun` take `budget_lane=None` and `ReplaySource` defaults its `lane` to
`FREE_LANE` (no budget) for tests and `bench/` only (`RecordedMerge` requires one: mypy pins it). In
`candleviewer/` no call may pass `budget_lane=None` or `lane=None`, no `ReplaySource(...)` may omit
`lane=`, and only the modules that define the fallback may name `FREE_LANE` or `_FreeLane` (as a
name, an attribute or an import).
"""

from __future__ import annotations

import ast
import warnings
from pathlib import Path

import candleviewer

PKG = Path(candleviewer.__file__).resolve().parent
FALLBACK_OWNERS = frozenset({"replay/budget.py", "replay/clock.py", "replay/source.py"})
FALLBACK = frozenset({"FREE_LANE", "_FreeLane"})


def _named(node: ast.AST) -> str | None:
    """The fallback name `node` refers to, if any."""
    if isinstance(node, ast.Name):
        name: str | None = node.id
    elif isinstance(node, ast.Attribute):
        name = node.attr
    elif isinstance(node, ast.alias):
        name = node.name
    else:
        return None
    return name if name in FALLBACK else None


def test_no_production_call_turns_the_replay_loop_budget_off() -> None:
    found: list[str] = []
    for path in sorted(PKG.rglob("*.py")):
        rel = path.relative_to(PKG).as_posix()
        with warnings.catch_warnings():  # another module's escape sequences are not this test's
            warnings.simplefilter("ignore", SyntaxWarning)
            tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                callee = node.func
                called = callee.id if isinstance(callee, ast.Name) else getattr(callee, "attr", "")
                keywords = {kw.arg for kw in node.keywords}
                if called == "ReplaySource" and "lane" not in keywords and None not in keywords:
                    found.append(f"{rel}:{node.lineno} ReplaySource without lane=")
                found += [
                    f"{rel}:{node.lineno} {kw.arg}=None"
                    for kw in node.keywords
                    if kw.arg in {"budget_lane", "lane"}
                    and isinstance(kw.value, ast.Constant)
                    and kw.value.value is None
                ]
            elif (name := _named(node)) is not None and rel not in FALLBACK_OWNERS:
                found.append(f"{rel}:{getattr(node, 'lineno', 0)} {name}")
    assert found == []
