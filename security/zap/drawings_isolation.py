#!/usr/bin/env python3
"""E14-X03 (#549, AC4): the Owner's drawings for the ZAP drawings profile, seeded and checked.

`seed` posts the fixture (`.zap/e14-drawings-seed.json`: `create` operations with fixed client ids)
as the Owner and writes the rows the stack holds. After the Manager's scan, `verify` lists the
fixture's symbol twice. As the Owner the rows must be exactly as seeded: a PUT, a DELETE or a batch
of the scan that changed one is a cross-owner write that succeeded (DR12, DR21). As the Manager no
row may be a seeded one or the Owner's: a cross-owner read that succeeded (DR20). The foreign 404
and the batch 409 are the contract and leave every row as it was. A session is the env file
`mint_sessions.py` wrote, sent as a browser would (SR-041); the target must be loopback, as there.
No credential is printed. Stdlib only.

Usage: drawings_isolation.py seed --target URL --session FILE --fixture FILE --out FILE
       drawings_isolation.py verify --target URL --owner-session FILE --manager-session FILE
                                    --seeded FILE
Exit: 0 clean, 1 a failed check or call.
"""

from __future__ import annotations

import argparse
import http.client
import json
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

#: One call: method, base URL, path with its query, a JSON body or None, headers -> status, JSON.
Send = Callable[[str, str, str, dict[str, Any] | None, dict[str, str]], tuple[int, Any]]


class Refused(RuntimeError):
    """A check or call that failed; the message names the step, never a credential."""


def check_target(target: str) -> str:
    parts = urlsplit(target)
    loopback = parts.hostname in ("127.0.0.1", "localhost") and parts.path in ("", "/")
    if parts.scheme != "http" or not loopback or parts.username or parts.password or parts.query:
        raise Refused("only http://127.0.0.1:<port> or localhost, with no userinfo, path or query")
    return target.rstrip("/")


def session_headers(session: Path) -> dict[str, str]:
    lines = session.read_text(encoding="ascii").splitlines()
    values = dict(line.split("=", 1) for line in lines if "=" in line)
    bearer, csrf = values.get("ZAP_AUTH_TOKEN"), values.get("ZAP_CSRF_TOKEN")
    if not bearer or not csrf:
        raise Refused(f"{session.name} holds no session")
    return {
        "Authorization": f"Bearer {bearer}",
        "X-CSRF-Token": csrf,
        "Cookie": f"__Host-cv_csrf={csrf}",
    }


def exchange(
    method: str, target: str, path: str, body: dict[str, Any] | None, headers: dict[str, str]
) -> tuple[int, Any]:
    """One plain-HTTP exchange with the loopback target `check_target` admitted."""
    parts = urlsplit(target)
    connection = http.client.HTTPConnection(parts.hostname or "", parts.port, timeout=30)
    data = None if body is None else json.dumps(body).encode()
    try:
        connection.request(method, path, data, {"Content-Type": "application/json", **headers})
        response = connection.getresponse()
        status, raw = response.status, response.read(4 << 20)
    finally:
        connection.close()
    try:
        return status, json.loads(raw) if raw else None
    except ValueError:  # not JSON, or not UTF-8: no body to read
        return status, None


def listing(send: Send, target: str, headers: dict[str, str], symbol: str) -> list[dict[str, Any]]:
    """The one page of drawings the session lists for `symbol`; more than a page cannot be read
    through, so it fails (the Owner's ids sort first, but a flood is a finding to look at)."""
    status, page = send("GET", target, f"/drawings?symbol={symbol}&limit=500", None, headers)
    if status != 200 or not isinstance(page, dict) or not isinstance(page.get("items"), list):
        raise Refused(f"GET /drawings: HTTP {status}, no page of drawings")
    if (page.get("meta") or {}).get("next_cursor"):
        raise Refused("GET /drawings: more than one page: the Owner's rows cannot be ruled out")
    items: list[dict[str, Any]] = page["items"]
    return items


def seed(
    send: Send, target: str, headers: dict[str, str], fixture: dict[str, Any]
) -> dict[str, Any]:
    status, result = send("POST", target, "/drawings/batch", fixture, headers)
    created = result.get("created") if isinstance(result, dict) else None
    wanted = sorted(op["id"] for op in fixture["operations"])
    if status != 200 or not isinstance(created, list) or sorted(r["id"] for r in created) != wanted:
        raise Refused(f"POST /drawings/batch: HTTP {status}, not every fixture row was created")
    return {"created": created}


def verify(
    send: Send, target: str, owner: dict[str, str], manager: dict[str, str], seeded: dict[str, Any]
) -> list[str]:
    rows: list[dict[str, Any]] = seeded["created"]
    symbol, owner_id, ids = rows[0]["symbol"], rows[0]["owner_user_id"], {r["id"] for r in rows}
    now = {row["id"]: row for row in listing(send, target, owner, symbol)}
    problems = [f"an Owner's drawing {i} the seed did not make appeared" for i in set(now) - ids]
    for row in rows:
        if (found := now.get(row["id"])) is None:
            problems.append(f"the Owner's drawing {row['id']} is gone: a cross-owner delete")
        elif found != row:
            fields = sorted(k for k in {*row, *found} if row.get(k) != found.get(k))
            problems.append(f"the Owner's drawing {row['id']} changed ({', '.join(fields)})")
    for row in listing(send, target, manager, symbol):
        if row.get("id") in ids or row.get("owner_user_id") == owner_id:
            problems.append(f"the Manager lists the Owner's drawing {row.get('id')} (DR20)")
    return problems


def main(argv: Sequence[str] | None = None, send: Send = exchange) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n", 1)[0])
    commands = ap.add_subparsers(dest="command", required=True)
    one, two = commands.add_parser("seed"), commands.add_parser("verify")
    for command in (one, two):
        command.add_argument("--target", required=True)
    for name in ("session", "fixture", "out"):
        one.add_argument(f"--{name}", type=Path, required=True)
    for name in ("owner-session", "manager-session", "seeded"):
        two.add_argument(f"--{name}", type=Path, required=True)
    args = ap.parse_args(argv)
    try:
        target = check_target(args.target)
        if args.command == "seed":
            fixture = json.loads(args.fixture.read_text(encoding="utf-8"))
            seeded = seed(send, target, session_headers(args.session), fixture)
            args.out.write_text(json.dumps(seeded, indent=1) + "\n", encoding="utf-8")
            print(f"drawings_isolation: seeded {len(seeded['created'])} drawing(s) of the Owner")
            return 0
        seeded = json.loads(args.seeded.read_text(encoding="utf-8"))
        owner, manager = session_headers(args.owner_session), session_headers(args.manager_session)
        problems = verify(send, target, owner, manager, seeded)
    except (Refused, OSError, ValueError, KeyError, IndexError, http.client.HTTPException) as exc:
        print(f"::error title=drawings_isolation::{type(exc).__name__}: {exc}")
        return 1
    for problem in problems:
        print(f"::error title=drawings_isolation::{problem}")
    if not problems:
        print("drawings_isolation: the Owner's drawings are unchanged and the Manager lists none")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
