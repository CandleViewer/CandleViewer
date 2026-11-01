"""Build the offline breached-password list (SR-028, #2330 BQ-222) from a local source copy.

Source: SecLists, `Passwords/Common-Credentials/` (https://github.com/danielmiessler/SecLists),
licence: MIT (Copyright (c) 2018 Daniel Miessler). Only an MIT-licensed source passes the licence
allowlist; a CC-BY list does not. Nothing is downloaded: pass the path of a copy already on disk.

Usage:
    uv run python scripts/build_breached_passwords.py --commit <sha> --root <SecLists checkout> \
        --source <file under the root> [--source ...]

The committed list (#5269) is SecLists commit 00f80ec9cc39bed63ee40cf6805a6b1b77e87644,
`Passwords/Common-Credentials/xato-net-10-million-passwords-1000000.txt` and
`Passwords/Common-Credentials/Pwdb_top-1000000.txt`. `--commit` is the SecLists commit the sources
were taken from and `--root` the directory holding that commit's tree; the header records the
commit, and each source's path relative to the root and its SHA-256, so the list can be rebuilt
and checked byte for byte (the output is deterministic).

A list below `BREACHED_LIST_MIN` digests is refused unless `--allow-small` is given: the policy
fails closed on such a list (#5269), so committing one would refuse every password change and
invite redemption. `--allow-small` exists for tests and trials, never for the committed list.

Each source is read as UTF-8, one password per line. An entry shorter than 12 code points is
dropped (the policy's minimum is 14, so no shorter entry can ever match, and 12 keeps the list
valid should the minimum be lowered to SR-028's former 12). Every kept entry is written as the
SHA-1 hex digest of its NFC, lower-cased form (`candleviewer.auth.password_policy.digest`),
sorted and de-duplicated, under a header naming the source and its licence.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path

from candleviewer.auth.password_policy import BREACHED_LIST_MIN, BREACHED_LIST_PATH, digest

#: Entries shorter than this are dropped (BQ-222: ">= 12 code points").
MIN_ENTRY_LENGTH = 12
SOURCE_NOTE = "# Source: SecLists (github.com/danielmiessler/SecLists), MIT licence.\n"


#: A full 40-hex git commit sha (an abbreviated one could name another commit later).
_COMMIT = re.compile(r"[0-9a-f]{40}")


def provenance(commit: str, root: Path, sources: list[Path]) -> str:
    """The header lines naming the SecLists commit and each source's path (relative to *root*,
    the SecLists checkout) and SHA-256. A source outside *root* raises `ValueError`."""
    lines = [f"# SecLists commit: {commit}\n"]
    for path in sources:
        relative = path.resolve().relative_to(root.resolve()).as_posix()
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        lines.append(f"# Source file: {relative} sha256 {sha}\n")
    return "".join(lines)


def digests(entries: list[str]) -> list[str]:
    """The sorted, de-duplicated digests of the entries of `MIN_ENTRY_LENGTH` or more."""
    return sorted({digest(e) for e in entries if len(e) >= MIN_ENTRY_LENGTH})


def render(kept: list[str], *, sources_note: str) -> str:
    header = (
        "# GENERATED FILE - DO NOT EDIT BY HAND. Generator: services/api/scripts/"
        "build_breached_passwords.py\n"
        "# SHA-1 hex of NFC, lower-cased passwords of 12 code points or more (SR-028, #2330).\n"
    )
    return header + SOURCE_NOTE + sources_note + "".join(f"{d}\n" for d in kept)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", type=Path, action="append", required=True)
    parser.add_argument("--commit", required=True, help="the SecLists commit sha of the sources")
    parser.add_argument("--root", type=Path, required=True, help="the SecLists checkout")
    parser.add_argument("--allow-small", action="store_true", help="tests and trials only")
    parser.add_argument("--out", type=Path, default=BREACHED_LIST_PATH)
    args = parser.parse_args(argv)
    if not _COMMIT.fullmatch(args.commit):
        parser.error("--commit must be the full 40-hex SecLists commit sha")
    try:
        note = provenance(args.commit, args.root, args.source)
    except ValueError:
        parser.error("every --source must lie under --root (the SecLists checkout)")
    kept = digests(
        [
            line.rstrip("\r\n")
            for path in args.source
            for line in path.read_text(encoding="utf-8", errors="ignore").splitlines()
        ]
    )
    if len(kept) < BREACHED_LIST_MIN and not args.allow_small:
        parser.error(
            f"{len(kept)} digests is below BREACHED_LIST_MIN ({BREACHED_LIST_MIN}): the policy "
            "would fail closed on this list; pass --allow-small only outside the committed list"
        )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render(kept, sources_note=note), encoding="utf-8")
    print(f"[build_breached_passwords] wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
