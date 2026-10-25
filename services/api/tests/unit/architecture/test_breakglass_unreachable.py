"""S8 (E09-S11 #2119, SR-023, threat model Sec.3.6.1): no network path reaches break-glass.

The offline CLI, `python -m candleviewer.breakglass` (decision R5), is a trust boundary of its
own: it runs on the host, with the KEK, while cv-api is stopped. Nothing cv-api serves leads to it:

- no HTTP or WS route is named for it or served by one of its modules, no WS topic is named for
  it, and no path or operation of the OpenAPI contract, or of the subset `create_app()` serves, is;
- neither the API (`candleviewer.api`), the WS gateway (`candleviewer.ws`), the composition root
  (`app`, `main`) nor the server entry point (`server`) imports one of its modules, directly or
  through any chain (read with grimp, the graph `lint-imports` checks; function-level and
  `TYPE_CHECKING` imports included, and the `__init__` of each package a chain enters), or holds
  one's dotted name for `importlib` to load.

The bootstrap-Owner mint (#4479) shares that boundary: its service and store are dark too, so
cv-api never holds a writer that can mint an Owner invite (C2 adds its entry point and flow).

A route or topic that must be named for break-glass is a Sec.3.6.1 review first, then a change here.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import grimp
import pytest

import candleviewer
from candleviewer.api.contract_conformance import load_contract_subset, load_openapi_spec
from candleviewer.app import create_app
from candleviewer.ws.topics import TOPIC_REGISTRY

#: The CLI's modules: its entry point, flow, port composition and Postgres side; and the
#: bootstrap-Owner mint's service and store (#4479 C1).
DARK = (
    "candleviewer.breakglass",
    "candleviewer.admin.breakglass",
    "candleviewer.admin.breakglass_wiring",
    "candleviewer.storage.repositories.break_glass_cli_sqlalchemy",
    "candleviewer.auth.bootstrap_owner",
    "candleviewer.storage.repositories.bootstrap_owner_sqlalchemy",
)
#: What cv-api serves and boots from.
SERVED = (
    "candleviewer.api",
    "candleviewer.ws",
    "candleviewer.app",
    "candleviewer.main",
    "candleviewer.server",
)
_NAMED = re.compile(r"break[-_ ]?glass", re.IGNORECASE)
_PKG = Path(candleviewer.__file__).resolve().parent


def _routes(routes: Any, prefix: str = "") -> Iterator[tuple[str, str]]:
    """(path, endpoint module) of every HTTP and WS route, through included and mounted ones."""
    for route in routes:
        inner = getattr(route, "original_router", None)
        if inner is not None:
            context = getattr(route, "include_context", None)
            yield from _routes(inner.routes, prefix + (getattr(context, "prefix", "") or ""))
            continue
        mounted = getattr(route, "routes", None)
        if mounted is not None:
            yield from _routes(mounted, prefix + route.path)
            continue
        yield prefix + route.path, getattr(getattr(route, "endpoint", None), "__module__", "")


def _operations(spec: dict[str, Any]) -> Iterator[str]:
    """Each path, and each `METHOD path operationId` under it."""
    for path, item in spec["paths"].items():
        yield path
        for method, operation in item.items():
            if isinstance(operation, dict):
                yield f"{method.upper()} {path} {operation.get('operationId', '')}"


def test_no_route_topic_or_openapi_path() -> None:
    routes = list(_routes(create_app().routes))
    assert ("/ws", "candleviewer.ws.gateway") in routes  # the walk reaches the WS route too
    assert [r for r in routes if _NAMED.search(r[0]) or r[1].startswith(DARK)] == []
    topics = [pattern for pattern, _permission in TOPIC_REGISTRY]
    assert "system" in topics and [t for t in topics if _NAMED.search(t)] == []
    for spec in (load_openapi_spec(), load_contract_subset()):
        operations = list(_operations(spec))
        assert "/auth/login" in operations  # the contract was read
        assert [op for op in operations if _NAMED.search(op)] == []


@pytest.fixture(scope="module")
def graph() -> grimp.ImportGraph:
    return grimp.build_graph("candleviewer", cache_dir=None)


def test_unreachable_from_api_ws_imports(graph: grimp.ImportGraph) -> None:
    # The CLI's own edge exists, so a graph that sees no import at all cannot pass.
    assert graph.find_shortest_chain("candleviewer.breakglass", "candleviewer.admin.breakglass")
    chains = {
        (served, dark): graph.find_shortest_chain(served, dark, as_packages=True)
        for served in SERVED
        for dark in DARK
    }
    assert {pair: chain for pair, chain in chains.items() if chain is not None} == {}
    sources = [*(_PKG / "api").rglob("*.py"), *(_PKG / "ws").rglob("*.py")]
    sources += [_PKG / f"{name}.py" for name in ("app", "main", "server")]
    named = [str(path) for path in sources if any(d in path.read_text("utf-8") for d in DARK)]
    assert named == []


def _runs_with(graph: grimp.ImportGraph, todo: list[str]) -> set[str]:
    """Every module that runs when `todo`'s are imported: what they import, transitively, and the
    `__init__` of each package above one, which runs first (an edge grimp does not draw)."""
    seen: set[str] = set()
    while todo:
        module = todo.pop()
        if module not in seen:
            seen.add(module)
            todo += graph.find_modules_directly_imported_by(module)
            todo += [module.rsplit(".", n)[0] for n in range(1, module.count(".") + 1)]
    return seen


def test_unreachable_through_a_package_init(graph: grimp.ImportGraph) -> None:
    """An import in a package's `__init__` (`from candleviewer.auth import bootstrap_owner`) runs
    with every module under it, yet draws no chain above: nothing imports the bare package."""
    served = [module for name in SERVED for module in (name, *graph.find_descendants(name))]
    reached = _runs_with(graph, served)
    assert "candleviewer.auth" in reached  # the walk climbs to the packages
    assert sorted(reached.intersection(DARK)) == []
