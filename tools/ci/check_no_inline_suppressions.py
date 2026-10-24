#!/usr/bin/env python3
"""E14-X03 (#549; DR6, SR-E14-01): no silent suppression in the drawing render paths.

A drawing's stored text (label, note, template name) must reach the DOM as text only. The ESLint
ban and the Semgrep rules enforce that, and a comment that switches a check off there would hide
the next real finding. In the files under the paths of `tools/ci/no-inline-suppression-paths.json`
(globs relative to the repository root; a ticket that adds drawing or object-tree code extends the
list), a comment that holds `eslint-disable`, `@ts-ignore`, `@ts-expect-error` or `nosemgrep`
fails unless it is a reviewed annotation in the repo's form (`tools/ci/suppressions.py`,
CI-SEC-006): `reason=<token> owner=@<handle> review=YYYY-MM-DD` in the same comment line, the
review at most 180 days away.

Usage: python tools/ci/check_no_inline_suppressions.py [--root DIR] [--config FILE] [--today DATE]
Exit: 0 clean, 1 a suppression without a reviewed annotation, 2 a bad config. Stdlib only.
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
from tools.ci.suppressions import field_problems  # noqa: E402 - sys.path first

CONFIG = "tools/ci/no-inline-suppression-paths.json"
SOURCE_SUFFIXES = frozenset({".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts"})
SKIP_DIRS = frozenset({"node_modules", "dist", "coverage", ".turbo"})
# The marker anywhere in a comment: a word in a string is not one, a prose mention is (rephrase it).
MARKER_RE = re.compile(
    r"(?://|/\*)[^\n]*?(?P<marker>\beslint-disable(?:-next-line|-line)?\b|@ts-ignore\b"
    r"|@ts-expect-error\b|\bnosemgrep\b)(?P<rest>[^\n]*)"
)
_GLOB_TOKENS = ((r"**/", "(?:.*/)?"), (r"**", ".*"), (r"*", "[^/]*"), (r"?", "[^/]"))


class ConfigError(ValueError):
    pass


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
    try:
        data = json.loads(config.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ConfigError(f"{config}: {exc}") from exc
    paths = data.get("paths") if isinstance(data, dict) else None
    if not isinstance(paths, list) or not paths or not all(isinstance(p, str) and p for p in paths):
        raise ConfigError(f"{config}: 'paths' must be a non-empty list of globs")
    for p in paths:
        if p.startswith("/") or "\\" in p or ".." in p.split("/"):
            raise ConfigError(f"{config}: {p!r} must be a relative glob inside the repository")
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
            comment = (m.group("marker") + m.group("rest")).split("*/", 1)[0]
            problems = field_problems(comment, today)
            if problems:
                found.append(f"{rel}:{n}: {m.group('marker')}: {'; '.join(problems)}")
    return found


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n", 1)[0])
    ap.add_argument("--root", type=Path, default=_REPO_ROOT)
    ap.add_argument("--config", type=Path)
    ap.add_argument("--today", type=date.fromisoformat)
    args = ap.parse_args(argv)
    try:
        paths = load_paths(args.config or args.root / CONFIG)
    except ConfigError as exc:
        print(f"no-inline-suppressions: {exc}", file=sys.stderr)
        return 2
    today = args.today or datetime.now(UTC).date()
    files = files_in_scope(args.root, paths)
    findings = [
        m for f in files for m in findings_in(f, f.relative_to(args.root).as_posix(), today)
    ]
    for message in findings:
        print(f"no-inline-suppressions: {message}", file=sys.stderr)
    if findings:
        print(
            "no-inline-suppressions: DR6, SR-E14-01: remove it, or annotate it in the repo's form "
            "`reason=<token> owner=@<handle> review=YYYY-MM-DD` (docs/plan/security/ci-gates-e14.md)",  # noqa: E501 - one URL-like path
            file=sys.stderr,
        )
        return 1
    print(f"no-inline-suppressions: OK: {len(files)} file(s) under {len(paths)} path(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
