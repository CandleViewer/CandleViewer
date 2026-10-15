"""#2551: publish the contract's operations for the raw-body routers in `app.openapi()`.

The drawings (E14-T01) and workspaces (E15-T01) routers read raw request bodies, so their byte
caps and strict parsing run before anything else. FastAPI therefore generates their operations
without parameters, request bodies or the documented status codes, and `/openapi.json` drifts
from `docs/plan/22-api-openapi.yaml`, which is normative (C-6.1).

`install_contract_openapi()` wraps `app.openapi`. Each operation the app serves under
`RAW_BODY_PREFIXES` is replaced by the contract's own operation, read from the packaged subset
(#2555), with the contract's path-level parameters, and the components those reference are
merged in. An operation the app does not serve is never added, every other route is left as
generated, and handlers and runtime behaviour do not change: only the published document does.
"""

from __future__ import annotations

import copy
from collections.abc import Iterable, Mapping
from typing import Any

from fastapi import FastAPI

from candleviewer.api.contract_conformance import component_closure, under_raw_body_prefix
from candleviewer.api.deny_by_default import served_operations


class ContractPublishError(Exception):
    """A generated component has a merged contract component's name but other content."""


def publish_raw_body_operations(
    doc: dict[str, Any], contract: Mapping[str, Any], served: Iterable[tuple[str, str]]
) -> dict[str, Any]:
    """`doc`, updated in place: each served raw-body `(METHOD, path)` gets the contract's operation.

    A served operation the contract lacks keeps its generated form; `create_app()` already
    refuses to build with one (RBAC-CON-003). A generated component that shares a name with a
    merged contract component must be identical. Otherwise this raises `ContractPublishError`
    before changing anything: overwriting it would change what other operations document, and
    keeping it would publish the wrong schema.
    """
    published: list[tuple[str, str, Mapping[str, Any]]] = []
    for method, path in sorted(served):
        item = contract["paths"].get(path)
        if under_raw_body_prefix(path) and isinstance(item, dict) and method.lower() in item:
            published.append((method.lower(), path, item))
    roots = [[item[method], item.get("parameters", [])] for method, _, item in published]
    closure = component_closure(contract["components"], roots)
    generated = doc.get("components", {})
    for kind, entries in closure.items():
        for name, component in entries.items():
            if generated.get(kind, {}).get(name, component) != component:
                raise ContractPublishError(
                    f"components.{kind}.{name}: the generated document defines it differently "
                    "from the contract"
                )
    for method, path, item in published:
        target = doc.setdefault("paths", {}).setdefault(path, {})
        target[method] = copy.deepcopy(item[method])
        if "parameters" in item:
            target["parameters"] = copy.deepcopy(item["parameters"])
    for kind, entries in closure.items():
        doc.setdefault("components", {}).setdefault(kind, {}).update(copy.deepcopy(entries))
    return doc


def install_contract_openapi(app: FastAPI, contract: Mapping[str, Any]) -> None:
    """Make `app.openapi()` publish the contract's raw-body operations.

    Call once every router is included. The served operations are read when the document is
    first built; FastAPI caches it in `app.openapi_schema`, as before.
    """
    generate = app.openapi

    def openapi() -> dict[str, Any]:
        schema = app.openapi_schema
        if schema is None:
            try:
                schema = publish_raw_body_operations(generate(), contract, served_operations(app))
            except ContractPublishError:
                app.openapi_schema = None  # never cache the unpublished document
                raise
            app.openapi_schema = schema
        return schema

    app.openapi = openapi  # type: ignore[method-assign]  # FastAPI's documented override (#2551)
