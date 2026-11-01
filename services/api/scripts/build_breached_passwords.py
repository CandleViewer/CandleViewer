"""Build the offline breached-password list (SR-028, #2330 BQ-222) from a local source copy.

Source: SecLists, `Passwords/Common-Credentials/` (https://github.com/danielmiessler/SecLists),
licence: MIT (Copyright (c) 2018 Daniel Miessler). Only an MIT-licensed source passes the licence
allowlist; a CC-BY list does not. Nothing is downloaded: pass the path of a copy already on disk.

Usage:
    uv run python scripts/build_breached_passwords.py --source <file> [--source <file> ...]
    uv run python scripts/build_breached_passwords.py --seed

Each source is read as UTF-8, one password per line. An entry shorter than 12 code points is
dropped (the policy's minimum is 14, so no shorter entry can ever match, and 12 keeps the list
valid should the minimum be lowered to SR-028's former 12). Every kept entry is written as the
SHA-1 hex digest of its NFC, lower-cased form (`candleviewer.auth.password_policy.digest`),
sorted and de-duplicated, under a header naming the source and its licence. `--seed` writes the
committed seed instead: the former 8-entry deny list of `auth/invite_service.py`, until the
generator is run against the source.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from candleviewer.auth.password_policy import BREACHED_LIST_PATH, digest

#: Entries shorter than this are dropped (BQ-222: ">= 12 code points").
MIN_ENTRY_LENGTH = 12
SOURCE_NOTE = (
    "# Source: SecLists Passwords/Common-Credentials (github.com/danielmiessler/SecLists), "
    "MIT licence.\n"
)
#: The seed: the deny list `auth/invite_service.py` carried before this module (all >= 12).
SEED = (
    "password1234",
    "passwordpassword",
    "123456789012",
    "qwertyuiop12",
    "letmein123456",
    "administrator",
    "candleviewer1",
    "iloveyou12345",
)


def render(entries: list[str], *, seed: bool) -> str:
    kept = sorted({digest(e) for e in entries if len(e) >= MIN_ENTRY_LENGTH})
    header = (
        "# GENERATED FILE - DO NOT EDIT BY HAND. Generator: services/api/scripts/"
        "build_breached_passwords.py\n"
        "# SHA-1 hex of NFC, lower-cased passwords of 12 code points or more (SR-028, #2330).\n"
    )
    if seed:
        header += (
            "# SEED ONLY: the former 8-entry invite deny list, not the SecLists list. Run the\n"
            "# generator with --source against a local copy of the source to replace it.\n"
        )
    else:
        header += SOURCE_NOTE
    return header + "".join(f"{d}\n" for d in kept)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", type=Path, action="append", default=[])
    parser.add_argument("--seed", action="store_true")
    parser.add_argument("--out", type=Path, default=BREACHED_LIST_PATH)
    args = parser.parse_args(argv)
    if args.seed == bool(args.source):
        parser.error("give --seed or at least one --source, not both")
    entries = list(SEED)
    if not args.seed:
        entries = [
            line.rstrip("\r\n")
            for path in args.source
            for line in path.read_text(encoding="utf-8", errors="ignore").splitlines()
        ]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render(entries, seed=args.seed), encoding="utf-8")
    print(f"[build_breached_passwords] wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
