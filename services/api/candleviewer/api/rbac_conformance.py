"""RBAC contract-conformance checks (E09-T03).

Two conformance surfaces, both wired into CI's `contract` job alongside
`api/contract_conformance.py`:

1. **Route inventory** (`assert_every_operation_declares_rbac`): every
   operation in `docs/plan/22-api-openapi.yaml` either declares
   `x-rbac.permissions` (a non-empty list of permission codes covers the
   normal case; an empty list plus `scope: none` still counts as declared —
   `POST /auth/login` and friends are `security: []` *and* `x-rbac:
   {permissions: [], scope: none}`, meaning "public, no permission check"
   is an explicit statement, not a missing one) or is marked `security: []`
   (the explicit public marker). An operation with neither fails the build
   — deny-by-default at the contract level, before any request ever
   reaches a route (ticket "Every route declares a permission or is
   explicitly public").
2. **Vocabulary single source** (`rbac_vocabulary_single_source`): the
   permission codes named anywhere in `x-rbac.permissions`, the generated
   `Permission` enum, and the `permissions` table in
   `candleviewer/auth/rbac_seed.json` (which is what `candleviewer.db.seed`
   loads into the database) are exactly the same 36-code set. A hand-edit
   to the generated enum or a spec/seed edit that only touches one side
   fails this check (ticket "Vocabulary has one source of truth").
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.auth.generated_permissions import Permission

_HTTP_METHODS = frozenset({"get", "put", "post", "delete", "options", "head", "patch", "trace"})

#: Package-relative (#2555): the seed ships inside the package, so finding it needs no checkout.
RBAC_SEED_PATH = Path(__file__).resolve().parents[1] / "auth" / "rbac_seed.json"


class UndeclaredRouteError(Exception):
    """An operation declares neither `x-rbac` nor `security: []`."""

    def __init__(self, path: str, method: str) -> None:
        self.path = path
        self.method = method
        super().__init__(
            f"RBAC-CON-001: {method.upper()} {path} declares neither "
            "`x-rbac.permissions` nor an explicit `security: []` public "
            "marker — deny-by-default requires one of the two"
        )


def find_undeclared_routes(spec: dict[str, Any]) -> list[UndeclaredRouteError]:
    """Every operation must declare `x-rbac` or `security: []`; anything
    else is undeclared and fails the build (ticket AC "Every route declares
    a permission or is explicitly public")."""
    undeclared: list[UndeclaredRouteError] = []
    for path, path_item in spec.get("paths", {}).items():
        if not isinstance(path_item, dict):
            continue
        for method, op in path_item.items():
            if method not in _HTTP_METHODS or not isinstance(op, dict):
                continue
            has_rbac = isinstance(op.get("x-rbac"), dict)
            is_public = op.get("security") == []
            if not has_rbac and not is_public:
                undeclared.append(UndeclaredRouteError(path, method))
    return undeclared


def spec_permission_codes(spec: dict[str, Any]) -> set[str]:
    codes: set[str] = set()
    for path_item in spec.get("paths", {}).values():
        if not isinstance(path_item, dict):
            continue
        for op in path_item.values():
            if not isinstance(op, dict):
                continue
            rbac = op.get("x-rbac")
            if not isinstance(rbac, dict):
                continue
            for code in rbac.get("permissions", []):
                codes.add(code)
    return codes


def enum_permission_codes() -> set[str]:
    return {member.value for member in Permission}


def seed_permission_codes(seed_path: Path = RBAC_SEED_PATH) -> set[str]:
    import json

    with seed_path.open(encoding="utf-8") as fh:
        seed = json.load(fh)
    return {perm["code"] for perm in seed["permissions"]}


class VocabularyMismatchError(Exception):
    """The spec, generated enum and database seed vocabularies disagree."""

    def __init__(self, spec_only: set[str], enum_only: set[str], seed_only: set[str]) -> None:
        self.spec_only = spec_only
        self.enum_only = enum_only
        self.seed_only = seed_only
        super().__init__(
            "RBAC-CON-002: vocabulary mismatch — "
            f"spec_only={sorted(spec_only)} enum_only={sorted(enum_only)} "
            f"seed_only={sorted(seed_only)}"
        )


def assert_vocabulary_single_source(spec: dict[str, Any] | None = None) -> None:
    """`rbac_vocabulary_single_source`: the OpenAPI `x-rbac.permissions`
    codes, the generated `Permission` enum and `rbac_seed.json`'s
    `permissions` table must be identical sets. Raises
    `VocabularyMismatchError` naming exactly which codes differ."""
    resolved_spec = spec if spec is not None else load_openapi_spec()
    spec_codes = spec_permission_codes(resolved_spec)
    enum_codes = enum_permission_codes()
    seed_codes = seed_permission_codes()

    if spec_codes != enum_codes or spec_codes != seed_codes:
        raise VocabularyMismatchError(
            spec_only=spec_codes - enum_codes - seed_codes,
            enum_only=enum_codes - spec_codes,
            seed_only=seed_codes - spec_codes,
        )
