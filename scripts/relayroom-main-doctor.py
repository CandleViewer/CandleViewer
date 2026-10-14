"""RelayRoom main-orchestrator client doctor (nonsecret, read-only).

Validates the CandleViewer RelayRoom client binding WITHOUT printing any secret value:
JSON validity, Git exclusion, scope, URL structure, placeholder/whitespace rejection, descriptor
vs intended binding. Output is an allowlisted set of PASS/FAIL lines only.

Usage:  python scripts/relayroom-main-doctor.py [--config-root PATH]
Exit 0 = ready to activate; 1 = at least one FAIL.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

EXPECTED = {
    "project": "candleviewer",
    "part": "main-orchestrator",
    "persona": "Atlas",
    "mcpServer": "candleviewer-relayroom",
    "origin": "https://relay.candleviewer.com",
}
ENV_KEYS = (
    "CANDLEVIEWER_RELAYROOM_MCP_URL",
    "CANDLEVIEWER_RELAYROOM_API_KEY",
    "CANDLEVIEWER_RELAYROOM_MACHINE_LABEL",
)
PLACEHOLDER = re.compile(r"<[^>]+>|\$\{[^}]+\}|\bFRESH_|\bCURRENT_PROJECT_|\bchangeme\b", re.I)
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)

results: list[tuple[str, str]] = []


def check(name: str, ok: bool, note: str = "") -> None:
    results.append(("PASS" if ok else "FAIL", f"{name}{(' — ' + note) if note else ''}"))


def git_ignored(root: Path, rel: str) -> bool:
    r = subprocess.run(["git", "-C", str(root), "check-ignore", "-q", rel], capture_output=True)
    return r.returncode == 0


def git_tracked(root: Path, rel: str) -> bool:
    r = subprocess.run(["git", "-C", str(root), "ls-files", "--error-unmatch", rel], capture_output=True)
    return r.returncode == 0


def load_json(p: Path) -> dict | None:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config-root", default=str(Path(__file__).resolve().parents[1]))
    root = Path(ap.parse_args().config_root).resolve()

    # --- shared template --------------------------------------------------
    mcp = load_json(root / ".mcp.json")
    check(".mcp.json parses", mcp is not None)
    srv = (mcp or {}).get("mcpServers", {}).get(EXPECTED["mcpServer"])
    check("alias candleviewer-relayroom present", srv is not None)
    if srv:
        check("template uses env placeholders only (no literal secret)",
              srv.get("url") == "${CANDLEVIEWER_RELAYROOM_MCP_URL}"
              and srv.get("headers", {}).get("Authorization") == "Bearer ${CANDLEVIEWER_RELAYROOM_API_KEY}")

    # --- private identity -------------------------------------------------
    ident_p = root / ".claude" / "relayroom" / "identity.local.json"
    ident = load_json(ident_p)
    check("identity.local.json parses", ident is not None)
    check("identity.local.json git-ignored", git_ignored(root, ".claude/relayroom/identity.local.json"))
    if ident:
        for k in ("project", "part", "persona", "mcpServer"):
            check(f"identity.{k} == {EXPECTED[k]}", ident.get(k) == EXPECTED[k])
        check("identity.expectedIsMain is true", ident.get("expectedIsMain") is True)
        check("identity.clientInstanceId is a UUID", bool(UUID_RE.match(str(ident.get("clientInstanceId", "")))))
        check("identity.configRoot matches this checkout", Path(str(ident.get("configRoot", ""))).resolve() == root)
        secretish = json.dumps(ident).lower()
        check("identity carries no token/url/connect-code", not any(s in secretish for s in ("bearer", "/mcp/", "token", "connect")))

    # --- private credentials (presence/shape only; values never printed) ---
    sl_rel = ".claude/settings.local.json"
    sl = load_json(root / sl_rel)
    check("settings.local.json parses", sl is not None)
    check("settings.local.json NOT tracked", not git_tracked(root, sl_rel))
    check("settings.local.json git-ignored", git_ignored(root, sl_rel))
    env = (sl or {}).get("env", {}) if isinstance(sl, dict) else {}
    for k in ENV_KEYS:
        v = env.get(k)
        present = isinstance(v, str) and v.strip() != ""
        check(f"env.{k} present", present, "" if present else "pending (activation blocked)")
        if present:
            check(f"env.{k} has no placeholder", not PLACEHOLDER.search(v))
            check(f"env.{k} has no whitespace", v == v.strip() and not re.search(r"\s", v))
    url = env.get("CANDLEVIEWER_RELAYROOM_MCP_URL")
    if isinstance(url, str) and url.strip():
        u = urlsplit(url)
        check("MCP URL origin is the hub (https, exact host)", f"{u.scheme}://{u.netloc}" == EXPECTED["origin"])
        check("MCP URL path is /mcp/<connect-code>", bool(re.fullmatch(r"/mcp/[^/]+", u.path)))
        check("MCP URL query is exactly part=main-orchestrator", u.query == "part=main-orchestrator")
        check("MCP URL connect code is not double-encoded", "%25" not in u.path)
    label = env.get("CANDLEVIEWER_RELAYROOM_MACHINE_LABEL")
    if ident and isinstance(label, str) and label.strip():
        check("env machine label == identity.machineLabel", label == ident.get("machineLabel"))

    # --- runs -------------------------------------------------------------
    runs = sorted((root / ".claude" / "relayroom" / "runs").glob("*.json"))
    check("at least one run record exists", bool(runs))
    check("runs/ git-ignored", git_ignored(root, ".claude/relayroom/runs"))

    # --- report (allowlisted fields only) ------------------------------------
    for status, line in results:
        print(f"{status}  {line}")
    fails = sum(1 for s, _ in results if s == "FAIL")
    print(f"\nrelayroom-main-doctor: {'READY' if fails == 0 else f'{fails} FAIL'}  (part=main-orchestrator, alias=candleviewer-relayroom)")
    return 0 if fails == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
