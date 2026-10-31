#!/usr/bin/env python3
"""E14-X03 (#549): the reviewed exceptions of the drawings rules are exactly the listed sites.

`cv-drawings-query-missing-owner-filter` flags every statement on `drawings` that has no owner
predicate. The few that are unscoped by design carry a reviewed `nosemgrep`, so the product scan
shows none. This scans `services/api/candleviewer` with the five persistence rules and
`--disable-nosem`, names each finding by its rule, its file and the statement it starts at (the
assigned constant's name, else `line N`), and compares them with
`tools/ci/drawings-exception-sites.json`. A sixth unscoped statement fails here; an annotation moved
to another statement of the same file fails the job, here or in the whole-tree scan beside it. A
count of (file, rule) pairs would pass both. A scan that read no file, or left a target unread for
any reason but configuration (the skips `security_gate.py` allows), fails too: an exception there
could not be seen. It needs the `semgrep` binary: the `semgrep-bandit` job's venv has it, CI's
governance shards do not (`scripts/tests/test_e14_security_gates.py` checks the annotations against
the list there, without Semgrep).

Usage: check_drawings_exception_sites.py [--root DIR] [--sites FILE]
Exit: 0 the same, 1 a difference, 2 the scan or the list could not be read. Stdlib only.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
SITES = "tools/ci/drawings-exception-sites.json"
TARGET = "services/api/candleviewer"
RULES = (
    "cv-drawings-query-missing-owner-filter",
    "cv-drawings-owner-from-body",
    "cv-drawings-unbounded-geometry",
    "cv-drawings-batch-unvalidated-ids",
    "cv-drawings-pixel-geometry",
)
#: The skip reasons configuration explains, as `security_gate._CONFIGURED_SKIPS` (a test keeps
#: them equal): any other leaves a target unread.
CONFIGURED_SKIPS = frozenset(
    {
        "Gitignore_patterns_match",
        "semgrepignore_patterns_match",
        "cli_include_flags_do_not_match",
        "cli_exclude_flags_match",
    }
)
ASSIGNED = re.compile(r"\s*([A-Za-z_]\w*)\s*(?::[^=\n]+)?=(?!=)")
#: A site: the rule, the file (relative to the repo root) and the statement.
Site = tuple[str, str, str]


def statement(line: str, number: int) -> str:
    """The constant a statement assigns, or `line N` when its first line is no assignment."""
    named = ASSIGNED.match(line)
    return named.group(1) if named else f"line {number}"


def found_sites(results: Sequence[dict[str, Any]], root: Path) -> list[Site]:
    """Each Semgrep result as a site: its rule, its path and the statement its first line opens."""
    sites: list[Site] = []
    for result in results:
        path, number = Path(str(result["path"])).as_posix(), int(result["start"]["line"])
        lines = (root / path).read_text(encoding="utf-8").splitlines()
        rule = str(result["check_id"]).rsplit(".", 1)[-1]
        sites.append((rule, path, statement(lines[number - 1], number)))
    return sorted(sites)


def load_sites(path: Path) -> list[Site]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return sorted((str(data["rule"]), str(s["path"]), str(s["statement"])) for s in data["sites"])


def compare(found: Sequence[Site], listed: Sequence[Site]) -> list[str]:
    """One problem per site the scan found and the list lacks, and per listed site it did not."""
    problems = [
        f"{path}: {name}: {rule} reports it and {SITES} does not: fix the statement, or annotate "
        "it with a reviewed `nosemgrep` and list it"
        for rule, path, name in sorted(Counter(found) - Counter(listed))
    ]
    problems += [
        f"{path}: {name}: listed in {SITES}, but {rule} no longer reports it: remove it from there"
        for rule, path, name in sorted(Counter(listed) - Counter(found))
    ]
    return problems


def scan(root: Path) -> list[dict[str, Any]]:
    """The five rules' results over the service, annotations disabled."""
    argv = ["semgrep", "scan", "--metrics=off", "--verbose", "--json", "--disable-nosem"]
    argv += ["--timeout", "120", "--max-target-bytes", "5000000"]
    for rule in RULES:
        argv += ["--config", f".semgrep/{rule}.yml"]
    # --timeout: a slow parse on a loaded host is no failure; timeout=: a wedged scan is no hang.
    proc = subprocess.run(  # noqa: S603 - semgrep, a fixed argument list (#549)
        [*argv, TARGET],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=300,
    )
    if proc.returncode not in (0, 1):
        raise RuntimeError(f"semgrep exited {proc.returncode}: {proc.stderr[-300:]}")
    data = json.loads(proc.stdout)
    if data["errors"]:
        raise RuntimeError(f"semgrep reported errors: {data['errors']}")
    paths = data.get("paths") or {}  # --verbose writes both lists
    if not paths.get("scanned"):
        raise RuntimeError(f"semgrep read no file under {TARGET}: is --root the repository?")
    skipped = paths.get("skipped")
    if not isinstance(skipped, list):  # without --verbose: no word on what was left unread
        raise RuntimeError("semgrep listed no skipped targets: was --verbose dropped?")
    lost = [
        f"{entry.get('path')} ({entry.get('reason')})"
        for entry in skipped
        if entry.get("reason") not in CONFIGURED_SKIPS
    ]
    if lost:
        raise RuntimeError(f"semgrep left targets unread: {', '.join(lost[:5])}")
    results: list[dict[str, Any]] = data["results"]
    return results


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n", 1)[0])
    ap.add_argument("--root", type=Path, default=REPO_ROOT)
    ap.add_argument("--sites", type=Path)
    args = ap.parse_args(argv)
    try:
        listed = load_sites(args.sites or args.root / SITES)
        found = found_sites(scan(args.root), args.root)
    except (OSError, ValueError, LookupError, RuntimeError, subprocess.TimeoutExpired) as exc:
        print(f"drawings-exception-sites: {exc}", file=sys.stderr)
        return 2
    problems = compare(found, listed)
    for problem in problems:
        print(f"drawings-exception-sites: {problem}", file=sys.stderr)
    if not problems:
        print(f"drawings-exception-sites: OK: {len(found)} reviewed exception site(s), as listed")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
