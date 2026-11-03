#!/usr/bin/env python3
"""E03-T11: finalise CHANGELOG.md's Unreleased section under a version
heading (`docs/plan/07-release-and-prr.md` §3). Since #3099 the release-prep
PR does this through `tools/ci/prepare_release.py`, which imports `finalize`;
the CLI stays for local use. The names imported from `update_changelog` keep
their names and signatures (#2341 tool contract).

Usage:
    python tools/ci/finalize_changelog.py --changelog CHANGELOG.md \\
        --version 0.3.0 --date 2026-10-03

Prints the finalised section body to stdout (for use as the GitHub Release
body) and rewrites CHANGELOG.md with a fresh, empty Unreleased section
above the new version heading.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tools.ci.update_changelog import (  # noqa: E402
    _CATEGORY_ORDER,
    _parse_existing_unreleased,
    _render_unreleased_section,
)


def finalize(text: str, version: str, date: str) -> tuple[str, str]:
    """Return (new_changelog_text, release_body_markdown)."""
    before, after, entries = _parse_existing_unreleased(text)

    body_lines = [f"## {version} — {date}"]
    for cat in _CATEGORY_ORDER:
        lines = entries.get(cat, [])
        if not lines:
            continue
        body_lines.append("")
        body_lines.append(f"### {cat.value}")
        body_lines.extend(lines)
    body_lines.append("")
    release_section = "\n".join(body_lines)

    fresh_unreleased = "\n".join(_render_unreleased_section({}))
    new_text = before + fresh_unreleased + "\n" + release_section + "\n" + after
    return new_text, release_section


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--changelog", type=Path, default=Path("CHANGELOG.md"))
    parser.add_argument("--version", required=True)
    parser.add_argument("--date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--release-body-out", type=Path, default=None)
    args = parser.parse_args(argv)

    text = args.changelog.read_text(encoding="utf-8")
    new_text, release_body = finalize(text, args.version, args.date)
    args.changelog.write_text(new_text, encoding="utf-8", newline="\n")

    if args.release_body_out is not None:
        args.release_body_out.write_text(release_body, encoding="utf-8", newline="\n")

    print(release_body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
