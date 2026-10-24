#!/usr/bin/env python3
"""E14-X03 (#549; DR6, SR-E14-01): no silent suppression in the drawing render paths.

Under the globs of `tools/ci/no-inline-suppression-paths.json` (relative to the repo root; a ticket
that adds drawing or object-tree code extends the list), a comment holding `eslint-disable`, an
ESLint config comment (`/* eslint <rule>: off */`), `@ts-ignore`, `@ts-expect-error`, `nosemgrep`
or any `nosem...` spelling fails unless it is a reviewed annotation in the repo's form
(`tools/ci/suppressions.py`, CI-SEC-006) in the same comment: `reason=<token>`, `owner=` and
`review=YYYY-MM-DD`, at most 180 days away. The shared grammar takes any `@handle`; on these paths
only `@CandleViewer/security` may own one (the ticket's Security-engineer review). A marker that
opens a line inside a block comment counts too (ESLint reads `/*` + newline + `eslint-disable` as a
directive), and every marker on a line is judged, not only the first.

Usage: python tools/ci/check_no_inline_suppressions.py [--root DIR] [--config FILE] [--today DATE]
Exit: 0 clean, 1 an unreviewed suppression, 2 a bad config. Stdlib only.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Sequence
from datetime import UTC, date, datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
from tools.ci.suppressions import field, field_problems  # noqa: E402 - sys.path first (#549)

CONFIG = "tools/ci/no-inline-suppression-paths.json"
#: The one owner a drawing-path suppression may name: the shared grammar takes any `@handle`, which
#: would make the escape self-service (#4377's L5).
OWNER = "@CandleViewer/security"
SOURCE_SUFFIXES = frozenset({".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts"})
SKIP_DIRS = frozenset({"node_modules", "dist", "coverage", ".turbo"})
# No `\b` after a TypeScript marker, and any `nosem...` word: tsc honours `@ts-expect-errorx` and
# Semgrep `nosemantic` (CI-SEC-006 still blocks the Semgrep ones, a lane later).
_MARKERS = (
    r"\beslint-disable(?:-next-line|-line)?\b|@ts-ignore|@ts-expect-error|(?i:\bnosem\w*)"
    r"|\beslint(?=\s+[@\w/-]+\s*:)"  # a config comment: `/* eslint no-console: off */`
)
# The marker anywhere in a comment, or opening a line inside a block comment after any run of `/`
# and `*`, as TypeScript reads a directive. A marker in a string after code is not one; a string
# line that opens with one counts (it fails closed), and so does a prose mention (rephrase it).
MARKER_RE = re.compile(rf"(?:(?://|/\*)[^\n]*?|^\s*[/*]*\s*)(?P<marker>{_MARKERS})")
_GLOB_TOKENS = ((r"**/", "(?:.*/)?"), (r"**", ".*"), (r"*", "[^/]*"), (r"?", "[^/]"))


def glob_regex(pattern: str) -> re.Pattern[str]:
    """`**/` any directories, `**` anything, `*` and `?` within one path segment."""
    out, i = [], 0
    while i < len(pattern):
        token = next((t for t in _GLOB_TOKENS if pattern.startswith(t[0], i)), None)
        out.append(token[1] if token else re.escape(pattern[i]))
        i += len(token[0]) if token else 1
    return re.compile("".join(out))


def covered(relpath: str, paths: Sequence[str]) -> bool:
    return any(glob_regex(p).fullmatch(relpath) for p in paths)


def load_paths(config: Path) -> list[str]:
    # An OSError, or a ValueError for bad JSON, is the caller's to report.
    data = json.loads(config.read_text(encoding="utf-8"))
    paths = data.get("paths") if isinstance(data, dict) else None
    if not isinstance(paths, list) or not paths or not all(isinstance(p, str) and p for p in paths):
        raise ValueError("'paths' must be a non-empty list of globs")
    for p in paths:
        if p.startswith("/") or "\\" in p or ".." in p.split("/"):
            raise ValueError(f"{p!r} must be a relative glob inside the repository")
    return list(paths)


def files_in_scope(root: Path, paths: Sequence[str]) -> list[Path]:
    """The source files under the globs; a build or symlinked directory is not entered."""
    found: set[Path] = set()
    for pattern in paths:
        literal: list[str] = []
        for part in pattern.split("/"):
            if "*" in part or "?" in part:
                break
            literal.append(part)
        rx = glob_regex(pattern)
        base = root.joinpath(*literal)
        walked = [(str(base.parent), [], [base.name])] if base.is_file() else os.walk(base)
        for dirpath, dirnames, filenames in walked:
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for name in filenames:
                path = Path(dirpath, name)
                rel = path.relative_to(root).as_posix()
                if path.suffix in SOURCE_SUFFIXES and rx.fullmatch(rel):
                    found.add(path)
    return sorted(found)


def findings_in(path: Path, rel: str, today: date) -> list[str]:
    """One message per suppression comment in `path` that is no reviewed annotation."""
    found: list[str] = []
    for n, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        for m in MARKER_RE.finditer(line):
            comment = line[m.start("marker") :].split("*/", 1)[0]
            problems = field_problems(comment, today)
            owner = field(comment, "owner")
            if owner and owner != OWNER:
                problems.append(f"suppression owner {owner!r} must be {OWNER} on a drawing path")
            if problems:
                found.append(f"{rel}:{n}: {m.group('marker')}: {'; '.join(problems)}")
    return found


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n", 1)[0])
    ap.add_argument("--root", type=Path, default=_REPO_ROOT)
    ap.add_argument("--config", type=Path)
    ap.add_argument("--today", type=date.fromisoformat)
    args = ap.parse_args(argv)
    config = args.config or args.root / CONFIG
    try:
        paths = load_paths(config)
    except (OSError, ValueError) as exc:
        print(f"no-inline-suppressions: {config}: {exc}", file=sys.stderr)
        return 2
    today = args.today or datetime.now(UTC).date()
    files = files_in_scope(args.root, paths)
    findings = [
        m for f in files for m in findings_in(f, f.relative_to(args.root).as_posix(), today)
    ]
    for message in findings:
        print(f"no-inline-suppressions: {message}", file=sys.stderr)
    if findings:
        hint = f"remove it, or annotate it: `reason=<token> owner={OWNER} review=YYYY-MM-DD`"
        print(f"no-inline-suppressions: DR6, SR-E14-01: {hint}", file=sys.stderr)
        return 1
    print(f"no-inline-suppressions: OK: {len(files)} file(s) under {len(paths)} path(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
