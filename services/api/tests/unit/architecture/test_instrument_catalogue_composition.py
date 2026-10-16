"""#2561 composition guard: the deployed `create_app()` (no injected seams) attaches the E08-S01-2
instrument catalogue on the real backend whenever the app talks to the exchange (`CV_FEED=live`,
or the public WS behind `ingestion_ws_enabled`, which admits only catalogue symbols), and never in
the dev and CI defaults, which make no exchange call (C-13.5). Building the app opens no connection
and starts nothing. A smoke test then serves a catalogue seeded from the recorded instruments-info
page through the deployed `/instruments` routes and their session resolver: no Postgres and no
network, because the fetch, the SQL edges and the bus publish are faked."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from pydantic import SecretStr

import candleviewer.app as appmod
from candleviewer.exchange.base.instruments import InstrumentsFetchResult
from candleviewer.exchange.bybit.instruments import parse_instruments
from candleviewer.exchange.bybit.service import ExchangeBybitService
from candleviewer.ingestion.instruments_refresh import InstrumentsRefreshScheduler
from candleviewer.settings import FeedMode, Settings
from candleviewer.storage.repositories.instruments_sqlalchemy import (
    SqlAlchemyInstrumentsRepository,
)
from candleviewer.storage.repositories.relational_sqlalchemy import SqlAlchemyRelationalRepository
from tests._corpus import rest
from tests.contract.rbac.rbac_harness import bearer, build_world

_REAL: dict[str, Any] = {
    "storage_backend": "real",
    "auth_pepper": SecretStr("test-pepper"),
    "auth_totp_key_hex": SecretStr("11" * 32),
    "auth_recovery_hmac_key_hex": SecretStr("22" * 32),
    "auth_csrf_key_hex": SecretStr("33" * 32),
}
#: `CV_FEED=live` refuses to start without both (fake values: nothing is ever signed here).
_LIVE: dict[str, Any] = {
    "feed": FeedMode.LIVE,
    "bybit_api_key": SecretStr("test-key"),
    "bybit_api_secret": SecretStr("test-secret"),
}


@pytest.mark.parametrize(
    ("overrides", "attached"),
    [
        pytest.param({}, False, id="dev-defaults"),
        pytest.param(_LIVE, True, id="live-feed"),
        pytest.param({"ingestion_ws_enabled": True}, True, id="public-ws"),
        pytest.param({**_LIVE, "ingestion_ws_enabled": True}, True, id="live-feed-and-public-ws"),
        pytest.param({**_LIVE, "storage_backend": "fake"}, False, id="fake-backend-live"),
        pytest.param(
            {"storage_backend": "fake", "ingestion_ws_enabled": True}, False, id="fake-backend-ws"
        ),
    ],
)
def test_deployed_app_attaches_the_catalogue_when_it_talks_to_the_exchange(
    overrides: dict[str, Any], attached: bool
) -> None:
    ingestion = appmod.create_app(Settings(**{**_REAL, **overrides})).state.app_context.ingestion
    assert isinstance(ingestion.instruments, InstrumentsRefreshScheduler) is attached
    # Its pool is released when ingestion stops. #2599: it shares the public WS's REST client
    # (one governor, C-12.7), so there is one client whenever either talks to the exchange.
    closers = [getattr(close, "__qualname__", "") for close in ingestion._closers]
    public_ws = bool(overrides.get("ingestion_ws_enabled"))
    assert closers.count("SqlAlchemyRelationalRepository.dispose") == int(attached)
    assert closers.count("BybitRestClient.aclose") == int(attached or public_ws)


def test_live_feed_and_public_ws_share_one_public_rest_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#2599: with `CV_FEED=live` and the public WS together, the catalogue and the public WS
    (clock probe, klines, recent trades) use one credential-less REST client, so one
    token-bucket governor (C-12.7): the app builds exactly one and closes it exactly once."""
    built: list[Any] = []
    real = ExchangeBybitService.public_rest_client

    def _counting(env: str) -> Any:
        built.append(real(env))
        return built[-1]

    monkeypatch.setattr(ExchangeBybitService, "public_rest_client", staticmethod(_counting))
    settings = Settings(**{**_REAL, **_LIVE, "ingestion_ws_enabled": True})
    ingestion = appmod.create_app(settings).state.app_context.ingestion
    assert isinstance(ingestion.instruments, InstrumentsRefreshScheduler)
    assert ingestion.clock is not None  # the public WS's clock probe is wired too
    assert len(built) == 1
    closed = [
        getattr(close, "__self__", None)
        for close in ingestion._closers
        if getattr(close, "__qualname__", "") == "BybitRestClient.aclose"
    ]
    assert closed == built


def _recorded_page(_now_us: Callable[[], int]) -> Awaitable[InstrumentsFetchResult]:
    """The adapter's parser over the recorded 2026-10-05 instruments-info page (C-13.5)."""

    async def _fetch() -> InstrumentsFetchResult:
        items = rest("rest/instruments_before.json")["result"]["list"]
        return parse_instruments(items, fetched_at_us=_now_us())

    return _fetch()


async def _nothing(*_args: Any, **_kwargs: Any) -> None:
    return None


def test_deployed_instruments_routes_serve_a_seeded_catalogue() -> None:
    """Once a catalogue is attached and seeded, the deployed routes answer 200 to a caller with
    `instruments:read` (the RBAC matrix covers every actor), never the 503 or 501 fallback."""
    mp = pytest.MonkeyPatch()
    try:
        world = build_world(mp)
        ctx = world.app.state.app_context
        for edge in ("record_version", "upsert_snapshot"):
            mp.setattr(SqlAlchemyInstrumentsRepository, edge, _nothing)
        mp.setattr(ctx.bus.bus, "publish", _nothing)
        scheduler = appmod.wire_instrument_catalogue(
            ctx,
            fetch_instruments=_recorded_page,
            relational=SqlAlchemyRelationalRepository("postgresql+asyncpg://u@localhost/x", "t"),
        )
        asyncio.run(scheduler.refresh_now())
        listed = world.client.get("/instruments", headers=bearer("viewer"))
        one = world.client.get("/instruments/BTCUSDT", headers=bearer("viewer"))
        anonymous = world.client.get("/instruments", headers=bearer("unauthenticated"))
    finally:
        mp.undo()
    assert listed.status_code == 200, listed.text
    symbols = [item["symbol"] for item in listed.json()["items"]]
    assert symbols == ["BTCUSDT", "ETHUSDT", "LUNAUSDT", "SOLUSDT"]
    assert (one.status_code, one.json()["symbol"]) == (200, "BTCUSDT")
    assert anonymous.status_code == 401
    assert appmod._catalogue_listed(ctx, "BTCUSDT") is True
