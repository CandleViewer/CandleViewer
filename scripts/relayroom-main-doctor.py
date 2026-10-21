"""RelayRoom main-orchestrator client doctor (nonsecret, read-only).

Validates the CandleViewer RelayRoom client binding WITHOUT printing any secret value:
JSON validity, Git exclusion, scope, URL structure, placeholder/whitespace rejection, descriptor
vs intended binding. Output is an allowlisted set of PASS/FAIL lines only.

Usage:  python scripts/relayroom-main-doctor.py [--config-root PATH]
Exit codes: 0 = ready to activate; 1 = at least one FAIL; 2 = the doctor itself crashed (it
prints only the exception class name, never its message, which could echo a secret value).

Hub origin: the one origin the connect code may be sent to is never a committed literal. The doctor
resolves it from the environment variable CANDLEVIEWER_RELAYROOM_ORIGIN, else from the optional
`hubOrigin` key of the private descriptor (`.claude/relayroom/identity.local.json`), as a bare
`https://host[:port]`, and FAILs closed when neither is set or the value is invalid. Only the source
is reported; the value is never printed.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import urlsplit

EXPECTED = {
    "project": "candleviewer",
    "part": "main-orchestrator",
    "persona": "Atlas",
    "mcpServer": "candleviewer-relayroom",
}
# The hub origin is the allowlist for where the connect code may be sent, so it is never a committed
# literal: it comes from the operator's private configuration (see hub_origin()).
ORIGIN_ENV = "CANDLEVIEWER_RELAYROOM_ORIGIN"
ORIGIN_KEY = "hubOrigin"
# Exactly `https://host[:port]`: no userinfo, path, query or fragment, so nothing secret can ride along.
ORIGIN_RE = re.compile(r"https://[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?(:[0-9]{1,5})?")
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


def _blank(value: object) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def parse_origin(value: object) -> str | None:
    """The canonical (lower-case) `https://host[:port]` if `value` is exactly that, else None."""
    text = value.strip() if isinstance(value, str) else ""
    text = text.removesuffix("/")
    return text.lower() if ORIGIN_RE.fullmatch(text) else None


def hub_origin(identity: object, environ: Mapping[str, str] | None = None) -> tuple[str, str]:
    """Resolve the hub origin and where it came from (never a committed literal, no default).

    Order: env CANDLEVIEWER_RELAYROOM_ORIGIN, else the optional `hubOrigin` key of the private
    descriptor `identity`; with neither, fail closed. Raises ValueError whose message never contains
    the configured value (a mistyped value could be secret material); callers decide how to report.
    """
    env = os.environ if environ is None else environ
    raw: object = env.get(ORIGIN_ENV)
    source = f"env {ORIGIN_ENV}"
    if _blank(raw):
        raw = identity.get(ORIGIN_KEY) if isinstance(identity, dict) else None
        source = f"identity.{ORIGIN_KEY}"
    if _blank(raw):
        raise ValueError(
            f"not configured — set {ORIGIN_ENV} or `{ORIGIN_KEY}` in the private descriptor"
        )
    origin = parse_origin(raw)
    if origin is None:
        raise ValueError(f"invalid in {source} — expected https://host[:port] and nothing else")
    return origin, source


def run(root: Path) -> int:
    """Run every check against `root`, print the allowlisted report, return the exit code."""
    # --- local MCP config (copied from docs/ops/relayroom-mcp.template.json) ---
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
        # A `hubOrigin` that parse_origin() accepts is a bare https origin: it cannot carry a secret, but
        # its hostname may contain a scanned word, so only such a value is exempt. Any other value stays
        # in the scan, even when the env var takes precedence over it in hub_origin() below.
        scanned = {k: v for k, v in ident.items() if k != ORIGIN_KEY or parse_origin(v) is None}
        secretish = json.dumps(scanned).lower()
        check("identity carries no token/url/connect-code", not any(s in secretish for s in ("bearer", "/mcp/", "token", "connect")))

    # --- hub origin (private: env or identity.hubOrigin; only the source is printed, never the value) ---
    origin: str | None
    try:
        origin, origin_source = hub_origin(ident)
    except ValueError as e:
        origin = None
        check("hub origin resolved", False, str(e))
    else:
        check("hub origin resolved", True, f"via {origin_source}")

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
            check("MCP URL origin is the hub (https, exact host)",
                  origin is not None and f"{u.scheme}://{u.netloc}" == origin)
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
