"""#2668 G1 (C-4.14): production code never builds a replay clock, run or source without a lane.

`ReplayClock` / `ReplayRun` take `budget_lane=None` and `ReplaySource` defaults its `lane` to
`FREE_LANE` (no budget) for tests and `bench/` only. In `candleviewer/` no call may pass
`budget_lane=None` or `lane=None`, and only the modules that define the fallback name `FREE_LANE`.
"""

from __future__ import annotations

import ast
import warnings
from pathlib import Path

import candleviewer

PKG = Path(candleviewer.__file__).resolve().parent
FALLBACK_OWNERS = frozenset(
    {"replay/budget.py", "replay/clock.py", "replay/source.py", "replay/merge.py"}
)


def test_no_production_call_turns_the_replay_loop_budget_off() -> None:
    found: list[str] = []
    for path in sorted(PKG.rglob("*.py")):
        rel = path.relative_to(PKG).as_posix()
        with warnings.catch_warnings():  # another module's escape sequences are not this test's
            warnings.simplefilter("ignore", SyntaxWarning)
            tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                found += [
                    f"{rel}:{node.lineno} {kw.arg}=None"
                    for kw in node.keywords
                    if kw.arg in {"budget_lane", "lane"}
                    and isinstance(kw.value, ast.Constant)
                    and kw.value.value is None
                ]
            elif (
                isinstance(node, ast.Name) and node.id == "FREE_LANE" and rel not in FALLBACK_OWNERS
            ):
                found.append(f"{rel}:{node.lineno} FREE_LANE")
    assert found == []
