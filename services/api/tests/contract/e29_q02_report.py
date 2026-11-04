"""E29-Q02 (#1147): the conformance report of the OMS contract tests. A case list and a row.

`e29_q02_cases.txt` lists, one test function per line, `module::test | surface | plan cases`: the
surface it exercises and the plan's cases (E29-TC-nnn, `docs/qa/e29-oms-test-plan.md`) it gives
evidence for. The matrix (surface x case x outcome) with its `NOT RUN`, `FAILED` and `NEW` rows,
its `::warning::` lines and its artifacts (`e29-q02-conformance.json` and `.md`, the job summary)
are `_conformance_report.py`'s, the writer E12-Q04's report (`conftest.py`) uses too.

`conftest.py` registers this report by re-exporting `pytest_configure`: `pytest_plugins` there is
refused once pytest has configured, which any run that does not name `tests/contract` has.
`test_e29_q02_report.py` guards the rest.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Final

import pytest

from tests.contract._conformance_report import ConformanceReport

EXPECTED: Final = Path(__file__).with_name("e29_q02_cases.txt")
PLAN_CASE: Final = re.compile(r"E29-TC-\d{3}")


def _row(case: str, surface: str = "", plan: str = "") -> dict[str, Any]:
    """The row of a listed case; for one the list lacks, its module as the surface and no plan."""
    return {
        "surface": surface or case.partition("::")[0],
        "case": case,
        "plan_cases": [p.strip() for p in plan.split(",") if p.strip()],
    }


REPORT: Final = ConformanceReport(
    name="e29-q02-conformance",
    title="E29-Q02 OMS contract conformance (#1147)",
    cases=EXPECTED,
    columns={"Surface": "surface", "Test": "case", "Plan cases": "plan_cases", "Outcome": "status"},
    row=_row,
)


def pytest_configure(config: pytest.Config) -> None:
    """Registers the report, once; `conftest.py` re-exports this hook, which runs for a conftest
    loaded after configuration too."""
    if not config.pluginmanager.has_plugin(REPORT.name):
        config.pluginmanager.register(REPORT, REPORT.name)
