#!/usr/bin/env python3
"""E02-T10: flaky-test quarantine report generator (C-9.3).

Scans pytest test files for `@pytest.mark.flaky` decorators (read as tokens, so a
marker inside a string literal or a comment is not one) and Vitest test
files for a `.flaky` tag convention (`it.flaky("...")` / `describe.flaky(...)`,
mirroring Vitest's own `.skip`/`.only` modifier style), and requires each one
to carry a ticket reference on the same or the immediately preceding line
(e.g. `# ticket: OF-42` or `// ticket: OF-42`). An unreferenced `@flaky`
marker is a hard failure per C-9.3 ("gets a P1 ticket"); referenced markers
are non-blocking and listed in the quarantine report.

E49-Q01 (#1335, BQ-5): Playwright specs (`*.spec.ts`, `*.real.ts`) quarantine a test with the
`@flaky` title tag, which the configs' `flaky-nightly` project selects. The same `ticket:` and
`quarantined: YYYY-MM-DD` markers apply, plus an `owner: <login>` marker; `playwright_problems`
names a tag with no ticket, owner or start date, or one past C-9.3's ten working days
(CI-E2E-007, read by `tools/qa/ga_pack_health.py`).

Exit codes: 0 clean report written, 1 an unreferenced flaky marker was found,
2 internal error.

Stdlib only.
"""

from __future__ import annotations

import argparse
import io
import json
import re
import sys
import tokenize
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

TICKET_RE = re.compile(r"ticket:\s*([A-Z][A-Z0-9]*-\d+)")
PYTEST_FLAKY_RE = re.compile(r"@pytest\.mark\.flaky")
VITEST_FLAKY_RE = re.compile(r"\b(?:it|test|describe)\.flaky\s*\(")
#: A Playwright title tag: `test("... @flaky", ...)`, `test.describe("... @flaky", ...)`.
PLAYWRIGHT_FLAKY_RE = re.compile(
    r"""\b(?:test|it)(?:\.\w+)*\s*\(\s*(["'`])(?:(?!\1).)*@flaky(?![\w-])"""
)
OWNER_RE = re.compile(r"owner:\s*@?([A-Za-z0-9](?:[A-Za-z0-9-]{0,38}))")
QUARANTINED_RE = re.compile(r"quarantined:\s*(\d{4}-\d{2}-\d{2})")
#: C-9.3: a quarantined test is fixed or deleted within ten working days.
QUARANTINE_WORKING_DAYS = 10


@dataclass(frozen=True)
class QuarantineEntry:
    path: str
    line: int
    ticket: str | None
    owner: str | None = None
    quarantined: date | None = None
    playwright: bool = False

    @property
    def referenced(self) -> bool:
        return self.ticket is not None


@dataclass(frozen=True)
class QuarantineReport:
    entries: tuple[QuarantineEntry, ...] = field(default_factory=tuple)

    @property
    def unreferenced(self) -> tuple[QuarantineEntry, ...]:
        return tuple(e for e in self.entries if not e.referenced)

    def to_dict(self) -> dict[str, object]:
        return {
            "quarantined": [
                {"path": e.path, "line": e.line, "ticket": e.ticket}
                | ({"owner": e.owner, "since": _iso(e.quarantined)} if e.playwright else {})
                for e in self.entries
            ],
            "unreferenced_count": len(self.unreferenced),
        }


def _iso(day: date | None) -> str | None:
    return day.isoformat() if day else None


def _find_near(lines: list[str], idx: int, pattern: re.Pattern[str]) -> str | None:
    for probe in (lines[idx], lines[idx - 1] if idx > 0 else ""):
        m = pattern.search(probe)
        if m:
            return m.group(1)
    return None


def _find_ticket_near(lines: list[str], idx: int) -> str | None:
    return _find_near(lines, idx, TICKET_RE)


def _flaky_decorator_lines(source: str) -> list[int]:
    """The 1-based lines of `@pytest.mark.flaky` decorators, read as tokens, so a marker inside
    a string literal or a comment (a test's fixture text, a docstring) is never counted. A file
    that does not tokenize falls back to the line scan, so a marker is never missed."""
    skip = {tokenize.NL, tokenize.NEWLINE, tokenize.COMMENT, tokenize.INDENT, tokenize.DEDENT}
    try:
        tokens = [
            t for t in tokenize.generate_tokens(io.StringIO(source).readline) if t.type not in skip
        ]
    except (tokenize.TokenError, SyntaxError):
        return [i + 1 for i, line in enumerate(source.split("\n")) if PYTEST_FLAKY_RE.search(line)]
    return [
        t.start[0]
        for i, t in enumerate(tokens)
        if t.type == tokenize.OP
        and t.string == "@"
        and [n.string for n in tokens[i + 1 : i + 6]] == ["pytest", ".", "mark", ".", "flaky"]
    ]


def scan_pytest_file(path: Path, repo_root: Path) -> list[QuarantineEntry]:
    source = path.read_text(encoding="utf-8", errors="ignore")
    # Lines split as the tokenizer splits them: `splitlines()` also breaks at a form feed or a
    # U+2028, which would shift the ticket probe off the decorator's line.
    lines = source.split("\n")
    return [
        QuarantineEntry(
            path=str(path.relative_to(repo_root)).replace("\\", "/"),
            line=line,
            ticket=_find_ticket_near(lines, line - 1),
        )
        for line in _flaky_decorator_lines(source)
    ]


def scan_vitest_file(path: Path, repo_root: Path) -> list[QuarantineEntry]:
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    entries = []
    for i, line in enumerate(lines):
        if VITEST_FLAKY_RE.search(line):
            entries.append(
                QuarantineEntry(
                    path=str(path.relative_to(repo_root)).replace("\\", "/"),
                    line=i + 1,
                    ticket=_find_ticket_near(lines, i),
                )
            )
    return entries


def scan_playwright_file(path: Path, repo_root: Path) -> list[QuarantineEntry]:
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    entries = []
    for i, line in enumerate(lines):
        if PLAYWRIGHT_FLAKY_RE.search(line):
            since = _find_near(lines, i, QUARANTINED_RE)
            try:
                started = date.fromisoformat(since) if since else None
            except ValueError:
                started = None
            entries.append(
                QuarantineEntry(
                    path=str(path.relative_to(repo_root)).replace("\\", "/"),
                    line=i + 1,
                    ticket=_find_ticket_near(lines, i),
                    owner=_find_near(lines, i, OWNER_RE),
                    quarantined=started,
                    playwright=True,
                )
            )
    return entries


def working_days_between(start: date, end: date) -> int:
    """Mon-Fri days after `start`, up to and including `end` (no holiday calendar: C-9.3 names
    none), as tests/toolchain/pack.py counts them."""
    days, cursor = 0, start
    while cursor < end:
        cursor += timedelta(days=1)
        days += cursor.weekday() < 5
    return days


def playwright_problems(report: QuarantineReport, today: date) -> list[str]:
    """CI-E2E-007: each `@flaky` Playwright tag with no ticket, owner or start date, or quarantined
    for more than C-9.3's ten working days."""
    problems = []
    for e in (e for e in report.entries if e.playwright):
        where = f"{e.path}:{e.line}"
        fields = {"ticket": e.ticket, "owner": e.owner, "quarantined": e.quarantined}
        missing = [f"`{name}:`" for name, value in fields.items() if value is None]
        if missing:
            problems.append(f"{where} `@flaky` test has no {', '.join(missing)} marker")
        elif e.quarantined is not None:
            age = working_days_between(e.quarantined, today)
            if age > QUARANTINE_WORKING_DAYS:
                problems.append(
                    f"{where} quarantined since {e.quarantined.isoformat()} ({age} working days,"
                    f" over {QUARANTINE_WORKING_DAYS}), ticket {e.ticket}, owner @{e.owner}"
                )
    return problems


def build_report(repo_root: Path) -> QuarantineReport:
    entries: list[QuarantineEntry] = []
    for py_file in repo_root.rglob("test_*.py"):
        if any(part in {".venv", "node_modules", "__pycache__"} for part in py_file.parts):
            continue
        entries.extend(scan_pytest_file(py_file, repo_root))
    for ts_file in list(repo_root.rglob("*.test.ts")) + list(repo_root.rglob("*.test.tsx")) + list(
        repo_root.rglob("*.test.mjs")
    ):
        if any(part in {"node_modules", "dist"} for part in ts_file.parts):
            continue
        entries.extend(scan_vitest_file(ts_file, repo_root))
    for spec in list(repo_root.rglob("*.spec.ts")) + list(repo_root.rglob("*.real.ts")):
        if any(part in {"node_modules", "dist"} for part in spec.parts):
            continue
        entries.extend(scan_playwright_file(spec, repo_root))
    return QuarantineReport(entries=tuple(entries))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--out", default="reports/flaky-quarantine.json")
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    report = build_report(repo_root)

    out_path = repo_root / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report.to_dict(), indent=2) + "\n", encoding="utf-8")

    print(f"flaky-quarantine: {len(report.entries)} quarantined test(s), report at {args.out}")
    if report.unreferenced:
        print(
            f"flaky-quarantine: FAIL -- {len(report.unreferenced)} @flaky marker(s) with no "
            "ticket reference (C-9.3 requires a linked P1 ticket):",
            file=sys.stderr,
        )
        for e in report.unreferenced:
            print(f"  - {e.path}:{e.line}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
