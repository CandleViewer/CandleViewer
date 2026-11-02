"""#3461: the product's exchange clients take their TLS and their route from code.

Every httpx client or transport in `candleviewer/` and `cvdev/` passes `trust_env=False` and the
adapter's context (`verify=exchange_tls_context()`, `exchange/bybit/tls.py`), and no adapter module
builds a context from the environment (CPython's `create_default_context`, httpx's
`create_ssl_context`, the platform store's two loaders) or assigns a `keylog_filename`.

Limits: AST checks, so an alias or a name built at run time is not caught, as in
`test_signed_client_transport.py`.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import candleviewer
import cvdev

ROOTS = (Path(candleviewer.__file__).resolve().parent, Path(cvdev.__file__).resolve().parent)
ADAPTER = ROOTS[0] / "exchange" / "bybit"
CLIENTS = frozenset({"AsyncClient", "Client", "AsyncHTTPTransport", "HTTPTransport"})
READS_ENV = frozenset(
    {
        "create_default_context",
        "create_ssl_context",
        "load_default_certs",
        "set_default_verify_paths",
    }
)


def _name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    return node.attr if isinstance(node, ast.Attribute) else None


def _findings(source: str) -> list[str]:
    """Each httpx client built, `pinned` when it passes both keywords, and each context that
    reads the environment, `env`."""
    found = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call) and _name(node.func) in CLIENTS:
            given = {keyword.arg: keyword.value for keyword in node.keywords}
            env, verify = given.get("trust_env"), given.get("verify")
            ignores_env = isinstance(env, ast.Constant) and env.value is False
            ours = isinstance(verify, ast.Call) and _name(verify.func) == "exchange_tls_context"
            found.append("pinned" if ignores_env and ours else "unpinned")
        elif isinstance(node, ast.Call) and _name(node.func) in READS_ENV:
            found.append("env")
        elif isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Store):
            if node.attr == "keylog_filename":
                found.append("env")
    return found


@pytest.mark.parametrize(
    ("source", "found"),
    [
        ("httpx.AsyncClient()", ["unpinned"]),
        ("httpx.AsyncClient(trust_env=True, verify=exchange_tls_context())", ["unpinned"]),
        ("AsyncClient(trust_env=False, verify=True)", ["unpinned"]),
        ("httpx.AsyncHTTPTransport(verify=context)", ["unpinned"]),
        ("httpx.Client(**options)", ["unpinned"]),
        ("httpx.AsyncClient(verify=tls.exchange_tls_context(), trust_env=False)", ["pinned"]),
        ("httpx.Timeout(5.0)", []),
        ("ssl.create_default_context()", ["env"]),
        ("create_default_context(cafile=bundle)", ["env"]),
        ("httpx.create_ssl_context(verify=True, trust_env=False)", ["env"]),
        ("context.load_default_certs()", ["env"]),
        ("context.set_default_verify_paths()", ["env"]),
        ("context.keylog_filename = path", ["env"]),
        ('"""Never `create_default_context`."""\nassert context.keylog_filename is None', []),
        ("context.load_verify_locations(cafile=certifi.where())", []),
    ],
)
def test_the_scan_reads_clients_and_contexts(source: str, found: list[str]) -> None:
    assert _findings(source) == found


def test_every_exchange_client_in_the_product_takes_the_pinned_posture() -> None:
    """The product's httpx clients are the REST client's and the trade archive's (listing them
    shows the scan sees them), and a new one fails here until it is pinned. Contexts that read the
    environment are refused in every adapter module (`tls.py` among those scanned)."""
    found, adapter = {}, set()
    for root in ROOTS:
        for path in sorted(root.rglob("*.py")):
            text = path.read_text(encoding="utf-8")
            if path.parent == ADAPTER:
                adapter.add(path.name)
            elif "httpx" not in text:
                continue
            findings = _findings(text)
            if path.parent != ADAPTER:
                findings = [finding for finding in findings if finding != "env"]
            if findings:
                found[path.relative_to(root.parent).as_posix()] = findings
    assert {"archive.py", "key_ws_probe.py", "rest.py", "tls.py"} <= adapter
    assert found == {
        "candleviewer/exchange/bybit/archive.py": ["pinned"],
        "candleviewer/exchange/bybit/rest.py": ["pinned"],
    }
