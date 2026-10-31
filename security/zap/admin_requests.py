#!/usr/bin/env python3
"""E42-X03: the ZAP admin profile's plans, built from the RBAC matrix (#1026, AC5).

For each synthetic role (`manager`, `viewer`) this writes, from the template
`.zap/admin-surface.yaml`, two automation plans and one request list:

- `<role>-denials.yaml`: one `requestor` request per `/admin*` and `/users*` operation that
  `matrix.yaml` runs (`executed` or `not_executable`) and refuses the role, expecting its status
  (`403`, or a reviewed `DEVIATIONS` entry), each with its own UUIDv4 as both `X-Correlation-Id`
  (the correlation middleware's) and `X-Request-Id` (the admin principal's,
  `api/audit_principal.py`), which the API keeps as the record's `request_id`;
- `<role>-requests.json`: those requests, for `check_admin_denials.py` to find each one's
  denial record in the audit log;
- `<role>-scan.yaml`: the template's own jobs, the passive and active scan of the surface, which
  imports `admin-openapi.yaml`: the contract cut to the surface and the components it reaches.
  ZAP's import resolves every schema in full, and the contract's recursive condition tree passes
  its nesting limit, so the scan imports only what it scans.

The Owner's plan is fixed, not drawn from the matrix, which allows the Owner (E16-X02, #494): an
Owner signed in with password and TOTP holds no `recorder_purge` step-up, so each purge in
`security/zap/owner-purge-denials.yaml` is refused 403 and audited as a `retention.purge` denial
(its `action`, which `check_admin_denials.py` then requires). It writes `owner-denials.yaml` and
`owner-requests.json` only: the Owner never scans.

The expected statuses come from `matrix.yaml` alone (Security-owned, reviewed); nothing here
restates them. A Manager is `manager_without_grant` (the synthetic one holds no grant), so the
row the matrix allows a Manager (`GET /admin/audit`) is not in its denial plan, while the
recorder's compact and import are: `recording:write` is the Owner's alone (G-04, #484). Both
plans load the template's `script` job, `security/zap/role_session.js`,
which reads the role's bearer and SR-041 CSRF pair from `ZAP_AUTH_TOKEN` and `ZAP_CSRF_TOKEN`
once, when ZAP loads it, and adds them to each request to the surface (ZAP expands no variable
inside a replacer rule): no token is written.

The target guard (#1026 Security notes): `--target` must be `http://127.0.0.1:<port>` or
`http://localhost:<port>`. Any other target is refused, the contract's production server and
any tailnet host first. Stdlib and PyYAML only.

Usage: admin_requests.py --target URL --out DIR [--matrix PATH] [--template PATH]

`--out` is a relative directory without `..`: ZAP mounts the checkout at /zap/wrk, so the plans
must sit inside it to be read there (an absolute or climbing path is refused).
"""

from __future__ import annotations

import argparse
import functools
import json
import re
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import SplitResult, urlsplit

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
MATRIX = REPO_ROOT / "services/api/tests/contract/rbac/matrix.yaml"
TEMPLATE = REPO_ROOT / ".zap/admin-surface.yaml"
#: Each role whose refusals are a fixed list, not the matrix's, and that list.
FIXED: dict[str, Path] = {"owner": REPO_ROOT / "security/zap/owner-purge-denials.yaml"}
CONTRACT = REPO_ROOT / "docs/plan/22-api-openapi.yaml"
#: Each synthetic role and the matrix actor it is.
ROLES: dict[str, str] = {"manager": "manager_without_grant", "viewer": "viewer"}
SURFACE = ("/admin", "/users")
#: The matrix's filler for a path parameter it gives no value (tests/contract/rbac/rbac_harness.py).
FILLER = "00000000-0000-4000-8000-0000000000ff"
#: The request id each planned request carries, under both names the API reads it from.
_ID_HEADERS = ("Correlation-Id", "Request-Id")
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


def fixed_requests(plan: dict[str, Any], target: str) -> list[dict[str, Any]]:
    """A fixed plan's requests, as `denial_requests` writes them, each with the audit `action`
    its denial record must name, a fresh correlation id each, and a fresh `Idempotency-Key`
    each: the purge refuses a missing key (400) before its step-up check (#4622), so without
    one the probe would never reach the refusal it is for."""
    found: list[dict[str, Any]] = []
    for entry in plan["requests"]:
        method, path = str(entry["operation"]).split(" ", 1)
        found.append(
            {
                "operation": entry["operation"],
                "method": method,
                "url": target + path,
                "expected": int(entry["expected"]),
                "recorded": True,
                "deviation": None,
                "action": entry["action"],
                "body": json.dumps(entry["json"]),
                "correlation_id": str(uuid.uuid4()),
                "idempotency_key": str(uuid.uuid4()),
            }
        )
    return found


def denial_plan(
    template: dict[str, Any], role: str, requests: list[dict[str, Any]]
) -> dict[str, Any]:
    """Phase A: the template's environment and session script, then one requestor job of
    `requests`."""
    session = [job for job in template["jobs"] if job["type"] == "script"]
    entries = []
    for item in requests:
        entry: dict[str, Any] = {
            "name": f"{role} {item['operation']}",
            "url": item["url"],
            "method": item["method"],
            "headers": [f"X-{name}: {item['correlation_id']}" for name in _ID_HEADERS],
            "responseCode": item["expected"],
        }
        if item.get("idempotency_key"):
            entry["headers"].append(f"Idempotency-Key: {item['idempotency_key']}")
        if item["body"] is not None:
            entry["headers"].append("Content-Type: application/json")
            entry["data"] = item["body"]
        entries.append(entry)
    requestor = {"type": "requestor", "name": f"{role}-denials", "requests": entries}
    return {"env": template["env"], "jobs": [*session, requestor]}


def _refs(node: Any) -> Iterator[str]:
    if isinstance(node, dict):
        for key, value in node.items():
            yield from [value] if key == "$ref" and isinstance(value, str) else _refs(value)
    elif isinstance(node, list):
        for value in node:
            yield from _refs(value)


def admin_contract(contract: dict[str, Any]) -> dict[str, Any]:
    """`contract` cut to the `SURFACE` paths and every component they reach through `$ref`; the
    security schemes stay whole (requirements name them, they are not referenced)."""
    paths = {path: item for path, item in contract["paths"].items() if path.startswith(SURFACE)}
    reached: set[str] = set()
    pending = list(_refs(paths))
    while pending:
        if (ref := pending.pop()) not in reached:
            reached.add(ref)
            _, _, kind, name = ref.split("/", 3)  # "#/components/<kind>/<name>"
            pending += _refs(contract["components"][kind][name])
    components: dict[str, dict[str, Any]] = {}
    for ref in sorted(reached):
        _, _, kind, name = ref.split("/", 3)
        components.setdefault(kind, {})[name] = contract["components"][kind][name]
    if "securitySchemes" in contract["components"]:
        components["securitySchemes"] = contract["components"]["securitySchemes"]
    keys = ("openapi", "info", "security")
    kept: dict[str, Any] = {key: contract[key] for key in keys if key in contract}
    return {**kept, "paths": paths, "components": components}


def scan_plan(template: dict[str, Any], role: str, api_file: str) -> dict[str, Any]:
    """Phase B: the template's jobs, importing `api_file` (the admin contract, as ZAP sees the
    checkout), its report named for the role."""
    jobs = json.loads(json.dumps(template["jobs"]))  # a deep copy
    for job in jobs:
        if job["type"] == "openapi":
            job["parameters"]["apiFile"] = api_file
        if job["type"] == "report":
            job.setdefault("parameters", {})["reportFile"] = f"admin-surface-{role}"
    return {"env": template["env"], "jobs": jobs}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--target", required=True)
    parser.add_argument(
        "--out",
        type=Path,
        required=True,
        help="a relative directory, without '..', in the checkout ZAP mounts at /zap/wrk",
    )
    parser.add_argument("--matrix", type=Path, default=MATRIX)
    parser.add_argument("--template", type=Path, default=TEMPLATE)
    args = parser.parse_args(argv)
    try:
        target = check_target(args.target)
    except TargetRefused as exc:
        print(f"admin_requests: {exc}", file=sys.stderr)
        return 2
    if args.out.is_absolute() or ".." in args.out.parts:
        print(
            "admin_requests: --out must be a relative path, without '..', inside the checkout "
            "ZAP mounts",
            file=sys.stderr,
        )
        return 2
    matrix = yaml.safe_load(args.matrix.read_text(encoding="utf-8"))
    template = yaml.safe_load(args.template.read_text(encoding="utf-8"))
    args.out.mkdir(parents=True, exist_ok=True)
    contract = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
    api = args.out / "admin-openapi.yaml"
    api.write_text(yaml.safe_dump(admin_contract(contract), sort_keys=False), encoding="utf-8")
    api_file = f"/zap/wrk/{api.as_posix()}"  # the checkout is mounted at /zap/wrk
    for role in ROLES:
        requests = denial_requests(matrix, role, target)
        if not requests:
            print(f"admin_requests: no refused operation for {role}", file=sys.stderr)
            return 1
        (args.out / f"{role}-requests.json").write_text(json.dumps(requests, indent=1) + "\n")
        for name, plan in (
            (f"{role}-denials.yaml", denial_plan(template, role, requests)),
            (f"{role}-scan.yaml", scan_plan(template, role, api_file)),
        ):
            (args.out / name).write_text(yaml.safe_dump(plan, sort_keys=False), encoding="utf-8")
        print(f"admin_requests: {role}: {len(requests)} refused operations planned")
    for role, path in FIXED.items():
        requests = fixed_requests(yaml.safe_load(path.read_text(encoding="utf-8")), target)
        (args.out / f"{role}-requests.json").write_text(json.dumps(requests, indent=1) + "\n")
        plan = denial_plan(template, role, requests)
        (args.out / f"{role}-denials.yaml").write_text(
            yaml.safe_dump(plan, sort_keys=False), encoding="utf-8"
        )
        print(f"admin_requests: {role}: {len(requests)} fixed refusals planned")
    return 0


if __name__ == "__main__":
    sys.exit(main())
