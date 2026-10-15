"""RelayRoom main-orchestrator client doctor (nonsecret, read-only).

Validates the CandleViewer RelayRoom client binding WITHOUT printing any secret value:
JSON validity, Git exclusion, scope, URL structure, placeholder/whitespace rejection, descriptor
vs intended binding. Output is an allowlisted set of PASS/FAIL lines only.

Usage:  python scripts/relayroom-main-doctor.py [--config-root PATH]
Exit codes: 0 = ready to activate; 1 = at least one FAIL; 2 = the doctor itself crashed (it
prints only the exception class name, never its message, which could echo a secret value).
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
    """Parse `p` as a JSON object; None if missing, unreadable, invalid or not an object."""
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def run(root: Path) -> int:
    """Run every check against `root`, print the allowlisted report, return the exit code."""
    # --- shared template --------------------------------------------------
    mcp = load_json(root / ".mcp.json")
    check(".mcp.json parses as a JSON object", mcp is not None)
    servers = mcp.get("mcpServers") if mcp is not None else None
    srv = servers.get(EXPECTED["mcpServer"]) if isinstance(servers, dict) else None
    check("alias candleviewer-relayroom present", isinstance(srv, dict))
    if isinstance(srv, dict):
        headers = srv.get("headers")
        auth = headers.get("Authorization") if isinstance(headers, dict) else None
        check("template uses env placeholders only (no literal secret)",
              srv.get("url") == "${CANDLEVIEWER_RELAYROOM_MCP_URL}"
              and auth == "Bearer ${CANDLEVIEWER_RELAYROOM_API_KEY}")

    # --- private identity -------------------------------------------------
    ident_p = root / ".claude" / "relayroom" / "identity.local.json"
    ident = load_json(ident_p)
    check("identity.local.json parses as a JSON object", ident is not None)
    check("identity.local.json git-ignored", git_ignored(root, ".claude/relayroom/identity.local.json"))
    if ident is not None:
        for k in ("project", "part", "persona", "mcpServer"):
            check(f"identity.{k} == {EXPECTED[k]}", ident.get(k) == EXPECTED[k])
        check("identity.expectedIsMain is true", ident.get("expectedIsMain") is True)
        check("identity.clientInstanceId is a UUID", bool(UUID_RE.match(str(ident.get("clientInstanceId", "")))))
        # Path("") resolves to the cwd, so a missing/empty configRoot must not be treated as a match
        config_root = ident.get("configRoot")
        check("identity.configRoot matches this checkout",
              isinstance(config_root, str) and config_root.strip() != ""
              and Path(config_root).resolve() == root)
        secretish = json.dumps(ident).lower()
        check("identity carries no token/url/connect-code", not any(s in secretish for s in ("bearer", "/mcp/", "token", "connect")))

    # --- private credentials (presence/shape only; values never printed) ---
    sl_rel = ".claude/settings.local.json"
    sl = load_json(root / sl_rel)
    check("settings.local.json parses as a JSON object", sl is not None)
    check("settings.local.json NOT tracked", not git_tracked(root, sl_rel))
    check("settings.local.json git-ignored", git_ignored(root, sl_rel))
    raw_env = sl.get("env") if sl is not None else None
    env = raw_env if isinstance(raw_env, dict) else {}
    for k in ENV_KEYS:
        v = env.get(k)
        present = isinstance(v, str) and v.strip() != ""
        check(f"env.{k} present", present, "" if present else "pending (activation blocked)")
        if present:
            check(f"env.{k} has no placeholder", not PLACEHOLDER.search(v))
            check(f"env.{k} has no whitespace", v == v.strip() and not re.search(r"\s", v))
    url = env.get("CANDLEVIEWER_RELAYROOM_MCP_URL")
    if isinstance(url, str) and url.strip():
        try:
            u = urlsplit(url)
        except ValueError:
            check("MCP URL parses", False)
        else:
            check("MCP URL origin is the hub (https, exact host)", f"{u.scheme}://{u.netloc}" == EXPECTED["origin"])
            check("MCP URL path is the MCP prefix plus one connect-code segment", bool(re.fullmatch(r"/mcp/[^/]+", u.path)))
            check("MCP URL query is exactly part=main-orchestrator", u.query == "part=main-orchestrator")
            check("MCP URL connect code is not double-encoded", "%25" not in u.path)
    label = env.get("CANDLEVIEWER_RELAYROOM_MACHINE_LABEL")
    if ident is not None and isinstance(label, str) and label.strip():
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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="RelayRoom main-orchestrator client doctor")
    ap.add_argument("--config-root", default=str(Path(__file__).resolve().parents[1]))
    args = ap.parse_args(argv)
    results.clear()  # `results` is module-level: a second main() in one process starts clean
    try:
        return run(Path(args.config_root).resolve())
    except Exception as e:
        # Last-resort guard. Never print str(e) or a traceback: a message can embed a secret value.
        print(f"FAIL  doctor crashed: {type(e).__name__}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
