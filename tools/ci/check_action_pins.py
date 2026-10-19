#!/usr/bin/env python3
"""SR-132: verify every GitHub Actions workflow references actions by a
40-hex-character commit SHA (never a floating tag/branch) and never uses the
``pull_request_target`` trigger.

#3580: run without paths (the ``pin-check`` step), it checks every ``*.yml`` /
``*.yaml`` file under ``.github/workflows/**`` and ``.github/actions/**`` of
``--root`` (default ``.``), then compares ``.github/actions-pins.md`` with their
``uses:`` lines, failing closed on a table or a ``uses:`` line it cannot read
(CI-PIN-001 to CI-PIN-009: the rule is that file's "Verification" paragraph,
each code's recipe ``docs/ci-runbook.md`` §4). Run with paths, it applies the
SR-132 checks to those files alone.

Exit codes: 0 clean, 1 violations found, 2 internal error (bad path / no
workflows found when a specific path was requested).

CI-GATE-003 is the resolver error code raised when this check fails inside
the ``ci-required`` gate job (see ``.github/workflows/pr.yml``).

Stdlib only — this must run before any package manager is bootstrapped.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

# `uses:` lines referencing local paths (`./`) are exempt from SHA pinning —
# they aren't fetched from the marketplace. `docker://` refs must instead
# carry an `@sha256:<digest>` pin (SR-132) — image tags float just like
# branches do.
USES_RE = re.compile(r"^\s*(?:-\s*)?uses:\s*(?P<ref>\S+)\s*(?:#\s*(?P<tag>\S*).*)?$")
SHA_SUFFIX_RE = re.compile(r"@([0-9a-f]{40})$")
DOCKER_DIGEST_RE = re.compile(r"@sha256:[0-9a-f]{64}$")
COMMENT_LINE_RE = re.compile(r"^\s*#")
PULL_REQUEST_TARGET_WORD_RE = re.compile(r"\bpull_request_target\b")
# Top-level `on:` key (workflow trigger map). May be followed inline by a
# scalar/list value on the same line, or by an indented block on following
# lines — both forms must be scanned for `pull_request_target` (SR-132).
ON_KEY_RE = re.compile(r"^on:\s*(?P<inline>.*)$")
INDENT_RE = re.compile(r"^(\s*)\S")
# #3580: the ledger and the trees whose `uses:` lines it records, from the repository root.
LEDGER_PATH = Path(".github/actions-pins.md")
WORKFLOWS_DIR = Path(".github/workflows")
ACTIONS_DIR = Path(".github/actions")
LOCAL_TREES = (f"{WORKFLOWS_DIR.as_posix()}/", f"{ACTIONS_DIR.as_posix()}/")  # `./` refs scanned
# The columns the ledger check reads, by header title; any other column (Last bumped) is prose.
LEDGER_COLUMNS = ("Action", "Pinned SHA", "Upstream tag", "Used in")
CODE_CELL_RE = re.compile(r"^`([^`\s]+)`$")
SEPARATOR_CELL_RE = re.compile(r"^:?-{3,}:?$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
# A `uses` mapping key on a line USES_RE does not read is CI-PIN-009 (fail closed): in block or
# flow position (after `{`, `[`, `,` or `?`), behind `-`/`?` indicators, anchors or tags, quoted,
# with a space before the colon or its value on the next line; also an alias key, which may name
# a `uses` anchor, and a double-quoted key with an escape, which may spell `uses`.
USES_KEY_RE = re.compile(
    r"""(?:^\s*|[\[{,?]\s*)(?:(?:[-?]|[&!]\S*)\s+)*"""
    r"""(?:["']?uses["']?\s*(?::|$)|\*[\w-]+\s*:|"[^"]*\\[^"]*"\s*:)"""
)


@dataclass(frozen=True)
class Violation:
    path: Path
    line_no: int
    line: str
    reason: str

    def format(self) -> str:
        return f"{self.path}:{self.line_no}: {self.reason}: {self.line.strip()}"


@dataclass(frozen=True)
class PinUse:
    """A ``uses:`` line naming ``action`` at ``ref`` (a SHA when pinned); ``tag`` is its comment."""

    action: str
    ref: str
    tag: str
    name: str  # the file as "Used in" names it
    where: str  # path:line from the repository root


@dataclass(frozen=True)
class LedgerRow:
    action: str
    sha: str
    tag: str
    used_in: tuple[str, ...]
    line_no: int


class LedgerError(ValueError):
    """The ledger or its table cannot be read (CI-PIN-001)."""

    def __init__(self, reason: str, line_no: int | None = None) -> None:
        super().__init__(reason)
        self.line_no = line_no


def _iter_workflow_files(root: Path) -> list[Path]:
    if root.is_file():
        return [root]
    found: list[Path] = []
    for pattern in ("*.yml", "*.yaml"):
        found.extend(sorted(root.rglob(pattern)))
    return found


def _on_block_line_nos(lines: list[str]) -> set[int]:
    """Return 1-based line numbers that belong to the workflow's top-level
    ``on:`` trigger declaration — the inline value line itself (if any) plus
    any indented block lines that follow it. Handles both:

        on: pull_request_target
        on: [push, pull_request_target]

    and the block-mapping form:

        on:
          pull_request_target:
    """
    result: set[int] = set()
    in_block = False
    for idx, line in enumerate(lines):
        line_no = idx + 1
        if COMMENT_LINE_RE.match(line):
            continue
        m = ON_KEY_RE.match(line)
        if m:
            result.add(line_no)
            in_block = bool(not m.group("inline").strip())
            continue
        if in_block:
            indent_m = INDENT_RE.match(line)
            if indent_m and len(indent_m.group(1)) > 0:
                result.add(line_no)
                continue
            in_block = False
    return result


def check_file(path: Path) -> list[Violation]:
    violations: list[Violation] = []
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    on_line_nos = _on_block_line_nos(lines)
    for line_no, line in enumerate(lines, start=1):
        if COMMENT_LINE_RE.match(line):
            continue

        if line_no in on_line_nos and PULL_REQUEST_TARGET_WORD_RE.search(line):
            violations.append(
                Violation(
                    path,
                    line_no,
                    line,
                    "pull_request_target is prohibited (SR-132)",
                )
            )

        m = USES_RE.match(line)
        if not m:
            continue
        ref = m.group("ref").strip('"').strip("'")
        if ref.startswith("./"):
            continue
        if ref.startswith("docker://"):
            if not DOCKER_DIGEST_RE.search(ref):
                violations.append(
                    Violation(
                        path,
                        line_no,
                        line,
                        "unpinned docker:// reference (requires @sha256:<digest>)",
                    )
                )
            continue
        if "@" not in ref:
            violations.append(
                Violation(path, line_no, line, "unpinned action reference (no @ref)")
            )
            continue
        if not SHA_SUFFIX_RE.search(ref):
            violations.append(
                Violation(
                    path,
                    line_no,
                    line,
                    "unpinned action reference (not a 40-hex commit SHA)",
                )
            )
    return violations


def check_paths(paths: list[Path]) -> list[Violation]:
    violations: list[Violation] = []
    for root in paths:
        for wf in _iter_workflow_files(root):
            violations.extend(check_file(wf))
    return violations


def collect_uses(path: Path, root: Path) -> tuple[list[PinUse], list[str]]:
    """The ``uses:`` lines of ``path`` the ledger records (all but ``./`` and ``docker://``), and a
    CI-PIN-009 finding for each line naming an action whose pin this check cannot read."""
    rel = path.relative_to(root)
    name = rel.relative_to(WORKFLOWS_DIR) if rel.is_relative_to(WORKFLOWS_DIR) else rel
    uses: list[PinUse] = []
    unread: list[str] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if COMMENT_LINE_RE.match(line):
            continue
        where = f"{rel.as_posix()}:{line_no}"
        m = USES_RE.match(line)
        if m is None:
            if USES_KEY_RE.search(line):
                unread.append(f"CI-PIN-009 {where}: cannot read this uses: key: {line.strip()}")
            continue
        ref = m.group("ref").strip('"').strip("'")
        if ref.startswith("./") and not ref[2:].startswith(LOCAL_TREES):
            unread.append(
                f"CI-PIN-009 {where}: {ref} is a local action outside {ACTIONS_DIR.as_posix()}/, "
                "whose uses: lines are not checked"
            )
        if ref.startswith(("./", "docker://")):
            continue
        if ref.count("@") > 1:  # GitHub reads owner/repo[/path]@ref; CI-GATE-003 the last @ only
            unread.append(f"CI-PIN-009 {where}: cannot read {ref}, which has more than one @")
            continue
        action, _, version = ref.partition("@")
        uses.append(PinUse(action, version, m.group("tag") or "", name.as_posix(), where))
    return uses, unread


def _cells(line_no: int, line: str) -> list[str]:
    text = line.strip()
    if len(text) < 2 or not text.endswith("|"):
        raise LedgerError("the row does not end with |", line_no)
    return [cell.strip() for cell in text[1:-1].split("|")]


def _code(cell: str, line_no: int) -> str:
    m = CODE_CELL_RE.match(cell)
    if m is None:
        raise LedgerError(f"{cell!r} is not one `value`", line_no)
    return m.group(1)


def _row(line_no: int, line: str, titles: list[str]) -> LedgerRow:
    cells = _cells(line_no, line)
    if len(cells) != len(titles):
        raise LedgerError(f"the row has {len(cells)} cells, the header {len(titles)}", line_no)
    action, sha, tag = (_code(cells[titles.index(t)], line_no) for t in LEDGER_COLUMNS[:3])
    used_in = tuple(_code(c.strip(), line_no) for c in cells[titles.index("Used in")].split(","))
    if not SHA_RE.match(sha):
        raise LedgerError(f"{sha} is not a 40-hex commit SHA", line_no)
    if len(set(used_in)) != len(used_in):
        raise LedgerError("'Used in' lists a file twice", line_no)
    return LedgerRow(action, sha, tag, used_in, line_no)


def parse_ledger(path: Path) -> list[LedgerRow]:
    """Read the ledger's one table; a shape this cannot read raises LedgerError (fail closed)."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise LedgerError(f"cannot read it ({exc.__class__.__name__})") from None
    table = [(no, line) for no, line in enumerate(lines, start=1) if line.lstrip().startswith("|")]
    if len(table) < 2:
        raise LedgerError("has no table (a header row, then a --- separator row)")
    for offset, (line_no, _) in enumerate(table):
        if line_no != table[0][0] + offset:
            raise LedgerError("a second table starts here", line_no)
    end = table[-1][0]  # GitHub reads a non-blank line right after the table as one more row
    if end < len(lines) and lines[end].strip():
        raise LedgerError("the table must end at a blank line", end + 1)
    titles = _cells(*table[0])
    wrong = [title for title in LEDGER_COLUMNS if titles.count(title) != 1]
    if wrong:
        raise LedgerError(f"the header needs exactly one {', '.join(wrong)} column", table[0][0])
    separator = _cells(*table[1])
    if len(separator) != len(titles) or not all(map(SEPARATOR_CELL_RE.match, separator)):
        raise LedgerError("the header is not followed by a --- separator row", table[1][0])
    return [_row(line_no, line, titles) for line_no, line in table[2:]]


def check_ledger(root: Path, files: list[Path]) -> list[str]:
    """Compare the ledger with the ``uses:`` lines of ``files`` (CI-PIN-*), naming both sides."""
    ledger = LEDGER_PATH.as_posix()
    collected = [collect_uses(path, root) for path in files]
    unread = [finding for _, found in collected for finding in found]
    try:
        rows = parse_ledger(root / LEDGER_PATH)
    except LedgerError as exc:
        where = ledger if exc.line_no is None else f"{ledger}:{exc.line_no}"
        return [*unread, f"CI-PIN-001 {where}: {exc}"]
    by_action: dict[str, list[LedgerRow]] = {}
    for row in rows:
        by_action.setdefault(row.action, []).append(row)
    findings = unread + [
        f"CI-PIN-003 {', '.join(f'{ledger}:{row.line_no}' for row in same)}: {action} has "
        f"{len(same)} rows; keep one"
        for action, same in by_action.items()
        if len(same) > 1
    ]
    users: dict[str, dict[str, str]] = {}  # action -> {"Used in" name: its first file:line}
    for use in (use for uses, _ in collected for use in uses):
        users.setdefault(use.action, {}).setdefault(use.name, use.where)
        same = by_action.get(use.action, [])
        if not SHA_RE.match(use.ref) or len(same) > 1:
            continue  # CI-GATE-003 names an unpinned line; CI-PIN-003 the duplicate rows
        if not same:
            findings.append(
                f"CI-PIN-002 {use.where}: {use.action}@{use.ref} has no row in {ledger}"
            )
            continue
        row = same[0]
        if use.ref != row.sha:
            findings.append(
                f"CI-PIN-004 {use.where}: {use.action} is pinned at {use.ref}; "
                f"{ledger}:{row.line_no} has {row.sha}"
            )
        if use.tag != row.tag:
            tagged = f"is tagged {use.tag}" if use.tag else "has no `# <tag>` comment"
            findings.append(
                f"CI-PIN-005 {use.where}: {use.action} {tagged}; "
                f"{ledger}:{row.line_no} has {row.tag}"
            )
    for row in rows:
        used = users.get(row.action, {})
        if len(by_action[row.action]) > 1:
            continue
        if not used:
            findings.append(f"CI-PIN-006 {ledger}:{row.line_no}: no uses: line names {row.action}")
            continue
        findings.extend(
            f"CI-PIN-007 {where}: uses {row.action}; {ledger}:{row.line_no} 'Used in' does not "
            f"list {name}"
            for name, where in used.items()
            if name not in row.used_in
        )
        findings.extend(
            f"CI-PIN-008 {ledger}:{row.line_no}: 'Used in' lists {name}, which does not use "
            f"{row.action}"
            for name in row.used_in
            if name not in used
        )
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "paths",
        nargs="*",
        help="Workflow file(s) or directory to check for SR-132 alone (default: the repository "
        "run: .github/workflows/** and .github/actions/** under --root, then the ledger)",
    )
    parser.add_argument(
        "--root", type=Path, help="Repository root of the run without paths (default: .)"
    )
    args = parser.parse_args(argv)
    if args.paths and args.root is not None:
        print("error: --root is for the run without paths", file=sys.stderr)
        return 2

    root = Path(".") if args.root is None else args.root
    resolved = [Path(p) for p in args.paths] or [root / WORKFLOWS_DIR]
    for p in resolved:
        if not p.exists():
            print(f"error: path does not exist: {p}", file=sys.stderr)
            return 2

    findings: list[str] = []
    if args.paths:
        violations = check_paths(resolved)
    else:
        files = _iter_workflow_files(root / WORKFLOWS_DIR)
        if (root / ACTIONS_DIR).is_dir():
            files += _iter_workflow_files(root / ACTIONS_DIR)
        violations = [v for path in files for v in check_file(path)]
        findings = check_ledger(root, files)
    if violations:
        print("CI-GATE-003: unpinned or unsafe action reference(s) found:", file=sys.stderr)
        for v in violations:
            print(f"  {v.format()}", file=sys.stderr)
    if findings:
        print(f"{LEDGER_PATH.as_posix()} disagrees with the uses: lines:", file=sys.stderr)
        for finding in findings:
            print(f"  {finding}", file=sys.stderr)
    if violations or findings:
        return 1

    ledger = "" if args.paths else f"; {LEDGER_PATH.as_posix()} matches every uses: line"
    print(f"check_action_pins: OK — all actions SHA-pinned, no pull_request_target{ledger}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
