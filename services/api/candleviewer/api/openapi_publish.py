"""#2551: publish the contract's operations for the raw-body routers in `app.openapi()`.

The drawings (E14-T01) and workspaces (E15-T01) routers read raw request bodies, so their byte
caps and strict parsing run before anything else. FastAPI therefore generates their operations
without parameters, request bodies or the documented status codes, and `/openapi.json` drifts
from `docs/plan/22-api-openapi.yaml`, which is normative (C-6.1).

`install_contract_openapi()` wraps `app.openapi`. In the document FastAPI generates, each
operation under `RAW_BODY_PREFIXES` is replaced by the contract's own operation, read from the
packaged subset (#2555), together with the contract's path-level parameters, and the components
those reference are merged in. Only operations already in the generated document are replaced:
a route the app does not serve, or serves with `include_in_schema=False`, is never published,
and every other route stays as generated. Handlers and runtime behaviour do not change.

Not published: a raw-body route outside `RAW_BODY_PREFIXES` keeps its generated form, and the
contract's root `security` is not copied (the generated document declares none, as today).
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from fastapi import FastAPI

from candleviewer.api.contract_conformance import component_closure, under_raw_body_prefix


class ContractPublishError(Exception):
    """A generated component has a merged contract component's name but other content."""


def publish_raw_body_operations(
    doc: dict[str, object], contract: Mapping[str, object]
) -> dict[str, object]:
    """`doc`, updated in place: each raw-body operation it holds becomes the contract's.

    An operation or path the contract lacks keeps its generated form; `create_app()` already
    refuses to build with an undeclared route (RBAC-CON-003). A generated component that shares
    a name with a merged contract component must be identical. Otherwise this raises
    `ContractPublishError` before changing anything: overwriting it would change what other
    operations document, and keeping it would publish the wrong schema. A dangling reference in
    the contract raises `ValueError` (`component_closure`). If either document has no `paths`
    object, `doc` comes back unchanged: fail-open (nothing published), and unreachable through
    `create_app()`, whose generated document and packaged subset always have one.
    """
    paths, contract_paths = doc.get("paths"), contract.get("paths")
    if not isinstance(paths, dict) or not isinstance(contract_paths, Mapping):
        return doc
    replaced: list[tuple[dict[str, object], str, Mapping[str, object]]] = []
    for path, item in paths.items():
        source = contract_paths.get(path)
        if not under_raw_body_prefix(path) or not isinstance(item, dict):
            continue
        if not isinstance(source, Mapping):
            continue  # a raw-body path the contract lacks stays as generated
        replaced += [(item, key, source) for key in item if isinstance(source.get(key), Mapping)]
    contract_components = contract.get("components")
    closure = component_closure(
        contract_components if isinstance(contract_components, Mapping) else {},
        [[source[key], source.get("parameters", [])] for _, key, source in replaced],
    )
    components = doc.get("components")
    generated = components if isinstance(components, dict) else {}
    for kind, entries in closure.items():
        existing = generated.get(kind)
        for name, component in entries.items():
            if isinstance(existing, Mapping) and existing.get(name, component) != component:
                raise ContractPublishError(
                    f"components.{kind}.{name}: the generated document defines it differently "
                    "from the contract"
                )
    for item, key, source in replaced:
        item[key] = copy.deepcopy(source[key])
        if "parameters" in source:
            item["parameters"] = copy.deepcopy(source["parameters"])
    if closure:
        doc["components"] = generated
        for kind, entries in closure.items():
            existing = generated.get(kind)
            merged = existing if isinstance(existing, dict) else {}
            merged.update(copy.deepcopy(entries))
            generated[kind] = merged
    return doc


def install_contract_openapi(app: FastAPI, contract: Mapping[str, object]) -> None:
    """Make `app.openapi()` publish the contract's raw-body operations.

    FastAPI keeps owning the cache (`app.openapi_schema`): every call goes through FastAPI's
    own `openapi()`, a document it returns is published once (recognised by identity), and any
    exception clears the cache, so an unpublished or half-published document is never served
    from it. One caller at a time is assumed: FastAPI's `/openapi.json` handler runs on the
    event loop's thread, so the identity check is never raced.
    """
    generate = app.openapi
    published: dict[str, Any] | None = None

    def openapi() -> dict[str, Any]:
        nonlocal published
        try:
            schema = generate()
            if schema is not published:
                publish_raw_body_operations(schema, contract)
                published = schema
        except BaseException:
            app.openapi_schema = None
            raise
        return schema

    app.openapi = openapi  # type: ignore[method-assign]  # FastAPI's documented override (#2551)
