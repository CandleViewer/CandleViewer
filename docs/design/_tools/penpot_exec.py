"""Run a JavaScript file through a Penpot MCP server's `execute_code` tool, without retyping it.

Usage:  python docs/design/_tools/penpot_exec.py <file.js> [--out answer.txt]
            [--server NAME] [--project DIR] [--endpoint URL]
The file runs in the connected Penpot plugin exactly like one `execute_code` call: a function body
with `penpot`, `penpotUtils` and `storage` in scope, so a loader sent here is visible to later tool
calls. Its content goes to the selected MCP server (the hosted design.penpot.app for the default
entry) and runs in your own plugin, under docs/design/README.md's rule: `execute_code` only on the
file named in the ticket. A request body over about 90 KB (the server refuses bodies near 110 KB) is
sent in parts kept in `storage.__cvx_<random>` (one key per run, removed on success and on failure),
then joined and run as one async function body. The plugin sandbox refuses the AsyncFunction
constructor, so the parts run through `Function`.
The key is the `userToken` of an MCP server entry in ~/.claude.json and is never printed. Entry,
endpoint and env rules match penpot_export.py: --server (default `penpot`, user scope), --project
for a local-scope entry, the endpoint from the entry's own URL unless --endpoint overrides it
(https, or http on loopback only, opened without a proxy; redirects are refused), PENPOT_MCP_SERVER
/ _PROJECT / _ENDPOINT. Prints the tool's text answer; --out gets the same text (truncated first).
Exit 0: an answer; 2: a tool error (a sleeping tab included); 1: the request failed; 64: bad usage.
Requires the Penpot MCP plugin to be connected in an open browser tab.
"""
import argparse
import json
import os
import re
import secrets
import string
import sys
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_SERVER = "penpot"
ENDPOINT_RE = re.compile(r"https://[^\s/?#@]+(/[^\s?#]*)?"
                         r"|http://(127\.0\.0\.1|localhost)(:\d+)?(/[^\s?#]*)?")
BODY_LIMIT = 90_000  # bytes of the encoded code per request; the server refuses bodies near 110 KB
PART_BUDGET = 60_000  # bytes of the encoded literal per part
ASSEMBLE = string.Template("""const p = storage[$slot] || {};
delete storage[$slot];
let src = "";
for (let i = 1; i <= $n; i++) {
  if (typeof p[i] !== "string") throw new Error("penpot_exec: missing part " + i + " of $n");
  src += p[i];
}
if (src.length !== $units) {
  throw new Error("penpot_exec: length mismatch, want $units, got " + src.length);
}
const pu = typeof penpotUtils === "undefined" ? undefined : penpotUtils;
const body = "return (async () => {\\n" + src + "\\n})();";
// pass this call's console through, so the server captures the logs as in a single call
const run = new Function("penpot", "penpotUtils", "storage", "console", body);
return await run(penpot, pu, storage, console);
""")


class _Usage(argparse.ArgumentParser):
    def error(self, message):  # exit 2 means a tool error here
        self.print_usage(sys.stderr)
        self.exit(64, f"{self.prog}: error: {message}\n")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # a redirect would carry the key to another URL


# _entry, _redact and the endpoint rule: keep in sync with penpot_export.py
def _entry(server: str, project: str | None) -> tuple[str, str]:
    """(endpoint, key) of an MCP server entry: user scope, or a project's local scope."""
    cfg = json.load(open(os.path.expanduser("~/.claude.json"), encoding="utf-8"))
    project = os.path.abspath(os.path.expanduser(project)) if project else None
    scope = cfg.get("projects", {}).get(project, {}) if project else cfg
    url = scope.get("mcpServers", {}).get(server, {}).get("url", "")
    if not url.partition("userToken=")[2]:
        where = f"project {project!r}" if project else "user scope"
        raise SystemExit(f"no MCP server entry {server!r} with a userToken in ~/.claude.json"
                         f" ({where})")
    return url.split("?", 1)[0], url.split("userToken=", 1)[1]


def _redact(text: str, key: str) -> str:
    token = re.split(r"[&#]", key, maxsplit=1)[0]  # a server may echo the bare token
    forms = set()
    for k in (key, token):
        forms |= {k, json.dumps(k)[1:-1], urllib.parse.quote(k, safe=""),
                  urllib.parse.quote_plus(k)}
    for k in sorted(forms - {""}, key=len, reverse=True):
        text = text.replace(k, "<key>")
    return text


def _post(url: str, body: dict, sid: str | None = None):
    h = {"User-Agent": "candleviewer-design-tools", "Content-Type": "application/json",
         "Accept": "application/json, text/event-stream"}
    if sid:
        h["Mcp-Session-Id"] = sid
    # urllib/http.client messages embed the URL, which carries the key: report the error type only
    try:
        req = urllib.request.Request(url, json.dumps(body, ensure_ascii=False).encode(), h)
        handlers: list = [_NoRedirect()]
        if url.startswith("http://"):  # loopback only: never through an env proxy
            handlers.append(urllib.request.ProxyHandler({}))
        r = urllib.request.build_opener(*handlers).open(req, timeout=600)
        sid = r.headers.get("Mcp-Session-Id") or sid
        # split on \n only: JSON.stringify leaves U+2028/U+2029/U+0085 raw, which splitlines() cuts
        data = [json.loads(x[5:]) for x in r.read().decode().split("\n") if x.startswith("data:")]
    except urllib.error.HTTPError as e:
        raise SystemExit(f"MCP HTTP error {e.code}") from None
    except urllib.error.URLError as e:
        raise SystemExit(f"MCP connection error: {type(e.reason).__name__}") from None
    except Exception as e:
        raise SystemExit(f"MCP request failed: {type(e).__name__}") from None
    return sid, data


def _call(url: str, sid: str | None, n: int, code: str, key: str) -> tuple[int, str]:
    _, frames = _post(url, {"jsonrpc": "2.0", "id": n, "method": "tools/call",
                            "params": {"name": "execute_code", "arguments": {"code": code}}}, sid)
    frame = next((f for f in reversed(frames) if isinstance(f, dict) and f.get("id") == n), None)
    if frame is None:
        return 1, "the MCP reply carried no answer for this call"
    if "error" in frame:
        return 2, "MCP error: " + _redact(json.dumps(frame["error"]), key)
    res = frame.get("result")
    if not isinstance(res, dict):
        return 1, "the MCP reply carried no result"
    content = res.get("content") if isinstance(res.get("content"), list) else []
    texts = [c.get("text") for c in content if isinstance(c, dict) and c.get("type") == "text"]
    text = "\n".join(t for t in texts if isinstance(t, str))
    failed = res.get("isError") or text.startswith("Tool execution failed")
    return (2 if failed else 0), _redact(text, key)


def _encoded(text: str) -> int:
    return len(json.dumps(text, ensure_ascii=False).encode())


def _parts(code: str) -> list[str]:
    out, i = [], 0
    while i < len(code):  # code points, so a surrogate pair is never cut
        n = min(len(code) - i, PART_BUDGET)
        while n > 1 and _encoded(code[i:i + n]) > PART_BUDGET:
            n //= 2
        out.append(code[i:i + n])
        i += n
    return out


def run(code: str, server: str = DEFAULT_SERVER, project: str | None = None,
        endpoint: str | None = None) -> tuple[int, str]:
    base, key = _entry(server, project)
    src = "--endpoint / PENPOT_MCP_ENDPOINT" if endpoint else f"the URL of entry {server!r}"
    endpoint = endpoint or base
    if not ENDPOINT_RE.fullmatch(endpoint):
        raise SystemExit(f"{src} must be https (http on loopback only), with no query")
    url = endpoint + "?userToken=" + key
    sid, _ = _post(url, {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                         "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                                    "clientInfo": {"name": "cv-exec", "version": "1"}}})
    _post(url, {"jsonrpc": "2.0", "method": "notifications/initialized"}, sid)
    if _encoded(code) <= BODY_LIMIT:
        return _call(url, sid, 2, code, key)
    parts = _parts(code)
    slot = json.dumps("__cvx_" + secrets.token_hex(4))  # one storage key per run
    for i, part in enumerate(parts, 1):
        literal = json.dumps(part, ensure_ascii=False)
        store = (f"storage[{slot}] = storage[{slot}] || {{}};\nstorage[{slot}][{i}] = {literal};\n"
                 f"return {{ part: {i}, of: {len(parts)} }};")
        try:
            rc, text = _call(url, sid, 2 + i, store, key)
        except SystemExit as e:
            rc, text = 1, str(e.code)
        if rc:
            try:  # best effort: drop the parts already stored
                _call(url, sid, 3 + len(parts), f"delete storage[{slot}];\nreturn true;", key)
            except SystemExit:
                pass
            return rc, f"part {i}/{len(parts)} failed (re-send the whole file): {text}"
    units = len(code.encode("utf-16-le")) // 2  # JS string length counts UTF-16 code units
    assemble = ASSEMBLE.substitute(slot=slot, n=len(parts), units=units)
    return _call(url, sid, 3 + len(parts), assemble, key)


if __name__ == "__main__":
    p = _Usage(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("file")
    p.add_argument("--out")
    p.add_argument("--server", default=os.environ.get("PENPOT_MCP_SERVER") or DEFAULT_SERVER)
    p.add_argument("--project", default=os.environ.get("PENPOT_MCP_PROJECT") or None)
    p.add_argument("--endpoint", default=os.environ.get("PENPOT_MCP_ENDPOINT") or None)
    a = p.parse_args()
    if a.out:  # truncate first, so a failed run never leaves a stale answer behind
        os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
        open(a.out, "w", encoding="utf-8").close()
    with open(a.file, encoding="utf-8") as fh:
        rc, answer = run(fh.read(), a.server, a.project, a.endpoint)
    sys.stdout.reconfigure(errors="backslashreplace")
    print(answer)
    if a.out:
        with open(a.out, "w", encoding="utf-8", errors="backslashreplace") as fh:
            fh.write(answer)
    raise SystemExit(rc)
