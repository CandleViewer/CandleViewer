#!/usr/bin/env python3
"""Merge the changelog-worthy commits since the last release tag into CHANGELOG.md's
`## Unreleased` section (`docs/plan/07-release-and-prr.md` §3, #2341). `changelog.yml` runs it
with `--preview` (writes nothing; job summary); a reviewed sync PR runs it without (`AGENTS.md` §4).

Usage:
    python tools/ci/update_changelog.py (--commits-json PATH | --since-last-tag [--rev REV])
        [--changelog PATH] [--preview] [--summary PATH]

Idempotent merge (a pure function of the file and the commit list; a re-run is byte-identical):
exact-duplicate entries in Unreleased collapse (first occurrence wins); existing and curated
entries stay verbatim and in place; a commit is present when an entry line under `## Unreleased`
or a `## X.Y.Z — YYYY-MM-DD` heading ENDS with its `(sha7)` or the last `(#N)` of its subject
(never a mid-line mention, never the header above the first `##`); any other content inside
Unreleased raises ChangelogFormatError. `--commits-json` holds `[{"sha", "message"}]`;
`--since-last-tag` uses `tools/ci/collect_commits.py`.

Exit codes: 0 updated or no change, 1 ChangelogFormatError or a git/shallow-repository error.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tools.ci.changelog_lib import (  # noqa: E402
    Category,
    ParsedCommit,
    build_changelog_update,
    check_security_wording,
    parse_commit,
)
from tools.ci.collect_commits import (  # noqa: E402
    CollectCommitsError,
    commits_since_last_tag,
    last_final_tag,
)

_CATEGORY_ORDER = [
    Category.BREAKING,
    Category.FEATURES,
    Category.FIXES,
    Category.PERFORMANCE,
    Category.SECURITY,
]

_HEADING = "## Unreleased"
_VERSION_HEADING_RE = re.compile(r"^## \d+\.\d+\.\d+ — \d{4}-\d{2}-\d{2}$")
_TRAILING_TOKEN_RE = re.compile(r"\(([^()]+)\)$")
_PR_TOKEN_RE = re.compile(r"\(#(\d+)\)")
# Above this many pending entries a sync PR is due, so each one stays within C-4.8 (07 §3).
PENDING_WARN_THRESHOLD = 300


class ChangelogFormatError(ValueError):
    """Unknown content inside `## Unreleased`: fail loudly instead of dropping it."""


@dataclass
class MergeResult:
    text: str
    changed: bool
    section: list[str]
    entries: int
    pending: int
    duplicates: int
    security_violations: list[str]


def _default_changelog() -> str:
    lines = ["# Changelog", "", "All notable changes to CandleViewer are documented here.", ""]
    lines.append(_HEADING)
    for cat in _CATEGORY_ORDER:
        lines.append("")
        lines.append(f"### {cat.value}")
    lines.append("")
    return "\n".join(lines)


def _load_commits(path: Path) -> list[ParsedCommit]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [parse_commit(item["sha"], item["message"]) for item in raw]


def _render_unreleased_section(existing: dict[Category, list[str]]) -> list[str]:
    out = [_HEADING]
    for cat in _CATEGORY_ORDER:
        out.append("")
        out.append(f"### {cat.value}")
        out.extend(existing.get(cat, []))
    out.append("")
    return out


def _split_unreleased(text: str) -> tuple[str, str, dict[Category, list[str]], int]:
    """Return (before, after, entries by category, exact duplicates collapsed)."""
    lines = text.splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line.strip() == _HEADING)
    except StopIteration:
        return text.rstrip("\n") + "\n\n", "", {}, 0

    end = len(lines)
    for i in range(start + 1, len(lines)):
        if lines[i].startswith("## ") and lines[i].strip() != _HEADING:
            end = i
            break

    before = "\n".join(lines[:start]).rstrip("\n") + "\n\n"
    after = "\n".join(lines[end:])
    if after and not after.endswith("\n"):
        after += "\n"

    entries: dict[Category, list[str]] = {}
    seen: set[str] = set()
    duplicates = 0
    current: Category | None = None
    for number, line in enumerate(lines[start + 1 : end], start=start + 2):
        stripped = line.strip()
        if not stripped:
            continue
        matched = next((c for c in _CATEGORY_ORDER if stripped == f"### {c.value}"), None)
        if matched is not None:
            current = matched
        elif current is not None and stripped.startswith("- "):
            if line.rstrip() in seen:
                duplicates += 1
            else:
                seen.add(line.rstrip())
                entries.setdefault(current, []).append(line)
        else:
            raise ChangelogFormatError(
                f"line {number}: unexpected content inside {_HEADING!r} (only '### <Category>' "
                f"headings and '- ' entries under one are allowed): {line!r}"
            )
    return before, after, entries, duplicates


def _parse_existing_unreleased(text: str) -> tuple[str, str, dict[Category, list[str]]]:
    """Split `text` into (before, after, entries-under-Unreleased-by-category)."""
    before, after, entries, _ = _split_unreleased(text)
    return before, after, entries


def _version_section_entries(text: str) -> list[str]:
    """Entry lines under `## X.Y.Z — YYYY-MM-DD` headings (never the header above them)."""
    out: list[str] = []
    in_version = False
    for line in text.splitlines():
        if line.startswith("## "):
            in_version = bool(_VERSION_HEADING_RE.match(line.rstrip()))
        elif in_version and line.strip().startswith("- "):
            out.append(line)
    return out


def referenced_tokens(lines: Iterable[str]) -> set[str]:
    """The trailing `(token)` of each entry line (`abc1234`, `#123`); nothing else counts."""
    tokens: set[str] = set()
    for line in lines:
        match = _TRAILING_TOKEN_RE.search(line.rstrip())
        if match:
            tokens.add(match.group(1))
    return tokens


def is_referenced(commit: ParsedCommit, tokens: set[str]) -> bool:
    """True when `tokens` holds the commit's sha7 or the LAST `(#N)` of its subject line."""
    sha7 = commit.sha[:7]
    if sha7 and sha7 in tokens:
        return True
    prs = _PR_TOKEN_RE.findall(commit.subject_line)
    return bool(prs) and f"#{prs[-1]}" in tokens


def merge_unreleased(changelog_text: str, commits: list[ParsedCommit]) -> MergeResult:
    """Merge `commits` into Unreleased (see the module docstring); never re-adds or drops."""
    before, after, entries, duplicates = _split_unreleased(changelog_text)
    present = [line for lines in entries.values() for line in lines]
    tokens = referenced_tokens([*present, *_version_section_entries(changelog_text)])
    seen = {line.rstrip() for line in present}
    update = build_changelog_update([c for c in commits if not is_referenced(c, tokens)])
    pending = 0
    for cat, new_lines in update.entries.items():
        for line in new_lines:
            if line.rstrip() not in seen:
                seen.add(line.rstrip())
                entries.setdefault(cat, []).append(line)
                pending += 1

    section = _render_unreleased_section(entries)
    changed = bool(duplicates or pending)
    text = before + "\n".join(section) + "\n" + after if changed else changelog_text
    security = check_security_wording(entries.get(Category.SECURITY, []))
    total = sum(len(lines) for lines in entries.values())
    return MergeResult(text, changed, section, total, pending, duplicates, security.violations)


def apply_update(changelog_text: str, commits: list[ParsedCommit]) -> tuple[str, bool]:
    """Return (new_text, changed); an unchanged result is the input, byte-identical."""
    result = merge_unreleased(changelog_text, commits)
    for line in result.security_violations:
        print(
            f"WARNING: Security changelog line may contain exploit detail: {line!r}",
            file=sys.stderr,
        )
    return result.text, result.changed


def _escape(data: str) -> str:
    return data.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _summary(counts: list[str], section: str) -> str:
    fence = "`" * max(3, 1 + max((len(run) for run in re.findall(r"`+", section)), default=0))
    lines = ["### Changelog preview (read-only; CHANGELOG.md changes only via reviewed PRs)", ""]
    lines += [f"- {count}" for count in counts]
    return "\n".join([*lines, "", f"{fence}markdown", section, fence, ""])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--commits-json", type=Path)
    source.add_argument("--since-last-tag", action="store_true")
    parser.add_argument("--rev", default=None, help="revision for --since-last-tag (HEAD)")
    parser.add_argument("--changelog", type=Path, default=Path("CHANGELOG.md"))
    parser.add_argument("--preview", action="store_true", help="write nothing; print the result")
    parser.add_argument("--summary", type=Path, default=None, help="append a markdown report")
    args = parser.parse_args(argv)
    if args.rev is not None and not args.since_last_tag:
        parser.error("--rev needs --since-last-tag")

    if args.changelog.exists():
        text = args.changelog.read_text(encoding="utf-8")
    else:
        text = _default_changelog()
    try:
        if args.since_last_tag:
            rev = args.rev or "HEAD"
            tag = last_final_tag(rev)
            origin = f"{tag}..{rev}" if tag else f"{rev} (no final v* tag reachable)"
            commits = [parse_commit(c["sha"], c["message"]) for c in commits_since_last_tag(rev)]
        else:
            commits, origin = _load_commits(args.commits_json), str(args.commits_json)
        result = merge_unreleased(text, commits)
    except (ChangelogFormatError, CollectCommitsError) as exc:
        print(f"::error::{_escape(f'{args.changelog}: {exc}')}")
        return 1

    section = "\n".join(result.section).rstrip("\n")
    counts = [
        f"commits: {origin}",
        f"entries: {result.entries}",
        f"pending: {result.pending}",
        f"duplicates collapsed: {result.duplicates}",
        f"security warnings: {len(result.security_violations)}",
    ]
    if args.preview:
        print(section)
    print("\n".join(counts))
    warnings = [
        f"Security changelog line may contain exploit detail: {line}"
        for line in result.security_violations
    ]
    if result.pending > PENDING_WARN_THRESHOLD:
        warnings.insert(
            0,
            f"{result.pending} changelog entries are pending (> {PENDING_WARN_THRESHOLD}): "
            "open a changelog sync PR (docs/plan/07-release-and-prr.md §3)",
        )
    for warning in warnings:
        print(f"::warning::{_escape(warning)}")
    if args.summary is not None:
        with args.summary.open("a", encoding="utf-8") as fh:
            fh.write(_summary(counts, section))
    if args.preview or not result.changed:
        return 0
    args.changelog.write_text(result.text, encoding="utf-8", newline="\n")
    print(f"{args.changelog} updated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
