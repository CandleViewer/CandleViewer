"""Constant validation messages (C-12.6, #4562) on every UUID path parameter of the real app.

The routes come from the mounted route table (`create_app()` through the RBAC pack's world,
identity and stores faked, no network), never from a hand list: each operation with a path
parameter typed `uuid.UUID` is called as the Owner with a non-UUID value there, and answers
`422 validation_failed` with the constant `uuid_parsing` message and no part of the value."""

from __future__ import annotations

import itertools
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute

from tests.contract.rbac.rbac_harness import World, bearer, build_world, fill_path

#: Two parser paths: a malformed value, and a valid-length value with one bad character.
_VALUES = ("S0me-NOT-Qz9k", "12345678-1234-1234-1234-12345678901Q")
_CONSTANT = "Input should be a valid UUID."


def _uuid_params(dep: Dependant) -> list[str]:
    own = [p.alias for p in dep.path_params if p.field_info.annotation is uuid.UUID]
    return own + [name for sub in dep.dependencies for name in _uuid_params(sub)]


def _routes(routes: Any, prefix: str = "") -> Iterator[tuple[str, str, list[str]]]:
    for route in routes:
        inner = getattr(route, "original_router", None)
        if inner is not None:
            ctx = getattr(getattr(route, "include_context", None), "prefix", "") or ""
            yield from _routes(inner.routes, prefix + ctx)
        elif isinstance(route, APIRoute) and (names := sorted(set(_uuid_params(route.dependant)))):
            for method in sorted((route.methods or set()) - {"HEAD"}):
                yield method, prefix + route.path, names


@pytest.fixture(scope="module")
def world() -> Iterator[World]:
    mp = pytest.MonkeyPatch()
    try:
        yield build_world(mp)
    finally:
        mp.undo()


def test_non_uuid_path_value_answers_the_constant_and_no_part_of_it(world: World) -> None:
    misses, routes = [], list(_routes(world.app.routes))
    assert len(routes) >= 30  # a walk that stops finding routes fails here, not silently
    for method, path, names in routes:
        for name, value in itertools.product(names, _VALUES):
            resp = world.client.request(
                method,
                fill_path(path, {name: value}),
                json={} if method in ("POST", "PUT", "PATCH") else None,
                headers=bearer("owner"),
            )
            body = resp.text
            entries = resp.json().get("errors", []) if resp.status_code == 422 else []
            answered = {(e["rule"], e["message"]) for e in entries if e["field"] == f"path.{name}"}
            echoed = [s for s in (value[i : i + 3] for i in range(len(value) - 2)) if s in body]
            quoted = "`S`" in body or "`Q`" in body
            if answered != {("uuid_parsing", _CONSTANT)} or echoed or quoted:
                misses.append((method, path, name, value, resp.status_code, echoed, body[:200]))
    assert misses == []
