"""E08-X02 (f)+(g): environment confusion and capability creep. Register F, G.

SR-040a: one client instance per environment, base URL immutable at runtime.
"The market-data path cannot trade": fails by construction, not by policy.
"""

from __future__ import annotations

import ast
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from candleviewer.exchange.base.ports import MarketDataPort, TradingPort

# nosemgrep: cv-adapter-isolation reason=X02 owner=@CandleViewer/security review=2026-12-31
from candleviewer.exchange.bybit.config import RestClientConfig

# nosemgrep: cv-adapter-isolation reason=X02 owner=@CandleViewer/security review=2026-12-31
from candleviewer.exchange.bybit.public_ws import PUBLIC_WS_URLS

# nosemgrep: cv-adapter-isolation reason=X02 owner=@CandleViewer/security review=2026-12-31
from candleviewer.exchange.bybit.rest import BybitRestClient

# nosemgrep: cv-adapter-isolation reason=X02 owner=@CandleViewer/security review=2026-12-31
from candleviewer.exchange.bybit.service import ExchangeBybitService

# nosemgrep: cv-adapter-isolation reason=X02 owner=@CandleViewer/security review=2026-12-31
from candleviewer.exchange.bybit.signer import BybitSigner
from tests._signing import CREDENTIAL_ID, fake_capability

PKG = Path(__file__).resolve().parents[3] / "candleviewer"
#: Every module on the public market-data ingestion path (ticket repo paths).
INGESTION_PATH = ("ingestion", "book", "bars", "orderflow", "recorder", "replay")
TRADING_NAMES = {"TradingPort", "signed_request", "BybitSigner", "place_order", "cancel_all"}
TRADING_PATHS = ("/v5/order/", "/v5/position/", "/v5/asset/")


class _Rec:
    def __init__(self) -> None:
        self.hosts: list[str] = []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        self.hosts.append(req.url.host)
        return httpx.Response(200, json={"retCode": 0, "result": {}})


@pytest.mark.parametrize(
    "url",
    [
        "http://api.bybit.com",
        "https://evil.example",
        "https://api.bybit.com/v5",
        "https://api.bybit.com?x=1",
    ],
)
def test_base_url_must_be_allowlisted_bare_https_origin(url: str) -> None:
    with pytest.raises(ValidationError):
        RestClientConfig(base_url=url)


def test_config_is_frozen() -> None:
    cfg = RestClientConfig(base_url="https://api.bybit.com")
    with pytest.raises(ValidationError):
        cfg.base_url = "https://api-demo.bybit.com"


async def test_relative_paths_stay_on_configured_host() -> None:
    rec = _Rec()
    async with BybitRestClient(
        RestClientConfig(base_url="https://api-demo.bybit.com"),
        transport=httpx.MockTransport(rec),
    ) as c:
        await c.get_public("/v5/market/time")
    assert rec.hosts == ["api-demo.bybit.com"]


async def test_absolute_path_cannot_escape_base_url() -> None:
    rec = _Rec()
    signer = BybitSigner(fake_capability("DUMMYKEY" + "q" * 10), CREDENTIAL_ID)
    async with BybitRestClient(
        RestClientConfig(base_url="https://api.bybit.com"),
        signer=signer,
        transport=httpx.MockTransport(rec),
    ) as c:
        for p in ("https://api-demo.bybit.com/v5/x", "//evil.example/v5/x"):
            with pytest.raises((ValueError, TypeError)):
                await c.signed_request("GET", p)
    assert rec.hosts == []


def test_public_ws_hosts_never_mix_envs() -> None:
    assert PUBLIC_WS_URLS["demo"] == PUBLIC_WS_URLS["live"]  # demo has no public WS (SR-040a)
    assert "testnet" in PUBLIC_WS_URLS["testnet"]
    assert all(u.startswith("wss://") for u in PUBLIC_WS_URLS.values())


def test_public_rest_client_is_credential_less() -> None:
    client = ExchangeBybitService.public_rest_client("demo")
    assert client._signer is None and client._config.base_url == "https://api.bybit.com"


async def test_public_client_cannot_sign() -> None:
    client = ExchangeBybitService.public_rest_client("live")
    async with client:
        with pytest.raises(TypeError):
            await client.signed_request("POST", "/v5/order/create", body={"orderLinkId": "x"})


def _imports(module_dir: Path) -> list[tuple[Path, str]]:
    found: list[tuple[Path, str]] = []
    for py in module_dir.rglob("*.py"):
        tree = ast.parse(py.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                found += [(py, f"{node.module}.{a.name}") for a in node.names]
            elif isinstance(node, ast.Import):
                found += [(py, a.name) for a in node.names]
            elif isinstance(node, ast.Attribute) and node.attr in TRADING_NAMES:
                found.append((py, node.attr))
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                if any(node.value.startswith(t) for t in TRADING_PATHS):
                    found.append((py, node.value))
    return found


@pytest.mark.parametrize("module", INGESTION_PATH)
def test_ingestion_path_cannot_reach_trading(module: str) -> None:
    bad = [
        (str(p.relative_to(PKG)), name)
        for p, name in _imports(PKG / module)
        if name.rsplit(".", 1)[-1] in TRADING_NAMES
        or ".oms" in f".{name}"
        or ".secrets" in f".{name}"
        or any(name.startswith(t) for t in TRADING_PATHS)
    ]
    assert bad == []


def test_capability_scan_detects_planted_trading_import(tmp_path: Path) -> None:
    # Planted defect: proves the scan above would fail on a real violation.
    (tmp_path / "leak.py").write_text(
        "from candleviewer.exchange.base.ports import TradingPort\n"
        "async def f(c):\n    await c.signed_request('POST', '/v5/order/create')\n",
        encoding="utf-8",
    )
    names = {n for _, n in _imports(tmp_path)}
    assert {"candleviewer.exchange.base.ports.TradingPort", "signed_request"} <= names
    assert "/v5/order/create" in names


def test_market_data_port_has_no_trading_methods() -> None:
    md = {n for n in dir(MarketDataPort) if not n.startswith("_")}
    tr = {n for n in dir(TradingPort) if not n.startswith("_")}
    assert md.isdisjoint(tr - {"capabilities"})
    assert not any(n.startswith(("place", "cancel", "amend", "set_")) for n in md)


def test_wired_ingestion_service_exposes_no_trading_capability() -> None:
    svc = ExchangeBybitService()
    exposed = {n for n in dir(svc) if not n.startswith("_")}
    assert not isinstance(svc, TradingPort)
    assert exposed.isdisjoint({"place_order", "cancel_order", "signed_request", "signer"})
