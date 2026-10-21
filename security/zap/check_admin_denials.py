#!/usr/bin/env python3
"""E42-X03: the ZAP admin profile's denial gate (AC5: "ZAP authenticated as a manager: no /admin/*
endpoint returns anything other than 403, and every attempt appears in the audit log").

For each role it reads what `admin_requests.py` planned (`<role>-requests.json`), the log of
the role's denial run (`<role>-denials.log`) and the audit rows the workflow exported for the
synthetic users (`audit-rows.json`: `username`, `request_id`, `action`, `outcome`), and fails on:

- a requestor job that did not run to its end, a status other than the planned one (ZAP 2.17
  warns `Difference in response code values ...`, older ZAP `response code ... does not
  match`), or a plan failure;
- a refused request with no `denied` record of its user: matched by its request id (sent as
  `X-Correlation-Id` and `X-Request-Id`), which the API keeps as the record's `request_id`, else
  by one of the user's `denied` records of the `NAMELESS_DENIALS` actions, the refusals a planned
  request meets whose record names no request id; no other record without a request id counts;
- a nameless `denied` record of those actions that no planned request needed (the budget is tight);
- a CSRF refusal: an `auth.csrf_refused` record of either user, or that event in the API's log
  (`--api-log`; a throttled refusal is logged with no record). Its `403 csrf_token_invalid` is
  the planned status, but the request never reached RBAC: the scan lost its CSRF pair;
- a `KNOWN_SILENT` operation that has a record after all: it is fixed, so its entry goes.

What a nameless record proves is less than a request id does, in three ways:

1. For the operations it answers for, the proof is cardinality, not identity: one refusal with no
   record and one request that wrote two nameless records cancel out.
2. So the budget is asserted tight: a nameless record left after every planned refusal has its
   own is a failure, not a spare (#3990 names these records, and the stand-ins go).
3. A step-up refusal comes before RBAC is consulted, so for those routes the role's refusal by
   RBAC is held by the route x actor x elevation cells (none, stale, fresh), not by this nightly,
   which only ever sends the none state.

Stdlib only. Usage: check_admin_denials.py --dir DIR --audit FILE --user ROLE=USERNAME ...
[--api-log FILE]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

#: Operations whose refusal writes no record today, by finding; strict, as an xfail is.
KNOWN_SILENT: dict[str, str] = {
    "GET /admin/support-bundle/{job_id}": "X03-F1 (#2836): refused with no record",
}
_STARTED = re.compile(r"Job requestor started", re.I)
_FINISHED = re.compile(r"Job requestor finished", re.I)
_MISMATCH = re.compile(
    r"response code \d+ (?:does not|didn.t) match|Difference in response code values[^\n]*", re.I
)
_PLAN_FAILED = re.compile(r"Automation plan (?:failures|failed)", re.I)
#: The denial records a planned request can meet without its request id: a step-up refusal (the
#: session chart writes it), and the invites router's `rbac.denied`, whose owner check passes no
#: request id to `enforce` (#3990, with the other records that lose it).
NAMELESS_DENIALS = frozenset({"auth.step_up_required", "rbac.denied"})
#: A refusal before RBAC: the request's CSRF pair was missing or wrong (api/csrf.py).
CSRF_REFUSED = "auth.csrf_refused"
#: That refusal's events in the API's log, whatever its renderer: `auth.csrf_refused` and its
#: `.unaudited`, `.audit_slow` and `.audit_unavailable` forms, never a longer name.
_CSRF_EVENT = re.compile(r"(?<![\w.])auth\.csrf_refused(?!\w)")


def log_problems(role: str, log: str) -> list[str]:
    """The run log's evidence that the requestor ran to its end and every status was planned."""
    problems: list[str] = []
    if not _STARTED.search(log) or not _FINISHED.search(log):
        problems.append(f"{role}: the denial requestor did not run to its end")
    # ZAP 2.17 repeats each warning under "Automation plan warnings:": one problem per message.
    mismatches = dict.fromkeys(match.group(0).strip() for match in _MISMATCH.finditer(log))
    problems += [f"{role}: {mismatch}" for mismatch in mismatches]
    if _PLAN_FAILED.search(log):
        problems.append(f"{role}: ZAP reported automation plan failures")
    return problems


def audit_problems(
    role: str, requests: list[dict[str, Any]], rows: list[dict[str, Any]]
) -> list[str]:
    """Each refused request's `denied` record among `rows` (this role's user only)."""
    denied = [row for row in rows if row.get("outcome") == "denied"]
    named = [row for row in denied if row.get("request_id") and row.get("action") != CSRF_REFUSED]
    by_id = Counter(str(row["request_id"]) for row in named)
    nameless = (row for row in denied if not row.get("request_id"))
    spare = sum(1 for row in nameless if row.get("action") in NAMELESS_DENIALS)
    problems: list[str] = []
    lost = sum(1 for row in rows if row.get("action") == CSRF_REFUSED)
    if lost:
        problems.append(
            f"{role}: {lost} {CSRF_REFUSED} record(s): the scan lost its CSRF pair, so those "
            "requests never reached RBAC"
        )
    for item in requests:
        if not item.get("recorded", True):
            continue
        operation, matched = item["operation"], by_id[item["correlation_id"]] > 0
        if operation in KNOWN_SILENT:
            if matched:
                problems.append(f"{role}: {operation} is recorded now: drop it from KNOWN_SILENT")
        elif not matched and spare > 0:
            spare -= 1  # a nameless refusal record answers for one request
        elif not matched:
            problems.append(f"{role}: {operation} was refused with no audit record")
    if spare:  # the count proves a refusal only while no nameless record is left over
        problems.append(f"{role}: {spare} nameless denial record(s) answer for no planned request")
    return problems


def api_log_problems(log: str) -> list[str]:
    """The API's own evidence of a CSRF refusal, recorded or throttled."""
    count = len(_CSRF_EVENT.findall(log))
    if not count:
        return []
    return [f"the API logged {count} {CSRF_REFUSED} event(s): the scan lost its CSRF pair"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--dir", type=Path, required=True, help="the plans' and logs' directory")
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--user", action="append", required=True, help="ROLE=USERNAME")
    parser.add_argument("--api-log", type=Path, help="the API's log, for CSRF refusals")
    args = parser.parse_args(argv)
    users = dict(item.split("=", 1) for item in args.user)
    try:
        rows: list[dict[str, Any]] = json.loads(args.audit.read_text(encoding="utf-8")) or []
        problems: list[str] = []
        if args.api_log is not None:
            problems += api_log_problems(args.api_log.read_text(encoding="utf-8", errors="replace"))
        for role, username in sorted(users.items()):
            planned = json.loads((args.dir / f"{role}-requests.json").read_text(encoding="utf-8"))
            log = (args.dir / f"{role}-denials.log").read_text(encoding="utf-8", errors="replace")
            mine = [row for row in rows if row.get("username") == username]
            problems += log_problems(role, log)
            problems += audit_problems(role, planned, mine)
            print(f"check_admin_denials: {role}: {len(planned)} planned, {len(mine)} records")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"::error title=zap-admin::unreadable input: {type(exc).__name__}: {exc}")
        return 2
    for problem in problems:
        print(f"::error title=zap-admin::{problem}")
    if not problems:
        print("check_admin_denials: every refusal was planned and recorded")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
