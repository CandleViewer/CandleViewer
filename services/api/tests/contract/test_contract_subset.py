"""#2555 / #2551: the packaged contract subset `create_app()` reads instead of the YAML.

The API image ships no `docs/plan`, so deny-by-default reads
`candleviewer/api/_generated/contract_subset.json`, and the raw-body routers publish their
OpenAPI from it. These tests pin that the artifact is fresh, declares exactly the contract's
operations, is a faithful pruned copy of the YAML whose published part is valid OpenAPI, and
that the app builds from a copy of the package with no repository around it.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from importlib.resources import files
from pathlib import Path
from typing import Any

import pytest

import candleviewer
from candleviewer.api import contract_conformance as cc
from candleviewer.api.deny_by_default import declared_operations
from candleviewer.api.rbac_conformance import find_undeclared_routes, spec_permission_codes

_REGENERATE = "cd services/api && uv run python scripts/generate_protocol_models.py"
_RBAC = {"permissions": ["orders:read"], "scope": "account"}
_DRAWINGS = {"get": {"x-rbac": _RBAC, "responses": {"200": {"$ref": "#/components/responses/Ok"}}}}
#: A small contract: one ordinary path (path-level parameter, two operations), one raw-body
#: path, one malformed path item, and a component only the ordinary path references.
_SPEC: dict[str, object] = {
    "paths": {
        "/orders/{id}": {
            "parameters": [{"$ref": "#/components/parameters/Id"}],
            "get": {"x-rbac": _RBAC, "summary": "list", "responses": {}},
            "post": {"security": [], "requestBody": {"$ref": "#/components/requestBodies/B"}},
        },
        "/drawings": _DRAWINGS,
        "/broken": None,
    },
    "components": {
        "parameters": {"Id": {"name": "id", "in": "path", "required": True}},
        "responses": {"Ok": {"description": "ok"}},
    },
}


@pytest.fixture(scope="module")
def spec() -> dict[str, Any]:
    return cc.load_openapi_spec()


@pytest.fixture(scope="module")
def subset() -> dict[str, Any]:
    return cc.load_contract_subset()


def _operations(doc: dict[str, Any]) -> set[tuple[str, str]]:
    return {(p, m) for p, item in doc["paths"].items() for m in item if m in cc._HTTP_METHODS}


def _not_pruned_from(kept: Any, source: Any, where: str = "") -> list[str]:
    """Locations where `kept` is not `source` with some object keys removed."""
    if isinstance(kept, dict) and isinstance(source, dict):
        return [
            bad
            for key, value in kept.items()
            for bad in (
                _not_pruned_from(value, source[key], f"{where}/{key}")
                if key in source
                else [f"{where}/{key}"]
            )
        ]
    return [] if kept == source else [where or "/"]


def test_the_packaged_subset_is_fresh() -> None:
    """The committed artifact is what the generator renders from the committed YAML."""
    packaged = files(cc.CONTRACT_SUBSET_PACKAGE).joinpath(cc.CONTRACT_SUBSET_RESOURCE)
    rendered = cc.render_contract_subset(cc._checkout_spec_path().read_bytes())
    assert packaged.read_text(encoding="utf-8") == rendered, f"stale; run `{_REGENERATE}`"


def test_render_contract_subset_ignores_crlf_and_writes_the_header_first() -> None:
    source = cc._checkout_spec_path().read_bytes()
    text = cc.render_contract_subset(source)
    assert text == cc.render_contract_subset(source.replace(b"\n", b"\r\n"))
    assert text.endswith("}\n") and not text.endswith("\n\n")
    document = json.loads(text)
    assert list(document) == ["x-cv-generated", "components", "paths"]
    assert document["x-cv-generated"]["source"] == "docs/plan/22-api-openapi.yaml"
    assert "DO NOT EDIT BY HAND" in document["x-cv-generated"]["notice"]
    # #2743: no digest of the YAML. It would change with every contract PR, so any two
    # would conflict on it; freshness is checked by rendering again instead.
    assert set(document["x-cv-generated"]) == {"notice", "source"}


def test_the_subset_declares_exactly_the_contract_operations(
    spec: dict[str, Any], subset: dict[str, Any]
) -> None:
    """Deny-by-default reads the subset at runtime, so it must see the YAML's declarations."""
    assert _operations(subset) == _operations(spec)
    assert declared_operations(subset) == declared_operations(spec)
    assert find_undeclared_routes(subset) == find_undeclared_routes(spec) == []
    assert spec_permission_codes(subset) == spec_permission_codes(spec)


def test_the_subset_is_a_pruned_copy_of_the_contract(
    spec: dict[str, Any], subset: dict[str, Any]
) -> None:
    body = {key: value for key, value in subset.items() if key != "x-cv-generated"}
    assert _not_pruned_from(body, spec) == []


def test_raw_body_paths_keep_their_full_contract_path_items(
    spec: dict[str, Any], subset: dict[str, Any]
) -> None:
    raw = sorted(path for path in spec["paths"] if cc.under_raw_body_prefix(path))
    assert raw, f"no path under {cc.RAW_BODY_PREFIXES} in the contract"
    for path in raw:
        assert subset["paths"][path] == spec["paths"][path], path
    cut = next(path for path in subset["paths"] if not cc.under_raw_body_prefix(path))
    assert all(set(op) <= {"security", "x-rbac"} for op in subset["paths"][cut].values())


def test_the_published_part_is_valid_openapi_and_needs_no_other_component(
    spec: dict[str, Any], subset: dict[str, Any]
) -> None:
    published = {p: item for p, item in subset["paths"].items() if cc.under_raw_body_prefix(p)}
    needed = cc.component_closure(subset["components"], list(published.values()))
    assert needed == subset["components"]
    cc.assert_spec_is_valid(
        {
            "openapi": spec["openapi"],
            "info": {"title": "raw-body routers", "version": "subset"},
            "paths": published,
            "components": subset["components"],
        }
    )


def test_build_contract_subset_cuts_operations_to_their_rbac_keys() -> None:
    paths = cc.build_contract_subset(_SPEC)["paths"]
    assert isinstance(paths, dict)
    assert paths["/orders/{id}"] == {"get": {"x-rbac": _RBAC}, "post": {"security": []}}


def test_build_contract_subset_keeps_raw_body_path_items_whole() -> None:
    paths = cc.build_contract_subset(_SPEC)["paths"]
    assert isinstance(paths, dict)
    assert paths["/drawings"] == _DRAWINGS


def test_build_contract_subset_takes_components_from_raw_body_paths_only() -> None:
    components = cc.build_contract_subset(_SPEC)["components"]
    assert components == {"responses": {"Ok": {"description": "ok"}}}


def test_build_contract_subset_skips_a_malformed_path_item() -> None:
    paths = cc.build_contract_subset(_SPEC)["paths"]
    assert isinstance(paths, dict)
    assert "/broken" not in paths


@pytest.mark.parametrize(
    "spec_",
    [{}, {"paths": []}, {"paths": {}, "components": []}],
    ids=["no-paths", "paths-not-an-object", "components-not-an-object"],
)
def test_build_contract_subset_refuses_a_malformed_contract(spec_: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="`paths` object"):
        cc.build_contract_subset(spec_)


def test_component_closure_follows_refs_mappings_and_cycles() -> None:
    components = {
        "schemas": {
            "Node": {"properties": {"next": {"$ref": "#/components/schemas/Node"}}},
            "Shape": {
                "oneOf": [{"$ref": "#/components/schemas/Circle"}],
                "discriminator": {"mapping": {"square": "#/components/schemas/Square"}},
            },
            "Circle": {"type": "object"},
            "Square": {"properties": {"side": {"$ref": "#/components/schemas/Length"}}},
            "Length": {"type": "number"},
            "Unused": {"type": "string"},
            "a/b": {"type": "boolean"},
        },
        "responses": {
            "Gone": {"content": {"x": {"schema": {"$ref": "#/components/schemas/Node"}}}}
        },
    }
    roots = [
        {"$ref": "#/components/responses/Gone"},
        {"$ref": "#/components/schemas/Shape"},
        {"$ref": "#/components/schemas/a~1b"},
    ]
    closure = cc.component_closure(components, roots)
    assert sorted(closure["schemas"]) == ["Circle", "Length", "Node", "Shape", "Square", "a/b"]
    assert closure["responses"] == {"Gone": components["responses"]["Gone"]}


@pytest.mark.parametrize(
    ("ref", "message"),
    [
        ("#/components/schemas/Missing", "dangling"),
        ("#/components/nothing/Missing", "dangling"),
        ("other.yaml#/components/schemas/Circle", "unsupported"),
        ("#/components/schemas/Circle/properties/r", "unsupported"),
        ("#/components/schemas", "unsupported"),
    ],
)
def test_component_closure_refuses_what_it_cannot_publish(ref: str, message: str) -> None:
    components = {"schemas": {"Circle": {"type": "object"}}}
    with pytest.raises(ValueError, match=message):
        cc.component_closure(components, {"$ref": ref})


def test_raw_body_prefixes_match_whole_segments() -> None:
    assert cc.under_raw_body_prefix("/drawings") and cc.under_raw_body_prefix("/drawings/batch")
    assert cc.under_raw_body_prefix("/workspaces/{workspaceId}/layouts")
    assert cc.under_raw_body_prefix("/layout-presets")
    assert not cc.under_raw_body_prefix("/drawingsx")
    assert not cc.under_raw_body_prefix("/layout-presets-v2")


def test_the_yaml_path_is_resolved_on_use_not_at_import() -> None:
    assert "OPENAPI_SPEC_PATH" not in vars(cc)
    assert cc.OPENAPI_SPEC_PATH.is_file()  # resolved by the module `__getattr__`
    with pytest.raises(AttributeError, match="NO_SUCH_NAME"):
        getattr(cc, "NO_SUCH_NAME")  # noqa: B009 — mypy rejects the unknown attribute (#2555)


def test_the_image_layout_has_no_checkout_to_read() -> None:
    """In the image the module is `/app/candleviewer/api/contract_conformance.py`: `main`'s
    `parents[4]` raised `IndexError` there; the lookup now says why it cannot answer."""
    with pytest.raises(FileNotFoundError, match="not inside a repository checkout"):
        cc._checkout_spec_path(Path("/app/candleviewer/api/contract_conformance.py"))


def test_load_openapi_spec_reads_an_explicit_path(tmp_path: Path) -> None:
    spec_file = tmp_path / "spec.yaml"
    spec_file.write_text("openapi: 3.1.0\npaths: {}\n", encoding="utf-8")
    assert cc.load_openapi_spec(spec_file) == {"openapi": "3.1.0", "paths": {}}


def test_create_app_builds_from_a_package_copy_without_a_checkout(
    tmp_path: Path, spec: dict[str, Any]
) -> None:
    """#2555 regression. The image ships the package without `docs/plan`. On `main` this probe
    failed: `create_app()` read the YAML at `parents[4]` of the module, which here is a
    directory with no `docs/plan` (and in the image, no directory at all). PyYAML and
    openapi-spec-validator are blocked: the boot path must need neither (#2616)."""
    app_root = tmp_path / "app"
    package = Path(candleviewer.__file__).resolve().parent
    ignore = shutil.ignore_patterns("__pycache__")
    shutil.copytree(package, app_root / "candleviewer", ignore=ignore)
    probe = (
        "import sys; sys.modules.update(yaml=None, openapi_spec_validator=None); "
        "sys.path.insert(0, sys.argv[1]); import candleviewer.app as a; "
        "assert a.__file__.startswith(sys.argv[1]), a.__file__; "
        "from candleviewer.api.deny_by_default import declared_operations as d; "
        "a.create_app(); print('declared', len(d(a._cached_spec())))"
    )
    result = subprocess.run(  # noqa: S603 — fixed argv: this interpreter, isolated (#2555)
        [sys.executable, "-I", "-c", probe, str(app_root)],
        cwd=tmp_path,
        env={"PATH": os.environ.get("PATH", os.defpath)},
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert result.returncode == 0, result.stderr[-4000:]
    assert f"declared {len(declared_operations(spec))}" in result.stdout.splitlines()
