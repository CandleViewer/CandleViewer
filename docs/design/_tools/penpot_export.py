"""Export a Penpot shape/board to PNG via a Penpot MCP server (no plugin-side base64 juggling).

Usage:  python docs/design/_tools/penpot_export.py <shapeId> <out.png> [--svg]
            [--endpoint URL] [--server NAME] [--project DIR]
Reads the MCP key from the `userToken` of an MCP server entry in ~/.claude.json and never prints it.
The defaults keep the hosted setup: endpoint https://design.penpot.app/mcp/stream and the user-scope
entry `penpot`. For a self-hosted Penpot pass the endpoint and entry name, plus the project directory
for a local-scope entry (or set PENPOT_MCP_ENDPOINT / PENPOT_MCP_SERVER / PENPOT_MCP_PROJECT).
Requires the Penpot MCP plugin to be connected in an open browser tab (see docs/design/README.md).
"""
import argparse
import base64
import json
import os
import urllib.error
import urllib.request

DEFAULT_ENDPOINT = "https://design.penpot.app/mcp/stream"
DEFAULT_SERVER = "penpot"


def _key(server: str, project: str | None) -> str:
    cfg = json.load(open(os.path.expanduser("~/.claude.json"), encoding="utf-8"))
    scope = cfg.get("projects", {}).get(project, {}) if project else cfg
    url = scope.get("mcpServers", {}).get(server, {}).get("url", "")
    if "userToken=" not in url:
        raise SystemExit(f"no MCP server entry {server!r} with a userToken in ~/.claude.json")
    return url.split("userToken=", 1)[1]


def _post(url: str, body: dict, sid: str | None = None):
    h = {"User-Agent": "candleviewer-design-tools", "Content-Type": "application/json",
         "Accept": "application/json, text/event-stream"}
    if sid:
        h["Mcp-Session-Id"] = sid
    try:
        r = urllib.request.urlopen(urllib.request.Request(url, json.dumps(body).encode(), h), timeout=300)
    except urllib.error.HTTPError as e:  # never echo the URL: it carries the key
        raise SystemExit(f"MCP HTTP error {e.code}") from None
    except urllib.error.URLError as e:
        raise SystemExit(f"MCP connection error: {type(e.reason).__name__}") from None
    sid = r.headers.get("Mcp-Session-Id") or sid
    data = [json.loads(l[5:]) for l in r.read().decode().splitlines() if l.startswith("data:")]
    return sid, data


def export(shape_id: str, out: str, fmt: str = "png", endpoint: str = DEFAULT_ENDPOINT,
           server: str = DEFAULT_SERVER, project: str | None = None) -> int:
    url = endpoint + "?userToken=" + _key(server, project)
    sid, _ = _post(url, {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                         "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                                    "clientInfo": {"name": "cv-export", "version": "1"}}})
    _post(url, {"jsonrpc": "2.0", "method": "notifications/initialized"}, sid)
    _, d = _post(url, {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                       "params": {"name": "export_shape", "arguments": {"shapeId": shape_id, "format": fmt}}}, sid)
    msg = d[-1]
    if "error" in msg:
        raise SystemExit("MCP error: " + json.dumps(msg["error"])[:400])
    for c in msg["result"].get("content", []):
        if c.get("type") == "image":
            raw = base64.b64decode(c["data"])
            os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
            open(out, "wb").write(raw)
            return len(raw)
        if c.get("type") == "text" and fmt == "svg":
            open(out, "w", encoding="utf-8").write(c["text"])
            return len(c["text"])
    raise SystemExit("no image in response: " + json.dumps(msg)[:400])


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("shape_id")
    p.add_argument("out")
    p.add_argument("--svg", action="store_true")
    p.add_argument("--endpoint", default=os.environ.get("PENPOT_MCP_ENDPOINT", DEFAULT_ENDPOINT))
    p.add_argument("--server", default=os.environ.get("PENPOT_MCP_SERVER", DEFAULT_SERVER))
    p.add_argument("--project", default=os.environ.get("PENPOT_MCP_PROJECT"))
    a = p.parse_args()
    n = export(a.shape_id, a.out, "svg" if a.svg else "png", a.endpoint, a.server, a.project)
    print(f"wrote {a.out} ({n} bytes)")
