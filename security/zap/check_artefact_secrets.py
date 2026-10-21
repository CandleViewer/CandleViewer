#!/usr/bin/env python3
"""E42-X03: no secret of this run in the files the ZAP admin workflow uploads (C-12.2).

Each role's bearer and SR-041 CSRF token live inside the ZAP container, whose output and reports
are uploaded with the plans and the API's log; a GitHub mask hides a value in the run's log, not
in a file. The API's redaction filter (C-12.6) is the first control for the passwords, keys and
TOTP secrets the run made, and this is the second. Before the upload, it fails if one of these
appears in a file under the given paths, as written, JSON-escaped or percent-encoded:

- every value of the run's env files (`--env-dir`, each `*.env` that `mint_sessions.py` wrote:
  `NAME=value` lines);
- the value of each environment variable `--env NAME` names (the generated passwords, pepper and
  keys), unless it is unset or empty: the check also runs after a step that failed before the
  secret was made;
- the stripped content of each file `--secret-file GLOB` matches (the TOTP secrets
  `seed_fixture_user.py` writes), unless it is empty.

It names the env file and variable, `env:NAME` or `file:NAME`, and the artefact file, never the
value.

Fail-closed: a line that is not `NAME=value`, or a value too short to search for (an empty one
would match every file), is an error, not a pass; so is a variable or a secret file too short to
search by. No env file means no session was minted, so nothing can have leaked. Stdlib only.

Usage: check_artefact_secrets.py --env-dir DIR [--env NAME ...] [--secret-file GLOB ...]
PATH [PATH ...]
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import quote

#: The shortest value searched for: each secret is a token, key or seed of far more characters.
MIN_LEN = 16


class Unreadable(ValueError):
    """An input this check cannot read whole; the message never holds a value."""


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


def _searchable(label: str, value: str) -> str:
    if len(value) < MIN_LEN:
        raise Unreadable(f"{label} is too short to search for")
    return value


def run_secrets(
    names: list[str], patterns: list[str], environ: Mapping[str, str]
) -> dict[str, str]:
    """Each `--env` variable that holds a value, by `env:<name>`, and each `--secret-file` match
    that holds one, by `file:<file name>`; an unset or empty one holds no secret to look for."""
    values: dict[str, str] = {}
    for name in names:
        if value := environ.get(name, ""):
            values[f"env:{name}"] = _searchable(f"env:{name}", value)
    for pattern in patterns:
        for path in sorted(Path(match) for match in glob.glob(pattern)):
            if path.is_file() and (value := path.read_text(encoding="utf-8").strip()):
                label = f"file:{path.name}"
                if label in values:  # two files of one name: neither may hide the other
                    label = f"file:{path}"
                values[label] = _searchable(label, value)
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
    """Where a value appears: `<label> in <artefact file>`, never the value."""
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
    parser.add_argument(
        "--env",
        action="append",
        default=[],
        metavar="NAME",
        help="an environment variable whose value is searched for (repeatable)",
    )
    parser.add_argument(
        "--secret-file",
        action="append",
        default=[],
        metavar="GLOB",
        help="files whose stripped content is searched for (repeatable)",
    )
    parser.add_argument("paths", type=Path, nargs="+", help="the directories to be uploaded")
    args = parser.parse_args(argv)
    try:
        values = env_values(args.env_dir) if args.env_dir.is_dir() else {}
        extra = run_secrets(args.env, args.secret_file, os.environ)
        found = leaks({**values, **extra}, args.paths)
    except (OSError, UnicodeDecodeError, Unreadable) as exc:
        print(f"::error title=zap-admin::the artefact check cannot run: {exc}")
        return 2
    for item in found:
        print(f"::error title=zap-admin::a secret of the run reached the artefact: {item}")
    if not found:
        print(
            f"check_artefact_secrets: none of {len(values)} session values and "
            f"{len(extra)} run secrets in the artefact"
        )
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
