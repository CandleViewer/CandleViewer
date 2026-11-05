"""The conformance report E12-Q04 (#420) and E29-Q02 (#1147) share, `_conformance_report.py`: the
outcomes it records per case, the matrix it builds, the lines, artifact and job summary it writes.
Each is checked on a small report of its own, with a case list written as the real ones are; the
last tests run the two real reports through it."""

from __future__ import annotations

import importlib.util
import json
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Final, cast

import pytest

from tests.contract import e29_q02_report
from tests.contract._conformance_report import ConformanceReport

_LIST: Final = """\
# a comment line, then a listed test per line: module::test | surface | plan cases
tests/m.py::test_a | surface A | plan 1, plan 2

tests/m.py::test_b | surface B | plan 3   # a trailing comment
tests/n.py::test_c | surface C |
"""
_A: Final = "tests/m.py::test_a"
_C: Final = "tests/n.py::test_c"


@pytest.fixture(autouse=True)
def _no_destinations(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("CV_CONFORMANCE_REPORT_DIR", "GITHUB_STEP_SUMMARY"):
        monkeypatch.delenv(name, raising=False)


def _row(case: str, surface: str = "", plan: str = "") -> dict[str, Any]:
    return {"surface": surface or "-", "case": case, "plan": [p for p in plan.split(", ") if p]}


def _report(tmp_path: Path, name: str = "x-conformance", listed: str = _LIST) -> ConformanceReport:
    cases = tmp_path / f"{name}.txt"
    cases.write_text(listed, encoding="utf-8")
    columns = {"Surface": "surface", "Test": "case", "Plan": "plan", "Outcome": "status"}
    return ConformanceReport(name, "X rig (#1)", cases, columns, _row)


def _stats(**outcomes: list[str]) -> dict[str, list[Any]]:
    """What the terminal reporter holds: the reports of each outcome, by node id."""
    return {kind: [SimpleNamespace(nodeid=n) for n in ids] for kind, ids in outcomes.items()}


def _summarize(report: Any, key: Any, collected: set[str], **outcomes: list[str]) -> list[str]:
    """The lines a report's `pytest_terminal_summary` hook prints for a run that collected
    `collected` and recorded `outcomes`; the hook also writes whatever the environment names."""
    lines: list[str] = []
    reporter = SimpleNamespace(
        stats=_stats(**outcomes), section=lines.append, write_line=lines.append
    )
    config = cast(pytest.Config, SimpleNamespace(stash=pytest.Stash()))  # what the hook reads
    config.stash[key] = collected
    report.pytest_terminal_summary(reporter, config)
    return lines


def test_conformance_report_counts_a_case_once_per_outcome_whatever_its_parameters(
    tmp_path: Path,
) -> None:
    stats = _stats(
        passed=[f"{_A}[x]", f"{_A}[y]"],
        failed=[f"{_A}[z]"],
        skipped=["tests/other.py::test_q"],  # a module the list lacks
    )
    assert _report(tmp_path).outcomes(stats) == {_A: Counter(passed=2, failed=1)}


@pytest.mark.parametrize(
    ("counts", "status"),
    [
        (Counter(passed=2), "PASSED"),
        (Counter(passed=1, failed=1), "FAILED"),
        (Counter(error=1), "FAILED"),
        (Counter(xpassed=1), "FAILED"),
        (Counter(skipped=1), "NOT RUN"),
        (Counter(xfailed=1), "NOT RUN"),
        (Counter(), "NOT RUN"),
    ],
)
def test_conformance_report_status_of_a_listed_case_follows_its_outcomes(
    counts: Counter[str], status: str, tmp_path: Path
) -> None:
    [row, *_] = _report(tmp_path).matrix({_A: counts} if counts else {}, {_A})
    assert (row["case"], row["status"]) == (_A, status)


def test_conformance_report_matrix_lists_the_collected_modules_then_what_ran_unlisted(
    tmp_path: Path,
) -> None:
    ran = {"tests/m.py::test_new": Counter(passed=1), "tests/m.py::test_bad": Counter(failed=1)}
    rows = _report(tmp_path).matrix(ran, {_A})  # tests/n.py was not collected: its case is left out
    assert [(row["case"], row["status"], row["surface"]) for row in rows] == [
        (_A, "NOT RUN", "surface A"),
        ("tests/m.py::test_b", "NOT RUN", "surface B"),
        ("tests/m.py::test_bad", "FAILED", "-"),
        ("tests/m.py::test_new", "NEW", "-"),
    ]


def test_conformance_report_hooks_keep_each_reports_collected_cases_apart(tmp_path: Path) -> None:
    one = _report(tmp_path, "one-conformance")
    two = _report(tmp_path, "two-conformance", f"{_C} | surface C | plan 4\n")
    items = [SimpleNamespace(nodeid=f"{_A}[x]"), SimpleNamespace(nodeid=_C)]
    config = cast(pytest.Config, SimpleNamespace(stash=pytest.Stash()))
    for report in (one, two):
        report.pytest_collection_modifyitems(config, cast(list[pytest.Item], items))
    assert (config.stash[one.collected], config.stash[two.collected]) == ({_A, _C}, {_C})


def test_conformance_report_summary_prints_the_rows_and_writes_the_artifact_and_job_summary(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    out, summary = tmp_path / "not" / "yet", tmp_path / "summary.md"
    summary.write_text("an earlier step\n", encoding="utf-8")
    monkeypatch.setenv("CV_CONFORMANCE_REPORT_DIR", str(out))
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    report = _report(tmp_path)
    lines = _summarize(
        report, report.collected, {_A, _C}, passed=[f"{_A}[x]", f"{_A}[y]"], failed=[_C]
    )
    assert lines == [
        "X rig (#1): surface x case x outcome",
        "  PASSED  tests/m.py::test_a",
        " NOT RUN  tests/m.py::test_b",
        "::warning::X case NOT RUN: tests/m.py::test_b",
        "  FAILED  tests/n.py::test_c",
        "::warning::X case FAILED: tests/n.py::test_c",
    ]
    text = (out / "x-conformance.json").read_text("utf-8")
    rows = json.loads(text)
    assert text == json.dumps(rows, indent=2) + "\n"
    assert list(rows[0]) == ["surface", "case", "plan", "status", "passed"]
    table = [
        "### X rig (#1)",
        "",
        "| Surface | Test | Plan | Outcome | Counts |",
        "| --- | --- | --- | --- | --- |",
        "| surface A | `test_a` | plan 1, plan 2 | PASSED | passed 2 |",
        "| surface B | `test_b` | plan 3 | NOT RUN | - |",
        "| surface C | `test_c` | - | FAILED | failed 1 |",
        "",
    ]
    markdown = "\n".join(table)
    assert (out / "x-conformance.md").read_text("utf-8") == markdown
    assert summary.read_text("utf-8") == "an earlier step\n" + markdown


def test_conformance_report_registers_both_reports_to_record_before_deselection(
    request: pytest.FixtureRequest,
) -> None:
    """`tryfirst`, so the cases are recorded before `-m` or `-k` deselect any. E12-Q04's report
    gets its hooks from `conftest.py` and E29-Q02's is a plugin; pytest registers each once."""
    manager = request.config.pluginmanager

    def reports(hook: str) -> list[tuple[str, bool]]:
        impls = getattr(manager.hook, hook).get_hookimpls()
        owners = [(getattr(impl.function, "__self__", None), impl.tryfirst) for impl in impls]
        return sorted((o.name, first) for o, first in owners if isinstance(o, ConformanceReport))

    assert reports("pytest_collection_modifyitems") == [
        ("e12-q04-conformance", True),
        ("e29-q02-conformance", True),
    ]
    assert reports("pytest_terminal_summary") == [
        ("e12-q04-conformance", False),
        ("e29-q02-conformance", False),
    ]


def _e12_q04_conftest() -> Any:
    """E12-Q04's `conftest.py`, loaded apart from pytest's own copy so its hooks can be called."""
    path = Path(__file__).with_name("conftest.py")
    spec = importlib.util.spec_from_file_location("e12_q04_conftest", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_conformance_report_writes_each_real_report_under_its_own_name_and_columns(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("CV_CONFORMANCE_REPORT_DIR", str(tmp_path))
    e12, e29 = _e12_q04_conftest(), e29_q02_report.REPORT
    for report, key in ((e12, e12._COLLECTED), (e29, e29.collected)):
        case = report.expected_cases()[0]
        _summarize(report, key, {case}, passed=[case])
    stems = ("e12-q04-conformance", "e29-q02-conformance")
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(
        f"{stem}.{kind}" for stem in stems for kind in ("json", "md")
    )
    first = [json.loads((tmp_path / f"{stem}.json").read_text("utf-8"))[0] for stem in stems]
    assert [list(row) for row in first] == [
        ["surface", "case", "status", "passed"],
        ["surface", "case", "plan_cases", "status", "passed"],
    ]
    heads = [(tmp_path / f"{stem}.md").read_text("utf-8").splitlines()[2] for stem in stems]
    assert heads == [
        "| Surface | Case | Outcome | Counts |",
        "| Surface | Test | Plan cases | Outcome | Counts |",
    ]
