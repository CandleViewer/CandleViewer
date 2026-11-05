"""The conformance report E12-Q04 (#420) and E29-Q02 (#1147) share.

A report is a `ConformanceReport`: a committed case list (one test function per line, `module::test`
first and any `|`-separated fields after it as the report's `row` reads them), the report's name and
how a case becomes a row of the matrix (surface x case x outcome). It is a pytest plugin object. Its
hooks record the cases a run collected, before `-m` or `-k` deselect any, and print the matrix once
some listed case recorded an outcome; a run that collected the cases and ran none (a lane whose
markers deselect them, `--collect-only`) reports nothing. A listed case that did not pass is
`NOT RUN` or `FAILED` with a `::warning::` line, so coverage that went missing shows in CI; a case
that ran without being listed is `NEW`. When `CV_CONFORMANCE_REPORT_DIR` is set the matrix is also
written there as `<name>.json` and `.md`, and when `GITHUB_STEP_SUMMARY` is set the markdown is
appended to the job's summary. `test_conformance_report.py` guards the writer.
"""

from __future__ import annotations

import json
import os
from collections import Counter
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, Final

import pytest

_OUTCOMES: Final = ("passed", "failed", "error", "skipped", "xfailed", "xpassed")
_ROOT: Final = Path(__file__).resolve().parents[2]  # services/api: node ids are relative to it


def read_cases(path: Path) -> list[list[str]]:
    """The `|`-separated fields of each line of a committed case list, the first being
    `module::test`; `#` starts a comment and blank lines are skipped."""
    lines = (line.partition("#")[0].strip() for line in path.read_text("utf-8").splitlines())
    return [[field.strip() for field in line.split("|")] for line in lines if line]


def _cell(member: str, value: Any) -> str:
    """A row member as a table cell: the test's name for `case`, a list joined, `-` when empty."""
    if member == "case":
        return f"`{value.partition('::')[2]}`"
    return (", ".join(value) or "-") if isinstance(value, list) else str(value)


class ConformanceReport:
    """One conformance report: register the instance as a plugin, or take its two hooks.

    `row(case, *fields)` is the members of a case's row before its `status`: `surface`, `case`,
    then whatever else the report shows. It gets a listed case's fields, or the case alone when the
    run has one the list lacks. `columns` maps the markdown table's headers to the row members
    they show (the `case` as the test's name), `Counts` coming last; the title heads the table and
    the terminal section, and the name stems the artifact's files.
    """

    def __init__(
        self,
        name: str,
        title: str,
        cases: Path,
        columns: Mapping[str, str],
        row: Callable[..., dict[str, Any]],
    ) -> None:
        self.name, self.title, self.columns, self.row = name, title, columns, row
        self.listed = read_cases(cases)
        self.modules = frozenset(fields[0].partition("::")[0] for fields in self.listed)
        self.collected = pytest.StashKey[set[str]]()

    @property
    def ticket(self) -> str:
        """The ticket the warnings name: `E12-Q04` of `e12-q04-conformance`."""
        return self.name.removesuffix("-conformance").upper()

    def expected_cases(self) -> list[str]:
        """`module::test` per line of the case list."""
        return [fields[0] for fields in self.listed]

    def case_of(self, nodeid: str) -> str | None:
        """`module::test` of an item of a listed module (its parameters dropped), else None."""
        module, _, name = nodeid.partition("::")
        return f"{module}::{name.partition('[')[0]}" if module in self.modules else None

    def outcomes(self, stats: dict[str, list[Any]]) -> dict[str, Counter[str]]:
        """Each case's outcomes in the terminal reporter's `stats`, for the listed modules."""
        counts: dict[str, Counter[str]] = {}
        for outcome in _OUTCOMES:
            for report in stats.get(outcome, []):
                if case := self.case_of(getattr(report, "nodeid", "")):
                    counts.setdefault(case, Counter())[outcome] += 1
        return counts

    def matrix(self, counts: dict[str, Counter[str]], collected: set[str]) -> list[dict[str, Any]]:
        """A row per listed case of a module the run collected, then per case that ran unlisted."""
        modules = {case.partition("::")[0] for case in collected}
        listed = [fields for fields in self.listed if fields[0].partition("::")[0] in modules]
        known = {fields[0] for fields in listed}
        described = [self.row(*fields) for fields in listed]
        described += [self.row(case) for case in sorted(set(counts) - known)]
        rows = []
        for row in described:
            got = counts.get(row["case"], Counter())
            bad = got["failed"] + got["error"] + got["xpassed"]
            status = "FAILED" if bad else "PASSED" if got["passed"] else "NOT RUN"
            status = "NEW" if row["case"] not in known and status == "PASSED" else status
            rows.append({**row, "status": status, **{o: got[o] for o in _OUTCOMES if got[o]}})
        return rows

    def markdown(self, rows: list[dict[str, Any]]) -> str:
        head = [*self.columns, "Counts"]
        lines = ["| " + " | ".join(head) + " |", "| " + " | ".join("---" for _ in head) + " |"]
        for row in rows:
            counts = ", ".join(f"{k} {v}" for k, v in row.items() if k in _OUTCOMES)
            cells = [_cell(member, row[member]) for member in self.columns.values()]
            lines.append("| " + " | ".join([*cells, counts or "-"]) + " |")
        return "\n".join([f"### {self.title}", "", *lines, ""])

    def write(self, rows: list[dict[str, Any]]) -> None:
        """The matrix to `CV_CONFORMANCE_REPORT_DIR` (JSON and markdown) and the markdown to
        `GITHUB_STEP_SUMMARY`, each when set."""
        if out := os.environ.get("CV_CONFORMANCE_REPORT_DIR"):
            folder = _ROOT / out
            folder.mkdir(parents=True, exist_ok=True)
            report = json.dumps(rows, indent=2) + "\n"
            (folder / f"{self.name}.json").write_text(report, encoding="utf-8")
            (folder / f"{self.name}.md").write_text(self.markdown(rows), encoding="utf-8")
        if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
            with Path(summary).open("a", encoding="utf-8") as fh:
                fh.write(self.markdown(rows))

    @pytest.hookimpl(tryfirst=True)
    def pytest_collection_modifyitems(
        self, config: pytest.Config, items: list[pytest.Item]
    ) -> None:
        """The cases of the listed modules collected, before `-m` or `-k` deselect any."""
        config.stash[self.collected] = {
            case for item in items if (case := self.case_of(item.nodeid))
        }

    def pytest_terminal_summary(self, terminalreporter: Any, config: pytest.Config) -> None:
        """The matrix, once some listed case recorded an outcome."""
        counts = self.outcomes(terminalreporter.stats)
        if not counts:
            return
        rows = self.matrix(counts, config.stash.get(self.collected, set()))
        terminalreporter.section(f"{self.title}: surface x case x outcome")
        for row in rows:
            terminalreporter.write_line(f"{row['status']:>8}  {row['case']}")
            if row["status"] in ("NOT RUN", "FAILED"):
                warning = f"{self.ticket} case {row['status']}: {row['case']}"
                terminalreporter.write_line(f"::warning::{warning}")
        self.write(rows)
