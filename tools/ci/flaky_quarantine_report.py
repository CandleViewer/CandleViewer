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
from pathlib import Path

TICKET_RE = re.compile(r"ticket:\s*([A-Z][A-Z0-9]*-\d+)")
PYTEST_FLAKY_RE = re.compile(r"@pytest\.mark\.flaky")
VITEST_FLAKY_RE = re.compile(r"\b(?:it|test|describe)\.flaky\s*\(")


@dataclass(frozen=True)
class QuarantineEntry:
    path: str
    line: int
    ticket: str | None

    @property
    def referenced(self) -> bool:
        return self.ticket is not None


@dataclass(frozen=True)
class QuarantineReport:
    entries: tuple[QuarantineEntry, ...] = field(default_factory=tuple)

    @property
    def unreferenced(self) -> tuple[QuarantineEntry, ...]:
        return tuple(e for e in self.entries if not e.referenced)

    def to_dict(self) -> dict:
        return {
            "quarantined": [
                {"path": e.path, "line": e.line, "ticket": e.ticket} for e in self.entries
            ],
            "unreferenced_count": len(self.unreferenced),
        }


def _find_ticket_near(lines: list[str], idx: int) -> str | None:
    for probe in (lines[idx], lines[idx - 1] if idx > 0 else ""):
        m = TICKET_RE.search(probe)
        if m:
            return m.group(1)
    return None


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
        return [i + 1 for i, line in enumerate(source.splitlines()) if PYTEST_FLAKY_RE.search(line)]
    return [
        t.start[0]
        for i, t in enumerate(tokens)
        if t.type == tokenize.OP
        and t.string == "@"
        and [n.string for n in tokens[i + 1 : i + 6]] == ["pytest", ".", "mark", ".", "flaky"]
    ]


def scan_pytest_file(path: Path, repo_root: Path) -> list[QuarantineEntry]:
    source = path.read_text(encoding="utf-8", errors="ignore")
    lines = source.splitlines()
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
