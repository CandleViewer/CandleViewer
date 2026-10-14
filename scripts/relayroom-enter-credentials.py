"""Private entry of the RelayRoom client credentials — masked TTY input, atomic JSON merge.

Run this yourself in a NEW terminal opened at the CandleViewer checkout. It never echoes the
values, never prints them, and never puts them on a command line. It merges exactly three keys
into `.claude/settings.local.json` -> "env", preserving everything else in that file.

Usage:  python scripts/relayroom-enter-credentials.py
Refuses to run without a real TTY (so values cannot be piped or logged).
"""
from __future__ import annotations

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


def die(msg: str) -> None:
    print(f"refused: {msg}", file=sys.stderr)
    sys.exit(2)


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
    if re.search(r"\s", code) or re.search(r"\s", token):
        die("whitespace in a secret value")
    if re.search(r"<[^>]+>|\$\{", code + token):
        die("placeholder text entered instead of a value")
    if token.lower().startswith("bearer "):
        die("enter the raw token, without the 'Bearer ' prefix")
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

    fd, tmp = tempfile.mkstemp(dir=str(TARGET.parent), prefix=".settings.local.", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    os.replace(tmp, TARGET)
    print("written: 3 env keys merged into .claude/settings.local.json (values not shown).")
    print("next: python scripts/relayroom-main-doctor.py  then reconnect MCP in the Code session (/mcp).")


if __name__ == "__main__":
    main()
