#!/usr/bin/env python3
"""E42-X03: no session value of this run in the files the ZAP admin workflow uploads (C-12.2).

Each role's bearer and SR-041 CSRF token live inside the ZAP container, whose output and reports
are uploaded with the plans and the API's log; a GitHub mask hides a value in the run's log, not
in a file. Before the upload, this reads every value of the run's env files (`--env-dir`, each
`*.env` that `mint_sessions.py` wrote: `NAME=value` lines) and fails if one appears in a file
under the given paths, as written, JSON-escaped or percent-encoded. It names the env file, the
variable and the artefact file, never the value.

Fail-closed: a line that is not `NAME=value`, or a value too short to search for (an empty one
would match every file), is an error, not a pass. No env file means no session was minted, so
nothing can have leaked. Stdlib only.

Usage: check_artefact_secrets.py --env-dir DIR PATH [PATH ...]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.parse import quote

#: The shortest value searched for: each session value is a token of far more characters.
MIN_LEN = 16


class Unreadable(ValueError):
    """An env file this check cannot read whole; the message never holds a value."""


def env_values(env_dir: Path) -> dict[str, str]:
    """Each value of each `*.env` file in `env_dir`, by `<file>:<name>`."""
    values: dict[str, str] = {}
    for path in sorted(env_dir.glob("*.env")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            text = line.strip()
            if not text or text.startswith("#"):
                continue
            name, sep, value = text.partition("=")
            if not sep or not name.strip():
                raise Unreadable(f"{path.name}:{number}: not a NAME=value line")
            if len(value) < MIN_LEN:
                raise Unreadable(f"{path.name}:{number}: {name} is too short to search for")
            values[f"{path.name}:{name}"] = value
    return values


def _forms(value: str) -> set[bytes]:
    escaped = json.dumps(value)[1:-1]
    return {
        value.encode(),
        escaped.encode(),
        escaped.replace("/", "\\/").encode(),
        quote(value, safe="").encode(),
    }


def leaks(values: dict[str, str], roots: list[Path]) -> list[str]:
    """Where a value appears: `<file>:<name> in <artefact file>`, never the value."""
    needles = {label: _forms(value) for label, value in values.items()}
    found: list[str] = []
    for root in roots:
        if not root.exists():
            continue
        files = [root] if root.is_file() else sorted(p for p in root.rglob("*") if p.is_file())
        for path in files:
            data = path.read_bytes()
            found += [
                f"{label} in {path}"
                for label, forms in needles.items()
                if any(form in data for form in forms)
            ]
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--env-dir", type=Path, required=True)
    parser.add_argument("paths", type=Path, nargs="+", help="the directories to be uploaded")
    args = parser.parse_args(argv)
    try:
        values = env_values(args.env_dir) if args.env_dir.is_dir() else {}
        found = leaks(values, args.paths)
    except (OSError, UnicodeDecodeError, Unreadable) as exc:
        print(f"::error title=zap-admin::the artefact check cannot run: {exc}")
        return 2
    for item in found:
        print(f"::error title=zap-admin::a session value reached the artefact: {item}")
    if not found:
        print(f"check_artefact_secrets: none of {len(values)} session values in the artefact")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
