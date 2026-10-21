"""OM-D08 (G-8, #2877, ruling R5): every REST client draws on the process's one governor.

`BybitRestClient` takes `governor=` as a keyword with no default, and in every product module
(`candleviewer/`, `cvdev/`) each build passes it by name. The governor itself is built in one
place only, the adapter service, once per process; key verification draws through a capped
view of it. AST checks, so an alias or a name built at run time is not caught, as in
`test_signed_client_transport.py`.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

import candleviewer
import cvdev
from candleviewer.exchange.bybit.rest import BybitRestClient

ROOTS = (Path(candleviewer.__file__).resolve().parent, Path(cvdev.__file__).resolve().parent)


def _name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    return node.attr if isinstance(node, ast.Attribute) else None


def _builds(source: str, cls: str) -> list[tuple[int, bool]]:
    """`(line, names governor=)` for each call that builds `cls`."""
    found = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call) and _name(node.func) == cls:
            names = {kw.arg for kw in node.keywords}
            found.append((node.lineno, "governor" in names))
    return found


def _product(cls: str) -> dict[str, list[bool]]:
    found: dict[str, list[bool]] = {}
    for root in ROOTS:
        for path in sorted(root.rglob("*.py")):
            text = path.read_text(encoding="utf-8")
            if cls in text and (builds := _builds(text, cls)):
                found[path.relative_to(root.parent).as_posix()] = [ok for _, ok in builds]
    return found


def test_the_client_takes_the_governor_by_keyword_with_no_default() -> None:
    governor = inspect.signature(BybitRestClient).parameters["governor"]
    assert governor.kind is inspect.Parameter.KEYWORD_ONLY
    assert governor.default is inspect.Parameter.empty


def test_every_client_built_in_the_product_is_given_the_governor() -> None:
    builds = _product("BybitRestClient")
    assert builds and all(all(flags) for flags in builds.values()), builds


def test_the_governor_is_built_once_in_the_product_by_the_service() -> None:
    assert _product("TokenBucketGovernor") == {
        "candleviewer/exchange/bybit/service.py": [False],
    }


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("BybitRestClient(config)", [(1, False)]),
        ("rest.BybitRestClient(config, uid=uid, signer=signer)", [(1, False)]),
        ("BybitRestClient(config, governor=governor)", [(1, True)]),
    ],
)
def test_the_scan_sees_a_build_with_and_without_the_governor(
    source: str, expected: list[tuple[int, bool]]
) -> None:
    assert _builds(source, "BybitRestClient") == expected
