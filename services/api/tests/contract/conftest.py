"""E12-Q04 (#420): the conformance report of the market contract tests. Hooks only.

Each case (a test function) of the E12-Q04 modules is set against the committed list of expected
ones, `e12_q04_cases.txt`, and printed as a matrix (surface x case x outcome) at the end of a run
in which any of them recorded an outcome. A listed case that did not pass prints `NOT RUN` or
`FAILED` and a `::warning::` line, so coverage that went missing shows in CI; a case that ran but
is not listed prints `NEW`. When `CV_CONFORMANCE_REPORT_DIR` is set, the matrix is also written
there as `e12-q04-conformance.json` and `.md`, and when `GITHUB_STEP_SUMMARY` is set, appended to
the job's summary. That every listed case has a test is
`test_contract_e12_q04_expected_cases_are_the_tests`; that the report keeps quiet when none ran is
`test_contract_e12_q04_report_prints_only_when_a_case_ran`.

The matrix writer is `_conformance_report.py`'s, which E29-Q02's report (`e29_q02_report.py`, #1147)
uses too. This file supplies the case list, the report's name, the surface of each module and the
hooks that writer provides.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Final

from tests.contract._conformance_report import ConformanceReport
from tests.contract.e29_q02_report import pytest_configure  # noqa: F401 (E29-Q02's report)

EXPECTED: Final = Path(__file__).with_name("e12_q04_cases.txt")
#: The surface each listed module's cases exercise, for the matrix.
SURFACES: Final = {
    "tests/contract/test_market_e12_q04_contract.py": "GET /market/klines and /market/bars",
    "tests/contract/test_market_schemathesis_contract.py": "the same, fuzzed (Schemathesis)",
    "tests/contract/ws/test_ws_bars_e12_q04_contract.py": "bars.{symbol}.{bar_type}.{param}",
}


def _row(case: str) -> dict[str, Any]:
    module = case.partition("::")[0]
    return {"surface": SURFACES.get(module, module), "case": case}


_REPORT: Final = ConformanceReport(
    name="e12-q04-conformance",
    title="E12-Q04 contract conformance (#420)",
    cases=EXPECTED,
    columns={"Surface": "surface", "Case": "case", "Outcome": "status"},
    row=_row,
)
# pytest takes the hooks from this module; the E12-Q04 tests read the other two names.
pytest_collection_modifyitems = _REPORT.pytest_collection_modifyitems
pytest_terminal_summary = _REPORT.pytest_terminal_summary
expected_cases = _REPORT.expected_cases
_COLLECTED: Final = _REPORT.collected
