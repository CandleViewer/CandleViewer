#!/usr/bin/env python3
"""E10-X02: `electron-hardening` CI gate (SR-110..SR-119, SR-174, SR-114 at build time).

Inspects the *built* artefacts (compiled main/preload output and the renderer
bundle), not the TypeScript source, because source-level checks miss build-time
configuration and bundler output (ticket Technical notes). Facts that only a
running app can report (live `webPreferences`, the CSP header the main process
actually builds) come from `apps/desktop/scripts/collect-hardening-facts.mjs`
as a JSON file passed with `--facts`.

Every failure names the SR requirement and links its section 6.11 or 6.11a row so
a developer can self-serve the fix. Exit 0 = clean, 1 = violations, 2 = usage.
Stdlib only. Checks live in `electron_hardening_checks.py`.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.ci.electron_hardening_checks import run_all_checks


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--desktop-dist", type=Path, required=True, help="apps/desktop/dist"
    )
    ap.add_argument("--web-dist", type=Path, required=True, help="apps/web/dist")
    ap.add_argument(
        "--builder-config", type=Path, required=True, help="electron-builder.yml"
    )
    ap.add_argument("--facts", type=Path, help="JSON from collect-hardening-facts.mjs")
    ap.add_argument(
        "--require-runtime",
        action="store_true",
        help="fail if the facts file has no live window webPreferences (CI sets this)",
    )
    args = ap.parse_args(argv)

    facts: dict[str, object] = {}
    if args.facts is not None:
        facts = json.loads(args.facts.read_text(encoding="utf-8"))

    violations = run_all_checks(
        desktop_dist=args.desktop_dist,
        web_dist=args.web_dist,
        builder_config=args.builder_config,
        facts=facts,
        require_runtime=args.require_runtime,
    )
    if not violations:
        print("electron-hardening: clean (SR-110..SR-119 and SR-174 assertions hold)")
        return 0
    for v in violations:
        print(f"::error title=electron-hardening {v.sr}::{v.render()}")
        print(v.render(), file=sys.stderr)
    print(f"electron-hardening: {len(violations)} violation(s)", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
