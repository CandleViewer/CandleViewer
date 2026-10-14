"""E17-Q01: requirement coverage matrix in the CI output, so a silently skipped or deselected
requirement is visible rather than green (ticket "Observability")."""

from __future__ import annotations

import re
from typing import Any

#: §16.1 server MUSTs; client obligations C1-C12 are E17-Q04's (cross-referenced in the plan).
REQUIREMENTS = tuple(f"S{n}" for n in range(1, 14))
_NAME = re.compile(r"::test_(s\d+)_")


def pytest_terminal_summary(terminalreporter: Any) -> None:
    ran: dict[str, int] = {}
    for status in ("passed", "failed", "skipped", "xfailed", "xpassed"):
        for report in terminalreporter.stats.get(status, []):
            if getattr(report, "when", "call") != "call" and status != "skipped":
                continue
            if "contract/ws/" not in report.nodeid:
                continue
            m = _NAME.search(report.nodeid)
            if m:
                ran.setdefault(m.group(1).upper(), 0)
                ran[m.group(1).upper()] += status == "passed"
    if not ran:
        return
    terminalreporter.section("E17-Q01 WS conformance: requirement coverage (23-ws-protocol §16.1)")
    for req in REQUIREMENTS:
        n = ran.get(req)
        terminalreporter.write_line(f"{req:>4}  " + ("NOT RUN" if n is None else f"{n} passed"))
