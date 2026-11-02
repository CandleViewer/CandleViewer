"""#3461: a signed REST request on a real socket, from a client built with no transport.

The servers are the private-WS tests' (`Proxy`, `Peer`) on ephemeral 127.0.0.1 ports, and the
client reaches them through `RestClientConfig.model_construct`, which skips the host allow-list in
tests only, so no exchange host is named or resolved. Every wait is bounded.
"""

from __future__ import annotations

import asyncio
import ssl
from pathlib import Path

import httpx
import pytest

from candleviewer.exchange.base.errors import TransportError
from candleviewer.exchange.bybit.config import RestClientConfig
from candleviewer.exchange.bybit.rate_limit import TokenBucketGovernor
from candleviewer.exchange.bybit.rest import BybitRestClient
from candleviewer.exchange.bybit.signer import BybitSigner
from tests._signing import CREDENTIAL_ID, fake_capability
from tests.unit.exchange.bybit.test_key_ws_probe_real_socket import (
    Peer,
    Proxy,
    _issue,
    assert_default_opens,
    clean_environment,
    key_log,
)

_DEADLINE_S = 10.0


async def signed_get(base: str) -> TransportError:
    """One signed GET on a client for `base` with no transport; the transport error it raises."""
    config = RestClientConfig.model_construct(base_url=base, max_retries=0)
    signer = BybitSigner(fake_capability("k"), CREDENTIAL_ID)
    rest = BybitRestClient(config, signer=signer, governor=TokenBucketGovernor())
    try:
        with pytest.raises(TransportError) as raised:
            await rest.signed_request("GET", "/v5/account/wallet-balance", lane="poll")
    finally:
        await rest.aclose()
    return raised.value


def on_the_certificate(error: BaseException | None) -> bool:
    """Whether `error` came from the handshake's check of the server's certificate."""
    while error is not None and not isinstance(error, ssl.SSLCertVerificationError):
        error = error.__cause__ or error.__context__
    return error is not None


def https(url: str) -> str:
    """The `https://` origin of a peer's or a proxy's 127.0.0.1 URL."""
    return "https://" + url.split("://", 1)[1].split("/", 1)[0]


@pytest.mark.parametrize("name", ["HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy"])
async def test_a_proxy_the_environment_names_never_carries_a_signed_request(
    monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    """The signed request goes to the host's own port, and the proxy sees no connection. Guard:
    httpx's default client sends the same URL through that proxy."""
    clean_environment(monkeypatch)
    proxy, host = Proxy(), Proxy()  # each counts the connections it gets, and drops them
    async with asyncio.timeout(_DEADLINE_S), proxy.listening() as via, host.listening() as own:
        monkeypatch.setenv(name, via)
        await signed_get(https(own))
        assert (proxy.asked, host.asked) == (0, 1)
        async with httpx.AsyncClient() as default:
            with pytest.raises(httpx.TransportError):
                await default.get(https(own))
    assert (proxy.asked, host.asked) == (1, 1)


async def test_a_root_ssl_cert_file_names_never_sees_a_signed_request(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The handshake fails on the server's certificate, which certifi's bundle does not hold, and
    the server reads no request. Guard: httpx's default context, under the same value, sends one."""
    clean_environment(monkeypatch)
    root, served = _issue(tmp_path)
    monkeypatch.setenv("SSL_CERT_FILE", str(root))
    peer = Peer()
    async with asyncio.timeout(_DEADLINE_S), peer.serving(served) as url:
        assert on_the_certificate(await signed_get(https(url)))
        assert peer.handshakes == 0
        async with httpx.AsyncClient(verify=httpx.create_ssl_context(), trust_env=False) as default:
            await default.get(url.replace("wss://", "https://"))
    assert peer.handshakes == 1


async def test_a_signed_request_writes_no_key_log(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A signed request whose TLS handshake reaches the server's certificate, under
    `SSLKEYLOGFILE`, leaves no file at its path."""
    keys = key_log(monkeypatch, tmp_path)
    _, served = _issue(tmp_path)
    peer = Peer()
    async with asyncio.timeout(_DEADLINE_S), peer.serving(served) as url:
        assert on_the_certificate(await signed_get(https(url)))
    assert (peer.handshakes, keys.exists()) == (0, False)
    assert_default_opens(keys)
