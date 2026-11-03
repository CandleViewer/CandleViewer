#!/usr/bin/env python3
"""E03-T11: compute the semver bump for a commit list (C-15.5: pre-1.0 a
breaking change bumps MINOR; 1.0.0 only with --allow-1-0-0). A local CLI kept
for inspection (#3099): the release-prep and release-verification flow is
`tools/ci/prepare_release.py`, which reuses `release_semver` directly.

Usage:
    python tools/ci/compute_release_bump.py --commits-json commits.json \\
        --current-version version.txt [--allow-1-0-0]

Prints `next_version=<X.Y.Z>` and `bump=<major|minor|patch|none>` to
stdout and, when a BREAKING CHANGE commit is in the list, the triggering
sha(s). Exit codes: 0 ok, 1 1.0.0 guard tripped (CI-REL-002; not reachable
from a commit list since C-15.5 keeps breaking changes in 0.x), 2 no version
bump needed.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tools.ci.changelog_lib import build_changelog_update, parse_commit  # noqa: E402
from tools.ci.release_semver import Version, compute_next_version  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commits-json", type=Path, required=True)
    parser.add_argument(
        "--current-version", required=True, help="path to version.txt or a literal X.Y.Z"
    )
    parser.add_argument("--allow-1-0-0", action="store_true")
    args = parser.parse_args(argv)

    version_arg = args.current_version
    version_path = Path(version_arg)
    version_text = (
        version_path.read_text(encoding="utf-8").strip() if version_path.exists() else version_arg
    )
    current = Version.parse(version_text)

    raw_commits = json.loads(args.commits_json.read_text(encoding="utf-8"))
    parsed = [parse_commit(item["sha"], item["message"]) for item in raw_commits]
    update = build_changelog_update(parsed)

    result = compute_next_version(current, update.bump, allow_1_0_0=args.allow_1_0_0)
    if not result.ok:
        print(f"{result.error_code}: {result.reason}", file=sys.stderr)
        return 1

    if update.bump.value == "none":
        print("bump=none")
        print(f"next_version={current}")
        return 2

    print(f"bump={update.bump.value}")
    print(f"next_version={result.next_version}")
    if update.triggering_breaking_commits:
        print("triggering_commits=" + ",".join(update.triggering_breaking_commits))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
