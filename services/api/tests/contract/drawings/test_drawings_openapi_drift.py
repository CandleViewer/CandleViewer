"""E14-Q04 (#431) spec-drift guard: `app.openapi()` for `/drawings*` against `22-api-openapi.yaml`.
Both sides are normalised alike (refs inlined, keys sorted; prose, examples, `operationId`, tags,
response headers and `x-` keys dropped; parameters keyed by `in:name`), so paths, methods,
parameters, schemas and response codes are compared; a failure prints the unified diff.
"""

from __future__ import annotations

import copy
import difflib
import json
from typing import Any

from _drawings_contract import SPEC

from candleviewer.app import create_app
from candleviewer.settings import Settings

_DROPPED = frozenset(
    {"description", "summary", "title", "examples", "example", "operationId", "tags", "headers"}
)
_METHODS = ("get", "put", "post", "delete", "patch")


def _inline(doc: dict[str, Any], node: Any, seen: tuple[str, ...] = (), names: bool = False) -> Any:
    """`node` with refs inlined; `names` marks a name -> schema map whose keys are data."""
    if isinstance(node, list):
        return [_inline(doc, item, seen) for item in node]
    if not isinstance(node, dict):
        return node
    ref = node.get("$ref")
    if isinstance(ref, str):
        if ref in seen:  # a recursive schema: compare the reference itself
            return {"$ref": ref.rsplit("/", 1)[-1]}
        target: Any = doc
        for part in ref.removeprefix("#/").split("/"):
            target = target[part.replace("~1", "/").replace("~0", "~")]
        return _inline(doc, target, (*seen, ref))
    return {
        key: _inline(doc, value, seen, names=key == "properties" and not names)
        for key, value in sorted(node.items())
        if names or (key not in _DROPPED and not key.startswith("x-"))
    }


def drawings_contract(doc: dict[str, Any]) -> dict[str, Any]:
    """The comparable `/drawings*` subtree of an OpenAPI document."""
    out: dict[str, Any] = {}
    for path, item in sorted(doc["paths"].items()):
        if not path.startswith("/drawings"):
            continue
        for method in (m for m in _METHODS if m in item):
            op = item[method]
            merged = _inline(doc, [*item.get("parameters", []), *op.get("parameters", [])])
            out[f"{method.upper()} {path}"] = {
                "parameters": {f"{p['in']}:{p['name']}": p for p in merged},
                "requestBody": _inline(doc, op.get("requestBody")),
                "responses": _inline(doc, op.get("responses", {})),
            }
    return out


def _diff(spec: dict[str, Any], live: dict[str, Any], live_name: str = "app.openapi()") -> str:
    a, b = (json.dumps(t, indent=1, sort_keys=True).splitlines() for t in (spec, live))
    return "\n".join(difflib.unified_diff(a, b, "22-api-openapi.yaml", live_name, n=2, lineterm=""))


def _live() -> dict[str, Any]:
    return create_app(Settings(git_sha="test", version="0.0.0-test")).openapi()


def test_the_app_serves_exactly_the_documented_drawings_paths_and_methods() -> None:
    assert sorted(drawings_contract(_live())) == sorted(drawings_contract(SPEC))


def test_generated_openapi_matches_the_contract_for_drawings() -> None:
    """Gherkin "The implementation matches the published contract"."""
    spec, live = drawings_contract(SPEC), drawings_contract(_live())
    assert live == spec, f"/drawings* drifted from the contract:\n{_diff(spec, live)}"


def test_the_guard_reports_a_moved_promise_and_ignores_prose() -> None:
    reworded = copy.deepcopy(SPEC)
    batch = reworded["paths"]["/drawings/batch"]["post"]
    batch["description"], batch["responses"]["409"]["description"] = "reworded", "reworded"
    assert drawings_contract(reworded) == drawings_contract(SPEC)  # cosmetic churn is not drift
    del batch["responses"]["413"]
    batch["requestBody"]["content"]["application/json"]["schema"] = {"type": "object"}
    diff = _diff(drawings_contract(SPEC), drawings_contract(reworded), "mutated")
    assert '-   "413": {' in diff and '"maxItems": 200' in diff, diff
