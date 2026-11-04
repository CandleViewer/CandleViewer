"""E29-Q02 (#1147): the conformance report's own tests. The committed cases list
(`e29_q02_cases.txt`) names exactly the tests its modules define and gives each a surface and
plan cases; the report prints only when a case ran, writes its artifact, and is registered by
`conftest.py` whichever way the suite is run."""

from __future__ import annotations

import ast
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Final, cast

import pytest

from tests.contract import e29_q02_report as report

_API: Final = Path(__file__).resolve().parents[2]
_ROWS: Final = report.expected_cases()


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
    config.stash[report._COLLECTED] = {row.case for row in _ROWS}
    report.Report().pytest_terminal_summary(reporter, config)
    return lines


def test_e29_q02_cases_list_names_exactly_the_tests_its_modules_define() -> None:
    """A listed case with no test fails here, and so does a test the list lacks."""
    listed = {row.case for row in _ROWS}
    defined = {
        f"{module}::{node.name}"
        for module in {case.partition("::")[0] for case in listed}
        for node in ast.parse((_API / module).read_text(encoding="utf-8")).body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        and node.name.startswith("test_")
    }
    assert sorted(listed ^ defined) == []


def test_e29_q02_cases_list_gives_each_test_a_surface_and_plan_cases_once() -> None:
    assert [row.case for row in _ROWS if not (row.surface and row.plan)] == []
    assert [c for row in _ROWS for c in row.plan if not report.PLAN_CASE.fullmatch(c)] == []
    assert len({row.case for row in _ROWS}) == len(_ROWS)


def test_e29_q02_report_prints_only_when_a_case_ran() -> None:
    """A run that collected the cases and ran none (a lane whose markers deselect them) prints
    nothing; once one ran, the matrix lists every case, the others as `NOT RUN`."""
    assert _summary(passed=["tests/contract/test_market_tickers_contract.py::test_x"]) == []
    lines = _summary(passed=[f"{_ROWS[0].case}[a-case]"])
    statuses = [line[:8].strip() for line in lines[1:] if not line.startswith("::")]
    assert statuses == ["PASSED"] + ["NOT RUN"] * (len(_ROWS) - 1)


def test_e29_q02_report_writes_its_artifact_and_names_a_case_that_failed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`e29-q02-conformance.json` and `.md`: each row its surface, plan cases and outcome."""
    monkeypatch.setenv("CV_CONFORMANCE_REPORT_DIR", str(tmp_path))
    first = _ROWS[0]
    lines = _summary(failed=[first.case])
    [row, *_] = json.loads((tmp_path / "e29-q02-conformance.json").read_text("utf-8"))
    assert (row["surface"], row["plan_cases"], row["status"]) == (
        first.surface, list(first.plan), "FAILED",
    )  # fmt: skip
    assert f"::warning::E29-Q02 case FAILED: {first.case}" in lines
    assert first.surface in (tmp_path / "e29-q02-conformance.md").read_text("utf-8")


def test_e29_q02_report_is_registered_by_the_contract_conftest(
    request: pytest.FixtureRequest,
) -> None:
    assert request.config.pluginmanager.has_plugin(report.NAME)
