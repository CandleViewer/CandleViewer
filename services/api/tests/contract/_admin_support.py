"""Shared by the admin contract tests (E42-T05, E42-T07): owner-only RBAC outcomes, parsed 04
§7.2.2 rows, and example validation against the response schema (2020-12, format checker)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from referencing import Registry
from referencing.jsonschema import DRAFT202012

from candleviewer.api.contract_conformance import load_openapi_spec

ROOT = Path(__file__).resolve().parents[4]
SPEC: dict[str, Any] = load_openapi_spec()
OWNER_ONLY = {
    "owner": "allow",
    "manager_with_grant": "403",
    "manager_without_grant": "403",
    "viewer": "403",
    "unauthenticated": "401",
}
_URI = "urn:cv:22-api-openapi"
_REGISTRY: Registry[Any] = Registry().with_resource(_URI, DRAFT202012.create_resource(SPEC))


def text(description: str) -> str:
    """Whitespace-normalised, so no assertion depends on where the YAML wraps."""
    return " ".join(description.split())


def _escape(part: str) -> str:
    return part.replace("~", "~0").replace("/", "~1")


def example_cases(operations: list[tuple[str, str]]) -> list[tuple[str, str, Any]]:
    """`(case id, schema pointer, value)` for every example of every response of each operation,
    shared (`$ref`) responses included."""
    cases: list[tuple[str, str, Any]] = []
    for path, method in operations:
        for status, response in SPEC["paths"][path][method]["responses"].items():
            pointer = f"/paths/{_escape(path)}/{method}/responses/{status}"
            if "$ref" in response:
                pointer = response["$ref"].removeprefix("#")
                response = SPEC["components"]["responses"][pointer.rsplit("/", 1)[1]]
            for media, body in response.get("content", {}).items():
                schema = f"{pointer}/content/{_escape(media)}/schema"
                for name, example in body.get("examples", {}).items():
                    cases.append((f"{method} {path} {status} {name}", schema, example["value"]))
    return cases


def validate_example(pointer: str, value: Any) -> None:
    schema = {"$ref": f"{_URI}#{pointer}"}
    checker = Draft202012Validator.FORMAT_CHECKER
    Draft202012Validator(schema, registry=_REGISTRY, format_checker=checker).validate(value)


def capability_rows() -> dict[str, list[str]]:
    """04 §7.2.2 row id -> [capability, permission · operation, owner, manager, viewer]."""
    doc = (ROOT / "docs/plan/04-security-program.md").read_text(encoding="utf-8")
    table = doc.split("#### 7.2.2 Capability matrix", 1)[1].split("\n### ", 1)[0]
    rows: dict[str, list[str]] = {}
    for line in table.splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) == 6 and re.fullmatch(r"\d+[a-z]?", cells[0]):
            rows[cells[0]] = cells[1:]
    return rows


def grants(cell: str) -> tuple[set[str], set[str]]:
    """A `permission · operation` cell as (permissions, operationIds)."""
    permissions, _, operations = cell.partition(" · ")
    found = set(re.findall(r"`([a-z_]+:[a-z_]+)`", permissions))
    return found, set(re.findall(r"`([A-Za-z]+)`", operations))


def x_rbac(operation_id: str) -> list[str]:
    (permissions,) = [
        op["x-rbac"]["permissions"]
        for item in SPEC["paths"].values()
        for op in item.values()
        if isinstance(op, dict) and op.get("operationId") == operation_id
    ]
    return list(permissions)
