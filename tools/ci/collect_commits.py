#!/usr/bin/env python3
"""Collect the commits since the last release tag (#2341, docs/plan/07-release-and-prr.md §3).

"Since the last tag" means since the nearest FINAL `v*` tag reachable from the revision
(`git describe --tags --abbrev=0 --match 'v[0-9]*' --exclude '*-*' [--exclude TAG] REV`):
pre-release tags are not final, a tag on another line is never the base, and one named tag can
be excluded (a run at an already-tagged revision). With no such tag: the whole history.

Usage: python tools/ci/collect_commits.py [--rev REV] [--exclude TAG] [--repo DIR] [--out PATH]
Output: JSON `[{"sha", "message"}]`, newest first (`update_changelog.py --commits-json` input).
Exit codes: 0 ok, 1 shallow repository, unknown revision or git error. Stdlib only, no network.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import subprocess
import sys
from pathlib import Path


class CollectCommitsError(RuntimeError):
    """A shallow clone, an unknown revision or a failing git command."""


def _git(repo: str, *args: str) -> subprocess.CompletedProcess[str]:
    cmd = ["git", "-C", repo, *args]
    return subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace", check=False)


def last_final_tag(rev: str = "HEAD", repo: str = ".", exclude: str | None = None) -> str | None:
    """Return the nearest final `v*` tag reachable from `rev`, or None when there is none."""
    if rev.startswith("-"):
        raise CollectCommitsError(f"unknown revision {rev!r}")
    shallow = _git(repo, "rev-parse", "--is-shallow-repository")
    if shallow.returncode != 0:
        raise CollectCommitsError(f"not a git repository: {repo} ({shallow.stderr.strip()})")
    if shallow.stdout.strip() == "true":
        raise CollectCommitsError(
            f"{repo} is a shallow clone; the changelog range needs full history (fetch-depth: 0)"
        )
    resolved = _git(repo, "rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}")
    if resolved.returncode != 0:
        raise CollectCommitsError(f"unknown revision {rev!r}")
    sha = resolved.stdout.strip()
    args = ["describe", "--tags", "--abbrev=0", "--match", "v[0-9]*", "--exclude", "*-*"]
    described = _git(repo, *args, *(["--exclude", exclude] if exclude else []), sha)
    if described.returncode == 0:
        return described.stdout.strip()
    # describe fails both when no tag qualifies and on real errors; only the first is "no tag".
    merged = _git(repo, "tag", "--merged", sha, "--list", "v[0-9]*").stdout.split()
    if any("-" not in t and not (exclude and fnmatch.fnmatchcase(t, exclude)) for t in merged):
        raise CollectCommitsError(f"git describe failed: {described.stderr.strip()}")
    return None


def commits_since_last_tag(
    rev: str = "HEAD", repo: str = ".", exclude: str | None = None
) -> list[dict[str, str]]:
    """Return `[{sha, message}]` since the nearest final `v*` tag reachable from `rev`.

    `[]` at a tagged `rev`, unless that tag is `exclude`d.
    """
    tag = last_final_tag(rev, repo, exclude)
    range_ = rev if tag is None else f"{tag}..{rev}"
    log = _git(repo, "-c", "log.showSignature=false", "log", range_, "--pretty=format:%H%x1f%B%x1e")
    if log.returncode != 0:
        raise CollectCommitsError(f"git log {range_} failed: {log.stderr.strip()}")
    commits = []
    for chunk in log.stdout.split("\x1e"):
        chunk = chunk.strip()
        if chunk:
            sha, _, message = chunk.partition("\x1f")
            commits.append({"sha": sha, "message": message})
    return commits


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--rev", default="HEAD")
    parser.add_argument("--exclude", default=None, help="one tag never used as the base")
    parser.add_argument("--repo", default=".")
    parser.add_argument("--out", type=Path, default=None, help="write JSON here, not stdout")
    args = parser.parse_args(argv)
    try:
        commits = commits_since_last_tag(args.rev, args.repo, args.exclude)
    except CollectCommitsError as exc:
        print(f"collect_commits: {exc}", file=sys.stderr)
        return 1
    if args.out is None:
        print(json.dumps(commits))
    else:
        args.out.write_text(json.dumps(commits), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
