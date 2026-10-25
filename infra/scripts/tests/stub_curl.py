"""A stand-in for `curl` in `test_demo_host_owner_first_run.py` (#3180). Not collected by pytest.

The script under test hands curl each request as a config on stdin (`--config -`): the URL (the
invite token in its path), the bearer token, the CSRF cookie and header, and the JSON body with the
secrets typed at its prompts. This stub records its arguments to `argv.jsonl`, never what it reads
on stdin: it checks the request against the scenario the test wrote (the route, the path parameter,
the body members, the session headers, 22's schema for the body) and records the outcome as names,
booleans and validator names in `requests.jsonl`, so no record holds a value the script was given.
It answers as `curl --dump-header - --write-out '\\n%{http_code}'` prints: the head, the body, the
status. Each call's route (never its raw path, which may hold the token) also goes to the
`sequence.log` the docker stub shares, so a test sees the order of both. A scenario call with
`exit` ends the stub with that status and no output (curl's 7: the connection was refused).
`CV_STUB_DIR` names the directory of the scenario, the state and the logs.
"""

from __future__ import annotations

import json
import os
import re
import sys
import uuid
from pathlib import Path
from typing import Any

BASE = "http://127.0.0.1:8000"
#: A request's config is a few hundred bytes: one over this bound fails the run.
_MAX_CONFIG = 1 << 20
CSRF_COOKIE = "__Host-cv_csrf"
_CONFIG_LINE = re.compile(r'([a-z][a-z0-9-]*)\s*=\s*"((?:[^"\\]|\\.)*)"')
_ESCAPES = {"t": "\t", "n": "\n", "r": "\r", "v": "\v"}


def _unescape(text: str) -> str:
    """A quoted curl config value: `\\t`, `\\n`, `\\r`, `\\v`, else the escaped character."""
    return re.sub(r"\\(.)", lambda m: _ESCAPES.get(m[1], m[1]), text)


def _config(text: str) -> list[tuple[str, str]]:
    items = []
    for line in text.splitlines():
        if line.strip():
            matched = _CONFIG_LINE.fullmatch(line.strip())
            if matched is None:
                _fail('a config line curl would not read as `name = "value"`')
            items.append((matched[1], _unescape(matched[2])))
    return items


def _fail(why: str) -> None:
    print(f"stub curl: {why}", file=sys.stderr)
    raise SystemExit(2)


def _template(pattern: str) -> re.Pattern[str]:
    return re.compile(re.sub(r"\\\{(\w+)\\\}", r"(?P<\1>[^/]+)", re.escape(pattern)))


def main() -> int:
    stub = Path(os.environ["CV_STUB_DIR"])
    with (stub / "argv.jsonl").open("a", encoding="utf-8") as log:
        log.write(json.dumps(sys.argv[1:]) + "\n")
    if sys.argv[1:2] != ["-q"] or "--config" not in sys.argv:
        _fail("-q first, then --config -")
    text = sys.stdin.read(_MAX_CONFIG + 1)
    if len(text) > _MAX_CONFIG:
        _fail("a config over the stub's bound")
    config = _config(text)
    url = [v for k, v in config if k == "url"]
    if len(url) != 1 or not url[0].startswith(BASE + "/"):
        _fail(f"one url, on {BASE}")
    method = ([v for k, v in config if k == "request"] or ["GET"])[-1]
    path = url[0][len(BASE) :]
    headers: dict[str, str] = {}
    for name, value in (v.partition(":")[::2] for k, v in config if k == "header"):
        headers[name.strip().lower()] = value.strip()
    raw = [v for k, v in config if k == "data-binary"]
    scenario = json.loads((stub / "scenario.json").read_text(encoding="utf-8"))
    state_file = stub / "state.json"
    state = json.loads(state_file.read_text(encoding="utf-8")) if state_file.exists() else {}
    record: dict[str, Any] = {"method": method, "header_names": sorted(headers)}
    matching = (r for r in scenario["routes"] if r["method"] == method)
    route = next((r for r in matching if _template(r["path"]).fullmatch(path)), None)
    if route is None:
        record["route"] = "unmatched"
        call: dict[str, Any] = {"status": 404, "body": {"detail": "Not Found"}}
    else:
        key = f"{method} {route['path']}"
        record["route"] = key
        done = state.setdefault("calls", {}).get(key, 0)
        state["calls"][key] = done + 1
        if done >= len(route["calls"]):
            record["exhausted"] = True
            call = {"status": 599, "body": None}
        else:
            call = route["calls"][done]
        matched = _template(route["path"]).fullmatch(path)
        params = matched.groupdict() if matched else {}
        record["path_ok"] = params == call.get("path", params)
        body = json.loads(raw[-1]) if raw else None
        record["body_keys"] = sorted(body) if isinstance(body, dict) else body
        wanted = call.get("expect", {})
        members = body if isinstance(body, dict) else {}
        record["body_ok"] = {k: k in members and members[k] == v for k, v in wanted.items()}
        if route.get("schema") is not None:  # only the runs that check bodies pay the import
            from jsonschema import Draft202012Validator

            errors = Draft202012Validator(route["schema"]).iter_errors(body)
            record["schema_errors"] = sorted([e.json_path, str(e.validator)] for e in errors)
        if route["session"]:
            session = state.get("session") or {}
            cookie = f"{CSRF_COOKIE}={session.get('csrf')}"
            record["session_ok"] = bool(session) and (
                headers.get("authorization") == f"Bearer {session.get('access')}"
                and cookie in [c.strip() for c in headers.get("cookie", "").split(";")]
                and headers.get("x-csrf-token") == session.get("csrf")
            )
        if "idempotency-key" in headers:
            key_value = headers["idempotency-key"]
            record["idempotency_key"] = key_value
            record["idempotency_key_is_uuid4"] = _is_uuid4(key_value)
        if call.get("session"):
            state["session"] = call["session"]
    with (stub / "requests.jsonl").open("a", encoding="utf-8") as log:
        log.write(json.dumps(record) + "\n")
    with (stub / "sequence.log").open("a", encoding="utf-8") as log:
        log.write(f"curl {record['route']}\n")
    state_file.write_text(json.dumps(state), encoding="utf-8")
    if "exit" in call:
        return int(call["exit"])
    for option in ("--dump-header", "--write-out"):
        if option not in sys.argv:
            _fail(f"{option} is how the script reads the status and the cookies")
    status = int(call["status"])
    head = [f"HTTP/1.1 {status} Stub", "content-type: application/json"]
    for name, value in (call.get("cookies") or {}).items():
        head.append(f"set-cookie: {name}={value}; Max-Age=600; Path=/; SameSite=strict; Secure")
    text = "" if call.get("body") is None else json.dumps(call["body"])
    sys.stdout.write("\r\n".join(head) + "\r\n\r\n" + text + "\n" + str(status))
    return 0


def _is_uuid4(text: str) -> bool:
    try:
        return uuid.UUID(text).version == 4 and str(uuid.UUID(text)) == text
    except ValueError:
        return False


if __name__ == "__main__":
    raise SystemExit(main())
