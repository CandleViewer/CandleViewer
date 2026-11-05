"""E29-Q02 (#1147): the conformance report's own tests. The committed cases list
(`e29_q02_cases.txt`) names exactly the tests its modules define and gives each a surface and
plan cases; the report puts them in its artifact and is registered by `conftest.py` whichever way
the suite is run. The writer it shares with E12-Q04's report is `test_conformance_report.py`'s."""

from __future__ import annotations

import ast
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Final, cast

import pytest

from tests.contract import e29_q02_report as report
from tests.contract._conformance_report import read_cases

_API: Final = Path(__file__).resolve().parents[2]
_LISTED: Final = read_cases(report.EXPECTED)  # `module::test`, surface and plan cases per line
_CASES: Final = report.REPORT.expected_cases()


@pytest.fixture(autouse=True)
def _no_destinations(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("CV_CONFORMANCE_REPORT_DIR", "GITHUB_STEP_SUMMARY"):
        monkeypatch.delenv(name, raising=False)


def _summary(**outcomes: list[str]) -> list[str]:
    """The lines the report writes when the terminal reporter holds `outcomes` (node ids)."""
    lines: list[str] = []
    stats = {kind: [SimpleNamespace(nodeid=n) for n in ids] for kind, ids in outcomes.items()}
    reporter = SimpleNamespace(stats=stats, section=lines.append, write_line=lines.append)
    config = cast(pytest.Config, SimpleNamespace(stash=pytest.Stash()))  # what the hook reads
    config.stash[report.REPORT.collected] = set(_CASES)
    report.REPORT.pytest_terminal_summary(reporter, config)
    return lines


def test_e29_q02_cases_list_names_exactly_the_tests_its_modules_define() -> None:
    """A listed case with no test fails here, and so does a test the list lacks."""
    listed = set(_CASES)
    defined = {
        f"{module}::{node.name}"
        for module in {case.partition("::")[0] for case in listed}
        for node in ast.parse((_API / module).read_text(encoding="utf-8")).body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        and node.name.startswith("test_")
    }
    assert sorted(listed ^ defined) == []


def test_e29_q02_cases_list_gives_each_test_a_surface_and_plan_cases_once() -> None:
    assert [line[0] for line in _LISTED if len(line) != 3 or not all(line)] == []
    plan = [case.strip() for _, _, cases in _LISTED for case in cases.split(",")]
    assert [case for case in plan if not report.PLAN_CASE.fullmatch(case)] == []
    assert len(set(_CASES)) == len(_CASES)


def test_e29_q02_report_prints_only_when_a_case_ran() -> None:
    """A run that collected the cases and ran none (a lane whose markers deselect them) prints
    nothing; once one ran, the matrix lists every case, the others as `NOT RUN`."""
    assert _summary(passed=["tests/contract/test_market_tickers_contract.py::test_x"]) == []
    lines = _summary(passed=[f"{_CASES[0]}[a-case]"])
    statuses = [line[:8].strip() for line in lines[1:] if not line.startswith("::")]
    assert statuses == ["PASSED"] + ["NOT RUN"] * (len(_CASES) - 1)


def test_e29_q02_report_writes_its_artifact_and_names_a_case_that_failed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`e29-q02-conformance.json` and `.md`: each row its surface, plan cases and outcome."""
    monkeypatch.setenv("CV_CONFORMANCE_REPORT_DIR", str(tmp_path))
    case, surface, plan = _LISTED[0]
    plan_cases = [c.strip() for c in plan.split(",")]
    lines = _summary(failed=[case])
    [row, *_] = json.loads((tmp_path / "e29-q02-conformance.json").read_text("utf-8"))
    assert (row["surface"], row["plan_cases"], row["status"]) == (surface, plan_cases, "FAILED")
    assert f"::warning::E29-Q02 case FAILED: {case}" in lines
    table = (tmp_path / "e29-q02-conformance.md").read_text("utf-8")
    assert (
        f"| {surface} | `{case.partition('::')[2]}` | {', '.join(plan_cases)} | FAILED |" in table
    )


def test_e29_q02_report_gives_a_test_the_list_lacks_its_module_and_no_plan_cases() -> None:
    module = _CASES[0].partition("::")[0]
    case = f"{module}::test_not_listed"
    assert report.REPORT.row(case) == {"surface": module, "case": case, "plan_cases": []}
    assert f"     NEW  {case}" in _summary(passed=[case])


def test_e29_q02_report_is_registered_by_the_contract_conftest(
    request: pytest.FixtureRequest,
) -> None:
    assert request.config.pluginmanager.has_plugin(report.REPORT.name)
