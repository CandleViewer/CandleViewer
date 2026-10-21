"""Export a Penpot shape/board to PNG via a Penpot MCP server (no plugin-side base64 juggling).

Usage:  python docs/design/_tools/penpot_export.py <shapeId> <out.png> [--svg]
            [--server NAME] [--project DIR] [--endpoint URL]
The key is the `userToken` of an MCP server entry in ~/.claude.json and is never printed. The
default entry is the user-scope `penpot` (hosted design.penpot.app). For a local-scope entry, such
as a self-hosted Penpot's, also pass --project: the folder the entry was added in (its key under
`projects`). The endpoint is the entry's own URL without its query; --endpoint overrides it (https,
or http on loopback only). PENPOT_MCP_SERVER / PENPOT_MCP_PROJECT / PENPOT_MCP_ENDPOINT set the
defaults. Requires the Penpot MCP plugin to be connected in an open browser tab (see
docs/design/README.md).
"""
import argparse
import base64
import json
import os
import re
import urllib.error
import urllib.request

DEFAULT_SERVER = "penpot"
ENDPOINT_RE = re.compile(r"https://[^\s?#]+|http://(127\.0\.0\.1|localhost)(:\d+)?(/[^\s?#]*)?")


def _entry(server: str, project: str | None) -> tuple[str, str]:
    """(endpoint, key) of an MCP server entry: user scope, or a project's local scope."""
    cfg = json.load(open(os.path.expanduser("~/.claude.json"), encoding="utf-8"))
    project = os.path.abspath(os.path.expanduser(project)) if project else None
    scope = cfg.get("projects", {}).get(project, {}) if project else cfg
    url = scope.get("mcpServers", {}).get(server, {}).get("url", "")
    if "userToken=" not in url:
        where = f"project {project!r}" if project else "user scope"
        raise SystemExit(f"no MCP server entry {server!r} with a userToken in ~/.claude.json"
                         f" ({where})")
    return url.split("?", 1)[0], url.split("userToken=", 1)[1]


def _post(url: str, body: dict, sid: str | None = None):
    h = {"User-Agent": "candleviewer-design-tools", "Content-Type": "application/json",
         "Accept": "application/json, text/event-stream"}
    if sid:
        h["Mcp-Session-Id"] = sid
    # urllib/http.client messages embed the URL, which carries the key: report the error type only
    try:
        req = urllib.request.Request(url, json.dumps(body).encode(), h)
        r = urllib.request.urlopen(req, timeout=300)
        sid = r.headers.get("Mcp-Session-Id") or sid
        data = [json.loads(l[5:]) for l in r.read().decode().splitlines() if l.startswith("data:")]
    except urllib.error.HTTPError as e:
        raise SystemExit(f"MCP HTTP error {e.code}") from None
    except urllib.error.URLError as e:
        raise SystemExit(f"MCP connection error: {type(e.reason).__name__}") from None
    except Exception as e:
        raise SystemExit(f"MCP request failed: {type(e).__name__}") from None
    return sid, data


def export(shape_id: str, out: str, fmt: str = "png", server: str = DEFAULT_SERVER,
           project: str | None = None, endpoint: str | None = None) -> int:
    base, key = _entry(server, project)
    endpoint = endpoint or base
    if not ENDPOINT_RE.fullmatch(endpoint):
        raise SystemExit("the MCP endpoint must be https (http on loopback only), with no query")
    url = endpoint + "?userToken=" + key
    sid, _ = _post(url, {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                         "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                                    "clientInfo": {"name": "cv-export", "version": "1"}}})
    _post(url, {"jsonrpc": "2.0", "method": "notifications/initialized"}, sid)
    _, d = _post(url, {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                       "params": {"name": "export_shape", "arguments": {"shapeId": shape_id, "format": fmt}}}, sid)
    msg = d[-1] if d else {"error": "the MCP reply had no data frames"}
    if "error" in msg:
        raise SystemExit("MCP error: " + json.dumps(msg["error"]).replace(key, "<key>")[:400])
    for c in msg.get("result", {}).get("content", []):
        if c.get("type") == "image":
            raw = base64.b64decode(c["data"])
            os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
            open(out, "wb").write(raw)
            return len(raw)
        if c.get("type") == "text" and fmt == "svg":
            open(out, "w", encoding="utf-8").write(c["text"])
            return len(c["text"])
    raise SystemExit("no image in response: " + json.dumps(msg).replace(key, "<key>")[:400])


if __name__ == "__main__":
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("shape_id")
    p.add_argument("out")
    p.add_argument("--svg", action="store_true")
    p.add_argument("--server", default=os.environ.get("PENPOT_MCP_SERVER") or DEFAULT_SERVER)
    p.add_argument("--project", default=os.environ.get("PENPOT_MCP_PROJECT") or None)
    p.add_argument("--endpoint", default=os.environ.get("PENPOT_MCP_ENDPOINT") or None)
    a = p.parse_args()
    n = export(a.shape_id, a.out, "svg" if a.svg else "png", a.server, a.project, a.endpoint)
    print(f"wrote {a.out} ({n} bytes)")
