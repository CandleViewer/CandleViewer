"""Shared helper for tests that validate a body against the contract (`22-api-openapi.yaml`)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def deref(spec: Mapping[str, Any], node: Any) -> Any:
    """`node` with every component `$ref` (schemas and responses) inlined, `examples` dropped.

    `spec` is the parsed contract (`load_openapi_spec()`), a YAML document walked untyped. The
    result is a plain JSON Schema that `jsonschema.validate` takes without a resolver.
    """
    if isinstance(node, dict):
        if "$ref" in node:
            kind, name = node["$ref"].split("/")[-2:]
            return deref(spec, spec["components"][kind][name])
        return {k: deref(spec, v) for k, v in node.items() if k != "examples"}
    return [deref(spec, v) for v in node] if isinstance(node, list) else node
