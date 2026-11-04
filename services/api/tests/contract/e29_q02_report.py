"""E29-Q02 (#1147): the conformance report of the OMS contract tests. Hooks only.

`e29_q02_cases.txt` lists, one test function per line, `module::test | surface | plan cases`: the
surface it exercises and the plan's cases (E29-TC-nnn, `docs/qa/e29-oms-test-plan.md`) it gives
evidence for. At the end of a run in which any listed test recorded an outcome, the matrix (surface
x case x outcome) is printed: a listed test that did not pass is `NOT RUN` or `FAILED` with a
`::warning::` line, so coverage that went missing shows in CI, and a test that ran unlisted is
`NEW`. `CV_CONFORMANCE_REPORT_DIR` also gets it as `e29-q02-conformance.json` and `.md`, and
`GITHUB_STEP_SUMMARY` the markdown.

Modelled on E12-Q04's (`conftest.py`), and independent of it. `conftest.py` registers this one by
re-exporting `pytest_configure`: `pytest_plugins` there is refused once pytest has configured,
which any run that does not name `tests/contract` has. `test_e29_q02_report.py` guards the rest.
"""

from __future__ import annotations

import json
import os
import re
from collections import Counter
from pathlib import Path
from typing import Any, Final, NamedTuple

import pytest

NAME: Final = "e29-q02-report"
_ROOT: Final = Path(__file__).resolve().parents[2]  # services/api: node ids are relative to it
EXPECTED: Final = Path(__file__).with_name("e29_q02_cases.txt")
PLAN_CASE: Final = re.compile(r"E29-TC-\d{3}")
_COLLECTED: Final = pytest.StashKey[set[str]]()
_OUTCOMES: Final = ("passed", "failed", "error", "skipped", "xfailed", "xpassed")


class Listed(NamedTuple):
    case: str  # `module::test`
    surface: str
    plan: tuple[str, ...]  # the plan's case ids


def expected_cases() -> list[Listed]:
    """One per line of `e29_q02_cases.txt`; `#` starts a comment."""
    rows = []
    for raw in EXPECTED.read_text("utf-8").splitlines():
        if line := raw.partition("#")[0].strip():
            case, surface, plan = (field.strip() for field in line.split("|"))
            rows.append(Listed(case, surface, tuple(p.strip() for p in plan.split(","))))
    return rows


_MODULES: Final = frozenset(row.case.partition("::")[0] for row in expected_cases())


def _case(nodeid: str) -> str | None:
    """`module::test` of an item of a listed module (its parameters dropped), else None."""
    module, _, name = nodeid.partition("::")
    return f"{module}::{name.partition('[')[0]}" if module in _MODULES else None


def _counts(stats: dict[str, list[Any]]) -> dict[str, Counter[str]]:
    """Each E29-Q02 case's outcomes in the terminal reporter's `stats`."""
    counts: dict[str, Counter[str]] = {}
    for outcome in _OUTCOMES:
        for report in stats.get(outcome, []):
            if case := _case(getattr(report, "nodeid", "")):
                counts.setdefault(case, Counter())[outcome] += 1
    return counts


def _matrix(counts: dict[str, Counter[str]], collected: set[str]) -> list[dict[str, Any]]:
    modules = {case.partition("::")[0] for case in collected}
    listed = [row for row in expected_cases() if row.case.partition("::")[0] in modules]
    known = {row.case for row in listed}
    unlisted = [Listed(case, case.partition("::")[0], ()) for case in sorted(set(counts) - known)]
    rows = []
    for row in [*listed, *unlisted]:
        got = counts.get(row.case, Counter())
        bad = got["failed"] + got["error"] + got["xpassed"]
        status = "FAILED" if bad else "PASSED" if got["passed"] else "NOT RUN"
        status = "NEW" if row.case not in known and status == "PASSED" else status
        rows.append({"surface": row.surface, "case": row.case, "plan_cases": list(row.plan),
                     "status": status, **{o: got[o] for o in _OUTCOMES if got[o]}})  # fmt: skip
    return rows


def _markdown(rows: list[dict[str, Any]]) -> str:
    head = ["| Surface | Test | Plan cases | Outcome | Counts |", "| --- | --- | --- | --- | --- |"]
    lines = []
    for row in rows:
        counts = ", ".join(f"{k} {v}" for k, v in row.items() if k in _OUTCOMES)
        test, plan = row["case"].partition("::")[2], ", ".join(row["plan_cases"])
        cells = [row["surface"], f"`{test}`", plan or "-", row["status"], counts or "-"]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(["### E29-Q02 OMS contract conformance (#1147)", "", *head, *lines, ""])


class Report:
    """The report's hooks, registered once per session by `pytest_configure`."""

    @pytest.hookimpl(tryfirst=True)
    def pytest_collection_modifyitems(
        self, config: pytest.Config, items: list[pytest.Item]
    ) -> None:
        """The E29-Q02 cases collected, before `-m` or `-k` deselect any."""
        config.stash[_COLLECTED] = {case for item in items if (case := _case(item.nodeid))}

    def pytest_terminal_summary(self, terminalreporter: Any, config: pytest.Config) -> None:
        """The matrix, once some E29-Q02 case recorded an outcome. A run that collected the cases
        and ran none (a lane whose markers deselect them, `--collect-only`) reports nothing."""
        counts = _counts(terminalreporter.stats)
        if not counts:
            return
        rows = _matrix(counts, config.stash.get(_COLLECTED, set()))
        terminalreporter.section(
            "E29-Q02 OMS contract conformance (#1147): surface x case x outcome"
        )
        for row in rows:
            terminalreporter.write_line(f"{row['status']:>8}  {row['case']}")
            if row["status"] in ("NOT RUN", "FAILED"):
                terminalreporter.write_line(
                    f"::warning::E29-Q02 case {row['status']}: {row['case']}"
                )
        if out := os.environ.get("CV_CONFORMANCE_REPORT_DIR"):
            folder = _ROOT / out
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "e29-q02-conformance.json").write_text(
                json.dumps(rows, indent=2) + "\n", "utf-8"
            )
            (folder / "e29-q02-conformance.md").write_text(_markdown(rows), encoding="utf-8")
        if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
            with Path(summary).open("a", encoding="utf-8") as fh:
                fh.write(_markdown(rows))


def pytest_configure(config: pytest.Config) -> None:
    """Registers the report, once; `conftest.py` re-exports this hook, which runs for a conftest
    loaded after configuration too."""
    if not config.pluginmanager.has_plugin(NAME):
        config.pluginmanager.register(Report(), NAME)
