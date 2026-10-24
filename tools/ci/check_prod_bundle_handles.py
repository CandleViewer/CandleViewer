#!/usr/bin/env python3
"""E14-X03 (#549; DR5, SR-E14-10): no test-only engine handle in the production bundle.

`__cvEngine.projectForTest` (E14-Q03) lets a test project chart coordinates to pixels. A production
page that exposes it hands any script a way to spoof where a drawing sits: the E14 threat model's
DR5 (`docs/security/threat-models/E14-drawings.md`). The script files (`.js`, `.mjs`, `.cjs`) and
`.html` files of the web build must hold no identifier of
`tools/ci/prod-bundle-forbidden-handles.json` (E14-Q03 adds its names there). Source maps are never
read: their `sourcesContent` holds the source of a handle that is correctly gated out of the bundle.
A dist with no script file fails, so a missing or half-written build never passes, whatever `.html`
it holds. An identifier is matched as a substring: `__cvEngineDebug` counts as `__cvEngine`.

Usage: python tools/ci/check_prod_bundle_handles.py --dist apps/web/dist [--manifest FILE]
Exit: 0 clean, 1 a forbidden identifier is present, 2 a bad manifest or no script file to scan.
Stdlib only.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Sequence
from pathlib import Path

MANIFEST = Path(__file__).with_name("prod-bundle-forbidden-handles.json")
SCRIPT_SUFFIXES = frozenset({".js", ".mjs", ".cjs"})
SCAN_SUFFIXES = SCRIPT_SUFFIXES | {".html"}  # never ".map"
IDENTIFIER = re.compile(r"[A-Za-z_$][\w$]{3,}")
FIELDS = ("identifier", "threat", "requirement")


def load_handles(manifest: Path) -> list[dict[str, str]]:
    data = json.loads(manifest.read_text(encoding="utf-8"))
    handles = data.get("handles") if isinstance(data, dict) else None
    if not isinstance(handles, list) or not handles:
        raise ValueError("'handles' must be a non-empty list")
    for h in handles:
        ok = isinstance(h, dict) and all(isinstance(h.get(f), str) and h[f] for f in FIELDS)
        if not ok or not IDENTIFIER.fullmatch(h["identifier"]):
            raise ValueError(
                f"{h!r}: needs an identifier (4+ characters), a threat and a requirement"
            )
    return handles


def scan(dist: Path, handles: Sequence[dict[str, str]]) -> tuple[int, int, list[str]]:
    """The number of files read, how many of them are scripts, and one message per (file,
    identifier) found."""
    scanned, scripts, found = 0, 0, []
    for path in sorted(dist.rglob("*")):
        suffix = path.suffix.lower()
        if suffix not in SCAN_SUFFIXES or not path.is_file():
            continue
        scanned += 1
        scripts += suffix in SCRIPT_SUFFIXES
        text = path.read_text(encoding="utf-8", errors="replace")
        for h in handles:
            at = text.find(h["identifier"])
            if at >= 0:
                line, col = text.count("\n", 0, at) + 1, at - text.rfind("\n", 0, at)
                where = f"{path.relative_to(dist).as_posix()}:{line}:{col}"
                found.append(f"{where}: '{h['identifier']}' ({h['threat']}; {h['requirement']})")
    return scanned, scripts, found


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n", 1)[0])
    ap.add_argument("--dist", type=Path, required=True)
    ap.add_argument("--manifest", type=Path, default=MANIFEST)
    args = ap.parse_args(argv)
    try:
        handles = load_handles(args.manifest)
    except (OSError, ValueError) as exc:
        print(f"prod-bundle: {args.manifest}: {exc}", file=sys.stderr)
        return 2
    scanned, scripts, found = scan(args.dist, handles) if args.dist.is_dir() else (0, 0, [])
    if not scripts:
        print(
            f"prod-bundle: no script file (.js, .mjs or .cjs) under {args.dist}: build it first",
            file=sys.stderr,
        )
        return 2
    for message in found:
        print(f"prod-bundle: {message}", file=sys.stderr)
    if found:
        print(
            "prod-bundle: DR5 (spoofing: a test-only handle in a production bundle), SR-E14-10:"
            " gate it out of the build (docs/security/threat-models/E14-drawings.md)",
            file=sys.stderr,
        )
        return 1
    print(
        f"prod-bundle: OK: {scanned} file(s) scanned, none of {len(handles)} identifier(s) present"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
