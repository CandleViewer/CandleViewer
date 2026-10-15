"""Private entry of the RelayRoom client credentials — masked TTY input, atomic JSON merge.

Run this yourself in a NEW terminal opened at the CandleViewer checkout. It never echoes the
values, never prints them, and never puts them on a command line. It merges exactly three keys
into `.claude/settings.local.json` -> "env", preserving everything else in that file.

Usage:  python scripts/relayroom-enter-credentials.py
Refuses to run without a real TTY (so values cannot be piped or logged).
Exit codes: 0 = written; 2 = refused (no TTY, missing file or an invalid value), nothing written.

The write goes through a temp file next to the target (`.claude/.settings.local.*.tmp`, listed in
.gitignore) and `os.replace`; the temp file is removed on every failure path, so no copy of the
secrets is left behind.

Windows caveat: NTFS has no POSIX mode 0600. Access to the file is governed only by the inherited
NTFS ACL of the profile directory the checkout lives in (`.claude/` inherits it); this script
neither sets nor verifies it, so keep the checkout inside your user profile, not a shared folder.
On POSIX the temp file is created 0600 and `os.replace` keeps that mode.
"""
from __future__ import annotations

import contextlib
import getpass
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from urllib.parse import quote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / ".claude" / "settings.local.json"
ORIGIN = "https://relay.candleviewer.com"
PART = "main-orchestrator"
DEFAULT_LABEL = "cv-main-desktop-win-l01"
# The temp file name must match `.claude/.settings.local.*.tmp` in .gitignore.
TMP_PREFIX = ".settings.local."
TMP_SUFFIX = ".tmp"


def die(msg: str) -> None:
    print(f"refused: {msg}", file=sys.stderr)
    sys.exit(2)


def atomic_write_json(target: Path, data: dict) -> None:
    """Write `data` to `target` via a same-directory temp file; never leave the temp file behind."""
    fd, tmp = tempfile.mkstemp(dir=str(target.parent), prefix=TMP_PREFIX, suffix=TMP_SUFFIX)
    try:
        try:
            f = os.fdopen(fd, "w", encoding="utf-8")
        except BaseException:
            # fdopen failed before taking ownership of the descriptor
            with contextlib.suppress(OSError):
                os.close(fd)
            raise
        with f:  # closes the descriptor on every path out of this block
            json.dump(data, f, indent=2)
            f.write("\n")
        os.replace(tmp, target)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def main() -> None:
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        die("a real TTY is required; do not pipe or redirect")
    if not TARGET.exists():
        die(f"{TARGET} does not exist")

    print("RelayRoom credential entry for part=main-orchestrator (input is masked; nothing is echoed).")
    code = getpass.getpass("Project connect code (from the agent's Connect dialog, bypass OFF): ").strip()
    token = getpass.getpass("Fresh agent bearer token (NOT the account password): ").strip()
    label = input(f"Machine label [{DEFAULT_LABEL}]: ").strip() or DEFAULT_LABEL

    if not code or not token:
        die("empty value")
    # Before the whitespace check: "Bearer <token>" contains whitespace and would never reach it.
    if token.lower().startswith("bearer "):
        die("enter the raw token, without the 'Bearer ' prefix")
    if re.search(r"\s", code) or re.search(r"\s", token):
        die("whitespace in a secret value")
    if re.search(r"<[^>]+>|\$\{", code + token):
        die("placeholder text entered instead of a value")
    if "/" in code or "?" in code or "%" in code:
        # dashboard supplies a bare code; percent-encode once as a path segment
        if "%" in code:
            die("connect code looks already URL-encoded; paste the raw code")
    url = f"{ORIGIN}/mcp/{quote(code, safe='')}?part={PART}"
    u = urlsplit(url)
    if f"{u.scheme}://{u.netloc}" != ORIGIN or u.query != f"part={PART}":
        die("assembled URL failed its own structure check")

    data = json.loads(TARGET.read_text(encoding="utf-8"))
    env = data.setdefault("env", {})
    env["CANDLEVIEWER_RELAYROOM_MCP_URL"] = url
    env["CANDLEVIEWER_RELAYROOM_API_KEY"] = token
    env["CANDLEVIEWER_RELAYROOM_MACHINE_LABEL"] = label

    atomic_write_json(TARGET, data)
    print("written: 3 env keys merged into .claude/settings.local.json (values not shown).")
    print("next: python scripts/relayroom-main-doctor.py  then reconnect MCP in the Code session (/mcp).")


if __name__ == "__main__":
    main()
