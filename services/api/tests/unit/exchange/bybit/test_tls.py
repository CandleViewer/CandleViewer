"""#3461: the adapter's TLS context, and the REST and trade-archive clients that take it.

Each row clears the proxy, CA and key-log variables, sets synthetic values and builds the clients
as production does, with no transport; each negative assertion has its guard (httpx's or CPython's
default, under the same values, takes them). No socket is opened here.
"""

from __future__ import annotations

import contextlib
import re
import ssl
from pathlib import Path

import certifi
import httpx
import pytest

from candleviewer.exchange.bybit import key_ws_probe
from candleviewer.exchange.bybit.archive import BybitTradeArchive
from candleviewer.exchange.bybit.key_verify import key_verification_calls
from candleviewer.exchange.bybit.rate_limit import TokenBucketGovernor
from candleviewer.exchange.bybit.service import ExchangeBybitService
from candleviewer.exchange.bybit.tls import exchange_tls_context
from tests._signing import CREDENTIAL_ID, fake_capability
from tests.unit.exchange.bybit.test_key_ws_probe import roots
from tests.unit.exchange.bybit.test_key_ws_probe_real_socket import (
    _issue,
    assert_default_opens,
    clean_environment,
    key_log,
)

_PEM = re.compile(r"-----BEGIN CERTIFICATE-----.+?-----END CERTIFICATE-----", re.DOTALL)
#: certifi's bundle, DER, read from its file: no context is built for it.
BUNDLE = {ssl.PEM_cert_to_DER_cert(pem) for pem in _PEM.findall(Path(certifi.where()).read_text())}


def settings(context: ssl.SSLContext) -> dict[str, object]:
    """Every readable setting: each public attribute that is not a method, the ciphers, the
    loaded roots and the store's counts."""
    fields = {
        name: getattr(context, name)
        for name in dir(context)
        if not name.startswith("_") and not callable(getattr(context, name))
    }
    ciphers, store = context.get_ciphers(), context.cert_store_stats()
    return {**fields, "ciphers": ciphers, "roots": roots(context), "store": store}


def pinned(client: httpx.AsyncClient) -> ssl.SSLContext:
    """The context httpx's own transport dials with."""
    transport = client._transport
    assert isinstance(transport, httpx.AsyncHTTPTransport)
    context = transport._pool._ssl_context
    assert context is not None
    return context


def keys_logged(context: ssl.SSLContext, keys: Path) -> bool:
    """Whether `context` names a key log, or a file is at the key-log path."""
    return context.keylog_filename is not None or keys.exists()


@pytest.fixture
def every_variable(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """The issue's variables, both letter cases of each proxy name: the key-log path."""
    keys = key_log(monkeypatch, tmp_path)
    for name in ("HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy"):
        monkeypatch.setenv(name, "http://127.0.0.1:9")
    monkeypatch.setenv("SSL_CERT_FILE", str(_issue(tmp_path)[0]))
    monkeypatch.setenv("SSL_CERT_DIR", str(tmp_path))
    return keys


def test_the_exchange_context_matches_httpx_default_with_nothing_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With nothing set, every setting but the TLS floor equals httpx's default context
    (CPython's `create_default_context` on certifi's bundle), so production dials with today's
    settings. A Python whose defaults move (3.13 adds two verify flags) fails here instead of the
    builder drifting from them. The floor is pinned at TLS 1.2 whatever the platform states: one
    OpenSSL build reports its default as TLS 1.2, another leaves it at the library minimum. The
    absolutes hold whatever the defaults."""
    clean_environment(monkeypatch)
    ours = exchange_tls_context()
    fields = settings(ours)
    default = settings(httpx.create_ssl_context())
    assert {"verify_flags", "options", "minimum_version", "keylog_filename"} <= fields.keys()
    assert default.pop("minimum_version") in (
        ssl.TLSVersion.TLSv1_2,
        ssl.TLSVersion.MINIMUM_SUPPORTED,
    )
    assert fields.pop("minimum_version") == ssl.TLSVersion.TLSv1_2
    assert fields == default
    keylog: str | None = ours.keylog_filename  # typeshed says `str`; unset, it is None
    assert (ours.protocol, ours.verify_mode, ours.check_hostname, keylog) == (
        ssl.PROTOCOL_TLS_CLIENT,
        ssl.CERT_REQUIRED,
        True,
        None,
    )
    assert (ours.minimum_version, roots(ours)) == (ssl.TLSVersion.TLSv1_2, BUNDLE)


@pytest.mark.parametrize("name", ["SSL_CERT_FILE", "SSL_CERT_DIR"])
def test_the_exchange_context_takes_no_ca_variable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, name: str
) -> None:
    """Guard: httpx's default takes the variable: the throwaway root in place of the bundle, or
    a directory whose roots load only as a handshake asks, so none show."""
    clean_environment(monkeypatch)
    root, _ = _issue(tmp_path)
    monkeypatch.setenv(name, str(root if name == "SSL_CERT_FILE" else tmp_path))
    taken = {ssl.PEM_cert_to_DER_cert(root.read_text())} if name == "SSL_CERT_FILE" else set()
    assert (roots(exchange_tls_context()), roots(httpx.create_ssl_context())) == (BUNDLE, taken)


def test_the_exchange_context_opens_no_key_log(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    keys = key_log(monkeypatch, tmp_path)
    assert not keys_logged(exchange_tls_context(), keys)
    assert_default_opens(keys)


@pytest.mark.parametrize("env", ["demo", "live", "testnet"])
@pytest.mark.parametrize("kind", ["signed", "public"])
async def test_every_rest_client_takes_the_pinned_posture(
    every_variable: Path, kind: str, env: str
) -> None:
    """A signed client as key verification builds it and a public one as the adapter does, with
    no transport: no proxy mounted, httpx's own transport for its host, certifi's roots, no key
    log. Guard: httpx's default client, built under the same values, takes all three."""
    rest = (
        key_verification_calls(
            fake_capability("k"), env, CREDENTIAL_ID, uid="1", recv_window_ms=5000,
            governor=TokenBucketGovernor(), transport=None,
        )._client
        if kind == "signed"
        else ExchangeBybitService().public_rest_client(env)
    )  # fmt: skip
    client, context = rest._client, pinned(rest._client)
    route = client._transport_for_url(client.base_url)
    assert (client.trust_env, client._mounts, route) == (False, {}, client._transport)
    assert (roots(context), keys_logged(context, every_variable)) == (BUNDLE, False)
    await rest.aclose()
    async with httpx.AsyncClient() as default:
        proxied = default._transport_for_url(client.base_url) is not default._transport
        took = (
            proxied,
            roots(pinned(default)) != BUNDLE,
            keys_logged(pinned(default), every_variable),
        )
    assert took == (True, True, True)


async def test_each_rest_client_gets_its_own_context() -> None:
    """httpcore sets ALPN on the context it is given at every connect: no two REST clients share
    one, and none shares the private-WS connectors' context."""
    service = ExchangeBybitService()
    one, two = service.public_rest_client("demo"), service.public_rest_client("demo")
    contexts = {id(pinned(one._client)), id(pinned(two._client)), id(key_ws_probe._TLS)}
    await one.aclose()
    await two.aclose()
    assert len(contexts) == 3


async def test_a_socks_proxy_variable_never_reaches_the_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Guard: httpx's default client takes the variable: without SOCKS support installed it
    refuses to build, and with it, it mounts the proxy."""
    clean_environment(monkeypatch)
    monkeypatch.setenv("ALL_PROXY", "socks5://127.0.0.1:9")
    rest = ExchangeBybitService().public_rest_client("demo")
    assert rest._client._mounts == {}
    await rest.aclose()
    with contextlib.suppress(ImportError):
        async with httpx.AsyncClient() as default:
            assert default._mounts != {}


async def test_the_trade_archive_client_takes_the_pinned_posture(every_variable: Path) -> None:
    archive = BybitTradeArchive()
    client = archive._http()
    context = pinned(client)
    taken = (client.trust_env, client._mounts, roots(context), keys_logged(context, every_variable))
    assert taken == (False, {}, BUNDLE, False)
    await archive.aclose()
