#!/usr/bin/env python3
"""#3991: the low-privilege ZAP nightlies' plans, each importing the contract cut to its surface.

For a profile (`rules`, `market`, `drawings`, `recording`) this writes, from the profile's template:

- `<profile>-openapi.yaml`: the contract cut to the profile's paths and every component they
  reach through `$ref`. ZAP's import resolves each schema in full, so a `$ref` that closes a
  cycle (the Rule IR's condition and operand trees) becomes an open object: the import stops
  there instead of passing its nesting limit, as the whole contract did (#1026);
- `<profile>-scan.yaml`: the template, importing that file as ZAP sees the checkout.

The `drawings` profile also has a fixture, `.zap/e14-drawings-seed.json`: a synthetic Owner's
drawing with a fixed id. The cut's examples name it (`pin_seed`), so the scan's PUT and DELETE as
the Manager aim at a row the Manager does not own.

The template's `script` job loads `security/zap/role_session.js`, which reads the scan role's
bearer (the synthetic Viewer's, or the Manager's for `drawings`) and SR-041 CSRF pair from the
environment and adds them to each request to the surface `ZAP_PROFILE` names: no token is written
here. Stdlib and PyYAML only.

Usage: nightly_plans.py --profile {drawings,market,recording,rules} --out DIR [--role ROLE]

`--out` is a relative directory without `..`: ZAP mounts the checkout at /zap/wrk, so the plan
must sit inside it to be read there (an absolute or climbing path is refused).
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACT = REPO_ROOT / "docs/plan/22-api-openapi.yaml"
#: Each profile's template and the paths it scans. A path is kept when it is one of these or lies
#: under one (`/rules/{ruleId}`), never because it only starts with the same letters.
PROFILES: dict[str, tuple[Path, tuple[str, ...]]] = {
    "market": (REPO_ROOT / ".zap/market-data.yaml", ("/market/klines", "/market/bars")),
    "rules": (
        REPO_ROOT / ".zap/rules-low-priv.yaml",
        ("/rules", "/schemas/rule-ir.json"),
    ),
    "drawings": (REPO_ROOT / ".zap/e14-drawings.yaml", ("/drawings",)),
    "recording": (REPO_ROOT / ".zap/recording.yaml", ("/recording", "/admin/recorder")),
}
#: A profile's fixture: the rows its examples aim at (E14-X03).
SEEDS: dict[str, Path] = {"drawings": REPO_ROOT / ".zap/e14-drawings-seed.json"}
#: A requestor's status per scan role, where the roles are answered differently (#4868).
ROLE_CODES = "x-cv-role-response-code"
ROLES = ("viewer", "manager")
#: What a `$ref` that closes a cycle becomes.
OPEN: dict[str, str] = {
    "type": "object",
    "description": "a recursive reference, cut for ZAP",
}


def on_surface(path: str, surface: tuple[str, ...]) -> bool:
    return any(path == root or path.startswith(root + "/") for root in surface)


def _refs(node: Any) -> Iterator[str]:
    if isinstance(node, dict):
        for key, value in node.items():
            yield from (
                [value] if key == "$ref" and isinstance(value, str) else _refs(value)
            )
    elif isinstance(node, list):
        for value in node:
            yield from _refs(value)


def cut_cycles(components: dict[str, dict[str, Any]]) -> list[str]:
    """Replace, in place, each `$ref` that closes a cycle with `OPEN`, walking depth first from
    each component in name order. Returns the edges cut, as `from -> to`."""
    cut: list[str] = []
    done: set[str] = set()

    def walk(node: Any, owner: str, stack: list[str]) -> None:
        if isinstance(node, dict):
            target = node.get("$ref")
            if isinstance(
                target, str
            ):  # a `$ref` object: its siblings are ignored (OAS 3.0)
                if target in stack:
                    node.clear()
                    node.update(OPEN)
                    cut.append(f"{owner} -> {target}")
                elif target not in done:
                    visit(target, stack)
                return
            for value in node.values():
                walk(value, owner, stack)
        elif isinstance(node, list):
            for value in node:
                walk(value, owner, stack)

    def visit(ref: str, stack: list[str]) -> None:
        _, _, kind, name = ref.split("/", 3)  # "#/components/<kind>/<name>"
        walk(components[kind][name], ref, [*stack, ref])
        done.add(ref)

    for kind in sorted(components):
        for name in sorted(components[kind]):
            if (ref := f"#/components/{kind}/{name}") not in done:
                visit(ref, [])
    return cut


def cut_contract(
    contract: dict[str, Any], surface: tuple[str, ...]
) -> tuple[dict[str, Any], list[str]]:
    """`contract` cut to the `surface` paths and every component they reach through `$ref`, with
    its cycles cut (`cut_cycles`), and the edges cut. The security schemes stay whole: the
    requirements name them, nothing references them."""
    paths = {
        path: item
        for path, item in contract["paths"].items()
        if on_surface(path, surface)
    }
    reached: set[str] = set()
    pending = list(_refs(paths))
    while pending:
        if (ref := pending.pop()) not in reached:
            reached.add(ref)
            _, _, kind, name = ref.split("/", 3)
            pending += _refs(contract["components"][kind][name])
    components: dict[str, dict[str, Any]] = {}
    for ref in sorted(reached):
        _, _, kind, name = ref.split("/", 3)
        components.setdefault(kind, {})[name] = copy.deepcopy(
            contract["components"][kind][name]
        )
    edges = cut_cycles(components)
    if "securitySchemes" in contract["components"]:
        components["securitySchemes"] = contract["components"]["securitySchemes"]
    kept: dict[str, Any] = {
        k: contract[k] for k in ("openapi", "info", "security") if k in contract
    }
    return {**kept, "paths": copy.deepcopy(paths), "components": components}, edges


def pin_seed(api: dict[str, Any], seed: dict[str, Any]) -> None:
    """Point the cut's examples at the Owner's row: `{drawingId}`, the list's `symbol` and a PUT
    body valid for it (its symbol and tool, which are immutable). A cross-owner write that
    succeeded would change the row, which the isolation check after the scan finds."""
    first = seed["operations"][0]
    parameters, schemas = api["components"]["parameters"], api["components"]["schemas"]
    parameters["DrawingId"]["example"] = first["id"]
    parameters["SymbolQuery"]["example"] = first["drawing"]["symbol"]
    schemas["DrawingInput"]["example"] = {**first["drawing"], "label": "zap probe"}


def role_dependent(template: dict[str, Any]) -> bool:
    """Whether a requestor in `template` answers differently for the scan role."""
    return any(ROLE_CODES in request for request in _requests(template))


def _requests(plan: dict[str, Any]) -> Iterator[dict[str, Any]]:
    for job in plan["jobs"]:
        if job["type"] == "requestor":
            yield from job.get("requests", [])


def scan_plan(
    template: dict[str, Any], api_file: str, role: str | None = None
) -> dict[str, Any]:
    """The template, importing `api_file` (the cut contract, as ZAP sees the checkout). A request's
    `ROLE_CODES` map sets its `responseCode` for `role` and is dropped: ZAP never sees it (#4868)."""
    plan = copy.deepcopy(template)
    for job in plan["jobs"]:
        if job["type"] == "openapi":
            job["parameters"]["apiFile"] = api_file
    for request in _requests(plan):
        codes = request.pop(ROLE_CODES, {})
        if role in codes:
            request["responseCode"] = codes[role]
    return plan


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--profile", choices=sorted(PROFILES), required=True)
    parser.add_argument(
        "--out",
        type=Path,
        required=True,
        help="a relative directory, without '..', in the checkout ZAP mounts at /zap/wrk",
    )
    parser.add_argument(
        "--role",
        choices=ROLES,
        help="the scan role, required where a template's requestors answer the roles differently",
    )
    args = parser.parse_args(argv)
    if args.out.is_absolute() or ".." in args.out.parts:
        print(
            "nightly_plans: --out must be a relative path, without '..', inside the checkout "
            "ZAP mounts",
            file=sys.stderr,
        )
        return 2
    template_path, surface = PROFILES[args.profile]
    contract = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
    api, edges = cut_contract(contract, surface)
    if args.profile in SEEDS and api["paths"]:
        pin_seed(api, json.loads(SEEDS[args.profile].read_text(encoding="utf-8")))
    if not api["paths"]:
        print(
            f"nightly_plans: the contract has no path on the {args.profile} surface",
            file=sys.stderr,
        )
        return 1
    if args.role is None and role_dependent(
        yaml.safe_load(template_path.read_text("utf-8"))
    ):
        print(
            f"nightly_plans: {args.profile}'s requestors need --role", file=sys.stderr
        )
        return 2
    args.out.mkdir(parents=True, exist_ok=True)
    api_path = args.out / f"{args.profile}-openapi.yaml"
    api_path.write_text(yaml.safe_dump(api, sort_keys=False), encoding="utf-8")
    template = yaml.safe_load(template_path.read_text(encoding="utf-8"))
    plan = scan_plan(
        template, f"/zap/wrk/{api_path.as_posix()}", args.role
    )  # /zap/wrk: checkout
    plan_path = args.out / f"{args.profile}-scan.yaml"
    plan_path.write_text(yaml.safe_dump(plan, sort_keys=False), encoding="utf-8")
    components = sum(len(group) for group in api["components"].values())
    print(
        f"nightly_plans: {args.profile}: {len(api['paths'])} paths, {components} components"
    )
    for edge in edges:
        print(f"nightly_plans: {args.profile}: cut the cycle at {edge}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
