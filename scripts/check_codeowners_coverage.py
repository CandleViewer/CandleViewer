#!/usr/bin/env python3
"""GOV-001: verify every tracked path has a deliberate CODEOWNERS owner
(CONSTITUTION.md C-8.1, C-10.1).

Implements GitHub's CODEOWNERS matching semantics (gitignore-style patterns,
last matching rule wins, `/`-anchoring, directory patterns) and reports, for
every path from `git ls-files`, the winning rule and its owners.

Fails (exit 1) when:
  * a path's winning rule is the catch-all `*` and the path is not in the
    allowlist (scripts/codeowners-allowlist.txt);
  * a rule matches no tracked path (dead rule) and is not marked `# future:`;
  * a rule names an owner not declared in the file's team header block.

Exit codes: 0 clean, 1 violations found, 2 internal error.
Stdlib only.
"""

from __future__ import annotations

import argparse
import fnmatch
import functools
import json
import os
import re
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TextIO

CODEOWNERS_PATH = ".github/CODEOWNERS"
ALLOWLIST_PATH = "scripts/codeowners-allowlist.txt"
TEAM_HEADER_RE = re.compile(r"^#\s+(@[\w./-]+)")
FUTURE_MARKER = "# future:"


class InternalError(Exception):
    """Raised for unexpected/unreadable-repo conditions (exit 2)."""


@dataclass(frozen=True)
class Rule:
    line_no: int
    pattern: str
    owners: tuple[str, ...]
    is_future: bool

    @property
    def is_catch_all(self) -> bool:
        return self.pattern == "*"


@dataclass
class MatchResult:
    path: str
    rule: Rule | None


def git_tracked_files(repo_root: str) -> list[str]:
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in result.stdout.splitlines() if line]


def parse_codeowners(repo_root: str) -> tuple[list[Rule], set[str]]:
    """Parse CODEOWNERS into ordered rules plus the declared-team set.

    The declared-team set comes *only* from `#`-prefixed comment lines
    matching `#   @name - ...` (this repo documents teams and individual
    owners of last resort that way, e.g. `#   @CandleViewer/architecture -
    ...`). Owners used directly on a rule line are deliberately NOT
    auto-declared: that would make the "owner not in the declared team list"
    check a no-op, since every owner appears on at least one rule by
    definition. A rule owner must be named in the header comment block to
    count as declared.
    """
    path = os.path.join(repo_root, CODEOWNERS_PATH)
    try:
        with open(path, encoding="utf-8") as fh:
            lines = fh.readlines()
    except OSError as exc:
        raise InternalError(f"cannot read {CODEOWNERS_PATH}: {exc}") from exc

    declared: set[str] = set()
    rules: list[Rule] = []
    pending_future = False

    for lineno, raw in enumerate(lines, start=1):
        line = raw.rstrip("\n")
        stripped = line.strip()

        if stripped.startswith("#"):
            for token in TEAM_HEADER_RE.findall(line):
                declared.add(token)
            if FUTURE_MARKER in stripped:
                pending_future = True
            continue

        if not stripped:
            pending_future = False
            continue

        parts = stripped.split()
        if len(parts) < 2:
            # A pattern with zero owners is a defect in the file itself, not
            # something the coverage checker should silently accept.
            raise InternalError(
                f"{CODEOWNERS_PATH}:{lineno}: rule has no owners: {stripped!r}"
            )
        pattern, owners = parts[0], tuple(parts[1:])
        rules.append(Rule(lineno, pattern, owners, pending_future))
        pending_future = False

    return rules, declared


def compile_pattern(pattern: str) -> tuple[bool, str]:
    """Return (anchored, normalized_pattern).

    * A leading `/` anchors the pattern to the repo root.
    * A trailing `/` matches the directory and everything under it.
    * No leading `/` matches at any depth (equivalent to `**/pattern`).
    """
    anchored = pattern.startswith("/")
    norm = pattern[1:] if anchored else pattern
    if norm.endswith("/"):
        norm = norm + "**"
    return anchored, norm


def _fnmatch_segments(
    path_segments: Sequence[str], pat_segments: Sequence[str]
) -> bool:
    """Match path segments against pattern segments; `**` crosses `/`."""
    if not pat_segments:
        return not path_segments
    head, *rest = pat_segments
    if head == "**":
        if not rest:
            return True
        for i in range(len(path_segments) + 1):
            if _fnmatch_segments(path_segments[i:], rest):
                return True
        return False
    if not path_segments:
        return False
    if not fnmatch.fnmatchcase(path_segments[0], head):
        return False
    return _fnmatch_segments(path_segments[1:], rest)


@functools.cache
def _pattern_segments(pattern: str) -> tuple[bool, tuple[str, ...]]:
    """compile_pattern() plus the segment split, once per distinct pattern."""
    anchored, norm = compile_pattern(pattern)
    return anchored, tuple(norm.split("/"))


def pattern_matches(pattern: str, rel_path: str) -> bool:
    anchored, pat_segments = _pattern_segments(pattern)
    path_segments = rel_path.split("/")

    if anchored:
        return _fnmatch_segments(path_segments, pat_segments)

    # Unanchored: pattern may match starting at any depth.
    for start in range(len(path_segments)):
        if _fnmatch_segments(path_segments[start:], pat_segments):
            return True
    return False


def matching_rules(rules: list[Rule], rel_path: str) -> list[Rule]:
    """Every rule whose pattern matches `rel_path`, in file order. The last one
    owns the path (GitHub semantics: last matching rule wins)."""
    return [rule for rule in rules if pattern_matches(rule.pattern, rel_path)]


def load_allowlist(repo_root: str) -> dict[str, str]:
    """Return {path: reason} for allowlisted catch-all paths.

    Format: one path per line, immediately followed by a `# reason:` comment
    line. Blank lines and other comments are ignored.
    """
    path = os.path.join(repo_root, ALLOWLIST_PATH)
    if not os.path.exists(path):
        return {}
    entries: dict[str, str] = {}
    pending_path: str | None = None
    with open(path, encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, start=1):
            stripped = raw.strip()
            if not stripped:
                pending_path = None
                continue
            if stripped.startswith("# reason:"):
                if pending_path is None:
                    raise InternalError(
                        f"{ALLOWLIST_PATH}:{lineno}: '# reason:' with no preceding path"
                    )
                entries[pending_path] = stripped[len("# reason:") :].strip()
                pending_path = None
                continue
            if stripped.startswith("#"):
                continue
            if pending_path is not None:
                raise InternalError(
                    f"{ALLOWLIST_PATH}:{lineno}: path {stripped!r} missing "
                    f"a preceding '# reason:' for {pending_path!r}"
                )
            pending_path = stripped
    if pending_path is not None:
        raise InternalError(
            f"{ALLOWLIST_PATH}: path {pending_path!r} at EOF has no '# reason:' comment"
        )
    return entries


@dataclass
class Violations:
    catch_all: list[MatchResult] = field(default_factory=list)
    dead_rules: list[Rule] = field(default_factory=list)
    unknown_owners: list[tuple[Rule, str]] = field(default_factory=list)
    future_summary: list[Rule] = field(default_factory=list)


def check(repo_root: str) -> tuple[Violations, list[MatchResult]]:
    rules, declared = parse_codeowners(repo_root)
    allowlist = load_allowlist(repo_root)
    tracked = git_tracked_files(repo_root)

    any_matched_lines: set[int] = set()
    results: list[MatchResult] = []
    violations = Violations()

    for rel_path in tracked:
        # One matching pass per path serves both the owner (the last match)
        # and dead-rule detection (a rule is live if it matches any path,
        # winning or shadowed).
        matched = matching_rules(rules, rel_path)
        winner = matched[-1] if matched else None
        results.append(MatchResult(rel_path, winner))
        if (winner is None or winner.is_catch_all) and rel_path not in allowlist:
            violations.catch_all.append(MatchResult(rel_path, winner))
        any_matched_lines.update(rule.line_no for rule in matched)

    for rule in rules:
        if rule.is_catch_all:
            continue
        if rule.line_no not in any_matched_lines:
            if rule.is_future:
                violations.future_summary.append(rule)
            else:
                violations.dead_rules.append(rule)
        for owner in rule.owners:
            if owner not in declared:
                violations.unknown_owners.append((rule, owner))

    return violations, results


def emit(violations: Violations, as_json: bool, github_actions: bool) -> None:
    if as_json:
        payload = {
            "catch_all": [
                {"code": "GOV-001", "path": m.path} for m in violations.catch_all
            ],
            "dead_rules": [
                {"code": "GOV-001", "line": r.line_no, "pattern": r.pattern}
                for r in violations.dead_rules
            ],
            "unknown_owners": [
                {"code": "GOV-001", "line": r.line_no, "owner": o}
                for r, o in violations.unknown_owners
            ],
            "future_marked_dead": [
                {"line": r.line_no, "pattern": r.pattern}
                for r in violations.future_summary
            ],
        }
        print(json.dumps(payload, indent=2))
        return

    for m in violations.catch_all:
        rule_desc = f"line {m.rule.line_no} (*)" if m.rule else "no rule matched"
        print(f"GOV-001 {m.path} matched-by:{rule_desc} owners:catch-all")
        if github_actions:
            print(
                f"::error file={m.path}::GOV-001 {m.path} falls through to the "
                "catch-all CODEOWNERS rule"
            )
    for r in violations.dead_rules:
        print(
            f"GOV-001 {CODEOWNERS_PATH}:{r.line_no} dead rule "
            f"{r.pattern!r} matches no tracked path"
        )
        if github_actions:
            print(
                f"::error file={CODEOWNERS_PATH},line={r.line_no}::"
                f"GOV-001 dead rule {r.pattern!r}"
            )
    for r, owner in violations.unknown_owners:
        print(
            f"GOV-001 {CODEOWNERS_PATH}:{r.line_no} owner {owner!r} not in "
            "the declared team list"
        )
        if github_actions:
            print(
                f"::error file={CODEOWNERS_PATH},line={r.line_no}::"
                f"GOV-001 undeclared owner {owner!r}"
            )
    if violations.future_summary:
        print("GOV-001 forward-looking rules (# future:, not counted as dead):")
        for r in violations.future_summary:
            print(f"  {CODEOWNERS_PATH}:{r.line_no} {r.pattern}")


def emit_report(results: list[MatchResult], out: TextIO | None = None) -> None:
    for m in results:
        owners = " ".join(m.rule.owners) if m.rule else "(unowned)"
        rule_desc = m.rule.pattern if m.rule else "(none)"
        print(f"{m.path}\t{rule_desc}\t{owners}", file=out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--json", action="store_true", help="emit JSON instead of text")
    parser.add_argument(
        "--report",
        action="store_true",
        help="print a full path -> rule -> owners table and exit 0",
    )
    parser.add_argument(
        "--report-file",
        metavar="PATH",
        help="also write the --report table to PATH (exit code still from the check)",
    )
    args = parser.parse_args(argv)

    repo_root = os.path.abspath(args.repo_root)
    try:
        violations, results = check(repo_root)
    except InternalError as exc:
        print(f"GOV-001 internal error: {exc}", file=sys.stderr)
        return 2
    except subprocess.CalledProcessError as exc:
        print(f"GOV-001 internal error: git ls-files failed: {exc}", file=sys.stderr)
        return 2

    if args.report_file:
        with open(args.report_file, "w", encoding="utf-8") as report:
            emit_report(results, report)

    if args.report:
        emit_report(results)
        return 0

    github_actions = os.environ.get("GITHUB_ACTIONS") == "true"
    emit(violations, args.json, github_actions)

    has_violations = bool(
        violations.catch_all or violations.dead_rules or violations.unknown_owners
    )
    return 1 if has_violations else 0


if __name__ == "__main__":
    sys.exit(main())
