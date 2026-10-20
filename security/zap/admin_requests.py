#!/usr/bin/env python3
"""E42-X03: the ZAP admin profile's plans, built from the RBAC matrix (#1026, AC5).

For each synthetic role (`manager`, `viewer`) this writes, from the template
`.zap/admin-surface.yaml`, two automation plans and one request list:

- `<role>-denials.yaml`: one `requestor` request per `/admin*` and `/users*` operation that
  `matrix.yaml` runs (`executed` or `not_executable`) and refuses the role, expecting its status
  (`403`, or a reviewed `DEVIATIONS` entry), each with its own `X-Correlation-Id`, a UUIDv4 the
  API keeps as the record's `request_id`;
- `<role>-requests.json`: those requests, for `check_admin_denials.py` to find each one's
  denial record in the audit log;
- `<role>-scan.yaml`: the template's own jobs, the passive and active scan of the surface.

The expected statuses come from `matrix.yaml` alone (Security-owned, reviewed); nothing here
restates them. A Manager is `manager_without_grant` (the synthetic one holds no grant), so the
rows the matrix allows a Manager (`GET /admin/audit`, recorder compact and import) are not in
its denial plan. Both plans read the role's bearer and SR-041 CSRF pair at run time from
`ZAP_AUTH_TOKEN` and `ZAP_CSRF_TOKEN` (the template's `replacer` job): no token is written.

The target guard (#1026 Security notes): `--target` must be `http://127.0.0.1:<port>` or
`http://localhost:<port>`. Any other target is refused, the contract's production server and
any tailnet host first. Stdlib and PyYAML only.

Usage: admin_requests.py --target URL --out DIR [--matrix PATH] [--template PATH]
"""

from __future__ import annotations

import argparse
import functools
import json
import re
import sys
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import SplitResult, urlsplit

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
MATRIX = REPO_ROOT / "services/api/tests/contract/rbac/matrix.yaml"
TEMPLATE = REPO_ROOT / ".zap/admin-surface.yaml"
CONTRACT = REPO_ROOT / "docs/plan/22-api-openapi.yaml"
#: Each synthetic role and the matrix actor it is.
ROLES: dict[str, str] = {"manager": "manager_without_grant", "viewer": "viewer"}
SURFACE = ("/admin", "/users")
#: The matrix's filler for a path parameter it gives no value (tests/contract/rbac/rbac_harness.py).
FILLER = "00000000-0000-4000-8000-0000000000ff"
#: Where the running stack answers otherwise than a refusal of the role, by finding: the status
#: it gives instead, and whether that answer writes a record. Each entry turns the plan red the
#: day it is fixed, so it is then removed here (as an `xfail(strict=True)`).
DEVIATIONS: dict[str, tuple[int, bool, str]] = {
    "PUT /admin/log-level": (501, False, "X03-F5: no principal resolver is wired"),
}
_LOOPBACK = frozenset({"127.0.0.1", "localhost"})
_TAILNET = re.compile(r"(^|\.)(tailnet\.internal|ts\.net)$")


class TargetRefused(ValueError):
    """`--target` is not a loopback base URL: the plans are never written for it."""


@functools.cache
def _server_hosts(contract: Path) -> frozenset[str]:
    """The contract's server hosts other than loopback: the file is parsed once per path."""
    servers = yaml.safe_load(contract.read_text(encoding="utf-8")).get("servers", [])
    hosts = {(urlsplit(str(server.get("url", ""))).hostname or "").lower() for server in servers}
    return frozenset(hosts - _LOOPBACK)


def _shown(parts: SplitResult) -> str:
    """A target as a refusal names it: scheme, host and port, never userinfo, path or query."""
    return f"{parts.scheme}://{parts.netloc.rpartition('@')[2]}"


def check_target(target: str, contract: Path = CONTRACT) -> str:
    """`target` without a trailing slash, if it is a loopback base URL; else `TargetRefused`."""
    parts = urlsplit(target)
    host = (parts.hostname or "").lower()
    if host in _server_hosts(contract) or _TAILNET.search(host):
        raise TargetRefused(f"refusing a production or tailnet target: {host}")
    plain = not (parts.username or parts.password or parts.query or parts.fragment)
    if parts.scheme != "http" or host not in _LOOPBACK or parts.path not in ("", "/") or not plain:
        raise TargetRefused(
            f"refusing {_shown(parts)!r}: only http://127.0.0.1:<port> or localhost, with no "
            "userinfo, path, query or fragment"
        )
    return target.rstrip("/")


def _fill(path: str, values: dict[str, str]) -> str:
    return re.sub(r"\{([^}]+)\}", lambda m: values.get(m.group(1), FILLER), path)


def denial_requests(matrix: dict[str, Any], role: str, target: str) -> list[dict[str, Any]]:
    """The role's refused operations, as requests: method, path, url, expected status, whether
    a record is expected, and a fresh correlation id each."""
    actor = ROLES[role]
    found: list[dict[str, Any]] = []
    for key, row in sorted(matrix["operations"].items()):
        method, path = key.split(" ", 1)
        if not path.startswith(SURFACE) or row["state"] not in ("executed", "not_executable"):
            continue
        outcome = str(row["outcomes"][actor])
        if outcome == "allow":
            continue
        expected, recorded, why = DEVIATIONS.get(key, (int(outcome), True, ""))
        req = row.get("request", {})
        body = req.get("json", {} if method in ("POST", "PUT", "PATCH") else None)
        query = "&".join(f"{k}={v}" for k, v in sorted(req.get("params", {}).items()))
        url = target + _fill(path, req.get("path", {})) + (f"?{query}" if query else "")
        found.append(
            {
                "operation": key,
                "method": method,
                "url": url,
                "expected": expected,
                "recorded": recorded,
                "deviation": why or None,
                "body": None if body is None else json.dumps(body),
                "correlation_id": str(uuid.uuid4()),
            }
        )
    return found


def denial_plan(
    template: dict[str, Any], role: str, requests: list[dict[str, Any]]
) -> dict[str, Any]:
    """Phase A: the template's environment and replacer, then one requestor job of `requests`."""
    replacer = [job for job in template["jobs"] if job["type"] == "replacer"]
    entries = []
    for item in requests:
        entry: dict[str, Any] = {
            "name": f"{role} {item['operation']}",
            "url": item["url"],
            "method": item["method"],
            "headers": [f"X-Correlation-Id: {item['correlation_id']}"],
            "responseCode": item["expected"],
        }
        if item["body"] is not None:
            entry["headers"].append("Content-Type: application/json")
            entry["data"] = item["body"]
        entries.append(entry)
    requestor = {"type": "requestor", "name": f"{role}-denials", "requests": entries}
    return {"env": template["env"], "jobs": [*replacer, requestor]}


def scan_plan(template: dict[str, Any], role: str) -> dict[str, Any]:
    """Phase B: the template's jobs, its report named for the role."""
    jobs = json.loads(json.dumps(template["jobs"]))  # a deep copy
    for job in jobs:
        if job["type"] == "report":
            job.setdefault("parameters", {})["reportFile"] = f"admin-surface-{role}"
    return {"env": template["env"], "jobs": jobs}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--target", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--matrix", type=Path, default=MATRIX)
    parser.add_argument("--template", type=Path, default=TEMPLATE)
    args = parser.parse_args(argv)
    try:
        target = check_target(args.target)
    except TargetRefused as exc:
        print(f"admin_requests: {exc}", file=sys.stderr)
        return 2
    matrix = yaml.safe_load(args.matrix.read_text(encoding="utf-8"))
    template = yaml.safe_load(args.template.read_text(encoding="utf-8"))
    args.out.mkdir(parents=True, exist_ok=True)
    for role in ROLES:
        requests = denial_requests(matrix, role, target)
        if not requests:
            print(f"admin_requests: no refused operation for {role}", file=sys.stderr)
            return 1
        (args.out / f"{role}-requests.json").write_text(json.dumps(requests, indent=1) + "\n")
        for name, plan in (
            (f"{role}-denials.yaml", denial_plan(template, role, requests)),
            (f"{role}-scan.yaml", scan_plan(template, role)),
        ):
            (args.out / name).write_text(yaml.safe_dump(plan, sort_keys=False), encoding="utf-8")
        print(f"admin_requests: {role}: {len(requests)} refused operations planned")
    return 0


if __name__ == "__main__":
    sys.exit(main())
