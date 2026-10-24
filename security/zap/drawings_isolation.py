#!/usr/bin/env python3
"""E14-X03 (#549, AC4): the Owner's drawings for the ZAP drawings profile, seeded and checked.

`seed` posts the fixture (`.zap/e14-drawings-seed.json`: `create` operations with fixed client ids)
as the Owner and writes the rows the stack holds. After the Manager's scan, `verify` first writes to
each seeded row as the Manager itself, so the write half does not rest on what ZAP aimed at: a batch
`update` and `delete` carrying the row's live `updated_at` must answer the batch 409
(`target_unavailable`, DR21), a PUT and a DELETE the foreign 404 (`not_found`, DR20). A 2xx is a
cross-owner write that succeeded (DR12); any other answer is a probe that never reached the owner
check, which fails too. It then lists the fixture's symbol twice, every page. As the Owner the rows
must be exactly as seeded: a write of the scan or of a probe that changed one is a cross-owner write
(DR12, DR21). As the Manager no row may be a seeded one or the Owner's: a cross-owner read that
succeeded (DR20). The refusals leave every row as it was. A session is the env file
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
from typing import Any, NamedTuple
from urllib.parse import urlencode, urlsplit
from uuid import UUID

#: One call: method, base URL, path with its query, a JSON body or None, headers -> status, JSON.
Send = Callable[[str, str, str, dict[str, Any] | None, dict[str, str]], tuple[int, Any]]

#: The fields of a Drawing that a DrawingInput holds (22-api): what a PUT or an `update` replaces.
INPUT = (
    "symbol",
    "tool",
    "layout_id",
    "geometry",
    "style",
    "label",
    "locked",
    "visible",
    "z_index",
)
PROBE_LABEL = "zap cross-owner probe"
#: 500 rows a page; a scan's rows past 20 pages are a flood to look at, not a list to read.
MAX_PAGES = 20


class Refused(RuntimeError):
    """A check or call that failed; the message names the step, never a credential."""


def check_target(target: str) -> str:
    parts = urlsplit(target)
    loopback = parts.hostname in ("127.0.0.1", "localhost") and parts.path in ("", "/")
    extra = parts.username or parts.password or parts.query or parts.fragment
    try:
        port = parts.port  # read now, so a port that is no number fails here, not at a call
    except ValueError:
        port = -1
    if parts.scheme != "http" or not loopback or extra or port == -1:
        raise Refused(
            "only http://127.0.0.1:<port> or localhost, with no userinfo, path, query or fragment"
        )
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
    """Every drawing the session lists for `symbol`, page by page, at most `MAX_PAGES`; each one an
    object with an `id` and an `owner_user_id`, or the list cannot rule the Owner's rows out."""
    query, items = {"symbol": symbol, "limit": "500"}, list[dict[str, Any]]()
    for _ in range(MAX_PAGES):
        status, page = send("GET", target, f"/drawings?{urlencode(query)}", None, headers)
        meta = page.get("meta") if isinstance(page, dict) else None
        if status != 200 or not isinstance(meta, dict) or not isinstance(page.get("items"), list):
            raise Refused(f"GET /drawings: HTTP {status}, no page of drawings")
        for item in page["items"]:
            if not isinstance(item, dict) or not {"id", "owner_user_id"} <= item.keys():
                raise Refused("GET /drawings: an item with no id or no owner")
            items.append(item)
        if not (cursor := meta.get("next_cursor")):
            return items
        if not isinstance(cursor, str):
            raise Refused("GET /drawings: a next_cursor that is no string")
        query["cursor"] = cursor
    raise Refused(f"GET /drawings: over {MAX_PAGES} pages: the Owner's rows cannot be ruled out")


def seed(
    send: Send, target: str, headers: dict[str, str], fixture: dict[str, Any]
) -> dict[str, Any]:
    status, result = send("POST", target, "/drawings/batch", fixture, headers)
    created = result.get("created") if isinstance(result, dict) else None
    wanted = sorted(op["id"] for op in fixture["operations"])
    if status != 200 or not isinstance(created, list) or sorted(r["id"] for r in created) != wanted:
        raise Refused(f"POST /drawings/batch: HTTP {status}, not every fixture row was created")
    return {"created": created}


def _said(answer: Any) -> str:
    """A refusal's `code`, or for the batch's `conflict` its first error's `rule`."""
    if not isinstance(answer, dict):
        return ""
    errors = answer.get("errors")
    if answer.get("code") == "conflict" and isinstance(errors, list) and errors:
        first = errors[0]
        return str(first.get("rule")) if isinstance(first, dict) else ""
    return str(answer.get("code") or "")


class Probe(NamedTuple):
    """One write of the Manager's to the Owner's row, and the refusal the contract gives it."""

    what: str
    method: str
    path: str
    body: dict[str, Any] | None
    status: int
    said: str  # the refusal's `code`, or the batch conflict's `rule`
    threat: str


def probes(row: dict[str, Any]) -> list[Probe]:
    """The batch first, while the seed's `updated_at` is still the row's, then the PUT and the
    DELETE. The PUT body is the row's own input with the label changed, so it passes validation
    and only the owner check can refuse it."""
    ident = str(UUID(row["id"]))
    drawing = {key: row[key] for key in INPUT if key in row} | {"label": PROBE_LABEL}
    token = row["updated_at"]
    update = {"op": "update", "id": ident, "if_match": token, "drawing": drawing}
    delete = {"op": "delete", "id": ident, "if_match": token}
    batch, one = (409, "target_unavailable", "DR12, DR21"), (404, "not_found", "DR12, DR20")
    return [
        Probe("batch update", "POST", "/drawings/batch", {"operations": [update]}, *batch),
        Probe("batch delete", "POST", "/drawings/batch", {"operations": [delete]}, *batch),
        Probe("PUT", "PUT", f"/drawings/{ident}", drawing, *one),
        Probe("DELETE", "DELETE", f"/drawings/{ident}", None, *one),
    ]


def probe(
    send: Send, target: str, manager: dict[str, str], rows: list[dict[str, Any]]
) -> list[str]:
    problems = []
    for row in rows:
        for p in probes(row):
            status, answer = send(p.method, target, p.path, p.body, manager)
            said, name = _said(answer), f"the Manager's {p.what} of the Owner's drawing {row['id']}"
            if 200 <= status < 300:
                problems.append(f"{name} answered HTTP {status}: a cross-owner write ({p.threat})")
            elif (status, said) != (p.status, p.said):
                problems.append(
                    f"{name} answered HTTP {status} {said or '(no code)'}, not {p.status} {p.said}:"
                    " the probe never reached the owner check"
                )
    return problems


def verify(
    send: Send, target: str, owner: dict[str, str], manager: dict[str, str], seeded: dict[str, Any]
) -> list[str]:
    rows: list[dict[str, Any]] = seeded["created"]
    symbol, owner_id, ids = rows[0]["symbol"], rows[0]["owner_user_id"], {r["id"] for r in rows}
    problems = probe(send, target, manager, rows)
    now = {row["id"]: row for row in listing(send, target, owner, symbol)}
    problems += [f"an Owner's drawing {i} the seed did not make appeared" for i in set(now) - ids]
    for row in rows:
        if (found := now.get(row["id"])) is None:
            problems.append(f"the Owner's drawing {row['id']} is gone: a cross-owner delete")
        elif found != row:
            fields = sorted(k for k in {*row, *found} if row.get(k) != found.get(k))
            problems.append(f"the Owner's drawing {row['id']} changed ({', '.join(fields)})")
    for row in listing(send, target, manager, symbol):
        if row["id"] in ids or row["owner_user_id"] == owner_id:
            problems.append(f"the Manager lists the Owner's drawing {row['id']} (DR20)")
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
    failures = (Refused, OSError, ValueError, KeyError, IndexError, TypeError, AttributeError)
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
    except (*failures, http.client.HTTPException) as exc:
        print(f"::error title=drawings_isolation::{type(exc).__name__}: {exc}")
        return 1
    for problem in problems:
        print(f"::error title=drawings_isolation::{problem}")
    if not problems:
        print(
            "drawings_isolation: the Manager's writes were refused, the Owner's drawings are"
            " unchanged and the Manager lists none"
        )
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
