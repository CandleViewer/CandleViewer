#!/usr/bin/env python3
"""#3495: every backlog twin blob is committed with LF line endings.

`docs/plan/backlog/_tools/validate.py --check` reads a twin's CRLF line endings as LF (#3454), so
it cannot see a twin blob that holds CRLF. The git CLI never commits one here (.gitattributes:
`* text=auto eol=lf`), but a commit made without git's clean filter can, such as a web-editor or
contents-API commit. This gate fails unless `git ls-files --eol` names every
`docs/plan/backlog/*.json` blob (the twins: E<nn>.json and all-tickets.json) `i/lf`. Anything else
fails: `crlf` and `mixed` hold CRLF, `-text` a lone CR or a NUL byte, `none` no line ending at
all; validate.py writes none of them.

Exit codes: 0 clean, 1 violation(s), 2 internal error. Stdlib only.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# `:(glob)` makes `*` stop at `/`: the twins only, not the JSON under _tools/ or schema/.
PATHSPEC = ":(glob)docs/plan/backlog/*.json"
FIX = (
    "re-save the twin as AGENTS.md section 3a says and commit it with the git CLI; for CRLF or "
    "mixed line endings, `git add --renormalize docs/plan/backlog` restages it as LF (#3495)"
)


def index_eols(root: Path) -> dict[str, str]:
    """Each matching path -> its index blob's line endings, as `git ls-files --eol` names them."""
    out = subprocess.run(
        ["git", "ls-files", "--eol", "-z", "--", PATHSPEC],
        cwd=root,
        capture_output=True,
        check=True,
    ).stdout.decode("utf-8")
    eols: dict[str, str] = {}
    for record in filter(None, out.split("\0")):
        info, _, path = record.partition("\t")
        eols[path] = info.split()[0].removeprefix("i/")
    return eols


def violations(eols: dict[str, str]) -> list[str]:
    """TWIN-EOL messages: a twin blob that is not LF, or no twin at all."""
    if not eols:
        return [f"TWIN-EOL no tracked file matches {PATHSPEC}: the gate would check nothing"]
    return [
        f"TWIN-EOL {path}: the committed blob is i/{eol}, not i/lf"
        for path, eol in sorted(eols.items())
        if eol != "lf"
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="#3495: every backlog twin blob is LF")
    parser.add_argument(
        "--repo-root", default=str(ROOT), help="repository root (default: this checkout)"
    )
    args = parser.parse_args(argv)
    try:
        eols = index_eols(Path(args.repo_root))
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.decode("utf-8", errors="replace").strip()
        print(f"TWIN-EOL internal error: git ls-files failed: {stderr}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"TWIN-EOL internal error: {exc}", file=sys.stderr)
        return 2
    problems = violations(eols)
    for line in problems:
        print(line)
    if problems:
        print(f"::error title=Backlog twin blob not LF::{FIX}")
        return 1
    print(f"TWIN-EOL ok: all {len(eols)} docs/plan/backlog/*.json blobs are committed as LF")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
