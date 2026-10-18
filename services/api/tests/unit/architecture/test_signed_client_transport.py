"""#836 slice 2b3 (L2 of the #3233 consumer review): every signed REST client gets the transport.

`ExchangeBybitService(rest_transport=...)` chooses one transport for every account REST client
(#2893 S4): none in production, the dev-only fixture's only when `CV_ACCOUNT_FIXTURE` is set. A
signed client built without it would skip that choice, and in fixture mode send a signed call
through httpx's own transport to a real host (C-2.11, C-12.2). So in every product module
(`candleviewer/`, `cvdev/`) a `BybitRestClient(...)` call that passes `signer=`, or a `**` splat
that may carry it, passes `transport=` explicitly, and the factory of the signed clients takes
`transport` as a keyword with no default.

Limits: these are AST checks, so an alias of the class or a name built at run time is not caught,
as in `test_account_rest_transport_callers.py`.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

import candleviewer
import cvdev
from candleviewer.exchange.bybit.key_verify import key_verification_calls

ROOTS = (Path(candleviewer.__file__).resolve().parent, Path(cvdev.__file__).resolve().parent)
CLIENT = "BybitRestClient"


def _name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    return node.attr if isinstance(node, ast.Attribute) else None


def _builds_client(call: ast.Call) -> bool:
    """`call` builds the client directly, through `__init__` or as the first argument
    (`functools.partial`)."""
    func = call.func
    if _name(func) == CLIENT or (call.args and _name(call.args[0]) == CLIENT):
        return True
    if isinstance(func, ast.Attribute) and func.attr == "__init__":
        return _name(func.value) == CLIENT
    return False


def _signing_builds(source: str) -> list[tuple[int, bool]]:
    """`(line, passes transport=)` for each client build that may sign: it passes `signer=` or a
    `**` splat that could carry it."""
    found = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call) and _builds_client(node):
            names = {kw.arg for kw in node.keywords}
            if None in names or "signer" in names:
                found.append((node.lineno, "transport" in names))
    return found


@pytest.mark.parametrize(
    "source",
    [
        "BybitRestClient(config, signer=signer)",
        "rest.BybitRestClient(config, uid=uid, signer=signer, governor=governor)",
        "BybitRestClient(config, **kwargs)",
        "BybitRestClient.__init__(client, config, signer=signer)",
        "functools.partial(BybitRestClient, signer=signer)",
    ],
)
def test_a_signed_client_without_the_transport_is_flagged(source: str) -> None:
    assert _signing_builds(source) == [(1, False)]


@pytest.mark.parametrize(
    "source",
    [
        "BybitRestClient(config, signer=signer, transport=transport)",
        "BybitRestClient(config, **kwargs, transport=None)",
    ],
)
def test_a_signed_client_with_the_transport_passes(source: str) -> None:
    assert _signing_builds(source) == [(1, True)]


def test_a_public_client_is_not_a_signed_build() -> None:
    assert _signing_builds("BybitRestClient(RestClientConfig(base_url=base))") == []


def test_every_signed_client_in_the_product_passes_the_transport() -> None:
    """The one signed build today is the key-verification factory's; listing it shows the scan
    sees it, and a new signed build fails until it passes the transport."""
    found = {}
    for root in ROOTS:
        for path in sorted(root.rglob("*.py")):
            text = path.read_text(encoding="utf-8")
            if CLIENT in text and (builds := _signing_builds(text)):
                found[path.relative_to(root.parent).as_posix()] = [ok for _, ok in builds]
    assert found == {"candleviewer/exchange/bybit/key_verify.py": [True]}


def test_the_signed_client_factory_takes_the_transport_with_no_default() -> None:
    transport = inspect.signature(key_verification_calls).parameters["transport"]
    assert transport.kind is inspect.Parameter.KEYWORD_ONLY
    assert transport.default is inspect.Parameter.empty
