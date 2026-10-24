"""The generated REST models set against the contract they came from (#906 slice G2a): the models a
request body reaches, each paired with its contract schema, and what each side answers to one
value. A support module (no `test_` prefix): pytest collects nothing from it."""

from __future__ import annotations

import json
import re
import typing
from collections.abc import Iterator
from functools import cache
from typing import Any

from jsonschema import Draft202012Validator
from pydantic import BaseModel, RootModel, ValidationError
from referencing import Registry
from referencing.jsonschema import DRAFT202012

from candleviewer.api._generated import openapi_models as api
from candleviewer.api.contract_conformance import load_openapi_spec

SPEC: dict[str, Any] = load_openapi_spec()  # a parsed YAML document, walked untyped
_URI = "urn:cv:22-api-openapi"
_REGISTRY: Registry[Any] = Registry().with_resource(_URI, DRAFT202012.create_resource(SPEC))
_SCHEMAS = "/components/schemas/"


def _at(pointer: str) -> Any:
    """The node of the contract at a JSON pointer (`$ref` not followed)."""
    node: Any = SPEC
    for part in pointer.split("/")[1:]:
        node = node[int(part) if isinstance(node, list) else part]
    return node


def _deref(pointer: str) -> str:
    """Where a `$ref` chain ends: the pointer of the schema itself."""
    node = _at(pointer)
    return _deref(node["$ref"].removeprefix("#")) if "$ref" in node else pointer


def _members(pointer: str) -> dict[str, str]:
    """An object schema's members: wire name to the pointer of its schema (`allOf` merged)."""
    pointer = _deref(pointer)
    found: dict[str, str] = {}
    for i in range(len(_at(pointer).get("allOf", ()))):
        found |= _members(f"{pointer}/allOf/{i}")
    return found | {n: f"{pointer}/properties/{n}" for n in _at(pointer).get("properties", ())}


def _objects(pointer: str) -> Iterator[str]:
    """The object schemas a schema holds: itself, and those of its items, values and variants."""
    pointer = _deref(pointer)
    node = _at(pointer)
    if node.get("type") == "object" or _members(pointer):
        yield pointer
    for key in ("items", "additionalProperties"):
        if isinstance(node.get(key), dict):
            yield from _objects(f"{pointer}/{key}")
    for key in ("oneOf", "anyOf"):
        for i in range(len(node.get(key, ()))):
            yield from _objects(f"{pointer}/{key}/{i}")


def _models_in(annotation: object) -> Iterator[type[BaseModel]]:
    """The generated models an annotation names, through `Annotated`, unions, lists and dicts."""
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        yield annotation
    for arg in typing.get_args(annotation):
        yield from _models_in(arg)


def _request_roots() -> set[str]:
    """The components a request body names, directly or from inside an inline body."""
    found: set[str] = set()
    for item in SPEC["paths"].values():
        for operation in item.values():
            body = operation.get("requestBody") if isinstance(operation, dict) else None
            body = _at(body["$ref"].removeprefix("#")) if body and "$ref" in body else body
            found |= set(re.findall(r'"\$ref": "#/components/schemas/([^"]+)"', json.dumps(body)))
    return found


def _walk() -> tuple[dict[type[BaseModel], dict[str, str]], set[type[BaseModel]]]:
    """Walks every request body's models, member by member, beside the contract's schemas. A model
    pairs with the object schema its parent's member holds that has exactly its member names."""
    paired: dict[type[BaseModel], dict[str, str]] = {}
    seen: set[type[BaseModel]] = set()

    def visit(annotation: object, pointer: str) -> None:
        for model in _models_in(annotation):
            if model in seen:
                continue
            seen.add(model)
            if issubclass(model, RootModel):  # a wrapper: what it holds pairs where it sits
                visit(model.model_fields["root"].annotation, pointer)
                continue
            wire = {field.alias or name: name for name, field in model.model_fields.items()}
            for found in _objects(pointer):
                if set(_members(found)) == set(wire):
                    paired[model] = {wire[w]: ptr for w, ptr in _members(found).items()}
                    for name, field in model.model_fields.items():
                        visit(field.annotation, paired[model][name])
                    break

    for name in sorted(_request_roots()):
        if isinstance(root := getattr(api, name, None), type) and issubclass(root, BaseModel):
            visit(root, _SCHEMAS + name)
    return paired, {m for m in seen if not issubclass(m, RootModel)} - set(paired)


#: Every generated model a request body reaches, with the contract pointer of each member's schema;
#: and those reached that no schema of the contract fits.
REQUEST_MODELS, UNPAIRED = _walk()


def scalar_members(model: type[BaseModel]) -> dict[str, str]:
    """A paired model's boolean, integer and number members (or those and `null`) that no `enum`
    or `const` narrows: name to the pointer of the member's schema."""
    found: dict[str, str] = {}
    for name, pointer in REQUEST_MODELS[model].items():
        node = _at(_deref(pointer))
        kinds = {node["type"]} if isinstance(node.get("type"), str) else set(node.get("type", ()))
        if kinds - {"null"} in ({"boolean"}, {"integer"}, {"number"}):
            if not {"enum", "const"} & set(node):
                found[name] = pointer
    return found


@cache
def _validator(pointer: str) -> Draft202012Validator:
    return Draft202012Validator({"$ref": f"{_URI}#{pointer}"}, registry=_REGISTRY)


def contract_accepts(pointer: str, value: object) -> bool:
    """Whether the contract's schema at `pointer` accepts `value` (JSON Schema 2020-12)."""
    return _validator(pointer).is_valid(value)


def model_accepts(model: type[BaseModel], name: str, value: object) -> bool:
    """Whether the generated `model` takes `value` for its member `name`, the rest of it aside."""
    try:
        model.__pydantic_validator__.validate_assignment(model.model_construct(), name, value)
    except ValidationError:
        return False
    return True
