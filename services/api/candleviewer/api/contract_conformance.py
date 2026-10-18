"""E03-T06: contract conformance checks for the `contract` CI job.

Two conformance surfaces per ADR-0013 rule 3 and the ticket scope:

1. `docs/plan/22-api-openapi.yaml` is a structurally valid OpenAPI 3.1
   document (schemathesis/consumer tests further down the pyramid assume
   this holds).
2. Every route the FastAPI app actually registers resolves to an operation
   declared in the spec — a route the server serves that the contract does
   not document is drift (CI-CON-001), caught here without needing the
   full app wired up yet (R0: only `/healthz`, `/readyz`, `/metrics` exist).

`/metrics` is Prometheus-format, not part of the REST contract (see
`docs/plan/22-api-openapi.yaml` inline note) and is excluded deliberately.

#2555: the YAML exists only in a repository checkout, and the API image has none.
`load_openapi_spec()` / `OPENAPI_SPEC_PATH` (dev, CI and tests) resolve it on first use, never
at import. The runtime reads `load_contract_subset()`: a pruned copy of the YAML that
`scripts/generate_protocol_models.py` commits inside this package and that is loaded
package-relative, so `create_app()` needs no `docs/plan`.

Only the stdlib is imported at module level, so the boot path, the generator and the
`gen` CI gate (both load this file by path) need nothing else. The dev-only functions
import PyYAML and openapi-spec-validator when called (#2616). No network.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from importlib.resources import files
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

#: The normative contract (C-6.1), relative to the repository root.
OPENAPI_SPEC_RELPATH = "docs/plan/22-api-openapi.yaml"

#: The packaged contract subset (#2555), written by `scripts/generate_protocol_models.py`.
CONTRACT_SUBSET_PACKAGE = "candleviewer.api._generated"
CONTRACT_SUBSET_RESOURCE = "contract_subset.json"

#: Routers that read raw request bodies (#2551): drawings (E14-T01) and workspaces (E15-T01),
#: whose router also serves `/layout-presets` (the YAML groups it with `/workspaces*`). The
#: subset carries their full contract path items, so the app can publish those in its OpenAPI.
RAW_BODY_PREFIXES = ("/drawings", "/workspaces", "/layout-presets")

# Routes the app serves that are intentionally outside the REST contract
# (operational/observability endpoints, not product API surface).
NON_CONTRACT_ROUTES = frozenset(
    {"/metrics", "/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}
)

_HTTP_METHODS = frozenset({"get", "put", "post", "delete", "options", "head", "patch", "trace"})
#: The operation keys deny-by-default and the RBAC checks read (`declared_operations`).
_RBAC_KEYS = ("security", "x-rbac")
_REF_PREFIX = "#/components/"


def _checkout_spec_path(module: Path | None = None) -> Path:
    """The YAML in a repository checkout, four levels above `candleviewer/api/`.

    Only dev, CI and tests ask for it. The image installs the package at `/app/candleviewer/`,
    which has no directory four levels up: there this raises instead of guessing.
    """
    here = (module or Path(__file__)).resolve()
    if len(here.parents) < 5:
        raise FileNotFoundError(
            f"{OPENAPI_SPEC_RELPATH}: {here} is not inside a repository checkout; "
            "the runtime reads the packaged subset (load_contract_subset)"
        )
    return here.parents[4] / OPENAPI_SPEC_RELPATH


if TYPE_CHECKING:
    #: The YAML in a repository checkout (dev, CI and tests only), resolved on first use.
    OPENAPI_SPEC_PATH: Path
else:

    def __getattr__(name: str) -> Path:
        """`OPENAPI_SPEC_PATH`, resolved when first used rather than at import (PEP 562).

        Defined for the runtime only: mypy reads the declaration above, so it still reports
        any other name imported from this module.
        """
        if name == "OPENAPI_SPEC_PATH":
            return _checkout_spec_path()
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


class ContractDriftError(Exception):
    """Raised when a server route is absent from the OpenAPI contract."""

    def __init__(self, route: str, method: str) -> None:
        self.route = route
        self.method = method
        super().__init__(
            f"CI-CON-001: contract drift — {method.upper()} {route} is served by "
            f"the app but not declared in {OPENAPI_SPEC_RELPATH}"
        )


def load_openapi_spec(spec_path: Path | None = None) -> dict[str, object]:
    """The YAML at `spec_path`, by default the checkout's `OPENAPI_SPEC_PATH` (dev, CI, tests)."""
    import yaml  # dev-only: the runtime never parses the YAML

    path = _checkout_spec_path() if spec_path is None else spec_path
    with path.open(encoding="utf-8") as fh:
        return cast(dict[str, object], yaml.safe_load(fh))


def load_contract_subset() -> dict[str, object]:
    """The packaged contract subset, read package-relative. `create_app()` reads this."""
    resource = files(CONTRACT_SUBSET_PACKAGE).joinpath(CONTRACT_SUBSET_RESOURCE)
    return cast(dict[str, object], json.loads(resource.read_text(encoding="utf-8")))


def assert_spec_is_valid(spec: Mapping[str, object]) -> None:
    """Raises `openapi_spec_validator.exceptions.OpenAPIValidationError` on an
    invalid document; the caller decides how to surface that (CI job step
    failure output already includes the offending schema path)."""
    from openapi_spec_validator import validate as validate_openapi_spec  # dev-only (#2616)

    validate_openapi_spec(spec)


def spec_paths(spec: dict[str, Any]) -> set[str]:
    return set(spec.get("paths", {}).keys())


def _route_matches_spec(route: str, declared_paths: set[str]) -> bool:
    """FastAPI routes use `{param}` path params identically to OpenAPI, so an
    exact match after excluding non-contract routes is sufficient here; a
    templated-vs-literal mismatch would need a segment-aware matcher, which
    is unnecessary while every route is either declared verbatim or on the
    `NON_CONTRACT_ROUTES` allow-list."""
    return route in declared_paths


def find_drift(app_routes: list[tuple[str, str]], spec: dict[str, Any]) -> list[ContractDriftError]:
    """`app_routes` is a list of (path, http_method) tuples as served by the
    app (e.g. from `app.routes`). Returns one `ContractDriftError` per route
    not covered by the spec and not on the allow-list."""
    declared = spec_paths(spec)
    drift: list[ContractDriftError] = []
    for path, method in app_routes:
        if path in NON_CONTRACT_ROUTES:
            continue
        if not _route_matches_spec(path, declared):
            drift.append(ContractDriftError(path, method))
    return drift


def under_raw_body_prefix(path: str) -> bool:
    """`path` is, or is below, one of `RAW_BODY_PREFIXES` (segment-aware)."""
    return any(path == prefix or path.startswith(prefix + "/") for prefix in RAW_BODY_PREFIXES)


def component_refs(node: object) -> Iterator[str]:
    """Every component reference under `node`: `$ref` values and discriminator mapping targets
    (those name schemas too; a closure that skipped them could leave a reference dangling)."""
    if isinstance(node, list):
        for item in node:
            yield from component_refs(item)
        return
    if not isinstance(node, dict):
        return
    ref = node.get("$ref")
    if isinstance(ref, str):
        yield ref
    discriminator = node.get("discriminator")
    if isinstance(discriminator, dict) and isinstance(discriminator.get("mapping"), dict):
        yield from (str(target) for target in discriminator["mapping"].values())
    for value in node.values():
        yield from component_refs(value)


def component_closure(
    components: Mapping[str, object], roots: object
) -> dict[str, dict[str, object]]:
    """The components `roots` reference, transitively, as `{kind: {name: object}}`.

    Raises `ValueError` on a reference that is not `#/components/<kind>/<name>` or that names a
    component `components` lacks: a dangling reference must never be published.
    """
    closure: dict[str, dict[str, object]] = {}
    pending = list(component_refs(roots))
    while pending:
        ref = pending.pop()
        kind, _, name = ref.removeprefix(_REF_PREFIX).partition("/")
        if not ref.startswith(_REF_PREFIX) or not name or "/" in name:
            raise ValueError(f"unsupported reference {ref!r}: expected {_REF_PREFIX}<kind>/<name>")
        name = name.replace("~1", "/").replace("~0", "~")  # RFC 6901 escapes
        if name in closure.get(kind, {}):
            continue
        entries = components.get(kind)
        target = entries.get(name) if isinstance(entries, Mapping) else None
        if target is None:
            raise ValueError(f"dangling reference {ref!r}")
        closure.setdefault(kind, {})[name] = target
        pending.extend(component_refs(target))
    return closure


def build_contract_subset(spec: Mapping[str, object]) -> dict[str, object]:
    """The pruned copy of `spec` that ships in the package (#2555, #2551), holding only what
    its two consumers read.

    - Every operation, cut to `x-rbac` and `security`: deny-by-default reads nothing else, so
      `declared_operations()` gives the same set on the subset as on the YAML.
    - The full path items under `RAW_BODY_PREFIXES`, plus the components they reference,
      transitively: what publishing those routers' OpenAPI needs.

    Nothing is rewritten: each value kept equals the YAML's at the same location. The cut
    operations lack their parameters, so the subset as a whole is not an OpenAPI document;
    the published path items with their components are. Raises `ValueError` when `paths` or
    `components` is not an object.
    """
    all_paths = spec.get("paths")
    components = spec.get("components", {})
    if not isinstance(all_paths, dict) or not isinstance(components, Mapping):
        raise ValueError("the contract needs a `paths` object and, if present, a `components` one")
    paths: dict[str, object] = {}
    published: list[object] = []
    for path, item in all_paths.items():
        if not isinstance(item, dict):
            continue
        if under_raw_body_prefix(path):
            paths[path] = item
            published.append(item)
            continue
        paths[path] = {
            method: {key: op[key] for key in _RBAC_KEYS if key in op}
            for method, op in item.items()
            if method in _HTTP_METHODS and isinstance(op, dict)
        }
    return {"components": component_closure(components, published), "paths": paths}


def _sorted(node: Any) -> Any:
    if isinstance(node, dict):
        return {key: _sorted(node[key]) for key in sorted(node)}
    if isinstance(node, list):
        return [_sorted(item) for item in node]
    return node


def render_contract_subset(source: bytes) -> str:
    """The artifact text for the YAML bytes `source`, byte-identical for equal input.

    Keys are sorted (the `x-cv-generated` header first), with a two-space indent, LF line ends
    and a trailing newline; CRLF in `source` is folded to LF. The header names the source but
    records no digest of it (#2743): a digest of the whole YAML changes with every contract edit,
    so any two contract PRs would conflict on it. Freshness is checked by rendering again and
    comparing instead (`--check` of the generator, and the `gen` CI gate).
    """
    import yaml  # dev-only: only the generator, the `gen` CI gate and the tests render

    normalised = source.replace(b"\r\n", b"\n")
    header = {
        "notice": "GENERATED FILE — DO NOT EDIT BY HAND. Regenerate from services/api with "
        "`uv run python scripts/generate_protocol_models.py`.",
        "source": OPENAPI_SPEC_RELPATH,
    }
    subset = build_contract_subset(cast(dict[str, object], yaml.safe_load(normalised)))
    document = {"x-cv-generated": header, **_sorted(subset)}
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"
