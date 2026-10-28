"""#913 L1d-3: the binding measurements' numbers reach a green `py-perf` log.

CI runs `py-perf` without `-s` and without a JUnit report, so a `perf` test's `record_property`
would reach no one on a pass. Each passing test's `numbers` property is printed in the terminal
summary.
"""

from __future__ import annotations

from typing import Any


def pytest_terminal_summary(terminalreporter: Any) -> None:
    rows = [
        (report.nodeid, value)
        for report in terminalreporter.stats.get("passed", [])
        if getattr(report, "when", "call") == "call"
        for key, value in getattr(report, "user_properties", ())
        if key == "numbers"
    ]
    if not rows:
        return
    terminalreporter.section("#913 L1d-3: the binding measurements")
    for nodeid, value in rows:
        terminalreporter.write_line(f"{nodeid}: {value}")
