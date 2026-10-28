"""E12-Q04 (#420): the conformance report of the market contract tests. Hooks only.

Each case (a test function) of the E12-Q04 modules is set against the committed list of expected
ones, `e12_q04_cases.txt`, and printed as a matrix (surface x case x outcome) at the end of a run
that collected any of them. A listed case that did not pass prints `NOT RUN` or `FAILED` and a
`::warning::` line, so coverage that went missing shows in CI; a case that ran but is not listed
prints `NEW`. When `CV_CONFORMANCE_REPORT_DIR` is set, the matrix is also written there as
`e12-q04-conformance.json` and `.md`, and when `GITHUB_STEP_SUMMARY` is set, appended to the job's
summary. That every listed case has a test is `test_contract_e12_q04_expected_cases_are_the_tests`.
"""

from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path
from typing import Any, Final

import pytest

_ROOT: Final = Path(__file__).resolve().parents[2]  # services/api: node ids are relative to it
EXPECTED: Final = Path(__file__).with_name("e12_q04_cases.txt")
#: The surface each listed module's cases exercise, for the matrix.
SURFACES: Final = {
    "tests/contract/test_market_e12_q04_contract.py": "GET /market/klines and /market/bars",
    "tests/contract/test_market_schemathesis_contract.py": "the same, fuzzed (Schemathesis)",
    "tests/contract/ws/test_ws_bars_e12_q04_contract.py": "bars.{symbol}.{bar_type}.{param}",
}
_COLLECTED: Final = pytest.StashKey[set[str]]()
_OUTCOMES: Final = ("passed", "failed", "error", "skipped", "xfailed", "xpassed")


def expected_cases() -> list[str]:
    """`module::test` per line of `e12_q04_cases.txt`; `#` starts a comment."""
    lines = (line.partition("#")[0].strip() for line in EXPECTED.read_text("utf-8").splitlines())
    return [line for line in lines if line]


_MODULES: Final = frozenset(case.partition("::")[0] for case in expected_cases())


def _case(nodeid: str) -> str | None:
    """`module::test` of an item of a listed module (its parameters dropped), else None."""
    module, _, name = nodeid.partition("::")
    return f"{module}::{name.partition('[')[0]}" if module in _MODULES else None


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """The E12-Q04 cases collected, before `-m` or `-k` deselect any."""
    config.stash[_COLLECTED] = {case for item in items if (case := _case(item.nodeid))}


def _matrix(stats: dict[str, list[Any]], collected: set[str]) -> list[dict[str, Any]]:
    counts: dict[str, Counter[str]] = {}
    for outcome in _OUTCOMES:
        for report in stats.get(outcome, []):
            if case := _case(getattr(report, "nodeid", "")):
                counts.setdefault(case, Counter())[outcome] += 1
    modules = {case.partition("::")[0] for case in collected}
    listed = [case for case in expected_cases() if case.partition("::")[0] in modules]
    rows = []
    for case in [*listed, *sorted(set(counts) - set(listed))]:
        got = counts.get(case, Counter())
        bad = got["failed"] + got["error"] + got["xpassed"]
        status = "FAILED" if bad else "PASSED" if got["passed"] else "NOT RUN"
        status = "NEW" if case not in listed and status == "PASSED" else status
        module = case.partition("::")[0]
        rows.append({"surface": SURFACES.get(module, module), "case": case, "status": status, **{
            outcome: got[outcome] for outcome in _OUTCOMES if got[outcome]}})  # fmt: skip
    return rows


def _markdown(rows: list[dict[str, Any]]) -> str:
    lines = ["| Surface | Case | Outcome | Counts |", "| --- | --- | --- | --- |"]
    for row in rows:
        counts = ", ".join(f"{k} {v}" for k, v in row.items() if k in _OUTCOMES)
        test = row["case"].partition("::")[2]
        lines.append(f"| {row['surface']} | `{test}` | {row['status']} | {counts or '-'} |")
    return "\n".join(["### E12-Q04 contract conformance (#420)", "", *lines, ""])


def pytest_terminal_summary(terminalreporter: Any, config: pytest.Config) -> None:
    collected = config.stash.get(_COLLECTED, set())
    if not collected or config.option.collectonly:  # nothing ran: no outcome to report
        return
    rows = _matrix(terminalreporter.stats, collected)
    terminalreporter.section("E12-Q04 contract conformance (#420): surface x case x outcome")
    for row in rows:
        terminalreporter.write_line(f"{row['status']:>8}  {row['case']}")
        if row["status"] in ("NOT RUN", "FAILED"):
            terminalreporter.write_line(f"::warning::E12-Q04 case {row['status']}: {row['case']}")
    if out := os.environ.get("CV_CONFORMANCE_REPORT_DIR"):
        folder = _ROOT / out
        folder.mkdir(parents=True, exist_ok=True)
        report = json.dumps(rows, indent=2) + "\n"
        (folder / "e12-q04-conformance.json").write_text(report, encoding="utf-8")
        (folder / "e12-q04-conformance.md").write_text(_markdown(rows), encoding="utf-8")
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(summary).open("a", encoding="utf-8") as fh:
            fh.write(_markdown(rows))
